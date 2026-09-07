> **Live PANEL integration, 2026-09-07:** Dev's b2e467c is merged. PANEL is
> served at http://127.0.0.1:8000/ against the existing BRAIN (classical perception,
> 3-second delay). Godot was left untouched. Wire/HTTP/JS checks passed; browser
> visual check and live interrupt rehearsal remain. See [instructions](phase5-panel-integration.md).

# panel.md — PANEL lane (Dev, build this SECOND)

> **Phase 1 handoff:** `interface-contract.md` now specifies audit v2 and binary JPEG
> attachments. Strict v1 readers must update; the canned stub still supports v1.
> BRAIN emits monotonic `clock` fields, not epoch wall fields. No static HTTP server
> is currently supplied by BRAIN/stub BRAIN; use `python -m http.server` for page
> development until that integration task is implemented. Browser work remains Dev's lane.

**v1 · 2026-09-07** · Owner: **Dev**. Runs in a browser on the MacBook; served from Jabin's laptop.
**Build `sim.md` first.** PANEL is deliberately second and it is the droppable lane — if it isn't ready, the delay gets narrated from BRAIN's console and the demo still lands. That is not a reason to treat it as unimportant: **this screen is where the judges see the rover think.**

**Read first:** `interface-contract.md` §5–§8 (audit record, telemetry, uplink, command cycle).

---

## 1. What the PANEL is

The **scientist's view from Earth — 60 real seconds behind the rover.**

Its whole job is to make two things undeniable:
1. The humans are **too late to help.** Everything on this screen already happened a minute ago.
2. The rover **explains itself.** Every decision arrives with the arithmetic that produced it.

```
Jabin's laptop (Windows)                    Dev's MacBook
┌──────────────────────────────┐           ┌────────────────────┐
│ Godot SIM ──127.0.0.1──┐     │           │                    │
│ Python BRAIN ◄─────────┘     │           │  Chrome fullscreen │
│   ├─ :8000  static files ────┼──LAN──────┼──►  the panel      │
│   └─ :8766  WebSocket    ◄───┼──LAN──────┼──►  interrupt      │
└──────────────────────────────┘           └────────────────────┘
```

### Division of labour

| Piece | Owner |
|---|---|
| `panel/index.html`, `panel/app.js`, `panel/style.css` | **Dev — this is your deliverable** |
| `brain/panel_server.py` (static HTTP :8000 + WS :8766) | Jabin |
| `brain/delay.py` (the 60 s queue, both directions) | Jabin |

You build the **page**. Jabin serves it. Develop against `stub_brain.py`, which serves the files and pushes canned but schema-valid telemetry — **you never wait on him.**

---

## 2. ⚠ The panel must NOT show the live camera

Tempting, and wrong. A live undelayed feed here destroys the entire point — the gap between the two laptops **is** the argument.

- **Jabin's screen = the truth, now.** God view + rover camera + detection overlay.
- **Your screen = Earth, 60 s ago.** Only what the rover chose to downlink.

If both screens show the same thing at the same time, there is no delay to demonstrate, and a judge will notice. Keep this screen strictly delayed. Say so if asked — it is a design decision, not a limitation.

---

## 3. Layout

