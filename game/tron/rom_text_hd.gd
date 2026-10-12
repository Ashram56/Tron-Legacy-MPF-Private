extends Node2D
const RomTextHd = preload("res://tron/rom_text_hd.gd")
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
## Clean fonts (dmd_mode.gd font, default rajdhani): the lit dots are replaced by an ordinary font (fonts_ttf/),
## kept in the ROM's place: letters as tall as the ROM font's capitals, the line aligned as the ROM aligns it
## (left, centred or right, flags as tron/rom_text.gd) inside the ROM's text box and squeezed to its width when
## wider, in the top level of shaded fonts, with a black outline instead of the ROM's cell (wider for outlined fonts).
## Drawn as a multichannel signed distance field: sharp at any window size.

const HD_DIR := "res://fonts/hd/"
const GROUP := "dmd_hd_text"     # every line, redrawn when the service menu changes the glow or size (restyle())
const CELL_PLANE := 0xE000
const LEVEL_PLANE := 0xE000

const CLEAN_DIR := "res://fonts_ttf/"
## clean fonts: file in fonts_ttf/ ("" = Godot's own default font), OpenType weight (0 = as is)
const CLEAN := {"rajdhani": ["Rajdhani-Bold.ttf", 0], "orbitron": ["Orbitron.ttf", 700], "godot": ["", 0]}
const CLEAN_SIZE := 64           # the clean font's drawing size, scaled to the line's height in dots
## the clean fonts' two signed distance field copies (_sdf()): the letters, and the black and glow outlines
const MSDF_SIZE := 256
const TEXT_RANGE := 16
const WIDE_RANGE := 192
## the clean fonts' fields, made once at setup (tools/bake_fonts.gd, scripts/setup.py): made here, on Godot's
## main thread when a character is first drawn, they held the game 6 s (text) and 45 s (wide) for the 94
## printable characters of Orbitron on a Jetson Xavier NX
const BAKED_DIR := "res://fonts_ttf/baked/"
## the black under clean text, in dots on each side: outlined ROM fonts, the others (instead of the ROM's cell)
const OUTLINE_DOTS := 1.0
const CELL_DOTS := 0.5

static var _info: Dictionary = {}
static var _fonts: Dictionary = {}
static var _clean_name := "?"
static var _clean: Dictionary = {}

var line := Line.new()           # the line drawn (set_line()); a RomTextHd node draws one Line
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


## The clean fonts' size (dmd_mode.gd text_scale): 1 = capitals as tall as the ROM's, never wider than its text.
static func text_scale() -> float:
	var dmd = (Engine.get_main_loop() as SceneTree).root.get_node_or_null("DmdMode")
	return float(dmd.text_scale) if dmd and "text_scale" in dmd else 1.0


## The clean font of the HD mode: {"font", "cap" (capital height / em)}, or {} for the ROM's own fonts.
static func clean() -> Dictionary:
	var dmd = (Engine.get_main_loop() as SceneTree).root.get_node_or_null("DmdMode")
	var want: String = str(dmd.font) if dmd and "font" in dmd else "rom"
	if want == _clean_name:
		return _clean
	_clean_name = want
	_clean = {}
	if want == "rom":
		return _clean
	var spec: Array = CLEAN.get(want, [want, 0])
	var base: Font = null
	var path := ""
	if spec[0] == "":
		base = ThemeDB.fallback_font
	else:
		path = spec[0] if want not in CLEAN else CLEAN_DIR + spec[0]
		var f := FontFile.new()
		if FileAccess.file_exists(path) and f.load_dynamic_font(path) == OK:
			base = f
		else:
			push_warning("DMD font %s: cannot load %s, using the ROM fonts" % [want, path])
			return _clean
	var cap := cap_height(base)
	_clean = {"font": _sdf(base, TEXT_RANGE, spec[1], path), "wide": _sdf(base, WIDE_RANGE, spec[1], path),
		"cap": cap}
	return _clean


## The font as a multichannel signed distance field (sharp at any scale), at an OpenType weight (0 = as is).
## px_range: the field's reach in texels of a 256 texel glyph: small keeps the edges smooth, large lets outlines
## (the black under the text, the glow) grow wide.
## path: the font file, whose baked field (baked_path()) is used when there is one.
static func _sdf(base: Font, px_range: int, weight: int, path := "") -> Font:
	var baked := baked_path(path, px_range, weight) if path != "" else ""
	if baked != "" and ResourceLoader.exists(baked):
		base = load(baked)
	elif base is FontFile:
		base = msdf_copy(base as FontFile, px_range)
	return weighted(base, weight)


## A copy of a dynamic font drawn as a multichannel signed distance field (no glyph made yet).
static func msdf_copy(base: FontFile, px_range: int) -> FontFile:
	var f := base.duplicate() as FontFile
	f.multichannel_signed_distance_field = true
	f.msdf_pixel_range = px_range
	f.msdf_size = MSDF_SIZE
	f.allow_system_fallback = false
	return f


## The font at an OpenType weight (0 = as is).
static func weighted(base: Font, weight: int) -> Font:
	if weight > 0:
		var v := FontVariation.new()
		v.base_font = base
		v.variation_opentype = {TextServerManager.get_primary_interface().name_to_tag("wght"): weight}
		base = v
	return base


