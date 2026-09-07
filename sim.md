> **Current update, 2026-09-07:** BRAIN novelty validation and a live investigation/resumption
> sequence are complete for the tested simulator profile (confirmation AUC 0.8326;
> 15-second warm-up). See [novelty results and limits](phase3-novelty-calibration.md).
> Paired stay/deviate missions and browser PANEL remain pending. Earlier status
> notes below describe previous checkpoints.

> **Current Phase 3 result:** Rock detector trained on 1,500 images, held-out
> mAP50 0.8979, installed and tested with real Godot. Novelty calibration remains
> incomplete. See [measured results](phase3-results.md). Older status notes below are historical.

> **Integration update, 2026-09-07:** Dev's `151c4a0` is merged locally.
> Real Godot + BRAIN acceptance passed: 525 frames, 96 validated actions,
> M02 confirmed, disconnect stop and reconnect verified. See
> [phase2-integration.md](phase2-integration.md). Initial marker integration
> is established; all-marker missions, browser PANEL and trained rocks remain pending.

# sim.md — SIM lane (Dev, build this FIRST)

**v1 · 2026-09-07** · Owner: **Dev**, MacBook M3 Pro → GitHub → Jabin runs it on Windows.
**Read first:** `interface-contract.md` §1–§4 (schemas), `plan.md` (phases).
**Build SIM before PANEL.** SIM is what integration needs and it is the higher-variance piece. `panel.md` comes second.

> You own the world. **Jabin's BRAIN must never learn anything about it except through the camera image.** That constraint is the project — if BRAIN can query the scene graph, the identification half of the problem statement is gone and it becomes a pathfinding toy.

---

## 0. Read this before you open Godot

Three decisions that will cost you hours if you get them wrong:

1. **Godot 4.7.2-stable, standard build (not .NET), on both machines.** `project.godot` records the version; opening with a different one rewrites import metadata and Jabin gets a broken pull.
2. **Put the project on a LOCAL path, never inside OneDrive/iCloud.** `~/dev/rover-sim`. Cloud-synced Godot projects hang on "Downloading…", fail mass imports, and open blank. This is the single most common way to lose an hour today.
3. **`.gitignore` only `.godot/`** (plus `*.translation`). **Commit every `*.import` and `*.uid` sidecar** — without them Jabin's Godot re-imports everything and asset references break.

⚠ macOS and Windows are both case-insensitive by default, so a `res://Rocks/Rock_01.glb` vs `rock_01.glb` mismatch works for both of you and breaks nothing — but keep casing consistent anyway; Git is not case-insensitive.

---

## 1. What SIM is

A Godot 4.7 project that:
- renders a Mars world with terrain, curated rocks and ArUco marker quads
- drives a rover body continuously toward a heading BRAIN sends
- renders the rover's forward camera into a 640×480 `SubViewport` and ships it as JPEG
- owns the **budget** — SIM is the single source of truth, BRAIN only reads it
- handles **reactive obstacle avoidance itself** (BRAIN does not path-plan — that is PS 03)
- shows a **god view** on the main window so a judge can see the gap between truth and what the rover sees

**Connection: Godot is the WebSocket CLIENT.** BRAIN is the server at `ws://127.0.0.1:8765`. This means `stub_brain.py` and the real BRAIN are interchangeable — you never wait on Jabin.

Use `127.0.0.1`, **not** `localhost` — Python may bind `::1` and Godot may resolve to a different family.

---

## 2. Build order

| # | Step | Exit |
|---|---|---|
| 2.1 | Project + terrain + collision | rover doesn't fall through |
| 2.2 | Rover body + controller + hazard rays | drives to a heading you type |
| 2.3 | Two-camera rig (god view + rover SubViewport) | both visible on screen |
| 2.4 | `sim_link.gd` → `stub_brain.py` | JPEG arrives at the stub, action comes back |
| 2.5 | ArUco marker quads | Jabin's detector reads the IDs |
| 2.6 | Rock scatter (4–5 common + 2–3 anomalies) | world looks curated, not random |
| 2.7 | Budget accounting | budget drains as it drives |
| 2.8 | *(Phase 3)* auto-labeller for YOLO training | 1,500 labelled frames |

