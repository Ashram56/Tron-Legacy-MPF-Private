shader_type spatial;
render_mode unshaded;

// The light cycle arena's floor (game/pup/lightcycles.gd): a cyan grid on cell edges, brighter every 4 cells,
// fading into the distance.
uniform vec3 line_color = vec3(0.1, 0.75, 0.9);

void fragment() {
	vec3 wp = (INV_VIEW_MATRIX * vec4(VERTEX, 1.0)).xyz;
	vec2 g = abs(fract(wp.xz - 0.5) - 0.5) / fwidth(wp.xz);
	float minor = 1.0 - min(min(g.x, g.y), 1.0);
	vec2 g4 = abs(fract(wp.xz / 4.0 - 0.5) - 0.5) / fwidth(wp.xz / 4.0);
	float major = 1.0 - min(min(g4.x, g4.y), 1.0);
	float fade = clamp(1.0 - length(wp.xz) / 60.0, 0.15, 1.0);
	ALBEDO = vec3(0.0, 0.015, 0.03) + line_color * (minor * 0.35 + major * 0.9) * fade;
}
