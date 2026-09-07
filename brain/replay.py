"""replay.py -- if the live demo dies, replay a recorded run.

Two directions, both from a BRAIN run dir (runs/<stamp>_<tag>/):

  1) Re-drive the REAL brain from recorded observations (perception + policy run live):
        python stub_sim.py --replay runs/20260907_121000_deviate

  2) Push the recorded, already-delayed telemetry to the PANEL at the original real
     cadence, no BRAIN needed at all (serves :8766 itself):
        python replay.py runs/20260907_121000_deviate --speed 1.0 --wait
     --speed 3 plays 3x faster. --wait waits for the first panel before starting.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path

from websockets.asyncio.server import broadcast, serve

from contract import validate_telemetry
from runtime import dumps

log = logging.getLogger("replay")


async def run(args) -> None:
    run_dir = Path(args.run_dir)
    lines = (run_dir / "telemetry_delivered.jsonl").read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]
    log.info("loaded %d delivered telemetry records from %s", len(records), run_dir)
    panels: set = set()

    async def handler(ws):
        panels.add(ws)
        log.info("panel connected (%d)", len(panels))
        try:
            async for _ in ws:      # uplinks are accepted and ignored during replay
                pass
        finally:
            panels.discard(ws)

    async with serve(handler, args.host, args.port, compression=None):
        log.info("replay server on ws://%s:%d", args.host, args.port)
        if args.wait:
            while not panels:
                await asyncio.sleep(0.2)
        prev = None
        for rec in records:
            blobs = rec.get("_blobs", [])
            msg = {k: v for k, v in rec.items() if not k.startswith("_")}
            validate_telemetry(msg)
            t = msg.get("clock", {}).get("delivered_real_s")
            if prev is not None and t is not None:
                await asyncio.sleep(max(0.0, (t - prev) / args.speed))
            prev = t
            broadcast(panels, dumps(msg))
            for name in blobs:
                p = run_dir / "frames" / f"{name}.jpg"
                if p.exists():
                    broadcast(panels, p.read_bytes())
            log.info("sim %8.1f %-15s %s", msg["generated_at"], msg["state"], msg["audit"]["text"][:70])
        log.info("replay done; server stays up (Ctrl+C to exit)")
        await asyncio.Event().wait()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--wait", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
