extends Node

## Performance probe (docs/performance.md), off unless TRON_PERF_DIR is set (scripts/perf/run.sh sets it). Read-only:
## it looks at the frames, the PuP screens and GDE GoZen's VideoPlayback nodes, and changes nothing. Writes:
##   frames.csv  t_ms,delta_ms,draw_ms     every frame: process start (ms since start), process delta, and the time
##                                          from process start to RenderingServer.frame_post_draw (draw submitted)
##   video.csv   t_ms,screen,file,frame,step,late_ms
##                                          every video frame shown (VideoPlayback.next_frame_called): the frame number,
##                                          how far it moved (1 = cadence kept, >1 = frames skipped) and how late it
##                                          came against its due time (frame / fps after the video's start)
##   av.csv      t_ms,screen,file,av_ms    once a second per playing video with its own audio: audio position minus
##                                          the shown frame's time (+ = audio ahead)
##   events.csv  t_ms,kind,screen,detail   video opens ("open"), black screens over 0.2 s ("black": a PuP window
##                                          where some layer should show a picture and none does)
##   memory.csv  t_ms,static_mb,video_mb,texture_mb   once a second: Godot's own memory monitors (static memory;
##                                          video memory and the textures' share of it)

const PLAYBACK_SCRIPT := "video_playback.gd"

var _dir := ""
var _frames: FileAccess
var _video: FileAccess
var _av: FileAccess
var _events: FileAccess
var _memory: FileAccess
var _t0 := 0
var _frame_start := 0
var _line_open := false  # a frames.csv line waits for its draw time
var _next_second := 1000
var _players := {}      # VideoPlayback -> {screen, path, start_ms, last}
var _black := {}        # PuP screen number -> black since (ms)


func _ready() -> void:
	_dir = OS.get_environment("TRON_PERF_DIR")
	if _dir == "":
		set_process(false)
		return
	process_priority = 100000          # after every VideoPlayback has stepped this frame
	process_mode = Node.PROCESS_MODE_ALWAYS
	DirAccess.make_dir_recursive_absolute(_dir)
	_frames = _open("frames.csv", "t_ms,delta_ms,draw_ms")
	_video = _open("video.csv", "t_ms,screen,file,frame,step,late_ms")
	_av = _open("av.csv", "t_ms,screen,file,av_ms")
	_events = _open("events.csv", "t_ms,kind,screen,detail")
	_memory = _open("memory.csv", "t_ms,static_mb,video_mb,texture_mb")
	_t0 = Time.get_ticks_usec()
	get_tree().node_added.connect(_on_node_added)
	RenderingServer.frame_post_draw.connect(_on_post_draw)
	print("PerfProbe: writing to ", _dir)


func _open(name: String, header: String) -> FileAccess:
	var f := FileAccess.open(_dir.path_join(name), FileAccess.WRITE)
	f.store_line(header)
	return f


func _ms() -> float:
	return (Time.get_ticks_usec() - _t0) / 1000.0


func _on_node_added(node: Node) -> void:
	var script = node.get_script()
	if script != null and str(script.resource_path).ends_with(PLAYBACK_SCRIPT):
		_players[node] = {"screen": _screen_of(node), "path": "", "start_ms": 0.0, "last": -1}
		node.next_frame_called.connect(_on_video_frame.bind(node))
		node.tree_exiting.connect(func(): _players.erase(node))


## The PuP screen number of a VideoPlayback (its pup_screen.gd ancestor's "number"), or -1.
func _screen_of(node: Node) -> int:
	var n := node.get_parent()
	while n != null:
		if "number" in n and "audio_only" in n:
			return int(n.number)
		n = n.get_parent()
	return -1


