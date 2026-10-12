extends SubViewportContainer

## The DMD window's live background ([dmd] background="lightcycles", game/pup.cfg): a 3D grid where two
## 1982-style light cycles chase each other cell by cell. Their trails fade, a cycle that hits a live trail,
## a wall or the other cycle derezzes and comes back. pup_player.gd draws the DMD and its neon frame on top
## and gives the DMD's rectangle with set_dmd_rect(): the middle of the DMD is a wall, the rest of the cells
## behind it an avoid zone the cycles steer out of, and cells off the window are walls, so the chase stays
## in view around the DMD whatever the window's size.

const W := 48                # arena cells (x); cells off the window become walls
const H := 24                # arena cells (z)
const SPEED := 6.0           # cells per second
const FADE := 3.2            # seconds a trail lives
const WALL_H := 0.5
const RESPAWN := 2.2         # seconds a derezzed cycle stays away
const INSET := Vector2(0.137, 0.16)  # the wall is the DMD shrunk by this share of its size on each side
const BEHIND := 0.03          # the avoid zone reaches past the DMD by this share of its height
const AVOID := 3.0           # how hard the cycles steer out of the avoid zone
const COLORS := [Color(0.2, 0.75, 1.0), Color(1.0, 0.42, 0.04)]
const DIRS: Array[Vector2i] = [Vector2i.RIGHT, Vector2i.LEFT, Vector2i.UP, Vector2i.DOWN]

var _view: SubViewport
var _cam: Camera3D
var _dmd := Rect2()
var _blocked := {}           # walls: the middle of the DMD and the cells off the window
var _avoid := {}             # cell -> steps to the nearest open cell, for the cells behind the rest of the DMD
var _cells := {}             # cell -> [time laid, cycle index]
var _cycles := []
var _now := 0.0
var _rng := RandomNumberGenerator.new()


func _init() -> void:
	stretch = true
	mouse_filter = Control.MOUSE_FILTER_IGNORE


func _ready() -> void:
	_rng.randomize()
	_view = SubViewport.new()
	_view.own_world_3d = true
	_view.msaa_3d = Viewport.MSAA_2X
	add_child(_view)

	var e := Environment.new()
	e.background_mode = Environment.BG_COLOR
	e.background_color = Color(0, 0.005, 0.012)
	e.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	e.ambient_light_color = Color(0.15, 0.25, 0.35)
	e.ambient_light_energy = 0.6
	e.glow_enabled = true
	e.glow_intensity = 1.1
	e.glow_strength = 1.1
	e.glow_bloom = 0.08
	e.glow_blend_mode = Environment.GLOW_BLEND_MODE_ADDITIVE
	e.glow_hdr_threshold = 0.9
	e.set_glow_level(1, 1.0)
	e.set_glow_level(3, 1.0)
	e.set_glow_level(5, 0.6)
	e.fog_enabled = true
	e.fog_light_color = Color(0, 0.03, 0.06)
	e.fog_density = 0.02
	var env := WorldEnvironment.new()
	env.environment = e
	_view.add_child(env)
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-50, 30, 0)
	sun.light_energy = 0.8
	sun.light_color = Color(0.6, 0.8, 1.0)
	_view.add_child(sun)

	_cam = Camera3D.new()
	_cam.fov = 40
	_cam.position = Vector3(0, 10.0, 11.6)
	_view.add_child(_cam)
	_cam.look_at(Vector3(0, 0, 0.4))

	var floor_mesh := PlaneMesh.new()
	floor_mesh.size = Vector2(200, 200)
	var grid := ShaderMaterial.new()
	grid.shader = preload("res://pup/lightcycles_grid.gdshader")
	var floor_ := MeshInstance3D.new()
	floor_.mesh = floor_mesh
	floor_.material_override = grid
	floor_.position = Vector3(0.5, 0, 0.5)   # lines on the cell edges, cycles on the cell centres
	_view.add_child(floor_)

	for i in 2:
		_cycles.append(_make_cycle(i))


## The DMD's rectangle in this control's pixels (again on every resize): walls, avoid zone, a fresh start.
func set_dmd_rect(rect: Rect2) -> void:
	_dmd = rect
	call_deferred("_restart")


