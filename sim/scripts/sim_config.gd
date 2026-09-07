# sim_config.gd -- reads the ONE shared config.yaml (interface-contract.md S9).
# SIM lives in sim/, the file lives in brain/, so we go out through the OS path.
# Godot has no YAML parser; the file is deliberately flat scalars only.
class_name SimConfig
extends RefCounted

const DEFAULTS := {
	"time_compression": 1.0,
	"comms_delay_real_s": 60.0,
	"decision_interval_sim_s": 1.0,
	"observation_rate_hz": 5.0,
	"report_interval_sim_s": 7200.0,
	"gamma": 2.0,
	"alpha_distance": 1.0,
	"beta_time": 1.0,
	"mission_margin": 1.15,
	"confirm_dwell_sim_s": 3.0,
	"investigate_dwell_sim_s": 5.0,
	"camera_hfov_deg": 60.0,
	"camera_w": 640.0,
	"camera_h": 480.0,
	"jpeg_quality": 0.75,
	"budget_capacity_wh": 1000.0,
	"budget_start_wh": 1000.0,
	"drive_rate_wh_per_m": 1.0,
	"dwell_rate_wh_per_s": 1.0,
	"idle_rate_wh_per_s": 0.01,
	"max_speed_m_per_s": 1.0,
	"rover_yaw_rate_dps": 25.0,
	"hazard_ray_len_m": 12.0,
	"hazard_stop_m": 2.0,
	"arrive_range_m": 2.5,
	"marker_side_m": 0.8,
	"world_seed": 20260907.0,
}

## Search order: an explicit --config=<path>, then the sibling brain/ dir. Relative
## paths are resolved against the project folder so both machines behave the same.
static func shared_path(override_path := "") -> String:
	if override_path != "":
		if override_path.is_absolute_path():
			return override_path
		return ProjectSettings.globalize_path("res://").path_join(override_path).simplify_path()
	return ProjectSettings.globalize_path("res://").path_join("../brain/config.yaml").simplify_path()

static func load_shared(override_path := "") -> Dictionary:
	var cfg: Dictionary = DEFAULTS.duplicate()
	var path := shared_path(override_path)
	var f := FileAccess.open(path, FileAccess.READ)
	if f == null:
		push_warning("SimConfig: no config.yaml at %s -- using defaults" % path)
		return cfg
	var found := 0
	while not f.eof_reached():
		var line := f.get_line().strip_edges()
		if line.is_empty() or line.begins_with("#") or not line.contains(":"):
			continue
		var key := line.get_slice(":", 0).strip_edges()
		var raw := line.substr(line.find(":") + 1)
		var hash_at := raw.find("#")
		if hash_at >= 0:
			raw = raw.substr(0, hash_at)
		raw = raw.strip_edges().trim_prefix("\"").trim_suffix("\"").trim_prefix("'").trim_suffix("'")
		if raw.is_empty():
			continue
		if raw.is_valid_float():
			cfg[key] = raw.to_float()
		elif raw == "true" or raw == "false":
			cfg[key] = raw == "true"
		else:
			cfg[key] = raw
		found += 1
	f.close()
	print("SimConfig: %d keys from %s" % [found, path])
	return cfg

static func f(cfg: Dictionary, key: String) -> float:
	return float(cfg.get(key, DEFAULTS.get(key, 0.0)))

static func i(cfg: Dictionary, key: String) -> int:
	return int(f(cfg, key))
