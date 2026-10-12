extends "res://tron/dmd_slide.gd"
## A display effect's GMC slide (game/slides/deffs/<name>.tscn, scripts/gen_media.py): one node in GMC's slide stack,
## at the effect's priority, that keeps the effect's time and values (tron/dmd_effect.gd State) and shows the
## picture tron/dmd_screen.gd draws of the effect on top. Reused from show to show like every effect slide
## (tron/dmd_slide.gd).
## The effect is drawn from its data (effect, media/dmd/<name>/effect.json), unless:
##   - a custom scene res://dmd_custom/<name>.tscn exists: it is shown instead (any nodes; tron/rom_text.gd labels,
##     sprites, videos... register with this slide and get its event args, as in any GMC slide);
##   - tron/dmd/renderer is "nodes" (or TRON_DMD_RENDERER=nodes): the effect's node scene, media/dmd/<name>/nodes.tscn,
##     is shown instead (the way every effect was drawn before the data, kept to compare).

const DmdEffect = preload("res://tron/dmd_effect.gd")
const CUSTOM_DIR := "res://dmd_custom/"

@export var effect := ""

var state = null                    # DmdEffect.State when the effect is drawn from its data
var _scene: Node = null             # the custom or node scene shown instead


## "data" (default) or "nodes": tron/dmd/renderer, TRON_DMD_RENDERER.
static func renderer() -> String:
	var env := OS.get_environment("TRON_DMD_RENDERER").to_lower()
	if env in ["data", "nodes"]:
		return env
	return "nodes" if str(ProjectSettings.get_setting("tron/dmd/renderer", "data")).to_lower() == "nodes" else "data"


func _ready() -> void:
	if state != null or _scene != null:    # a reused slide (request_ready()): all made at its first show
		return
	add_to_group("rom_timed")
	var effect_name := effect.get_base_dir().get_file()
	var custom := CUSTOM_DIR + effect_name + ".tscn"
	var nodes := effect.get_base_dir() + "/nodes.tscn"
	if ResourceLoader.exists(custom):
		_scene = load(custom).instantiate()
	elif renderer() == "nodes" and ResourceLoader.exists(nodes):
		_scene = load(nodes).instantiate()
	if _scene:
		add_child(_scene)
		return
	var dmd = get_tree().root.get_node_or_null("DmdMode")
	state = DmdEffect.State.new(DmdEffect.items_of(effect), dmd != null and dmd.hd)
	if not state.hd:
		texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	add_to_group(preload("res://tron/dmd_screen.gd").GROUP)
	queue_redraw()


func action_update(settings: Dictionary, kwargs: Dictionary = {}) -> void:
	super(settings, kwargs)
	if _scene is MPFSceneBase:          # a node scene's own slide root: its labels registered with it
		_scene.action_update(settings, kwargs)
	if state:
		state.update(settings, kwargs)


func _process(delta: float) -> void:
	if state:
		state.advance(delta)


func seek_ms(t: float) -> void:
	if state:
		state.seek_ms(t)


func reset() -> void:
	super()
	if state:
		state.reset()


func _draw() -> void:
	var screen = get_tree().root.get_node_or_null("DmdScreen") if is_inside_tree() else null
	if state and screen:
		draw_texture_rect(screen.texture(), Rect2(0, 0, 128, 32), false)
