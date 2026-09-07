# Progress and restart guide

Last updated: 2026-09-07. Owner: Jabin.

**Current: Dev's simulator merged; initial real Godot + BRAIN integration passed.**

Preserved prior BRAIN in `0e28b90`, merged Dev's `151c4a0` in `8d602bf`, then
corrected integration mismatches. Nothing was pushed. The real BRAIN (classical
fallback, not Dev's probe/dummy) received 525 rendered frames, emitted 96 valid
actions, stopped when disconnected, reconnected and confirmed M02 at 61.8 s.
The checked post-disconnect window showed 0.00 m motion. Dev's verify_run.py
also accepts the final recording. See [phase2-integration.md](phase2-integration.md)
for paths, commands, coarse camera range measurements and energy accounting.

Checks now pass: 6 foundation + 28 policy/runtime + 12 training preparation +
5 novelty preparation = 51 Python checks; Godot integration assertions pass,
Python compilation and git diff --check pass. Real-SIM acceptance is additional.
No all-marker mission, learned detector, browser PANEL or staged stay/deviate
run is claimed. Godot acceptance used a 3-second development downlink.

Phase 3 tools exist but training is not complete. Next: adapt Dev's labeller
from three classes to single-class rock, add independent capture grouping and
manifest, visually review labels, then train/evaluate and calibrate novelty.
Stop at this integration boundary before beginning that training phase.

Earlier entries below are historical and may describe the pre-SIM checkout.

## Working agreement

Read the existing context before building. Work on one phase at a time. At each
phase boundary, run appropriate checks, update the relevant Markdown files,
explain the result in beginner-friendly language, and stop for Jabin's review.
Do not automatically start the next phase. Jabin owns BRAIN; Dev owns SIM and
PANEL; Anton owns the pitch.

## Context checkpoint — complete

Reviewed all seven project Markdown documents and the BRAIN prototype, stubs,
configuration, transport validation, runtime helpers, and replay code. The
checkout contains one initial commit and no SIM or PANEL implementation. Their
absence here does not establish whether Dev has built them elsewhere.

The project is a simulated rover with a primary obligation to reach assigned
markers and an optional opportunity to inspect unusual rocks. Its contribution
is the autonomous decision to stay or deviate, executed through rover motion and
explained in an audit log. Statistical novelty is not scientific importance.
The research claims in the old notes were read, not independently reverified in
this checkpoint.

The runtime flow is:

1. SIM renders a camera image and reports the rover's own state.
2. The contract validator rejects fields outside the permitted message shape.
3. Perception turns pixels into marker IDs and candidate rock regions.
4. Novelty compares rock appearances with remembered appearances.
5. Policy compares mission value and curiosity against estimated costs.
6. An action goes back to SIM, which moves and charges the actual simulated cost.
7. The next image lets BRAIN reconsider. This feedback is the closed loop.
8. PANEL receives selected images and explanations through a real-time delay.

## Verified foundation

Added `brain/check_foundation.py`, runnable from the repository root with:

```powershell
& 'C:\Users\Jabin M\AppData\Local\Programs\Python\Python313\python.exe' brain/check_foundation.py
```

Result: **6 tests passed** on Python 3.13.5. They cover the existing contract
examples and rejection checks, forbidden fields at every observation object
boundary, invalid budget numbers, NaN rejection in JSON output, latest-frame
replacement, and ordered delivery after a short real-time delay.

At the initial context checkpoint, these checks proved useful pieces of plumbing.
They did **not** prove JPEG decoding,
ArUco detection, WebSocket integration, GPU execution, a 60-second end-to-end delay,
or successful mission behavior. No feature-building phase is marked complete.

Environment inspected at the initial context checkpoint (superseded by Phase 0):

- Python 3.13.5 exists but has none of the checked BRAIN dependencies.
- Python 3.10.11 has NumPy, PyYAML, websockets, and torch discoverable; OpenCV,
  torchvision, and ultralytics are absent. Presence is not an import or CUDA test.
- No project venv exists in this checkout. No packages were installed in this
  checkpoint. Python installation paths required sandbox escalation to execute.

## Phase 0 — BRAIN environment and runnable baseline complete

Built a project-local `.venv` with Python 3.13.5 and installed the existing Windows
CUDA requirements successfully. `pip check` reports no broken requirements. The
full package snapshot is `brain/requirements-win-lock.txt`; run instructions are
in `brain/README.md`. Existing global Python installations were not modified.

Verified on this laptop:

- PyTorch 2.14.0+cu130, torchvision 0.29.0+cu130, CUDA runtime 13.0, RTX 5060 Laptop
  GPU. Matrix multiplication and a ResNet18 forward pass execute on the GPU with
  finite results. The ResNet used random weights: this checks GPU execution, not
  learned recognition quality.
- OpenCV 4.14.0 detects real DICT_4X4_50 marker pixels after JPEG encoding. M02
  at three horizontal positions gave bearings -15.19, -0.05, and +15.10 degrees,
  and a 4.44 m range estimate (expected approximately 4.43 m). Blank input produced
  no detections. Detection overlays were generated and visually inspected.
- Added `brain/check_phase0.py` to launch actual BRAIN, stub SIM, and stub PANEL
  processes on temporary localhost ports and validate the resulting recordings.
- Fixed a startup blocker in `Tracker.match`: two boxes in one frame could reuse
  the same tracking ID, causing audit validation to stop BRAIN. A track can now be
  matched only from an earlier frame. Regression checks cover same-frame exclusion,
  retention from the previous frame, and unique IDs in three actual stub frames.

| Acceptance run | Frames | Valid actions | Delivered telemetry | Panel JPEGs | Measured downlink delay |
|---|---:|---:|---:|---:|---|
| Short delay | 54 | 11 | 8 | 32 | 3.000–3.009 s |
| Full delay | 339 | 68 | 8 | 32 | 60.000–60.014 s |

The full run moved from (0, 0) to (2.017, 0.058) m. Budget fell from 950.000 to
947.302 Wh. Each action passed the current contract arithmetic checks, decisions
were at least one physics second apart, and saved panel JPEGs decoded correctly.
Only the first eight messages had time to emerge from the delay queue before the
test stopped; this is expected for a roughly 68-second run with a 60-second delay.

Evidence folders (ignored by Git):

- `recordings/phase0-20260907-132959/` — short-delay report, configs, logs, images.
- `recordings/phase0-20260907-133044/` — full-delay report, configs, logs, images.
- `recordings/phase0-20260907-132804/` — initial failing run that exposed duplicate IDs.

Also passed: all six foundation tests in the new venv, Python compilation checks,
and Git whitespace checks.

**Scope and limits:** The tested loop uses ArUco + simple blob proposals + histogram
memory on CPU. GPU execution was checked separately. No rock model was trained or
downloaded. The check uses its own 1x-time configuration with 5 Hz JPEGs and 1 Hz
decisions; shared `brain/config.yaml` remains the earlier 60x profile. No marker was
confirmed during this short run, and target switching remains visible. This proves
the communication/perception baseline, not stable mission completion, novelty
quality, delayed uplink behavior, Godot, or the browser PANEL.

**Beginner explanation:** We gave the existing BRAIN a working Python workspace,
checked that its eyes can read a marker from an image, and confirmed that its GPU
can execute calculations. Then we connected the pieces: the simulated body sent
images, BRAIN replied with commands, the body moved and spent energy, and the
scientist's console saw the explanation a minute later. The duplicate-ID fix
prevents two visible rocks being confused as one entry in that explanation.
The next phase improves how BRAIN chooses, remembers, and sticks with a target.

## Initial context audit (historical, before Phase 1)

| Area | Current implementation | Remaining work |
|---|---|---|
| Curiosity | `n * confidence` | Implement and expose the planned `k=10` scale consistently in policy and audit validation |
| Costs and reserve | `cost_est` currently holds Wh; reserve lacks its denominator in the audit | Separate physical cost from normalized cost and make gate arithmetic recomputable |
| Budget fallback | A failed gate can select a mission target without a new affordability check | Verify affordability and reserve for the action actually executed |
| Novelty | Linear cosine-distance score; memory on track expiry or investigation start | Implement the planned warm-up and staged admission, then calibrate on actual crops |
| Rock perception | Saturation blobs, or all detections from the configured YOLO model | Keep fallback explicit; require trained single-class rock weights for the learned path |
| Marker confidence | Apparent-size proxy only | Add detection-history proxy and verify on rendered JPEGs |
| Commitment | Stores target ID; no planned switch ratio or lock | Add hysteresis and visited-location handling |
| Time | Shared config and stub use 60x compression | Reconcile physics-second cadence, dwell, speed, and cost together |
| Observation transport | Header followed by one JPEG; state advances when JPEG arrives | Resolve the proposed 10 Hz headers / 5 Hz JPEGs before Dev integrates |
| PANEL images | Code sends binary JPEG attachments; panel.md says base64 JSON | Document one agreed wire format; current executable contract uses binary attachments |
| PANEL clock | Code emits optional monotonic `clock` fields | Reconcile notes requesting epoch wall stamps with the actual wire format |
| Uplink | Contract requires issued/arrival fields omitted by panel.md's sample | Correct the sample when the shared contract is reconciled |
| Commands | `force_investigate` always becomes stale; gamma is not clamped | Implement or explicitly document unsupported behavior; clamp policy input |
| Runtime | Pending header shared across SIM connections; workers not supervised | Isolate connections and prevent silent worker failure during integration |
| Static page server | Absent from BRAIN and stub BRAIN | Add when wiring Dev's PANEL |

The staging numbers in brain.md also need recalculation: a three-marker mission
with default unseen ranges of 70 m does not automatically imply a 490 Wh reserve,
and the displayed utility ratios do not match the claimed margins. Treat the
two runs as acceptance tests to establish, not already verified outcomes.

## Completed phase scope — Phase 0, BRAIN environment and runnable baseline

1. Use one explicit project venv. Verify package availability and compatible
   versions before installing; existing requirement pins are not proven by this
   checkout. Verify CUDA by an actual GPU operation, not package presence.
2. Prove ArUco generation, JPEG decoding, marker ID, bearing, and approximate range
   with synthetic camera frames. Keep the CPU fallback available.
3. Run stub SIM → real BRAIN → stub PANEL; verify valid actions and attachments.
4. Record measured results, exact run commands, and outstanding limitations here
   and in brain.md / plan.md. Stop and explain before Phase 1.

The BRAIN baseline scope above is complete. Phase 1 is the corrected BRAIN autonomy implementation;
Phase 2 is real Godot integration; Phase 3 is learned perception and PANEL;
Phase 4 stages and records both runs; Phase 5 rehearses and hands off the pitch.

## Phase 1 — BRAIN autonomy complete, 2026-09-07

Implemented and stopped before Godot integration:

- Curiosity scale 10; no rounding before decisions; Wh costs separated from normalized
  utility costs. Strict audit v2 validates candidate arithmetic and the selected command.
- Every fallback and deferred target passes affordability and a post-action mission
  reserve check. Remaining marker costs are estimated from the proposed target location.
- 1.3x switching hysteresis, 5 s commitment lock, new-candidate exception, brief estimated
  target retention, deferred expiry/reacquisition, and visited-position suppression.
- Investigation keeps the correct audited target and rechecks remaining dwell. Completion
  learns once and resumes selection; abort cancels completion and applies a 30 s cooldown.
- Bounded staged memory: 60 s warm-up, 30 s pending admission, protected approach/dwell,
  completion-time learning, calibrated cosine distance with a tau floor.
- Pretrained ResNet18 on RTX 5060: 160-pixel input, finite 512-value unit embedding.
  Actual BRAIN loop with this encoder passes; CPU histogram fallback remains.
- Marker detection-history confidence proxy and heading-corrected tracking. Learned
  rock inference requires local single-class `rock` weights; training remains Phase 3.
- Shared 1x physics, 5 Hz paired JSON/JPEG, 1 Hz decisions, energy rates, 5 s investigation,
  3 s confirmation, and 0.8 m marker size. Canonical boundary is `interface-contract.md`.
- Isolated SIM sessions, strict header pairing and monotonic sequences, stale-result
  rejection, supervised worker failure, and a 2.5 s command watchdog in the Python stub.
- Clamped gamma uplinks, empty assignment handling, corrected binary-image/clock docs.
  `force_investigate` is explicitly unsupported and executes no override.

Updated implementation: policy, novelty, perception, main runtime, contract, config,
stubs, and checks. Updated docs: brain, novelty, interface contract, plan, context,
SIM, PANEL, progress, and runbook.

### Phase 1 evidence

**27 Phase 1 tests and 6 foundation tests pass.** Cases cover both decision branches,
32 confidence-variation decisions, affordability, zero budget/obligation, commitment,
deferred targets, investigation lifecycle, audit tampering, memory staging/bounds,
marker confidence, session isolation, worker failure, uplinks, and simulator dwell/watchdog.
Python compilation and Git whitespace checks pass.

| Runtime check | Frames | Actions | Downlinks | Delay | Evidence under recordings/ |
|---|---:|---:|---:|---|---|
| CPU + delayed gamma uplink | 69 | 14 | 11 | 3.000–3.014 s | phase0-20260907-135409 |
| Pretrained GPU encoder | 55 | 11 | 8 | 3.001–3.017 s | phase0-20260907-135616 |
| Full-delay CPU regression | 340 | 68 | 8 | 60.001–60.007 s | phase0-20260907-135704-754461 |

All emitted actions passed audit validation; delivered JPEGs decoded. The full run
spent 8.838 Wh and ended at (6.194, -2.679) m. **No marker completed in that run.**
Perception, avoidance, and scene geometry still need integration calibration; this
is not a complete stay/deviate Godot demonstration. Memory separation on Dev's assets
is also unverified. The gate constrains estimates, not guaranteed actual energy use.

Controlled example: same marker at 30 m (c=.6), rock at 6 m (n=.85, c=.8), and two
unseen assigned markers; mission estimate 179 Wh.

| Case | Budget / gamma | Marker U | Rock U | Selected |
|---|---|---:|---:|---|
| Stay | 210 Wh / 2 | 1.817631 | 0.134588 | M01 |
| Deviate | 400 Wh / 1 | 1.817631 | 3.412352 | A01 |

Stay gate: `177 >= 146*1.15`; deviate gate: `389 >= 173*1.15`.
Exact audits: `brain/phase1-examples.json`. These replace the old inconsistent
560/950 Wh staging/margin claims. Actual scene budgets are still Phase 4 work.

GPU cache and run evidence are ignored by Git. Test processes are stopped. No
commit, push, deployment, or message to Dev was performed.

### Beginner explanation of Phase 1

BRAIN now asks: “How valuable is this target?”, “How much energy might it take?”,
and “Would enough remain for my assigned job?” A discovery must pass both the score
comparison and budget checks. Small score changes no longer immediately turn it around.

Memory learns at a more useful time: seeing a rock does not instantly make it familiar
while approaching. A completed investigation admits its appearance and remembers the
location, helping BRAIN move on. The audit explains the command actually sent.

## Next phase — Phase 2, real Godot integration

**2026-09-07 update:** Jabin authorized this phase. The checkout and freshly fetched
remote contain no Godot project. `origin/main` is still the initial `fd821f0` commit;
no other remote branches were found. Asked Jabin for Dev's project path/repository.
Prepared camera/coordinate calibration and runtime acceptance checks in
`phase2-integration.md`. Phase 2 is incomplete pending the simulator source.

Obtain Dev's SIM in this checkout and align it with `interface-contract.md` and
`brain/config.yaml`. Verify camera/FOV/marker width, motion, dwell and energy charges,
watchdog/reconnect on Windows. Begin with marker reaching. Dev has not yet confirmed
the revised contract; no message has been sent. Continue this authorized phase when
the simulator location is supplied; stop before Phase 3.

## Initial context checkpoint explanation (historical)

Think of SIM as the rover's body and surroundings, BRAIN as its onboard decision
software, and PANEL as the distant scientist's screen. The image is its view;
perception gives names and rough directions to things in that view. Memory asks
whether a rock looks familiar. Policy asks whether visiting it is worth spending
resources needed for the assigned job.

This checkpoint checked the wiring before improving those abilities. The input
guard rejects extra fields that could hand BRAIN the answers. The newest-image
holder prevents old frames piling up. The delay queue prevents immediate message
delivery. The next phase makes that wiring carry real camera images end to end.
