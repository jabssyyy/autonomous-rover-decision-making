# main.gd -- SIM orchestrator. Builds the whole scene in code so there is no hand
# authored .tscn to drift, owns the sim clock and the budget, and ships one
# observation (header + JPEG) per capture tick.
#
# THE RULE (interface-contract.md S1): BRAIN receives pixels, its own pose and its
# own budget. Nothing else. Never add a key to the observation. contract.py rejects
# unknown keys at any depth, and a name like "rock" or "target" trips a tripwire
# that prints THE RULE VIOLATED -- that check is the project, not a nuisance.
extends Node3D

enum CamMode { CHASE, ORBIT, TOP }

var cfg: Dictionary
var args := {}

var terrain: Terrain
var world: World
var rover: Rover
var rig: CameraRig
var link: SimLink
var hud: Hud
var debug_view: DebugView
var recorder: RunRecorder
var labeller: Labeller

var god_cam: Camera3D
var cam_mode: int = CamMode.CHASE
var _orbit_yaw := 35.0
var _orbit_pitch := 22.0
var _orbit_dist := 14.0
var _dragging := false

var seq := 0
var sim_time := 0.0
var time_compression := 60.0
var budget := 1000.0
var capacity := 1000.0
var assigned: Array[String] = ["M01", "M02", "M03"]
var confirmed: Array[String] = []
var state := "AUTONOMOUS"
var decision := "hold"
var target_label := ""
var audit_text := "waiting for BRAIN..."
var dwell_sim_s := 0.0
var manual := false
var hud_visible := true

var _capturing := false
var _last_distance := 0.0
var _dump_requested := false
var _wall_s := 0.0
var _frames_counted := 0

func _ready() -> void:
	_parse_args()
	cfg = SimConfig.load_shared(args.get("config", ""))
	time_compression = SimConfig.f(cfg, "time_compression")
	capacity = SimConfig.f(cfg, "budget_capacity_wh")
	budget = minf(SimConfig.f(cfg, "budget_start_wh"), capacity)

	_build_environment()

	terrain = Terrain.new()
	terrain.name = "Terrain"
	add_child(terrain)
	terrain.build(SimConfig.i(cfg, "world_seed"))

	world = World.new()
	world.name = "World"
	add_child(world)
	world.build(terrain, cfg, args.has("lowfx"))

	rover = Rover.new()
	rover.name = "Rover"
	add_child(rover)
	rover.build(cfg, terrain)
	rover.attach_model()
	rover.global_position = Vector3(0.0, terrain.ground_y(0.0, 0.0) + 0.3, 0.0)
	rover.heading_deg = 0.0
	rover.command(0.0, 0.0)

	god_cam = Camera3D.new()
	god_cam.name = "GodCam"
	god_cam.fov = 62.0
	god_cam.far = 900.0
	god_cam.current = true
	add_child(god_cam)

	var canvas := CanvasLayer.new()
	canvas.name = "CanvasLayer"
	add_child(canvas)

	rig = CameraRig.new()
	rig.name = "CameraRig"
	add_child(rig)
	rig.build(canvas, rover.cam_mount, cfg)

	debug_view = DebugView.new()
	debug_view.name = "DebugView"
	add_child(debug_view)
	debug_view.build(rover, rig.cam, terrain)

	hud = Hud.new()
	hud.name = "HUD"
	canvas.add_child(hud)
	hud.build(rig.sub_viewport.get_texture(), world, rover)

	link = SimLink.new()
	link.name = "SimLink"
	if args.has("brain"):
		link.url = args["brain"]
	add_child(link)
	link.action_received.connect(_on_action)

	if args.has("record"):
		recorder = RunRecorder.new()
		recorder.start(args["record"], cfg, {
			"assigned_markers": assigned,
			"start_budget_wh": budget,
			"brain_url": link.url,
		})

	var t := Timer.new()
	t.name = "CaptureTimer"
	t.wait_time = 1.0 / maxf(1.0, SimConfig.f(cfg, "capture_rate_hz"))
	t.autostart = true
	t.timeout.connect(_on_capture_tick)
	add_child(t)

	if args.has("dumpat"):
		get_tree().create_timer(float(args["dumpat"])).timeout.connect(
			func() -> void: _dump_requested = true)

	if args.has("label"):
		# offline training-data generation, NOT runtime perception -- BRAIN still only
		# ever receives the JPEG at run time. Say it in exactly those words if asked.
		labeller = Labeller.new()
		add_child(labeller)
		labeller.run(self, int(args["label"]))

	print("SIM ready | camera %dx%d hfov %.0f KEEP_WIDTH | %.0f Hz capture | budget %.0f/%.0f Wh | seed %d"
		% [SimConfig.i(cfg, "camera_w"), SimConfig.i(cfg, "camera_h"),
		SimConfig.f(cfg, "camera_hfov_deg"), SimConfig.f(cfg, "capture_rate_hz"),
		budget, capacity, SimConfig.i(cfg, "world_seed")])

