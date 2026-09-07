# debug_view.gd -- the god-view overlay that makes THE RULE visible.
#
# A judge's first question is "how do you know the rover isn't just reading the scene
# graph?" The honest answer is a picture: this draws the camera frustum and its ground
# footprint, so anything outside the wedge is provably invisible to BRAIN. The hazard
# fan is drawn too, because that is the ONLY other thing the rover senses.
class_name DebugView
extends Node3D

const FRUSTUM_RANGE := 30.0
const CONE_RANGE := 6.5      # the 3D cone stays short; the ground wedge carries the message

var show_frustum := true
var show_rays := true
## Set while BRAIN is investigating: the wedge turns cold so the beat is legible from
## the back of the room without reading the decision line.
var investigating := false

var _mesh: ImmediateMesh
var _rover: Rover
var _cam: Camera3D
var _terrain: Terrain

func build(rover: Rover, cam: Camera3D, terrain: Terrain) -> void:
	_rover = rover
	_cam = cam
	_terrain = terrain
	_mesh = ImmediateMesh.new()
	var mi := MeshInstance3D.new()
	mi.name = "Lines"
	mi.mesh = _mesh
	mi.material_override = _line_material()
	mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	# The overlay is for the judge on the main window, never for the rover camera --
	# BRAIN must not receive frames with our debug lines drawn into them.
	mi.layers = 2
	add_child(mi)

func _line_material() -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.vertex_color_use_as_albedo = true
	m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	m.cull_mode = BaseMaterial3D.CULL_DISABLED
	m.depth_draw_mode = BaseMaterial3D.DEPTH_DRAW_DISABLED
	# depth test stays ON: an overlay that punches through boulders would be lying
	# about exactly the thing it is drawn to demonstrate.
	m.no_depth_test = false
	return m

func _process(_delta: float) -> void:
	if _mesh == null or _cam == null:
		return
	_mesh.clear_surfaces()
	if not (show_frustum or show_rays):
		return
	_mesh.surface_begin(Mesh.PRIMITIVE_LINES)
	if show_frustum:
		_draw_frustum()
		_draw_footprint()
	if show_rays:
		_draw_rays()
	_mesh.surface_end()
	if show_frustum:
		_draw_wedge_fill()

func _line(a: Vector3, b: Vector3, c: Color) -> void:
	_mesh.surface_set_color(c)
	_mesh.surface_add_vertex(a)
	_mesh.surface_set_color(c)
	_mesh.surface_add_vertex(b)

## The four edges of what the 640x480 / 60 deg HFOV camera can actually see.
func _draw_frustum() -> void:
	var t := _cam.global_transform
	var half_h := deg_to_rad(_cam.fov) * 0.5
	var tan_x := tan(half_h)
	var tan_y := tan_x * 480.0 / 640.0                 # KEEP_WIDTH: vertical follows aspect
	var col := Color(1.0, 0.85, 0.35, 0.55)
	var corners := []
	for sx: float in [-1.0, 1.0]:
		for sy: float in [-1.0, 1.0]:
			corners.append(t * Vector3(sx * tan_x * CONE_RANGE, sy * tan_y * CONE_RANGE, -CONE_RANGE))
	for c in corners:
		_line(t.origin, c, col)
	_line(corners[0], corners[1], col)
	_line(corners[1], corners[3], col)
	_line(corners[3], corners[2], col)
	_line(corners[2], corners[0], col)

## The same wedge laid on the ground, which is what actually reads at a glance.
func _draw_footprint() -> void:
	if _terrain == null:
		return
	var col := Color(0.5, 0.87, 1.0, 0.8) if investigating else Color(1.0, 0.75, 0.25, 0.7)
	var origin := Vector2(_cam.global_position.x, _cam.global_position.z)
	var half := _cam.fov * 0.5
	var l_dir := _dir_xz(_rover.heading_deg - half)
	var r_dir := _dir_xz(_rover.heading_deg + half)
	var left: Array[Vector3] = []
	var right: Array[Vector3] = []
	for step in 13:
		var d := FRUSTUM_RANGE * float(step) / 12.0
		left.append(_on_ground(origin + l_dir * d))
		right.append(_on_ground(origin + r_dir * d))
	for i in range(1, left.size()):
		_line(left[i - 1], left[i], col)
		_line(right[i - 1], right[i], col)
	_line(left[left.size() - 1], right[right.size() - 1], col)

## Same compass convention as the rover: 0 = -Z, clockwise from above.
func _dir_xz(h_deg: float) -> Vector2:
	var r := deg_to_rad(h_deg)
	return Vector2(sin(r), -cos(r))

## A translucent slab of "this is the only ground BRAIN can see right now". It follows
## the terrain, so it disappears behind rises exactly where the camera's view does.
func _draw_wedge_fill() -> void:
	if _terrain == null:
		return
	var origin := Vector2(_cam.global_position.x, _cam.global_position.z)
	var half := _cam.fov * 0.5
	var col := Color(0.45, 0.85, 1.0, 0.16) if investigating else Color(1.0, 0.78, 0.3, 0.10)
	_mesh.surface_begin(Mesh.PRIMITIVE_TRIANGLES)
	var steps := 10
	for s in steps:
		var d0 := FRUSTUM_RANGE * float(s) / float(steps)
		var d1 := FRUSTUM_RANGE * float(s + 1) / float(steps)
		var l0 := _on_ground(origin + _dir_xz(_rover.heading_deg - half) * d0)
		var r0 := _on_ground(origin + _dir_xz(_rover.heading_deg + half) * d0)
		var l1 := _on_ground(origin + _dir_xz(_rover.heading_deg - half) * d1)
		var r1 := _on_ground(origin + _dir_xz(_rover.heading_deg + half) * d1)
		for tri in [[l0, r0, l1], [r0, r1, l1]]:
			for v: Vector3 in tri:
				_mesh.surface_set_color(col)
				_mesh.surface_add_vertex(v)
	_mesh.surface_end()

func _on_ground(p: Vector2) -> Vector3:
	return Vector3(p.x, _terrain.ground_y(p.x, p.y) + 0.06, p.y)

## The hazard fan: green while clear, red where it has hit something.
func _draw_rays() -> void:
	for seg in _rover.ray_segments():
		var c: Color = Color(1.0, 0.35, 0.3, 0.9) if seg["hit"] else Color(0.4, 0.9, 0.5, 0.35)
		_line(seg["from"], seg["to"], c)
