> **Current Phase 3 result:** Rock detector trained on 1,500 images, held-out
> mAP50 0.8979, installed and tested with real Godot. Novelty calibration remains
> incomplete. See [measured results](phase3-results.md). Older status notes below are historical.

> **Integration update, 2026-09-07:** Dev's `151c4a0` is merged locally.
> Real Godot + BRAIN acceptance passed: 525 frames, 96 validated actions,
> M02 confirmed, disconnect stop and reconnect verified. See
> [phase2-integration.md](phase2-integration.md). Initial marker integration
> is established; all-marker missions, browser PANEL and trained rocks remain pending.

# context.md — IETE Inception '26 Hackathon (master)

**Last updated:** 2026-09-07

**Changelog:**
- v1 — initial capture (problem understanding + research base)
- v2 — verification pass vs primary sources (RAD750 133→200 MHz; AEGIS acronym; 93%/24% verbatim; "256→327" traced to a journalist misread; +4 verified facts)
- v3 — research phase closed; 4-layer candidate architecture, labour split, build tooling
- v4 — mission locked (markers = primary, rocks = bonus); `score = class_priority × confidence`, confidence-weighted no cutoff
- v5 — handoff retargeted to the PPT deck; slide-ready quick-reference added
- v6 — pivot folded in; ARTPS verified; differentiator re-cut to the closed-loop action policy
- **v7 — EXECUTION PIVOT: physical pan-tilt rig replaced by a simulated Mars environment + delayed scientist panel.** Architecture rewritten around three processes (SIM / BRAIN / PANEL). Full utility equation locked (slack-driven, see `novelty.md`). Interface contract frozen in `interface-contract.md`. Labour split updated: Jabin + Dev build, Anton pitches. Three amplifier novelties added.

> **HANDOFF — start here.** Idea locked and corrected (`novelty.md` wins on idea/scoring/decision). Execution is now a **simulation**, not a rig. Four files: **`context.md`** (master), **`novelty.md`** (the idea), **`interface-contract.md`** (message schemas — freeze before coding), **`ppt-deck.md`** (deck content; **stale — written for the hardware framing, needs a pass if reused for the pitch**).

### Quick-reference for slide writing (pull straight from here)

