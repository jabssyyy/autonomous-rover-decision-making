# terrain.gd -- sim.md S3. Visual ArrayMesh and HeightMapShape3D are filled from the
# SAME height function in the SAME row-major loop, at 1 m spacing, centred on origin.
# HeightMapShape3D's grid is FIXED at 1 unit and centred, so matching the visual mesh
# spacing exactly makes every alignment calculation disappear. Never scale the shape.
class_name Terrain
extends StaticBody3D

const SIZE := 257                # verts per side -> a 256 m x 256 m collidable field
const HALF := (SIZE - 1) / 2     # 128
const FAR_SIZE := 129            # visual-only skirt, 6.25 m spacing, out to +-400 m
const FAR_HALF := 400.0
const FAR_DROP := 0.35           # sunk this far so the fine mesh always wins at the seam

var _base := FastNoiseLite.new()
var _ridge := FastNoiseLite.new()
var _detail := FastNoiseLite.new()
var mesh_instance: MeshInstance3D
var far_instance: MeshInstance3D

func build(seed_value: int) -> void:
	collision_layer = 1
	collision_mask = 0
	_base.seed = seed_value
	_base.noise_type = FastNoiseLite.TYPE_SIMPLEX_SMOOTH
	_base.frequency = 0.006
	_base.fractal_octaves = 3
	_ridge.seed = seed_value + 7
	_ridge.noise_type = FastNoiseLite.TYPE_SIMPLEX_SMOOTH
	_ridge.frequency = 0.011
	_ridge.fractal_octaves = 2
	_detail.seed = seed_value + 1
	_detail.noise_type = FastNoiseLite.TYPE_SIMPLEX_SMOOTH
	_detail.frequency = 0.055
	_detail.fractal_octaves = 2

	var heights := PackedFloat32Array()
	heights.resize(SIZE * SIZE)
	for j in SIZE:
		for i in SIZE:
			heights[j * SIZE + i] = height_at(float(i - HALF), float(j - HALF))

	var mat := _build_material()

	mesh_instance = MeshInstance3D.new()
	mesh_instance.name = "Mesh"
	mesh_instance.mesh = _grid_mesh(SIZE, 1.0, 0.0)
	mesh_instance.material_override = mat
	mesh_instance.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON
	add_child(mesh_instance)

	# Without this the 256 m field ends in mid-air and the horizon is a hard line.
	far_instance = MeshInstance3D.new()
	far_instance.name = "FarMesh"
	far_instance.mesh = _grid_mesh(FAR_SIZE, (FAR_HALF * 2.0) / float(FAR_SIZE - 1), FAR_DROP, 120.0)
	far_instance.material_override = mat
	far_instance.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	add_child(far_instance)

	var shape := HeightMapShape3D.new()
	shape.map_width = SIZE
	shape.map_depth = SIZE
	shape.map_data = heights
	var col := CollisionShape3D.new()
	col.name = "Collision"
	col.shape = shape
	add_child(col)

## The single source of terrain truth. Metres in, metres up. Collision, visual mesh,
## the far skirt and every prop that gets dropped on the ground all read this.
func height_at(x: float, z: float) -> float:
	var d := Vector2(x, z).length()
	var h := _base.get_noise_2d(x, z) * 3.2
	# ridged term: |noise| inverted reads as eroded crests rather than dunes. Held back
	# near the rover so the demo corridor stays drivable and only the horizon gets hills.
	var far := smoothstep(45.0, 130.0, d)
	h += (1.0 - absf(_ridge.get_noise_2d(x, z))) * 6.0 * far
	h += _detail.get_noise_2d(x, z) * 0.45
	# flat pad under the spawn so the rover settles cleanly and the first frames are level
	return h * clampf((d - 6.0) / 10.0, 0.0, 1.0)

func ground_y(x: float, z: float) -> float:
	return height_at(x, z)

## Surface normal from the height gradient. Analytic, so it never disagrees with the mesh.
func normal_at(x: float, z: float) -> Vector3:
	var dx := height_at(x + 0.5, z) - height_at(x - 0.5, z)
	var dz := height_at(x, z + 0.5) - height_at(x, z - 0.5)
	return Vector3(-dx, 1.0, -dz).normalized()

