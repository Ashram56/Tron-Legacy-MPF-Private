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
##   glow         --dmd-text-glow=X             TRON_DMD_TEXT_GLOW        tron/dmd/text_glow        (0.8; 0 = none)
## (first match wins, left to right). The tint picks the default colours: blue #2a6cff (glow #22b8ff), or
## orange #ff730d (glow #ff9a3c), the classic DMD's.
## Text font (HD only): --dmd-font=NAME (or TRON_DMD_FONT, or tron/dmd/font): a clean font drawn in the ROM's
## place (tron/rom_text_hd.gd: same lines, same alignment, the ROM's letter height, never wider than the ROM's
## text): rajdhani (default), orbitron, godot (Godot's own default font) or a .ttf/.otf file; or rom (the ROM's
## dot fonts traced to smooth outlines, the look before the clean fonts).
## Text size (HD only, clean fonts): --dmd-text-scale=X (or TRON_DMD_TEXT_SCALE, or tron/dmd/text_scale), 0.5-1.5:
## 1 = capitals as tall as the ROM's and lines never wider than the ROM's text; default 0.85, a bit smaller,
## so stacked lines and the glow keep apart. Lines shrink about the middle of their capitals.
## Service menu (HD only): ADJUSTMENTS > DISPLAY ADJUSTMENTS sets TEXT GLOW and TEXT SIZE while the game runs
## (tron/settings.py DisplaySettings). MPF sends them as the machine variables dmd_text_glow and dmd_text_size
## (percent; -1 = the value chosen above at start), and every HD text line is redrawn at once.
## Dot-matrix look (HD only): --dmd-dots=N (or TRON_DMD_DOTS=N, or tron/dmd/dots): round dots, N per DMD
## dot along each axis (1 = the 128x32 grid of the real display, 2 = 256x64, ...); 0 = off (default).

const MEDIA := "res://media/dmd/"
const MEDIA_HD := "res://media/dmd_hd/"
const DOTS_SHADER := "res://tools/dmd_dots.gdshader"
const TINTS := {"blue": ["#2a6cff", "#22b8ff"], "orange": ["#ff730d", "#ff9a3c"]}
const DEFAULT_TINT := "blue"
const DEFAULT_TEXT_COLOR := "#2a6cff"
const DEFAULT_GLOW_COLOR := "#22b8ff"
const DEFAULT_GLOW := 0.8
const DEFAULT_FONT := "rajdhani"
const DEFAULT_TEXT_SCALE := 0.85

var mode := "classic"
var hd := false
var dots := 0
var frame_scale := 8
var text_color := Color(DEFAULT_TEXT_COLOR)
var glow_color := Color(DEFAULT_GLOW_COLOR)
var glow := DEFAULT_GLOW
var font := DEFAULT_FONT
var text_scale := DEFAULT_TEXT_SCALE
var _start_glow := DEFAULT_GLOW            # the glow and text scale chosen at start (args, environment, project),
var _start_text_scale := DEFAULT_TEXT_SCALE   # which the service menu's settings replace while they are set
var _frames_hd := {}
var _frame_text = null           # media/dmd_hd/text.json: the recorded frames' text lines (FrameText)
var _frame_shapes = null         # media/dmd_hd/shapes.json: the frames drawn as rectangles (FrameText)
const LetterPanel := preload("res://tron/letter_panel.gd")
const DmdSlide := preload("res://tron/dmd_slide.gd")
const DmdEffectSlide := preload("res://tron/dmd_effect_slide.gd")
const PRELOAD_IN_FLIGHT := 8       # background loads running at once (more would queue ahead of the game's own)
var _preload: Array[String] = []    # resources loading in the background (_start_preload)
var _to_preload: Array[String] = []   # resources not requested yet, in effect order
var _preload_start := 0
var _letters: Array[String] = []
var _preloaded: Array[Resource] = []   # the preloaded ones: holding them keeps them in Godot's resource cache
var _to_warm: Array[SpriteFrames] = []   # preloaded scenes' sprite frames whose HD frames are not built yet (_warm_scene)


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


