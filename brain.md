# brain.md — BRAIN lane (Jabin)

**v1 · 2026-09-07** · Owner: **Jabin**, RTX 5060 / Windows 11.
**Read first:** `novelty.md` (the idea), `interface-contract.md` (schemas), `plan.md` (phases, env traps).

> BRAIN is the project. SIM and PANEL are staging that makes it visible. The policy, the audit log and the closed loop **are** the contribution — everything here should be defensible to a judge who reads it.

---

## 1. What BRAIN is

One Python process, one asyncio loop:

- **WebSocket SERVER** on `127.0.0.1:8765` — SIM connects as a client. (BRAIN owns the ports, so `stub_sim.py` and the real Godot SIM are interchangeable clients.)
- **WebSocket SERVER** on `0.0.0.0:8766` + static HTTP on `0.0.0.0:8000` — the PANEL connects from Dev's Mac.
- Receives observations at 5 Hz (JSON header + binary JPEG), decides at **1 Hz**, sends actions, pushes telemetry through a **60-real-second** delay queue.

```
brain/
  main.py        asyncio loop, both servers, the 1 Hz decision tick
  validate.py    THE RULE — whitelist validator (§7)
  perception.py  ArUco + rock proposals -> detections
  novelty.py     RockEmbedder + NoveltyMemory (§6)
  policy.py      utility, slack, gate, hysteresis, deferred queue (§5)
  audit.py       builds the audit record; arithmetic must close
  delay.py       one delay heap, both directions (§8)
  weights/
```

---

## 2. THE RULE

> **BRAIN receives pixels, its own pose, and its own budget. Nothing else.**

You no longer own SIM, so this is enforced by structure — but back it with the validator in §7 anyway. If SIM ever sends a field outside the contract whitelist, **raise loudly**. A judge asking *"is YOLO actually running, or are you reading ground truth?"* should be answerable by pointing at one function.

**The one legitimate exception is offline:** the sim projects rock boxes into the camera to write YOLO *training labels* (`sim.md` §8). That is dataset generation. At runtime BRAIN still gets only the JPEG.

---

## 3. Build order

| # | Step | Depends on | Exit |
|---|---|---|---|
| 3.1 | venv + CUDA proof (`plan.md` §5) | — | `torch.cuda.is_available() == True` |
| 3.2 | `stub_sim.py` running | — | frames + pose arriving |
| 3.3 | WS server + validator + observation decode | 3.2 | `cv2.imdecode` gives a 640×480 BGR frame |
| 3.4 | **ArUco detection** → bearing + range | 3.3 | marker IDs with plausible bearings |
| 3.5 | **Classical rock proposals** (MSER) | 3.3 | boxes + confidence proxy |
| 3.6 | **Novelty memory** | 3.5 | novelty in [0,1], first sighting high |
| 3.7 | **Policy + audit** | 3.4–3.6 | decisions printing, arithmetic closes |
| 3.8 | Delay queue + telemetry out | 3.7 | panel stub receives records 60 s late |
| 3.9 | *(later)* YOLO swap-in | Phase 3 | mAP50 ≥ 0.6, then replace 3.5 |

**3.4 → 3.7 is the critical path.** ArUco alone is enough to produce a working demo. Everything after 3.7 is upgrade, not foundation.

---

## 4. Perception

### 4.1 ArUco — the uncompromised leg

Real OpenCV detection on a genuinely rendered marker texture. No training, identical to a physical tag. **Dictionary: `DICT_4X4_50`** — largest cells, best detection at range and under JPEG compression; error correction matters less when there are only 3 markers.

⚠ **Verify these signatures against your installed OpenCV before trusting them** — the ArUco deep-dive agent failed, so this section is from fragments plus first principles:
```bash
python -c "import cv2; print(cv2.__version__); print([n for n in dir(cv2.aruco) if 'etect' in n or 'enerate' in n])"
```

Current (OpenCV ≥ 4.7) API — the old free-function `cv2.aruco.detectMarkers(...)` is deprecated:
```python
adict    = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
params   = cv2.aruco.DetectorParameters()
params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
detector = cv2.aruco.ArucoDetector(adict, params)
corners, ids, rejected = detector.detectMarkers(gray)
```

