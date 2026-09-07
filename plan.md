> Phase 3 update (2026-09-07): frozen-memory novelty evaluation tooling is implemented
> alongside detector training preparation. See [Phase 3 status](phase3-perception.md).
> Actual scene training/calibration and Dev's PANEL remain pending; no GitHub pull
> until Jabin announces Dev's update.

# plan.md — build plan, phase by phase

> **Current status, 2026-09-07:** Jabin's Phase 1 BRAIN is implemented and tested.
> See [progress.md](progress.md): 27 Phase 1 tests, 6 foundation tests, pretrained
> GPU loop, delayed gamma uplink, and full 60-second downlink pass. Dev's SIM/PANEL
> and real Godot integration remain unverified. Phase 2 preparation has started,
> but the Godot project is absent from this checkout and fetched remote. Awaiting
> Dev's GitHub update, which Jabin will announce; see `phase2-integration.md`.
> Phase 2 is not complete. Jabin authorized independent training preparation:
> dataset validation/splitting and train/evaluate CLIs now exist with 12 passing
> offline checks; see `rock-training.md`. Actual Phase 3 training awaits exports.
> `brain.md` and `interface-contract.md` specify audit v2, 1x time, and paired 5 Hz frames.
> Work one phase at a time, update the relevant Markdown files, explain it to Jabin
> in beginner-friendly terms, and stop before starting the next phase.

**v1 · 2026-09-07** · Master build plan for IETE Inception '26, PS 04.1.
**Read `context-iete.md` for the research, `novelty.md` for the idea, `interface-contract.md` for the schemas.**
**Lane docs:** `brain.md` (Jabin) · `sim.md` (Dev, first) · `panel.md` (Dev, second).

> Anything in `IETE'26-PPT/` is **stale** (v6, written for the abandoned pan-tilt rig). Ignore it except the submitted deck.

---

## 0. Ownership — locked

| Who | Owns | Machine | Why |
|---|---|---|---|
| **Jabin** | **BRAIN** — perception, novelty, policy, audit log. Plus integration and running the demo. | RTX 5060, Windows 11 | Training lives inside BRAIN and only this machine has CUDA. Holds the research context; will answer the judges' questions about the policy. |
| **Dev** | **SIM first, then PANEL** | MacBook M3 Pro → GitHub → Jabin pulls | Both are the presentation layer — making the rover's reasoning visible. Godot doesn't need CUDA. |
| **Anton** | Pitch. Not interrupted. | — | The pitch is the deliverable that gets judged. |

**At demo time everything runs on Jabin's laptop.** GitHub moves *code*, not *traffic*. SIM↔BRAIN stay on `127.0.0.1`; only the PANEL is served across the LAN to Dev's Mac, and that link is already designed to be 60 s late, so network jitter is invisible.

**Order matters for Dev: SIM before PANEL.** SIM is what integration needs and it is the higher-variance piece. PANEL is the droppable one — if it isn't ready, the delay gets narrated from a console and the demo still lands.

---

## 1. THE RULE

> **BRAIN receives pixels, its own pose, and its own budget. Nothing else.**

Because Jabin no longer owns SIM, this is now enforced *structurally* — Dev's SIM simply never sends ground truth, and Jabin cannot reach for it. Keep it that way, and back it with the whitelist validator in `brain.md` §7 so a violation raises instead of passing quietly.

**One legitimate exception, and it is not a runtime one:** the sim may project rock bounding boxes into the camera **to generate YOLO training labels offline** (`sim.md` §8). That is dataset generation, not perception. At runtime BRAIN still receives only the JPEG. Say it in exactly those words if a judge asks.

---

## 2. Phases

### Phase 0 — Setup (everyone, ~45 min, do first, do not skip)

**BRAIN checkpoint:** Installed the project-root `.venv` from the existing Windows
requirements and verified actual RTX 5060 kernels. Stubs and shared config currently
live under `brain/`, not the root layout proposed below. See `brain/README.md` for
the tested commands. Do not duplicate or relocate Dev's shared files during setup.

