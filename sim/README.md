> **Current Phase 3 result:** Rock detector trained on 1,500 images, held-out
> mAP50 0.8979, installed and tested with real Godot. Novelty calibration remains
> incomplete. See [measured results](../phase3-results.md). Older status notes below are historical.

> **Windows integration update (2026-09-07):** Real BRAIN integration now passes;
> see [phase2-integration.md](../phase2-integration.md) for tested commands.
> Current shared config is 1x time, 0.8 m marker, 1 Wh/m drive and 1 Wh/s dwell.
> Older Mac results/settings below are historical. Current runtime uses audit v2,
> a 3-second committed marker dwell, and disconnect/command-timeout stops.
> The labeller below still emits three classes; adapt it before rock-only training.

# SIM — Godot 4.7.2 Mars rover simulator

The world half of the project. Renders Mars, drives the rover, owns the budget, and
ships one 640×480 JPEG plus a pose/budget header to BRAIN five times a second.

> **THE RULE:** BRAIN receives pixels, its own pose and its own budget. Nothing else.
> Everything the rover "knows" about the world it derives from the image. If SIM ever
> hands BRAIN an object list, the identification half of the problem statement is gone.

## Run it

```bash
# 1. a BRAIN on :8765 — either of these
python brain/stub_brain.py --delay 3        # canned decisions, exercises the whole link
python tools/aruco_probe.py --target M02    # real OpenCV: works the assigned marker list

# 2. the sim (Godot is the WebSocket CLIENT, so start order does not matter)
godot --path sim
```

**Keys:** drag / wheel — orbit the god camera · `C` chase / orbit / top-down ·
`F` camera frustum · `R` hazard rays · `H` hide the HUD (for clean recording) ·
`M` manual drive (arrows) · `P` dump a capture PNG · `Shift+Esc` quit.

**Flags** (after a bare `--`):

| Flag | Does |
|---|---|
| `--brain=ws://HOST:PORT` | point at a BRAIN somewhere else |
| `--config=PATH` | use a different shared config |
| `--record=NAME` | write the run to `runs/NAME/` (frames + jsonl + manifest) |
| `--label=N [--label-name=X]` | render N labelled YOLO frames and exit |
| `--lowfx` | fewer pebbles, shorter shadows, no fog — for a weak laptop |
| `--ssao` | turn SSAO back on (costs ~25 fps) |
| `--top`, `--dumpat=SECONDS` | start top-down; dump a capture at T |

## The two demo runs

`interface-contract.md` §9: the two runs are the same binary with a different start
budget and gamma, and **nothing else changes** — that is what makes it a policy rather
than a script. There is one shared `config.yaml`, and this rewrites the two lines:

```bash
python tools/set_run.py deviate    # 1000 Wh, gamma 1.0 — slack, so it goes and looks
python tools/set_run.py stay       #  420 Wh, gamma 3.0 — thin, so it stays on task
python tools/set_run.py show
```

Restart SIM and BRAIN afterwards; both read the file once at startup. The world seed
is untouched, so the rocks, markers and anomalies are in identical places both times.

## Tools

| Tool | What it is for |
|---|---|
| `tools/aruco_probe.py` | a 40-line BRAIN that only knows OpenCV. Detects markers in the JPEG, steers on the bearing it computes, works the whole assigned list, dwells on arrival. Proves the marker leg before Jabin's stack exists. |
| `tools/verify_run.py` | replays a recorded run through `contract.py`: every observation, JPEG and action, plus the audit arithmetic, plus sanity (seq monotonic, budget only drains, markers only accumulate). Non-zero exit, so it can gate a push. |
| `tools/set_run.py` | switches between the stay run and the deviate run. |

## What is verified, not just written

Run end to end on an M3 Pro against `tools/aruco_probe.py`:

| Check | Result |
|---|---|
| Contract-valid observations | `contract.py` accepted every frame of a 488-frame run, zero violations |
| Recorded run re-validates | `verify_run.py`: 488 observations, 488 actions, all three decision types, **OK** |
| JPEG over the link | 45–56 KB per frame at q0.75, 5 Hz, zero drops |
| ArUco survives render + JPEG | `DICT_4X4_50` detected from **~30 m** (22 px marker), held in 410/417 frames |
| Range estimate `f_px·W_m/w_px` | within **~1 m at 20–30 m** of ground truth |
| Bearing / FOV chain | bearing converges to 0.00° as the rover closes — `KEEP_WIDTH` is honest |
| Closed loop | rover found M02 **from pixels alone**, drove 32 m to it, SIM confirmed arrival |
| Budget | `1.5 Wh/m + 0.002 Wh/sim-s`, 1000 → 931 Wh over the run, matches by hand |
| YOLO set | 40 frames / 160 boxes in 0.7 s (≈26 s for 1500), boxes verified by overlay |
| Frame rate | 100–145 fps headless, 50–80 fps windowed at 3456×1944 with the 5 Hz readback |

## Assets — all free to use, and all replaceable