## The HD text font (first match wins): the user arg --dmd-font=, TRON_DMD_FONT, tron/dmd/font, rajdhani.
static func choose_font(args: PackedStringArray, env_font: String, setting: String) -> String:
	var values: Array = []
	for a in args:
		if a.begins_with("--dmd-font="):
			values.append(a.trim_prefix("--dmd-font="))
	values += [env_font, setting]
	for v in values:
		var f := str(v).strip_edges()
		if f != "":
			return f if f.get_extension().to_lower() in ["ttf", "otf", "woff", "woff2"] else f.to_lower()
	return DEFAULT_FONT


## The clean fonts' size (first valid match wins): --dmd-text-scale=, TRON_DMD_TEXT_SCALE, tron/dmd/text_scale,
## 0.85; clamped to 0.5-1.5.
static func choose_text_scale(args: PackedStringArray, env_scale: String, setting: String) -> float:
	var values: Array = []
	for a in args:
		if a.begins_with("--dmd-text-scale="):
			values.append(a.trim_prefix("--dmd-text-scale="))
	values += [env_scale, setting]
	for v in values:
		var t := str(v).strip_edges()
		if t.is_valid_float() and t.to_float() > 0.0:
			return clampf(t.to_float(), 0.5, 1.5)
	return DEFAULT_TEXT_SCALE


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
	text_scale = choose_text_scale(args, OS.get_environment("TRON_DMD_TEXT_SCALE"),
		str(ProjectSettings.get_setting("tron/dmd/text_scale", "")))
	_start_glow = glow
	_start_text_scale = text_scale
	font = choose_font(args, OS.get_environment("TRON_DMD_FONT"), str(ProjectSettings.get_setting("tron/dmd/font", "")))
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
	print("DMD: hd mode, window %s%s, text %s in %s x%.2f, glow %s x%.2f" % [root.size,
		(", dot-matrix look %d" % dots) if dots > 0 else "", text_color.to_html(false), font, text_scale, glow_color.to_html(false),
		glow])


func _ready() -> void:
	set_process(false)
	tree_exiting.connect(DmdSlide.clear_pool)   # the effects' slides kept for reuse, freed at exit
	if hd and font != "rom":
		preload("res://tron/rom_text_hd.gd").load_baked(font)
	if hd:
		_start_preload()
		_follow_service_settings.call_deferred()
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


## The service menu's DISPLAY ADJUSTMENTS (MPF machine variables, sent by GMC's machine variable monitor).
func _follow_service_settings() -> void:
	var mpf = get_tree().root.get_node_or_null("MPF")
	if mpf == null or mpf.game == null:
		return
	mpf.game.machine_update.connect(service_setting)
	for k in ["dmd_text_glow", "dmd_text_size"]:
		if mpf.game.machine_vars.has(k):
			service_setting(k, mpf.game.machine_vars[k])


## A DISPLAY ADJUSTMENTS value: dmd_text_glow / dmd_text_size in percent, < 0 = the start value. Redraws the
## HD text lines (tron/rom_text_hd.gd) when it changes; the ZUSE/TRON letters take the glow when next shown.
func service_setting(var_name: String, value) -> void:
	if not (var_name in ["dmd_text_glow", "dmd_text_size"]) or not str(value).is_valid_float():
		return
	var v := str(value).to_float()
	if var_name == "dmd_text_glow":
		var g := _start_glow if v < 0.0 else clampf(v / 100.0, 0.0, 4.0)
		if g == glow:
			return
		glow = g
	else:
		var s := _start_text_scale if v < 0.0 else clampf(v / 100.0, 0.5, 1.5)
		if s == text_scale:
			return
		text_scale = s
	print("DMD: service menu %s %s: glow x%.2f, text x%.2f" % [var_name, value, glow, text_scale])
	get_tree().call_group("dmd_hd_text", "restyle")   # tron/rom_text_hd.gd GROUP


