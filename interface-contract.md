# interface-contract.md — process boundaries & message schemas

**Freeze this before writing feature code.** Jabin builds BRAIN, Dev builds SIM + PANEL. Both develop against stubs; neither blocks the other.
**v1 · 2026-09-07**

---

## 0. The three processes

```
┌─────────────┐  observation (10 Hz, JSON + JPEG)   ┌─────────────┐
│     SIM     │ ──────────────────────────────────► │    BRAIN    │
│  Godot      │ ◄────────────────────────────────── │   Python    │
│  world +    │  action (≤1 Hz, JSON)               │  perception │
│  rover body │                                     │  + policy   │
│  + camera   │                                     └──────┬──────┘
└─────────────┘                                            │ telemetry
                                                           │ (DELAYED)
                                              ┌────────────▼────────────┐
                                              │        PANEL            │
                                              │  web UI, scientist side │
                                              └────────────┬────────────┘
                                                           │ uplink (DELAYED)
                                                           └──────► BRAIN
```

**Transport:** WebSocket on localhost. `ws://localhost:8765` sim↔brain, `ws://localhost:8766` brain↔panel. JSON text frames for control, binary frames for images. Panel is a browser page, so WebSocket costs nothing extra there.

---

## 1. THE RULE (violate this and the project is dead)

> **BRAIN receives pixels, its own pose, and its own budget. Nothing else.**

BRAIN must **never** receive: object lists, ground-truth positions, object classes, novelty labels, or anything behind/outside the camera frustum. If BRAIN can answer "what's over that ridge," the identification half of the PS is gone and the demo is a pathfinding toy.

**Permitted non-visual inputs, and why each is legitimate:**

| Input | Why a real rover has it |
|---|---|
| `pose` | wheel odometry + IMU |
| `budget.remaining` | its own battery telemetry |
| `hazard.range_m` | proximity/hazard sensing (reactive only — not a map) |
| `mission.assigned_markers` | came down on the last uplink from Earth |
| `sim_time` | onboard clock |

Everything else about the world must be **derived from the image** by BRAIN's own perception stack.

---

## 2. SIM → BRAIN : `observation` (10 Hz)

Sent as a JSON text frame immediately followed by one binary frame (JPEG, rover camera viewport).

```json
{
  "type": "observation",
  "seq": 1423,
  "sim_time": 4821.5,
  "pose": { "x": 132.4, "y": 88.1, "heading_deg": 47.2 },
  "budget": { "remaining": 742.0, "capacity": 1000.0, "unit": "Wh", "simulated": true },
  "hazard": { "range_m": 3.8, "bearing_deg": 2.0 },
  "mission": {
    "assigned_markers": ["M01", "M02", "M03"],
    "confirmed_markers": ["M01"]
  },
  "state": "AUTONOMOUS",
  "camera": { "w": 640, "h": 480, "hfov_deg": 60, "encoding": "jpeg" }
}
```

`hfov_deg` matters — BRAIN needs it to turn a bounding-box centre into a bearing. Keep it fixed for v1.

---

## 3. BRAIN → SIM : `action` (≤1 Hz)

```json
{
  "type": "action",
  "in_reply_to_seq": 1423,
  "sim_time": 4821.5,
  "decision": "drive_to_target",
  "target": { "label": "M02", "kind": "marker", "bearing_deg": 12.4, "est_range_m": 18.2 },
  "drive": { "heading_deg": 59.6, "speed": 0.6 },
  "audit": { "...": "see §5" }
}
```

**`decision` enum — the complete action space. Do not add to it without both of you agreeing.**

| Value | Meaning |
|---|---|
| `drive_to_target` | commit and drive straight-line toward `target` |
| `investigate` | stop at target, dwell, capture, spend budget |
| `continue` | keep current heading (nothing worth re-committing to) |
| `survey` | rotate in place to widen the view |
| `report` | enter the command-cycle report window |
| `hold` | stop and wait (awaiting uplink, or safety veto with no fallback) |

**Reactive avoidance stays in SIM.** If `hazard.range_m` is below the safety limit, SIM steers around the obstacle while keeping BRAIN's committed target. BRAIN does not path-plan — that's PS 03. Say this out loud if asked.

---

## 4. Budget accounting — SIM owns it

BRAIN never decrements budget itself; it only reads `budget.remaining`. SIM is the single source of truth, which keeps the two sides from drifting.

```
drive:        cost_rate_drive  × distance_travelled
investigate:  cost_rate_dwell  × dwell_time
idle:         cost_rate_idle   × elapsed
```

BRAIN's cost *estimates* (used in the utility function) are predictions of these. Mismatch between predicted and actual is honest and worth showing.

---

## 5. The audit record — the novelty artifact

