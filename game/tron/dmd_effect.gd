extends RefCounted
## A display effect drawn from its data instead of a scene of nodes: media/dmd/<name>/effect.json (scripts/gen_media.py
## write_effect()), its items in drawing order, as the effect's node scene (media/dmd/<name>/nodes.tscn) has its nodes:
##   {"type": "rect", "name", "x", "y", "w", "h", "level", "color"}      a filled rectangle (Background, Clear*, panel)
##   {"type": "frames", "name", "loop", "frames": [[picture, ms], ...]}  the effect's pictures, each shown for ms
##   {"type": "letters", "sprites": [{"name", "pic", "x", "y", "level", "color", "letter"}], ...}   tron/letter_panel.gd
##   {"type": "arcade", "cabinets", "icons_a", "icons_b", "frame_ms"}    tron/arcade_reel.gd
##   {"type": "text", "name", "var", "font", "x", "y", "flags", ...}     a line of ROM text, tron/rom_text.gd's fields
##   {"type": "panel", "score_lines", "match"}                          tron/score_display.gd over the named items
## A picture is a res:// path: a picture of media/dmd/ is shown in HD as its twin of media/dmd_hd/ (tools/dmd_mode.gd);
## any other picture (redrawn art, a larger frame) is shown as it is, fitted to the 128x32 box. The data can be edited
## or replaced by hand: nothing else needs generating again.
##
## One State per show of the effect (tron/dmd_effect_slide.gd): its time, the values MPF sent, the lines' text; build()
## turns it into a draw list for tron/dmd_screen.gd, the same pixels the node scene draws (tests/test_dmd_hd.py). The
## logic is the node scripts' own, item for item (rom_text.gd, score_display.gd, letter_panel.gd, arcade_reel.gd).

const DmdEffect = preload("res://tron/dmd_effect.gd")
const RomText = preload("res://tron/rom_text.gd")
const RomTextHd = preload("res://tron/rom_text_hd.gd")
const LetterPanel = preload("res://tron/letter_panel.gd")
const ScoreDisplay = preload("res://tron/score_display.gd")
const ArcadeReel = preload("res://tron/arcade_reel.gd")
const MEDIA := "res://media/dmd/"
const MEDIA_HD := "res://media/dmd_hd/"
const DMD_COLOR := Color(1, 0.45, 0.05, 1)
const BOX := Rect2(0, 0, 128, 32)

static var _data: Dictionary = {}       # effect.json path -> its items (parsed once)


## The items of an effect's data ([] when it cannot be read).
static func items_of(path: String) -> Array:
	if not _data.has(path):
		var parsed = JSON.parse_string(FileAccess.get_file_as_string(path)) if FileAccess.file_exists(path) else null
		_data[path] = _ints(parsed.get("items", [])) if parsed is Dictionary else []
		if not parsed is Dictionary:
			push_warning("DMD effect %s: no data" % path)
	return _data[path]


## JSON's numbers are floats: whole ones become ints (flags, positions, fonts are used as ints).
static func _ints(v):
	if v is Array:
		return v.map(func(x): return _ints(x))
	if v is Dictionary:
		var out := {}
		for k in v:
			out[k] = _ints(v[k])
		return out
	if v is float and v == floorf(v) and absf(v) < 1e9:
		return int(v)
	return v


static func _dmd() -> Node:
	return (Engine.get_main_loop() as SceneTree).root.get_node_or_null("DmdMode")


## The picture drawn for a picture path: in HD its media/dmd_hd/ twin when there is one.
static func picture(path: String, hd: bool) -> Texture2D:
	if hd and path.begins_with(MEDIA):
		var big := MEDIA_HD + path.trim_prefix(MEDIA)
		if ResourceLoader.exists(big):
			return load(big)
	return load(path) if ResourceLoader.exists(path) else null