| What | Source | Licence |
|---|---|---|
| Rover | NASA `Mars 2020 Perseverance Rover.glb`, [NASA-3D-Resources](https://github.com/nasa/NASA-3D-Resources) — 2.71 × 1.85 × 3.11 m, already in real metres | NASA — not subject to copyright in the US |
| Common rocks | Poly Haven `namaqualand_boulder_02…06` (1k) — five metre-scale desert scans, each with its own albedo/normal/ARM | CC0 |
| Anomalies | Poly Haven `rock_face_01` (A07, pale layered outcrop), `stone_01` (A11), `namaqualand_stones_01` (A14) | CC0 |
| Gravel | Poly Haven `moon_rock_02` texture on a procedural pebble, 2600 MultiMesh instances | CC0 |
| Ground | Poly Haven `cracked_red_ground` + `dry_ground_rocks`, blended by noise in a shader | CC0 |
| Markers | `cv2.aruco.generateImageMarker`, `DICT_4X4_50`, 720 px with a 120 px quiet zone | — |

**The NASA GLB ships Draco-compressed and Godot cannot read it.** It was decompressed once with
`npx @gltf-transform/cli copy in.glb out.glb` (4.99 MB → 10.08 MB). If you re-download it,
do that again or the import fails with `KHR_draco_mesh_compression is not supported`.

## A07 staging

A07 sits at (6, −20), ~5.7 m off the straight line to M02 at (1.5, −32) — the staging
`brain.md` §5.3 tuned the two runs against. A 2.7 m instance of a **common** boulder type
at (3.9, −13.1) sits on the sight line from spawn and hides it; A07 comes into frame
around 20 s in, once the rover has driven past. Nothing is hidden and revealed by
script — it is occlusion, so a judge can orbit the god camera and see why.

A07 is also the only rock with a pale tint. The "differ in texture, not tint" rule
(`brain.md` §6) is about keeping the five **common** types separable from each other;
an anomaly is supposed to be anomalous, and a light-toned outcrop on dusty red basalt
is exactly the thing Perseverance drives over to look at.

## Traps this project already hit, so you do not have to

1. **Terrain winding.** Godot front faces are clockwise. Wind them the other way and the
   terrain is back-face culled: physics still works, the rover still drives, and you look
   straight through the ground at the sky.
2. **The marker quiet zone scales every range.** The PNG is 720 px but the ArUco pattern is
   only 480 px of it. `config.yaml`'s `marker_width_m` is the **pattern** width and
   `world.gd` divides by `PATTERN_FRACTION` to size the quad. Size the quad directly and
   every range BRAIN reports is 1.5× too far — and looks completely plausible.
3. **`was_string_packet()` describes the packet you already fetched**, not the next one.
   Call it before `get_packet()` and every action is off by one.
4. **Godot's JSON parser makes every number a float.** `in_reply_to_seq` comes back as
   `1423.0` and is written straight back out that way, so anything that re-emits an action
   fails `contract.py`. `sim_link.gd` casts it back to int at the parse boundary.
5. **`drive.speed` is a fraction in [0, 1]**, not m/s — `contract.py` enforces the range.
6. **The NASA mesh faces +Z**; Godot's forward is −Z. Without `rotation.y = PI` the rover
   drives backwards for the whole demo.
7. **A single hazard ray height is a sensor lie.** A fan at 0.9 m sails over a 0.7 m
   boulder the 1.2 m collision box still walks into: the rover jams while `hazard.range_m`
   reports a clear 12 m. There are now two fans (0.35 m and 0.9 m) plus a stuck detector
   that backs out after 1.5 s of commanded-but-not-moving.
8. **`Basis(x, y, z)` takes columns and must stay right-handed** (`right × up = −forward`).
   Flip one and `slerp` refuses the reflection every frame.
9. **`set_anchors_preset` leaves a Control at zero size** under a CanvasLayer, and every
   panel anchored right or bottom silently never appears. Use the `_and_offsets_` variant.
10. **`EXPAND_IGNORE_SIZE` must be set before `size`** on a TextureRect, or the 640×480
    minimum clamps it straight back up.
11. **Poly Haven rocks ship LOD0/LOD1/LOD2 as siblings** — Godot renders all of them.
12. **Poly Haven "moon rocks" are 7–25 cm pebble scans.** Every rock type carries a `base`
    scale so call sites ask for a size in metres.
13. **Don't stop dead on a hazard.** A full stop deadlocks; it crawls at 35 % instead.
14. **`sim/assets/.gdignore` blocks the whole import.** It has been removed.

## Layout

```
sim/
  main.tscn        one node; everything else is built in code, so no .tscn drift
  scripts/
    main.gd        orchestrator: sim clock, budget, observation assembly, cameras, input
    terrain.gd     ArrayMesh + HeightMapShape3D from ONE height function, + horizon skirt
    world.gd       seeded boulder scatter, gravel MultiMesh, ArUco quads, ground truth
    rover.gd       CharacterBody3D, heading control, hazard fans, avoidance, wheel tracks
    camera_rig.gd  SubViewport + RoverCam + RemoteTransform3D + JPEG capture
    sim_link.gd    WebSocketPeer client
    sim_config.gd  reads the shared brain/config.yaml
    hud.gd         instrument panel, budget bar, mission chips, minimap
    debug_view.gd  camera frustum + ground wedge + hazard fan (god view only, layer 2)
    recorder.gd    --record: frames + observations.jsonl + actions.jsonl + manifest
    labeller.gd    --label: offline YOLO training set (NOT runtime perception)
```

## Still open

- `decision_interval_sim_s: 1.0` in `config.yaml` is inconsistent with
  `time_compression: 60`: SIM's clock runs 60× real, so a 1 sim-second interval fires on
  every frame and BRAIN decides 5×/s. If ~1 Hz real decisions are wanted, that key should
  be **60**. Jabin's call — SIM does not read it.
- The YOLO boxes are projected object AABBs, so a rotated boulder gets a slightly loose
  box. Fine for training; tighten by projecting mesh vertices if it ever matters.
- Real Jezero DEM terrain (USGS HiRISE, CC0, 1 m/post) would swap in at `height_at()` if
  the story is worth the download and a GDAL step.
