# novelty.md — the core idea (design source of truth)

**Read alongside `context.md`. Where they conflict on the idea/scoring/decision, THIS file wins.**
**v3 · 2026-09-07**
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

**Verified ARTPS quotes:** *"designed for edge-compute constraints, respecting memory/energy budgets, timing requirements, and communication latency"* · *"balances scientific value with operational budgets"* · *"explainable diagnostics suitable for operator-in-the-loop workflows"* · **future work:** *"active exploration policies on edge devices with strict power budgets."*

**Our contribution:** the closed-loop action policy. **ARTPS ranks; we act.**

## Prior art — never claim these

- The curiosity/anomaly score is **not ours** (ARTPS 2025; Kerner et al. 2018/2020; Wagstaff DEMUD 2013).
- Budget-aware scoring is **not ours** (ARTPS does it).
- **Never say** "nobody thought of finding the unexpected" or "we invented budget-aware autonomy." False and checkable.
- **Ours:** the autonomous act-or-stay policy under a *competing mission obligation*, executed onboard, with an audit trail.

**The precise fresh ground:** ARTPS ranks curiosity against *nothing*. Our rover has a **contract** — reach these markers — and must trade discovery against a promise it is not allowed to break. That competing-obligation framing is the novel structure.

---

## The equation

**1. Value — two streams**
```
M_i = p_i x c_i          mission value   (p = 10 marker, 1 common rock)
C_i = n_i x c_i          curiosity value (n = novelty score in [0,1])
```

**2. Cost — what going there spends**
```
Cost_i = alpha*d_i + beta*t_i      (drive distance + investigation dwell, normalised)
```

**3. Slack — the adaptive core**
```
B      = remaining budget
B_req  = budget needed to finish the remaining assigned markers
S      = (B - B_req) / B           discretionary fraction
w_c    = max(0, S)^gamma           curiosity weight
```
`S` is budget *beyond what the job requires*. Negative -> behind schedule. `gamma` is one temperament dial: high = cautious, low = eager.

**4. Utility**
```
U_i = (M_i + w_c * C_i) / (Cost_i + eps)
target* = argmax U_i
```

**5. Hard gate — never strand the mission**
```
accept target*  iff  B - Cost(target*) >= B_req_after * margin
else -> fall back to the best mission target
```

**Why this is defensible:** mission urgency needs no separate term. As budget drains toward what the mission requires, `S -> 0`, so `w_c -> 0` and curiosity **switches itself off**. The rover becomes single-minded exactly when it should, with no rule telling it to.

**Worked example (matches the audit record in `interface-contract.md` section 5):**
```
budget 742, mission needs 490      -> S = (742-490)/742 = 0.34
gamma = 2                          -> w_c = 0.34^2 = 0.12
marker M02:  10 x 0.58 = 5.80  / cost 3.31          -> U = 1.75
anomaly A07: 0.82 x 0.71 = 0.58, x w_c = 0.07 / cost 1.14 -> U = 0.06
decision: stay on task
```
Same scene with budget 950 and gamma 1 gives S = 0.48, w_c = 0.48, anomaly U = 0.24 -- and if mission utility is lower at that moment, the rover deviates. **Same code, different slack: that is the whole demo.**

**The one-liner:** *curiosity never costs it the mission.*

Every term is loggable, so the audit trail is free (see `interface-contract.md` section 5).

---

## Amplifier novelties (secondary — never dilute the main claim)

1. **The downlink is also a decision.** At the report window bandwidth is scarce; the rover ranks what is worth the bits with the same utility machinery. Grounded in real practice (OASIS `WATCH`). Makes the panel meaningful — **the humans only see what the rover chose to show them.**
2. **Habituation — nearly free.** With novelty as embedding-distance from a running memory, the fifth identical striped rock scores near zero *because the first one is now in memory*. Curiosity saturates on repetition with no code written for it. Emergent, scientifically correct, excellent Q&A material.
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
- **Terrain and rocks textured with real AI4Mars imagery** -> keeps YOLO inside its training distribution and makes the world look credible.
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