| # | Task | Owner |
|---|---|---|
| 0.1 | Create GitHub repo `mars-rover-autonomy`, both push access | Jabin |
| 0.2 | Folder skeleton + `.gitignore` (§4) | Jabin |
| 0.3 | Install **Godot 4.7.2-stable** (standard build, *not* .NET) on both machines | Both |
| 0.4 | **Move the Godot project out of OneDrive** onto a local path — `C:\dev\rover-sim` / `~/dev/rover-sim`. OneDrive sync makes Godot hang on import and open blank projects. | Both |
| 0.5 | `config.yaml` + `stub_sim.py` + `stub_brain.py` committed at root | Jabin |
| 0.6 | BRAIN venv: **torch with CUDA first, then ultralytics** (§5) | Jabin |
| 0.7 | Prove CUDA: `python -c "import torch;print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"` | Jabin |

**0.5 is the unblock.** Once both stubs are pushed, neither builder can be blocked by the other for the rest of the day.

### Phase 1 — Both lanes against stubs (parallel, ~3 h)

**Jabin's lane complete.** Corrected policy, staged memory, commitment, audit v2,
encoder/fallback, and runtime checks pass. Dev's lane is not verified here. The shipped
classical detector is a saturation-blob fallback; MSER below is an unimplemented alternative.

Jabin builds BRAIN against `stub_sim.py`; Dev builds SIM against `stub_brain.py`. Neither needs the other to exist.

**Jabin (`brain.md`):** WebSocket server on :8765 → observation validator → ArUco detection → classical rock proposals → embedding novelty → policy → audit record → action out. Decisions printing to console with arithmetic that closes.

**Dev (`sim.md`):** Godot project, terrain + collision, rover controller, two-camera rig (god view + rover SubViewport), ArUco marker quads, rock scatter, budget accounting, WebSocket client to :8765.

**Exit criteria:** Jabin — `stub_sim.py` frames produce valid audit records once per second. Dev — rover drives to a heading sent by `stub_brain.py` and the JPEG arrives at the stub.

### Phase 2 — First real integration (⚠ the checkpoint that must happen early, ~1 h)

**Do this the moment both Phase 1 exits pass. Do not defer it.**

1. Dev pushes SIM. Jabin pulls and **runs Godot on the Windows laptop** — this is the first cross-platform run and it is where import/path/FOV bugs surface.
2. Real SIM → real BRAIN on `127.0.0.1:8765`. Rover moves under BRAIN's decisions.
3. Verify against the sim: bearings point at the right things, `est_range_m` is roughly true, budget drains.
4. Deliberately kill and restart BRAIN — confirm Godot reconnects.

**If this slips past the halfway mark of the day, cut scope to marker-reaching only and stage the demo on that.**

### Phase 3 — Perception upgrade + PANEL (parallel, ~2 h)

**Jabin:** auto-label ~1,500 frames from the sim → fine-tune YOLO26n (single class `rock`) → swap out the classical proposals. Calibrate the novelty memory against real sim crops. **Keep the classical detector as the live fallback.**

**Dev:** PANEL — delayed feed, decision log rendering the audit record, budget gauge, DELAYED clock, interrupt button. Built against `stub_brain.py`, then pointed at the real BRAIN.

### Phase 4 — Staging the two runs (~1.5 h)

The two runs are **the same binary with different config**. Nothing else changes — say exactly that to the judges.

| | Stay-on-task run | Deviate run |
|---|---|---|
| `start_budget_wh` | 560 | 950 |
| `gamma` | 2.0 | 1.0 |
| Expected | marker U ≫ anomaly U, rover ignores a strong anomaly | anomaly wins at first sighting, rover investigates, then resumes |

**Superseded staging numbers:** the 560/950 Wh and margin claims above were inconsistent.
Phase 1 establishes controlled branches at 210/400 Wh; see `brain.md` and
`brain/phase1-examples.json`. These are fixtures, not calibrated Godot demo configs.

Then: **record both runs to video.** A recording that plays is worth more than a live run that crashes. Also enable BRAIN's frame+decision dump so a run can be replayed from disk.

### Phase 5 — Demo rehearsal + pitch handoff (~1 h)

