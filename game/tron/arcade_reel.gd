extends Node2D
## The Flynn's Arcade award reel, drawn like the ROM's deff_105_arcade_award (0x0100e8bc): three cabinets
## (45 dots wide, 5 apart), each with an award icon at +8/+5 under it, enter from x reel_x and move 4 dots
## left every frame of 3 ticks for `scroll` frames. Then the award's slot blinks for `blink` frames: its
## bright icon (icon_a) on even frames, the dim one (icon_b) on odd frames; the other two icons stay dim.
## The last frame stays up through the hold. The choices come from the event args (tron/features/arcade.py
## Arcade.reel): cab0-cab2 (cabinet 0-3), icon0-icon2 (award id 1-12, 0 = none), slot, scroll, blink.
## Seekable for scripts/render_diff.py (seek_ms).

@export var cabinets: Array[Texture2D] = []
@export var icons_a: Array[Texture2D] = []
@export var icons_b: Array[Texture2D] = []
@export var frame_ms := 48.78
@export var reel_x := 82
@export var reel_step := 4
@export var cabinet_gap := 5
@export var icon_dx := 8
@export var icon_y := 5

var _elapsed_ms := 0.0
var _seeked := false
var _values := {}
var _scale := 1           # the pictures' size over their classic size (their colour twins: DmdMode.color_scale)


func _ready() -> void:
	add_to_group("rom_timed")
	_use_color_twins()
	var slide = MPF.util.find_parent_slide_or_widget(self)
	if slide:
		slide.register_updater(self)
	queue_redraw()


## HD with colour: the cabinets and icons in their Serum colours (DmdMode.color_texture, color_scale times
## larger), drawn at their classic size with crisp dots and no DMD tint; only when every picture has its twin.
func _use_color_twins() -> void:
	var dm = get_node_or_null("/root/DmdMode")
	if dm == null or not dm.has_method("color_texture"):
		return
	var sets := [cabinets, icons_a, icons_b]
	var twins := []
	for pics in sets:
		var out: Array[Texture2D] = []
		for tex in pics:
			var big: Texture2D = dm.color_texture(tex)
			if big == null:
				return
			out.append(big)
		twins.append(out)
	cabinets = twins[0]
	icons_a = twins[1]
	icons_b = twins[2]
	_scale = int(dm.color_scale)
	modulate = Color(1, 1, 1, modulate.a)
	texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST


func _pic(tex: Texture2D, at: Vector2) -> void:
	if _scale == 1:
		draw_texture(tex, at)
	else:
		draw_texture_rect(tex, Rect2(at, tex.get_size() / _scale), false)


func _exit_tree() -> void:
	var slide = MPF.util.find_parent_slide_or_widget(self)
	if slide:
		slide.remove_updater(self)


func update(_settings: Dictionary, kwargs: Dictionary = {}) -> void:
	for k in kwargs:
		_values[k] = kwargs[k]
	queue_redraw()


func seek_ms(t: float) -> void:
	_seeked = true
	_elapsed_ms = t
	queue_redraw()


func _process(delta: float) -> void:
	if not _seeked:
		_elapsed_ms += delta * 1000.0
		queue_redraw()


func _arg(key: String, default: int) -> int:
	var v = _values.get(key, default)
	return int(v) if v != null and str(v) != "" else default


## Reel position and blink step on effect frame `frame`: [x, step] (step -1 while the reel scrolls).
static func reel_state(frame: int, scroll: int, blink: int, x0: int, step: int) -> Array:
	if frame < scroll:
		return [x0 - step * frame, -1]
	return [x0 - step * scroll, mini(frame - scroll, maxi(blink - 1, 0))]


func _draw() -> void:
	var frame := int(_elapsed_ms / frame_ms) if frame_ms > 0 else 0
	var slot := _arg("slot", -1)
	var state := reel_state(frame, _arg("scroll", 0), _arg("blink", 0), reel_x, reel_step)
	var x: int = state[0]
	var blink_step: int = state[1]
	for i in 3:
		var cab := _arg("cab%d" % i, 0)
		var id := _arg("icon%d" % i, 0)
		if id >= 1 and id <= icons_a.size() and id <= icons_b.size():
			var bright := blink_step < 0 or (i == slot and blink_step % 2 == 0)
			_pic(icons_a[id - 1] if bright else icons_b[id - 1], Vector2(x + icon_dx, icon_y))
		var tex: Texture2D = cabinets[cab] if cab >= 0 and cab < cabinets.size() else null
		if tex:
			_pic(tex, Vector2(x, 0))
			x += tex.get_width() / _scale + cabinet_gap
		else:
			x += 45 + cabinet_gap
