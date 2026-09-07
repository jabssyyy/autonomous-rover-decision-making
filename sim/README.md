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
python tools/aruco_probe.py --target M02    # real OpenCV, actually chases a marker

# 2. the sim (Godot is the WebSocket CLIENT, so start order does not matter)
godot --path sim
```

Keys: `M` manual drive (arrows steer) · `C` chase/top-down · `P` dump a capture PNG to
`user://` · `Esc` quit. Command line: `--brain=ws://HOST:PORT`, `--config=PATH`,
`--dumpat=SECONDS`.

## What is verified, not just written

Run end to end on an M3 Pro against `tools/aruco_probe.py`:

| Check | Result |
|---|---|
| Contract-valid observations | `contract.py` accepted 500+ frames, zero violations |
| JPEG over the link | 26–27 KB per frame at q0.75, 5 Hz, zero drops |
| ArUco survives render + JPEG | `DICT_4X4_50` detected from **~28 m** (16 px marker) |
| Range estimate `f_px·W_m/w_px` | within **−0.5 m at 18 m** of ground truth |
| Bearing / FOV chain | bearing converges to 0.00° as the rover closes — `KEEP_WIDTH` is honest |
| Budget | drains as `1.5 Wh/m + 0.002 Wh/sim-s`, matches by hand |
| Closed loop, end to end | rover found M02 **from pixels alone**, drove to it, SIM confirmed arrival — marker held in 221/233 frames, 16 px at acquisition to 349 px at arrival |
| Frame rate | 79–120 fps with the 5 Hz readback stall included |

## Assets — all free to use, and all replaceable

| What | Source | Licence |
|---|---|---|
| Rover | NASA `Mars 2020 Perseverance Rover.glb`, [NASA-3D-Resources](https://github.com/nasa/NASA-3D-Resources) | NASA — not subject to copyright in the US |
| Rocks | Poly Haven `moon_rock_01…05`, `stone_01`, `rock_face_01`, `namaqualand_stones_01` | CC0 |
| Ground | Poly Haven `cracked_red_ground` (albedo/normal/rough) | CC0 |
| Markers | generated with `cv2.aruco.generateImageMarker`, `DICT_4X4_50`, 720 px with a 120 px quiet zone | — |

**The NASA GLB ships Draco-compressed and Godot cannot read it.** It was decompressed once with
`npx @gltf-transform/cli copy in.glb out.glb` (4.99 MB → 10.08 MB). If you ever re-download it,
do that again or the import fails with `KHR_draco_mesh_compression is not supported`.

## Traps this project already hit, so you do not have to

1. **Terrain winding.** Godot front faces are clockwise. Wind them the other way and the
   terrain is back-face culled: physics still works, the rover still drives, and you look
   straight through the ground at the sky. `terrain.gd` builds `a,b,c / b,d,c`.
2. **The marker quiet zone scales every range.** The PNG is 720 px but the ArUco pattern is
   only 480 px of it. `config.yaml`'s `marker_width_m` is the **pattern** width and
   `world.gd` divides by `PATTERN_FRACTION` to size the quad. Size the quad directly and
   every range BRAIN reports is 1.5× too far — and looks completely plausible.
3. **`was_string_packet()` describes the packet you already fetched**, not the next one.
   Call it before `get_packet()` and every action is off by one.
4. **`drive.speed` is a fraction in [0, 1]**, not m/s — `contract.py` enforces the range.
   Dividing it by `max_speed` again pins the rover at full throttle.
5. **The NASA mesh faces +Z**; Godot's forward is −Z. Without `rotation.y = PI` the rover
   drives backwards for the whole demo.
6. **`EXPAND_IGNORE_SIZE` must be set before `size`** on the rover-cam TextureRect, or the
   640×480 minimum size clamps it straight back up and it overflows the panel.
7. **Poly Haven rocks ship LOD0/LOD1/LOD2 as siblings.** Godot renders all three at once.
   `_strip_lods()` drops the rest.
8. **Poly Haven "moon rocks" are 7–25 cm pebble scans.** Every common type carries its own
   `base` scale in `world.gd`; jitter multiplies that, it never sets absolute size.
9. **Do not stop dead on a hazard.** A full stop deadlocks: the rover brakes, the avoidance
   swings the heading, the ray that sees the rock moves to the next fan angle, and it never
   clears. It crawls at 35 % instead, and only hard-stops inside 0.9 m.
10. **`sim/assets/.gdignore` blocks the whole import.** It was there to stop half-downloaded
    assets importing; it has been removed.

## Layout

```
sim/
  main.tscn        one node; everything else is built in code, so no .tscn drift
  scripts/
    main.gd        orchestrator: sim clock, budget, observation assembly, HUD, god cam
    terrain.gd     ArrayMesh + HeightMapShape3D from ONE height function
    world.gd       seeded rock scatter, ArUco quads, marker ground truth
    rover.gd       CharacterBody3D, heading control, hazard rays, reactive avoidance
    camera_rig.gd  SubViewport + RoverCam + RemoteTransform3D + JPEG capture
    sim_link.gd    WebSocketPeer client
    sim_config.gd  reads the shared brain/config.yaml
```

## A07 staging

A07 sits at (6, −20), ~5.7 m off the straight line to M02 at (1.5, −32), which is the
staging `brain.md` §5.3 tuned the two runs against. A 1.75 m instance of a **common** rock
type at (3.9, −13.1) sits on the sight line from spawn and hides it; A07 comes into frame
around 20 real seconds in, once the rover has driven past. Nothing is hidden and revealed
by script — it is occlusion, so a judge can walk the god camera around and see why.

## Still open

- **Auto-labeller for YOLO** (`sim.md` §8, phase 3) is not built.
- `decision_interval_sim_s: 1.0` in `config.yaml` is inconsistent with
  `time_compression: 60`: SIM's clock runs 60× real, so a 1 sim-second interval fires on
  every single frame. BRAIN decides every observation right now. If ~1 Hz real decisions
  are wanted, that key should be **60**. Jabin's call — SIM does not read it.
