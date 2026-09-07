# world.gd -- sim.md S8. CURATED, not generated: 5 common rock types repeated plus
# 3 visibly distinct anomalies, all placed from a seed so both demo runs replay
# identically. Variety is the enemy here -- a field of unique rocks flattens the
# novelty signal, habituation never demonstrates, and the policy has nothing to
# arbitrate. The 5 common types differ in TEXTURE, not tint (brain.md S6).
class_name World
extends Node3D

# Poly Haven CC0 Namaqualand boulders: real metre-scale desert scans, each with its
# own 1k albedo/normal/ARM set. `base` normalises the longest axis to 1 m so every
# call site can ask for a size in METRES and never think about the source scan.
const COMMON := [
	{"path": "res://assets/rocks/namaqualand_boulder_02/namaqualand_boulder_02_1k.gltf", "base": 0.395},
	{"path": "res://assets/rocks/namaqualand_boulder_03/namaqualand_boulder_03_1k.gltf", "base": 0.326},
	{"path": "res://assets/rocks/namaqualand_boulder_04/namaqualand_boulder_04_1k.gltf", "base": 0.397},
	{"path": "res://assets/rocks/namaqualand_boulder_05/namaqualand_boulder_05_1k.gltf", "base": 0.735},
	{"path": "res://assets/rocks/namaqualand_boulder_06/namaqualand_boulder_06_1k.gltf", "base": 0.826},
]
# A07 is the one the demo turns on. It gets rock_face_01: a different scan family,
# visibly layered rather than rounded, and 2k maps so it stays crisp in the crop
# BRAIN sends to the panel.
# A07 also gets a pale tint. That is not cheating the novelty story -- the "differ in
# texture, not tint" rule (brain.md S6) is about keeping the COMMON types separable
# from each other. An anomaly is supposed to be anomalous, and a light-toned outcrop
# against dusty red basalt is the real thing Perseverance goes and looks at.
const ANOMALY := {
	"A07": {"path": "res://assets/rocks/rock_face_01/rock_face_01.gltf", "base": 0.202, "size": 2.0,
		"tint": Color(0.95, 0.92, 0.86)},
	"A11": {"path": "res://assets/rocks/stone_01/stone_01.gltf", "base": 6.67, "size": 1.4,
		"tint": Color(0.62, 0.60, 0.66)},
	"A14": {"path": "res://assets/rocks/namaqualand_stones_01/namaqualand_stones_01.gltf", "base": 0.98,
		"size": 1.6, "tint": Color(0.88, 0.74, 0.52)},
}
# Gravel. The moon_rock scans are 7-25 cm pebbles, which is exactly what they are
# good for -- as ground litter at native scale, not blown up into boulders.
var pebble_count := 2600
const PEBBLE_RADIUS := 95.0

# Staging from brain.md S5.3 -- these distances are what make the deviate run win by
# 2.1x and the stay run lose by 15x. The rover spawns at origin on heading 0 (-Z).
const MARKERS := {
	"M01": Vector2(-8.0, -12.0),
	"M02": Vector2(1.5, -32.0),     # the primary: ~32 m ahead
	"M03": Vector2(-20.0, -46.0),
	"M04": Vector2(26.0, -30.0),
	"M05": Vector2(-30.0, 10.0),
}
const ANOMALY_POS := {
	"A07": Vector2(6.0, -20.0),     # ~5.7 m off the M02 path -- the decision the demo is about
	"A11": Vector2(-34.0, -24.0),
	"A14": Vector2(22.0, 16.0),
}
# A07 must not be in frame during BRAIN's novelty warm-up, or it gets learned as
# "normal" and habituation eats the whole demo (sim.md S8). Rather than hiding it,
# a COMMON boulder sits on the sight line from spawn and occludes it until the rover
# has driven past -- physical, reproducible, and nothing pops into existence.
const A07_SCREEN := Vector2(3.9, -13.1)

