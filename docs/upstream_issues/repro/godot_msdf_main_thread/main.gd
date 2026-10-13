extends Node2D
# MSDF glyphs are generated on the thread that first draws them, usually the main thread.
# Each frame draws the 94 printable ASCII characters with a fresh MSDF copy of Orbitron (OFL, bundled), first at
# msdf_pixel_range 16, then 192 (a wide range, for outlines and glow), and prints how long that frame took.
# Expected: glyph generation off the main thread (or a way to pre-render a character set).
# Actual on a Jetson Xavier NX: 6.8 s (range 16) and 45 s (range 192) with the game frozen.

const TEXT := " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~"
const RANGES := [16, 192]
var step := 0
var font: FontFile
var t0 := 0


func _ready() -> void:
	_next()


func _next() -> void:
	if step >= RANGES.size():
		get_tree().quit()
		return
	var base := FontFile.new()
	base.load_dynamic_font("res://Orbitron.ttf")
	font = base.duplicate() as FontFile
	font.multichannel_signed_distance_field = true
	font.msdf_pixel_range = RANGES[step]
	font.msdf_size = 256
	queue_redraw()
	t0 = Time.get_ticks_msec()


func _draw() -> void:
	if font == null:
		return
	draw_string(font, Vector2(10, 100), TEXT.substr(0, 48), HORIZONTAL_ALIGNMENT_LEFT, -1, 32)
	draw_string(font, Vector2(10, 150), TEXT.substr(48), HORIZONTAL_ALIGNMENT_LEFT, -1, 32)


func _process(_delta: float) -> void:
	if font == null or t0 == 0:
		return
	# the frame after the draw: the glyphs were made while drawing
	print("msdf_pixel_range %d: first frame with the text took %d ms" % [RANGES[step], Time.get_ticks_msec() - t0])
	t0 = 0
	step += 1
	_next.call_deferred()
