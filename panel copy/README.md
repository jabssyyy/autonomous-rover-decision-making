> Current Windows launch: serve this actual `panel copy/` directory with
> `python -m http.server 8000 --directory "panel copy"` from the repository root,
> then open http://127.0.0.1:8000/. Runtime time compression defaults to 1.
> Current preserved live BRAIN has a 3-second delay; clock stamps are authoritative.
> See ../phase5-panel-integration.md. Older setup examples below are historical.

# panel/ — MISSION CONTROL, EARTH SIDE

The scientist's console. Three files, no build step, no npm, no CDN, no webfont —
open `index.html` and it runs.

```
panel/
  index.html    structure
  style.css     the console
  app.js        link + render + uplink        ← speaks interface-contract.md §6/§7
  demo.js       synthetic mission source      ← ONLY loaded by ?demo=1
```

---

## 1. What this screen is

**Earth, 60 real seconds behind the rover.** Everything on it already happened.
It exists to make two things undeniable to a judge standing across the room:

1. **The humans are too late to help.** The delay banner, the light-time lane and
   the "IN FLIGHT — NOT YET VISIBLE" counter all say the same thing three ways.
2. **The rover explains itself.** Every decision arrives with the arithmetic that
   produced it, and the panel *re-derives that arithmetic independently* and marks
   each candidate row ✓ or ✗. A judge can check `U = value_weighted / cost_est` by
   hand from what is on the screen, and if BRAIN's numbers ever stopped closing,
   this screen would say so out loud.

### It deliberately does NOT show a live camera

Jabin's screen is the truth, now: god view, rover camera, detection overlay.
This screen is Earth, 60 s ago: only what the rover chose to downlink. If both
screens showed the same thing at the same moment there would be no delay to
demonstrate. Say that out loud if asked — it is a design decision, not a gap.

---

## 2. Running it

### On the day (served from Jabin's laptop)

```
http://<jabin-ip>:8000/panel/
```
The page derives the WebSocket host from the URL it was served from, so nothing
needs editing. `localhost` never appears in the code (panel.md §8).

Overrides, all optional:

| query param | default | meaning |
|---|---|---|
| `?ws=ws://host:8766` | — | full WebSocket URL, wins over everything |
| `?host=` `&port=` | page host, 8766 | host/port separately |
| `?delay=` | 60 | *display* fallback only, until the first packet lands |
| `?tc=` | 60 | `time_compression`, for the sim→real fallback |
| `?cap=` | 1000 | battery capacity in Wh, for the gauge |
| `?demo=1` | off | synthetic source, see §5 |

Keys: **A** abort investigation · **H** halt · **F** fullscreen · **Esc** dismiss alarm.

### Without Jabin

```bash
cd panel && python3 -m http.server 8000
open "http://127.0.0.1:8000/?demo=1"
```

### Against the stubs in this repo

```bash
cd brain
python3 stub_brain.py --delay 5          # :8765 for SIM, :8766 for PANEL
python3 stub_sim.py                      # drives it
# then open the panel with ?host=127.0.0.1&port=8766
```
Verified working end to end against exactly this: 110 packets, delay pinned at
5.00 s off BRAIN's own stamps, thumbnails paired to their attachments, ground
track drawn, and a late `abort_investigation` resolving to **UPLINK STALE** with
the same sim times BRAIN printed in its log.

---

## 3. The wire, exactly as BRAIN sends it

One JSON text frame, then **one binary frame per entry in `attachments`, in order**:

```
{"type":"telemetry", ..., "attachments":[{"kind":"thumbnail",...},{"kind":"anomaly_crop",...}]}
<JPEG bytes>      ← the thumbnail
<JPEG bytes>      ← the crop
```

The panel pairs them positionally and turns each blob into an object URL. Old URLs
are revoked, so a two-hour run does not leak the heap.

### The delay is never taken from this machine's clock