# The marker PNGs are 720 px with a 120 px white quiet zone baked in on every side,
# so the ArUco pattern itself is only 480/720 of the quad. config.yaml's
# marker_width_m is the PATTERN width, because that is what BRAIN's range estimate
# f_px * W_m / w_px measures. Size the quad by the full image and every range comes
# back 1.5x too far -- a silent, perfectly plausible-looking 50 % error.
const PATTERN_FRACTION := 480.0 / 720.0

var terrain: Terrain
var marker_nodes := {}
var anomaly_nodes := {}
var rock_count := 0
var _rng := RandomNumberGenerator.new()
var _tinted := {}

const DUST := Color(1.0, 0.80, 0.63)

func build(terrain_ref: Terrain, cfg: Dictionary, low_fx := false) -> void:
	terrain = terrain_ref
	if low_fx:
		pebble_count = 700
	_rng.seed = SimConfig.i(cfg, "world_seed")
	_scatter_common()
	_place_anomalies()
	_place_markers(SimConfig.f(cfg, "marker_width_m"))
	_scatter_gravel()
	print("World: %d boulders, %d pebbles, %d markers, %d anomalies"
		% [rock_count, pebble_count, MARKERS.size(), ANOMALY.size()])

# ------------------------------------------------------------------ rock field
func _scatter_common() -> void:
	# Two passes: a dense band along the demo corridor so the rover always has common
	# rocks in frame to habituate on, then a thinner field out to the horizon.
	for k in 34:
		var along := Vector2.ZERO.lerp(Vector2(1.5, -48.0), _rng.randf())
		_try_place(along + Vector2(_rng.randf_range(-14.0, 14.0), _rng.randf_range(-7.0, 7.0)))
	for k in 46:
		_try_place(Vector2(_rng.randf_range(-75.0, 75.0), _rng.randf_range(-75.0, 75.0)))
	# The occluder. A big instance of a COMMON type, so the screen introduces nothing novel.
	_spawn_rock(COMMON[2], A07_SCREEN, 2.7, "A07Screen")

func _try_place(p: Vector2) -> void:
	if p.length() < 9.0:                      # keep the spawn pad clear
		return
	for c in MARKERS.values():
		if p.distance_to(c) < 4.0:
			return
	for a in ANOMALY_POS.values():
		if p.distance_to(a) < 7.0:            # anomalies must read as isolated
			return
	if p.distance_to(A07_SCREEN) < 5.0:
		return
	var idx := rock_count % COMMON.size()
	_spawn_rock(COMMON[idx], p, _rng.randf_range(0.7, 2.1), "Rock%03d_t%d" % [rock_count, idx])

func _place_anomalies() -> void:
	for id in ANOMALY.keys():
		var a: Dictionary = ANOMALY[id]
		anomaly_nodes[id] = _spawn_rock(a, ANOMALY_POS[id], float(a["size"]), id)

## `size_m` is the rock's longest axis in METRES; the type's `base` does the conversion.
func _spawn_rock(type_def: Dictionary, p: Vector2, size_m: float, node_name: String) -> Node3D:
	var scene := load(str(type_def["path"])) as PackedScene
	if scene == null:
		push_warning("World: missing rock %s" % type_def["path"])
		return null
	var inst := scene.instantiate() as Node3D
	inst.name = node_name
	_strip_lods(inst)
	var s := float(type_def["base"]) * size_m
	inst.scale = Vector3.ONE * s
	inst.rotation.y = _rng.randf_range(0.0, TAU)
	inst.position = Vector3(p.x, terrain.ground_y(p.x, p.y) - 0.10 * size_m, p.y)
	_dust(inst, str(type_def["path"]), type_def.get("tint", DUST))
	add_child(inst)
	_add_collision(inst)
	rock_count += 1
	return inst