class State extends RefCounted:
	var items: Array
	var hd := false
	var elapsed_ms := 0.0
	var seeked := false
	var values := {}               # every event arg received (the panel, letters and reel read them)
	var received_ms := 0.0         # time of the last update (the panel's ages count from there)
	var texts := {}                # text item index -> its text
	var use_alt := {}              # text item index -> drawn at alt_x / alt_y
	var screen_on := {}            # text item index -> its screen is shown
	var _pictures := {}            # picture path -> texture (loaded once per show)
	var _durations := PackedFloat32Array()
	var _total_ms := 0.0
	var _frames_item := -1

	func _init(of: Array, hd_mode: bool) -> void:
		items = of
		hd = hd_mode
		for i in items.size():
			if items[i]["type"] == "frames":
				_frames_item = i
				for f in items[i]["frames"]:
					_durations.append(float(f[1]))
					_total_ms += float(f[1])
		reset()

	## Back to the start of a show: time 0, no values, no text (as a node scene just built).
	func reset() -> void:
		elapsed_ms = 0.0
		seeked = false
		values = {}
		received_ms = 0.0
		texts = {}
		use_alt = {}
		screen_on = {}
		for i in items.size():
			var it: Dictionary = items[i]
			if it["type"] == "text":
				texts[i] = ""
				use_alt[i] = false
				screen_on[i] = it.get("screens", []).has(0) if it.get("screens", []).size() else true

	func advance(delta: float) -> void:
		if not seeked:
			elapsed_ms += delta * 1000.0

	func seek_ms(t: float) -> void:
		seeked = true
		elapsed_ms = t

	## The event args of a show or an update (GMC's action_update), as each node script takes them.
	func update(settings: Dictionary, kwargs: Dictionary) -> void:
		for k in kwargs:
			values[k] = kwargs[k]
		received_ms = elapsed_ms
		for i in items.size():
			var it: Dictionary = items[i]
			if it["type"] != "text":
				continue
			if it.get("screens", []).size():           # tron/rom_text.gd update()
				var shown = kwargs.get("screen", settings.get("screen", null))
				if shown != null and str(shown) != "":
					screen_on[i] = it["screens"].has(int(shown))
			if it.get("alt_when_empty", "") != "":
				var other = kwargs.get(it["alt_when_empty"], settings.get(it["alt_when_empty"], ""))
				use_alt[i] = other == null or str(other) == ""
			var v = null                                 # MPFVariable update(): kwargs, tokens, settings
			var has := true
			if it["var"] in kwargs:
				v = kwargs[it["var"]]
			elif it["var"] in settings.get("tokens", {}):
				v = settings["tokens"][it["var"]]
			elif it["var"] in settings:
				v = settings[it["var"]]
			else:
				has = false
			if has:
				texts[i] = "" if v == null else ("%s" % v if (v is int or v is float) else str(v))

	func _int(key: String, default := 0) -> int:
		var v = values.get(key, default)
		return int(v) if v != null and str(v) != "" else default

	## The frame shown at the current time (AnimatedSprite2D's timing: each picture for its ms; a loop starts over).
	func frame_index() -> int:
		if _durations.is_empty() or _total_ms <= 0.0:
			return 0
		var t := elapsed_ms
		if items[_frames_item].get("loop", false):
			t = fmod(t, _total_ms)
		var acc := 0.0
		for i in _durations.size():
			acc += _durations[i]
			if t < acc:
				return i
		return _durations.size() - 1

	func _picture(path: String) -> Texture2D:
		if not _pictures.has(path):
			_pictures[path] = DmdEffect.picture(path, hd)
		return _pictures[path]

	## The draw list of the current time: what tron/dmd_screen.gd draws, in order. Lists are compared to redraw only
	## on a change, so they hold values, not objects made here.
	func build() -> Array:
		var dmd = DmdEffect._dmd()
		var text_color: Color = dmd.text_color if hd and dmd else Color.WHITE
		var out: Array = []
		var panel := _panel_state()
		for i in items.size():
			var it: Dictionary = items[i]
			match it["type"]:
				"rect":
					var r := Rect2(it["x"], it["y"], it["w"], it["h"])
					var c := Color(it["color"][0], it["color"][1], it["color"][2], 1)
					var mod := Color.WHITE
					var st: Dictionary = panel.get(it["name"], {})
					if st.has("visible") and not st["visible"]:
						continue
					if st.has("rect"):
						r = st["rect"]
					if st.has("mod"):
						mod = st["mod"]
					if hd and it["name"] != "Background":
						c = dmd.text_tint(c)
					if r.size.x > 0 and r.size.y > 0:
						out.append(["rect", r, c * mod])
				"frames":
					var f: Array = it["frames"][frame_index()] if it["frames"].size() else []
					var tex := _picture(f[0]) if f.size() else null
					if tex:
						out.append(["tex", tex, BOX, dmd.text_tint(DMD_COLOR) if hd else DMD_COLOR])
						if hd and tex.resource_path.begins_with(MEDIA_HD):
							_frame_text(out, tex.resource_path.trim_prefix(MEDIA_HD), dmd)
				"letters":
					_letters(out, it, dmd)
				"arcade":
					_arcade(out, it, dmd)
				"text":
					_text(out, i, it, panel.get(it["name"], {}))
		return out

	# ------------------------------------------------------------------ text (tron/rom_text.gd)

	func _timed(it: Dictionary) -> bool:
		return it.get("show_after_ms", 0) or it.get("hide_after_ms", 0) or it.get("blink_ms", 0) \
			or it.get("cycle_ms", 0) or it.get("level_steps", []).size()

	func _text(out: Array, i: int, it: Dictionary, st: Dictionary) -> void:
		var visible: bool = screen_on[i]
		var mod := Color.WHITE
		if _timed(it):                                    # rom_text.gd _apply_time()
			var show_after: int = it.get("show_after_ms", 0)
			var hide_after: int = it.get("hide_after_ms", 0)
			var blink: int = it.get("blink_ms", 0)
			var cycle: int = it.get("cycle_ms", 0)
			var blink_dark: bool = it.get("blink_dark", false)
			var blink_on := blink == 0 or int((elapsed_ms - show_after) / blink) % 2 == 0
			var cycle_on: bool = cycle == 0 or fposmod(elapsed_ms - it.get("cycle_offset_ms", 0), cycle) \
				< it.get("cycle_on_ms", 0)
			visible = screen_on[i] and cycle_on and elapsed_ms >= show_after \
				and (hide_after == 0 or elapsed_ms < hide_after) and (blink_on or blink_dark)
			if blink_dark:
				mod = Color(1, 1, 1, 1) if blink_on else Color(0, 0, 0, 1)
			var steps: Array = it.get("level_steps", [])
			var step: int = it.get("step_ms", 0)
			if steps.size() and step > 0:
				var level: float = steps[mini(int(elapsed_ms / step), steps.size() - 1)] / 15.0
				mod = Color(level, level, level, 1)
		if st.has("visible"):
			visible = st["visible"]
		if st.has("mod"):
			mod = st["mod"]
		if not visible:
			return
		var lay := _layout(i, it, st.get("rom_y", it["y"]))
		if lay.is_empty() or lay["text"] == "":
			return
		if hd:
			out.append(["htext", [lay["text"], lay["font"], lay["ascent"], lay["line_h"], lay["w"], it["flags"], 0, -1],
				Transform2D(0.0, lay["pos"]), mod, Rect2()])
		else:
			var font := RomText.font_file(lay["font"])
			out.append(["ctext", font, lay["text"], lay["pos"] + Vector2(0, font.get_ascent(lay["line_h"])),
				lay["line_h"], DMD_COLOR * mod])

	## rom_text.gd _layout(): the font (first of fit_fonts that fits), the text it can draw, the place.
	func _layout(i: int, it: Dictionary, rom_y: int) -> Dictionary:
		var text: String = texts[i]
		var font_id: int = it["font"]
		var y := rom_y
		var m := RomText.font_metrics(font_id)
		var shown := ""
		for c in text:
			if m.get("glyphs", {}).has(c):
				shown += c
		var fits: Array = it.get("fit_fonts", [])
		var fit_ys: Array = it.get("fit_ys", [])
		for k in fits.size():
			var fm := RomText.font_metrics(fits[k])
			var fs := ""
			for c in text:
				if fm["glyphs"].has(c):
					fs += c
			font_id = fits[k]
			m = fm
			shown = fs
			y = fit_ys[k] if k < fit_ys.size() else rom_y
			if RomText.rom_width(fm, fs) <= it.get("fit_width", 0):
				break
		if m.is_empty():
			return {}
		texts[i] = shown                                   # as the label keeps it
		var alt: bool = use_alt[i]
		var x: int = it.get("alt_x", 0) if alt else it["x"]
		if alt:
			y = it.get("alt_y", 0)
		var w := RomText.rom_width(m, shown)
		var left := x
		if it["flags"] & 2:
			left = x - w / 2
		elif it["flags"] & 4:
			left = x + 1 - w
		var ascent := int(m["ascent"])
		return {"text": shown, "font": font_id, "pos": Vector2(left, y - ascent + 1), "w": w, "ascent": ascent,
			"line_h": ascent + int(m["descent"])}

	# ------------------------------------------------------------------ status panel (tron/score_display.gd)

	## The panel's changes to its named items: {name: {"visible", "mod", "rom_y", "rect"}}.
	func _panel_state() -> Dictionary:
		var panel := {}
		for it in items:
			if it["type"] == "panel":
				panel = it
		if panel.is_empty():
			return {}
		var out := {}
		var ticks := int(elapsed_ms / ScoreDisplay.TICK_MS)
		var since := int((elapsed_ms - received_ms) / ScoreDisplay.TICK_MS)
		var players := maxi(_int("players", 1), 1)
		var current := _int("player", 1)
		var replay := str(values.get("replay", ""))
		var alt := replay != "" and ScoreDisplay.replay_phase(ticks)
		var score_lines: bool = panel.get("score_lines", false)
		var match_panel: bool = panel.get("match", false)
		if score_lines:
			out["Line0"] = {"visible": not alt}
			out["Credits"] = {"visible": not alt}
			out["Replay"] = {"visible": alt}
		var blink_age := _int("blink_age", 0) + since
		var blank := not bool(values.get("valid", true)) and blink_age >= 63 and (blink_age - 62) % 14 <= 6
		if score_lines:
			out["Line1"] = {"visible": not blank}
		for p in range(1, 5):
			var st := {"visible": p <= players and not (blank and p == current),
				"rom_y": 21 if p == 2 and players == 2 else p * 8 - 3,
				"mod": Color(1, 1, 1, 1) if p == current else Color(0.2, 0.2, 0.2, 1)}
			if match_panel:
				st["visible"] = p <= players
				st["mod"] = Color(2 / 15.0, 2 / 15.0, 2 / 15.0, 1)
			out["P%d" % p] = st
		if match_panel:
			out["Separator"] = {"mod": Color(15, 15, 15, 1)}
			for n in ["Award", "Dash0", "Dash1", "Dash2", "BarDs", "BarBumpers", "BarSpinners", "BarZfs", "BarClu",
					"BarGem"]:
				out[n] = {"visible": false}
			return out
		var age := _int("award_age", 99) + since
		var lv := ((26 - age) >> 1) / 15.0
		out["Award"] = {"visible": players < 3 and _int("award", 0) != 0 and age < 26,
			"rom_y": 13 if current == 1 else current * 8 + 13, "mod": Color(lv, lv, lv, 1)}
		for b in [["BarDs", "bar_ds", 4], ["BarBumpers", "bar_bumpers", 16], ["BarSpinners", "bar_spinners", 28]]:
			out[b[0]] = {"rect": Rect2(b[2], 31, clampi(_int(b[1]), 0, 10), 1)}
		for b in [["BarZfs", "bar_zfs", 10], ["BarClu", "bar_clu", 21], ["BarGem", "bar_gem", 32]]:
			var n := clampi(_int(b[1]), 0, 10)
			out[b[0]] = {"rect": Rect2(40, b[2] - n, 1, n)}
		return out

	# ------------------------------------------------------------------ letters (tron/letter_panel.gd)

	func _mask(key: String) -> int:
		if key == "":
			return 0
		var v = values.get(key, 0)
		return int(v) if v != null and str(v) != "" else 0

	func _letters(out: Array, it: Dictionary, dmd) -> void:
		var frame_ms: float = it["frame_ms"]
		var frame := int(elapsed_ms / frame_ms) if frame_ms > 0 else 0
		var lit := _mask(it["lit_key"])
		var fresh := _mask(it["new_key"])
		var st: Dictionary = {} if not hd else dmd.text_style()
		for s in it["sprites"]:
			var i := int(str(s["name"]).right(1))
			var state := LetterPanel.letter_state(i, lit, fresh, it["all_new"], frame, it["blink_shift"],
				it["solid_after"])
			if it["hide_after_ms"] > 0 and elapsed_ms >= it["hide_after_ms"]:
				state = ""
			if state != str(s["name"]).left(-1).to_lower():
				continue
			var tex := _picture(s["pic"])
			if tex == null:
				continue
			var classic := Color(s["color"][0], s["color"][1], s["color"][2], 1)
			var rect := Rect2(s["x"], s["y"], 0, 0)
			var dots := Vector2i((tex.get_size() / (float(dmd.frame_scale) if hd and tex.resource_path.begins_with(
				MEDIA_HD) else 1.0)).round())
			rect.size = Vector2(dots)
			if not hd:
				out.append(["tex", tex, rect, classic])
				continue
			var level: float = classic.r          # orange times the palette level: the level
			out.append(["tex", tex, rect, dmd.text_tint(Color(level, 0, 0, 1))])
			if float(st["glow"]) > 0.0:
				LetterPanel.start_glow(tex)
				var glow := LetterPanel.made_glow(tex)
				if glow:
					var g: Color = st["glow_color"] * (float(st["glow"]) * level)
					g.a = 1.0
					var m := float(LetterPanel.GLOW_DOTS)
					out.append(["glowtex", glow, Rect2(rect.position - Vector2(m, m), rect.size + Vector2(2 * m, 2 * m)), g])

	# ------------------------------------------------------------------ arcade reel (tron/arcade_reel.gd)

	func _arcade(out: Array, it: Dictionary, dmd) -> void:
		var frame := int(elapsed_ms / float(it["frame_ms"])) if float(it["frame_ms"]) > 0 else 0
		var slot := _int("slot", -1)
		var state := ArcadeReel.reel_state(frame, _int("scroll", 0), _int("blink", 0), 82, 4)
		var x: int = state[0]
		var blink_step: int = state[1]
		var color: Color = dmd.text_tint(DMD_COLOR) if hd else DMD_COLOR
		var icons_a: Array = it["icons_a"]
		var icons_b: Array = it["icons_b"]
		var cabinets: Array = it["cabinets"]
		for i in 3:
			var cab := _int("cab%d" % i, 0)
			var id := _int("icon%d" % i, 0)
			if id >= 1 and id <= icons_a.size() and id <= icons_b.size():
				var bright := blink_step < 0 or (i == slot and blink_step % 2 == 0)
				var icon := DmdEffect.picture(icons_a[id - 1] if bright else icons_b[id - 1], false)
				if icon:
					out.append(["tex", icon, Rect2(Vector2(x + 8, 5), icon.get_size()), color])
			var tex: Texture2D = DmdEffect.picture(cabinets[cab], false) if cab >= 0 and cab < cabinets.size() else null
			if tex:
				out.append(["tex", tex, Rect2(Vector2(x, 0), tex.get_size()), color])
				x += tex.get_width() + 5
			else:
				x += 45 + 5

	# ------------------------------------------------------------------ recorded text (tools/dmd_mode.gd FrameText)

	func _frame_text(out: Array, key: String, dmd) -> void:
		var color: Color = dmd.text_color
		for r in dmd.frame_shapes().get(key, []):
			var lv := float(r[4]) / 15.0
			var c := Color(color.r * lv, color.g * lv, color.b * lv, 1)
			var box := Rect2(float(r[0]), float(r[1]), float(r[2]) - float(r[0]) + 1, float(r[3]) - float(r[1]) + 1)
			if int(r[5]):
				out.append(["rect", box, c])
			else:                       # a one-dot frame
				out.append(["rect", Rect2(box.position, Vector2(box.size.x, 1)), c])
				out.append(["rect", Rect2(box.position + Vector2(0, box.size.y - 1), Vector2(box.size.x, 1)), c])
				out.append(["rect", Rect2(box.position + Vector2(0, 1), Vector2(1, box.size.y - 2)), c])
				out.append(["rect", Rect2(box.position + Vector2(box.size.x - 1, 1), Vector2(1, box.size.y - 2)), c])
		var clean := not RomTextHd.clean().is_empty()
		for l in dmd.frame_text().get(key, []):
			var m := RomText.font_metrics(int(l[1]))
			if m.is_empty():
				continue
			var whole := str(l[0])
			var from := int(l[6])
			var n := int(l[7])
			var ascent := int(m["ascent"])
			var pos := Vector2(float(l[2]), float(l[3]) - ascent + 1)
			var lv := float(l[4]) / 15.0
			var mod := Color(lv, lv, lv, 1)
			var params: Array
			if clean:          # aligned as the recorded line: against an edge of the DMD, else centred on it
				var align := 4 if int(l[2]) + int(l[5]) >= 127 else (0 if int(l[2]) <= 1 else 2)
				params = [whole, int(l[1]), ascent, ascent + int(m["descent"]), int(l[5]), align, from, n]
			else:              # the ROM's dot font: the part shown, where the ROM draws it
				var part := whole.substr(from, n)
				if from > 0:
					pos.x += RomText.rom_width(m, whole.left(from)) + int(m["spacing"])
				params = [part, int(l[1]), ascent, ascent + int(m["descent"]), RomText.rom_width(m, part), 0, 0, -1]
			if l.size() > 9:   # a zoomed line (scripts/frame_text.py ZOOMS): about its middle, clipped
				var z := float(l[8])
				var left := float(l[9])
				var mid := pos + Vector2(float(l[5]) / 2.0, ascent - int(m["cap"]) / 2.0)
				pos = mid + (pos - mid) * z
				out.append(["htext", params, Transform2D(0.0, Vector2(z, z), 0.0, pos), mod, Rect2(left, 0, 128 - left, 32)])
				continue
			out.append(["htext", params, Transform2D(0.0, pos), mod, Rect2()])