func _on_video_frame(frame: int, node: Node) -> void:
	var st: Dictionary = _players[node]
	var t := _ms()
	var fps: float = node._frame_rate
	var path: String = node.path
	if path != st.path or frame < st.last or st.last < 0:
		if path != st.path:
			_events.store_line("%.1f,open,%d,%s" % [t, st.screen, path.get_file().replace(",", " ")])
		st.path = path
		st.start_ms = t - (frame / fps * 1000.0 if fps > 0.0 else 0.0)
		st.last = frame - 1
	var late: float = t - st.start_ms - (frame / fps * 1000.0 if fps > 0.0 else 0.0)
	_video.store_line("%.1f,%d,%s,%d,%d,%.1f" % [t, st.screen, path.get_file().replace(",", " "), frame,
			frame - st.last, late])
	st.last = frame


func _process(delta: float) -> void:
	_frame_start = Time.get_ticks_usec()
	var t := _ms()
	var second := t >= _next_second
	if second:
		_next_second += 1000
	for node in _players:
		var st: Dictionary = _players[node]
		if second and node.is_playing and node._frame_rate > 0.0 and node.enable_audio \
				and node.audio_player.playing and node.audio_player.stream != null:
			var apos: float = node.audio_player.get_playback_position() + AudioServer.get_time_since_last_mix() \
					- AudioServer.get_output_latency()   # the sound heard now
			_av.store_line("%.1f,%d,%s,%.1f" % [t, st.screen, str(node.path).get_file().replace(",", " "),
					(apos - node.current_frame / node._frame_rate) * 1000.0])
	_check_black(t)
	if second:
		_memory.store_line("%.1f,%.1f,%.1f,%.1f" % [t, Performance.get_monitor(Performance.MEMORY_STATIC) / 1048576.0,
				Performance.get_monitor(Performance.RENDER_VIDEO_MEM_USED) / 1048576.0,
				Performance.get_monitor(Performance.RENDER_TEXTURE_MEM_USED) / 1048576.0])
		for f in [_frames, _video, _av, _events, _memory]:
			f.flush()
	_frames.store_line("%.1f,%.3f," % [t, delta * 1000.0])   # draw_ms is filled in by _on_post_draw
	_line_open = true


func _on_post_draw() -> void:
	# complete the line just stored with the draw time (seek back over its trailing newline)
	if not _line_open:
		return
	_line_open = false
	var draw_ms := (Time.get_ticks_usec() - _frame_start) / 1000.0
	_frames.seek(_frames.get_position() - 1)
	_frames.store_line("%.3f" % draw_ms)


## A PuP window is black when one of its layers should show something (a foreground or the background runs) and
## no layer of that window shows a picture (a layer still opening lets the one under it show through).
func _check_black(t: float) -> void:
	var pup = get_node_or_null("/root/Pup")
	if pup == null or not ("screens" in pup):
		return
	var lit := {}
	var wants := {}
	for n in pup.screens:
		var sc = pup.screens[n]
		if not is_instance_valid(sc) or sc.audio_only or not sc.is_visible_in_tree():
			continue
		var win = sc.get_window()
		var showing: bool = sc._image != null and sc._image.visible and sc._image.texture != null
		var v = sc._video
		if v != null and v.visible and ("_playback" in v) and v._playback != null:
			showing = showing or (v._playback.video_texture.visible and v._playback.y_texture != null)
		if showing:
			lit[win] = true
		if v != null and v.visible and (sc.fg != null or sc.bg_playing):
			wants[n] = win
	for n in wants:
		if not lit.has(wants[n]):
			if not _black.has(n):
				_black[n] = t
		elif _black.has(n):
			_end_black(n, t)
	for n in _black.keys():
		if not wants.has(n):
			_end_black(n, t)


func _end_black(n: int, t: float) -> void:
	var dur: float = t - _black[n]
	_black.erase(n)
	if dur > 200.0:
		_events.store_line("%.1f,black,%d,%.0f ms" % [t, n, dur])


func _exit_tree() -> void:
	for f in [_frames, _video, _av, _events, _memory]:
		if f != null:
			f.flush()
