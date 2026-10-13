extends Node
## Renders GMC slides frame by frame for scripts/render_diff.py, without MPF:
##   godot --path game res://tools/slide_capture.tscn -- --job=/abs/job.json
## job.json: [{"slide": "deff_025", "kwargs": {"line1": "50,000"}, "times_ms": [0, 49, ...],
##             optional "scene": "res://slides/service.tscn" (a slide other than slides/deffs/<slide>.tscn),
##             optional "machine_vars": {"dmd_text_size": 100, ...} (MPF machine variables, as GMC receives
##             them, set once the slide is up: the service menu's DISPLAY ADJUSTMENTS),
##             optional "reuse_kwargs": {...} (the slide is first shown with these args, run to 3 s and removed, then
##             shown again from GMC's slide pool, tron/dmd_slide.gd: a reused slide must render as a new one),
##             "out": "/abs/dir"}, ...]. For each time the slide's animation is put on the frame
## showing at that time, timed nodes (group "rom_timed": tron/rom_text.gd, tron/score_display.gd) are
## put at that time, and the 128x32 viewport is saved as out/frame_NNNNN.png. Quits when done.

func _ready() -> void:
	var job_path := ""
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--job="):
			job_path = arg.trim_prefix("--job=")
	if not job_path:
		return
	_run(JSON.parse_string(FileAccess.get_file_as_string(job_path)))


func _run(jobs: Array) -> void:
	for job in jobs:
		DirAccess.make_dir_recursive_absolute(job["out"])
		var scene: String = job.get("scene", "res://slides/deffs/%s.tscn" % job["slide"])
		var slide = load(scene).instantiate()
		if job.has("reuse_kwargs") and slide.has_method("reset"):
			slide = await _shown_and_pooled(slide, job["slide"], job["reuse_kwargs"])
		slide.initialize(job["slide"], {"key": job["slide"]}, "capture", 0, job.get("kwargs", {}))
		add_child(slide)
		var mvars: Dictionary = job.get("machine_vars", {})
		for k in mvars:
			MPF.game.update_machine({"name": k, "value": mvars[k]})
		var anim: AnimatedSprite2D = slide.find_child("Anim", true, false)
		if anim:
			anim.pause()
		var n := 0
		for t in job["times_ms"]:
			if anim:
				anim.frame = _frame_at(anim, float(t))
			get_tree().call_group("rom_timed", "seek_ms", float(t))
			await RenderingServer.frame_post_draw
			await RenderingServer.frame_post_draw
			get_viewport().get_texture().get_image().save_png("%s/frame_%05d.png" % [job["out"], n])
			n += 1
		slide.queue_free()
		await get_tree().process_frame
	get_tree().quit()


## The slide shown once with kwargs, run for 3 s and removed into the slide pool, then taken back from it.
func _shown_and_pooled(slide: Node, slide_name: String, kwargs: Dictionary) -> Node:
	slide.initialize(slide_name, {"key": slide_name}, "capture", 0, kwargs)
	add_child(slide)
	await get_tree().process_frame
	get_tree().call_group("rom_timed", "seek_ms", 3000.0)
	var anim: AnimatedSprite2D = slide.find_child("Anim", true, false)
	if anim:
		anim.frame = anim.sprite_frames.get_frame_count(anim.animation) - 1
	await RenderingServer.frame_post_draw
	slide.remove(false)
	var again = slide.take(slide_name)
	assert(again == slide, "slide pool: the removed slide was not kept")
	return again


func _frame_at(anim: AnimatedSprite2D, t: float) -> int:
	var frames := anim.sprite_frames
	var count := frames.get_frame_count("default")
	var loop := frames.get_animation_loop("default")
	var total := 0.0
	for i in count:
		total += frames.get_frame_duration("default", i)
	if total <= 0.0:
		return 0
	if loop:
		t = fmod(t, total)
	var acc := 0.0
	for i in count:
		acc += frames.get_frame_duration("default", i)
		if t < acc:
			return i
	return count - 1
