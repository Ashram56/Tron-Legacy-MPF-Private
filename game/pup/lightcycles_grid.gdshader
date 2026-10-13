shader_type spatial;
render_mode unshaded;

// The light cycle arena's floor (game/pup/lightcycles.gd): a cyan grid on cell edges, brighter every 4 cells,
// fading into the distance. Now and then a glowing segment runs along a line picked at random, along x or z,
// with a fading tail, like the pulses running round the DMD's neon frame (above the environment's glow
// threshold, so the bloom gives it its halo): all in this shader, nothing per frame on the CPU.
uniform vec3 line_color = vec3(0.1, 0.75, 0.9);
uniform float pulse_chance = 0.15;   // share of the lines that carry a segment in each of their cycles
uniform float pulse_speed = 9.0;     // cells per second
uniform float pulse_length = 4.0;    // the segment's length with its tail, in cells
uniform float pulse_energy = 3.0;    // the brightest the segment gets, over the line colour
const float RUN = 24.0;              // a segment runs from -RUN to +RUN cells along its line

float hash(vec2 p) {
	return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

// The segment on the line numbered id (axis 0: lines of constant x, 1: constant z) at the point "along" the
// line (world units), 0..1: its head bright, its tail fading behind it.
float pulse(float id, float along, float axis) {
	float run = 2.0 * RUN / pulse_speed;                        // seconds one segment takes
	float len = run * (1.2 + hash(vec2(id, axis + 7.0)));      // each line its own cycle, a pause between runs
	float t = TIME / len + hash(vec2(id, axis + 3.0));
	float cycle = floor(t);
	if (hash(vec2(id * 1.37 + cycle, axis)) > pulse_chance) {
		return 0.0;
	}
	float dir = hash(vec2(cycle, id + axis * 91.0)) > 0.5 ? 1.0 : -1.0;
	float head = (-RUN + fract(t) * len * pulse_speed) * dir;
	float s = (along - head) * dir;                             // < 0 behind the head
	if (s > 0.3 || s < -pulse_length) {
		return 0.0;
	}
	float tail = 1.0 + min(s, 0.0) / pulse_length;
	return tail * tail * 0.7 + exp(-s * s * 6.0) * 0.6;
}

void fragment() {
	vec3 wp = (INV_VIEW_MATRIX * vec4(VERTEX, 1.0)).xyz;
	vec2 d = abs(fract(wp.xz - 0.5) - 0.5);          // world distance to the nearest line, x and z
	vec2 g = d / fwidth(wp.xz);
	float minor = 1.0 - min(min(g.x, g.y), 1.0);
	vec2 g4 = abs(fract(wp.xz / 4.0 - 0.5) - 0.5) / fwidth(wp.xz / 4.0);
	float major = 1.0 - min(min(g4.x, g4.y), 1.0);
	float fade = clamp(1.0 - length(wp.xz) / 60.0, 0.15, 1.0);
	vec2 id = floor(wp.xz + 0.5);
	// lines of constant x run along z, lines of constant z along x
	vec2 lit = vec2(pulse(id.x, wp.z, 0.0), pulse(id.y, wp.x, 1.0));
	vec2 core = 1.0 - min(g * 0.6, 1.0);                // a little wider than the line itself
	vec2 halo = exp(-d * 14.0) * 0.35;
	float glow = dot(lit, core + halo);
	ALBEDO = vec3(0.0, 0.015, 0.03) + line_color * ((minor * 0.35 + major * 0.9) * fade + glow * pulse_energy);
}