func _restart() -> void:
	var area := Rect2(Vector2.ZERO, size).grow(-12)
	var wall := _dmd.grow_individual(-_dmd.size.x * INSET.x, -_dmd.size.y * INSET.y,
		-_dmd.size.x * INSET.x, -_dmd.size.y * INSET.y)
	var behind := _dmd.grow(_dmd.size.y * BEHIND)
	_blocked.clear()
	_avoid.clear()
	_cells.clear()
	for x in W:
		for z in H:
			var c := Vector2i(x, z)
			var p := _cam.unproject_position(_cell_pos(c))
			if _cam.is_position_behind(_cell_pos(c)) or not area.has_point(p) or wall.has_point(p):
				_blocked[c] = true
			elif behind.has_point(p):
				_avoid[c] = 0
	# steps out of the avoid zone: from its edge inwards
	var edge := []
	for c in _avoid:
		for d in DIRS:
			var n: Vector2i = c + d
			if _inside(n) and not _blocked.has(n) and not _avoid.has(n):
				_avoid[c] = 1
				edge.append(c)
				break
	var level := 1
	while not edge.is_empty():
		var nxt := []
		for c in edge:
			for d in DIRS:
				var n: Vector2i = c + d
				if _avoid.get(n, -1) == 0:
					_avoid[n] = level + 1
					nxt.append(n)
		edge = nxt
		level += 1
	for cy in _cycles:
		cy.points = []
		_spawn(cy)


func _inside(c: Vector2i) -> bool:
	return c.x >= 0 and c.y >= 0 and c.x < W and c.y < H


func _cell_pos(c: Vector2i) -> Vector3:
	return Vector3(c.x - W / 2, 0, c.y - H / 2)


func _free(c: Vector2i) -> bool:
	if not _inside(c) or _blocked.has(c):
		return false
	var t = _cells.get(c)
	return t == null or _now - t[0] > FADE * 0.85


func _emissive(col: Color, energy: float) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_color = col.darkened(0.6)
	m.emission_enabled = true
	m.emission = col
	m.emission_energy_multiplier = energy
	return m


func _make_cycle(i: int) -> Dictionary:
	var col: Color = COLORS[i]
	var body := Node3D.new()
	body.add_child(_build_cycle(col))
	body.visible = false
	_view.add_child(body)
	var trail_mat := StandardMaterial3D.new()
	trail_mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	trail_mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	trail_mat.blend_mode = BaseMaterial3D.BLEND_MODE_ADD
	trail_mat.cull_mode = BaseMaterial3D.CULL_DISABLED
	trail_mat.vertex_color_use_as_albedo = true
	var trail := MeshInstance3D.new()
	trail.mesh = ImmediateMesh.new()
	trail.material_override = trail_mat
	_view.add_child(trail)
	# derez: a burst of lit fragments and a flash
	var boom := CPUParticles3D.new()
	boom.emitting = false
	boom.one_shot = true
	boom.amount = 160
	boom.lifetime = 1.4
	boom.explosiveness = 1.0
	boom.direction = Vector3.UP
	boom.spread = 180
	boom.initial_velocity_min = 2.0
	boom.initial_velocity_max = 7.0
	boom.gravity = Vector3(0, -6, 0)
	boom.damping_min = 1.0
	boom.damping_max = 2.0
	var bit := BoxMesh.new()
	bit.size = Vector3.ONE * 0.09
	boom.mesh = bit
	boom.material_override = _emissive(col.lightened(0.3), 4.0)
	boom.scale_amount_min = 0.5
	boom.scale_amount_max = 1.5
	var shrink := Curve.new()
	shrink.add_point(Vector2(0, 1))
	shrink.add_point(Vector2(1, 0))
	boom.scale_amount_curve = shrink
	_view.add_child(boom)
	var flash := OmniLight3D.new()
	flash.light_color = col
	flash.omni_range = 6
	flash.light_energy = 0
	_view.add_child(flash)
	return {"i": i, "body": body, "trail": trail, "boom": boom, "flash": flash, "col": col,
		"cell": Vector2i.ZERO, "dir": Vector2i.RIGHT, "t": 0.0, "points": [], "alive": false, "dead_at": -RESPAWN}