**Bearing** from the marker's pixel centre `cx` in a frame of width `W` with horizontal FOV `hfov`:
```python
f_px        = (W / 2) / tan(radians(hfov) / 2)
bearing_deg = degrees(atan((cx - W/2) / f_px))     # use atan, NOT the linear approximation
```
The linear form `(cx/W - 0.5) * hfov` is only accurate near the centre; at the frame edges it is off by several degrees. Use `atan`.

**Range** from apparent marker width `w_px` and physical width `W_m`:
```python
est_range_m = f_px * W_m / w_px
```
Agree `W_m` with Dev and put it in `config.yaml` — if the sim's marker quad is 0.5 m, every range is wrong by that ratio.

**Confidence.** ArUco has no native confidence, and inventing one is dishonest. Use a **defensible proxy and name it as a proxy**: the fraction of the last N frames in which this ID was detected, times a sharpness term. It rises as the rover approaches — which is exactly what the no-threshold uncertainty story needs.

```python
confidence = (hits_in_last_N / N) * min(1.0, w_px / w_px_reference)
```

### 4.2 Rock proposals — classical first, learned later

**Ship the classical detector first and keep it as the live fallback.** MSER + CLAHE + greedy NMS on the rendered frame produces boxes and a confidence proxy with zero training, and it works from hour one.

The learned upgrade (Phase 3): fine-tune **YOLO26n** (`ultralytics 8.4.142`, `yolo26n.pt`) on ~1,500 frames **auto-labelled from the sim itself** (`sim.md` §8). There is no public real-rover dataset with per-rock bounding boxes — Katwijk ships only DGPS rock coordinates, AI4Mars and MarsData-V2 are segmentation masks, and none of them look like your curated meshes anyway. Sim-labelled is the only detector that will be in-distribution.

**Single class: `rock`. Never a class called `anomaly`.** The moment a class encodes "unusual", the novelty score becomes a lookup of your own label and the entire curiosity story collapses. Anomaly-ness comes from the embedding module and nowhere else. This is the most important line in this document.

Training gotchas: wrap `model.train()` in `if __name__ == '__main__':` on Windows or dataloader workers crash. Use `batch=-1` or `32` — the YOLO26 docs suggest 128, which OOMs an 8 GB laptop GPU. Never train from a `.yaml` (random init); always start from `yolo26n.pt`.

---

## 5. The policy — corrections, and the numbers that work

### 5.1 The equation, corrected

`novelty.md` v3 is right in shape and **wrong in scale**. With `C_i = n·c` where `n ∈ [0,1]`, competing against markers at `p = 10`, **the deviate run cannot happen** for any realistic geometry — the marker would have to be ~129 m away or below 8% confidence. Two independent analyses reached this today.

**Fix: a curiosity scale constant.**
```
M_i = p_i · c_i                    mission value      (p = 10 marker)
C_i = k · n_i · c_i                curiosity value    k = 10
```
`k = 10` reads cleanly to a judge: *at full slack, a perfect discovery is worth exactly one marker; slack scales it down from there.* `k = 1` reproduces `novelty.md` exactly and can never deviate — say so if asked, it shows the tuning was reasoned.

The rest stands unchanged:
```
Cost_i  = drive_rate · d_i + dwell_wh_i          (in Wh, same rates SIM charges)
B_req   = Σ over unconfirmed markers: drive_rate · dist + confirm_dwell
S       = (B - B_req) / B
w_c     = max(0, S)^gamma
U_i     = value_weighted / (cost_est + eps)
gate:   accept iff  B - Cost(target*) >= B_req_after · margin
```

`B_req` when a marker has never been seen (no range yet): use a **default 70 m**. Put it in config; it is an honest estimate, not a fudge.

### 5.2 Tuned constants

