# hud.gd -- the god-view instrument panel. Everything here is for the human in the
# room; none of it reaches BRAIN. The layout is built around one idea: put the truth
# and the rover's view side by side so the gap between them is the visible subject.
class_name Hud
extends Control

const BG := Color(0.07, 0.055, 0.05, 0.78)
const EDGE := Color(1.0, 0.62, 0.35, 0.35)
const TEXT := Color(0.93, 0.90, 0.86)
const DIM := Color(0.63, 0.60, 0.57)
const GOOD := Color(0.45, 0.86, 0.52)
const WARN := Color(1.0, 0.75, 0.32)
const BAD := Color(0.96, 0.42, 0.36)
const ACCENT := Color(1.0, 0.74, 0.45)

var status: RichTextLabel
var telemetry: RichTextLabel
var audit: RichTextLabel
var view_rect: TextureRect
var minimap: MiniMap
var _bar_fill: ColorRect
var _bar_label: Label
var _chips: HBoxContainer

func build(view_texture: Texture2D, world: World, rover: Rover) -> void:
	# set_anchors_preset alone leaves this Control at zero size under a CanvasLayer, and
	# every panel anchored to the right or bottom edge then resolves to an empty rect
	# and simply never appears. The offsets variant is the one that fills the viewport.
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_IGNORE

	var left := _panel(Vector2(14, 12), Vector2(430, 114))
	status = _label(left, 13)
	status.offset_left = 12; status.offset_top = 9
	status.offset_right = -12; status.offset_bottom = -9

	var mid := _panel(Vector2(14, 136), Vector2(430, 112))
	telemetry = _label(mid, 13)
	telemetry.offset_left = 12; telemetry.offset_top = 9
	telemetry.offset_right = -12; telemetry.offset_bottom = -9

	# budget: a real bar, because "how much is left" is the whole policy question
	var budget_panel := _panel(Vector2(14, 258), Vector2(430, 74))
	var cap := Label.new()
	cap.text = "BUDGET"
	cap.position = Vector2(12, 6)
	cap.add_theme_font_size_override("font_size", 11)
	cap.add_theme_color_override("font_color", DIM)
	budget_panel.add_child(cap)
	var track := ColorRect.new()
	track.color = Color(0.16, 0.13, 0.12, 1.0)
	track.position = Vector2(12, 28)
	track.size = Vector2(406, 18)
	budget_panel.add_child(track)
	_bar_fill = ColorRect.new()
	_bar_fill.color = GOOD
	_bar_fill.position = Vector2(0, 0)
	_bar_fill.size = Vector2(406, 18)
	track.add_child(_bar_fill)
	_bar_label = Label.new()
	_bar_label.position = Vector2(12, 48)
	_bar_label.add_theme_font_size_override("font_size", 12)
	_bar_label.add_theme_color_override("font_color", TEXT)
	budget_panel.add_child(_bar_label)

	# mission chips: one per assigned marker, filled in as SIM confirms arrival
	var mission_panel := _panel(Vector2(14, 340), Vector2(430, 58))
	var mcap := Label.new()
	mcap.text = "ASSIGNED MARKERS"
	mcap.position = Vector2(12, 6)
	mcap.add_theme_font_size_override("font_size", 11)
	mcap.add_theme_color_override("font_color", DIM)
	mission_panel.add_child(mcap)
	_chips = HBoxContainer.new()
	_chips.position = Vector2(12, 26)
	_chips.add_theme_constant_override("separation", 8)
	mission_panel.add_child(_chips)

	# rover camera: the only thing BRAIN ever receives
	var cam_panel := _panel(Vector2.ZERO, Vector2(336, 288))
	cam_panel.set_anchors_preset(Control.PRESET_TOP_RIGHT)
	cam_panel.offset_left = -350; cam_panel.offset_top = 12
	cam_panel.offset_right = -14; cam_panel.offset_bottom = 300
	view_rect = TextureRect.new()
	# expand_mode BEFORE size: while it is still EXPAND_KEEP_SIZE the minimum size is
	# the texture's 640x480 and any smaller size you set is clamped straight back up.
	view_rect.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	view_rect.stretch_mode = TextureRect.STRETCH_SCALE
	view_rect.texture = view_texture
	view_rect.position = Vector2(8, 8)
	view_rect.size = Vector2(320, 240)
	view_rect.mouse_filter = Control.MOUSE_FILTER_IGNORE
	cam_panel.add_child(view_rect)
	var vcap := RichTextLabel.new()
	vcap.bbcode_enabled = true
	vcap.scroll_active = false
	vcap.position = Vector2(8, 250)
	vcap.size = Vector2(320, 34)
	vcap.add_theme_font_size_override("normal_font_size", 11)
	vcap.text = "[color=#ffbc72]ROVER CAM[/color] [color=#a09a95]640x480 - 60 deg HFOV - 5 Hz JPEG[/color]\n[color=#a09a95]this frame, its pose and its budget are ALL BRAIN receives[/color]"
	cam_panel.add_child(vcap)

	minimap = MiniMap.new()
	minimap.world = world
	minimap.rover = rover
	minimap.set_anchors_preset(Control.PRESET_BOTTOM_RIGHT)
	minimap.offset_left = -286; minimap.offset_top = -286
	minimap.offset_right = -14; minimap.offset_bottom = -14
	add_child(minimap)

	var audit_panel := _panel(Vector2.ZERO, Vector2.ZERO)
	audit_panel.set_anchors_preset(Control.PRESET_BOTTOM_WIDE)
	audit_panel.offset_left = 14; audit_panel.offset_right = -300
	audit_panel.offset_top = -104; audit_panel.offset_bottom = -14
	audit = _label(audit_panel, 14)
	audit.offset_left = 12; audit.offset_top = 8
	audit.offset_right = -12; audit.offset_bottom = -8