**2.4 is the checkpoint that unblocks Jabin.** Get there early and push.

---

## 3. Terrain

Build it procedurally in one script — skip premade Mars terrain. Every free one found is CC-BY at planet/crater scale (5 km or CTX resolution) or a 520k-tri FBX; none is rover-scale CC0, and Terrain3D is overkill for a few-hour build.

- **Visual:** 257×257 `ArrayMesh` at **1 m spacing**, displaced by `FastNoiseLite`.
- **Collision:** `HeightMapShape3D` filled from the **same height function in the same row-major loop**.

⚠ `HeightMapShape3D`'s grid is **fixed at 1 unit spacing and centred** on the `CollisionShape3D` origin. Match the visual mesh's spacing exactly and all alignment maths disappears. **Never scale the `CollisionShape3D`** to stretch it — non-uniform scale misbehaves.

**Fallback if the height field misbehaves** (rover falls through, jitter, invisible terrain): keep the `ArrayMesh` and call `$Mesh.create_trimesh_collision()` — one line, exact match, slower but correct.

**Texture:** `StandardMaterial3D` with an AI4Mars NavCam crop as `albedo_texture`, `uv1_triplanar` on. NavCam frames are greyscale — tint via `albedo_color` to get the Mars red. This keeps the render inside the distribution Jabin's perception expects.

---

## 4. The camera rig — get this exactly right

Two cameras: a **god-view `Camera3D`** on the main window, and the **rover camera inside a `SubViewport`**.

```
Main (Node3D)
├── GodCam (Camera3D)              # what the judge sees — the truth
├── Rover (CharacterBody3D)
│   ├── CamMount (Node3D)
│   │   └── RemoteTransform3D  ->  remote_path = RoverCam
│   └── HazardRay (RayCast3D)
└── CanvasLayer
    ├── SubViewport               # 640x480
    │   └── RoverCam (Camera3D)
    └── TextureRect               # texture = SubViewport.get_texture()
```

**`SubViewport` settings — all four matter:**
| Property | Value | Why |
|---|---|---|
| `size` | `640 × 480` | matches the contract |
| `own_world_3d` | `false` | share the main scene's World3D or you render an empty world |
| `render_target_update_mode` | `UPDATE_ALWAYS` | default `UPDATE_WHEN_VISIBLE` means an off-screen SubViewport never re-renders and `get_image()` returns blank |
| `msaa_3d` | **off** | the MSAA colour attachment lacks `TEXTURE_USAGE_CAN_COPY_FROM_BIT`; readback errors |
| `use_hdr_2d` | `false` | HDR makes the target `RGBAH`, and `save_jpg_to_buffer` gets the wrong format |

### ⚠ The FOV trap — this one silently corrupts everything

**`Camera3D.fov` is the VERTICAL FOV by default** (`keep_aspect = KEEP_HEIGHT`). The contract fixes `camera.hfov_deg = 60`.

**Set `keep_aspect = Camera3D.KEEP_WIDTH` and `fov = 60`.**

Get this wrong and *every bearing BRAIN computes is off by the 4:3 aspect ratio* — the rover will consistently steer beside its targets and you will spend an hour blaming the policy. (Equivalent alternative: keep `KEEP_HEIGHT` and set `fov = 46.83` for 640×480.)

**A `Camera3D` inside a `SubViewport` is not in the rover's `Node3D` hierarchy** — it ignores the rover's transform. Drive it with the `RemoteTransform3D` above, or copy `CamMount.global_transform` to it every `_process`. Forget this and the rover view is a frozen shot of wherever the camera spawned.

---

## 5. Capture — 5 Hz, not 10

```gdscript
func _capture() -> PackedByteArray:
    await RenderingServer.frame_post_draw
    var img := sub_viewport.get_texture().get_image()
    return img.save_jpg_to_buffer(0.75)
```

