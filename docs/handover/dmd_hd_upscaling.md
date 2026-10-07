# HD DMD: drawing a 128x32 DMD at any resolution

Game agnostic (any 128x32, 16-shade DMD game). Tron files in `code`. Colour is out of scope here.

## Requirements that shaped it

- **Classic stays exact.** The 128x32 output (scaled by whole pixels) is what the ROM checks compare;
  it must stay byte-identical. HD is a mode switch, never a change to classic slides.
- **Same layout as the ROM.** HD draws the same 128x32 layout at the window's resolution: every glyph
  advance and position is the ROM's, only rendered smoother. No re-layout.
- **Build time, deterministic, offline.** No learned model, no network: Pillow (+ fontTools for fonts).
- Real-hardware outputs (P-ROC DMD) and render captures are always classic.

## Pipeline

| Step | Tool | Output (git-ignored) |
|---|---|---|
| Effect frames and letter sprites upscaled | `scripts/dmd_hd.py`, called by `gen_media.py` | `game/media/dmd_hd/deff_NNN/*.png` (same names as `media/dmd/`), cached by content in `.cache/dmd_hd/` |
| ROM fonts traced to vector outlines | `scripts/font_outline.py`, called by `gen_fonts.py` | `game/fonts/hd/rom_font_NN.ttf` + glow atlas `rom_font_NN_glow.fnt/.png`, `fonts_hd.json` |
| Mode selection at runtime | `game/tools/dmd_mode.gd` (autoload) | |
| HD text drawing | `game/tron/rom_text_hd.gd` (used by `rom_text.gd`, `service_screen.gd`) | |

### Frame upscaler (level sets)

16-shade DMD art is processed one shade at a time: for each shade present, the mask `dot >= shade` is
enlarged bilinearly, blurred (Gaussian `SIGMA = 0.28` dots) and thresholded at `CUT = 118/255` (a bit
under half, so diagonal neighbours stay joined as pixel art intends) with a 1-px anti-aliased ramp.
Stacking the masks gives the picture: staircases become straight or curved edges, one-dot lines keep
their width, single dots become round. `FRAME_SCALE = 8` (1024x256; linear filtering above).
No learned upscaler: the filter keeps the 16 discrete levels and gives the same output on every build.

### Vector fonts

Each glyph's dots get the same smoothing, then marching squares trace the `CUT` iso-line at 16 samples
per dot, simplified to 0.01 dot. Metrics are the ROM's exactly: 1 dot = 128 units, units per em = line
height, advance = glyph width + x offset + font spacing. So `font_size = line height in dots` lands every
glyph where the 128x32 layout does, sharp up to 4K. One TTF holds layers drawn in order:

- `U+E000 + c`: the cell (black box under plain glyphs, black border of outlined ones), drawn black;
- `c`: the lit dots in the text colour (so the font also works as an ordinary font);
- `U+E000 + 0x100*k + c`: dots at level >= k for shaded fonts (big digits).

The glow atlas is a BMFont of each glyph's lit dots blurred twice (sigma 0.45 and 1.3 dots), same
advances, drawn additively behind the text. The first version used 16x bitmap atlases from the same
filter; vector outlines replaced them because they stay sharp at any size.

### Clean fonts (default)

The traced ROM fonts keep the ROM's 5x7-style letter shapes, which look soft and blobby on a big LCD. By
default HD draws the text in an ordinary font instead (`game/fonts_ttf/`, SIL OFL: Orbitron at weight 700, the default,
or Rajdhani Bold; or Godot's own default font, or any `.ttf`/`.otf`), chosen with `--dmd-font` /
`TRON_DMD_FONT` / `tron/dmd/font`; `rom` keeps the traced fonts. `rom_text_hd.gd` keeps the ROM's layout:
the callers pass the ROM's text width and alignment flags, the letters are scaled so the font's capital
height (measured from its "H") equals the ROM font's `cap`, the line is aligned in the ROM's box and squeezed
horizontally (leaving one dot of air) when wider. `--dmd-text-scale` (default 0.85) then shrinks each line
about the middle of its capitals, so stacked lines and the glow keep apart. Shaded fonts are drawn flat at their top level; instead of
the ROM's black cell the text gets a black outline (1 dot for outlined ROM fonts, 0.5 otherwise); the glow is
five widening outlines added in the glow colour.

![before / after](../images/hd_clean_fonts_before_after.png)

Rendering: multichannel signed distance field (MSDF) at a fixed size of 64 scaled by the canvas transform, so
fractional sizes and any window size stay sharp. Godot's MSDF edges get jagged when the field's pixel range
is large compared to `msdf_size`, and outlines can only grow as wide as the range: so two copies, `font`
(range 16 of 256, the letters) and `wide` (range 192, outlines and glow).

### Runtime (`dmd_mode.gd`)

Mode precedence, first match wins: `--proc-dmd` (classic) → user arg `--dmd=hd|classic` → render
captures (classic) → env `TRON_DMD` → project setting `tron/dmd/mode` (default `hd`).
In HD: content scale mode `canvas_items` at 4:1, filtered textures, every sprite showing `media/dmd/X`
swaps to `media/dmd_hd/X` scaled to the same 128x32 footprint, text drawn from the TTFs.
Options: text colour (default `#2a6cff`), glow colour (`#22b8ff`) and strength (0.8) via `--dmd-text-*`,
`TRON_DMD_TEXT_*` or `tron/dmd/text_*`; optional dot-matrix look `--dmd-dots N` (`tools/dmd_dots.gdshader`).
Plain labels and letter sprites get their glow from a SubViewport + `tools/dmd_glow.gdshader`.

## Tests

- Classic frames against pixel hashes taken before HD existed (`tests/test_dmd_hd.py`).
- Every font and layer: TrueType and glow advances = ROM advances x scale; outline winding; Godot's own
  layout advances (`tools/font_check.gd`).
- HD frames exist for every deff; HD text rendered at 1280x320.

## Gotchas

- When the base branch changes a deff, the classic hashes must be re-taken: render the same frames on
  the base first and only re-take when they agree.
- Without fontTools the HD fonts are skipped and HD falls back to classic; `gen_media.py --no-hd` skips HD.
- Identical frames share a cache key; on Windows/OneDrive a parallel worker may hold the entry: keep the
  existing file instead of replacing it.
- Text baked into captured frames and text drawn live go through the same filter, so they match.