func _parse_args() -> void:
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--") and a.contains("="):
			args[a.substr(2, a.find("=") - 2)] = a.substr(a.find("=") + 1)
		elif a.begins_with("--"):
			args[a.substr(2)] = true
	if args.has("top"):
		cam_mode = CamMode.TOP

# ---------------------------------------------------------------- environment
func _build_environment() -> void:
	var sun := DirectionalLight3D.new()
	sun.name = "Sun"
	sun.rotation_degrees = Vector3(-38.0, 128.0, 0.0)
	sun.light_color = Color(1.0, 0.91, 0.79)
	sun.light_energy = 1.35
	sun.shadow_enabled = true
	sun.directional_shadow_max_distance = 60.0 if args.has("lowfx") else 95.0
	sun.directional_shadow_blend_splits = true
	add_child(sun)

	var sky_mat := ProceduralSkyMaterial.new()
	# Mars: dusty butterscotch overhead, brighter and paler toward the horizon, with a
	# small bright sun disc. The colour of the sky is the first thing anyone judges.
	sky_mat.sky_top_color = Color(0.42, 0.31, 0.25)
	sky_mat.sky_horizon_color = Color(0.80, 0.63, 0.46)
	sky_mat.sky_curve = 0.12
	sky_mat.ground_bottom_color = Color(0.33, 0.21, 0.15)
	sky_mat.ground_horizon_color = Color(0.74, 0.57, 0.42)
	sky_mat.sun_angle_max = 5.0
	sky_mat.sun_curve = 0.08
	var sky := Sky.new()
	sky.sky_material = sky_mat

	var env := Environment.new()
	env.background_mode = Environment.BG_SKY
	env.sky = sky
	env.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	env.ambient_light_energy = 0.6
	env.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	env.tonemap_white = 1.6
	# SSAO looks lovely and costs ~25 fps on a laptop with 2600 gravel instances in
	# frame. The demo needs headroom on Jabin's machine more than it needs contact
	# shadows -- turn it back on with --ssao if the machine can afford it.
	env.ssao_enabled = args.has("ssao")
	env.ssao_intensity = 1.3
	env.ssao_radius = 1.1
	env.fog_enabled = true
	env.fog_mode = Environment.FOG_MODE_DEPTH
	env.fog_light_color = Color(0.80, 0.61, 0.46)
	env.fog_density = 0.0022          # depth cue only -- heavier fog eats ArUco at range
	# --lowfx is the escape hatch for a weak laptop on the day: fewer pebbles, a
	# shorter shadow cascade, no fog. The world and the contract are unchanged.
	if args.has("lowfx"):
		env.fog_enabled = false
	env.fog_sky_affect = 0.35
	var we := WorldEnvironment.new()
	we.name = "WorldEnvironment"
	we.environment = env
	add_child(we)

# ----------------------------------------------------------------- main loop
func _process(delta: float) -> void:
	_wall_s += delta
	_frames_counted += 1
	var d_sim := delta * time_compression
	sim_time += d_sim
	if decision == "investigate":
		dwell_sim_s += d_sim
	if labeller == null:          # labelling teleports the rover; mission logic must not react
		_charge_budget(d_sim)
		_confirm_markers()
	_drive_god_cam(delta)
	_manual_drive(delta)
	debug_view.investigating = decision == "investigate"
	if hud_visible:
		hud.update(_hud_state())

func _charge_budget(d_sim: float) -> void:
	# SIM owns the budget and is the single source of truth. BRAIN never decrements
	# it, it only reads budget.remaining -- that is what keeps the two from drifting.
	var moved := rover.distance_travelled - _last_distance
	_last_distance = rover.distance_travelled
	budget -= SimConfig.f(cfg, "drive_rate_wh_per_m") * moved
	budget -= SimConfig.f(cfg, "idle_rate_wh_per_s") * d_sim
	if decision == "investigate":
		budget -= SimConfig.f(cfg, "dwell_wh_investigate") * d_sim
	budget = clampf(budget, 0.0, capacity)