## The large display effects (at least tron/dmd/preload_min_frames HD frames; 0 = none), their HD frames and their
## slide scenes, loaded on worker threads from the start. A slide is created on Godot's main thread when MPF shows its
## effect, and loading 300 frames there stalled the game a second or more (docs/performance.md); with the frames
## already in Godot's resource cache, the slide's load() calls return at once.
## The letter pictures (solid*, hollow*) are loaded the same way, whatever their effect's size, and their glows made
## on worker threads (tron/letter_panel.gd start_glow()).
## Then, with tron/dmd/preload_small (default on), every other effect the same way, after the large ones: a small
## slide's scene, read from disk and dropped from the cache once the slide was removed, cost 35-50 ms at each show,
## and building its HD frames 50-70 ms more the first time (Xavier NX: a 0.1-0.15 s hitch at about 40% of the
## slides shown, docs/performance.md). Each preloaded scene's HD frames are built once, as soon as it is loaded
## (_warm_scene()), so a slide shown later finds them made.
func _start_preload() -> void:
	var min_frames := int(ProjectSettings.get_setting("tron/dmd/preload_min_frames", 40))
	var small := bool(ProjectSettings.get_setting("tron/dmd/preload_small", true)) and min_frames > 0
	var glows := float(text_style()["glow"]) > 0.0
	var later: Array[String] = []
	var data := DmdEffectSlide.renderer() == "data"
	var seen := {}
	for d in DirAccess.get_directories_at(MEDIA_HD):
		var paths: Array[String] = []
		if data:          # the pictures its data names (frames shared between effects load once), and its slide
			for path in _data_pictures(MEDIA + d + "/effect.json"):
				if seen.has(path):
					continue
				seen[path] = true
				var f := path.get_file()
				if glows and (f.begins_with("solid") or f.begins_with("hollow")):
					_letters.append(path)
				elif not (f.begins_with("solid") or f.begins_with("hollow")):
					paths.append(path)
			paths.append("res://slides/deffs/%s.tscn" % d)
			if min_frames > 0 and paths.size() > min_frames:
				_to_preload.append_array(paths)
			elif small:
				later.append_array(paths)
			continue
		for f in DirAccess.get_files_at(MEDIA_HD + d):
			f = f.trim_suffix(".import")          # an exported game lists the .import files
			var path := MEDIA_HD + d + "/" + f
			if not f.ends_with(".png") or path in paths or path in _letters:
				continue
			if f.begins_with("f"):
				paths.append(path)                # effect frames
			elif glows and (f.begins_with("solid") or f.begins_with("hollow")):
				_letters.append(path)
		var scene := MEDIA + d + "/nodes.tscn"           # tron/dmd/renderer="nodes": the effect's node scene
		if ResourceLoader.exists(scene):
			paths.append(scene)
		if min_frames > 0 and paths.size() > min_frames:
			_to_preload.append_array(paths)
		elif small:
			later.append_array(paths)
	_to_preload = _letters + _to_preload + later
	_preload_start = Time.get_ticks_msec()
	set_process(not _to_preload.is_empty())


## The pictures an effect's data names (tron/dmd_effect.gd), as drawn: in HD their media/dmd_hd/ twins.
func _data_pictures(effect_path: String) -> Array[String]:
	var out: Array[String] = []
	for it in DmdEffectSlide.DmdEffect.items_of(effect_path):
		var pics: Array = []
		match it["type"]:
			"frames":
				pics = it["frames"].map(func(f): return f[0])
			"letters":
				pics = it["sprites"].map(func(sp): return sp["pic"])
		for p in pics:
			var big := MEDIA_HD + str(p).trim_prefix(MEDIA) if str(p).begins_with(MEDIA) else str(p)
			out.append(big if ResourceLoader.exists(big) else str(p))
	return out


