# recorder.gd -- writes a demo run to disk exactly as it went over the wire.
#
# Three things need this and none of them are optional on the day:
#   1. integration checkpoint 5, "both demo runs recorded end-to-end"
#   2. brain/stub_sim.py replays a folder of frames, so BRAIN can be developed and
#      re-tuned against a REAL run with no Godot running at all
#   3. the frames are the raw material for the YOLO set (see labeller.gd)
class_name RunRecorder
extends RefCounted

var dir := ""
var frames := 0
var actions := 0
var active := false

var _obs: FileAccess
var _act: FileAccess

func start(run_name: String, cfg: Dictionary, extra: Dictionary) -> bool:
	var root := ProjectSettings.globalize_path("res://").path_join("../runs").simplify_path()
	dir = root.path_join(run_name)
	var err := DirAccess.make_dir_recursive_absolute(dir.path_join("frames"))
	if err != OK:
		push_error("RunRecorder: cannot create %s (%s)" % [dir, error_string(err)])
		return false
	_obs = FileAccess.open(dir.path_join("observations.jsonl"), FileAccess.WRITE)
	_act = FileAccess.open(dir.path_join("actions.jsonl"), FileAccess.WRITE)
	if _obs == null or _act == null:
		push_error("RunRecorder: cannot open jsonl files in %s" % dir)
		return false
	var manifest := {
		"run": run_name,
		"started_unix": int(Time.get_unix_time_from_system()),
		"started_iso": Time.get_datetime_string_from_system(true),
		"godot": Engine.get_version_info()["string"],
		"config": cfg,
	}
	manifest.merge(extra, true)
	var mf := FileAccess.open(dir.path_join("manifest.json"), FileAccess.WRITE)
	if mf:
		mf.store_string(JSON.stringify(manifest, "  "))
		mf.close()
	active = true
	print("RunRecorder: writing to %s" % dir)
	return true

## The header and the JPEG are stored as they were sent, so a replay is byte-identical
## to what BRAIN saw. `_frame_ref` is the only added key and it never goes on the wire.
func observation(header: Dictionary, jpeg: PackedByteArray) -> void:
	if not active:
		return
	var ref := "f_%06d" % int(header.get("seq", frames))
	var f := FileAccess.open(dir.path_join("frames").path_join(ref + ".jpg"), FileAccess.WRITE)
	if f:
		f.store_buffer(jpeg)
		f.close()
	var row := header.duplicate(true)
	row["_frame_ref"] = ref
	row["_bytes"] = jpeg.size()
	_obs.store_line(JSON.stringify(row))
	_obs.flush()
	frames += 1

func action(a: Dictionary) -> void:
	if not active:
		return
	_act.store_line(JSON.stringify(a))
	_act.flush()
	actions += 1

func finish(summary: Dictionary) -> void:
	if not active:
		return
	active = false
	if _obs:
		_obs.close()
	if _act:
		_act.close()
	var f := FileAccess.open(dir.path_join("summary.json"), FileAccess.WRITE)
	if f:
		summary["frames"] = frames
		summary["actions"] = actions
		f.store_string(JSON.stringify(summary, "  "))
		f.close()
	print("RunRecorder: %d frames, %d actions -> %s" % [frames, actions, dir])
