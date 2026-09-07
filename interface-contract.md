# interface-contract.md — current executable process boundary

**Phase 1 revision · 2026-09-07.** Owner of BRAIN: Jabin. SIM/PANEL: Dev.
This revision implements the planned scoring/cost corrections. Dev must pull the
updated shared files before Phase 2. No action enum or observation field was added.
Audit v2 extends the action/telemetry payload; old clients with strict v1 audit
validators need updating. Dev has not independently confirmed this revision yet.

## The input rule

BRAIN receives camera pixels, odometry, battery telemetry, reactive hazard range,
mission assignment/confirmation state, and a clock. It never receives scene objects,
rock labels, ground-truth positions, novelty labels, or a map. `brain/contract.py`
rejects unknown keys at every nested level of an observation.

Offline labels for Phase 3 training are not runtime observations.

## Endpoints and framing

- SIM connects to BRAIN at `ws://127.0.0.1:8765`.
- PANEL connects at `ws://<brain-host>:8766` (LAN binding is configurable).
- **Observation rate: 5 Hz. Every JSON text header is immediately followed by one
  binary JPEG.** There are no unpaired 10 Hz pose-only headers in this revision.
- BRAIN decides at most once per physics second. `time_compression` must be 1.
- Telemetry is a JSON text frame followed by one binary JPEG per attachment, in
  attachment order. Images are not base64 fields inside JSON.
- A second SIM connection is rejected. A reconnecting continuing mission must keep
  sequence and physics time increasing. Restart BRAIN to begin a new mission.
- SIM must stop motion and dwell on disconnect or after 2.5 s without a valid command.
  The Python stub implements this; Godot must implement it during Phase 2.

## Observation (exact existing shape)

```json
{
  "type": "observation", "seq": 42, "sim_time": 8.4,
  "pose": {"x": 1.0, "y": 2.0, "heading_deg": 30.0},
  "budget": {"remaining": 400.0, "capacity": 1000.0, "unit": "Wh", "simulated": true},
  "hazard": {"range_m": 99.0, "bearing_deg": 0.0},
  "mission": {"assigned_markers": ["M01", "M02", "M03"], "confirmed_markers": []},
  "state": "AUTONOMOUS",
  "camera": {"w": 640, "h": 480, "hfov_deg": 60, "encoding": "jpeg"}
}
```

Immediately send the corresponding JPEG. Its decoded dimensions must match the
header. Marker dictionary is DICT_4X4_50; numeric ID 2 becomes M02. Printed black
square side = `marker_side_m` (0.8 m); the white quiet zone is outside that width.

## Action

Fields: `type="action"`, `in_reply_to_seq`, `sim_time`, `decision`, `target`, `drive`,
`audit`. `target` is null or `{label, kind, bearing_deg, est_range_m}`. Kinds remain
`marker`, `rock`, `anomaly`; rock/anomaly is a presentation distinction derived
from novelty, not a detector class. `drive` is `{heading_deg, speed}` with speed [0,1].

| Decision | SIM behavior |
|---|---|
| `drive_to_target` | Drive toward the supplied absolute heading; reactive avoidance stays in SIM |
| `investigate` | Stop and dwell at the selected rock; repeated commands do not reset active dwell |
| `continue` | Retain supplied heading/speed (legacy stub support) |
| `survey` | Rotate in place; speed zero |
| `report` | Stop for report transition |
| `hold` | Stop motion and cancel active dwell |

For real BRAIN audit v2, target label equals `audit.chosen`. Holds, surveys, and
reports have null target/chosen and zero drive speed. A marker is confirmed by SIM
only after BRAIN commits, the rover arrives, and 3 seconds of confirmation dwell pass.

## Audit v2

`audit.version = 2`. Real BRAIN emits v2. Readers retain support for unversioned v1
recordings and the canned `stub_brain.py` audit; v1 is not evidence for the corrected
policy. Exact executable v2 examples: [brain/phase1-examples.json](brain/phase1-examples.json).

Common candidate fields:

- `id`, `stream` (mission or curiosity), `c` (confidence proxy or detector score).
- Mission has `p=10`; curiosity has `n` in [0,1] and `k=10`.
- `value_raw = p*c` for mission; `k*n*c` for curiosity.
- `value_weighted = value_raw` for mission; `w_curiosity*value_raw` for curiosity.
- `cost_wh`: predicted physical energy use.
- `cost_est = max(cost_wh / audit.cost_unit_wh, audit.cost_est_floor)`.
- `U = value_weighted / (cost_est + audit.eps)`.
- `required_for_mission_after`: estimated remaining obligation from this target's
  estimated location; excludes the selected marker only for a mission candidate.