func _process(_delta: float) -> void:
	# at most PRELOAD_IN_FLIGHT at a time, in effect order: a slide the game shows meanwhile loads its own resources
	# without waiting behind thousands of queued ones (with every effect requested at once, the first effect of a
	# game waited 2.5 s)
	while _preload.size() < PRELOAD_IN_FLIGHT and not _to_preload.is_empty():
		var p: String = _to_preload.pop_front()
		if ResourceLoader.load_threaded_request(p) == OK:
			_preload.append(p)
	# a few finished loads per frame; taking a finished load is cheap
	var i := 0
	var taken := 0
	while i < _preload.size() and taken < 32:
		var status := ResourceLoader.load_threaded_get_status(_preload[i])
		if status == ResourceLoader.THREAD_LOAD_IN_PROGRESS:
			i += 1
			continue
		if status == ResourceLoader.THREAD_LOAD_LOADED:
			_preloaded.append(ResourceLoader.load_threaded_get(_preload[i]))
			if _preload[i] in _letters:
				LetterPanel.start_glow(_preloaded[-1])
			elif _preloaded[-1] is PackedScene:
				_warm_scene(_preloaded[-1])
			taken += 1
		_preload.remove_at(i)                    # loaded, or failed (the slide then loads it itself)
	if _warm_ready() and _preload.is_empty() and _to_preload.is_empty():
		set_process(false)
		print("DMD: %d effect frames and scenes preloaded in %.1f s" % [_preloaded.size(),
				(Time.get_ticks_msec() - _preload_start) / 1000.0])


## Builds the HD frames of a preloaded slide scene's sprites (_hd_frames(), cached by the scene's own SpriteFrames),
## so showing the slide only looks them up. Its HD pictures were preloaded before it (same effect, same queue).
## A SpriteFrames whose HD pictures are still loading waits in _to_warm (a load() of one of them here would block
## the main thread until its worker finished).
func _warm_scene(scene: PackedScene) -> void:
	var state := scene.get_state()
	for n in state.get_node_count():
		for p in state.get_node_property_count(n):
			var v = state.get_node_property_value(n, p)
			if v is SpriteFrames and not _frames_hd.has(v):
				_to_warm.append(v)


## Builds the waiting HD frames whose pictures are all in the cache; true when none waits.
func _warm_ready() -> bool:
	var i := 0
	while i < _to_warm.size():
		var frames: SpriteFrames = _to_warm[i]
		var cached := true
		for anim in frames.get_animation_names():
			for f in frames.get_frame_count(anim):
				var tex := frames.get_frame_texture(anim, f)
				if tex and tex.resource_path.begins_with(MEDIA) and not ResourceLoader.has_cached(
						MEDIA_HD + tex.resource_path.trim_prefix(MEDIA)) and ResourceLoader.exists(
						MEDIA_HD + tex.resource_path.trim_prefix(MEDIA)):
					cached = false
					break
			if not cached:
				break
		if cached or (_preload.is_empty() and _to_preload.is_empty()):   # all loads done: build it anyway
			_hd_frames(frames)
			_to_warm.remove_at(i)
		else:
			i += 1
	return _to_warm.is_empty()


## The HD twin of a classic DMD picture, or null.
func hd_texture(tex: Texture2D) -> Texture2D:
	if tex == null or not tex.resource_path.begins_with(MEDIA):
		return null
	var path := MEDIA_HD + tex.resource_path.trim_prefix(MEDIA)
	return load(path) if ResourceLoader.exists(path) else null


