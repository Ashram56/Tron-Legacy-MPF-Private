shader_type canvas_item;
render_mode blend_add;

// Neon frame around the DMD over the light cycle arena (game/pup/pup_player.gd): a white core and a blue halo
// that breathes, with two bright pulses running round it.
uniform vec2 size = vec2(1280.0, 390.0);       // the window, in pixels
uniform vec4 box = vec4(254.0, 98.0, 772.0, 193.0); // the DMD, in pixels
uniform float margin = 12.0;                   // frame line to DMD edge
uniform float radius = 18.0;
uniform float scale = 1.0;                     // line and glow widths (1 for a 772 px wide DMD)
uniform vec3 core = vec3(0.85, 0.95, 1.0);
uniform vec3 halo = vec3(0.15, 0.55, 1.0);

float sd_box(vec2 p, vec2 b, float r) {
	vec2 q = abs(p) - b + r;
	return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}

void fragment() {
	vec2 p = UV * size;
	vec2 c = box.xy + box.zw * 0.5;
	vec2 half_size = box.zw * 0.5 + margin;
	float d = abs(sd_box(p - c, half_size, radius)) / scale;
	float breathe = 0.75 + 0.25 * sin(TIME * 2.2);
	// position round the frame, 0..1
	float ang = atan(p.y - c.y, (p.x - c.x) * half_size.y / half_size.x) / 6.28318 + 0.5;
	float run = 0.0;
	for (int i = 0; i < 2; i++) {
		float h = fract(TIME * 0.18 + float(i) * 0.5);
		float dd = abs(fract(ang - h + 0.5) - 0.5);
		run += exp(-dd * dd * 900.0);
	}
	float line = exp(-d * d / 2.5);
	float glow = exp(-d / 7.0) * 0.55 + exp(-d / 22.0) * 0.25;
	COLOR = vec4(core * line * (0.8 + run * 0.6) + halo * glow * (breathe + run * 1.2), 1.0);
}