## One uniform Martian dust tint over every rock type. It multiplies, so the TEXTURE
## differences between types (which is what novelty separates on, brain.md S6) all
## survive -- it only stops terrestrial grey boulders sitting on red ground like props.
func _dust(inst: Node3D, key: String, tint: Color) -> void:
	if not _tinted.has(key):
		var mats := []
		var mi := _first_mesh(inst)
		if mi:
			for s in mi.mesh.get_surface_count():
				var src := mi.mesh.surface_get_material(s)
				var dup: BaseMaterial3D = src.duplicate() if src is BaseMaterial3D else StandardMaterial3D.new()
				dup.albedo_color = tint
				mats.append(dup)
		_tinted[key] = mats
	var mi2 := _first_mesh(inst)
	if mi2 == null:
		return
	for s in (_tinted[key] as Array).size():
		mi2.set_surface_override_material(s, _tinted[key][s])

## Poly Haven glTFs ship LOD0/LOD1/LOD2 as sibling meshes. Godot renders all of them
## on top of each other -- multiplied triangles and z-fighting on every rock.
func _strip_lods(n: Node) -> void:
	for c in n.get_children():
		var nm := str(c.name).to_lower()
		if nm.contains("_lod") and not nm.ends_with("_lod0"):
			c.queue_free()

## Convex hull per rock on layer 2 -- the layer the hazard rays watch.
func _add_collision(inst: Node3D) -> void:
	var mi := _first_mesh(inst)
	if mi == null:
		return
	var body := StaticBody3D.new()
	body.name = "Body"
	body.collision_layer = 2
	body.collision_mask = 0
	var col := CollisionShape3D.new()
	col.shape = mi.mesh.create_convex_shape()
	col.transform = mi.transform
	body.add_child(col)
	inst.add_child(body)

func _first_mesh(n: Node) -> MeshInstance3D:
	if n is MeshInstance3D and (n as MeshInstance3D).mesh != null:
		return n
	for c in n.get_children():
		var found := _first_mesh(c)
		if found:
			return found
	return null

# --------------------------------------------------------------------- gravel
## Ground litter, one MultiMesh, no collision and no per-instance nodes. This is what
## stops the terrain reading as a bare painted plane, and it is nearly free: a ~90
## triangle pebble drawn 2600 times in a single draw call.
func _scatter_gravel() -> void:
	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.mesh = _pebble_mesh()
	mm.instance_count = pebble_count
	for i in pebble_count:
		# sqrt keeps the density even across the disc instead of clumping at the centre
		var r := sqrt(_rng.randf()) * PEBBLE_RADIUS
		var a := _rng.randf() * TAU
		var p := Vector2(cos(a), sin(a)) * r
		var size := _rng.randf_range(0.04, 0.19)
		var b := Basis(Vector3.UP, _rng.randf_range(0.0, TAU))
		b = b.rotated(Vector3.RIGHT, _rng.randf_range(-0.4, 0.4))
		b = b.scaled(Vector3(size * _rng.randf_range(0.8, 1.4), size * _rng.randf_range(0.5, 0.9), size))
		mm.set_instance_transform(i, Transform3D(b,
			Vector3(p.x, terrain.ground_y(p.x, p.y) - size * 0.25, p.y)))
	var mmi := MultiMeshInstance3D.new()
	mmi.name = "Gravel"
	mmi.multimesh = mm
	mmi.material_override = _pebble_material()
	mmi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF   # 2600 shadow casters is not worth 20 fps
	add_child(mmi)

## A sphere pushed around by noise. Cheap, and it reads as a stone rather than a ball.
func _pebble_mesh() -> ArrayMesh:
	var sphere := SphereMesh.new()
	sphere.radius = 0.5
	sphere.height = 1.0
	sphere.radial_segments = 7
	sphere.rings = 4
	var arrays := sphere.get_mesh_arrays()
	var verts: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var norms: PackedVector3Array = arrays[Mesh.ARRAY_NORMAL]
	var n := FastNoiseLite.new()
	n.seed = _rng.seed
	n.frequency = 1.6
	for i in verts.size():
		var v := verts[i]
		verts[i] = v * (1.0 + n.get_noise_3d(v.x * 6.0, v.y * 6.0, v.z * 6.0) * 0.45)
		norms[i] = verts[i].normalized()
	arrays[Mesh.ARRAY_VERTEX] = verts
	arrays[Mesh.ARRAY_NORMAL] = norms
	var am := ArrayMesh.new()
	am.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	return am

