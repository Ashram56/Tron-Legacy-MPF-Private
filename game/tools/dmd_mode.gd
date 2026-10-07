extends Node
## DMD display mode: "classic" (the ROM's 128x32 dots, scaled up by whole pixels: exactly the ROM output)
## or "hd" (the same 128x32 layout drawn at the window's resolution: smooth HD fonts and upscaled effect
## frames, made by scripts/gen_fonts.py and scripts/gen_media.py with scripts/dmd_hd.py).
##
## Chosen, first match wins:
##   1. --proc-dmd (the P-ROC feeds the machine's own 128x32 DMD): always classic;
##   2. the user arg --dmd=hd|classic   (godot --path game -- --dmd=classic; scripts/run.py --dmd classic);
##   3. render captures (--job=, slide_capture; --capture-dir=, render_check): classic, so the ROM checks
##      compare dots;
##   4. the environment variable TRON_DMD=hd|classic;
##   5. the project setting tron/dmd/mode (game/project.godot, default "hd").
## In classic mode this node does nothing at all: the output is the 128x32 picture as before.
##
## HD mode: the window's content scale mode becomes canvas_items (2D drawn at the window's resolution,
## kept at the 4:1 aspect), textures are filtered, tron/rom_text.gd draws the text from the ROM fonts'
## vector outlines (fonts/hd/, tron/rom_text_hd.gd), and every sprite showing a picture of media/dmd/ shows
## its twin of media/dmd_hd/ (same name), scaled down to the same 128x32 footprint.
## Colour (HD only): the DMD is Tron blue instead of the original orange. Every DMD text (ROM text lines, the
## score display, the service menu, the ZUSE/TRON letters, the attract and initials pages) is drawn in the
## text colour, and the effect frames tinted orange in the classic look take the same colour, level for
## level. Optionally with a soft glow around the text:
##   tint         --dmd-tint=blue|orange        TRON_DMD_TINT             tron/dmd/tint             (blue)
##   colour       --dmd-text-color=#RRGGBB      TRON_DMD_TEXT_COLOR       tron/dmd/text_color       (the tint's)
##   glow colour  --dmd-text-glow-color=#RRGGBB TRON_DMD_TEXT_GLOW_COLOR  tron/dmd/text_glow_color  (the tint's)
##   glow         --dmd-text-glow=X             TRON_DMD_TEXT_GLOW        tron/dmd/text_glow        (0 = none)
## (first match wins, left to right). The tint picks the default colours: blue #2a6cff (glow #22b8ff), or
## orange #ff730d (glow #ff9a3c), the classic DMD's.
## Animation colour (HD only): --dmd-color=on|off (scripts/run.py --dmd-color; or TRON_DMD_COLOR=on|off, or the project
## setting tron/dmd/color, default "on"). On, the effects' animation frames show their colour twins of
## media/dmd_hd_color/ (scripts/dmd_color.py: each effect's 16 shades mapped to a palette inspired by the
## PuP-Pack video of that moment; 2x, 256x64, made with Scale2x, drawn with nearest filtering) untinted;
## off, the grey HD frames in the DMD colour above. Text drawn live (tron/rom_text.gd, score_display.gd) keeps
## the colour above. The sprites with a colour twin there (the ZUSE/TRON letters of letter_panel.gd, the
## arcade reel's cabinets and icons: the Serum colourisation's colours) show it instead, untinted.
## Dot-matrix look (HD only): --dmd-dots=N (or TRON_DMD_DOTS=N, or tron/dmd/dots): round dots, N per DMD
## dot along each axis (1 = the 128x32 grid of the real display, 2 = 256x64, ...); 0 = off (default).

const MEDIA := "res://media/dmd/"
const MEDIA_HD := "res://media/dmd_hd/"
const MEDIA_COLOR := "res://media/dmd_hd_color/"
const DOTS_SHADER := "res://tools/dmd_dots.gdshader"
const TINTS := {"blue": ["#2a6cff", "#22b8ff"], "orange": ["#ff730d", "#ff9a3c"]}
const DEFAULT_TINT := "blue"
const DEFAULT_TEXT_COLOR := "#2a6cff"
const DEFAULT_GLOW_COLOR := "#22b8ff"
const DEFAULT_GLOW := 0.0

var mode := "classic"
var hd := false
var dots := 0
var color := false
var frame_scale := 8
var color_scale := 2
var text_color := Color(DEFAULT_TEXT_COLOR)
var glow_color := Color(DEFAULT_GLOW_COLOR)
var glow := DEFAULT_GLOW
var _frames_hd := {}
var _colored := {}