- **One-line problem:** Mars is 3–22 minutes of radio delay away, one-way — too far for real-time control, so the rover must see, judge, and act on its own.
- **One-line solution:** A rover in a simulated Martian environment that uses its camera to (1) reach and confirm assigned mission markers as its primary task, and (2) decide *for itself* whether an unexpected rock is worth leaving that task to investigate — arbitrating `class_priority × confidence` against `novelty × confidence` through a slack-driven adaptive policy, then **acting** on it and logging why for a scientist panel running one minute behind.
- **Real-mission credibility anchor:** AEGIS (flight software on Curiosity + Perseverance) hits **>93%** targeting accuracy vs **~24%** without intelligent targeting (Science Robotics, verbatim) — proof onboard decision-making already works on Mars.
- **Differentiator (corrected):** AEGIS finds only what it's told to; OnBoard Planner budgets but has no science value; **ARTPS ranks curiosity budget-aware but stops at a list for an operator.** We close the loop: an autonomous, onboard **decision to deviate-or-stay**, executed with no operator. ARTPS's own future work names this gap. **We act; they rank.**
- **Honest boundaries (don't overclaim):** visual classification only, no composition analysis; marker = confirm/reach, not collect; budget is *simulated*; novelty = statistical unusualness, not verified science value; the curiosity score and budget-aware scoring are prior art (ARTPS/Kerner/DEMUD) — our contribution is the action policy.

---

## 1. Project brief

| Item | Detail |
|---|---|
| Event | IETE Inception '26, ISF-LICET × TEC (Electronics Club) |
| Host | Loyola-ICAM College of Engineering and Technology (LICET), Dept. of ECE |
| Team | Jabin, Anton, Dev (3 of 3–4 allowed) |
| Domain | **04 — Sustainable Engineering & Social Impact** (locked at registration) |
| Problem statement | **04.1 — Visual Identification & Decision Making** |
| Idea PPT deadline | 05.09.2026, 11:59 PM |
| Shortlist | 06.09.2026 |
| Build day | 07.09.2026, 08:00–18:00 (**10-hour sprint**), on campus, venue **G01** |
| Goal | **Win, not participate** |

### Problem statement (verbatim)

> The rover encounters various geological formations, objects, and mission markers on the Martian surface. Because human operators cannot continuously control the rover in real time, it must use its onboard camera to identify relevant objects or markers and make appropriate navigation or mission decisions.

Two halves, both named: **(1) identification** (formations, objects, markers) and **(2) decision-making** (navigation/mission actions). Sensor: **single onboard camera.** Compute: **onboard only.** Out of scope: full SLAM/path planning (that is PS 03).

---

## 2. Locked decisions

- **PS 04.1 selected** — the rover PS where intelligence lives in perception + decision, not motor control/SLAM. Best fit for an AI&DS team.
- **Understand → plan → build.** No design before problem understanding is solid.
- **NotebookLM** as research base (16-source pack, §5). Research phase **complete and verified.**
- **Design first, fit to template second.**
- **Labour split (v7):** **Jabin = BRAIN** (perception, novelty, policy, audit log). **Dev = SIM + PANEL** (Godot world, rover controller, camera render, scientist UI). **Anton = pitch.** Both builders develop against stubs from `interface-contract.md` section 10 so neither blocks the other.
- **Build tooling:** Antigravity IDE.
- **Mission (locked):** two-tier. **Primary** — reach and confirm assigned mission markers (artificial tags placed in advance; proves an assigned task completed autonomously). **Bonus** — notice unusual rocks/formations and decide whether to investigate; logged and downlinked for Earth to revisit.
- **Decision engine (locked, corrected in v6 — see `novelty.md`):** two value streams plus an adaptive action policy.
  - `mission_value = class_priority × confidence` (markers as the assigned task)
  - `curiosity_value = novelty_score × confidence` (anomalies as opportunistic discovery)
  - **Adaptive policy** arbitrates *investigate vs stay on task* using remaining (simulated) budget, mission progress, and anomaly magnitude. **This policy, executed onboard and closing the loop into action, is the contribution** — not the scores themselves (prior art) and not budget-awareness (ARTPS already does it).
- **(b) Uncertainty policy (locked):** confidence-weighted, **no hard cutoff** — multiplies into both value streams; low confidence demotes gracefully. Avoids an indefensible "why this threshold" in Q&A; matches AEGIS's no-discard ranking.
- **Worked example (mission side, for the deck):** marker @58% → 10×0.58 = 5.8 outranks weird rock @91% → 3×0.91 = 2.7 and common rock @95% → 1×0.95 = 0.95.
- **Capability boundaries (Q&A honesty):** visual classification only (no composition analysis — needs ChemCam-style hardware); marker = confirm/reach, not collect/return; budget is **simulated**; novelty = statistical unusualness; curiosity score + budget-aware scoring are prior art.

## 3. Locked architecture (v7 — simulation)

Three processes. **Message schemas are frozen in `interface-contract.md` — read that before writing code.**

```
[ SIM ]  Godot: Mars terrain, rover body, camera
   |  observation @10Hz {frame_jpeg, pose, budget, hazard, mission}
   v
[ BRAIN ]  Python: ArUco + YOLOv8n + novelty + policy + audit log
   |  action <=1Hz {decision, target, drive, audit}
   |  telemetry --> DELAY QUEUE (60s) -->
   v
[ PANEL ]  Web UI: delayed live feed, decision log, budget gauge, interrupt
   |  uplink --> DELAY QUEUE (60s) --> BRAIN
```

### THE RULE (violate this and the project is dead)

> **BRAIN receives pixels, its own pose, and its own budget. Nothing else.**

No object lists, no ground-truth positions, no scene-graph queries. Everything about the world is derived from the image by BRAIN's own perception. Legitimate non-visual inputs are only those a real rover has: odometry pose, own battery telemetry, reactive hazard range, assigned marker IDs from the last uplink, onboard clock.

### Layer detail (inside BRAIN)

1. **Perception** — OpenCV ArUco (markers, no training, real detection on rendered ArUco texture quads) + YOLOv8n fine-tuned on AI4Mars (rocks) + novelty module (embedding-distance from a running memory).
2. **World model** — thin running list `{class, priority, confidence, novelty, bearing, est_range, t}` + deferred-target queue.
3. **Decision engine** — two value streams, slack-driven adaptive policy, safety veto. Full equation in `novelty.md`.
4. **Action + telemetry** — action to SIM; audit record to the delay queue; closed loop back through the next frame.

### Motion (locked)

Continuous driving, decisions at a fixed cadence (~1 sim-second, configurable). Straight-line heading to the committed target. **Reactive obstacle avoidance lives in SIM; no global planner** (that is PS 03). Waypoint-teleport was rejected because it kills the uncertainty story — the no-threshold defense needs intermediate approach frames for confidence to climb.

### Environment (locked)

Godot + premade Mars terrain, **textured with real AI4Mars imagery** to keep YOLO in-distribution. **Curate, do not generate:** 4-5 repeated common rock types + 2-3 distinct anomalies. Generating hundreds of unique rocks flattens the novelty signal and kills habituation. Meshy for 3-5 hero anomaly models at most. **Higgsfield dropped** — video generation cannot produce a controllable environment.

### Quality priorities (highest judge-impact per hour)

1. Scientist panel (delayed feed, decision log, budget gauge, interrupt)
2. Detection overlay on the rover camera feed (proof perception is real)
3. God view + rover view side by side (the gap between them *is* the problem)
4. Asset fidelity — last

### Remaining opens

- Novelty method: embedding-distance (preferred) vs autoencoder reconstruction error.
- Safety-veto rules for the sim (hazard-close, out of range, unreachable).
- Exact `alpha`/`beta`/`gamma`/`margin` values — tune once both runs are stageable.
- Fixed forward camera for v1; pannable mast is a stretch (adds an action type).

## 4. Verified research base

Every number carries a source; unverified items are flagged and must not reach a slide unchecked.

### 4.1 The autonomy premise

| Fact | Value | Source |
|---|---|---|
| Earth–Mars one-way delay | **~3 to ~22 min** (round trip ~6–44) | NASA / NTRS crewed-Mars study (max ~22 min) |
| Command uplink cadence | ~once every 1–3 days | AEGIS literature |
| Why real-time control fails | rover idles most of its life waiting on round trips | Planetary Society (Francis & Estlin, 2018) |

**⚠ CORRECTED:** the "tens to hundreds of light-minutes" phrase describes the *solar system's scale*, not the Mars link. Correct: **3–22 min one-way.**

### 4.2 AEGIS — closest real-world analogue

**Autonomous Exploration for Gathering Increased Science** (verbatim, Science Robotics). Opportunity 2009 (Pancam) → Curiosity flight software Oct 2015 → routine from **May 2016** → Perseverance (SuperCam).

Pipeline: NavCam/RMI image → **Rockster** edge-detection segmentation → property extraction (albedo, area, 3D size, stereo distance, roughness) → filter (too small / beyond ChemCam 7 m) → rank vs a **scene profile** → **safety veto** (not on/near rover body; not near sun) → point mast, fire ChemCam LIBS, capture RMI context. *Earth sends the goal (profile); the rover makes the decision.*

| Metric | Value | Status |
|---|---|---|
| Targeting accuracy (last 2.5 km into new terrain) | **>93%** | **Verified — abstract, verbatim** |
| Accuracy without intelligent targeting | **~24%** | **Verified** |
| Observation success | **all** AEGIS obs geochemically successful | **Verified** |
| Scene parsing | tens–hundreds of seconds on limited compute | **Verified** |
| Runs in first 11 months | **54** after May 2016 | Verified (Phys.org) |
| Autonomous targets by Mar 2018 | 130+ | Verified (Planetary Society) |
| "25% ChemCam rate increase" | — | **UNVERIFIED** — abstract says only "markedly increased the pace" |
| "256 → 327 per sol" | — | **DO NOT USE** — journalist misread; implausible; absent from abstract |

**Failure modes (the gap to occupy):** built for discrete float rocks on sand/gravel; struggles on continuous bedrock/layered outcrop; sensitive to shadow/low-contrast/glare; safety exclusions block some targets; zero-target runs in monotonous terrain; classical CV only (no deep nets onboard).

### 4.3 Identification — AI4Mars

~35,000 images, ~326,000 crowdsourced segmentation labels; Curiosity NAVCAM+Mastcam, Opportunity/Spirit NAVCAM. Classes: soil, bedrock, sand, big rock (+null). Labels: ≥3 labelers, >65% agreement; ~1,500-image expert validation set at 100% agreement. Rover mask + 30 m range mask. Segmentation (not boxes) because terrain is amorphous — you can't box "sand." Hardest: visual homogeneity, dust coating, shadow-as-edge, class-boundary ambiguity.

### 4.4 Decision-making mechanics + the field gap

- **AEGIS scoring:** rank by distance of a candidate feature vector from a scientist-weighted optimum.
- **Uncertainty:** multiply by classifier confidence → graceful degradation, not a binary stop.
- **Bandwidth (OASIS `WATCH`):** onboard NavCam scan → crop ROI → downlink only that subset (basis for "prioritized downlink").
- **The three-system gap we close (verified — see `novelty.md`):**

| System | Has | Lacks |
|---|---|---|
| AEGIS | value-driven targeting, closed to point+fire | only finds what it's told; blind to the unexpected |
| OnBoard Planner (2023) | budget/thermal/time scheduling | no science-value concept |
| **ARTPS** (arXiv 2509.00042, Sept 2025) | learnable curiosity score, **budget-aware, edge, explainable** | **stops at a ranked list for an operator — no autonomous act-or-stay policy (its own §7 future work)** |

**ARTPS verified quotes:** *"designed for edge-compute constraints, respecting memory/energy budgets…"*; *"balances scientific value with operational budgets"*; *"explainable diagnostics suitable for operator-in-the-loop workflows"*; **future work:** *"active exploration policies on edge devices with strict power budgets."* → Our contribution is exactly that closed-loop action policy. **We act; ARTPS ranks.**

**⚠ CORRECTED:** "AEGIS is a component of OASIS" — overstated; AEGIS *builds on* earlier onboard-science work incl. OASIS.

### 4.5 Onboard compute constraint

| Fact | Value |
|---|---|
| Curiosity/Perseverance flight CPU | **RAD750 @ 200 MHz** (~400 MIPS), rad-hard, VxWorks |
| CPU headroom | ~50% used by baseline engineering |
| Consequence | real rovers run classical CV (Rockster), not deep nets |
| Perseverance VCE | separate rad-hard Virtex-5 FPGA for stereo/visual odometry |

**YOLOv8n edge:** Jetson Nano ~6 FPS detection / ~4.2 FPS seg; Orin NX ~23.7 FPS (batch 1); Orin+TensorRT ~52 FPS FP16 / ~65 FPS INT8; cap batch ≤4 (OOM above ~8).
**⚠ Misleading:** the "INT8 97%→37.2%" drop is a Cortex-M4 case; on Jetson INT8 costs a few mAP points. **Drop:** "85% latency reduction vs cloud" (unverifiable).

### 4.6 Mission markers — ArUco

(n+2)×(n+2) grid; black border for segmentation; inner n×n binary ID. Detect: adaptive threshold → contour (Suzuki–Abe) → polygon approx (Douglas–Peucker) → homography rectify → Otsu → per-cell majority vote → dictionary match over 4 rotations. Error correction: corrects ⌊(τ̂−1)/2⌋ bits (6×6/30-marker dict, τ̂=12 → 5 bits). Smaller grid (4×4) = better at distance/blur, weaker correction; **choose the smallest dictionary that meets the need.** Corner refinement keeps jitter <~0.2 px. **⚠ Caveat:** the "insignificant error to 85% occlusion" figure is for a 24-marker *board*, not a lone tag — matters for physical demo design.

### 4.7 Mission-to-system map

MER: AutoNav; AEGIS from 2009 (Pancam); OASIS (`WATCH`). MSL: AutoNav; AEGIS from May 2016 (ChemCam); SPOC (ground). Mars 2020: ENav+ACE ("think while driving"); VCE FPGA; AEGIS for SuperCam; OnBoard Planner (2023). AEGIS modes: (1) autonomous target selection (full loop post-drive), (2) autonomous pointing refinement (milliradian "pointing insurance").

---

## 5. Source pack (NotebookLM)

science.org/scirobotics.aan4582 · science.org/scirobotics.adi3099 · planetary.org/0313-automating-science-on-mars · phys.org 2017-06 · AI4Mars CVPRW 2021 PDF · ntrs.nasa.gov/20220008371 · arxiv 2104.04359 · 2410.17738 · 2111.11537 · 2206.02180 · **arxiv 2509.00042 (ARTPS)** · Mines ArUco PDF · ReadyTensor Jetson YOLOv8 · mdpi 15/2/74 · Kaggle+HF AI4Mars (training data, not reasoning).
Failed to load: docs.opencv.org, zbotic.in (bot protection) → replaced with Mines ArUco PDF (backup: Clemson mirror).

## 6. Team capability & resources

Compute: RTX 5060 laptop, RTX 5050 laptop, Mac Pro (fine-tune YOLO overnight). AI-assisted dev is a **real capability**, not a crutch — treat the team as capable builders. **No prior CV/embedded experience** — genuine risk is physical integration/debug on the day, which AI doesn't shorten. Hardware unsourced (Ritchie St., Chennai). Team of 3 (not 4) = ~25% less build-day labour.

## 7. Working principles

Understand deeply → plan collaboratively → then build. Propose clear positions, not open-ended question chains. Every slide number needs a source. Concision valued; time-wasting called out.

## 8. Open questions

1. Novelty method — embedding-distance (preferred, lighter) vs autoencoder reconstruction error.
2. Safety-veto rules for the sim.
3. Tuning values for `alpha` / `beta` / `gamma` / `margin`.
4. Whether the pitch reuses `ppt-deck.md` (written for the hardware framing — **stale**, needs a pass for Anton).

**Resolved:** venue G01 · pre-trained models allowed · mission locked · decision engine locked and corrected · ARTPS verified · **hardware demo not required (simulation accepted)** · motion model locked (continuous + fixed decision cadence) · environment approach locked (Godot + premade terrain + real AI4Mars textures, curated asset set) · interface contract frozen.

## 9. Corrections log

| # | Claim | Status |
|---|---|---|
| 1 | Earth–Mars "light-minutes" | **WRONG** → 3–22 min one-way |
| 2 | "AEGIS is a component of OASIS" | **OVERSTATED** → builds on earlier work incl. OASIS |
| 3 | INT8 97%→37.2% | **NOT GENERALIZABLE** → Cortex-M4 case |
| 4 | "85% latency reduction vs cloud" | **DROP** → unverifiable |
| 5 | "256 → 327 per sol" | **DO NOT USE** → journalist misread |
| 6 | "25% ChemCam rate increase" | **UNVERIFIED** → don't quantify |
| 7 | terrain values "cost reduction" | **AMBIGUOUS** → likely out of scope for marker/rock mission |
| 8 | ArUco 85% occlusion tolerance | **SCOPED** → 24-marker board, not a lone tag |
| 9 | AEGIS "Automated" vs "Autonomous" | **RESOLVED** → Autonomous |
| 10 | RAD750 "133 MHz" | **WRONG** → 200 MHz on the rovers |
| 11 | **"budget-awareness is our differentiator"** | **CORRECTED (v6)** → ARTPS is already budget-aware (verified from arXiv 2509.00042). Our differentiator is the **closed-loop autonomous action policy**, which ARTPS lists as future work. |

### Verified-good (safe to use)
>93% vs ~24% targeting · all obs geochemically successful · scene parsing tens–hundreds of s · 54 runs/11 months · 130+ targets by Mar 2018 · ChemCam 7 m · RAD750 @ 200 MHz · AI4Mars ~35k images / ~326k labels / 4 classes · AEGIS timeline (2009 → Oct 2015 → May 2016) · **ARTPS is budget-aware/edge/explainable and defers active exploration policies to future work.**

---

## 10. PPT template (received 05.09) — maps to `ppt-deck.md`

> **v7 note:** the submitted deck was built on the hardware + pan-tilt framing. `ppt-deck.md` is **stale** for the live pitch — Anton needs the simulation framing, the equation, and the three demo beats from `novelty.md`.

Official IETE Inception '26 template. **Fixed structure, max 7 content slides (excl. title). Submit as .pdf. Remove the instructions slide.**

| # | Slide | Template prompts |
|---|---|---|
| 1 | Title | Team, Domain, PS title, Solution type (HW/SW) |
| 2 | Discover & Define | problem context, research, existing solutions, key gap, references |
| 3 | Ideate & Innovate | proposed idea, how it solves, key features, unique advantage |
| 4 | Design to Build | technologies, HW/SW, architecture/workflow, methodology, diagrams |
| 5 | Reality Check | feasibility, resources, challenges/risks, mitigation |
| 6 | Impact & Next Step | impact/beneficiaries, outcomes, limitations, future scope |

Rules: concise points not paragraphs; diagrams/infographics over text; precise. Full slide content lives in **`ppt-deck.md`**.
