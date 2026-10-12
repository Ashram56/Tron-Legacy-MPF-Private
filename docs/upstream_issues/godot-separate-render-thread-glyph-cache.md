# Separate render thread: `_texture_2d_update` errors when a font's glyph cache grows

**Project:** https://github.com/godotengine/godot

## Environment

- Godot 4.6.3-stable (official Linux arm64 build), Vulkan, Forward Mobile renderer
- Jetson Xavier NX, L4T R35.6.4 (JetPack 5.1.4), NVIDIA Tegra Xavier (nvgpu), X11

## What happens

With `rendering/driver/threads/thread_model` set to `Separate` (2), drawing text at sizes the font has not cached
yet logs, every few frames:

    ERROR: Condition "p_image.is_null() || p_image->is_empty()" is true.
       at: _texture_2d_update (servers/rendering/renderer_rd/storage_rd/texture_storage.cpp:1368)

No script is on the call stack (`debug/settings/gdscript/always_track_call_stacks` prints no backtrace): the call
comes from the engine's own glyph cache update. With `thread_model` 1 (Safe) there are no errors.

The picture looks complete: drawing the same 120 sizes in both modes and comparing the final frames gives identical
pixels, so the update that fails seems to be an empty one. The errors flood the log, though, and hide real ones.

## Reproduce

[`repro/godot_glyph_cache/`](repro/godot_glyph_cache/): a project of three files that draws outlined text with
`ThemeDB.fallback_font` at a new size each frame for 10 s.

    godot --path docs/upstream_issues/repro/godot_glyph_cache

Result: 8 errors in 10 s with `thread_model=2`, 0 with `thread_model=1`. Text drawn without an outline did not
show it in the same test; in a real project (labels and `draw_string` with dynamic fonts, no outlines) it showed
7 to 15 times in 40 s.

## Workaround

A font with `multichannel_signed_distance_field` enabled avoids the errors, but its glyphs are generated on first
use on the main thread: in a real project that stalled the game for 3 to 7 s at start-up. The errors are left as
they are; `scripts/perf/summary.py` counts them apart.