## The 1982 film's light cycle: one dark shell over both wheels, a raised canopy in the middle, the wheels
## showing as lit rims and hubs, and a lit line along each side. Forward is +x, about 1.6 cells long.
func _build_cycle(col: Color) -> Node3D:
	var m := Node3D.new()
	m.scale = Vector3.ONE * 0.85
	var shell := StandardMaterial3D.new()
	shell.albedo_color = Color(0.09, 0.1, 0.13)
	shell.metallic = 0.3
	shell.roughness = 0.35
	shell.rim_enabled = true
	shell.rim = 0.6
	shell.emission_enabled = true
	shell.emission = col * 0.12
	var glass := StandardMaterial3D.new()
	glass.albedo_color = Color.BLACK
	glass.metallic = 0.9
	glass.roughness = 0.05
	glass.emission_enabled = true
	glass.emission = col.darkened(0.6)
	glass.emission_energy_multiplier = 0.6
	var lit := _emissive(col, 4.5)
	var r := 0.34   # wheel radius
	var wx := 0.66  # wheel centres at +-wx
	# shell side profile: rounded tail and nose over the wheels, the canopy hump, a flat belly
	var top := PackedVector2Array()
	for k in 13:
		var a := lerpf(PI * 1.08, PI * 0.5, k / 12.0)
		top.append(Vector2(-wx + cos(a) * (r + 0.07), r + sin(a) * (r + 0.07)))
	top.append_array(PackedVector2Array([Vector2(-0.3, r + 0.45), Vector2(-0.12, r + 0.58),
		Vector2(0.18, r + 0.6), Vector2(0.42, r + 0.46)]))
	for k in 13:
		var a := lerpf(PI * 0.5, -PI * 0.08, k / 12.0)
		top.append(Vector2(wx + cos(a) * (r + 0.07), r + sin(a) * (r + 0.07)))
	var outline := top.duplicate()
	outline.append_array(PackedVector2Array([Vector2(wx - 0.05, r - 0.12), Vector2(-wx + 0.05, r - 0.12)]))
	var body := CSGPolygon3D.new()
	body.polygon = outline
	body.depth = 0.42
	body.position.z = 0.21
	body.material = shell
	m.add_child(body)
	var canopy := CSGPolygon3D.new()
	canopy.polygon = PackedVector2Array([Vector2(-0.28, r + 0.42), Vector2(-0.1, r + 0.555),
		Vector2(0.17, r + 0.575), Vector2(0.38, r + 0.44), Vector2(0.1, r + 0.4)])
	canopy.depth = 0.3
	canopy.position = Vector3(0, 0.012, 0.15)
	canopy.material = glass
	m.add_child(canopy)
	# lit line along each side, under the shell's upper outline
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	for z in [0.225, -0.225]:
		for k in top.size() - 1:
			var p0: Vector2 = top[k] + Vector2(0, -0.1)
			var p1: Vector2 = top[k + 1] + Vector2(0, -0.1)
			var q0 := p0 + Vector2(0, -0.11)
			var q1 := p1 + Vector2(0, -0.11)
			for v in [p0, p1, q1, p0, q1, q0]:
				st.add_vertex(Vector3(v.x, v.y, z))
	var band := MeshInstance3D.new()
	band.mesh = st.commit()
	var band_mat := _emissive(col, 4.5)
	band_mat.cull_mode = BaseMaterial3D.CULL_DISABLED
	band.material_override = band_mat
	m.add_child(band)
	var belly_mesh := BoxMesh.new()
	belly_mesh.size = Vector3(2 * wx, 0.07, 0.46)
	var belly := MeshInstance3D.new()
	belly.mesh = belly_mesh
	belly.position.y = r - 0.12
	belly.material_override = lit
	m.add_child(belly)
	# wheels: dark discs with a lit rim and hub ring on each face
	for x in [-wx, wx]:
		var disc_mesh := CylinderMesh.new()
		disc_mesh.top_radius = r
		disc_mesh.bottom_radius = r
		disc_mesh.height = 0.36
		var disc := MeshInstance3D.new()
		disc.mesh = disc_mesh
		disc.rotation.x = PI / 2
		disc.position = Vector3(x, r, 0)
		disc.material_override = shell
		m.add_child(disc)
		for z in [0.185, -0.185]:
			for ring in [[r, r - 0.1], [r * 0.45, r * 0.3]]:
				var torus := TorusMesh.new()
				torus.outer_radius = ring[0]
				torus.inner_radius = ring[1]
				var t := MeshInstance3D.new()
				t.mesh = torus
				t.rotation.x = PI / 2
				t.position = Vector3(x, r, z)
				t.material_override = lit
				m.add_child(t)
	return m


func _spawn(cy: Dictionary) -> void:
	for n in 300:
		var c := Vector2i(_rng.randi_range(1, W - 2), _rng.randi_range(1, H - 2))
		var d: Vector2i = DIRS[_rng.randi() % 4]
		if not _avoid.has(c) and _free(c) and _free(c + d) and _free(c + d * 2) and _free(c + d * 3):
			cy.cell = c
			cy.dir = d
			cy.t = 0.0
			cy.alive = true
			cy.points = [[_cell_pos(c), _now]]
			cy.body.visible = true
			_cells[c] = [_now, cy.i]
			return
	cy.alive = false   # no room (a tiny window): try again later
	cy.dead_at = _now
	cy.body.visible = false


