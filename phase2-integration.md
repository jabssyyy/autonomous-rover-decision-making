# Phase 2 integration checklist

2026-09-07. **Started, awaiting Dev's Godot project. Not complete.**

## Prerequisite search

- No `project.godot` exists in this checkout.
- `git fetch origin` succeeded. All remote branch heads are fetched; only `origin/main`
  exists, at initial commit `fd821f0`, with no simulator project.
- No running Godot process or Godot executable on PATH was found. This does not prove
  Godot is absent from the machine; a portable installation may live elsewhere.
- Checked the expected `C:/dev` and user `dev` locations and likely project/download
  locations without finding a matching project. Jabin was asked for its path or repo.

Existing BRAIN changes remain local and preserved. No pull/merge, push, message to Dev,
or replacement simulator build was performed.

## First integration sequence (not yet executed)

1. Inspect Dev's project and its Godot version; run an isolated local copy outside
   OneDrive. Keep Dev's original files and the current BRAIN work intact.
2. Align its shared settings with `brain/config.yaml` and current audit v2 contract.
3. Capture the actual rover SubViewport JPEG. Verify marker ID, direction, apparent
   width, and rough range before enabling driving.
4. Reach one assigned marker in a simple obstacle-free scene, dwell for 3 s, and confirm.
5. Compare actual distance/dwell energy charges with the shared rates. Then add obstacles.
6. Stop BRAIN while driving: SIM must stop within 2.5 s. Restart BRAIN, reconnect, and
   verify a continuing stream. A fresh SIM mission requires a fresh BRAIN process.
7. Save observation/action logs and visual evidence. Record pass/fail for every check
   before calling Phase 2 complete.

## Camera and coordinate checks

The viewport must be 640x480 with an actual 60-degree horizontal field of view.
Godot exposes camera projection and screen-ray methods, so verify the angle between
left and right edge rays rather than trusting an inspector setting alone.
See [Camera3D documentation](https://docs.godotengine.org/en/stable/classes/class_camera3d.html).

Suggested diagnostic, to execute inside the actual scene once available:

```gdscript
var left_ray = rover_camera.project_local_ray_normal(Vector2(0, 240))
var right_ray = rover_camera.project_local_ray_normal(Vector2(640, 240))
print("Measured horizontal FOV: ", rad_to_deg(left_ray.angle_to(right_ray)))
```

The following mapping is a proposed adapter to BRAIN's existing 2D convention, not
an assumption about how Dev has implemented his project:

```
wire pose.x = Godot global_position.x
wire pose.y = Godot global_position.z
forward = -rover.global_basis.z
wire heading = degrees(atan2(forward.z, forward.x)) modulo 360
command direction = Vector3(cos(heading), 0, sin(heading))
```

Godot's Y-up / negative-Z-forward convention is documented in its
[3D introduction](https://docs.godotengine.org/en/stable/tutorials/3d/introduction_to_3d.html).
The mapping above is derived to match `brain/policy.py` and must be checked against
the rover's actual forward axis. A target to the image's right must have positive
relative bearing and cause a right turn. Check center, left, and right targets.

At 640 pixels and horizontal FOV 60 degrees, BRAIN's focal length is about 554.26 px.
A frontal 0.8 m black marker square at 10 m should span roughly 44.34 px. The white
quiet zone must not be counted in the 0.8 m width. Keep camera offsets and tilted
terrain out of this first calibration; test them after the basic alignment works.

Transport remains one JSON header followed immediately by one binary JPEG at 5 Hz.
Confirm the WebSocket buffer configuration and check send errors; the API is described
in [WebSocketPeer documentation](https://docs.godotengine.org/en/stable/classes/class_websocketpeer.html).

## Result

All Godot runtime checks above are pending. No new integration success is claimed.
# Waiting agreement (2026-09-07)

Jabin will ask Dev to update GitHub and notify us when ready. Do not fetch/pull
until that notification. Independent rock-training preparation was authorized
and implemented while waiting; see [rock-training.md](rock-training.md).
No Godot integration check has run, and Phase 2 remains incomplete.
