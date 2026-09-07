"""Phase 0 acceptance checks. Run from any directory with the project venv.

python brain/check_phase0.py --delay 3
python brain/check_phase0.py --delay 60
Outputs evidence to recordings/phase0-<timestamp>/; no learned weights downloaded.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import copy
import json
import math
from pathlib import Path
import socket
import subprocess
import sys
import time

import cv2
import numpy as np
import yaml

from contract import EXAMPLE_OBSERVATION, validate_action, validate_telemetry
from perception import Observation, Perceiver, Tracker

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def camera_check(out: Path) -> dict:
    cfg = yaml.safe_load((HERE / "brain.yaml").read_text(encoding="utf-8"))
    perceiver = Perceiver(cfg["perception"], use_yolo=False, use_torch=False)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    marker = cv2.aruco.generateImageMarker(dictionary, 2, 100)
    measurements = []
    for left in (120, 270, 420):
        frame = np.full((480, 640, 3), 255, dtype=np.uint8)
        frame[110:210, left:left + 100] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
        ok, encoded = cv2.imencode(".jpg", frame)
        assert ok
        hdr = copy.deepcopy(EXAMPLE_OBSERVATION)
        result = perceiver.perceive(Observation(hdr, encoded.tobytes(), 0))
        markers = [d for d in result.detections if d.kind == "marker"]
        assert len(markers) == 1 and markers[0].id == "M02", markers
        d = markers[0]
        focal = 320 / math.tan(math.radians(30))
        expected_bearing = math.degrees(math.atan((left + 49.5 - 320) / focal))
        expected_range = 0.8 * focal / 100
        assert abs(d.bearing_deg - expected_bearing) < 0.5
        assert abs(d.est_range_m - expected_range) / expected_range < 0.05
        (out / f"marker-{left}.jpg").write_bytes(encoded.tobytes())
        (out / f"overlay-{left}.jpg").write_bytes(result.thumbnail_jpeg)
        measurements.append({"left_px": left, "id": d.id,
                             "bearing_deg": d.bearing_deg, "range_m": d.est_range_m})
    blank = np.full((480, 640, 3), 255, dtype=np.uint8)
    _, encoded = cv2.imencode(".jpg", blank)
    result = perceiver.perceive(Observation(hdr, encoded.tobytes(), 0))
    assert not result.detections, "Blank image produced detections"
    tracker = Tracker()
    tracker.update("R01", 1.0, 5, 0, "rock")
    assert tracker.match(1.1, 0) is None, "Same-frame track was reused"
    assert tracker.match(1.1, 1) == "R01", "Previous-frame track was not retained"
    tracker.update("R01", 1.1, 5, 1, "rock")
    assert tracker.match(1.2, 1) is None, "Second box received an already-used ID"
    from stub_sim import World
    world = World(950, ["M01", "M02", "M03"])
    for _ in range(3):
        result = perceiver.perceive(Observation(world.header(), world.render(), 0))
        ids = [d.id for d in result.detections]
        assert len(ids) == len(set(ids)), f"Duplicate detection IDs: {ids}"
        world.step(0.2)
    return {"opencv": cv2.__version__, "markers": measurements, "blank": "pass",
            "unique_tracks_on_stub_frames": "pass"}


def cuda_check() -> dict:
    import torch
    import torchvision
    assert torch.cuda.is_available(), "CUDA is not available"
    x = torch.arange(16, dtype=torch.float32, device="cuda").reshape(4, 4)
    product = x @ x.T
    torch.cuda.synchronize()
    assert torch.allclose(product.cpu(), x.cpu() @ x.cpu().T)
    # Exercise convolution kernels as well as matrix multiplication.
    model = torchvision.models.resnet18(weights=None).eval().cuda()
    with torch.inference_mode():
        output = model(torch.zeros(1, 3, 160, 160, device="cuda"))
    torch.cuda.synchronize()
    assert output.shape == (1, 1000) and torch.isfinite(output).all()
    return {"torch": torch.__version__, "torchvision": torchvision.__version__,
            "cuda_runtime": torch.version.cuda, "gpu": torch.cuda.get_device_name(0),
            "matrix_and_resnet_kernels": "pass (untrained model, execution check only)"}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def load_lines(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def loop_check(out: Path, delay: float, uplink: bool = False, use_torch: bool = False) -> dict:
    sim_port, panel_port = free_port(), free_port()
    while panel_port == sim_port:
        panel_port = free_port()
    cfg = yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))
    # Isolated baseline profile; do not silently change Dev's shared configuration.
    cfg.update(time_compression=1, decision_interval_sim_s=1, comms_delay_real_s=delay)
    bcfg = yaml.safe_load((HERE / "brain.yaml").read_text(encoding="utf-8"))
    bcfg["ports"].update(host="127.0.0.1", sim=sim_port, panel=panel_port)
    cfg_path, brain_path = out / "config.yaml", out / "brain.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    brain_path.write_text(yaml.safe_dump(bcfg), encoding="utf-8")
    processes, handles = [], []

    def launch(name, args):
        log = (out / f"{name}.log").open("w", encoding="utf-8")
        handles.append(log)
        proc = subprocess.Popen([sys.executable, "-u", str(HERE / name)] + args,
                                cwd=HERE, stdout=log, stderr=subprocess.STDOUT,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        processes.append(proc)
        return proc

    try:
        brain_args = ["--config", str(cfg_path), "--brain", str(brain_path),
                      "--no-yolo", "--record-dir", str(out / "run"), "--tag", "baseline"]
        if not use_torch:
            brain_args.append("--no-torch")
        brain = launch("main.py", brain_args)
        deadline = time.monotonic() + 60
        while True:
            assert brain.poll() is None, "BRAIN failed to start; inspect main.py.log"
            try:
                with socket.create_connection(("127.0.0.1", panel_port), timeout=0.2):
                    break
            except OSError:
                assert time.monotonic() < deadline, "BRAIN startup timeout"
                time.sleep(0.1)
        panel_args = ["--url", f"ws://127.0.0.1:{panel_port}", "--out", str(out / "panel-images")]
        if uplink:
            panel_args += ["--send", "set_gamma", "--value", "0", "--after", "0", "--time-compression", "1"]
        launch("stub_panel.py", panel_args)
        launch("stub_sim.py", ["--brain", f"ws://127.0.0.1:{sim_port}",
                               "--config", str(cfg_path), "--hz", "5"])
        deadline = time.monotonic() + delay * (2 if uplink else 1) + 8
        while time.monotonic() < deadline:
            assert all(p.poll() is None for p in processes), "A process exited; inspect logs"
            time.sleep(0.25)
    finally:
        for p in reversed(processes):
            if p.poll() is None:
                p.terminate()
            p.wait(timeout=10)
        for handle in handles:
            handle.close()

    run = next((out / "run").iterdir())
    actions = load_lines(run / "actions.jsonl")
    observations = load_lines(run / "observations.jsonl")
    telemetry = load_lines(run / "telemetry_delivered.jsonl")
    assert len(actions) >= 5 and len(telemetry) >= 3
    for action in actions:
        validate_action({k: v for k, v in action.items() if not k.startswith("_")})
    for record in telemetry:
        validate_telemetry({k: v for k, v in record.items() if not k.startswith("_")})
        assert record["clock"]["delay_real_s"] >= delay - 0.002
    times = [a["sim_time"] for a in actions]
    assert all(b - a >= 0.999 for a, b in zip(times, times[1:]))
    assert any(a["target"] and a["target"]["kind"] == "marker" for a in actions)
    first, last = observations[0], observations[-1]
    assert last["budget"]["remaining"] < first["budget"]["remaining"]
    assert (last["pose"]["x"], last["pose"]["y"]) != (first["pose"]["x"], first["pose"]["y"])
    sim_log = (out / "stub_sim.py.log").read_text(encoding="utf-8")
    panel_log = (out / "stub_panel.py.log").read_text(encoding="utf-8")
    brain_log = (out / "main.py.log").read_text(encoding="utf-8")
    if use_torch:
        assert "aruco+blobs+resnet18" in brain_log, "Requested CNN fell back unexpectedly"
    assert "real delay" in panel_log and "last drive_to_target" in sim_log
    for log in (sim_log, panel_log, brain_log):
        assert "INVALID" not in log and "CONTRACT VIOLATION" not in log and "Task exception" not in log
    images = list((out / "panel-images").glob("*.jpg"))
    assert len(images) >= len(telemetry)
    assert all(cv2.imread(str(p)) is not None for p in images)
    if uplink:
        commands = load_lines(run / "uplinks.jsonl")
        received = next(c for c in commands if c["_event"] == "received")
        applied = next(c for c in commands if c["_event"] == "uplink_applied")
        assert applied["_real_s"] - received["_real_s"] >= delay
        assert any(a["audit"]["gamma"] == .1 for a in actions)
    return {"observations": len(observations), "actions": len(actions),
            "telemetry": len(telemetry), "panel_jpegs": len(images),
            "min_delay_s": min(t["clock"]["delay_real_s"] for t in telemetry),
            "max_delay_s": max(t["clock"]["delay_real_s"] for t in telemetry),
            "budget_start": first["budget"]["remaining"], "budget_end": last["budget"]["remaining"],
            "pose_start": first["pose"], "pose_end": last["pose"],
            "backend": "aruco+blobs+resnet18" if use_torch else "aruco+blobs+hist", "physics_time_compression": 1,
            "delayed_gamma_uplink": "pass" if uplink else "not tested"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delay", type=float, default=3)
    parser.add_argument("--uplink", action="store_true")
    parser.add_argument("--torch", action="store_true", help="use pretrained ResNet18 in the live BRAIN")
    args = parser.parse_args()
    if args.delay < 0:
        parser.error("delay must be nonnegative")
    out = ROOT / "recordings" / datetime.now().strftime("phase0-%Y%m%d-%H%M%S-%f")
    out.mkdir(parents=True)
    print(f"Evidence: {out}", flush=True)
    report = {"python": sys.version, "camera": camera_check(out)}
    print("Camera checks passed", flush=True)
    report["gpu"] = cuda_check()
    print(f"GPU checks passed: {report['gpu']}", flush=True)
    report["loop"] = loop_check(out, args.delay, args.uplink, args.torch)
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    print("PHASE 0 CHECKS PASSED", flush=True)


if __name__ == "__main__":
    main()