- Two laptops side by side, Jabin's on the left (truth), Dev's on the right (Earth, 60 s late).
- Rehearse **the late interrupt**: Dev hits abort during an investigation; it lands 60 s later; BRAIN logs `uplink_stale` and continues. This is the single best argument in the demo — rehearse it until the timing is reliable.
- Anton gets: the two recordings, the audit-log screenshot, the corrections in §6, and the Q&A prep already in `ppt-deck.md`.

---

## 3. Integration checkpoints (definition of done)

1. ☑ Stub sim → real brain → decisions printing with closing arithmetic (audit v2)
2. ☐ Real sim → real brain → rover moving in Godot **on the Windows laptop**
3. ☐ Telemetry reaching the panel with visible delay, from the Mac over LAN
4. ☐ Uplink round-trip including one deliberate stale interrupt
5. ☐ Both demo runs recorded end to end

---

## 4. Repo layout

```
mars-rover-autonomy/
  config.yaml            # shared truth, both processes read it
  stub_sim.py            # Jabin builds BRAIN against this
  stub_brain.py          # Dev builds SIM and PANEL against this
  requirements.txt
  brain/                 # JABIN ONLY
    main.py  perception.py  novelty.py  policy.py  audit.py  delay.py  validate.py
    weights/
  sim/                   # DEV ONLY — Godot 4.7.2 project (developed on a LOCAL path, not OneDrive)
  panel/                 # DEV ONLY
    index.html  app.js  style.css
  recordings/
```

`.gitignore`:
```
sim/.godot/
*.translation
brain/weights/*.pt
recordings/
__pycache__/
*.pyc
.venv/
```
**Commit every `*.import` and `*.uid` sidecar** — Godot needs them. Ignore only `.godot/`.

**No merge conflicts by construction:** nobody edits another person's folder. `config.yaml`, the stubs and the schemas are shared — change them only by mutual agreement, announced.

---

## 5. Environment — the traps that eat hours

**Verified environment supersedes the older installation notes in this section:**
use `.venv/Scripts/python.exe` (Python 3.13.5), torch 2.14.0+cu130, torchvision
0.29.0+cu130, OpenCV 4.14.0, and websockets 17.1. NVIDIA driver 591.91 reports
CUDA 13.1 support; the installed torch runtime is CUDA 13.0. Real GPU matrix and
convolution checks pass. The dependency snapshot is `brain/requirements-win-lock.txt`.

**RTX 5060 is Blackwell, `sm_120`.** The default PyPI `torch` on Windows is CPU-only, and `cu126` wheels have no Blackwell kernels (`CUDA error: no kernel image is available`). Only **cu128** (torch 2.7–2.11) or **cu130** (2.9+, needs driver r580+) work. Check `nvidia-smi` and pick by the reported CUDA version.

