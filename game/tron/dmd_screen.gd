extends Node
## The display effects' picture (autoload DmdScreen): one fixed set of canvas items in its own SubViewport draws the
## effect on top of GMC's slide stack from its data (tron/dmd_effect.gd), and the viewport renders only when that
## picture changes (a new frame, a line blinking, new values), not at every frame. Each effect's GMC slide
## (tron/dmd_effect_slide.gd, one node) shows this picture. Nothing is built or freed when an effect starts or stops:
## its show only changes the draw list.
## Size: classic, the 128x32 dots; HD, the 128x32 area of the window in pixels (the window's content scale), kept in
## step when the window is resized. Layers, as the node scenes draw them: the pictures, rectangles and the black under
## the text; the glows (added); the lit text. A zoomed line (deff 100) has its own three, clipped.

const RomTextHd = preload("res://tron/rom_text_hd.gd")
const GROUP := "dmd_effect_slides"     # tron/dmd_effect_slide.gd in data mode

var hd := false
var redraws := 0                       # pictures rendered (the perf probe and tests read it)
var _vp: SubViewport
var _layers: Array[Node2D] = []        # base, glow, ink, then the clipped base, glow, ink
var _list: Array = []
var _top: Node = null
var _dirty := true
var _clip := Rect2()


func _ready() -> void:
	process_priority = 1000            # after the effects' slides advanced their time
	var dmd = get_tree().root.get_node_or_null("DmdMode")
	hd = dmd != null and dmd.hd
	_vp = SubViewport.new()
	_vp.name = "DmdPicture"
	_vp.disable_3d = true
	_vp.transparent_bg = false
	_vp.gui_disable_input = true
	_vp.canvas_item_default_texture_filter = Viewport.DEFAULT_CANVAS_ITEM_TEXTURE_FILTER_LINEAR if hd \
		else Viewport.DEFAULT_CANVAS_ITEM_TEXTURE_FILTER_NEAREST
	_vp.render_target_update_mode = SubViewport.UPDATE_ONCE
	add_child(_vp)
	for k in 6:
		var layer := Node2D.new()
		layer.name = ["Base", "Glow", "Ink", "ZoomBase", "ZoomGlow", "ZoomInk"][k]
		if k % 3 == 1:
			var add := CanvasItemMaterial.new()
			add.blend_mode = CanvasItemMaterial.BLEND_MODE_ADD
			layer.material = add
		layer.draw.connect(_draw_layer.bind(layer, k))
		_vp.add_child(layer)
		_layers.append(layer)
	for k in range(3, 6):
		RenderingServer.canvas_item_set_clip(_layers[k].get_canvas_item(), true)
	add_to_group(RomTextHd.GROUP)       # restyle(): the service menu changed the text glow or size
	_resize()
	get_tree().root.size_changed.connect(_resize)


func _exit_tree() -> void:
	preload("res://tron/letter_panel.gd").clear_glows()


## The picture the effects' slides show (128x32 dots).
func texture() -> Texture2D:
	return _vp.get_texture()


func _resize() -> void:
	var size := Vector2i(128, 32)
	var k := 1.0
	if hd:
		var win := Vector2(get_tree().root.size)
		k = maxf(minf(win.x / 128.0, win.y / 32.0), 1.0)
		size = Vector2i(roundi(128.0 * k), roundi(32.0 * k))
	if size != _vp.size:
		_vp.size = size
		_vp.canvas_transform = Transform2D.IDENTITY.scaled(Vector2(k, k))
		_dirty = true


func restyle() -> void:
	_dirty = true


## The effect on top: the last effect slide in the tree's drawing order that shows.
func _top_slide() -> Node:
	var slides := get_tree().get_nodes_in_group(GROUP)
	for i in range(slides.size() - 1, -1, -1):
		var s = slides[i]
		if s.state != null and s.is_visible_in_tree():
			return s
	return null


func _process(_delta: float) -> void:
	var top := _top_slide()
	var list: Array = top.state.build() if top else []
	if top == _top and list == _list and not _dirty:
		return
	_top = top
	_list = list
	_dirty = false
	_clip = Rect2()
	for e in _list:
		if e[0] == "htext" and e[4] != Rect2():
			_clip = e[4]
			break
	for k in range(3, 6):                 # the clipped layers sit at the clip's corner
		_layers[k].position = _clip.position
		RenderingServer.canvas_item_set_custom_rect(_layers[k].get_canvas_item(), true, Rect2(Vector2.ZERO, _clip.size))
	for layer in _layers:
		layer.queue_redraw()
	_vp.render_target_update_mode = SubViewport.UPDATE_ONCE
	redraws += 1


static func _line(p: Array) -> RomTextHd.Line:
	var l := RomTextHd.Line.new()
	l.set_line(p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7])
	return l


func _draw_layer(item: Node2D, k: int) -> void:
	var zoom := k >= 3
	var part := k % 3
	for e in _list:
		match e[0]:
			"tex":
				if part == 0 and not zoom:
					item.draw_texture_rect(e[1], e[2], false, e[3])
			"rect":
				if part == 0 and not zoom:
					item.draw_rect(e[1], e[2])
			"ctext":
				if part == 0 and not zoom:
					item.draw_string(e[1], e[3], e[2], HORIZONTAL_ALIGNMENT_LEFT, -1, e[4], e[5])
			"glowtex":
				if part == 1 and not zoom:
					item.draw_texture_rect(e[1], e[2], false, e[3])
			"htext":
				if (e[4] != Rect2()) != zoom:
					continue
				var xf: Transform2D = e[2]
				if zoom:
					xf = Transform2D(0.0, -e[4].position) * xf
				var line := _line(e[1])
				if part == 0:
					line.draw_cell(item, xf, e[3])
				elif part == 1:
					line.draw_glow(item, xf, e[3])
				else:
					line.draw_ink(item, xf, e[3])