func _confirm_markers() -> void:
	# Ground truth, and legitimately SIM's call: a real rover knows it reached a
	# waypoint from its own mission state, not by being told what is in the frame.
	var hit := world.marker_within(rover.global_position, SimConfig.f(cfg, "arrive_range_m"))
	if hit != "" and hit in assigned and not (hit in confirmed):
		confirmed.append(hit)
		print("SIM: confirmed %s at sim_time %.1f (%d/%d)" % [hit, sim_time, confirmed.size(), assigned.size()])

func _on_capture_tick() -> void:
	if _capturing or labeller != null:
		return
	_capturing = true
	var jpeg: PackedByteArray = await rig.capture_jpeg()
	if _dump_requested:
		_dump_requested = false
		await rig.dump_png("user://capture_check.png")
		await RenderingServer.frame_post_draw
		var gv := get_viewport().get_texture().get_image()
		if gv and not gv.is_empty():
			gv.save_png("user://godview_check.png")
			print("Main: wrote godview_check.png")
	if not jpeg.is_empty():
		seq += 1
		var header := _observation()
		if link.connected:
			link.send_observation(header, jpeg)
		if recorder:
			recorder.observation(header, jpeg)
	_capturing = false

func _observation() -> Dictionary:
	var h: Dictionary = rover.hazard()
	# pose.y is the world's SECOND HORIZONTAL axis (Godot z), not altitude.
	return {
		"type": "observation",
		"seq": seq,
		"sim_time": snappedf(sim_time, 0.01),
		"pose": {
			"x": snappedf(rover.global_position.x, 0.01),
			"y": snappedf(rover.global_position.z, 0.01),
			"heading_deg": snappedf(rover.heading_deg, 0.01),
		},
		"budget": {
			"remaining": snappedf(budget, 0.01),
			"capacity": snappedf(capacity, 0.01),
			"unit": "Wh",
			"simulated": true,
		},
		"hazard": {
			"range_m": snappedf(h.range_m, 0.01),
			"bearing_deg": snappedf(h.bearing_deg, 0.01),
		},
		"mission": {
			"assigned_markers": assigned,
			"confirmed_markers": confirmed,
		},
		"state": state,
		"camera": {
			"w": SimConfig.i(cfg, "camera_w"),
			"h": SimConfig.i(cfg, "camera_h"),
			"hfov_deg": snappedf(SimConfig.f(cfg, "camera_hfov_deg"), 0.01),
			"encoding": "jpeg",
		},
	}

func _on_action(action: Dictionary) -> void:
	if recorder:
		recorder.action(action)
	if manual:
		return
	var prev := decision
	decision = str(action.get("decision", "hold"))
	if decision != "investigate" or prev != "investigate":
		dwell_sim_s = 0.0
	var drive: Dictionary = action.get("drive", {})
	var heading := float(drive.get("heading_deg", rover.heading_deg))
	# contract.py enforces drive.speed in [0, 1]: it is a FRACTION of the rover's top
	# speed, not m/s. Dividing it by max_speed again pins every drive at full throttle.
	var frac := clampf(float(drive.get("speed", 0.0)), 0.0, 1.0)
	var tgt = action.get("target", null)
	target_label = str(tgt.get("label", "")) if typeof(tgt) == TYPE_DICTIONARY else ""
	var audit: Dictionary = action.get("audit", {})
	audit_text = str(audit.get("text", audit_text))

	match decision:
		"drive_to_target", "continue":
			state = "AUTONOMOUS"
			rover.command(heading, frac)
		"investigate":
			state = "AUTONOMOUS"
			rover.command(heading, 0.0)
		"survey":
			state = "AUTONOMOUS"
			rover.command(rover.heading_deg + 90.0, 0.0)   # rotate in place to widen the view
		"report":
			state = "REPORTING"
			rover.command(rover.heading_deg, 0.0)
		"hold":
			state = "AWAITING_UPLINK"
			rover.command(rover.heading_deg, 0.0)