```js
const lag = msg.clock.delay_real_s;    // BRAIN's stamps. authoritative.
```
Falling back, only if `clock` is absent, to `(delivered_at - generated_at) / time_compression`.
`Date.now()` is used for exactly two cosmetic things: the "arrived 0.4 s ago"
counter and the local uplink countdown. The two laptops' wall clocks differ by
seconds and a judge watching a "60 s" delay read 63 s would be right to wonder
what else is approximate.

### One small ask for BRAIN (optional)

When an uplink lands, BRAIN already logs `uplink_applied` / `uplink_stale`. If it
also pushes that down the panel socket:

```json
{"type": "uplink_ack", "command": "abort_investigation", "result": "uplink_stale"}
```

the panel will show BRAIN's own verdict instead of its inference. **It is not
required.** Without it the panel works out the fate of every command itself, from
the first telemetry generated at or after the command's arrival time — which is
the honest shape of the problem anyway: you cannot know whether your stop button
mattered until one further delay has passed. Both paths were tested; they agreed.

---

## 4. Reading the screen

| region | what it is |
|---|---|
| **delay banner** | one-way lag, from BRAIN's stamps, with measured jitter |
| **light-time lane** | every dot is a packet crossing the gap. Dots short of the right wall are decisions that **already happened** and that nobody in the room can see yet |
| **last downlink** | the frame the rover chose to send, with BRAIN's detection overlay already burnt in |
| **decision log** | the audit record in full — `value_raw` **and** `value_weighted`, cost, `U`, the slack line, the gate. Colour-coded by decision so the run's shape reads from across the room. Identical consecutive decisions coalesce into one card with a packet count, so 5 Hz of telemetry stays readable |
| **power budget** | remaining vs the mission reserve (red dashes), slack, γ, and `w = slack^γ` plotted with the current point marked |
| **ground track** | the only map Earth has: the rover's own delayed pose, plus a pin wherever a marker was confirmed |
| **uplink console** | in-flight countdown → LANDED → APPLIED/STALE |

Everything on this screen is derived from the contract's telemetry. There are no
decorative fake readouts — if a number is there, BRAIN sent it or the panel
computed it from something BRAIN sent.

---

## 5. Demo mode (`?demo=1`)

`demo.js` fabricates the whole mission client-side: a procedural world, a rover
driving it under the same policy shape, a camera that renders what the rover sees
(markers, anomalies, rocks, detection boxes), audit records whose arithmetic
closes, and a real delay line in front of all of it. It exists so this screen can
be built and rehearsed with no Godot, no BRAIN and no network.

It is **loud** about being fake: the link reads `SIMULATED SOURCE` in violet, the
tab title is `[DEMO]`, and the first log line says every number is synthetic.
Nothing auto-falls-back into demo mode — a dropped link shows `LINK LOST` and
retries once a second, forever. A panel that quietly started inventing telemetry
mid-demo would be the worst possible failure.

The two demo runs from `interface-contract.md` §9, same binary, different config:

```
?demo=1&gamma=4&budget=560      stay-run     — low budget, high γ, never deviates
?demo=1&gamma=0.7&budget=1000   deviate-run  — healthy budget, low γ, takes the detour
```

---

## 6. Network checklist (panel.md §8 — do this in Phase 2, not at 5 PM)

- Bind BRAIN to `0.0.0.0`, never `localhost`.
- Pre-create the Windows firewall rule in an admin PowerShell **before** the first
  run. If anyone clicks Cancel on the Security Alert pop-up, Windows writes a
  BLOCK rule for that `python.exe` and LAN access fails silently forever after.
- Use the Wi-Fi address from `ipconfig`. `192.168.56.1` is VirtualBox's
  host-only adapter and is unreachable from the Mac.
- Do not test with `ping` — Windows blocks inbound ICMP on the Public profile.
  Test with `curl -I http://<jabin-ip>:8000/`.
- If the Mac cannot load the page within five minutes, stop debugging the
  firewall: campus Wi-Fi commonly has AP/client isolation. Turn on Windows 11
  Mobile Hotspot, join the Mac to it, use `http://192.168.137.1:8000/`.
- The real safety net: everything runs on Jabin's laptop anyway. If the network
  dies mid-demo, open the panel in a second window on his machine. The second
  screen is a bonus, never a dependency.