- `eligible`: both `B >= cost_wh` and `B-cost_wh >= required_after*margin` pass.

Audit-level fields: `version`, `candidates`, `budget` (`remaining`,
`required_for_mission`), `slack`, `gamma`, `w_curiosity`, `eps=0.001`,
`cost_unit_wh=10`, `cost_est_floor=0.5`, `gate`, `chosen`, `text`.

The gate describes the **selected action**, not a rejected top-scoring candidate:

```json
{
  "result": "pass",
  "post_action_reserve": 2.2485549132947975,
  "margin": 1.15,
  "cost_wh": 11.0,
  "required_for_mission_after": 173.0,
  "reserve_wh": 389.0
}
```

This example has B=400. Recompute `reserve_wh = B - cost_wh` and
`post_action_reserve = reserve_wh / required_for_mission_after`. A zero remaining
mission requirement has a **null ratio**, never infinity or an invented sentinel.
Use the Wh inequality to decide pass/fail. With no selection, gate cost is zero and
required-after is the current mission estimate. Gate pass does not imply movement:
other vetoes can require hold. `text` explains the actual decision and relevant veto.
Calculations are emitted without decision-time rounding; the PANEL may format display.

## Budget and time

SIM alone charges actual energy. Current shared `brain/config.yaml` values:

| Setting | Value |
|---|---:|
| time_compression | 1 |
| observation_rate_hz | 5 |
| decision_interval_sim_s | 1 |
| comms_delay_real_s | 60 |
| drive_rate_wh_per_m | 1 |
| dwell_rate_wh_per_s | 1 |
| idle_rate_wh_per_s | 0.01 |
| investigate_dwell_sim_s | 5 |
| confirm_dwell_sim_s | 3 |
| max_speed_m_per_s | 1 |
| marker_side_m | 0.8 |
| mission_margin | 1.15 |

BRAIN predicts straight-line drive plus dwell. Idle spending, avoidance distance,
and perception error can make actual expenditure differ; the reserve gate constrains
estimates, not a guaranteed route. `alpha_distance`/`beta_time` remain legacy config
keys and no longer rescale physical energy estimates.

## Telemetry and measured delay

Fields: `type="telemetry"`, `generated_at`, `delivered_at` (physics times), `pose`,
`state`, `audit`, `mission` (`confirmed_markers`, `total`), and `attachments`.
Each attachment is either `{kind:"thumbnail", frame_ref}` or
`{kind:"anomaly_crop", id, novelty}`; one JPEG follows for each.

BRAIN adds `clock: {generated_real_s, delivered_real_s, delay_real_s}` at delivery.
These are measured with its monotonic clock; PANEL displays `clock.delay_real_s`.
Do not compute lag from the other laptop's wall clock. No `wall_generated_at`,
`wall_delivered_at`, or base64 image fields are emitted in this revision.

## Uplink and command cycle

```json
{
  "type": "uplink", "issued_at": 8.4, "arrives_at": 68.4,
  "command": "abort_investigation", "payload": {"reason": "operator override"}
}
```

Both time fields are required for v1 compatibility; `arrives_at` from the client is
advisory. BRAIN schedules arrival from receipt using the real delay queue and replaces
`arrives_at` when applying it. PANEL can use the last delivered physics time as
`issued_at`; it represents the operator's delayed view, not a synchronized onboard clock.

Commands: `ack_report`, `reassign_markers` (`assigned_markers`, including []),
`abort_investigation`, `set_gamma` (`gamma`, clamped to [0.1,5]), `halt`.
`force_investigate` remains an accepted legacy command name but is explicitly
unsupported in Phase 1: it logs a note/stale event and executes no override.
An abort with no active investigation is stale. Aborts do not complete or learn a rock;
a 30-second location cooldown prevents immediate automatic restart.

Report cycle: AUTONOMOUS → REPORTING → AWAITING_UPLINK; then `ack_report` restores
AUTONOMOUS. Investigation finishes before a due report starts. A halt is sticky;
there is no general-purpose resume command in this version. Explain this in the UI.

## Phase 2 checks still required with Dev

Real JPEG decoding, marker width/FOV/bearing alignment, continuous motion and dwell,
energy charges, reconnect/watchdog behavior, v2 audit rendering, binary attachment
ordering, and LAN connectivity. The Phase 1 Python tests do not certify Godot.
