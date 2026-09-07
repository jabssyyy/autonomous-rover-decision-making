# sim_link.gd -- sim.md S6. Godot is the WebSocket CLIENT; BRAIN is the server at
# ws://127.0.0.1:8765. That direction is deliberate: stub_brain.py and the real
# BRAIN are interchangeable, so SIM never waits on the perception stack.
# 127.0.0.1, not localhost -- Python may bind ::1 and Godot may resolve the other family.
class_name SimLink
extends Node

signal action_received(action: Dictionary)
signal link_changed(connected: bool)

const BUFFER_BYTES := 4 * 1024 * 1024
const RETRY_S := 1.0

var url := "ws://127.0.0.1:8765"
var connected := false
var frames_sent := 0
var frames_dropped := 0
var actions_received := 0
var last_error := ""

var _ws: WebSocketPeer = null
var _retry_in := 0.0

func _ready() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--brain="):
			url = arg.substr(8)
	_open()

func _open() -> void:
	_ws = WebSocketPeer.new()
	# THE 65535-BYTE TRAP: outbound_buffer_size defaults to 65535, and a 640x480
	# JPEG at q0.75 is routinely 50-120 KB. Over the limit send() returns
	# ERR_OUT_OF_MEMORY and the frame is silently gone. Set this BEFORE connecting.
	_ws.outbound_buffer_size = BUFFER_BYTES
	_ws.inbound_buffer_size = BUFFER_BYTES
	_ws.max_queued_packets = 64
	var err := _ws.connect_to_url(url)
	if err != OK:
		last_error = "connect_to_url: %s" % error_string(err)
		_retry_in = RETRY_S

func _process(delta: float) -> void:
	if _ws == null:
		_retry_in -= delta
		if _retry_in <= 0.0:
			_open()
		return
	_ws.poll()
	match _ws.get_ready_state():
		WebSocketPeer.STATE_OPEN:
			if not connected:
				connected = true
				last_error = ""
				print("SimLink: connected to %s" % url)
				link_changed.emit(true)
			_drain()
		WebSocketPeer.STATE_CLOSED:
			if connected:
				print("SimLink: closed (%d) %s" % [_ws.get_close_code(), _ws.get_close_reason()])
				connected = false
				link_changed.emit(false)
			_ws = null
			_retry_in = RETRY_S
		_:
			pass

func _drain() -> void:
	while _ws.get_available_packet_count() > 0:
		# ORDER MATTERS: was_string_packet() describes the packet already fetched by
		# get_packet(), not the next one. Ask first and every action is off by one.
		var pkt := _ws.get_packet()
		if not _ws.was_string_packet():
			continue                       # BRAIN sends no binary on this link
		var parsed = JSON.parse_string(pkt.get_string_from_utf8())
		if typeof(parsed) != TYPE_DICTIONARY:
			last_error = "unparseable action frame"
			continue
		if parsed.get("type", "") != "action":
			continue
		# Godot's JSON parser turns EVERY number into a float: 1423 comes back as
		# 1423.0 and JSON.stringify writes it straight back out that way. Python's
		# contract.py wants a real int for in_reply_to_seq, so anything that re-emits
		# an action (the run recorder, a replay tool) fails validation unless the cast
		# happens here, once, at the parse boundary.
		var reply = parsed.get("in_reply_to_seq", -1)
		if not (reply is float or reply is int) or not is_finite(float(reply)) or float(reply) != floor(float(reply)):
			continue
		parsed["in_reply_to_seq"] = int(reply)
		var audit = parsed.get("audit", null)
		if audit is Dictionary and audit.has("version"):
			if float(audit.version) != 2.0:
				continue
			audit["version"] = 2
		actions_received += 1
		action_received.emit(parsed)

## One text frame (the observation header) immediately followed by one binary frame
## (the JPEG). A single TCP connection guarantees the order; Python receives str
## then bytes and pairs them. Returns false if the pair did not go out intact.
func send_observation(header: Dictionary, jpeg: PackedByteArray) -> bool:
	if not connected or _ws == null:
		return false
	if jpeg.is_empty():
		frames_dropped += 1
		last_error = "empty capture"
		return false
	var e1 := _ws.send_text(JSON.stringify(header))
	if e1 != OK:
		frames_dropped += 1
		last_error = "send_text: %s" % error_string(e1)
		return false
	var e2 := _ws.send(jpeg)               # default WRITE_MODE_BINARY
	if e2 != OK:
		frames_dropped += 1
		last_error = "send jpeg (%d B): %s" % [jpeg.size(), error_string(e2)]
		_ws.close(1011, "incomplete observation pair")
		return false
	frames_sent += 1
	return true

func _exit_tree() -> void:
	if _ws:
		_ws.close()                        # close() is asynchronous; nothing to await
