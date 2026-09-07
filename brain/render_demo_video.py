"""Export a recorded rover run as an annotated, timestamp-aligned MP4.

Uses logged simulation timestamps, not action receipt times (which the source
does not record). Frames/actions are held until the next sample, never borrowed
from the future. The resulting video is an evidence viewer, not a live PANEL.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
import hashlib
import json
import math
from pathlib import Path
import re
import textwrap

import cv2
import numpy as np


def read_rows(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    times = [float(row["sim_time"]) for row in rows]
    if any(not math.isfinite(t) for t in times) or times != sorted(times):
        raise ValueError(f"Non-finite or out-of-order simulation timestamps: {path}")
    return rows


def index_at(times: list[float], timestamp: float) -> int:
    """Return last sample at/before timestamp; -1 means none yet."""
    return bisect_right(times, timestamp) - 1


def frame_path(recording: Path, ref: str) -> Path:
    if not re.fullmatch(r"f_[0-9]+", ref):
        raise ValueError(f"Invalid frame reference: {ref!r}")
    return recording / "frames" / (ref + ".jpg")


def canvas(frame: np.ndarray, obs: dict, action: dict | None, timestamp: float, title: str) -> np.ndarray:
    result = np.full((720, 1280, 3), (26, 23, 20), dtype=np.uint8)
    font = cv2.FONT_HERSHEY_SIMPLEX

    def line(text: str, x: int, y: int, scale: float = .56, color=(230, 230, 230)) -> None:
        cv2.putText(result, text.encode("ascii", "replace").decode(), (x, y), font, scale, color, 1, cv2.LINE_AA)

    line(title[:85], 24, 42, .85, (120, 220, 240))
    line(f"Simulation {timestamp:.2f} s  |  camera sample {obs['sim_time']:.2f} s", 24, 77)
    h, w = frame.shape[:2]
    scale = min(640 / w, 480 / h)
    resized = cv2.resize(frame, (round(w * scale), round(h * scale)))
    rh, rw = resized.shape[:2]
    result[112:112 + rh, 16:16 + rw] = resized
    budget = obs["budget"]
    line(f"Energy: {budget['remaining']:.2f} / {budget['capacity']:.2f} Wh", 24, 626, .64)
    mission = obs.get("mission", {})
    confirmed = ", ".join(mission.get("confirmed_markers", [])) or "none"
    line(f"Confirmed markers: {confirmed}", 24, 658)
    line("Recorded camera; no object ground truth supplied to BRAIN", 24, 690, .47, (175, 175, 175))
    x, y = 684, 115
    if action is None:
        line("Awaiting first recorded decision", x, y, .62)
        return result
    audit = action.get("audit", {})
    target = action.get("target") or {}
    fields = [
        f"Decision: {action['decision']}",
        f"Target: {target.get('label', '-')} ({target.get('kind', '-')})",
        f"Decision source time: {action['sim_time']:.2f} s",
        f"Mission estimate: {audit.get('budget', {}).get('required_for_mission', 0):.2f} Wh",
        f"Slack: {audit.get('slack', 0):.3f}   Curiosity weight: {audit.get('w_curiosity', 0):.3f}",
        f"Reserve gate: {audit.get('gate', {}).get('result', '-')}",
    ]
    for field in fields:
        line(field, x, y)
        y += 29
    chosen = next((c for c in audit.get("candidates", []) if c.get("id") == audit.get("chosen")), None)
    if chosen:
        line(f"Selected utility: {chosen.get('U', 0):.4f}", x, y)
        y += 29
        if "n" in chosen:
            line(f"Appearance novelty: {chosen['n']:.3f}", x, y)
            y += 29
    y += 12
    line("BRAIN explanation", x, y, .64, (120, 220, 240))
    y += 28
    for chunk in textwrap.wrap(audit.get("text", "No explanation recorded."), width=64):
        if y > 653:
            line("[continued in actions.jsonl]", x, y, .46)
            break
        line(chunk, x, y, .47)
        y += 23
    line("Actions aligned by source timestamp; receipt latency is unrecorded.", x, 696, .40, (175, 175, 175))
    return result


def render(recording: Path, output: Path, title: str, fps: float = 10, start: float | None = None, end: float | None = None) -> dict:
    if not math.isfinite(fps) or fps <= 0 or fps > 60:
        raise ValueError("FPS must be finite and in (0, 60].")
    if output.suffix.lower() != ".mp4":
        raise ValueError("Output must use .mp4 extension.")
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing video: {output}")
    observations = read_rows(recording / "observations.jsonl")
    actions = read_rows(recording / "actions.jsonl")
    if not observations:
        raise ValueError("Recording has no observations.")
    ot = [float(o["sim_time"]) for o in observations]
    at = [float(a["sim_time"]) for a in actions]
    start = ot[0] if start is None else start
    end = ot[-1] if end is None else end
    if not all(map(math.isfinite, (start, end))) or not ot[0] <= start < end <= ot[-1]:
        raise ValueError("Clip must fall within observation timestamps and have positive duration.")
    for obs in observations:
        if not frame_path(recording, obs["_frame_ref"]).is_file():
            raise FileNotFoundError(obs["_frame_ref"])
    count = math.ceil((end - start) * fps)
    output.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(output), cv2.VideoWriter_fourcc(*"mp4v"), fps, (1280, 720))
    if not writer.isOpened():
        raise RuntimeError("OpenCV could not open the MP4 encoder.")
    previous = -1
    try:
        for i in range(count):
            t = start + i / fps
            oi, ai = index_at(ot, t), index_at(at, t)
            if oi != previous:
                raw = cv2.imread(str(frame_path(recording, observations[oi]["_frame_ref"])))
                if raw is None:
                    raise ValueError(f"Unreadable camera image: {observations[oi]['_frame_ref']}")
                previous = oi
            writer.write(canvas(raw, observations[oi], actions[ai] if ai >= 0 else None, t, title))
    finally:
        writer.release()
    capture = cv2.VideoCapture(str(output))
    decoded = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame.shape[:2] != (720, 1280):
                raise ValueError("Decoded video has incorrect dimensions.")
            decoded += 1
    finally:
        capture.release()
    if decoded != count:
        raise ValueError(f"Video decode validation failed: {decoded}/{count} frames.")
    report = {
        "recording": str(recording.resolve()), "video": str(output.resolve()),
        "title": title, "fps": fps, "frames": count, "decoded_frames": decoded,
        "source_start_s": start, "source_end_s": end, "video_duration_s": count / fps,
        "alignment": "Last observation/action at or before video simulation timestamp; action receipt latency not recorded.",
        "observations_sha256": hashlib.sha256((recording / "observations.jsonl").read_bytes()).hexdigest(),
        "actions_sha256": hashlib.sha256((recording / "actions.jsonl").read_bytes()).hexdigest(),
        "video_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }
    output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def self_test() -> None:
    # Irregular samples and equal timestamps must not show future decisions.
    assert index_at([1., 1.4, 2.7], .9) == -1
    assert index_at([1., 1.4, 2.7], 1.3) == 0
    assert index_at([1., 1.4, 2.7], 1.4) == 1
    assert index_at([1., 1.4, 1.4], 1.4) == 2
    assert index_at([], 4.) == -1
    for bad in ("../secret", "f_1/../../secret", "f_1.jpg"):
        try:
            frame_path(Path("."), bad)
        except ValueError:
            pass
        else:
            raise AssertionError("Unsafe frame reference accepted")
    print("Timeline and frame-reference checks passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path, nargs="?")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--title", default="Rover decision demonstration")
    parser.add_argument("--fps", type=float, default=10.)
    parser.add_argument("--start", type=float, help="Absolute simulation time in seconds")
    parser.add_argument("--end", type=float, help="Absolute simulation time in seconds")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        if args.recording is None or args.out is None:
            parser.error("recording and --out are required")
        print(json.dumps(render(args.recording, args.out, args.title, args.fps, args.start, args.end), indent=2))