func _panel(pos: Vector2, sz: Vector2) -> Panel:
	var p := Panel.new()
	var sb := StyleBoxFlat.new()
	sb.bg_color = BG
	sb.border_color = EDGE
	sb.set_border_width_all(1)
	sb.set_corner_radius_all(6)
	sb.content_margin_left = 0
	p.add_theme_stylebox_override("panel", sb)
	p.position = pos
	p.size = sz
	p.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(p)
	return p

func _label(parent: Control, font_size: int) -> RichTextLabel:
	var r := RichTextLabel.new()
	r.bbcode_enabled = true
	r.scroll_active = false
	r.fit_content = false
	r.set_anchors_preset(Control.PRESET_FULL_RECT)
	r.add_theme_font_size_override("normal_font_size", font_size)
	r.add_theme_font_size_override("bold_font_size", font_size)
	r.add_theme_color_override("default_color", TEXT)
	r.mouse_filter = Control.MOUSE_FILTER_IGNORE
	parent.add_child(r)
	return r

func update(s: Dictionary) -> void:
	var link_txt: String = ("[color=#73dc84]BRAIN LINKED[/color]" if s["linked"]
		else "[color=#f56b5c]NO BRAIN[/color] [color=#a09a95]%s[/color]" % s["url"])
	status.text = "\n".join([
		"[b]MARS ROVER SIM[/b]   %s" % link_txt,
		"[color=#a09a95]sim clock[/color]  %s   [color=#a09a95]x%d real time[/color]" % [_clock(s["sim_time"]), int(s["compression"])],
		"[color=#a09a95]frames[/color] %d sent, %d dropped, %d KB   [color=#a09a95]actions[/color] %d" % [s["frames"], s["drops"], s["kb"], s["actions"]],
		"[color=#a09a95]render[/color] %d fps   [color=#a09a95]seq[/color] %d" % [s["fps"], s["seq"]],
		"[color=#6f6a66]drag/wheel orbit  C camera  F frustum  R rays  H hud  M manual  P dump  Esc quit[/color]",
	])
	var avoid: String = "   [color=#ffbf52]AVOIDING[/color]" if s["avoiding"] else ""
	var manual: String = "   [color=#ffbf52]MANUAL OVERRIDE[/color]" if s["manual"] else ""
	telemetry.text = "\n".join([
		"[color=#a09a95]state[/color]  [b]%s[/b]%s" % [s["state"], manual],
		"[color=#a09a95]decision[/color]  [b]%s[/b]  [color=#ffbc72]%s[/color]" % [s["decision"], s["target"]],
		"[color=#a09a95]pose[/color]  x %.1f  y %.1f  hdg %.0f deg   [color=#a09a95]slope[/color] %.0f deg" % [s["x"], s["y"], s["heading"], s["slope"]],
		"[color=#a09a95]speed[/color] %.2f m/s   [color=#a09a95]driven[/color] %.1f m%s" % [s["speed"], s["driven"], avoid],
		"[color=#a09a95]hazard[/color]  %s%s" % [_hazard(s["hazard_range"], s["hazard_bearing"], s["hazard_max"]),
			"   [color=#8fd8ff]dwelling %.0f sim-s[/color]" % float(s["dwell"]) if s["decision"] == "investigate" else ""],
	])
	var frac: float = clampf(float(s["budget"]) / maxf(1.0, float(s["capacity"])), 0.0, 1.0)
	_bar_fill.size.x = 406.0 * frac
	_bar_fill.color = GOOD if frac > 0.5 else (WARN if frac > 0.25 else BAD)
	_bar_label.text = "%.1f / %.0f Wh   (%.0f%%)   spent %.1f Wh" % [
		s["budget"], s["capacity"], frac * 100.0, float(s["capacity"]) - float(s["budget"])]
	_sync_chips(s["assigned"], s["confirmed"])
	audit.text = "[color=#a09a95]BRAIN's own account of the decision:[/color]\n" + str(s["audit"])
	minimap.queue_redraw()