```yaml
k_curiosity: 10.0
gamma: 2.0                 # 1.0 for the deviate run
drive_rate_wh_per_m: 1.0
dwell_wh_investigate: 5.0
confirm_dwell_wh: 3.0
default_marker_range_m: 70.0
mission_margin: 1.15
eps: 0.001
cost_est_floor: 0.5        # stops U exploding as cost -> 0
gamma_clamp: [0.1, 5.0]
switch_ratio: 1.3
commit_lock_s: 5.0
visited_radius_m: 5.0
```

### 5.3 Verified staging for the two runs

Scene: **marker at ~30–35 m, confidence ~0.60. Anomaly at ~5–6 m, novelty 0.85, confidence 0.80.**

| Config | `start_budget_wh` | `gamma` | S | w_c | U_marker | U_anomaly | Result |
|---|---|---|---|---|---|---|---|
| **Stay** | 560 | 2.0 | 0.125 | 0.016 | 0.182 | 0.008 | **marker, ~15× margin** |
| **Deviate** | 950 | 1.0 | 0.484 | 0.484 | 0.182 | 0.235 | **anomaly, ~2.1× margin** |

Gate on the deviate branch: `950 − 14 = 936 ≥ 490 × 1.15 = 564` → **pass**.

Robustness: across marker confidence 0.45–0.75 and anomaly confidence 0.60–0.90, the deviate run holds in 13 of 16 combinations. That is enough margin to survive live perception noise.

**If the deviate run doesn't switch on the day**, read the `t=2` audit record: if `U_anomaly / U_marker < 1.3`, raise `start_budget_wh` to 1000, or drop `gamma` to 0.3, or lower `switch_ratio` to 1.2. Change *config*, never code — that distinction is the whole "it's a policy, not a script" claim.

### 5.4 Five failure modes, and the fixes

1. **`Cost → 0` makes `U` explode.** Floor it: `cost_est = max(cost_wh / 10, 0.5)`.
2. **Oscillation** between two close-U targets every tick. Add **hysteresis**: a challenger must beat the committed target by `switch_ratio` (1.3×), and the commitment locks for `commit_lock_s` (5 s). ⚠ **Brand-new candidates are exempt from the lock but never from the ratio** — without that exemption the deviate run dies, because the marker gets closer every tick and the anomaly's only chance to win is the tick it appears.
3. **An already-investigated anomaly re-triggering forever.** Keep a **visited set** keyed on estimated world position with a 5 m radius. Habituation lowers novelty but does not zero it — a residual `n = 0.3` anomaly 2 m away still outscores a 25 m marker.
4. **`gamma = 0`** — in Python `0.0 ** 0.0 == 1.0`, which turns curiosity fully ON at zero slack. Define `w_c` piecewise and clamp gamma to `[0.1, 5.0]`. A `set_gamma` uplink must go through the clamp.
5. **No candidates visible** → `survey` (rotate in place). **Deferred-queue re-entry** must pass the gate *and* the unaffordable veto again, or the rover will burn its reserve on a late detour.

**A property worth pointing out to judges:** slack rises as markers get *confirmed* (`B_req` shrinks), not only as budget drains. So the rover can ignore an anomaly on approach and legitimately turn back for it after confirming the marker. That is opportunistic science, emergent from the equation — not scripted.

### 5.5 Audit record — the arithmetic must close

Per `interface-contract.md` §5, with the §14 correction: emit **both** `cost_wh` and normalised `cost_est`, plus `gate.required_for_mission_after`, so a judge can recompute `post_action_reserve` by hand. `value_weighted = value_raw` for mission, `w_c · value_raw` for curiosity. `U = value_weighted / (cost_est + eps)`.

The `text` field is written **by BRAIN, in its own words** — the rover explaining itself is the point. Include the numbers that decided it.

---

## 6. Novelty — training-free, with staged memory

**Embedder:** torchvision **ResNet18**, `IMAGENET1K_V1`, `fc = nn.Identity()` → 512-d, crops resized to 160×160, L2-normalised. No training. (Fallback if separation is weak: DINOv2-S via timm — one constructor change, memory code untouched.)