## One grid builder for both meshes. `hole` skips quads whose centre is inside that
## radius, so the coarse skirt never fights the fine mesh it wraps.
func _grid_mesh(n: int, spacing: float, drop: float, hole := 0.0) -> ArrayMesh:
	var half := (n - 1) / 2
	var verts := PackedVector3Array(); verts.resize(n * n)
	var norms := PackedVector3Array(); norms.resize(n * n)
	var uvs := PackedVector2Array(); uvs.resize(n * n)
	for j in n:
		for i in n:
			var idx := j * n + i
			var x := float(i - half) * spacing
			var z := float(j - half) * spacing
			verts[idx] = Vector3(x, height_at(x, z) - drop, z)
			uvs[idx] = Vector2(x, z) * 0.25
			norms[idx] = normal_at(x, z)
	var indices := PackedInt32Array()
	for j in n - 1:
		for i in n - 1:
			if hole > 0.0:
				var cx := (float(i - half) + 0.5) * spacing
				var cz := (float(j - half) + 0.5) * spacing
				if absf(cx) < hole and absf(cz) < hole:
					continue
			var a := j * n + i
			var b := a + 1
			var c := a + n
			var d := c + 1
			# Godot front faces are CLOCKWISE. Wind them the other way and the terrain
			# is silently back-face culled: physics still works, the rover still drives,
			# and you look straight through the ground at the sky.
			indices.append_array([a, b, c, b, d, c])
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = verts
	arrays[Mesh.ARRAY_NORMAL] = norms
	arrays[Mesh.ARRAY_TEX_UV] = uvs
	arrays[Mesh.ARRAY_INDEX] = indices
	var am := ArrayMesh.new()
	am.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	return am

## Two CC0 ground scans blended by low-frequency noise, each sampled at two scales.
## A single tiled texture over 256 m reads as wallpaper from the god camera and gives
## BRAIN's perception a periodic signal that does not exist on Mars.
func _build_material() -> ShaderMaterial:
	var sh := Shader.new()
	sh.code = """
shader_type spatial;
render_mode cull_back, diffuse_burley, specular_schlick_ggx;

uniform sampler2D a_albedo : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D a_normal : hint_roughness_normal, filter_linear_mipmap, repeat_enable;
uniform sampler2D a_rough  : hint_default_white, filter_linear_mipmap, repeat_enable;
uniform sampler2D b_albedo : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D b_normal : hint_roughness_normal, filter_linear_mipmap, repeat_enable;
uniform sampler2D b_rough  : hint_default_white, filter_linear_mipmap, repeat_enable;
uniform sampler2D blend_mask : hint_default_white, filter_linear_mipmap, repeat_enable;
uniform vec3 tint : source_color = vec3(1.0, 0.72, 0.55);
uniform float uv_scale = 0.18;
uniform float macro_scale = 0.037;
uniform float mask_scale = 0.0035;

varying vec3 wpos;

void vertex() {
	wpos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}

void fragment() {
	vec2 uv = wpos.xz * uv_scale;
	vec2 uv2 = wpos.xz * macro_scale;
	float m = smoothstep(0.38, 0.62, texture(blend_mask, wpos.xz * mask_scale).r);

	vec3 alb = mix(texture(a_albedo, uv).rgb, texture(b_albedo, uv).rgb, m);
	// second, much larger sample of the same map breaks the tile repeat without
	// costing another texture -- overlay it at half strength
	vec3 macro = mix(texture(a_albedo, uv2).rgb, texture(b_albedo, uv2).rgb, m);
	ALBEDO = mix(alb, alb * macro * 2.0, 0.45) * tint;

	NORMAL_MAP = mix(texture(a_normal, uv).rgb, texture(b_normal, uv).rgb, m);
	NORMAL_MAP_DEPTH = 0.85;
	ROUGHNESS = mix(texture(a_rough, uv).r, texture(b_rough, uv).r, m) * 0.95 + 0.05;
	SPECULAR = 0.15;
}
"""
	var mat := ShaderMaterial.new()
	mat.shader = sh
	var g := "res://assets/ground/"
	mat.set_shader_parameter("a_albedo", load(g + "cracked_red_ground_Diffuse_2k.jpg"))
	mat.set_shader_parameter("a_normal", load(g + "cracked_red_ground_nor_gl_2k.jpg"))
	mat.set_shader_parameter("a_rough", load(g + "cracked_red_ground_Rough_2k.jpg"))
	mat.set_shader_parameter("b_albedo", load(g + "dry_ground_rocks_Diffuse_2k.jpg"))
	mat.set_shader_parameter("b_normal", load(g + "dry_ground_rocks_nor_gl_2k.jpg"))
	mat.set_shader_parameter("b_rough", load(g + "dry_ground_rocks_Rough_2k.jpg"))

	var noise := FastNoiseLite.new()
	noise.seed = _base.seed + 31
	noise.noise_type = FastNoiseLite.TYPE_SIMPLEX_SMOOTH
	noise.frequency = 0.9
	noise.fractal_octaves = 3
	var nt := NoiseTexture2D.new()
	nt.noise = noise
	nt.seamless = true
	nt.width = 512
	nt.height = 512
	mat.set_shader_parameter("blend_mask", nt)
	return mat
