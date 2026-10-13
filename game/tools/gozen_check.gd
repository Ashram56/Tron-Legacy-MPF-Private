extends SceneTree

## Checks GDE GoZen's video decoding on this PC (docs/pup/README.md), without the game: opens a few PuP Pack videos one
## after another, decodes up to FRAMES frames of each as fast as it can, and says per video whether the GPU decoded
## it (NV12 frames: Direct3D 11 Video / DXVA2 on Windows, the Jetson's decoder) and how fast, against the video's
## own frame rate. scripts/pup/video_check.py runs it on the GPU and then in software (GOZEN_HWDEC=0).
##   godot --headless --path game -s res://tools/gozen_check.gd -- [--out FILE] [VIDEO...]

const FRAMES := 300
const VIDEOS := ["Background - Backglass/TronLegacyBG.mp4", "AttractMode/AttractMode-Trailer1.mp4",
		"Background - Topper/TronLegacyLogo.mp4", "CluMode/CLU Mode Default.mp4"]

var _lines: PackedStringArray = []


func _init() -> void:
	var args := OS.get_cmdline_user_args()
	var out := ""
	var videos: Array[String] = []
	var i := 0
	while i < args.size():
		if args[i] == "--out" and i + 1 < args.size():
			out = args[i + 1]
			i += 1
		else:
			videos.append(args[i])
		i += 1
	if videos.is_empty():
		var pack := _pack_dir()
		for v in VIDEOS:
			if FileAccess.file_exists(pack.path_join(v)):
				videos.append(pack.path_join(v))
	if not ClassDB.class_exists("GoZenVideo"):
		_say("GoZen is not loaded (game/addons/gde_gozen: run scripts/setup.py)")
	elif videos.is_empty():
		_say("no PuP Pack videos found (pup_pack/: run scripts/setup.py)")
	else:
		var hwdec := OS.get_environment("GOZEN_HWDEC")
		_say("GoZen on %s, %s, GOZEN_HWDEC=%s" % [OS.get_name(), OS.get_processor_name(),
				hwdec if hwdec else "(unset: GPU first)"])
		for path in videos:
			_check(path)
	if out:
		var f := FileAccess.open(out, FileAccess.WRITE)
		if f:
			f.store_string("\n".join(_lines) + "\n")
	quit()


func _pack_dir() -> String:
	var cfg := ConfigFile.new()
	var dir := "pup_pack/trn_174h"
	for path in ["res://pup.cfg", "res://pup.local.cfg"]:
		if cfg.load(path) == OK:
			dir = str(cfg.get_value("pup", "pack_dir", dir))
	return ProjectSettings.globalize_path("res://").path_join("..").path_join(dir).simplify_path()


func _check(path: String) -> void:
	var video: Object = ClassDB.instantiate("GoZenVideo")
	var t0 := Time.get_ticks_usec()
	video.open(path)
	var open_ms := (Time.get_ticks_usec() - t0) / 1000.0
	if not video.is_open():
		_say("%s: could not open" % path.get_file())
		return
	var frames := mini(FRAMES, maxi(1, video.get_frame_count() - 2))
	t0 = Time.get_ticks_usec()
	for n in frames:
		video.next_frame(false)
	var ms := (Time.get_ticks_usec() - t0) / 1000.0 / frames
	var fps: float = video.get_framerate()
	var res: Vector2i = video.get_actual_resolution()
	_say("%s: %dx%d %s, %s, open %.0f ms, %.1f ms per frame (%.1fx real time at %.0f fps)" % [
			path.get_file(), res.x, res.y, video.get_pixel_format(),
			"GPU (NV12)" if video.is_nv12() else "software", open_ms, ms,
			(1000.0 / fps) / maxf(ms, 0.001) if fps > 0 else 0.0, fps])


func _say(text: String) -> void:
	print(text)
	_lines.append(text)
