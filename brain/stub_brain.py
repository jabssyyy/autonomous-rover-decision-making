"""stub_brain.py -- stand-in for BRAIN with NO perception and NO policy.

Lets Dev build SIM and PANEL with nothing but this file + contract.py + runtime.py.
  * server on :8765 for SIM   (observation header + JPEG in; action out)
  * server on :8766 for PANEL (delayed telemetry + thumbnail out; uplink in)
Every decision_interval_sim_s of SIM time it answers 'drive_to_target' (toward a
fake bearing) or 'continue' with a canned but arithmetically-closed audit record,
pushes telemetry through a REAL-seconds delay line, and delays inbound uplinks the
same way (stale ones are logged as uplink_stale).

  python stub_brain.py                 # delay from config.yaml (60 s)
  python stub_brain.py --delay 3       # short delay while wiring things up
  python stub_brain.py --record        # also dump frames + decisions to runs/
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import random
import time
from pathlib import Path

import cv2
import numpy as np
import yaml
from websockets.asyncio.server import broadcast, serve
from websockets.exceptions import ConnectionClosed

from contract import (ContractViolation, validate_action, validate_jpeg, validate_observation,
                      validate_telemetry, validate_uplink)
from runtime import DelayLine, Recorder, dumps

log = logging.getLogger("stub_brain")


def r2(x: float) -> float:
    return round(float(x), 2)


def canned_audit(remaining: float, gamma: float, margin: float, tick: int) -> tuple[dict, str]:
    """A record in the exact shape of contract section 5 whose arithmetic closes."""
    B = max(remaining, 1.0)
    B_req = min(490.0, 0.66 * B)
    slack = r2((B - B_req) / B)
    w_c = r2(max(0.0, slack) ** gamma)
    c_m = r2(0.45 + 0.1 * math.sin(tick / 3.0))           # marker confidence wobbles
    m_raw = r2(10 * c_m); m_cost = 3.31; m_U = r2(m_raw / m_cost)
    n_a, c_a = 0.82, r2(0.6 + 0.1 * math.cos(tick / 5.0))
    a_raw = r2(n_a * c_a); a_w = r2(w_c * a_raw); a_cost = 1.14; a_U = r2(a_w / a_cost)
    chosen = "M02" if m_U >= a_U else "A07"
    cost_chosen = m_cost if chosen == "M02" else a_cost
    B_req_after = B_req - (m_cost if chosen == "M02" else 0.0)
    reserve = r2(min(99.99, (B - cost_chosen) / max(B_req_after, 1e-3)))
    result = "pass" if reserve >= margin else "fail"
    text = (f"Marker M02 (U={m_U}) over anomaly A07 (U={a_U}). Anomaly raw value {a_raw}, but slack {slack} "
            f"at gamma {gamma} gives curiosity weight {w_c} -> weighted {a_w}. Staying on task."
            if chosen == "M02" else
            f"Anomaly A07 (U={a_U}) over marker M02 (U={m_U}); slack {slack} at gamma {gamma} gives curiosity "
            f"weight {w_c}. Gate {result} (reserve {reserve} vs margin {margin}). Deviating.")
    audit = {
        "candidates": [
            {"id": "M02", "stream": "mission", "p": 10, "c": c_m, "value_raw": m_raw,
             "value_weighted": m_raw, "cost_est": m_cost, "U": m_U},
            {"id": "A07", "stream": "curiosity", "n": n_a, "c": c_a, "value_raw": a_raw,
             "value_weighted": a_w, "cost_est": a_cost, "U": a_U},
        ],
        "budget": {"remaining": r2(remaining), "required_for_mission": r2(B_req)},
        "slack": slack, "gamma": gamma, "w_curiosity": w_c,
        "gate": {"result": result, "post_action_reserve": reserve, "margin": margin},
        "chosen": chosen, "text": text,
    }
    return audit, chosen


class StubBrain:
    def __init__(self, cfg: dict, delay_s: float, recorder: Recorder | None) -> None:
        self.cfg, self.rec = cfg, recorder
        self.t0 = time.monotonic()
        self.sim_time = 0.0                 # onboard clock: ONLY ever set from observations
        self.last_decision_sim = -1e9
        self.tick = 0
        self.sim_ws = None
        self.panels: set = set()
        self.pending_header: dict | None = None
        self.down = DelayLine(delay_s, self.deliver)       # BRAIN -> PANEL, REAL seconds
        self.up = DelayLine(delay_s, self.apply_uplink)    # PANEL -> BRAIN, REAL seconds
        self.investigating = False

    def real(self) -> float:
        return time.monotonic() - self.t0

    # ---------------- SIM side ----------------
    async def sim_handler(self, ws) -> None:
        log.info("SIM connected from %s (newest connection wins)", ws.remote_address)
        self.sim_ws = ws
        try:
            async for msg in ws:
                if isinstance(msg, str):
                    self.pending_header = validate_observation(json.loads(msg))
                    continue
                if self.pending_header is None:
                    raise ContractViolation("binary frame arrived without a preceding observation header")
                hdr, self.pending_header = self.pending_header, None
                jpeg = validate_jpeg(msg)
                self.sim_time = hdr["sim_time"]
                if self.rec:
                    ref = self.rec.frame(hdr["seq"], jpeg)
                    self.rec.jsonl("observations", {**hdr, "_frame_ref": ref, "_real_s": self.real(), "_bytes": len(jpeg)})
                if hdr["sim_time"] - self.last_decision_sim >= self.cfg["decision_interval_sim_s"]:
                    await self.decide(hdr, jpeg, ws)
        except ContractViolation as e:
            log.critical("CONTRACT VIOLATION from SIM: %s", e)
            raise
        except ConnectionClosed:
            log.info("SIM disconnected")
        finally:
            if self.sim_ws is ws:
                self.sim_ws = None

    async def decide(self, hdr: dict, jpeg: bytes, ws) -> None:
        self.tick += 1
        self.last_decision_sim = hdr["sim_time"]
        audit, chosen = canned_audit(hdr["budget"]["remaining"], self.cfg["gamma"], self.cfg["mission_margin"], self.tick)
        heading = hdr["pose"]["heading_deg"]
        if self.tick % 3 == 0:
            decision, target = "continue", None
            audit["chosen"], audit["text"] = None, "Nothing worth re-committing to; continuing on heading."
            drive = {"heading_deg": r2(heading), "speed": 0.6}
        else:
            bearing = r2(random.uniform(-15, 15))
            kind = "marker" if chosen == "M02" else "anomaly"
            decision = "drive_to_target"
            target = {"label": chosen, "kind": kind, "bearing_deg": bearing, "est_range_m": r2(random.uniform(6, 25))}
            drive = {"heading_deg": r2((heading + bearing) % 360), "speed": 0.6}
        action = {"type": "action", "in_reply_to_seq": hdr["seq"], "sim_time": hdr["sim_time"],
                  "decision": decision, "target": target, "drive": drive, "audit": audit}
        validate_action(action)
        await ws.send(dumps(action))
        log.info("seq %5d sim %8.1f -> %-16s %s", hdr["seq"], hdr["sim_time"], decision, target["label"] if target else "")
        if self.rec:
            self.rec.jsonl("actions", {**action, "_real_s": self.real()})
        # thumbnail: the frame we were given, downscaled (the real BRAIN draws boxes on it first)
        img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        blobs = []
        if img is not None:
            cv2.putText(img, f"{decision} {target['label'] if target else ''}", (8, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            ok, buf = cv2.imencode(".jpg", cv2.resize(img, (320, 240)), [cv2.IMWRITE_JPEG_QUALITY, 70])
            if ok:
                blobs.append(buf.tobytes())
        tele = {"type": "telemetry", "generated_at": hdr["sim_time"], "delivered_at": hdr["sim_time"],
                "pose": hdr["pose"], "state": hdr["state"], "audit": audit,
                "mission": {"confirmed_markers": hdr["mission"]["confirmed_markers"],
                            "total": len(hdr["mission"]["assigned_markers"])},
                "attachments": [{"kind": "thumbnail", "frame_ref": f"f_{hdr['seq']}"}] if blobs else []}
        validate_telemetry(tele)
        self.down.push({"msg": tele, "blobs": blobs, "generated_real_s": self.real()})

    # ---------------- PANEL side ----------------
    async def deliver(self, item: dict) -> None:
        msg = item["msg"]
        now = self.real()
        msg["delivered_at"] = self.sim_time                      # onboard clock at the moment of delivery
        msg["clock"] = {"generated_real_s": round(item["generated_real_s"], 3), "delivered_real_s": round(now, 3),
                        "delay_real_s": round(now - item["generated_real_s"], 3)}
        validate_telemetry(msg)
        broadcast(self.panels, dumps(msg))                       # JSON text frame ...
        for b in item["blobs"]:
            broadcast(self.panels, b)                            # ... then one binary frame per attachment
        if self.rec:
            self.rec.jsonl("telemetry_delivered", msg)

    async def panel_handler(self, ws) -> None:
        log.info("PANEL connected from %s (%d panels)", ws.remote_address, len(self.panels) + 1)
        self.panels.add(ws)
        try:
            async for msg in ws:
                if not isinstance(msg, str):
                    continue
                try:
                    up = validate_uplink(json.loads(msg))
                except (ContractViolation, ValueError) as e:
                    log.error("INVALID uplink from panel: %s", e)
                    continue
                log.info("uplink %s received at sim %.1f; lands in %.0f real s", up["command"], self.sim_time, self.up.delay_s)
                if self.rec:
                    self.rec.jsonl("uplinks", {**up, "_event": "received", "_real_s": self.real()})
                self.up.push(up)
        except ConnectionClosed:
            pass
        finally:
            self.panels.discard(ws)
            log.info("PANEL disconnected (%d panels)", len(self.panels))

    async def apply_uplink(self, up: dict) -> None:
        up["arrives_at"] = self.sim_time
        cmd = up["command"]
        stale = cmd in ("abort_investigation", "force_investigate") and not self.investigating
        log.warning("uplink %s %s at sim %.1f (issued at sim %.1f)", cmd,
                    "STALE -> ignored (uplink_stale)" if stale else "applied", self.sim_time, up["issued_at"])
        if self.rec:
            self.rec.jsonl("uplinks", {**up, "_event": "uplink_stale" if stale else "uplink_applied", "_real_s": self.real()})

    async def serve(self, host: str, sim_port: int, panel_port: int) -> None:
        async with serve(self.sim_handler, host, sim_port, max_size=16 * 2**20, compression=None), \
                   serve(self.panel_handler, host, panel_port, max_size=2**20, compression=None):
            log.info("stub_brain up: SIM ws://%s:%d  PANEL ws://%s:%d  delay %.0f real s",
                     host, sim_port, host, panel_port, self.down.delay_s)
            await asyncio.gather(self.down.run(), self.up.run())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(Path(__file__).with_name("config.yaml")))
    ap.add_argument("--delay", type=float, default=None, help="override comms_delay_real_s (REAL seconds)")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--sim-port", type=int, default=8765)
    ap.add_argument("--panel-port", type=int, default=8766)
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--record-dir", default="runs")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    cfg = {"time_compression": 60, "comms_delay_real_s": 60, "decision_interval_sim_s": 1.0,
           "gamma": 2.0, "mission_margin": 1.15}
    if Path(args.config).exists():
        cfg.update(yaml.safe_load(Path(args.config).read_text(encoding="utf-8")) or {})
    delay = args.delay if args.delay is not None else float(cfg["comms_delay_real_s"])
    rec = Recorder(args.record_dir, "stub", {"config": cfg, "delay_real_s": delay, "wall_start": time.time()}) if args.record else None
    brain = StubBrain(cfg, delay, rec)
    try:
        asyncio.run(brain.serve(args.host, args.sim_port, args.panel_port))
    except KeyboardInterrupt:
        pass
    finally:
        if rec:
            rec.close()


if __name__ == "__main__":
    main()
