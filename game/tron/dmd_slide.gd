extends MPFSlide
## A display effect's slide (game/slides/deffs/, scripts/gen_media.py), kept for its next show instead of freed.
## GMC builds a new node tree from the slide's scene at every show and frees it at its removal; on a Xavier NX that
## cost about 12 ms to build and 25 ms more in its first drawn frame (new canvas items, text shaped again,
## docs/performance.md). Removed, this slide leaves the tree and waits in a pool (POOL_PER_SLIDE per effect, so an
## effect restarted while its last show is still on screen finds one too); GMC's media.get_slide_instance()
## (patched by scripts/gmc_patch.py) takes it back, reset to its start: every node with a pool_reset() method
## (tron/rom_text.gd, score_display.gd, letter_panel.gd, arcade_reel.gd) back to time 0 and its first values, the
## effect's animation back to its first frame. Off with tron/dmd/pool_slides=false or TRON_DMD_POOL=0 (measuring).

const POOL_PER_SLIDE := 2

static var _pool: Dictionary = {}       # slide name -> Array of removed slides, ready to show again
static var _enabled = null
static var _reused := 0                  # shows served from the pool, and shows that built a new slide (logged at exit)
static var _built := 0

var _pool_name := ""


## Whether removed slides are kept (tron/dmd/pool_slides, default on; TRON_DMD_POOL=0 turns it off).
static func enabled() -> bool:
	if _enabled == null:
		_enabled = bool(ProjectSettings.get_setting("tron/dmd/pool_slides", true)) \
			and OS.get_environment("TRON_DMD_POOL") != "0"
	return _enabled


## A kept slide of that name, reset to its start, or null (GMC then builds a new one).
static func take(slide_name: String) -> MPFSlide:
	var kept: Array = _pool.get(slide_name, [])
	while not kept.is_empty():
		var slide = kept.pop_back()
		if is_instance_valid(slide):
			slide.request_ready()          # GMC's initialize() waits for the slide's ready signal again
			slide.remove_meta("persisted")
			slide.reset()
			_reused += 1
			return slide
	_built += 1
	return null


## Keeps a removed slide for its next show; false when the pool for its name is full (it is freed then).
static func give(slide: MPFSlide) -> bool:
	if not enabled() or slide.get("_pool_name") in [null, ""]:
		return false
	var kept: Array = _pool.get_or_add(slide._pool_name, [])
	if kept.size() >= POOL_PER_SLIDE or slide in kept:
		return slide in kept
	kept.append(slide)
	return true


## The number of slides kept (tests, the performance probe).
static func pooled() -> int:
	var n := 0
	for kept in _pool.values():
		n += kept.size()
	return n


## Frees every kept slide (at exit, tests) and logs how many shows reused one.
static func clear_pool() -> void:
	if _reused + _built > 0:
		print("DMD: slide pool: %d shows reused a slide, %d built one, %d kept" % [_reused, _built, pooled()])
	for kept in _pool.values():
		for slide in kept:
			if is_instance_valid(slide):
				slide.free()
	_pool.clear()


func initialize(n: String, settings: Dictionary, c: String, p: int = 0, kwargs: Dictionary = {}) -> void:
	_pool_name = n
	super(n, settings, c, p, kwargs)


## Back to the state of a slide just built from its scene: every timed node at time 0 with no values yet, the
## effect's animation at its first frame (playing again when the scene autoplays it).
func reset() -> void:
	_reset_node(self)


static func _reset_node(node: Node) -> void:
	for child in node.get_children():
		if child is AnimatedSprite2D:
			var sprite := child as AnimatedSprite2D
			sprite.stop()
			if sprite.sprite_frames and sprite.sprite_frames.has_animation(sprite.animation):
				sprite.set_frame_and_progress(0, 0.0)
			if sprite.autoplay != "":
				sprite.play(sprite.autoplay)
		if child.has_method("pool_reset"):
			child.pool_reset()
		_reset_node(child)


## As GMC's remove(), but the slide waits in the pool instead of being freed. Its updaters (the text lines, the
## status panel) unregister themselves when they leave the tree and register only once, in their _ready(): they
## are kept for the next show.
func remove(with_animation: bool = true) -> void:
	if with_animation and _trigger_animation(CoreAnimation.REMOVED):
		await animation_player.animation_finished
	if current_animation in [CoreAnimation.CREATED, CoreAnimation.ACTIVE]:
		animation_player.stop()
	elif current_animation == CoreAnimation.REMOVED:
		return
	var kept := {}                     # this slide's updaters, and those of a slide scene shown inside it
	for s in [self] + find_children("*", "", true, false):
		if s is MPFSceneBase:
			kept[s] = s._updaters.duplicate()
	if get_parent():
		get_parent().remove_child(self)
	for s in kept:
		s._updaters = kept[s]
	if not give(self):
		queue_free()
