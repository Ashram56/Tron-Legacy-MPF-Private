# MSDF glyphs are generated on the main thread when first drawn (seconds per string on ARM)

**Project:** https://github.com/godotengine/godot

## Environment

- Godot 4.6.3 stable (also 4.5.2 stable: 2.0 s and 12.9 s with the test project on x86_64), Linux arm64, Mobile renderer
- Jetson Xavier NX, nvpmodel mode 5 (4 Carmel cores at 1.9 GHz)
- `FontFile` with `multichannel_signed_distance_field = true`, `msdf_size = 256`, `msdf_pixel_range` 16 and 192

## What happens

The first time a character is drawn, its MSDF is generated synchronously on the thread that draws it, usually the
main thread. With Orbitron (an OFL font) and the 94 printable ASCII characters:

| `msdf_pixel_range` | Time on the main thread |
|---|---|
| 16 | 6.8 s |
| 192 (wide copy, for outlines and glow) | 45 s |

So the first lines of text froze the game for 20-30 s. A larger pixel range costs much more, which the docs do not
say.

## Minimal reproduction project

[`repro/godot_msdf_main_thread/`](repro/godot_msdf_main_thread/) (zip: `repro/godot_msdf_main_thread.zip`): draws
the 94 printable ASCII characters with an MSDF copy of Orbitron (OFL, bundled with its licence), at
`msdf_pixel_range` 16 and then 192, and prints how long each first frame took. Results:

| Machine | range 16 | range 192 |
|---|---|---|
| Jetson Xavier NX, mode 5 (in the game, the whole set of lines) | 6.8 s | 45 s |
| Linux x86_64, Xeon 2.1 GHz, 4 cores (this project) | 2.0 s | 13.2 s |

## Workaround

Generate the glyphs once offline (`font_render_glyph()` for every character in a headless script), save the
`FontFile` with `ResourceSaver.save()` (the generated glyph cache is kept), and load the saved resource at
start-up with `ResourceLoader.load_threaded_request()`. Text renders identically (0 differing pixels in our
comparison). Script: `game/tools/bake_fonts.gd`.

## Expected

The font importer's pre-render option helps only fonts imported into the project, not fonts loaded at run time
with `load_dynamic_font()` (as a game that lets the user pick a font does). Glyph generation for MSDF fonts on a worker thread (show the glyph a frame later), or an editor/import option to
pre-render a character set, and a note in the `msdf_pixel_range` docs about its cost.
