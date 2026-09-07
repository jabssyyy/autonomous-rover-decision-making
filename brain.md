> **Current Phase 3 result:** Rock detector trained on 1,500 images, held-out
> mAP50 0.8979, installed and tested with real Godot. Novelty calibration remains
> incomplete. See [measured results](phase3-results.md). Older status notes below are historical.

> **Integration update, 2026-09-07:** Dev's `151c4a0` is merged locally.
> Real Godot + BRAIN acceptance passed: 525 frames, 96 validated actions,
> M02 confirmed, disconnect stop and reconnect verified. See
> [phase2-integration.md](phase2-integration.md). Initial marker integration
> is established; all-marker missions, browser PANEL and trained rocks remain pending.

﻿# brain.md — BRAIN lane (Jabin)

## What BRAIN now does

BRAIN receives a camera JPEG, odometry, battery telemetry, hazard range, and mission
state. `contract.py` rejects other fields at every nested observation boundary.
It never receives the SIM's rock list or target positions. Offline training labels
are a separate Phase 3 task and must never be added to runtime observations.

The loop is: pixels → detections → appearance memory → utility and reserve check →
action → new pixels. The action's audit is the explanation of the actual command,
including holds and ongoing investigations, rather than an unrelated top-ranked target.

## Files and responsibilities

| File | Responsibility |
|---|---|
| `brain/main.py` | WebSocket servers, perception worker, decision cadence, delayed uplinks/downlinks |
| `brain/contract.py` | Exact message whitelists; legacy audit reader and strict audit v2 arithmetic |
| `brain/perception.py` | ArUco, rock proposals, tracking, appearance encoder, overlay |
| `brain/novelty.py` | Bounded nearest-neighbor memory, calibration, warm-up, pending admission |
| `brain/policy.py` | Mission estimates, candidate scoring, gates, commitment, investigation lifecycle |
| `brain/runtime.py` | Newest-frame mailbox, real-time delay, background recording |
| `brain/config.yaml` | Shared physics rates, marker width, timing, gamma, reserve margin |
| `brain/brain.yaml` | BRAIN-only perception, policy, and port settings |

Run with the root `.venv` (Python 3.13.5). CUDA and pretrained ResNet18 execution
are verified on the RTX 5060. `--no-yolo --no-torch` retains the tested CPU fallback.

## Perception

ArUco uses `DICT_4X4_50`; dictionary generation and detection were executed on
OpenCV 4.14.0. Camera width/height must match the decoded JPEG. Bearing is
`atan((cx - width/2) / focal_px)`; marker range is `focal_px * marker_width / pixel_width`.
The marker's black square is 0.8 m wide; a quiet zone is outside that physical width.

ArUco has no calibrated confidence probability. The explicitly named proxy is:
`(hits in last 5 processed frames / 5) * min(1, apparent_width / 48)`.
Missing detections lower the history score. There is no policy confidence cutoff.
Detector proposal thresholds and geometric filters still exist; do not claim otherwise.

Rock proposals currently use saturation blobs. YOLO is loaded only if the local
`brain/weights/rock.pt` exists and has exactly one class named `rock`. A stock COCO
model is not substituted or downloaded as a rock detector. The learned detector
remains Phase 3. The blob method is a prototype and needs evaluation on Dev's scene.

Rock tracking compares heading-corrected angular bearings, with one box per track
per frame. This improves stability during rotation; it is still a simple tracker,
not robust multi-object mapping. Visited-position suppression also helps after IDs change.

## Appearance memory

Default encoder: pretrained ImageNet ResNet18, classifier removed, 160-pixel crops,
512-dimensional unit vectors. Cached weights live under ignored `brain/weights/`.
Histogram/texture signatures remain the download-free fallback.

Nearest cosine distance `d` becomes:

```
novelty = 1 - exp(-max(0, d - d_lo) / tau)
```

`d_lo` is the 90th percentile of leave-one-out nearest distances in admitted memory.
`tau` is at least 0.10 and otherwise the median nearest distance. Calibration depends
on the scene: separation and scientific usefulness are not established by unit tests.

For the first 60 physics seconds, scores are zero and observed appearances are
admitted immediately. This defines normal, so start facing common rocks. Afterward,
score the whole frame before staging new appearances. Pending admission takes 30
physics seconds and does not reset on repeated frames. The selected rock is protected
through approach and dwell. Completion admits it immediately; losing the camera view
alone does not admit it. Aborts are not recorded as completed observations.

