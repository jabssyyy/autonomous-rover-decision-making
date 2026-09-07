> **Current Phase 3 result:** Rock detector trained on 1,500 images, held-out
> mAP50 0.8979, installed and tested with real Godot. Novelty calibration remains
> incomplete. See [measured results](phase3-results.md). Older status notes below are historical.

> **Integration update, 2026-09-07:** Dev's `151c4a0` is merged locally.
> Real Godot + BRAIN acceptance passed: 525 frames, 96 validated actions,
> M02 confirmed, disconnect stop and reconnect verified. See
> [phase2-integration.md](phase2-integration.md). Initial marker integration
> is established; all-marker missions, browser PANEL and trained rocks remain pending.

# novelty.md — the core idea (design source of truth)

**Read alongside `context-iete.md` and `brain.md`. This file states the idea; `brain.md` and `interface-contract.md` specify the implemented policy and wire format.**
**v4 · 2026-09-07 — Phase 1 equation implemented and controlled cases verified.**
**Changelog:** v2 — ARTPS verified; differentiator re-cut from "budget-awareness" (false) to the closed-loop action policy. **v3 — execution pivoted to a simulated Mars environment + delayed scientist panel. Full utility equation specified (slack-driven). Three amplifier novelties added.**

---

## The one-line idea

**A rover that decides for itself whether an unexpected discovery is worth leaving its assigned mission for — and executes that call onboard, with a human too far away to stop it in time.**

---

## The gap in the field (verified)

| System | Has | Lacks |
|---|---|---|
| **AEGIS** (Curiosity + Perseverance) | value-driven targeting, closed loop to point+fire | only finds **what it was told to look for** — blind to the unexpected |
| **OnBoard Planner** (Perseverance, 2023) | budget/thermal/time scheduling | **no concept of science value** |
| **ARTPS** (arXiv 2509.00042, Sept 2025) | learnable curiosity score, **budget-aware**, edge, explainable | **stops at a ranked list for an operator** — no autonomous act-or-stay policy |

**Verified ARTPS quotes:** *"designed for edge-compute constraints, respecting memory/energy budgets, timing requirements, and communication latency"* · *"balances scientific value with operational budgets"* · *"explainable diagnostics suitable for operator-in-the-loop workflows"* · **future work:** active exploration policies for edge compute (paraphrase, not a verbatim quotation).

**Our contribution:** the closed-loop action policy. **ARTPS ranks; we act.**

## Prior art — never claim these

- The curiosity/anomaly score is **not ours** (ARTPS 2025; Kerner et al. 2018/2020; Wagstaff DEMUD 2013).
- Budget-aware scoring is **not ours** (ARTPS does it).
- **Never say** "nobody thought of finding the unexpected" or "we invented budget-aware autonomy." False and checkable.
- **Ours:** the autonomous act-or-stay policy under a *competing mission obligation*, executed onboard, with an audit trail.

**The precise fresh ground:** ARTPS ranks curiosity against *nothing*. Our rover has a **contract** — reach these markers — and must trade discovery against a promise it is not allowed to break. That competing-obligation framing is the novel structure.

---

## The equation — implemented in Phase 1

The old version lacked the curiosity scale and mixed normalized costs with Wh.
The implemented definitions are:

```
M = 10 * confidence
C = k * novelty * confidence       k = 10
cost_wh = drive_rate * estimated_distance + dwell_rate * dwell_seconds
cost_est = max(cost_wh / 10, 0.5)
B_req = sum of current estimates for remaining assigned markers
slack = (B - B_req) / B            -1 when budget is zero
w_curiosity = slack ** gamma if slack > 0 else 0
U_mission = M / (cost_est + 0.001)
U_curiosity = w_curiosity * C / (cost_est + 0.001)
```

Every candidate, including mission fallbacks and deferred discoveries, must satisfy:

```
B >= cost_wh
B - cost_wh >= required_for_mission_after * 1.15
```

BRAIN estimates remaining marker costs from the proposed target's estimated location.
Known positions come from pixels and odometry; unseen markers use a 70 m estimate.
This is a budget constraint on estimates, not a guarantee against stranding: actual
avoidance, idle spending, and perception error remain limitations.

Gamma is clamped to [0.1,5]. A five-second commitment lock and 1.3x switch ratio
prevent small changes from repeatedly reversing the choice. New candidates bypass
the lock, but must still satisfy the ratio and gate. Safety and affordability win
over commitment. During dwell the gate is checked again for the remaining time.

**Executed controlled example:** marker 30 m away at c=.60; rock 6 m away on the
same bearing at n=.85, c=.80; two more unseen assigned markers. B_req = 179 Wh.

| Configuration | Marker U | Rock U | Decision | Reserve test |
|---|---:|---:|---|---|
| 210 Wh, gamma 2 | 1.817631 | 0.134588 | Marker | 177 >= 146 x 1.15 |
| 400 Wh, gamma 1 | 1.817631 | 3.412352 | Rock | 389 >= 173 x 1.15 |

Same policy and candidates, only budget/gamma differ. All 16 tested confidence
combinations preserve both branches. This establishes the policy behavior with
controlled detections; Godot scene calibration and end-to-end demonstration remain
later phases. Full arithmetic: `brain/phase1-examples.json`.