```
┌────────────────────────────────────────────────────────────────┐
│  MISSION CONTROL — EARTH          ⏱ DELAYED 60s   ● LINK OK    │
├──────────────────────────┬─────────────────────────────────────┤
│  LAST DOWNLINK           │  DECISION LOG                       │
│  ┌────────────────────┐  │  ┌───────────────────────────────┐  │
│  │  thumbnail (JPEG)  │  │  │ t=4821  STAY ON TASK          │  │
│  └────────────────────┘  │  │ "Marker M02 (U=1.75) over     │  │
│  generated 4821.5        │  │  anomaly A07 (U=0.06)..."     │  │
│  arrived   4881.5        │  │  ┌─────────────────────────┐  │  │
│                          │  │  │ cand  val_raw  w   U    │  │  │
│  ANOMALY CROPS           │  │  │ M02   5.80  5.80  1.75  │  │  │
│  ┌────┐ ┌────┐           │  │  │ A07   0.58  0.07  0.06  │  │  │
│  │A07 │ │A03 │           │  │  └─────────────────────────┘  │  │
│  └────┘ └────┘           │  │  slack 0.34 · γ2.0 · w_c 0.12 │  │
│  n=0.82   n=0.44         │  │  gate PASS                    │  │
├──────────────────────────┤  └───────────────────────────────┘  │
│  BUDGET  ▓▓▓▓▓▓░░░ 742Wh │  (scrolls, newest on top)           │
│  needed for mission 490  │                                     │
│  MARKERS  ●●○  2/3       │                                     │
├──────────────────────────┴─────────────────────────────────────┤
│         [ ABORT INVESTIGATION ]   [ HALT ]                     │
│         ⚠ commands take 60s to arrive                          │
└────────────────────────────────────────────────────────────────┘
```

**Priority order if you run short of time:** decision log → delay clock → budget gauge → interrupt button → thumbnails → anomaly crops. The decision log is the demo; everything else is supporting cast.

---

## 4. The decision log — build this properly

This is the artifact that makes an uncertifiable value judgment trustworthy. **Render the arithmetic, not a summary.** A judge should be able to check `U = value_weighted / (cost_est + audit.eps)` for v2 by hand from what is on screen.