## Starts loading the baked fields of clean font want on worker threads (tools/dmd_mode.gd, at start-up), so the
## first line drawn finds them loaded (loaded then, on the main thread, they held the game 1.3 s).
static func load_baked(want: String) -> void:
	var spec: Array = CLEAN.get(want, [want, 0])
	var path: String = spec[0] if want not in CLEAN else CLEAN_DIR + spec[0]
	if spec[0] == "" or not FileAccess.file_exists(path):
		return
	for px_range in [TEXT_RANGE, WIDE_RANGE]:
		var baked := baked_path(path, px_range, spec[1])
		if ResourceLoader.exists(baked):
			ResourceLoader.load_threaded_request(baked)


## Where tools/bake_fonts.gd saves the field of font file path: named after the file, its contents, the weight,
## the field's settings and the Godot version, so a change of any of them is never served a stale field.
static func baked_path(path: String, px_range: int, weight: int) -> String:
	var key := "%s %d %d %d %s" % [FileAccess.get_md5(path), weight, MSDF_SIZE, px_range,
		Engine.get_version_info()["string"]]
	return "%s%s_%s.res" % [BAKED_DIR, path.get_file().get_basename(), key.md5_text().left(12)]


## A font's capital height per em (the top of its "H"), 0.7 when it has none.
static func cap_height(font: Font) -> float:
	var ts := TextServerManager.get_primary_interface()
	var rid: RID = font.get_rids()[0]
	var gid := ts.font_get_glyph_index(rid, 256, "H".unicode_at(0), 0)
	if gid == 0:
		return 0.7
	ts.font_render_glyph(rid, Vector2i(256, 0), gid)
	var top := -ts.font_get_glyph_offset(rid, Vector2i(256, 0), gid).y / 256.0
	return top if top > 0.2 else 0.7


static func plane(s: String, base: int) -> String:
	var out := ""
	for c in s:
		out += String.chr(base + c.unicode_at(0))
	return out


func _init() -> void:
	name = "HdText"
	add_to_group(GROUP)
	_glow = Node2D.new()
	_glow.name = "Glow"
	var add := CanvasItemMaterial.new()
	add.blend_mode = CanvasItemMaterial.BLEND_MODE_ADD
	_glow.material = add
	_glow.draw.connect(func(): line.draw_glow(_glow))
	add_child(_glow)
	_ink = Node2D.new()
	_ink.name = "Ink"
	_ink.draw.connect(func(): line.draw_ink(_ink))
	add_child(_ink)


## Redraws the line in the current text style and size (tools/dmd_mode.gd service_setting()).
func restyle() -> void:
	queue_redraw()
	_glow.queue_redraw()
	_ink.queue_redraw()


## Shows text s in ROM font id; line_ascent and line_height in dots (fonts.json ascent, ascent + descent);
## width: the ROM's text width in dots, align_flags: the ROM's alignment (both for the clean fonts).
func set_line(s: String, id: int, line_ascent: int, line_height: int, width := -1, align_flags := 0,
		from := 0, n := -1) -> void:
	if line.set_line(s, id, line_ascent, line_height, width, align_flags, from, n):
		restyle()


func _draw() -> void:
	line.draw_cell(self)