This is the thing that makes an uncertifiable value judgment trustworthy. It goes in every `action`, and it's what the panel renders. Design it well; it *is* the demo.

```json
"audit": {
  "candidates": [
    { "id": "M02", "stream": "mission",
      "p": 10, "c": 0.58, "value_raw": 5.80, "value_weighted": 5.80,
      "cost_est": 3.31, "U": 1.75 },
    { "id": "A07", "stream": "curiosity",
      "n": 0.82, "c": 0.71, "value_raw": 0.58, "value_weighted": 0.07,
      "cost_est": 1.14, "U": 0.06 }
  ],
  "budget": { "remaining": 742.0, "required_for_mission": 490.0 },
  "slack": 0.34,
  "gamma": 2.0,
  "w_curiosity": 0.12,
  "gate": { "result": "pass", "post_action_reserve": 1.52, "margin": 1.15 },
  "chosen": "M02",
  "text": "Marker M02 (U=1.75) over anomaly A07 (U=0.06). Anomaly raw value 0.58, but slack 0.34 at gamma 2 gives curiosity weight 0.12 -> weighted 0.07. Staying on task."
}
```

**Arithmetic must close, and a judge may check it.** `value_weighted` = `value_raw` for mission candidates, and `w_curiosity x value_raw` for curiosity candidates. `U` = `value_weighted / cost_est`. `post_action_reserve` = `(remaining - cost_est) / required_for_mission_after`. Emit both raw and weighted: raw alone hides the policy, weighted alone hides what was given up.

```
```

`text` is written by BRAIN, not the panel — the rover explains itself in its own words. That's the point.

---

## 6. BRAIN → PANEL : `telemetry` (DELAYED)

Every action, plus a thumbnail and any anomaly crops, pushed into a delay queue.

```json
{
  "type": "telemetry",
  "generated_at": 4821.5,
  "delivered_at": 4881.5,
  "pose": { "...": "" },
  "state": "AUTONOMOUS",
  "audit": { "...": "as §5" },
  "mission": { "confirmed_markers": ["M01"], "total": 3 },
  "attachments": [
    { "kind": "thumbnail", "frame_ref": "f_1423" },
    { "kind": "anomaly_crop", "id": "A07", "novelty": 0.82 }
  ]
}
```

**Delay is enforced in BRAIN's outbound queue**, one place only. Never delay in the panel — a judge asking "is the delay real?" needs one file to look at.

## 7. PANEL → BRAIN : `uplink` (DELAYED)

```json
{
  "type": "uplink",
  "issued_at": 4820.0,
  "arrives_at": 4880.0,
  "command": "abort_investigation",
  "payload": { "reason": "operator override" }
}
```

Commands: `ack_report` · `reassign_markers` · `abort_investigation` · `force_investigate` · `set_gamma` · `halt`.

**The late-interrupt beat:** an uplink issued at T lands at T+delay. If BRAIN already moved on, it logs `uplink_stale` and continues. Engineer this into the demo deliberately — the operator hits stop, and it arrives too late. That single moment argues the case for autonomy better than any slide.

## 8. Command cycle (the report window)

```
AUTONOMOUS ──(report_interval elapsed)──► REPORTING ──► AWAITING_UPLINK
      ▲                                                        │
      └──────────────── ack_report received ◄──────────────────┘
```

In `AWAITING_UPLINK` the rover holds. This is the real rover cadence (uplink every 1–3 sols), and it makes the human's role visible without letting them drive.

---

## 9. Config — one shared file, both processes read it

```yaml
time_compression: 60        # 1 real second = 60 sim seconds
comms_delay_real_s: 60      # one-way, REAL seconds (the demo's gut-punch)
decision_interval_sim_s: 1.0
observation_rate_hz: 10
report_interval_sim_s: 7200 # 2 sim-hours
gamma: 2.0                  # curiosity temperament
alpha_distance: 1.0
beta_time: 1.0
mission_margin: 1.15
```

**The two demo runs are the same binary with different config + start budget.** Stay-run: low budget, high gamma. Deviate-run: healthy budget, low gamma. Nothing else changes — that's what makes it a policy and not a script, and you should say exactly that.

---

## 10. Stubs — build these first, today

- **`stub_sim.py`** — replays a folder of recorded/rendered frames with fake pose and a draining budget. Lets BRAIN be built with no Godot at all.
- **`stub_brain.py`** — returns `continue` with a random target and a canned audit record. Lets SIM and PANEL be built with no perception at all.

Both emit schema-valid messages. Whoever finishes first is never blocked on the other.

## 11. Definition of done (integration checkpoints)

1. Stub sim → real brain → decisions printing to console
2. Real sim → real brain → rover physically moving in Godot
3. Telemetry reaching the panel with visible delay
4. Uplink round-trip, including one stale interrupt
5. Both demo runs recorded end-to-end
