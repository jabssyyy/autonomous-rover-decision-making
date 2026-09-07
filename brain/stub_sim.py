"""stub_sim.py -- stand-in for the Godot SIM (interface-contract.md sections 2, 3, 4, 10).

Speaks EXACTLY the contract: one JSON text frame (observation) then one binary
frame (JPEG) per tick, to ws://localhost:8765 (BRAIN is the server). Applies the
actions BRAIN sends back, so the rover really moves, budget really drains, and a
marker is confirmed only when BRAIN has committed to it and driven close.

Modes
  synthetic (default) 640x480 frames: Mars-ish ground, grey rock blobs (4 repeated
                      looks), two striped 'anomaly' rocks, and a REAL ArUco marker
                      (DICT_4X4_50, id = marker number) for each assigned marker.
  --replay DIR        replay JPEGs from DIR (sorted). If DIR is a BRAIN recording
                      (contains observations.jsonl + frames/), the recorded headers
                      are replayed verbatim and BRAIN's actions are ignored.

Usage
  python stub_sim.py                          # 5 Hz synthetic -> ws://localhost:8765
  python stub_sim.py --budget 742             # stay-run budget
  python stub_sim.py --replay runs/20260907_121000_stay
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import time
from pathlib import Path

import cv2
import numpy as np
import yaml
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from contract import ContractViolation, validate_action, validate_jpeg, validate_observation

W, H = 640, 480
HFOV_DEG = 60.0
CAM_HEIGHT_M = 1.2
MARKER_SIDE_M = 0.8            # must equal brain.yaml perception.marker_side_m
ARUCO = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
F_PX = (W / 2) / math.tan(math.radians(HFOV_DEG / 2))
HORIZON_Y = H // 2

DEFAULT_CFG = yaml.safe_load(Path(__file__).with_name("config.yaml").read_text(encoding="utf-8"))

# --- SIM-side physics. Contract section 4: SIM owns budget accounting. ---------
TURN_DEG_PER_SIMS = 5.0
CONFIRM_RANGE_M = 3.0
HAZARD_SENSE_M = 8.0
AVOID_RANGE_M = 2.5


class World:
    """SIM-only knowledge. NOTHING here reaches BRAIN except through header() and render()."""

    def __init__(self, budget: float, assigned: list[str], seed: int = 7, cfg: dict | None = None) -> None:
        self.cfg = dict(DEFAULT_CFG if cfg is None else cfg)
        self.last_action_time = time.monotonic()
        self.confirm_elapsed = 0.0
        rng = random.Random(seed)
        self.markers = {"M01": (18.0, 6.0), "M02": (34.0, -9.0), "M03": (52.0, 11.0)}
        self.rocks: list[tuple] = []            # (x, y, radius_m, shade, kind)
        for i in range(26):                     # common rocks: four repeated looks
            self.rocks.append((rng.uniform(5, 60), rng.uniform(-24, 24), rng.uniform(0.3, 0.9),
                               75 + 25 * (i % 4), "common"))
        self.rocks.append((22.0, 2.5, 1.1, 150, "striped"))     # anomaly near the M01->M02 path
        self.rocks.append((44.0, -13.0, 1.0, 150, "striped"))   # a second identical one: habituation
        self.x, self.y, self.heading = 0.0, 0.0, 10.0
        self.speed, self.heading_cmd = 0.0, 10.0
        self.budget, self.capacity = float(budget), 1000.0
        self.assigned, self.confirmed = list(assigned), []
        self.committed: str | None = None
        self.decision = "continue"
        self.dwell_left = 0.0
        self.state = "AUTONOMOUS"
        self.sim_time, self.seq = 0.0, 0
        self.frame_rng = np.random.default_rng(seed)

    # ---- contract section 3: apply an action ---------------------------------
    def apply(self, action: dict) -> None:
        validate_action(action)                 # SIM refuses malformed actions, loudly
        self.last_action_time = time.monotonic()
        d = action["decision"]
        drv = action["drive"]
        self.decision = d
        if d == "drive_to_target":
            self.committed = action["target"]["label"]
            self.heading_cmd, self.speed, self.state = drv["heading_deg"], drv["speed"], "AUTONOMOUS"
        elif d == "investigate":
            label = action["target"]["label"]
            if self.dwell_left <= 0 or self.committed != label:
                self.dwell_left = self.cfg["investigate_dwell_sim_s"]
            self.committed, self.speed, self.state = label, 0.0, "AUTONOMOUS"
        elif d == "continue":
            self.heading_cmd, self.speed, self.state = drv["heading_deg"], drv["speed"], "AUTONOMOUS"
        elif d == "survey":
            self.speed, self.heading_cmd, self.state = 0.0, self.heading + 90.0, "AUTONOMOUS"
        elif d == "report":
            self.speed, self.state = 0.0, "REPORTING"
        elif d == "hold":
            self.speed, self.dwell_left = 0.0, 0.0
            if self.state == "REPORTING":
                self.state = "AWAITING_UPLINK"

    # ---- physics --------------------------------------------------------------
    def rel(self, pt: tuple[float, float]) -> tuple[float, float]:
        dx, dy = pt[0] - self.x, pt[1] - self.y
        rng_ = math.hypot(dx, dy)
        bearing = (math.degrees(math.atan2(dy, dx)) - self.heading + 180.0) % 360.0 - 180.0
        return rng_, bearing

    def hazard(self) -> tuple[float, float]:
        best = (99.0, 0.0)
        for (rx, ry, r, _, _) in self.rocks:
            d, b = self.rel((rx, ry))
            d = max(0.0, d - r)
            if abs(b) < 30.0 and d < HAZARD_SENSE_M and d < best[0]:
                best = (d, b)
        return best

    def step(self, dt: float) -> None:
        if time.monotonic() - self.last_action_time > 2.5 or self.budget <= 0:
            self.speed, self.dwell_left = 0., 0.
        self.sim_time += dt
        if self.committed in self.markers and self.rel(self.markers[self.committed])[0] < CONFIRM_RANGE_M:
            self.speed = 0.  # remain at the marker during confirmation dwell
        self.seq += 1
        cost = self.cfg["idle_rate_wh_per_s"] * dt
        if self.dwell_left > 0:
            elapsed = min(dt, self.dwell_left)
            self.dwell_left -= elapsed
            cost += self.cfg["dwell_rate_wh_per_s"] * elapsed
        else:
            hz_r, hz_b = self.hazard()
            cmd = self.heading_cmd
            if self.speed > 0 and hz_r < AVOID_RANGE_M and abs(hz_b) < 20:
                cmd = self.heading + (30.0 if hz_b < 0 else -30.0)   # reactive avoidance lives in SIM
            err = (cmd - self.heading + 180.0) % 360.0 - 180.0
            self.heading = (self.heading + max(-TURN_DEG_PER_SIMS * dt, min(TURN_DEG_PER_SIMS * dt, err))) % 360.0
            if self.speed > 0:
                dist = self.speed * self.cfg["max_speed_m_per_s"] * dt
                self.x += dist * math.cos(math.radians(self.heading))
                self.y += dist * math.sin(math.radians(self.heading))
                cost += self.cfg["drive_rate_wh_per_m"] * dist
        self.budget = max(0.0, self.budget - cost)
        # Confirmation requires visual commitment, arrival, and the shared dwell.
        if (self.committed in self.markers and self.committed not in self.confirmed
                and self.decision == "drive_to_target" and self.budget > 0
                and time.monotonic() - self.last_action_time <= 2.5):
            if self.rel(self.markers[self.committed])[0] < CONFIRM_RANGE_M:
                self.speed = 0.
                elapsed = min(dt, max(0., self.cfg["confirm_dwell_sim_s"] - self.confirm_elapsed))
                self.confirm_elapsed += elapsed
                self.budget = max(0., self.budget - self.cfg["dwell_rate_wh_per_s"] * elapsed)
                if self.confirm_elapsed >= self.cfg["confirm_dwell_sim_s"]:
                    self.confirmed.append(self.committed)
                    self.committed, self.confirm_elapsed = None, 0.
            else:
                self.confirm_elapsed = 0.
        else:
            self.confirm_elapsed = 0.

    # ---- contract section 2: the ONLY things BRAIN gets ------------------------
    def header(self) -> dict:
        hz_r, hz_b = self.hazard()
        return {
            "type": "observation", "seq": self.seq, "sim_time": round(self.sim_time, 3),
            "pose": {"x": round(self.x, 3), "y": round(self.y, 3), "heading_deg": round(self.heading, 2)},
            "budget": {"remaining": round(self.budget, 3), "capacity": self.capacity, "unit": "Wh", "simulated": True},
            "hazard": {"range_m": round(hz_r, 2), "bearing_deg": round(hz_b, 1)},
            "mission": {"assigned_markers": list(self.assigned), "confirmed_markers": list(self.confirmed)},
            "state": self.state,
            "camera": {"w": W, "h": H, "hfov_deg": HFOV_DEG, "encoding": "jpeg"},
        }

    @staticmethod
    def _paste(img: np.ndarray, tile: np.ndarray, x0: int, y0: int) -> None:
        th, tw = tile.shape[:2]
        xs, ys, xe, ye = max(0, x0), max(0, y0), min(W, x0 + tw), min(H, y0 + th)
        if xe <= xs or ye <= ys:
            return
        img[ys:ye, xs:xe] = tile[ys - y0:ye - y0, xs - x0:xe - x0]

    def render(self) -> bytes:
        img = np.empty((H, W, 3), np.uint8)
        img[:HORIZON_Y] = (150, 170, 205)      # BGR butterscotch sky
        img[HORIZON_Y:] = (40, 70, 140)        # rust ground
        noise = self.frame_rng.integers(-16, 16, (H, W, 1), dtype=np.int16)
        img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        items = []
        for (rx, ry, r, shade, kind) in self.rocks:
            d, b = self.rel((rx, ry))
            if d > 0.8 and abs(b) < HFOV_DEG / 2 + 5:
                items.append((d, "rock", b, r, shade, kind))
        for label, pt in self.markers.items():
            d, b = self.rel(pt)
            if d > 0.8 and abs(b) < HFOV_DEG / 2 + 5:
                items.append((d, "marker", b, label, 0, ""))
        for it in sorted(items, key=lambda t: -t[0]):          # far to near (painter's order)
            d, what, b = it[0], it[1], it[2]
            cx = int(W / 2 + F_PX * math.tan(math.radians(b)))
            gy = int(HORIZON_Y + F_PX * CAM_HEIGHT_M / d)          # ground contact row
            if what == "rock":
                r, shade, kind = it[3], it[4], it[5]
                ax, ay = max(2, int(F_PX * r / d)), max(1, int(F_PX * r * 0.65 / d))
                cv2.ellipse(img, (cx, gy - ay // 2), (ax, ay), 0, 0, 360, (shade - 10, shade, shade + 5), -1)
                if kind == "striped":
                    mask = np.zeros((H, W), np.uint8)
                    cv2.ellipse(mask, (cx, gy - ay // 2), (ax, ay), 0, 0, 360, 255, -1)
                    striped = img.copy()
                    for yy in range(gy - ay, gy + ay + 1, max(2, ay // 3)):
                        cv2.line(striped, (cx - ax, yy), (cx + ax, yy), (25, 25, 35), max(1, ay // 7))
                    img[mask > 0] = striped[mask > 0]
            else:
                label = it[3]
                side = int(F_PX * self.cfg["marker_side_m"] / d)
                if side >= 8:
                    tag = cv2.aruco.generateImageMarker(ARUCO, int(label[1:]), side)   # real ArUco pixels
                    pad = max(2, side // 6)                                             # white quiet zone
                    tile = cv2.copyMakeBorder(tag, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)
                    tile = cv2.cvtColor(tile, cv2.COLOR_GRAY2BGR)
                    self._paste(img, tile, cx - tile.shape[1] // 2, gy - tile.shape[0])
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        assert ok
        return buf.tobytes()


# --- replay source -------------------------------------------------------------
def load_replay(path: Path):
    """Yields (header_or_None, jpeg_bytes)."""
    obs_file = path / "observations.jsonl"
    if obs_file.exists():
        for line in obs_file.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            ref = rec.get("_frame_ref") or f"f_{rec['seq']}"
            rec = {k: v for k, v in rec.items() if not k.startswith("_")}
            jpg = path / "frames" / f"{ref}.jpg"
            if jpg.exists():
                yield rec, jpg.read_bytes()
    else:
        for jpg in sorted(path.glob("*.jpg")) + sorted(path.glob("*.jpeg")):
            yield None, jpg.read_bytes()


async def pump_actions(ws, world: World, stats: dict, ignore: bool) -> None:
    async for msg in ws:
        if not isinstance(msg, str):
            print("!! BRAIN sent a binary frame on the action link; ignoring")
            continue
        try:
            action = json.loads(msg)
            if ignore:
                validate_action(action)
            else:
                world.apply(action)
            stats["n"] += 1
            stats["last"] = f"{action['decision']}" + (f"->{action['target']['label']}" if action["target"] else "")
        except (ContractViolation, ValueError, KeyError) as e:
            print(f"!! BRAIN sent an INVALID action: {e}")


async def run(args: argparse.Namespace) -> None:
    cfg = dict(DEFAULT_CFG)
    if Path(args.config).exists():
        cfg.update(yaml.safe_load(Path(args.config).read_text(encoding="utf-8")) or {})
    assigned = [m.strip() for m in args.markers.split(",") if m.strip()]
    world = World(args.budget, assigned, seed=args.seed, cfg=cfg)
    dt_sim = cfg["time_compression"] / args.hz
    period = 1.0 / args.hz
    stats = {"n": 0, "last": "-"}
    replay = list(load_replay(Path(args.replay))) if args.replay else None
    if replay is not None:
        print(f"replaying {len(replay)} frames from {args.replay}")
    print(f"stub_sim -> {args.brain} @ {args.hz} Hz | dt_sim={dt_sim:.1f} s/frame | budget {args.budget} Wh | markers {assigned}")

    async for ws in connect(args.brain, max_size=None, compression=None, open_timeout=5):
        print("connected to BRAIN")
        rx = asyncio.create_task(pump_actions(ws, world, stats, ignore=replay is not None))
        try:
            next_t = time.monotonic()
            last_print = 0.0
            i = 0
            while True:
                if replay is not None:
                    if i >= len(replay):
                        if not args.loop:
                            print("replay finished")
                            rx.cancel()
                            return
                        i = 0
                    hdr, jpeg = replay[i]
                    i += 1
                    if hdr is None:
                        hdr = world.header()
                else:
                    hdr, jpeg = world.header(), world.render()
                validate_observation(hdr)           # dogfood: SIM proves it obeys THE RULE
                validate_jpeg(jpeg)
                await ws.send(json.dumps(hdr))      # text frame ...
                await ws.send(jpeg)                 # ... immediately followed by the binary frame
                world.step(dt_sim)
                now = time.monotonic()
                if now - last_print >= 1.0:
                    last_print = now
                    print(f"seq {hdr['seq']:5d} sim {hdr['sim_time']:8.1f}s pose ({hdr['pose']['x']:6.1f},{hdr['pose']['y']:6.1f}) "
                          f"hdg {hdr['pose']['heading_deg']:6.1f} budget {hdr['budget']['remaining']:7.1f} "
                          f"confirmed {hdr['mission']['confirmed_markers']} | actions {stats['n']} last {stats['last']}")
                next_t += period
                await asyncio.sleep(max(0.0, next_t - time.monotonic()))
        except ConnectionClosed as e:
            print(f"BRAIN link closed ({e}); reconnecting...")
            rx.cancel()
            world.speed, world.dwell_left = 0., 0.
            continue


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--brain", default="ws://localhost:8765")
    ap.add_argument("--config", default=str(Path(__file__).with_name("config.yaml")))
    ap.add_argument("--hz", type=float, default=5.0)
    ap.add_argument("--budget", type=float, default=950.0, help="start budget (Wh). stay-run ~742, deviate-run ~950")
    ap.add_argument("--markers", default="M01,M02,M03")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--replay", default=None, help="folder of JPEGs, or a BRAIN run dir")
    ap.add_argument("--loop", action="store_true", help="loop the replay")
    args = ap.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
