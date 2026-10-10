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

## Where the work is (branches of this repo, not merged into its `main`)

| Branch | What | Last |
|---|---|---|
| `claude/serum-colorization-n17wko` | First Serum import: `scripts/serum.py`, a Python port of libserum's v1 loader and colouriser (Serum_LoadFile, Identify_Frame, Colorize_Frame, sprite detection), so a frame gets the colours PinMAME gives it; `dmd_color.py` colours each effect frame from its Serum frame, Scale2x on the colour indices (256x64). | 2026-10-04 |
| `claude/serum-remaining-animations-rfmmq8` | Serum colours for effects drawn from their bitmaps (looked up through their emulator capture by CRC or by screen fit), and for sprites (ZUSE/TRON letters, arcade reel): 83 effects in Serum colours. Also the PuP-Pack integration (`docs/pup.md`, `scripts/gen_pup.py`, `pup_*`). Based on the current `main` of this repo. | 2026-10-07 |
| `claude/project-thread-8ucgr9` | Installers of this repo with the token step for private repos. | 2026-10-07 |

The earlier PuP-palette colouring (hues measured on the PuP-Pack videos, film palette only) is in the history
of both Serum branches (`scripts/pup_colormap.py`, `game/tools/dmd_colormap.json`). A separate repository,
`Ashram56/Tron-Legacy-MPF-PuP`, carried the PuP-Pack work first.

## What was learned

- The Tron colourisation is `serum/trn_174h.cRZ` (a zip holding `trn_174h.cRom`), Serum v1: 5,368 coloured
  frames found by a CRC32 of the 16-shade frame (optional comparison mask, "shape" mode), 64-colour palette per
  frame, dynamic zones coloured by shade (so text drawn over an animation is coloured), sprites found by a
  detection dword and area. Colour rotations are recorded but not applied.
- Effects whose text the game prints live are drawn from bitmaps the colourisation never saw alone: match
  them through the effect's emulator capture (`reference_capture.gif`), by CRC as PinMAME does, or by screen
  fit when the capture's values differ from the colourist's game.
- Colour frames at 2x with Scale2x stay crisp; the smooth 8x upscale made busy film clips soft.
- Windows/OneDrive: identical frames share a cache key; keep the existing cache file when another worker
  holds it (`scripts/fsutil.py`).

Last updated 2026-10-10 (agents moved to Stern-SAM-Decryption).