static func choose(args: PackedStringArray, env_mode: String, setting: String) -> String:
	if "--proc-dmd" in args:
		return "classic"
	for a in args:
		if a.begins_with("--dmd="):
			var m := a.trim_prefix("--dmd=").to_lower()
			if m in ["hd", "classic"]:
				return m
	for a in args:
		if a.begins_with("--job=") or a.begins_with("--capture-dir="):
			return "classic"
	if env_mode.to_lower() in ["hd", "classic"]:
		return env_mode.to_lower()
	return "hd" if setting.to_lower() == "hd" else "classic"


## HD colour on or off: --dmd-color=on|off, then TRON_DMD_COLOR, then the project setting.
static func choose_color(args: PackedStringArray, env_color: String, setting: String) -> bool:
	for a in args:
		if a.begins_with("--dmd-color="):
			var c := a.trim_prefix("--dmd-color=").to_lower()
			if c in ["on", "off"]:
				return c == "on"
	if env_color.to_lower() in ["on", "off"]:
		return env_color.to_lower() == "on"
	return setting.to_lower() != "off"


## The text style from the user args, the environment and the project settings (first match wins): {"tint",
## "color", "glow_color", "glow"}. Invalid values are skipped.
static func choose_text_style(args: PackedStringArray, env: Dictionary, settings: Dictionary) -> Dictionary:
	var tint := DEFAULT_TINT
	var tints: Array = []
	for a in args:
		if a.begins_with("--dmd-tint="):
			tints.append(a.trim_prefix("--dmd-tint="))
	tints += [env.get("TRON_DMD_TINT", ""), settings.get("tron/dmd/tint", "")]
	for t in tints:
		if str(t).strip_edges().to_lower() in TINTS:
			tint = str(t).strip_edges().to_lower()
			break
	var out := {"tint": tint}
	for spec in [["color", "--dmd-text-color=", "TRON_DMD_TEXT_COLOR", "tron/dmd/text_color", TINTS[tint][0]],
			["glow_color", "--dmd-text-glow-color=", "TRON_DMD_TEXT_GLOW_COLOR", "tron/dmd/text_glow_color",
				TINTS[tint][1]],
			["glow", "--dmd-text-glow=", "TRON_DMD_TEXT_GLOW", "tron/dmd/text_glow", DEFAULT_GLOW]]:
		var values: Array = []
		for a in args:
			if a.begins_with(spec[1]):
				values.append(a.trim_prefix(spec[1]))
		values += [env.get(spec[2], ""), settings.get(spec[3], ""), spec[4]]
		for v in values:
			var text := str(v).strip_edges()
			if spec[0] == "glow":
				if text.is_valid_float():
					out["glow"] = clampf(text.to_float(), 0.0, 4.0)
					break
			elif Color.html_is_valid(text):
				out[spec[0]] = Color.html(text)
				break
	return out


## The DMD text style (tron/rom_text_hd.gd and the text drawers): {"color", "glow_color", "glow"}.
func text_style() -> Dictionary:
	return {"color": text_color, "glow_color": glow_color, "glow": glow}


## A DMD colour of the classic look (orange times a palette level) in the HD text colour, same level.
func text_tint(classic: Color) -> Color:
	var level := classic.r
	return Color(text_color.r * level, text_color.g * level, text_color.b * level, classic.a)


## Whether a modulate is the classic look's tint (gen_media.py DMD_COLOR, orange times a palette level).
static func is_classic_tint(c: Color) -> bool:
	return c.r > 0.0 and absf(c.g - 0.45 * c.r) < 0.01 and absf(c.b - 0.05 * c.r) < 0.01


