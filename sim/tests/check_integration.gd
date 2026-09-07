extends SceneTree

var failures := 0

func check(condition: bool, message: String) -> void:
	if not condition:
		failures += 1
		push_error(message)

func _initialize() -> void:
	call_deferred("run")

func run() -> void:
	var main = load("res://scripts/main.gd").new()
	main.cfg = SimConfig.DEFAULTS.duplicate()
	main.rover = Rover.new()
	# Keep nodes outside the live scene so no rendering or physics loop is needed.
	main.world = World.new()
	main.seq = 10
	main.sim_time = 2.0
	main.budget = 1000.0
	main.capacity = 1000.0
	var action := {"in_reply_to_seq": 10, "sim_time": 2.0, "decision": "drive_to_target",
		"drive": {"heading_deg": 270.0, "speed": 0.6},
		"target": {"label": "M02"}, "audit": {"text": "fixture"}}
	main._on_action(action)
	check(is_equal_approx(main.rover.commanded_heading_deg, 0.0), "wire heading must map to internal compass")
	check(is_equal_approx(main.rover.commanded_speed, 0.6), "drive fraction changed")
	main._safe_stop("fixture disconnect")
	check(main.rover.commanded_speed == 0.0 and main.decision == "hold", "disconnect must stop")
	main._on_action(action)
	check(main.rover.commanded_speed == 0.0, "replayed command restarted rover")
	main.seq = 11
	action.in_reply_to_seq = 11
	main.sim_time = 10.0
	main._on_action(action)
	check(main.rover.commanded_speed == 0.0, "stale command restarted rover")
	action.sim_time = 10.0
	main._on_action(action)
	main.rover.position = Vector3(1.5, 0, -32.0)
	# marker_within uses global_position; enter only rover, with physics disabled.
	main.rover.set_physics_process(false)
	root.add_child(main.rover)
	main._confirm_markers(0.1)
	check(main.confirmed.is_empty() and main.rover.commanded_speed == 0.0, "arrival must begin stopped dwell")
	main._charge_budget(1.0)
	check(is_equal_approx(main.budget, 998.99), "dwell must charge shared Wh/s plus idle")
	main._confirm_markers(2.9)
	check(main.confirmed.is_empty(), "marker confirmed too early")
	main._confirm_markers(0.11)
	check("M02" in main.confirmed, "marker did not confirm after 3 seconds")
	main.confirmed.clear()
	main._confirm_markers(0.1)
	main._safe_stop("cancel")
	main._confirm_markers(4.0)
	check(main.confirmed.is_empty() and main._confirm_label == "", "hold must cancel marker dwell")
	main.rover.free()
	main.world.free()
	main.free()
	print("SIM integration checks: %d failure(s)" % failures)
	quit(1 if failures else 0)