Memory and pending admission each hold at most 512 entries. Duplicate admitted
vectors are skipped. A protected target remains protected until released by policy.

## Policy and budget

```
mission_raw = 10 * confidence
curiosity_raw = 10 * novelty * confidence
cost_wh = drive_rate_wh_per_m * estimated_distance + dwell_rate_wh_per_s * dwell_seconds
cost_est = max(cost_wh / 10, 0.5)
B_req = sum of estimated costs for remaining markers
slack = (B - B_req) / B           # -1 when B = 0
w_curiosity = slack ** gamma if slack > 0 else 0
U = value_weighted / (cost_est + 0.001)
```

Marker value is not weighted by curiosity. Rock value is multiplied by `w_curiosity`.
Gamma is clamped to [0.1, 5], including uplinks; zero slack always means zero curiosity.
Calculations are not rounded before choosing or logging a candidate.

Known marker locations come from camera-derived range and odometry. Unseen markers
use a 70 m distance estimate. For a proposed target, BRAIN re-estimates remaining
marker costs from the target's estimated position. Only a selected mission marker
is removed from that hypothetical post-completion obligation.

Every candidate must satisfy both:

```
B >= cost_wh
B - cost_wh >= required_for_mission_after * 1.15
```

This includes mission fallbacks and deferred targets. If no positive-value candidate
is affordable, hold; if there is nothing useful to choose, survey. A close hazard
(≤0.5 m) or exhausted budget vetoes motion. The gate constrains estimates, not physical
truth: reactive avoidance, odometry error, idle energy, and unseen geometry can change
actual cost. Never promise that this model guarantees mission completion.

## Commitment and investigation

A challenger must beat the current eligible target by 1.3×. Commitment locks for 5 s;
a brand-new candidate is exempt from the lock, but not the ratio. An ineligible
commitment loses protection immediately. Briefly missing committed targets can be
approached using their estimated position for 10 s. Deferred rocks expire after 120 s.
Near a remembered rock, BRAIN surveys to reacquire it before investigating.

Investigation starts within 4 m, dwells for 5 physics seconds, and repeatedly checks
the remaining dwell against the reserve gate. The active target remains the audited
target even when the marker has a higher instantaneous score. Completion happens
before next-candidate selection; it adds a visited position with a 5 m suppression
radius and resumes selection. Abort or safety interruption cancels completion and
suppresses that location for 30 s to prevent immediate restart.

## Controlled two-branch example (executed, not a Godot demo)

Same inputs: marker at 30 m, c=0.6; rock at 6 m on the same bearing, n=0.85, c=0.8;
two additional unseen assigned markers. Mission estimate = 33 + 73 + 73 = 179 Wh.

| Case | Budget | Gamma | Marker U | Rock U | Selected |
|---|---:|---:|---:|---:|---|
| Stay | 210 Wh | 2 | 1.817631 | 0.134588 | M01 |
| Deviate | 400 Wh | 1 | 1.817631 | 3.412352 | A01 |

Stay gate: `210 - 33 = 177 >= 146 * 1.15 = 167.9`.
Deviate gate: `400 - 11 = 389 >= 173 * 1.15 = 198.95`.
Both decisions hold for all 16 tested combinations of marker confidence
[0.45, 0.55, 0.65, 0.75] and rock confidence [0.60, 0.70, 0.80, 0.90].
Exact executable audit outputs: [brain/phase1-examples.json](brain/phase1-examples.json).
These replace the earlier inconsistent 490 Wh reserve and claimed 15×/2.1× margins.

## Transport and remaining boundaries

One observation header followed immediately by one binary JPEG, at 5 Hz. Decisions
at 1 Hz; physics time is real time. Both communications directions use a 60-real-second
queue. `clock` contains BRAIN's monotonic generation/delivery stamps. No panel-side delay.
Audit v2 is specified in [interface-contract.md](interface-contract.md).

One SIM is accepted at a time; duplicate connections are rejected. Clock/sequence
regression requires a fresh BRAIN mission. Old-session or stale perception results
are discarded. Worker failures propagate rather than silently freezing. The stub
stops driving/dwelling after 2.5 seconds without commands; Dev must implement that
watchdog in Godot too.

`force_investigate` remains explicitly unsupported; it logs a note and does not
bypass safety. The browser static server, Godot integration, asset calibration,
trained rock detector, and staged videos are later-phase work.