func _hd_frames(frames: SpriteFrames) -> SpriteFrames:
	if _frames_hd.has(frames):
		return _frames_hd[frames]
	var out := SpriteFrames.new()
	var complete := true
	for anim in frames.get_animation_names():
		if not out.has_animation(anim):
			out.add_animation(anim)
		out.set_animation_loop(anim, frames.get_animation_loop(anim))
		out.set_animation_speed(anim, frames.get_animation_speed(anim))
		for i in frames.get_frame_count(anim):
			var tex := frames.get_frame_texture(anim, i)
			var big := hd_texture(tex)
			complete = complete and big != null
			out.add_frame(anim, big if big else tex, frames.get_frame_duration(anim, i))
	_frames_hd[frames] = out if complete else frames
	return _frames_hd[frames]


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
			sprite.scale = sprite.scale / frame_scale
			if _has_frame_text(sprite.sprite_frames):
				_add_frame_text.call_deferred(sprite)
	elif node is Sprite2D:
		var s := node as Sprite2D
		var big := hd_texture(s.texture)
		if big:
			s.texture = big
			s.scale = s.scale / frame_scale


## The text lines found in the recorded frames (scripts/frame_text.py): {"deff_NNN/fNNN.png": [[text, font id,
## x, baseline, level, width, first shown, count shown], ...]}. Their HD frames have those letters cleared;
## FrameText draws them.
func frame_text() -> Dictionary:
	if _frame_text == null:
		_frame_text = _load_json(MEDIA_HD + "text.json")
	return _frame_text


## The effects whose pictures are only rectangles (scripts/frame_text.py shapes): {"deff_NNN/fNNN.png":
## [[x0, y0, x1, y1, level, filled], ...]}, cleared from their HD frames and drawn by FrameText.
func frame_shapes() -> Dictionary:
	if _frame_shapes == null:
		_frame_shapes = _load_json(MEDIA_HD + "shapes.json")
	return _frame_shapes


static func _load_json(path: String) -> Dictionary:
	if FileAccess.file_exists(path):
		var data = JSON.parse_string(FileAccess.get_file_as_string(path))
		if data is Dictionary:
			return data
	return {}


static func frame_key(tex: Texture2D) -> String:
	return tex.resource_path.trim_prefix(MEDIA_HD) if tex else ""


func _has_frame_text(frames: SpriteFrames) -> bool:
	var lines := frame_text()
	var rects := frame_shapes()
	for anim in frames.get_animation_names():
		for i in frames.get_frame_count(anim):
			var key := frame_key(frames.get_frame_texture(anim, i))
			if lines.has(key) or rects.has(key):
				return true
	return false


func _add_frame_text(sprite: AnimatedSprite2D) -> void:
	if not is_instance_valid(sprite) or sprite.get_parent() == null or sprite.has_meta("dmd_frame_text"):
		return
	sprite.set_meta("dmd_frame_text", true)
	var overlay := FrameText.new(sprite, frame_text(), frame_shapes(), frame_scale)
	sprite.add_sibling(overlay)