Driven by a `Timer` at **5 Hz** (the contract's 10 Hz was amended — see `plan.md` §6 #17). BRAIN decides at 1 Hz, so 5 Hz loses nothing and halves the cost.

**Known cost, accept it:** `get_image()` forces a GPU sync (`godot#75877`). At 640×480 that is a 1–2 frame hitch, five times a second. Ship the synchronous version first — it is correct on every renderer and every version.

⚠ `await RenderingServer.frame_post_draw` prevents *black/stale* captures but does **not** remove the stall — the stall is inside `texture_get_data()`. Both problems are real and separate; you need the `await` regardless.

⚠ **Never call `get_image()` from a `Thread` or `WorkerThreadPool` task.** Godot 4.4+ render-thread guards return errors and the thread-safety docs forbid GPU access off the main thread. Do not enable `Multi-Threaded` thread model to dodge this — it is marked experimental with known crashes.

**If the god view visibly stutters on Jabin's laptop:** drop capture to 3 Hz first. Only if that is still unacceptable, look at the async `RenderingDevice.texture_get_data_async` path — it is a real optimisation but not worth the risk on the day.

---

## 6. The link

```gdscript
var ws := WebSocketPeer.new()
ws.outbound_buffer_size = 4 * 1024 * 1024      # BEFORE connect_to_url
ws.inbound_buffer_size  = 4 * 1024 * 1024
ws.connect_to_url("ws://127.0.0.1:8765")
```

### ⚠ The 65535-byte trap

`outbound_buffer_size` **defaults to 65535 bytes**. A 640×480 JPEG at quality 0.75 is commonly 50–120 KB. Above the limit `send()` returns `ERR_OUT_OF_MEMORY` and **the frame is silently gone**. Set the buffer before connecting, and check `send()`'s return value.

**Per observation: one text frame then one binary frame.**
```gdscript
ws.send_text(JSON.stringify(header))    # the observation JSON
ws.send(jpeg_bytes)                     # default WRITE_MODE_BINARY
```
One TCP connection guarantees order; Python receives `str` then `bytes` and pairs them.

**Poll every frame:** `ws.poll()` in `_process`, then drain with `get_available_packet_count()` / `get_packet()`, using `was_string_packet()` to tell text from binary.

**Reconnect:** on `STATE_CLOSED`, build a fresh `WebSocketPeer` after 1 s. `close()` is asynchronous — just call it in `_exit_tree()`.

⚠ **Godot's JSON parser turns every number into a float** — `JSON.parse_string("1423")` gives `1423.0`, while `JSON.stringify` writes ints without `.0`. Python gives `int`. Cast with `int()` on both sides wherever `seq` is used.

**Fallback if text+binary pairing ever desyncs:** send a single binary frame with a 4-byte length prefix + JSON + JPEG. Same `send()`, zero pairing state, Python splits with `struct.unpack`.

**Do not use `WebSocketMultiplayerPeer`** — it is for Godot's MultiplayerAPI/RPC layer, not a foreign Python peer.

---

## 7. ArUco markers — the uncompromised leg

Jabin's detector runs **real OpenCV** on these. If they render wrong, the primary mission fails.

Generate PNGs with `cv2.aruco.generateImageMarker(dict, id, 480)` using **`DICT_4X4_50`**, apply to a `QuadMesh`/`PlaneMesh`.

**Bake a white quiet zone into the PNG** — ~120 px on a 480 px marker. `generateImageMarker`'s black border runs to the image edge; against dark reddish ground, candidates get rejected without the quiet zone.

**Import settings, per file — the editor will sabotage you otherwise.** Godot's "Detect 3D" silently re-imports any texture used in a 3D material as **VRAM Compressed with mipmaps**, and block-compression artefacts plus mip blur destroy the marker cells at range:

| Setting | Value |
|---|---|
| Compress Mode | **Lossless** |
| Mipmaps | **Off** |
| Detect 3D | **Off** |
| Filter | **Nearest** |

**Material:** `StandardMaterial3D` with `shading_mode = SHADING_MODE_UNSHADED` so lighting cannot alter the black/white cells.

Agree the **physical marker width in metres** with Jabin and put it in `config.yaml` — his range estimate is `f_px · W_m / w_px`, so a mismatch scales every range wrongly.

---

## 8. Rocks — curate, do not generate

**4–5 common types repeated + 2–3 distinct anomalies.** Generating hundreds of unique rocks flattens the novelty signal, kills habituation, and leaves the policy nothing to arbitrate. **Variety is the enemy here.**

Free CC0 sources: **Poly Haven** `moon_rock_01..07` (6k–18k tris, glTF), plus Quaternius / Kenney low-poly sets. Anomalies should be visibly distinct meshes.

### ⚠ Requirement from `brain.md` §6 — this one is not cosmetic

**The 4–5 common rock types must differ in TEXTURE, not just tint.** Types that differ only by colour barely separate in the embedding space (between/within distance ratio ~1.5), which means the novelty score cannot tell them apart and habituation never demonstrates. Use different AI4Mars texture crops per type.

**Scatter from a script** at seeded positions so both demo runs are reproducible.
An anomaly around 6 m away with a marker around 30 m away is the starting geometry.
The old claimed margins were inconsistent. `brain.md` now gives a verified controlled
210/400 Wh example; calibrate the actual Godot image-based decisions before staging.

⚠ **Do not let the anomaly be visible in the first 60 sim-seconds.** BRAIN's novelty memory treats whatever it sees during warm-up as "normal". Start the rover facing common rocks.

### Auto-labelling for YOLO (Phase 3, only if time allows)

Project each rock's 3D AABB into the camera with `Camera3D.unproject_position()` to write YOLO-format labels, render ~1,500 frames, hand the folder to Jabin.

**This is legitimate:** it is offline *training-data generation*, not runtime perception. BRAIN still receives only the JPEG at runtime. Say it in those words if asked.

⚠ Label from the **640×480 SubViewport**, never the main window — `unproject_position` returns wrong coordinates when the window aspect differs (`godot#77906`). And always `await RenderingServer.frame_post_draw` after moving the camera/sun and *before* `get_image()`, or you write labels from the pre-move transform against the post-move image — the classic silent corruption in synthetic datasets.

---

## 9. Rover controller + budget

**Body:** `CharacterBody3D`. Accepts `heading_deg` and `speed` from BRAIN's `action`, drives continuously in a straight line toward the committed target.

**Hazard:** forward `RayCast3D` → report `range_m` and `bearing_deg` in the observation.

**Reactive avoidance lives here, not in BRAIN.** If `hazard.range_m` drops below the safety limit, steer around the obstacle **while keeping BRAIN's committed target**. BRAIN does not path-plan — that is PS 03, explicitly out of scope. Say this out loud if asked.

**Budget — SIM owns it.** BRAIN never decrements; it only reads `budget.remaining`. Use the same three rates Jabin's cost model predicts (`brain.md` §5.2), from `config.yaml`:
```
drive:        drive_rate_wh_per_m  x  distance_travelled
investigate:  dwell_rate_wh_per_s x dwell_time
confirm:      dwell_rate_wh_per_s x confirmation_time
idle:         idle_rate_wh_per_s x elapsed
```
Mismatch between BRAIN's *predicted* cost and SIM's *actual* charge is honest and worth showing on the panel.

**Marker confirmation** requires a BRAIN-committed marker, arrival within 3 m,
and 3 physics seconds of confirmation dwell. Stop at the marker and charge dwell
energy. Only then add the ID to `mission.confirmed_markers`.

---

## 10. Handing off to Jabin

Push early and often; he integrates on Windows. Before you say it's ready:

- ☐ Runs from a clean clone (no absolute paths, no missing `.import` files)
- ☐ `keep_aspect = KEEP_WIDTH`, `fov = 60` confirmed
- ☐ `outbound_buffer_size` raised before `connect_to_url`
- ☐ Marker textures import as Lossless / no mipmaps / nearest
- ☐ Connects to `stub_brain.py` and drives on its actions
- ☐ Budget drains visibly
- ☐ Common rock types differ in texture, not just tint

Then move to `panel.md`.
# Offline rock export handoff (2026-09-07)

Jabin's dataset preparation and training/evaluation tools are ready. Follow
[rock-training.md](rock-training.md) for the 640x480 images, single-class YOLO
labels and grouped JSONL manifest. Labels are offline training material only;
do not add them to runtime observations. Actual training and Godot integration
remain pending. Jabin will announce when Dev's GitHub update is ready to pull.