func _enter_tree() -> void:
	var args := OS.get_cmdline_user_args()
	mode = choose(args, OS.get_environment("TRON_DMD"),
		str(ProjectSettings.get_setting("tron/dmd/mode", "hd")))
	hd = mode == "hd" and FileAccess.file_exists("res://fonts/hd/fonts_hd.json")
	if mode == "hd" and not hd:
		push_warning("DMD: HD media not generated (scripts/gen_media.py), showing the classic DMD")
		mode = "classic"
	if not hd:
		return
	dots = int(ProjectSettings.get_setting("tron/dmd/dots", 0))
	if OS.get_environment("TRON_DMD_DOTS").is_valid_int():
		dots = int(OS.get_environment("TRON_DMD_DOTS"))
	for a in args:
		if a == "--dmd-dots":
			dots = 2
		elif a.begins_with("--dmd-dots="):
			dots = int(a.trim_prefix("--dmd-dots="))
	color = choose_color(args, OS.get_environment("TRON_DMD_COLOR"),
		str(ProjectSettings.get_setting("tron/dmd/color", "on"))) \
		and FileAccess.file_exists(MEDIA_COLOR + "palettes.json")
	if color:
		var cinfo = JSON.parse_string(FileAccess.get_file_as_string(MEDIA_COLOR + "palettes.json"))
		if cinfo is Dictionary:
			color_scale = int(cinfo.get("scale", color_scale))
	var env := {}
	for k in ["TRON_DMD_TINT", "TRON_DMD_TEXT_COLOR", "TRON_DMD_TEXT_GLOW_COLOR", "TRON_DMD_TEXT_GLOW"]:
		env[k] = OS.get_environment(k)
	var settings := {}
	for k in ["tron/dmd/tint", "tron/dmd/text_color", "tron/dmd/text_glow_color", "tron/dmd/text_glow"]:
		settings[k] = ProjectSettings.get_setting(k, "")
	var st := choose_text_style(args, env, settings)
	text_color = st["color"]
	glow_color = st["glow_color"]
	glow = st["glow"]
	if FileAccess.file_exists(MEDIA_HD + "scale.json"):
		var info = JSON.parse_string(FileAccess.get_file_as_string(MEDIA_HD + "scale.json"))
		if info is Dictionary:
			frame_scale = int(info.get("scale", frame_scale))
	var root := get_tree().root
	root.content_scale_mode = Window.CONTENT_SCALE_MODE_CANVAS_ITEMS
	root.content_scale_aspect = Window.CONTENT_SCALE_ASPECT_KEEP
	root.content_scale_stretch = Window.CONTENT_SCALE_STRETCH_FRACTIONAL
	root.canvas_item_default_texture_filter = Viewport.DEFAULT_CANVAS_ITEM_TEXTURE_FILTER_LINEAR_WITH_MIPMAPS
	get_tree().node_added.connect(_on_node_added)
	print("DMD: hd mode, window %s%s%s, text %s glow %s x%.2f" % [root.size, ", colour" if color else "",
		(", dot-matrix look %d" % dots) if dots > 0 else "", text_color.to_html(false), glow_color.to_html(false), glow])


func _ready() -> void:
	if hd and dots > 0:
		var layer := CanvasLayer.new()
		layer.layer = 128
		var rect := ColorRect.new()
		rect.mouse_filter = Control.MOUSE_FILTER_IGNORE
		rect.size = Vector2(128, 32)
		var mat := ShaderMaterial.new()
		mat.shader = load(DOTS_SHADER)
		mat.set_shader_parameter("grid", Vector2(128 * dots, 32 * dots))
		rect.material = mat
		layer.add_child(rect)
		add_child(layer)


## The HD twin of a classic DMD picture (its colour twin with in_color, when there is one), or null.
func hd_texture(tex: Texture2D, in_color := false) -> Texture2D:
	if tex == null or not tex.resource_path.begins_with(MEDIA):
		return null
	var rel := tex.resource_path.trim_prefix(MEDIA)
	if in_color and ResourceLoader.exists(MEDIA_COLOR + rel):
		return load(MEDIA_COLOR + rel)
	var path := MEDIA_HD + rel
	return load(path) if ResourceLoader.exists(path) else null


## The colour twin of a classic DMD sprite (letters, the arcade reel: scripts/dmd_color.py sprite_build, in the
## Serum colourisation's colours, color_scale times larger), or null when the colour is off or it has none.
func color_texture(tex: Texture2D) -> Texture2D:
	if not (hd and color) or tex == null or not tex.resource_path.begins_with(MEDIA):
		return null
	var path := MEDIA_COLOR + tex.resource_path.trim_prefix(MEDIA)
	return load(path) if ResourceLoader.exists(path) else null


## The HD frames of an effect animation: all in colour (color on and every frame has its colour twin), else
## all grey; the classic frames when an HD twin is missing.
func _hd_frames(frames: SpriteFrames) -> SpriteFrames:
	if _frames_hd.has(frames):
		return _frames_hd[frames]
	if color:
		var colored := _twin_frames(frames, true)
		if colored != frames:
			_frames_hd[frames] = colored
			_colored[colored] = true
			return colored
	_frames_hd[frames] = _twin_frames(frames, false)
	return _frames_hd[frames]


func _twin_frames(frames: SpriteFrames, in_color: bool) -> SpriteFrames:
	var out := SpriteFrames.new()
	var complete := true
	for anim in frames.get_animation_names():
		if not out.has_animation(anim):
			out.add_animation(anim)
		out.set_animation_loop(anim, frames.get_animation_loop(anim))
		out.set_animation_speed(anim, frames.get_animation_speed(anim))
		for i in frames.get_frame_count(anim):
			var tex := frames.get_frame_texture(anim, i)
			var big := hd_texture(tex, in_color)
			if in_color and big and not big.resource_path.begins_with(MEDIA_COLOR):
				big = null
			complete = complete and big != null
			out.add_frame(anim, big if big else tex, frames.get_frame_duration(anim, i))
	return out if complete else frames


