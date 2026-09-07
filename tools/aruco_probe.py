"""aruco_probe.py -- a 40-line BRAIN that only knows OpenCV, for proving SIM's markers.

It is NOT the real BRAIN and has no policy. It exists to answer, before Jabin's
perception stack exists, the one SIM question that cannot be eyeballed:

  * do the rendered ArUco quads survive Godot's import + JPEG at real range?
  * can a rover working from pixels alone complete the whole assigned marker list?
  * is camera.hfov_deg honest, i.e. does steering on a bearing computed from the
    image actually bring the rover to the marker? (KEEP_WIDTH vs KEEP_HEIGHT)
  * does the range estimate f_px * W_m / w_px match the ground truth?

Run it INSTEAD of stub_brain.py, then start the sim:
    python tools/aruco_probe.py --target M02
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import sys
from pathlib import Path

import cv2
import numpy as np
import yaml
from websockets.asyncio.server import serve

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "brain"))
from contract import validate_action, validate_jpeg, validate_observation  # noqa: E402

log = logging.getLogger("aruco_probe")
DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
DETECTOR = cv2.aruco.ArucoDetector(DICT)


def audit_for(marker: str | None, conf: float, remaining: float, gamma: float, margin: float) -> dict:
    """Contract S5 shape with arithmetic that closes -- validate_action checks it."""
    B = max(remaining, 1.0)
    B_req = min(490.0, 0.66 * B)
    slack = round((B - B_req) / B, 3)
    w_c = round(max(0.0, slack) ** gamma, 3)
    p, c = 10.0, round(conf, 3)
    raw = round(p * c, 3)
    cost = 3.31
    U = round(raw / cost, 3)
    reserve = round(min(99.99, (B - cost) / max(B_req - cost, 1e-3)), 3)
    return {
        "candidates": [{"id": marker or "M??", "stream": "mission", "p": p, "c": c,
                        "value_raw": raw, "value_weighted": raw, "cost_est": cost, "U": U}],
        "budget": {"remaining": round(B, 2), "required_for_mission": round(B_req, 2)},
        "slack": slack, "gamma": gamma, "w_curiosity": w_c,
        "gate": {"result": "pass" if reserve >= margin else "fail",
                 "post_action_reserve": reserve, "margin": margin},
        "chosen": marker,
        "text": (f"ArUco probe: {marker} at bearing/range from pixels only." if marker
                 else "ArUco probe: no marker in frame, sweeping."),
    }


class Probe:
    def __init__(self, cfg: dict, target: str) -> None:
        self.cfg = cfg
        self.target = target                      # first marker to chase; then the mission
        self.search_heading = 0.0
        self.best_px = 0.0
        self.seen = 0
        self.frames = 0
        self.dwell = 0
        self.done: set[str] = set()

    async def handler(self, ws) -> None:
        log.info("SIM connected")
        header = None
        async for msg in ws:
            if isinstance(msg, str):
                header = validate_observation(json.loads(msg))
                continue
            if header is None:
                continue
            hdr, header = header, None
            jpeg = validate_jpeg(msg)
            await self.decide(hdr, jpeg, ws)

    def pick_target(self, hdr: dict) -> str | None:
        """Work the mission list in order, skipping whatever SIM has already confirmed."""
        confirmed = set(hdr["mission"]["confirmed_markers"])
        order = [self.target] + [m for m in hdr["mission"]["assigned_markers"] if m != self.target]
        for m in order:
            if m not in confirmed:
                return m
        return None

    async def decide(self, hdr: dict, jpeg: bytes, ws) -> None:
        self.frames += 1
        cam = hdr["camera"]
        w, h = cam["w"], cam["h"]
        # f_px from the HORIZONTAL fov the contract carries. If SIM left the camera on
        # Godot's default KEEP_HEIGHT this is wrong by the 4:3 aspect and the rover
        # will steer consistently beside every marker.
        f_px = (w / 2.0) / math.tan(math.radians(cam["hfov_deg"]) / 2.0)
        img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_GRAYSCALE)
        corners, ids, _ = DETECTOR.detectMarkers(img)

        confirmed = set(hdr["mission"]["confirmed_markers"])
        for m in confirmed - self.done:
            self.done.add(m)
            log.info("CONFIRMED by SIM: %s  (%d/%d, largest marker %.0f px, seen in %d/%d frames)",
                     m, len(confirmed), len(hdr["mission"]["assigned_markers"]),
                     self.best_px, self.seen, self.frames)
            self.dwell = 15                       # a visible beat at the marker, then move on

        active = self.pick_target(hdr)
        decision, target, speed = "continue", None, 0.6
        heading = hdr["pose"]["heading_deg"]
        conf = 0.35

        if self.dwell > 0:
            # stop and dwell: this is the branch that spends dwell budget in SIM and
            # turns the god-view camera wedge cold, so the beat reads from across a room
            self.dwell -= 1
            last = sorted(confirmed)[-1] if confirmed else self.target
            action = {"type": "action", "in_reply_to_seq": int(hdr["seq"]), "sim_time": hdr["sim_time"],
                      "decision": "investigate",
                      "target": {"label": last, "kind": "marker", "bearing_deg": 0.0, "est_range_m": 1.5},
                      "drive": {"heading_deg": round(heading, 2), "speed": 0.0},
                      "audit": audit_for(last, 0.9, hdr["budget"]["remaining"], self.cfg["gamma"],
                                         self.cfg["mission_margin"])}
            validate_action(action)
            await ws.send(json.dumps(action))
            return
        if active is None:
            log.info("mission complete: %s  -- holding", sorted(confirmed))
            action = {"type": "action", "in_reply_to_seq": int(hdr["seq"]), "sim_time": hdr["sim_time"],
                      "decision": "hold", "target": None,
                      "drive": {"heading_deg": round(heading, 2), "speed": 0.0},
                      "audit": audit_for(None, 0.5, hdr["budget"]["remaining"], self.cfg["gamma"],
                                         self.cfg["mission_margin"])}
            validate_action(action)
            await ws.send(json.dumps(action))
            return

        hit = None
        want_id = int(active[1:])                 # M02 -> aruco id 2
        if ids is not None:
            for quad, mid in zip(corners, ids.ravel()):
                if int(mid) == want_id:
                    hit = quad.reshape(4, 2)

        if hit is not None:
            self.seen += 1
            cx = float(hit[:, 0].mean())
            px = float(np.linalg.norm(hit[0] - hit[1]))
            self.best_px = max(self.best_px, px)
            bearing = math.degrees(math.atan2(cx - w / 2.0, f_px))
            est_range = f_px * self.cfg["marker_width_m"] / max(px, 1e-3)
            true_range = math.hypot(hdr["pose"]["x"] - MARKER_TRUTH[active][0],
                                    hdr["pose"]["y"] - MARKER_TRUTH[active][1])
            conf = min(0.99, 0.4 + px / 120.0)
            decision = "drive_to_target"
            target = {"label": active, "kind": "marker",
                      "bearing_deg": round(bearing, 2), "est_range_m": round(est_range, 2)}
            heading = (heading + bearing) % 360.0
            if self.frames % 5 == 0:
                log.info("%s  %5.1f px  bearing %+6.2f deg  est %5.1f m  true %5.1f m  err %+5.1f m",
                         active, px, bearing, est_range, true_range, est_range - true_range)
        else:
            # nothing in frame: creep the heading so the rover sweeps the horizon
            self.search_heading = (self.search_heading + 3.0) % 360.0
            heading = self.search_heading
            speed = 0.35

        action = {"type": "action", "in_reply_to_seq": int(hdr["seq"]), "sim_time": hdr["sim_time"],
                  "decision": decision, "target": target,
                  "drive": {"heading_deg": round(heading, 2), "speed": speed},
                  "audit": audit_for(active if hit is not None else None, conf,
                                     hdr["budget"]["remaining"], self.cfg["gamma"],
                                     self.cfg["mission_margin"])}
        validate_action(action)
        await ws.send(json.dumps(action))


# ground truth, for the error column only -- never sent to any BRAIN
MARKER_TRUTH = {"M01": (-8.0, -12.0), "M02": (1.5, -32.0), "M03": (-20.0, -46.0),
                "M04": (26.0, -30.0), "M05": (-30.0, 10.0)}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="M02")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    cfg = yaml.safe_load((Path(__file__).resolve().parents[1] / "brain" / "config.yaml").read_text())
    probe = Probe(cfg, args.target)
    async with serve(probe.handler, "127.0.0.1", args.port, max_size=8 * 1024 * 1024):
        log.info("aruco_probe on ws://127.0.0.1:%d -- works the assigned marker list, "
                 "starting at %s (pattern %.2f m)", args.port, args.target, cfg["marker_width_m"])
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
