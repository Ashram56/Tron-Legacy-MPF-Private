# Colour DMD and third-party media: notes for the improvement agent (private)

Private on purpose. The public game repo ([Ashram56/Tron-Legacy-MPF](https://github.com/Ashram56/Tron-Legacy-MPF))
only points here. The agents are game agnostic and live in
[Ashram56/Stern-SAM-Decryption](https://github.com/Ashram56/Stern-SAM-Decryption): its
[master plan](https://github.com/Ashram56/Stern-SAM-Decryption/blob/main/agents/README.md) and improvement agent
(`agents/improvement.md`) cover everything else; Tron's status and decisions are on the
[Tron game page](https://github.com/Ashram56/Tron-Legacy-MPF/blob/main/docs/agents/README.md). Never describe
this work, or copy its files, into a public repository other than this one (Stern-SAM-Decryption is public
too). Keep this file current like the public agent files.

## Owner decisions

- 2026-10-04: no colourisation on the public `main`, no colour option left there; the HD DMD is Tron blue.
  Colour work stays in this repository, on its own branches, unless the owner says otherwise.
- 2026-10-12: full colourisation of the HD DMD from the Serum file, on the data renderer (effect.json). All
  text is our own vector font (as in the main game), in the colour the colourisation gives each line; the
  colourisation's own lettering (credits, blink phases, scores) is not shown.

## Where the work is (branches of this repo, not merged into its `main`)

| Branch | What | Last |
|---|---|---|
| `claude/serum-colorization-n17wko` | First Serum import: `scripts/serum.py`, a Python port of libserum's v1 loader and colouriser (Serum_LoadFile, Identify_Frame, Colorize_Frame, sprite detection), so a frame gets the colours PinMAME gives it; `dmd_color.py` colours each effect frame from its Serum frame, Scale2x on the colour indices (256x64). | 2026-10-04 |
| `claude/serum-remaining-animations-rfmmq8` | Serum colours for effects drawn from their bitmaps (looked up through their emulator capture by CRC or by screen fit), and for sprites (ZUSE/TRON letters, arcade reel): 83 effects in Serum colours. Also the PuP-Pack integration (`docs/pup.md`, `scripts/gen_pup.py`, `pup_*`). Based on the current `main` of this repo. | 2026-10-07 |
| `claude/project-thread-nj2ate` | **Full colourisation on the data renderer** (current; below). `--dmd-color on\|off`. | 2026-10-12 |
| `claude/project-thread-8ucgr9` | Installers of this repo with the token step for private repos. | 2026-10-07 |

The earlier PuP-palette colouring (hues measured on the PuP-Pack videos, film palette only) is in the history
of both Serum branches (`scripts/pup_colormap.py`, `game/tools/dmd_colormap.json`). A separate repository,
`Ashram56/Tron-Legacy-MPF-PuP`, carried the PuP-Pack work first.

## How the full colourisation works (`claude/project-thread-nj2ate`)

- Setup (`scripts/gen_media.py`, HD) runs `dmd_color.build` and `dmd_color.annotate` when `serum/trn_174h.cRZ`
  is there (`--no-color` skips it): coloured 2x pictures in `game/media/dmd_color/` (git-ignored, cached in
  `.cache/dmd_color`), `palettes.json` (per effect: source, Serum frame counts), `text_colors.json`.
- `annotate` writes into each `media/dmd/deff_NNN/effect.json`: frames `color_frames` (identical pictures
  share one file, by sha1), text items `color`, rects `color_rgb`, letters `color_pic`, arcade
  `color_cabinets`/`color_icons_a`/`color_icons_b`. Text and rect colours are measured on the effect's
  emulator capture identified in Serum; effects the file does not know take the PuP hues
  (`game/tools/dmd_colormap.json`).
- Recorded frames lose their ROM text (frame_text dots and line boxes, black in the picture); HD draws it live
  in the clean font, ink per line from `text_colors.json`, glow at half the ink. Where a frame is a text screen
  (one lit shade right of the status panel), every dot the ROM leaves dark is black: the colourisation's own
  lettering goes.
- Godot: `dmd_mode.gd` `choose_color` (`--dmd-color=`, `TRON_DMD_COLOR`, `tron/dmd/color`, default on, needs
  `palettes.json`); `dmd_effect.gd` uses the colour twins; `dmd_screen.gd` draws coloured pictures in runs
  (nearest filtering) between the ink layers. Colour off is the plain HD output
  (`tests/test_dmd_color.py` compares the two renders).
- `scripts/serum_lib.py`: libserum itself through ctypes (`build` clones v2.8.0 and the libframeutil revision
  its `platforms/config.sh` pins, CMake), or `TRON_LIBSERUM`. `tests/test_serum.py` checks the Python port and
  its Scale2xPreserve against it (skipped without the library).

## Open

1. Colour rotations (19 frames of the file) are not applied.
2. The node renderer and the GMC slides (service menu, attract pages) keep the HD text colour.
3. About 60 effects the colourisation does not know take PuP hues, not Serum colours.
4. Text screens lose the colourisation's frame decorations on ROM-dark dots (deff 1's red and blue border).

## What was learned

- The Tron colourisation is `serum/trn_174h.cRZ` (a zip holding `trn_174h.cRom`), Serum v1: 5,368 coloured
  frames found by a CRC32 of the 16-shade frame (optional comparison mask, "shape" mode), 64-colour palette per
  frame, dynamic zones coloured by shade (so text drawn over an animation is coloured), sprites found by a
  detection dword and area. Colour rotations are recorded but not applied.
- Effects whose text the game prints live are drawn from bitmaps the colourisation never saw alone: match
  them through the effect's emulator capture (`reference_capture.gif`), by CRC as PinMAME does, or by screen
  fit when the capture's values differ from the colourist's game.
- Colour frames at 2x with Scale2x stay crisp; the smooth 8x upscale made busy film clips soft.
- libserum v1 colourisations give 128x32 only (no 64-line frames); hosts upscale with libframeutil
  `Scale2xPreserve`: Scale2x on the colour indices, outside the frame is index 0, and a lit centre never takes
  an empty neighbour. `scale2x_serum` is that, checked against libserum dot for dot.
- The Python port (`scripts/serum.py`) matched libserum on all 8,620 capture frames tried (indices compared
  modulo 64: libserum can return indices above 63 for the same colour).
- libserum keeps the last colours for an unknown frame; the build colours an effect's frames in order from a
  reset, as the game shows them.
- Windows/OneDrive: identical frames share a cache key; keep the existing cache file when another worker
  holds it (`scripts/fsutil.py`).

Last updated 2026-10-12 (full colourisation on the data renderer, our fonts for all text, libserum parity).