## One line of ROM text and how it is drawn, in three layers: draw_cell() (the black under the glyphs), draw_glow()
## (added: on a canvas item with an additive material) and draw_ink() (the lit dots). A RomTextHd node draws one on its
## own canvas items; tron/dmd_screen.gd draws every line of a display effect on three shared ones. xf places the
## line (its top left, its scale) on the item; mod multiplies its colours (the ROM's per-line level and blinking).
class Line extends RefCounted:
	var text := ""
	var font_id := 0
	var ascent := 0
	var font_size := 1
	var box_width := -1              # the ROM's text width in dots (-1: unknown, no fitting)
	var flags := 0                   # 2 = centred, 4 = right aligned, else left (tron/rom_text.gd rom_flags)
	var first := 0                   # clean fonts: only the characters first.. (count) of the line are drawn,
	var count := -1                  # where they sit in the whole line (-1: to the end)

	## As RomTextHd.set_line(); false when nothing changed.
	func set_line(s: String, id: int, line_ascent: int, line_height: int, width := -1, align_flags := 0,
			from := 0, n := -1) -> bool:
		if s == text and id == font_id and line_ascent == ascent and maxi(line_height, 1) == font_size \
				and width == box_width and align_flags == flags and from == first and n == count:
			return false
		first = from
		count = n
		text = s
		font_id = id
		ascent = line_ascent
		font_size = maxi(line_height, 1)
		box_width = width
		flags = align_flags
		return true

	## The clean font's placement: [font, origin (the baseline's left end), scale x, scale y] in dots, or [].
	func clean_layout() -> Array:
		var c := RomTextHd.clean()
		if c.is_empty() or text == "":
			return []
		var s := RomTextHd.text_scale()
		var cap := float(RomTextHd.info(font_id).get("cap", font_size))
		var base := float(ascent)
		var air := 1.0                     # a dot of air: clean letters reach their box's edges, ROM letters do not
		if RomTextHd.info(font_id).get("outline", false):
			cap -= 2.0                     # the ROM's cap counts the black border above and below the lit dots,
			base -= 1.0                    # whose bottom row is the baseline row
			air = 2.0
		var k := s * cap / (float(c["cap"]) * CLEAN_SIZE)
		var font: Font = c["font"]
		var w := font.get_string_size(text, HORIZONTAL_ALIGNMENT_LEFT, -1, CLEAN_SIZE).x * k
		var sx := k
		var room := s * (box_width - air)
		var x := 0.0
		if box_width > 0 and w > room:
			sx = k * room / w
			w = room
			x = (box_width - w) / 2.0
		elif box_width > 0:
			if flags & 2:
				x = (box_width - w) / 2.0
			elif flags & 4:
				x = box_width - w
		if first > 0:
			x += font.get_string_size(text.left(first), HORIZONTAL_ALIGNMENT_LEFT, -1, CLEAN_SIZE).x * sx
		return [font, Vector2(x, base - cap * (1.0 - s) / 2.0), sx, k]   # scaled about the capitals' middle

	## The characters drawn in the clean font: the whole line, or its part first.. (count).
	func shown_text() -> String:
		return text.substr(first, count) if first > 0 or count >= 0 else text

	func _draw_clean(item: CanvasItem, xf: Transform2D, color: Color, outline_dots: float) -> void:
		var l := clean_layout()
		if l.is_empty():
			return
		item.draw_set_transform_matrix(xf * Transform2D(0.0, Vector2(l[2], l[3]), 0.0, l[1]))
		if outline_dots > 0.0:
			item.draw_string_outline(RomTextHd.clean()["wide"], Vector2.ZERO, shown_text(), HORIZONTAL_ALIGNMENT_LEFT,
				-1, CLEAN_SIZE, maxi(1, roundi(2.0 * outline_dots / l[3])), color)
		else:
			item.draw_string(l[0], Vector2.ZERO, shown_text(), HORIZONTAL_ALIGNMENT_LEFT, -1, CLEAN_SIZE, color)
		item.draw_set_transform_matrix(xf)

	## The black under the glyphs (the ROM's cell; the clean fonts' outline).
	func draw_cell(item: CanvasItem, xf := Transform2D.IDENTITY, mod := Color.WHITE) -> void:
		if text == "":
			return
		item.draw_set_transform_matrix(xf)
		if not RomTextHd.clean().is_empty():
			_draw_clean(item, xf, Color(0, 0, 0, 1) * mod,
				OUTLINE_DOTS if RomTextHd.info(font_id).get("outline", false) else CELL_DOTS)
		else:
			item.draw_string(RomTextHd.vector_font(font_id), Vector2(0, ascent), RomTextHd.plane(text, CELL_PLANE),
				HORIZONTAL_ALIGNMENT_LEFT, -1, font_size, Color(0, 0, 0, 1) * mod)
		item.draw_set_transform_matrix(Transform2D.IDENTITY)

	## The glow (to be added to what is under it).
	func draw_glow(item: CanvasItem, xf := Transform2D.IDENTITY, mod := Color.WHITE) -> void:
		var st := RomTextHd.style()
		if text == "" or float(st["glow"]) <= 0.0:
			return
		item.draw_set_transform_matrix(xf)
		var g: Color = st["glow_color"] * float(st["glow"])
		g.a = 1.0
		if not RomTextHd.clean().is_empty():
			for r in [2.0, 1.5, 1.1, 0.75, 0.4]:   # widening outlines, added: soft light around the strokes
				_draw_clean(item, xf, Color(g.r * 0.3, g.g * 0.3, g.b * 0.3, 1) * mod, r)
		else:
			item.draw_string(RomTextHd.glow_font(font_id), Vector2(0, ascent), text, HORIZONTAL_ALIGNMENT_LEFT, -1,
				font_size, g * mod)
		item.draw_set_transform_matrix(Transform2D.IDENTITY)

	## The lit dots in the text colour (shaded fonts: one layer per level, brighter over dimmer).
	func draw_ink(item: CanvasItem, xf := Transform2D.IDENTITY, mod := Color.WHITE) -> void:
		if text == "":
			return
		item.draw_set_transform_matrix(xf)
		var color: Color = RomTextHd.style()["color"]
		var levels: Array = RomTextHd.info(font_id).get("levels", [15])
		if not RomTextHd.clean().is_empty():
			var top := float(levels.max()) / 15.0
			_draw_clean(item, xf, Color(color.r * top, color.g * top, color.b * top, 1) * mod, 0.0)
		else:
			var font := RomTextHd.vector_font(font_id)
			for k in levels.size():
				var lv := float(levels[k]) / 15.0
				var s := text if k == 0 else RomTextHd.plane(text, LEVEL_PLANE + 0x100 * k)
				item.draw_string(font, Vector2(0, ascent), s, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size,
					Color(color.r * lv, color.g * lv, color.b * lv, 1) * mod)
		item.draw_set_transform_matrix(Transform2D.IDENTITY)
