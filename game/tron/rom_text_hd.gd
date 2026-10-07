extends Node2D
## One line of ROM text in the HD display mode (tools/dmd_mode.gd): drawn from the ROM font's vector
## outlines (fonts/hd/rom_font_NN.ttf, scripts/font_outline.py) at the window's resolution, in the DMD text
## style (dmd_mode.gd: text colour, glow colour and strength). Child of the node placing the line (a
## tron/rom_text.gd label or a tron/service_screen.gd item): its origin is the line's top left, the
## baseline is `ascent` dots below, glyph advances are the ROM's, so the text lands dot for dot where the
## 128x32 layout puts it.
## Layers, in drawing order: the cell (the black the ROM draws under and around the glyphs), the glow
## (fonts/hd/rom_font_NN_glow.fnt, blurred lit dots, added to what is under it) and the lit dots in the
## text colour (shaded fonts: one layer per level, brighter over dimmer). The ROM's per-line brightness
## and blinking (the parent's modulate) apply to every layer.

const HD_DIR := "res://fonts/hd/"
const CELL_PLANE := 0xE000
const LEVEL_PLANE := 0xE000

static var _info: Dictionary = {}
static var _fonts: Dictionary = {}

var text := ""
var font_id := 0
var ascent := 0
var font_size := 1
var _glow: Node2D
var _ink: Node2D


## fonts_hd.json's entry of a ROM font (levels, files), {} when the HD fonts are not generated.
static func info(id: int) -> Dictionary:
	if _info.is_empty() and FileAccess.file_exists(HD_DIR + "fonts_hd.json"):
		var data = JSON.parse_string(FileAccess.get_file_as_string(HD_DIR + "fonts_hd.json"))
		if data is Dictionary:
			for f in data.get("fonts", []):
				_info[int(f["id"])] = f
	return _info.get(id, {})


## The ROM font's vector font (TrueType outlines rasterised at the drawn size: sharp at any resolution).
static func vector_font(id: int) -> FontFile:
	var key := "v%d" % id
	if not _fonts.has(key):
		var f := FontFile.new()
		f.load_dynamic_font(HD_DIR + str(info(id).get("file", "rom_font_%02d.ttf" % id)))
		f.antialiasing = TextServer.FONT_ANTIALIASING_GRAY
		f.hinting = TextServer.HINTING_NONE
		f.subpixel_positioning = TextServer.SUBPIXEL_POSITIONING_DISABLED
		f.allow_system_fallback = false
		f.generate_mipmaps = false
		_fonts[key] = f
	return _fonts[key]


## The ROM font's glow atlas (a bitmap font of the blurred glyphs, same advances).
static func glow_font(id: int) -> FontFile:
	var key := "g%d" % id
	if not _fonts.has(key):
		var f := FontFile.new()
		f.generate_mipmaps = true
		f.load_bitmap_font(HD_DIR + str(info(id).get("glow", "rom_font_%02d_glow.fnt" % id)))
		f.fixed_size_scale_mode = TextServer.FIXED_SIZE_SCALE_ENABLED
		_fonts[key] = f
	return _fonts[key]


## The DMD text style of tools/dmd_mode.gd (defaults when it is not there).
static func style() -> Dictionary:
	var dmd = (Engine.get_main_loop() as SceneTree).root.get_node_or_null("DmdMode")
	if dmd and dmd.has_method("text_style"):
		return dmd.text_style()
	return {"color": Color("#2a6cff"), "glow_color": Color("#22b8ff"), "glow": 0.0}


static func plane(s: String, base: int) -> String:
	var out := ""
	for c in s:
		out += String.chr(base + c.unicode_at(0))
	return out


func _init() -> void:
	name = "HdText"
	_glow = Node2D.new()
	_glow.name = "Glow"
	var add := CanvasItemMaterial.new()
	add.blend_mode = CanvasItemMaterial.BLEND_MODE_ADD
	_glow.material = add
	_glow.draw.connect(_draw_glow)
	add_child(_glow)
	_ink = Node2D.new()
	_ink.name = "Ink"
	_ink.draw.connect(_draw_ink)
	add_child(_ink)


## Shows text s in ROM font id; line_ascent and line_height in dots (fonts.json ascent, ascent + descent).
func set_line(s: String, id: int, line_ascent: int, line_height: int) -> void:
	if s == text and id == font_id and line_ascent == ascent and line_height == font_size:
		return
	text = s
	font_id = id
	ascent = line_ascent
	font_size = maxi(line_height, 1)
	queue_redraw()
	_glow.queue_redraw()
	_ink.queue_redraw()


func _draw() -> void:
	if text != "":
		draw_string(vector_font(font_id), Vector2(0, ascent), plane(text, CELL_PLANE), HORIZONTAL_ALIGNMENT_LEFT,
			-1, font_size, Color(0, 0, 0, 1))


func _draw_glow() -> void:
	var st := style()
	if text == "" or float(st["glow"]) <= 0.0:
		return
	var g: Color = st["glow_color"] * float(st["glow"])
	g.a = 1.0
	_glow.draw_string(glow_font(font_id), Vector2(0, ascent), text, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size, g)


func _draw_ink() -> void:
	if text == "":
		return
	var color: Color = style()["color"]
	var levels: Array = info(font_id).get("levels", [15])
	var font := vector_font(font_id)
	for k in levels.size():
		var lv := float(levels[k]) / 15.0
		var s := text if k == 0 else plane(text, LEVEL_PLANE + 0x100 * k)
		_ink.draw_string(font, Vector2(0, ascent), s, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size,
			Color(color.r * lv, color.g * lv, color.b * lv, 1))