func _on_node_added(node: Node) -> void:
	if node is CanvasItem and is_classic_tint((node as CanvasItem).modulate):
		var item := node as CanvasItem
		item.set_meta("dmd_classic_tint", item.modulate)
		item.modulate = text_tint(item.modulate)
	if node is Label and not ("rom_font" in node):
		_style_label(node as Label)
	elif node is AnimatedSprite2D:
		var sprite := node as AnimatedSprite2D
		if sprite.sprite_frames and sprite.sprite_frames != _hd_frames(sprite.sprite_frames):
			sprite.sprite_frames = _hd_frames(sprite.sprite_frames)
			if _colored.has(sprite.sprite_frames):     # the colours are in the frames: no DMD tint
				sprite.scale = sprite.scale / color_scale
				sprite.modulate = Color(1, 1, 1, sprite.modulate.a)
				if color_scale <= 2:                   # 2x pixel art (Scale2x): crisp dots, not blurred
					sprite.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
			else:
				sprite.scale = sprite.scale / frame_scale
	elif node is Sprite2D:
		var s := node as Sprite2D
		var colored := color_texture(s.texture)
		if colored:                                    # its Serum colours: no DMD tint, crisp dots
			s.texture = colored
			s.scale = s.scale / color_scale
			s.modulate = Color(1, 1, 1, s.modulate.a)
			s.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
			return
		var big := hd_texture(s.texture)
		if big:
			s.texture = big
			s.scale = s.scale / frame_scale


## A plain label on the DMD (game/slides/text_page.tscn: attract pages, initials entry): the text colour, and
## the glow drawn behind it (LabelGlow).
func _style_label(label: Label) -> void:
	if label.has_meta("dmd_glow_copy") or label.has_meta("dmd_text_hd"):
		return
	label.add_theme_color_override("font_color", text_color)
	if glow > 0.0:
		label.add_child(LabelGlow.new(label, glow_color, glow), false, INTERNAL_MODE_FRONT)


## The glow of a plain label: its text drawn white into a small picture (a SubViewport, PX pixels per dot,
## redrawn when the text changes), blurred by tools/dmd_glow.gdshader and added behind the label.
class LabelGlow extends Node2D:
	const PX := 4
	const MARGIN := 4                  # dots of glow around the label's box
	const SHADER := "res://tools/dmd_glow.gdshader"
	var label: Label
	var _vp: SubViewport
	var _copy: Label

	func _init(of: Label, glow_color: Color, glow_strength: float) -> void:
		label = of
		name = "Glow"
		show_behind_parent = true
		var mat := ShaderMaterial.new()
		mat.shader = load(SHADER)
		mat.set_shader_parameter("glow_color", glow_color)
		mat.set_shader_parameter("strength", glow_strength)
		mat.set_shader_parameter("sigma", 0.9 * PX)
		material = mat
		_vp = SubViewport.new()
		_vp.transparent_bg = true
		_vp.disable_3d = true
		_vp.render_target_update_mode = SubViewport.UPDATE_ONCE
		_vp.canvas_transform = Transform2D.IDENTITY.scaled(Vector2(PX, PX))
		_copy = Label.new()
		_copy.set_meta("dmd_glow_copy", true)
		_vp.add_child(_copy)
		add_child(_vp)

	func _ready() -> void:
		label.draw.connect(_sync)
		_sync()

	func _sync() -> void:
		var box := label.size
		_vp.size = Vector2i(((box + Vector2.ONE * 2 * MARGIN) * PX).ceil())
		_copy.position = Vector2.ONE * MARGIN
		_copy.size = box
		_copy.text = label.text
		_copy.horizontal_alignment = label.horizontal_alignment
		_copy.vertical_alignment = label.vertical_alignment
		_copy.add_theme_font_override("font", label.get_theme_font("font"))
		_copy.add_theme_font_size_override("font_size", label.get_theme_font_size("font_size"))
		_copy.add_theme_color_override("font_color", Color.WHITE)
		_vp.render_target_update_mode = SubViewport.UPDATE_ONCE
		queue_redraw()

	func _draw() -> void:
		if label.text != "":
			draw_texture_rect(_vp.get_texture(), Rect2(-Vector2.ONE * MARGIN, label.size + Vector2.ONE * 2 * MARGIN), false)
