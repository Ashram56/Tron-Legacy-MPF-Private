extends Node3D
## Godot issue repro: with the separate render thread (project.godot, thread_model=2) the Vulkan pipeline cache is
## never written, so every start compiles every pipeline again.
## Run it twice. Each run prints whether user://vulkan holds a pipeline cache and the longest frame. At 2 s a
## burst of emissive particles and an omni light appear (new pipelines): a long frame on every start, and no cache
## file. With thread_model=1, or with rendering_device/pipeline_cache/save_chunk_size_mb=0.1, the file is written
## and the second run has no long frame.

var _t := 0.0
var _longest := 0.0
var _at := 0.0
var _burst := false
var _last := 0


func _ready() -> void:
	var files := DirAccess.get_files_at("user://vulkan") if DirAccess.dir_exists_absolute("user://vulkan") else PackedStringArray()
	print("project thread_model=%d (--render-thread overrides it), pipeline cache files at start: %s" % [ProjectSettings.get_setting("rendering/driver/threads/thread_model"), files])
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.glow_enabled = true
	env.fog_enabled = true
	var we := WorldEnvironment.new()
	we.environment = env
	add_child(we)
	var cam := Camera3D.new()
	cam.position = Vector3(0, 3, 8)
	add_child(cam)
	cam.look_at(Vector3.ZERO)
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-50, 30, 0)
	add_child(sun)
	var floor_mesh := MeshInstance3D.new()
	floor_mesh.mesh = PlaneMesh.new()
	floor_mesh.mesh.size = Vector2(20, 20)
	add_child(floor_mesh)
	_last = Time.get_ticks_usec()


func _burst_now() -> void:
	var boom := CPUParticles3D.new()
	boom.amount = 160
	boom.explosiveness = 1.0
	boom.spread = 180
	boom.initial_velocity_max = 6.0
	var bit := BoxMesh.new()
	bit.size = Vector3.ONE * 0.1
	boom.mesh = bit
	var m := StandardMaterial3D.new()
	m.emission_enabled = true
	m.emission = Color(0.2, 0.7, 1.0)
	m.emission_energy_multiplier = 4.0
	boom.material_override = m
	add_child(boom)
	var flash := OmniLight3D.new()
	flash.light_energy = 6.0
	flash.omni_range = 6.0
	add_child(flash)


func _process(delta: float) -> void:
	var now := Time.get_ticks_usec()
	var frame_ms := (now - _last) / 1000.0
	_last = now
	_t += delta
	if _t > 0.5 and frame_ms > _longest:
		_longest = frame_ms
		_at = _t
	if not _burst and _t >= 2.0:
		_burst = true
		_burst_now()
	if _t >= 5.0:
		print("longest frame after start-up: %.0f ms at %.1f s" % [_longest, _at])
		get_tree().quit()
