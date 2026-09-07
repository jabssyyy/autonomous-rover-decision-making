"""stub_panel.py -- CLI stand-in for the PANEL (interface-contract.md sections 6, 7).

Connects to ws://<host>:8766, validates every telemetry message, prints the
measured REAL delay, collects the binary attachments that follow each message
(in the order of msg["attachments"]), and can fire one late uplink.

  python stub_panel.py                                   # local BRAIN
  python stub_panel.py --url ws://192.168.1.20:8766      # Jabin's laptop over LAN
  python stub_panel.py --send abort_investigation --after 10
  python stub_panel.py --send set_gamma --value 0.5
  python stub_panel.py --out panel_dump                  # save thumbnails/crops
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from contract import ContractViolation, validate_telemetry, validate_uplink


async def send_late(ws, args, last: dict) -> None:
    await asyncio.sleep(args.after)
    delay_sim = (last.get("clock", {}).get("delay_real_s") or 60.0) * args.time_compression
    payload: dict = {"reason": "operator override"}
    if args.send == "set_gamma":
        payload = {"gamma": float(args.value)}
    elif args.send == "reassign_markers":
        payload = {"assigned_markers": [m.strip() for m in str(args.value).split(",")]}
    elif args.send == "force_investigate":
        payload = {"target": str(args.value)}
    msg = {"type": "uplink", "issued_at": last["delivered_at"],
           "arrives_at": last["delivered_at"] + delay_sim, "command": args.send, "payload": payload}
    validate_uplink(msg)
    await ws.send(json.dumps(msg))
    print(f">> uplink sent: {args.send} {payload} (issued_at sim {msg['issued_at']:.1f}; "
          f"BRAIN will apply it {delay_sim / args.time_compression:.0f} real s from now)")


async def run(args) -> None:
    out = Path(args.out) if args.out else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    async for ws in connect(args.url, max_size=None, open_timeout=5):
        print(f"connected to {args.url}")
        n, pending, expect, sent = 0, None, 0, False
        try:
            async for msg in ws:
                if isinstance(msg, str):
                    t = json.loads(msg)
                    try:
                        validate_telemetry(t)
                    except ContractViolation as e:
                        print(f"!! INVALID telemetry: {e}")
                        continue
                    n += 1
                    clk = t.get("clock", {})
                    a = t["audit"]
                    print(f"[{n:4d}] sim gen {t['generated_at']:8.1f} -> del {t['delivered_at']:8.1f} | "
                          f"real delay {clk.get('delay_real_s', float('nan')):6.2f}s | {t['state']:15s} | "
                          f"chosen {str(a['chosen']):5s} slack {a['slack']:5.2f} w_c {a['w_curiosity']:4.2f} | "
                          f"{len(t['attachments'])} att | {a['text'][:80]}")
                    pending, expect = t, len(t["attachments"])
                    if args.send and not sent:
                        sent = True
                        asyncio.create_task(send_late(ws, args, t))
                else:
                    if pending is None or expect <= 0:
                        print("!! unexpected binary frame (no attachments pending)")
                        continue
                    att = pending["attachments"][len(pending["attachments"]) - expect]
                    expect -= 1
                    if out:
                        name = att.get("frame_ref") or f"{att['kind']}_{att.get('id')}_{n}"
                        (out / f"{name}.jpg").write_bytes(msg)
        except ConnectionClosed:
            print("BRAIN link closed; reconnecting...")
            continue


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="ws://localhost:8766")
    ap.add_argument("--out", default=None)
    ap.add_argument("--send", default=None, choices=["ack_report", "reassign_markers", "abort_investigation",
                                                       "force_investigate", "set_gamma", "halt"])
    ap.add_argument("--after", type=float, default=5.0, help="real seconds after the first telemetry")
    ap.add_argument("--value", default=None, help="gamma | comma list of markers | target id")
    ap.add_argument("--time-compression", type=float, default=1.0)
    args = ap.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