Audit v2 exposes costs in Wh, normalized costs, eligibility, the post-action mission
estimate, and the selected action's reserve. A zero obligation has a null ratio;
the Wh comparison remains authoritative. See `interface-contract.md`.

## Amplifier novelties (secondary — never dilute the main claim)

1. **The downlink is also a decision.** At the report window bandwidth is scarce; the rover ranks what is worth the bits with the same utility machinery. Grounded in real practice (OASIS `WATCH`). Makes the panel meaningful — **the humans only see what the rover chose to show them.**
2. **Habituation — nearly free.** With novelty as embedding-distance from a running memory, a repeated striped rock scores near zero after its appearance has been admitted to memory. Phase 1 protects a committed appearance until investigation completion, with delayed admission for other observations. Curiosity saturates on repetition with no code written for it. Emergent, scientifically correct, excellent Q&A material.
3. **Deferred-target queue.** An anomaly it could not afford is not forgotten — it is queued with its score and revisited if slack opens later. That is what opportunistic science actually looks like.

---

## Execution: simulated Mars + delayed scientist panel

**Why the sim is stronger than the rig it replaced:**
- **The delay becomes visible.** A panel running one minute behind lets the judge *watch* a human being useless in real time. The PS's premise, demonstrated instead of asserted.
- **Both branches become showable.** Set slack high -> deviate run. Set slack low -> stay run. Same binary, different config.
- **Simulated budget stops being an apology** — in a simulation it is just the model.
- **The report cycle is not invented** — it is the real command cycle (uplink every 1-3 sols). Say it in those words.

**Architecture:** three processes — SIM (Godot) -> BRAIN (Python) -> PANEL (web). Full schemas in `interface-contract.md`.

### The rule that governs everything

> **BRAIN receives pixels, its own pose, and its own budget. Nothing else.**

If the rover can query the scene graph, the identification half of the PS is gone and it is a pathfinding toy. One judge asking *"is YOLO actually running, or are you reading ground truth?"* ends the project.

### Perception legitimacy

- **ArUco markers render as real ArUco textures on flat quads** -> OpenCV genuinely detects them, no training, identical to a physical tag. This is the uncompromised leg.
- **Curated simulated textures and geometry** form the training distribution for the later sim-labelled rock detector. AI4Mars imagery alone does not make an off-the-shelf detector valid.
- **Curate, do not generate.** 4-5 common rock types repeated + 2-3 distinct anomalies. Generating hundreds of unique rocks would flatten the novelty signal, kill habituation, and leave the policy nothing to arbitrate. **Variety is the enemy here.**

### Motion

Continuous driving, decisions at a fixed cadence (~1 sim-second, configurable). Straight-line heading to the committed target; reactive obstacle avoidance in SIM only; **no global planner** (that is PS 03).

*Why not waypoint-teleport:* it kills the uncertainty story. The no-threshold defense depends on approaching a target so it grows in frame and confidence climbs. No intermediate frames -> no approach -> the loop never converges. Continuous motion is load-bearing, not polish.

*Literature anchor:* MSL AutoNav had to **stop to think**; Perseverance ENav+ACE **thinks while driving**. Our cadence sits between them — say so.

### The two demo runs (non-negotiable)

1. **Stay-on-task** — low budget / weak anomaly -> reaches the marker.
2. **Deviate** — healthy budget + strong anomaly -> investigates, then resumes.

Same binary, different config. One run is an argmax; two runs are a policy.

### Demo beats to engineer deliberately

- **God view + rover camera side by side.** The gap between what is true and what the rover can see *is the problem being solved*, made visible.
- **Detection overlay** (boxes, class, confidence) on the live camera feed — proof perception is real, not scene-graph lookup.
- **The late interrupt.** Operator hits stop; it lands 60 s later; the rover already decided. Best single argument for autonomy in the whole demo.

---

## Honest boundaries (state before a judge does)

- Visual classification only — **no composition analysis** (needs ChemCam-style spectrometry).
- Markers are **confirmed/reached, not collected**.
- Budget is **simulated**.
- **Novelty is not scientific importance** — statistical unusualness only.
- Perception runs on **rendered frames**; sim-to-real transfer is not claimed.
- Curiosity scoring and budget-awareness are **prior art**; the action policy is ours.

## Verified figures safe for slides

Earth-Mars one-way delay **3-22 min** · AEGIS **>93%** vs **~24%** targeting (Science Robotics, verbatim) · all AEGIS observations geochemically successful · scene parsing in tens-hundreds of seconds · RAD750 **@ 200 MHz** · AI4Mars ~35k images / ~326k labels / 4 classes.
**Do NOT use:** "256 -> 327 per sol" (journalist misread) · "25% ChemCam increase" (unverified) · "light-minutes" for the Mars delay.

## Key citations

- AEGIS: https://www.science.org/doi/10.1126/scirobotics.aan4582
- Perseverance autonomy + OnBoard Planner: https://www.science.org/doi/10.1126/scirobotics.adi3099
- ARTPS: https://arxiv.org/abs/2509.00042
- Novelty detection (Stefanuk & Skonieczny 2022): https://www.frontiersin.org/journals/robotics-and-ai/articles/10.3389/frobt.2022.974397/full
- AI4Mars: https://openaccess.thecvf.com/content/CVPR2021W/AI4Space/papers/Swan_AI4MARS_A_Dataset_for_Terrain-Aware_Autonomous_Driving_on_Mars_CVPRW_2021_paper.pdf