## At each cell: keep going, or turn left or right. Room ahead and going straight score, the cycle heads
## for the cell in front of the other one (a cut-off), and the avoid zone costs more the deeper it goes.
func _choose_dir(cy: Dictionary) -> void:
	var other: Dictionary = _cycles[1 - cy.i]
	var options := [cy.dir, Vector2i(cy.dir.y, -cy.dir.x), Vector2i(-cy.dir.y, cy.dir.x)]
	var best: Vector2i = cy.dir
	var best_score := -1e9
	for k in options.size():
		var d: Vector2i = options[k]
		var c: Vector2i = cy.cell + d
		if not _free(c):
			continue
		var room := 0
		while room < 6 and _free(c + d * room):
			room += 1
		var score := room * 1.0 + (1.5 if k == 0 else 0.0) + _rng.randf() * 1.5
		if other.alive:
			var target: Vector2i = other.cell + other.dir * 3
			score -= Vector2(c - target).length() * (0.15 if _avoid.has(target) else 0.6)
		score -= _avoid.get(c, 0) * AVOID
		if _avoid.has(cy.cell) and _avoid.get(c, 0) < _avoid[cy.cell]:
			score += AVOID
		if score > best_score:
			best_score = score
			best = d
	if best != cy.dir:
		cy.points.append([_cell_pos(cy.cell), _now])
	cy.dir = best


func _derez(cy: Dictionary) -> void:
	cy.alive = false
	cy.dead_at = _now
	cy.body.visible = false
	cy.boom.position = cy.body.position + Vector3(0, 0.3, 0)
	cy.boom.restart()
	cy.boom.emitting = true
	cy.flash.position = cy.boom.position
	cy.flash.light_energy = 6.0
	# its trail fades out fast and stops being a wall
	for p in cy.points:
		p[1] = minf(p[1], _now - FADE * 0.7)
	for c in _cells:
		if _cells[c][1] == cy.i:
			_cells[c][0] = minf(_cells[c][0], _now - FADE)


func _process(delta: float) -> void:
	if _dmd.size == Vector2.ZERO or not is_visible_in_tree():
		return
	_now += delta
	for cy in _cycles:
		cy.flash.light_energy = maxf(0.0, cy.flash.light_energy - delta * 10.0)
		if not cy.alive:
			if _now - cy.dead_at > RESPAWN:
				_spawn(cy)
			_draw_trail(cy, null)
			continue
		cy.t += delta * SPEED
		while cy.t >= 1.0 and cy.alive:
			cy.t -= 1.0
			var next: Vector2i = cy.cell + cy.dir
			var other: Dictionary = _cycles[1 - cy.i]
			if other.alive and next == other.cell:
				_derez(cy)
				_derez(other)
				break
			if not _free(next):
				_derez(cy)
				break
			cy.cell = next
			_cells[next] = [_now, cy.i]
			_choose_dir(cy)
		if cy.alive:
			var head: Vector3 = _cell_pos(cy.cell) + Vector3(cy.dir.x, 0, cy.dir.y) * cy.t
			cy.body.position = head
			cy.body.rotation.y = atan2(-cy.dir.y, cy.dir.x)
			_draw_trail(cy, head)
		while cy.points.size() > 2 and _now - cy.points[1][1] > FADE:
			cy.points.pop_front()


## The trail: a lit wall along the corners the cycle turned at, fading with age, brightest along its top.
func _draw_trail(cy: Dictionary, head) -> void:
	var mesh: ImmediateMesh = cy.trail.mesh
	mesh.clear_surfaces()
	var pts: Array = cy.points.duplicate()
	if head != null:
		pts.append([head, _now])
	if pts.size() < 2:
		return
	var up := Vector3(0, WALL_H, 0)
	mesh.surface_begin(Mesh.PRIMITIVE_TRIANGLES)
	for k in pts.size() - 1:
		var a: Vector3 = pts[k][0]
		var b: Vector3 = pts[k + 1][0]
		var n := maxi(1, int(a.distance_to(b)))   # one piece per cell, so the fade runs along the wall
		for s in n:
			var p0 := a.lerp(b, float(s) / n)
			var p1 := a.lerp(b, float(s + 1) / n)
			var a0 := clampf(1.0 - (_now - lerpf(pts[k][1], pts[k + 1][1], float(s) / n)) / FADE, 0, 1)
			var a1 := clampf(1.0 - (_now - lerpf(pts[k][1], pts[k + 1][1], float(s + 1) / n)) / FADE, 0, 1)
			var base0: Color = cy.col * 0.9
			var base1: Color = cy.col * 0.9
			var top0: Color = cy.col * 2.4
			var top1: Color = cy.col * 2.4
			base0.a = a0 * 0.8
			base1.a = a1 * 0.8
			top0.a = a0
			top1.a = a1
			mesh.surface_set_color(base0); mesh.surface_add_vertex(p0)
			mesh.surface_set_color(base1); mesh.surface_add_vertex(p1)
			mesh.surface_set_color(top1); mesh.surface_add_vertex(p1 + up)
			mesh.surface_set_color(base0); mesh.surface_add_vertex(p0)
			mesh.surface_set_color(top1); mesh.surface_add_vertex(p1 + up)
			mesh.surface_set_color(top0); mesh.surface_add_vertex(p0 + up)
	mesh.surface_end()