# --------------------------------------------------------------- god view/HUD
func _drive_god_cam(delta: float) -> void:
	var focus := rover.global_position + Vector3.UP * 1.0
	match cam_mode:
		CamMode.CHASE:
			var back := -Rover.forward_from_heading(rover.heading_deg)
			var want := focus + back * 9.0 + Vector3.UP * 4.2
			god_cam.global_position = god_cam.global_position.lerp(want, clampf(delta * 4.0, 0.0, 1.0))
			god_cam.look_at(focus, Vector3.UP)
		CamMode.ORBIT:
			var yaw := deg_to_rad(_orbit_yaw)
			var pitch := deg_to_rad(clampf(_orbit_pitch, 4.0, 84.0))
			var off := Vector3(sin(yaw) * cos(pitch), sin(pitch), cos(yaw) * cos(pitch)) * _orbit_dist
			god_cam.global_position = focus + off
			god_cam.look_at(focus, Vector3.UP)
		CamMode.TOP:
			var want_t := rover.global_position + Vector3.UP * 55.0 + Vector3(0.01, 0, 0.01)
			god_cam.global_position = god_cam.global_position.lerp(want_t, clampf(delta * 4.0, 0.0, 1.0))
			god_cam.look_at(rover.global_position, -Rover.forward_from_heading(rover.heading_deg))

func _hud_state() -> Dictionary:
	var h: Dictionary = rover.hazard()
	return {
		"linked": link.connected, "url": link.url,
		"sim_time": sim_time, "compression": time_compression,
		"frames": link.frames_sent, "drops": link.frames_dropped,
		"kb": rig.last_bytes / 1024, "actions": link.actions_received,
		"fps": Engine.get_frames_per_second(), "seq": seq,
		"state": state, "decision": decision, "target": target_label,
		"x": rover.global_position.x, "y": rover.global_position.z,
		"heading": rover.heading_deg, "slope": rover.slope_deg,
		"speed": rover.speed_mps, "driven": rover.distance_travelled,
		"avoiding": rover.avoiding, "manual": manual,
		"hazard_range": float(h.range_m), "hazard_bearing": float(h.bearing_deg),
		"hazard_max": rover.ray_len,
		"budget": budget, "capacity": capacity,
		"assigned": assigned, "confirmed": confirmed,
		"audit": audit_text, "dwell": dwell_sim_s,
	}

func _manual_drive(delta: float) -> void:
	if not manual:
		return
	var turn := 0.0
	if Input.is_key_pressed(KEY_LEFT):
		turn -= 60.0 * delta
	if Input.is_key_pressed(KEY_RIGHT):
		turn += 60.0 * delta
	var spd := rover.commanded_speed
	if Input.is_key_pressed(KEY_UP):
		spd = 1.0
	if Input.is_key_pressed(KEY_DOWN):
		spd = 0.0
	rover.command(rover.commanded_heading_deg + turn, spd)

func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton:
		var mb := event as InputEventMouseButton
		if mb.button_index == MOUSE_BUTTON_LEFT:
			_dragging = mb.pressed
			if mb.pressed:
				cam_mode = CamMode.ORBIT
		elif mb.pressed and mb.button_index == MOUSE_BUTTON_WHEEL_UP:
			_orbit_dist = clampf(_orbit_dist * 0.88, 3.0, 160.0)
		elif mb.pressed and mb.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			_orbit_dist = clampf(_orbit_dist * 1.14, 3.0, 160.0)
	elif event is InputEventMouseMotion and _dragging:
		var mm := event as InputEventMouseMotion
		_orbit_yaw -= mm.relative.x * 0.4
		_orbit_pitch = clampf(_orbit_pitch + mm.relative.y * 0.3, 4.0, 84.0)
	elif event is InputEventKey and event.pressed and not (event as InputEventKey).echo:
		match (event as InputEventKey).keycode:
			KEY_M:
				manual = not manual
				decision = "manual" if manual else "hold"
			KEY_C:
				cam_mode = (cam_mode + 1) % 3
			KEY_F:
				debug_view.show_frustum = not debug_view.show_frustum
			KEY_R:
				debug_view.show_rays = not debug_view.show_rays
			KEY_H:
				hud_visible = not hud_visible
				hud.visible = hud_visible
			KEY_P:
				_dump_requested = true
			KEY_ESCAPE:
				# Shift-Escape, not bare Escape: a stray keypress during a live demo
				# must not be able to kill the sim.
				if (event as InputEventKey).shift_pressed:
					get_tree().quit()

func _exit_tree() -> void:
	if _frames_counted > 0:
		print("SIM perf: %.0f fps average over %.0f s (%d frames)"
			% [_frames_counted / maxf(_wall_s, 0.001), _wall_s, _frames_counted])
	if recorder:
		recorder.finish({
			"sim_time_end": sim_time, "budget_end_wh": budget,
			"distance_m": rover.distance_travelled, "confirmed_markers": confirmed,
		})
