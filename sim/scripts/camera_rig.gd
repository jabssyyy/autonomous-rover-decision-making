# camera_rig.gd -- sim.md S4/S5. The rover's forward camera, rendered into an
# off-screen 640x480 SubViewport and shipped as JPEG. Every property set here is
# load-bearing; the comments say which failure each one prevents.
class_name CameraRig
extends Node

var sub_viewport: SubViewport
var cam: Camera3D
var jpeg_quality := 0.75
var flip_y := false          # set true only if a capture comes out mirrored vertically
var last_bytes := 0
var frames_captured := 0

func build(canvas: CanvasLayer, cam_mount: Node3D, cfg: Dictionary) -> void:
	jpeg_quality = SimConfig.f(cfg, "jpeg_quality")
	var w := SimConfig.i(cfg, "camera_w")
	var h := SimConfig.i(cfg, "camera_h")

	sub_viewport = SubViewport.new()
	sub_viewport.name = "RoverViewport"
	sub_viewport.size = Vector2i(w, h)
	sub_viewport.own_world_3d = false                                  # false => share the main World3D, or we render an empty scene
	sub_viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS # default only redraws when VISIBLE; off-screen it would return blank
	sub_viewport.msaa_3d = Viewport.MSAA_DISABLED                      # the MSAA colour attachment cannot be copied from -> readback errors
	sub_viewport.use_hdr_2d = false                                    # HDR makes the target RGBAH and save_jpg_to_buffer gets the wrong format
	sub_viewport.transparent_bg = false
	sub_viewport.handle_input_locally = false
	canvas.add_child(sub_viewport)

	cam = Camera3D.new()
	cam.name = "RoverCam"
	# THE FOV TRAP: Camera3D.fov is VERTICAL by default (KEEP_HEIGHT). The contract
	# fixes camera.hfov_deg = 60, so keep_aspect must be KEEP_WIDTH. Get this wrong
	# and every bearing BRAIN computes is off by the 4:3 aspect ratio -- the rover
	# steers consistently beside its targets and the policy takes the blame.
	cam.keep_aspect = Camera3D.KEEP_WIDTH
	cam.fov = SimConfig.f(cfg, "camera_hfov_deg")
	cam.near = 0.05
	cam.far = 400.0
	# Visual layer 2 is the god-view debug overlay (frustum, hazard fan). BRAIN must
	# never receive a frame with our own annotations rendered into it.
	cam.cull_mask = 0xFFFFF & ~2
	cam.current = true
	sub_viewport.add_child(cam)

	# A Camera3D inside a SubViewport is NOT in the rover's node hierarchy, so it
	# ignores the rover transform. RemoteTransform3D is what actually moves it;
	# without this the rover view is a frozen shot of wherever the camera spawned.
	var remote := RemoteTransform3D.new()
	remote.name = "CamLink"
	remote.remote_path = cam.get_path()
	remote.update_position = true
	remote.update_rotation = true
	remote.update_scale = false
	remote.use_global_coordinates = true
	cam_mount.add_child(remote)

## Synchronous readback. get_image() forces a GPU sync (godot#75877) -- a 1-2 frame
## hitch, five times a second. That cost is known and accepted: this version is
## correct on every renderer and every version, which matters more today.
func capture_jpeg() -> PackedByteArray:
	# prevents black/stale frames. It does NOT remove the stall (that is inside
	# texture_get_data) -- separate problems, and the await is needed regardless.
	await RenderingServer.frame_post_draw
	var tex := sub_viewport.get_texture()
	if tex == null:
		return PackedByteArray()
	var img := tex.get_image()
	if img == null or img.is_empty():
		return PackedByteArray()
	if flip_y:
		img.flip_y()
	if img.get_format() != Image.FORMAT_RGB8:
		img.convert(Image.FORMAT_RGB8)
	var buf := img.save_jpg_to_buffer(jpeg_quality)
	last_bytes = buf.size()
	frames_captured += 1
	return buf

## Debug helper: dump one frame to user:// so the orientation can be eyeballed.
func dump_png(path: String) -> void:
	await RenderingServer.frame_post_draw
	var img := sub_viewport.get_texture().get_image()
	if img and not img.is_empty():
		img.save_png(path)
		print("CameraRig: wrote %s (%dx%d %s)" % [ProjectSettings.globalize_path(path),
			img.get_width(), img.get_height(), img.get_format()])
