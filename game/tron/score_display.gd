extends Node
## Drives the score display slide (deff 19) like the ROM's deff_019 (0x01023a98) and its status panel
## (deff_draw_status_panel 0x010230ec). Values come from tron/media_bridge.py as event args:
##   line0 "BALL n", line1 score, credits ("CREDITS 0 1/3", "FREE PLAY"), replay ("REPLAY AT ..."),
##   p1..p4 player scores, players, player (current), valid (playfield validated),
##   award (last points shown under the current score) with award_age / blink_age in ticks,
##   bar_ds, bar_bumpers, bar_spinners (TRON target timers, 0-10), bar_zfs, bar_clu, bar_gem (0-10).
## Timing in ROM ticks; the bottom line rotates 156 ticks BALL/credits, 312 ticks replay level (when
## there is one), 1250 ticks BALL/credits, ... Before the playfield is valid the current score blinks
## (blanked 7 of every 14 ticks once 63 ticks passed without new points). The last points fade from
## level 13 to 0 over 26 ticks. Seekable for scripts/render_diff.py (seek_ms).

## score_lines: the slide is the score display itself (bottom-line rotation, blinking main score);
## without it only the status panel is driven (effects that draw deff_draw_status_panel).
@export var score_lines := false
## match_panel: the match effect's panel (FUN_0102cc48): every player score at level 2, the separator
## at level 15, no dashes or timer bars.
@export var match_panel := false

const TICK_MS := 15.41           # ROM tick as the deff 19 capture runs (its 7-tick blink = 107.9 ms frames)

var _elapsed_ms := 0.0
var _seeked := false
var _values := {}
var _received_ms := 0.0          # slide time of the last update (ages count from there)


func _ready() -> void:
	add_to_group("rom_timed")
	MPF.util.find_parent_slide_or_widget(self).register_updater(self)
	_tint_panel()
	_apply()


## HD mode (tools/dmd_mode.gd): the panel's separator, dashes and timer bars in the DMD text colour, as its
## text (tron/rom_text.gd), at the same levels.
func _tint_panel() -> void:
	var dmd = get_tree().root.get_node_or_null("DmdMode")
	if not (dmd and dmd.hd):
		return
	for node in get_parent().get_children():
		if node is ColorRect and node.name != "Background":
			(node as ColorRect).color = dmd.text_tint((node as ColorRect).color)


func _exit_tree() -> void:
	var slide = MPF.util.find_parent_slide_or_widget(self)
	if slide:
		slide.remove_updater(self)


func update(settings: Dictionary, kwargs: Dictionary = {}) -> void:
	for k in kwargs:
		_values[k] = kwargs[k]
	_received_ms = _elapsed_ms
	_apply()


## Back to time 0 with no values (tron/dmd_slide.gd reuses slides).
func pool_reset() -> void:
	_elapsed_ms = 0.0
	_seeked = false
	_values = {}
	_received_ms = 0.0
	_apply()


func seek_ms(t: float) -> void:
	_seeked = true
	_elapsed_ms = t
	_apply()


func _process(delta: float) -> void:
	if not _seeked:
		_elapsed_ms += delta * 1000.0
		_apply()


func _int(key: String, default := 0) -> int:
	var v = _values.get(key, default)
	return int(v) if v != null and str(v) != "" else default


func _node(n: String) -> CanvasItem:
	return get_parent().get_node_or_null(n)


## Ticks of the bottom-line rotation: false while BALL n / credits show, true while the replay line shows.
static func replay_phase(ticks: int) -> bool:
	if ticks < 156:
		return false
	var t := (ticks - 156) % (312 + 1250)
	return t < 312


func _apply() -> void:
	var ticks := int(_elapsed_ms / TICK_MS)
	var since := int((_elapsed_ms - _received_ms) / TICK_MS)
	var players := maxi(_int("players", 1), 1)
	var current := _int("player", 1)
	# bottom line
	var replay := str(_values.get("replay", ""))
	var alt := replay != "" and replay_phase(ticks)
	if score_lines:
		for n in ["Line0", "Credits"]:
			if _node(n):
				_node(n).visible = not alt
		if _node("Replay"):
			_node("Replay").visible = alt
	# blink of the current score before the playfield is valid
	var blink_age := _int("blink_age", 0) + since
	var blank := not bool(_values.get("valid", true)) and blink_age >= 63 and (blink_age - 62) % 14 <= 6
	if score_lines and _node("Line1"):
		_node("Line1").visible = not blank
	# player scores in the panel: current player full, the others dim (level 3)
	for p in range(1, 5):
		var node := _node("P%d" % p)
		if not node:
			continue
		node.visible = p <= players and not (blank and p == current)
		node.rom_y = 21 if p == 2 and players == 2 else p * 8 - 3
		node.modulate = Color(1, 1, 1, 1) if p == current else Color(0.2, 0.2, 0.2, 1)
		if match_panel:
			node.visible = p <= players
			node.modulate = Color(2 / 15.0, 2 / 15.0, 2 / 15.0, 1)
		node._layout()
	if match_panel:
		(_node("Separator") as ColorRect).modulate = Color(15, 15, 15, 1)
		for n in ["Award", "Dash0", "Dash1", "Dash2", "BarDs", "BarBumpers", "BarSpinners", "BarZfs", "BarClu", "BarGem"]:
			if _node(n):
				_node(n).visible = false
		return
	# last points, fading, under the current player's score (one or two players only)
	var award := _node("Award")
	if award:
		var age := _int("award_age", 99) + since
		award.visible = players < 3 and _int("award", 0) != 0 and age < 26
		award.rom_y = 13 if current == 1 else current * 8 + 13
		award.modulate = Color(((26 - age) >> 1) / 15.0, ((26 - age) >> 1) / 15.0, ((26 - age) >> 1) / 15.0, 1)
		award._layout()
	# timer bars: TRON target awards on the bottom row, hurry-ups on the separator column
	for b in [["BarDs", "bar_ds"], ["BarBumpers", "bar_bumpers"], ["BarSpinners", "bar_spinners"]]:
		var bar := _node(b[0]) as ColorRect
		if bar:
			bar.size.x = clampi(_int(b[1]), 0, 10)
	for b in [["BarZfs", "bar_zfs", 10], ["BarClu", "bar_clu", 21], ["BarGem", "bar_gem", 32]]:
		var bar := _node(b[0]) as ColorRect
		if bar:
			var n := clampi(_int(b[1]), 0, 10)
			bar.size.y = n
			bar.position.y = b[2] - n