func _hazard(r: float, b: float, max_r: float) -> String:
	if r >= max_r - 0.01:
		return "[color=#73dc84]clear[/color]"
	var col := "#f56b5c" if r < 3.0 else "#ffbf52"
	return "[color=%s]%.1f m at %+.0f deg[/color]" % [col, r, b]

func _clock(t: float) -> String:
	var s := int(t)
	return "%02d:%02d:%02d" % [s / 3600, (s / 60) % 60, s % 60]

func _sync_chips(assigned: Array, confirmed: Array) -> void:
	while _chips.get_child_count() < assigned.size():
		var l := Label.new()
		l.add_theme_font_size_override("font_size", 13)
		_chips.add_child(l)
	for i in _chips.get_child_count():
		var l: Label = _chips.get_child(i)
		if i >= assigned.size():
			l.visible = false
			continue
		l.visible = true
		var id: String = str(assigned[i])
		var done: bool = id in confirmed
		l.text = ("[x] " if done else "[ ] ") + id
		l.add_theme_color_override("font_color", GOOD if done else DIM)


## Top-down ground truth: every marker and anomaly, the rover, where it has been, and
## the wedge it can currently see. This is the panel that makes "the rover cannot see
## behind that rock" a thing you point at rather than a thing you claim.
class MiniMap extends Control:
	const SPAN := 150.0
	var world: World
	var rover: Rover
	var trail: PackedVector2Array = PackedVector2Array()
	var _last := Vector2(1e9, 1e9)

	func _to_map(p: Vector2) -> Vector2:
		return size * 0.5 + p / SPAN * size

	func _draw() -> void:
		draw_rect(Rect2(Vector2.ZERO, size), Color(0.06, 0.05, 0.05, 0.82))
		draw_rect(Rect2(Vector2.ZERO, size), Color(1.0, 0.62, 0.35, 0.35), false, 1.0)
		var grid := Color(1.0, 0.7, 0.45, 0.08)
		for k in range(1, 6):
			var f := size * (float(k) / 6.0)
			draw_line(Vector2(f.x, 0), Vector2(f.x, size.y), grid, 1.0)
			draw_line(Vector2(0, f.y), Vector2(size.x, f.y), grid, 1.0)
		if world == null or rover == null:
			return

		var pos := Vector2(rover.global_position.x, rover.global_position.z)
		if pos.distance_to(_last) > 1.0:
			trail.append(pos)
			_last = pos
			if trail.size() > 600:
				trail.remove_at(0)
		if trail.size() > 1:
			var pts := PackedVector2Array()
			for p in trail:
				pts.append(_to_map(p))
			draw_polyline(pts, Color(1.0, 0.72, 0.45, 0.5), 1.5)

		# what the camera can see, as a wedge
		var half := 30.0
		var a := _dir(rover.heading_deg - half) * 34.0 + pos
		var b := _dir(rover.heading_deg + half) * 34.0 + pos
		draw_colored_polygon(PackedVector2Array([_to_map(pos), _to_map(a), _to_map(b)]),
			Color(1.0, 0.8, 0.35, 0.13))

		for id in World.ANOMALY_POS.keys():
			var p: Vector2 = World.ANOMALY_POS[id]
			var m := _to_map(p)
			draw_circle(m, 4.0, Color(0.65, 0.55, 1.0, 0.95))
			draw_string(ThemeDB.fallback_font, m + Vector2(7, 4), id, HORIZONTAL_ALIGNMENT_LEFT, -1, 10, Color(0.72, 0.65, 1.0))
		for id in World.MARKERS.keys():
			var p: Vector2 = World.MARKERS[id]
			var m := _to_map(p)
			draw_rect(Rect2(m - Vector2(3.5, 3.5), Vector2(7, 7)), Color(0.95, 0.93, 0.9, 0.95))
			draw_string(ThemeDB.fallback_font, m + Vector2(7, 4), id, HORIZONTAL_ALIGNMENT_LEFT, -1, 10, Color(0.9, 0.88, 0.85))

		var r := _to_map(pos)
		var f := _dir(rover.heading_deg)
		var s := _dir(rover.heading_deg + 90.0)
		draw_colored_polygon(PackedVector2Array([
			r + f * 7.0, r - f * 4.0 + s * 4.5, r - f * 4.0 - s * 4.5]), Color(1.0, 0.55, 0.25))
		draw_string(ThemeDB.fallback_font, Vector2(8, size.y - 8), "GOD VIEW - ground truth", HORIZONTAL_ALIGNMENT_LEFT, -1, 10, Color(0.63, 0.6, 0.57))

	func _dir(h_deg: float) -> Vector2:
		var r := deg_to_rad(h_deg)
		return Vector2(sin(r), -cos(r))