**Score:** cosine distance to the **single nearest neighbour** (`k=1`) in a running memory, squashed to [0,1]:
```
novelty = 1 - exp(-max(0, d - d_lo) / tau)
```
`d_lo` = 90th percentile of leave-one-out NN distances inside memory; `tau` re-estimated when memory changes and **floored at 0.10**. Without the floor, with only two rock types in memory `tau` collapses to ~0.023 and every common rock in the first minute scores 0.999 — total saturation.

**Memory admission is the whole trick.** Naïvely appending every crop on sight *destroys the deviate run*: in simulation the anomaly's score fell from 0.91 to 0.00 by the fifth approach tick, because the rover memorised the anomaly while driving toward it.

- **Warm-up** (first 60 sim-s): commit every crop immediately, ramp scores down. Whatever the rover sees here becomes "normal" — **start it facing common rocks**, or seed memory from a folder of common-rock crops.
- **After warm-up:** score against memory, then only **stage** the crop. Consolidate after `commit_delay` (~30 decision ticks, longer than approach + dwell) or immediately when an `investigate` completes.

This gives exactly what `novelty.md` promises: the first striped rock scores high and stays high through the approach; the fifth scores near zero. Habituation, emergent, no code written for it.

⚠ **Tell Dev:** common rock types that differ only by *tint* barely separate (between/within distance ratio ~1.5). The 4–5 common types must differ in **texture**, not colour. This is a `sim.md` requirement that comes from here.

---

## 7. The validator — THE RULE as code

```python
ALLOWED = {"type","seq","sim_time","pose","budget","hazard","mission","state","camera"}

def validate_observation(msg: dict) -> dict:
    extra = set(msg) - ALLOWED
    if extra:
        raise ContractViolation(f"SIM sent forbidden field(s): {sorted(extra)}")
    return msg
```
Loud, not lenient. Also validate outbound `action`/`audit` against the contract so a malformed audit never reaches the panel.

---

## 8. Runtime notes

⚠ *The runtime deep-dive agent failed; this section is from the transport and panel findings plus first principles. Treat it as a starting design, not verified gospel.*

**Never block the event loop.** Perception takes 50–200 ms. Run it in `asyncio.run_in_executor` and use **latest-frame-wins** — a single-slot holder, not a queue. `websockets` buffers `max_queue=16` frames then stops reading; if BRAIN processes in arrival order it will act on up to 1.6 s of stale reality. Dropping frames is correct.

**Two clocks.** `sim_time` comes from SIM. The delay queue runs on **real** seconds (`comms_delay_real_s: 60`). Stamp `wall_generated_at` / `wall_delivered_at` in BRAIN with `time.time()` and let the panel display lag as their difference — never compute delay from the Mac's clock, the two laptops differ by seconds.

**One delay heap, both directions**, in `delay.py`, keyed on `delivered_at`. One file a judge can read. Never delay in the panel.

**websockets ≥14 API** — AI agents will emit the legacy form from training data:
```python
from websockets.asyncio.server import serve          # NOT: import websockets; websockets.serve
async def handler(websocket):                        # ONE argument, no `path`
    ...
```

**Recording.** Dump every frame + decision to `recordings/<run>/` so a run can be replayed if the live demo fails. Cheap insurance, worth the twenty minutes.

---

## 9. What to say when asked

- *"Is the perception real?"* — ArUco is genuine OpenCV detection on a rendered marker texture, identical to a physical tag. The validator in `validate.py` rejects any world knowledge from the sim. One file to check.
- *"Isn't `p × c` trivial?"* — deliberately. It is meant to be correct and explainable. The intelligence is the **policy** arbitrating mission against discovery under a budget, and the closed loop. Don't defend the formula as clever.
- *"How is this a policy and not a script?"* — same binary, two configs, opposite behaviour, with logged reasoning both times. One run is an argmax; two runs are a policy.
- *"What's yours vs prior art?"* — ours: the closed-loop act-or-stay policy under a competing mission obligation, plus the audit trail. Not ours, and cited: the curiosity score (ARTPS, Kerner, DEMUD), budget-aware scoring (ARTPS), AEGIS-style ranking.
- *"Where did `k = 10` come from?"* — from making the two branches reachable; `k = 1` reproduces the paper-shaped equation and can never deviate. Tuning a constant is not the contribution; the structure is.