For each `audit` record (schema in `interface-contract.md` §5, with the `plan.md` §6 #14 correction):

- **The rover's own sentence** (`audit.text`) in plain prose, prominent. BRAIN writes this, not you — the rover explaining itself in its own words is the point.
- **A candidates table**: `id`, `stream`, `value_raw`, `value_weighted`, `cost_wh`, `cost_est`, `U`. Highlight the chosen row.
- **The slack line**: `budget.remaining`, `required_for_mission`, `slack`, `gamma`, `w_curiosity`.
- **The gate**: pass/fail, `reserve_wh`, `cost_wh`, `post_action_reserve`, `margin`, `required_for_mission_after`. A null ratio means no remaining mission requirement; show "not applicable," not zero.
- Use `audit.version === 2` to enable the extended fields. The legacy stub lacks them.
- HALT is sticky in this version; there is no general resume button/command.

**Show both `value_raw` and `value_weighted`.** Raw alone hides the policy; weighted alone hides what was given up. The gap between them is the rover's judgment made visible — that column *is* the contribution.

Colour the decision by kind (`drive_to_target` / `investigate` / `survey` / `report` / `hold`) so a judge can read the run's shape at a glance from across the room.

---

## 5. The delay — display it honestly

⚠ **Never compute the delay from the Mac's clock.** The two laptops' wall clocks differ by seconds, and a judge watching a "60 s" delay read 63 s will reasonably wonder what else is approximate.

BRAIN stamps a monotonic `clock` object at delivery. Display:
```js
const lagSeconds = msg.clock.delay_real_s;   // authoritative
```
Use `Date.now()` **only** for the cosmetic "arrived 4 s ago" counter, never for the delay itself.

Make the delay banner large and always visible. A judge should never have to ask whether the delay is real.

**The delay is 60 REAL seconds.** The old compressed-clock ambiguity is resolved:
physics runs at 1x, and BRAIN emits a monotonic `clock` object. Use `clock.delay_real_s`.

---

## 6. The interrupt — the beat that wins the demo

Two buttons: **ABORT INVESTIGATION** (`abort_investigation`) and **HALT** (`halt`).

```js
ws.send(JSON.stringify({
  type: "uplink",
  issued_at: lastTelemetry.delivered_at,
  arrives_at: lastTelemetry.delivered_at + 60,
  command: "abort_investigation",
  payload: { reason: "operator override" }
}));
```

**The uplink is delayed too**, in BRAIN's queue — not here. Show it clearly:

1. Button pressed → a visible **"COMMAND SENT — arrives in 60s"** countdown.
2. When it lands, BRAIN reports whether it was applied or logged **`uplink_stale`**.
3. Render `uplink_stale` prominently. *That* is the moment: the operator hit stop, and the rover had already decided.

Rehearse it with Jabin until the timing is reliable (`plan.md` Phase 5). It argues the case for autonomy better than any slide.

---

## 7. Stack — no build step

Vanilla HTML + CSS + JS. No React, no bundler, no `npm`. Three files Jabin drops into `panel/` and serves. Anything you'd reach for a framework for, you don't need here.

CDN libraries only if they earn their place. The layout above is plain CSS grid.

**Thumbnails:** Each telemetry JSON header is followed by one binary JPEG per attachment, in order. Set `ws.binaryType = "arraybuffer"`, make a JPEG Blob for each attachment, and use object URLs for images (revoke replaced URLs). The payload has no base64 image fields.

**Reconnect:** if the socket drops, retry every 1 s and show `● LINK LOST`. Campus wifi will drop at least once today.

---

## 8. ⚠ Networking — where this lane actually fails

The page is trivial. Getting the Mac to reach Jabin's laptop is the real work. **Test it in Phase 2, not at 5 PM.**

**Bind to `0.0.0.0`, never `localhost`.** `interface-contract.md` §0 literally says `ws://localhost:8766` — that string must not survive into the code, or nothing outside Jabin's laptop can connect.

**The Windows firewall trap.** On first listen, Windows shows a *Security Alert* pop-up. **If anyone clicks Cancel, Windows writes a BLOCK rule for that `python.exe` and LAN access silently fails forever after** — and you will debug the wrong layer for an hour. Have Jabin pre-create the rule in an admin PowerShell before the first run.

**Use the right IP.** `ipconfig` on Jabin's laptop lists several. `192.168.56.1` is the VirtualBox Host-Only adapter and is unreachable from the Mac. You want the Wi-Fi (or hotspot) address.

**Do not test with `ping`.** Windows blocks inbound ICMP echo on the Public profile by default, so `ping` fails even when port 8000 is perfectly reachable. Test with:
```bash
curl -I http://<jabin-ip>:8000/
```

**Fallback — do not fight the campus network.** If the Mac can't load the page within five minutes, stop debugging: turn on **Windows 11 Mobile Hotspot** on Jabin's laptop (Settings → Network & internet → Mobile hotspot), join the Mac to it, and use `http://192.168.137.1:8000/`. Campus Wi-Fi commonly has AP/client isolation, which no amount of firewall work will fix.

**And the real safety net:** everything runs on Jabin's laptop anyway. If the network dies mid-demo, open the panel in a second window on his machine. The second screen is a bonus, never a dependency.

---

## 9. Python API gotcha (for when you read Jabin's server)

AI coding agents reliably emit the **legacy** `websockets` API from training data:
```python
import websockets                                  # ✗ legacy
async def handler(websocket, path): ...            # ✗ two arguments
```
On `websockets` ≥ 14 the handler takes **one** argument and lives in `websockets.asyncio.server`:
```python
from websockets.asyncio.server import serve        # ✓
async def handler(websocket): ...                  # ✓ one argument
```
The verified BRAIN environment is the project Python 3.13.5 venv with `websockets`
17.1. Use the single-argument handler already implemented in BRAIN.

---

## 10. Done checklist

- ☐ Loads from `stub_brain.py` with no Jabin dependency
- ☐ Decision log renders the full candidates table; `U` checks out by hand
- ☐ Both `value_raw` and `value_weighted` shown
- ☐ Delay computed from BRAIN's monotonic clock fields, not the Mac's clock
- ☐ Delay banner visible at a glance from across a room
- ☐ Interrupt sends, shows a countdown, and renders `uplink_stale` loudly
- ☐ Reconnects after a dropped socket
- ☐ **Reachable from the Mac over LAN, tested with `curl -I`**
- ☐ Readable on a projector — large type, high contrast, no thin greys