## The text of a recorded effect, drawn live over its HD frames (whose letters are cleared): for the frame
## the sprite shows, one tron/rom_text_hd.gd line per text line found in it, at the ROM's place and level,
## centred on the recorded line (so the clean fonts' scale shrinks it in place; a line against the DMD's edge
## stays against it); a line the frame shows only
## part of (letters covered by the art, or not yet drawn) shows those letters where they sit in the line.
## Effects whose pictures are only rectangles (frames, blocks, bars) get them drawn as rectangles, sharp at
## any size, in the text colour at their level.
class FrameText extends Node2D:
	const RomText = preload("res://tron/rom_text.gd")
	const RomTextHd = preload("res://tron/rom_text_hd.gd")
	var sprite: AnimatedSprite2D
	var lines: Dictionary
	var rects: Dictionary
	var _key := "-"

	func _init(of: AnimatedSprite2D, text_lines: Dictionary, shapes: Dictionary, frame_scale: int) -> void:
		sprite = of
		lines = text_lines
		rects = shapes
		name = sprite.name + "Text"
		position = sprite.position
		scale = sprite.scale * frame_scale
		sprite.frame_changed.connect(_sync)
		sprite.animation_changed.connect(_sync)
		sprite.visibility_changed.connect(_sync)

	func _ready() -> void:
		_sync()

	func _draw() -> void:
		var color: Color = RomTextHd.style()["color"]
		for r in rects.get(_key, []):
			var lv := float(r[4]) / 15.0
			var c := Color(color.r * lv, color.g * lv, color.b * lv, 1)
			var box := Rect2(float(r[0]), float(r[1]), float(r[2]) - float(r[0]) + 1, float(r[3]) - float(r[1]) + 1)
			if int(r[5]):
				draw_rect(box, c)
			else:                       # a one-dot frame
				draw_rect(Rect2(box.position, Vector2(box.size.x, 1)), c)
				draw_rect(Rect2(box.position + Vector2(0, box.size.y - 1), Vector2(box.size.x, 1)), c)
				draw_rect(Rect2(box.position + Vector2(0, 1), Vector2(1, box.size.y - 2)), c)
				draw_rect(Rect2(box.position + Vector2(box.size.x - 1, 1), Vector2(1, box.size.y - 2)), c)

	func _sync() -> void:
		visible = sprite.visible
		var tex := sprite.sprite_frames.get_frame_texture(sprite.animation, sprite.frame) if sprite.sprite_frames else null
		var key := tex.resource_path.trim_prefix(MEDIA_HD) if tex else ""
		if key == _key:
			return
		_key = key
		queue_redraw()
		for c in get_children():
			c.queue_free()
		var clean := not RomTextHd.clean().is_empty()
		for l in lines.get(key, []):
			var m := RomText.font_metrics(int(l[1]))
			if m.is_empty():
				continue
			var whole := str(l[0])
			var from := int(l[6])
			var n := int(l[7])
			var ascent := int(m["ascent"])
			var line := Node2D.new()
			line.position = Vector2(float(l[2]), float(l[3]) - ascent + 1)
			var lv := float(l[4]) / 15.0
			line.modulate = Color(lv, lv, lv, 1)
			var hd: Node2D = RomTextHd.new()
			line.add_child(hd)
			if clean:          # aligned as the recorded line: against an edge of the DMD, else centred on it
				var align := 4 if int(l[2]) + int(l[5]) >= 127 else (0 if int(l[2]) <= 1 else 2)
				hd.set_line(whole, int(l[1]), ascent, ascent + int(m["descent"]), int(l[5]), align, from, n)
			else:              # the ROM's dot font: the part shown, where the ROM draws it
				var part := whole.substr(from, n)
				if from > 0:
					line.position.x += RomText.rom_width(m, whole.left(from)) + int(m["spacing"])
				hd.set_line(part, int(l[1]), ascent, ascent + int(m["descent"]), RomText.rom_width(m, part), 0)
			if l.size() > 9:   # a zoomed line (scripts/frame_text.py ZOOMS): about its middle, clipped
				var z := float(l[8])
				var left := float(l[9])
				var mid := line.position + Vector2(float(l[5]) / 2.0, ascent - int(m["cap"]) / 2.0)
				line.position = mid + (line.position - mid) * z - Vector2(left, 0)
				line.scale = Vector2(z, z)
				var clip := Control.new()
				clip.clip_contents = true
				clip.mouse_filter = Control.MOUSE_FILTER_IGNORE
				clip.position = Vector2(left, 0)
				clip.size = Vector2(128 - left, 32)
				clip.add_child(line)
				add_child(clip)
				continue
			add_child(line)


## A plain label on the DMD (game/slides/text_page.tscn: attract pages, initials entry): the text colour, and
## the glow drawn behind it (LabelGlow).
func _style_label(label: Label) -> void:
	if label.has_meta("dmd_glow_copy") or label.has_meta("dmd_text_hd") or label.has_meta("dmd_styled"):
		return
	label.set_meta("dmd_styled", true)     # once: a reused slide (tron/dmd_slide.gd) enters the tree again
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
