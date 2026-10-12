extends Node2D
# Outlined text at a new font size every frame, with rendering/driver/threads/thread_model=2 (separate).
# Expected: no errors. Actual: "_texture_2d_update: Condition p_image.is_null() || p_image->is_empty()" errors.
var n := 0

func _ready() -> void:
	get_tree().create_timer(10.0).timeout.connect(get_tree().quit)

func _process(_delta: float) -> void:
	n += 1
	queue_redraw()

func _draw() -> void:
	var font := ThemeDB.fallback_font
	var size := 8 + n % 120
	draw_string_outline(font, Vector2(10, 150), "SCORE %d" % n, HORIZONTAL_ALIGNMENT_LEFT, -1, size, 4)
	draw_string(font, Vector2(10, 150), "SCORE %d" % n, HORIZONTAL_ALIGNMENT_LEFT, -1, size)