**Install order matters.** `pip install ultralytics` first resolves torch from PyPI and gives you the CPU build. Always:

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
pip install ultralytics
pip install "opencv-python<5,!=5.0.0.93" "websockets>=14" pyyaml
```

**Pin `opencv-python<5`.** OpenCV 5.0 (July 2026) is in flight with an ArUco overhaul and the migration guide is silent on `cv2.aruco`. ArUco is the uncompromised leg of the perception story — do not let it move under you today.

**Two Python stacks exist on Jabin's laptop:** `python` → 3.10.11 (has torch, websockets 16.0), `py` → 3.14. Put BRAIN in one explicit venv and always invoke it the same way. `websockets` 17.x requires ≥3.11; 16.0 on 3.10 is fine and the `websockets.asyncio` API is identical — **do not burn time upgrading Python today.**

---

## 6. Corrections to the locked docs (fold these in)

| # | Where | Issue | Fix |
|---|---|---|---|
| 12 | all three docs | ARTPS future-work quote is a **paraphrase**, not verbatim | Real text: *"We aim to integrate uncertainty more tightly into scoring, extend to multimodal fusion, and develop **active exploration policies for edge compute**."* The claim survives; the quotation marks were wrong. |
| 13 | `novelty.md` equation | With `C_i = n·c` against `p=10` markers, **the deviate run is unreachable** for any realistic geometry (the marker would need to be ~129 m away or below 8% confidence) | Add a curiosity scale: `C_i = k · n · c`, **`k = 10`**. Reached independently by two analyses. See `brain.md` §5. |
| 14 | `interface-contract.md` §5 | Audit example mixes units (`B_req` 490 Wh vs `cost_est` 3.31 normalised); `post_action_reserve` 1.52 cannot be recomputed | Emit `cost_wh` **and** `cost_est`, plus `gate.required_for_mission_after`, so a judge can check the arithmetic. |
| 15 | `interface-contract.md` §6 vs §9 | §6 shows a 60 s delay, §9 config implies 3600 sim-s | Delay is **60 real seconds**. Stamp `wall_generated_at` / `wall_delivered_at` in BRAIN. |
| 16 | `interface-contract.md` §9 | `time_compression: 60` with `decision_interval_sim_s: 1.0` = 60 decisions per real second | Define cadence, dwell and cost rates in **physics seconds (= real seconds)**. Drop time compression for the demo. |
| 17 | `interface-contract.md` §2 | Observation at 10 Hz forces frequent GPU readback | **Paired JSON + JPEG at 5 Hz** in the implemented revision. No unpaired pose-only headers. |
| 18 | `context-iete.md` §3 | "YOLOv8n fine-tuned on AI4Mars" | AI4Mars is terrain **segmentation** with no per-rock boxes. Train on **sim-auto-labelled frames** instead; AI4Mars stays as terrain **texture**. |

**Also for the pitch:** ARTPS is a single-author, non-peer-reviewed preprint. Lead credibility with AEGIS (peer-reviewed, flight-proven) and introduce ARTPS as *the most recent published attempt* — not "the state of the art". And the submitted deck says **Solution Type: Hardware + Software** while the build is now pure simulation. Anton needs an answer ready: the simulation *is* the contribution's testbed, and the delay is demonstrated rather than asserted.

---

## 7. Risk register

| Risk | Likelihood | Mitigation | Fallback |
|---|---|---|---|
| Godot/OneDrive import hang | **High** | Local path from minute one (0.4) | — |
| Cross-platform Godot break on Windows | High | Checkpoint 2 **early**, not at the end | Dev runs SIM on the Mac, BRAIN over LAN (degraded but alive) |
| `hfov` wrong → every bearing wrong | High | `keep_aspect = KEEP_WIDTH`, `fov = 60` | Recalibrate empirically against a marker at a known distance |
| JPEG > 65535 B silently dropped | High | `outbound_buffer_size = 4 MiB` before `connect_to_url` | Drop JPEG quality to 0.6 |
| torch CPU-only / wrong CUDA | High | Install order in §5; prove with 0.7 | Everything runs on CPU at 1 Hz — acceptable |
| YOLO not ready | Medium | Classical MSER proposals ship first and stay | Classical detector for the demo; it produces boxes + a confidence proxy |
| Novelty saturates or habituates too fast | Medium | Staged memory commit, `tau` floor (`brain.md` §6) | Hand-tune `d_lo`/`tau` from captured crops |
| Campus wifi client isolation | Medium | Test early with `curl -I`, not `ping` | Windows Mobile Hotspot → `http://192.168.137.1:8000` |
| Deviate run won't switch | Medium | Grid in `brain.md` §5 | Raise budget to 1000 or drop gamma to 0.3 |
| Live demo crashes | Medium | Record both runs in Phase 4 | Play the recording |
| PANEL unfinished | Low-Med | It is explicitly second and droppable | Narrate the delay from BRAIN's console |

---

## 8. Still open

1. **Two research agents did not report** — the OpenCV ArUco deep-dive and the BRAIN runtime deep-dive. `brain.md` §4 and §7 are written from the verified fragments in the other agents' findings plus first principles; **verify the exact `cv2.aruco` call signatures against your installed version before trusting them** (one line: `python -c "import cv2;print(cv2.__version__);help(cv2.aruco.ArucoDetector)"`).
2. Safety-veto rules beyond hazard-range — deliberately deferred until runs are stageable.
3. Whether the pitch reuses `ppt-deck.md` — it is stale for the sim framing; Anton's call.