func _pebble_material() -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	var tex := load("res://assets/rocks/moon_rock_02/textures/moon_rock_02_diff_1k.jpg") as Texture2D
	if tex:
		m.albedo_texture = tex
		m.uv1_triplanar = true
		m.uv1_scale = Vector3(4.0, 4.0, 4.0)
	m.albedo_color = Color(0.78, 0.52, 0.38)
	m.roughness = 0.95
	return m

# -------------------------------------------------------------------- markers
## ArUco quads -- sim.md S7. Jabin's detector runs real OpenCV on these, so the
## texture must survive import uncompressed and the material must be UNSHADED:
## lighting is not allowed to touch the black/white cells.
func _place_markers(width_m: float) -> void:
	var quad_m := width_m / PATTERN_FRACTION
	for id in MARKERS.keys():
		var p: Vector2 = MARKERS[id]
		var holder := Node3D.new()
		holder.name = id
		holder.position = Vector3(p.x, terrain.ground_y(p.x, p.y), p.y)
		add_child(holder)

		var post := MeshInstance3D.new()
		var cyl := CylinderMesh.new()
		cyl.top_radius = 0.05
		cyl.bottom_radius = 0.07
		cyl.height = 0.9
		post.mesh = cyl
		post.position = Vector3(0, 0.45, 0)
		var pm := StandardMaterial3D.new()
		pm.albedo_color = Color(0.28, 0.26, 0.25)
		pm.roughness = 0.8
		post.material_override = pm
		holder.add_child(post)

		var plate := Node3D.new()
		plate.name = "Plate"
		plate.position = Vector3(0, 0.9 + quad_m * 0.5, 0)
		holder.add_child(plate)

		# a thin backing so the marker reads as a physical plate, not a floating decal
		var back := MeshInstance3D.new()
		var bm := BoxMesh.new()
		bm.size = Vector3(quad_m * 1.03, quad_m * 1.03, 0.03)
		back.mesh = bm
		back.position = Vector3(0, 0, -0.02)
		var backm := StandardMaterial3D.new()
		backm.albedo_color = Color(0.55, 0.53, 0.5)
		backm.roughness = 0.7
		back.material_override = backm
		plate.add_child(back)

		var quad := MeshInstance3D.new()
		quad.name = "Face"
		var qm := QuadMesh.new()
		qm.size = Vector2(quad_m, quad_m)
		quad.mesh = qm
		quad.material_override = _marker_material(id)
		plate.add_child(quad)

		# QuadMesh faces +Z; look_at points -Z at the target, so flip after aiming.
		var aim := Vector3(0, plate.global_position.y, 0)
		if aim.distance_to(plate.global_position) > 0.5:
			plate.look_at(aim, Vector3.UP)
			plate.rotate_object_local(Vector3.UP, PI)
		marker_nodes[id] = holder

func _marker_material(id: String) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	var tex := load("res://assets/markers/%s.png" % id) as Texture2D
	if tex:
		m.albedo_texture = tex
	else:
		push_warning("World: missing marker texture %s" % id)
		m.albedo_color = Color.WHITE
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.texture_filter = BaseMaterial3D.TEXTURE_FILTER_NEAREST
	m.cull_mode = BaseMaterial3D.CULL_DISABLED
	return m

## Ground truth for marker confirmation. SIM's call, not BRAIN's (sim.md S9).
func marker_within(pos: Vector3, range_m: float) -> String:
	for id in MARKERS.keys():
		var p: Vector2 = MARKERS[id]
		if Vector2(pos.x, pos.z).distance_to(p) <= range_m:
			return id
	return ""
