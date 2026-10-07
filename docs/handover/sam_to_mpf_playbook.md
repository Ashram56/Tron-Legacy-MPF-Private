# Stern SAM game to MPF: the playbook

Game agnostic. Everything here was learned rebuilding Tron Legacy LE v1.74 (the "Tron instance";
file paths in `code` are that repo's, use them as templates). Facts are tagged where it matters:
**[SAM]** true of every Stern SAM game, **[MPF]** / **[GMC]** / **[Godot]** toolchain behaviour,
**[Tron]** specific to that game.

## 1. Inputs and target

Inputs, from a ROM-decompilation repo (see `rom_decomp_feedback.md` for what it should contain):
rules specs per mode, annotated decompiled C, an MPF config package (switches, coils, lights, settings,
shows, sounds), DMD media (frames, timing, reference captures, `rom_images_all.zip`), IO tables,
sound-call tables, and **reference traces**: scenario scripts replayed in an instrumented PinMAME,
logging every score, deff, sound, leff, audit, lamp and coil event as JSONL.

Target toolchain (pinned in one file, `scripts/toolchain.py`):

| Piece | Version | Note |
|---|---|---|
| Python | 3.11 (3.10-3.14 work) | stdlib-only setup script, per-OS venv paths |
| MPF | 0.80.1 (PyPI) | pin `ruamel.yaml.clib==0.2.14`: 0.2.15 breaks `mpf` once mpf-monitor is installed |
| Godot | 4.5.2 stable | download from GitHub releases (tuxfamily mirror may be blocked) |
| GMC (mpf-gmc) | 1.0.0 | not on PyPI: zip/git from github.com/missionpinball/mpf-gmc; needs a patch (section 6) |
| MPF Monitor | 1.0.0 (optional) | PyPI release lacks `core/ui/*.ui`; fetch them from the v1.0.0 tag |
| fontTools, Pillow | any recent | build-time media only |

## 2. Repository layout

- New **game repo**; the asset repo is a **shallow git submodule at `assets/`**. Never copy files out of
  it: generate from it, so an upstream fix reaches the game on the next sync.
- `game/` is both the MPF machine folder and the Godot project, kept apart from `assets/` so Godot does
  not import thousands of asset files (`.gdignore` in folders Godot must skip).
- Everything OS- or CPU-specific (venv, Godot binary, GMC add-on) and everything generated (config with
  MPF headers, slides, sounds, fonts, media data) is **git-ignored** and rebuilt by `scripts/setup.py`.
- Root `.gitignore` uses `/tools/`, not `tools/`, or `game/tools/` (Godot scripts) is ignored too.
- A scheduled sync job bumps the submodule and opens a PR listing changed areas when the asset repo moves.
- Hardware is an **overlay**: `config.yaml` is platform neutral (no `hardware:` section, ROM numbering);
  launch with `-c config,hw_virtual` / `hw_proc` / `hw_vpx`.

## 3. Architecture: model the SAM OS, let MPF own the hardware

MPF owns switches, coils, ball devices, trough, players and turn order. On top, a Python layer reproduces
what the ROM's OS does; most of the game's logic depends on these OS semantics, so build them first.

| Layer | Models | Tron file |
|---|---|---|
| OS layer | ROM **tasks** as tick timers keyed by ROM task id (1 tick = 16.26 ms in play [SAM]); game flags; audits; adjustments by ROM number; `score_add` (nothing while tilted or out of game); playfield validation; ball save; tilt; extra ball; end of ball, bonus, game over; multiball as one task; ball search | `game/tron/os_layer.py` |
| Switch layer | One handler per switch: repeat guard, then feature **hooks in the ROM's fixed order** (`os.hook(name)`), then base score | `game/tron/switches.py` |
| Features | One module per mode spec, registering under ROM hook names; per-player state reset on first ball; auto-discovered | `game/tron/features/*.py` |
| Display manager | Deff priorities, background deffs, foreground run length, 10-tick hold at low priority, **show queue** (show tasks wait for lower priority and oldest-first), **deff rules** that re-assert the background deff, music rules | `game/tron/display.py` |
| Lamp model | Game lamp image + flash mask, override layers by priority (leffs), lamp groups, list-5 "lamp rules" redrawn on every refresh, flashers as coil events | `game/tron/lamps.py` |
| Media bridge | Deff → GMC slide, sound call → one sample of its pool on its track, deff text formatting with live values, over BCP | `game/tron/media_bridge.py` |
| Settings / service | Adjustments as MPF settings, persisted audits, ROM service menu tree, credits/pricing, high scores | `settings.py`, `service.py`, `credits.py` |
| Trace logger | Same JSONL format as the reference traces, so the comparison tool works unchanged | `game/tron/trace.py` |

Keep ROM identifiers (task ids, deff/leff/sound numbers, function addresses) in names and comments.
They make every spec, trace and decompiled-code lookup a grep.

Effects are posted as MPF events (`tron_deff_<id>`, `tron_sound_<call>`, `tron_leff_<id>`,
`tron_tube_<id>`) and written to the trace at the same time.

## 4. Build order

Each step was a stacked branch/PR (next one based on the previous), tested before push, without waiting
for merges.

1. **Toolchain**: MPF + GMC boot, headless DMD capture (`render_check`).
2. **Machine + OS layer + switch layer + scenario harness**, then features mode by mode, each checked
   against its reference trace before the next.
3. **Media**: one GMC slide per deff (frames + ROM timing), sounds, BCP bridge; then ROM fonts and
   ROM text layout; then the score display (deff 19 on Tron) and status panel drawn as the ROM does.
4. **Lamps**: lamp model, leff layers from captured shows, code-drawn leffs, lamp/coil trace comparison.
5. **Service**: adjustments, audits, service menu, credits and pricing, high scores, attract pages.
6. **Hardware overlays**: smart_virtual + MPF Monitor, P-ROC (`driverboards: sternSAM`), VPX bridge.
7. **Portability**: one setup script for Windows/macOS/Linux, CI on all three, installers, Docker.
8. **Optional HD display**: see `dmd_hd_upscaling.md`.

## 5. Verification loop (the part that makes it faithful)

- `tests/scenario.py <name>`: replays `assets/rules/traces/<name>.txt` (`start`, `hit N`, `wait s`,
  `mark`, `adj N v`) on smart_virtual; the runner plays the player (plunge, drain, trough switches).
- `scripts/trace_check.py <name> [--events kinds]`: compares the rebuild's JSONL with the reference
  (wraps the asset repo's `trace_compare.py`, aligned on a `ready` event, tolerance 0.25 s). It drops
  non-rule noise: OS bookkeeping audits, sounds played from inside a deff (checked with the media), and
  background deff re-asserts (`rule: 1`) unless `--strict`. Kinds: score, deff_start, sound, leff_start,
  tube_show_start, audit, multiball_start, mark, plus `lamp` (steady states) and `coil` (flasher/shaker bursts).
- `tests/test_traces.py` holds a **TRACES table: scenario → kinds that match today**. It is the regression
  net: add a kind when it matches, never remove one to get green.
- `scripts/render_diff.py`: renders slides in Godot at the reference capture's frame times and compares
  dot by dot; text must be pixel-exact. `tests/test_dmd_text.py` fails on blank printf lines, fallback
  fonts and empty DMD time during play.
- `scripts/render_check.py`: boots Godot + MPF and fails on a blank DMD.
- Unit tests cover paths no reference scenario reaches; seed the RNG in tests, never in live play.
- Tron result: score matches in 26/30 scenarios, audits 28/30, deffs 27/30 at the end of the rules phase;
  the remaining gaps were features built later.

## 6. Gotchas (each one cost a debugging session)

### MPF 0.80 [MPF]
- Generated YAML needs `#config_version=6` as the first line; the asset package's files lack it.
- Without a terminal start `mpf game . -t` (no curses UI). Never pass `-b`: it disables BCP, MPF Monitor's server with it.
- MPF always serves BCP on 127.0.0.1:5051 (MPF Monitor's port) and **waits for GMC on 5050**: start Godot first.
- `bcp_trigger()` only reaches clients that registered the event name; GMC registers none for sounds,
  so every sound was dropped. Use `bcp_trigger_client()` addressed to `local_display`.
- Duplicate YAML keys are silently merged (PyYAML keeps the last): an early package lost 8 switches and 8 lamps that way. Check generated YAML for duplicates.
- An autofire device marks the playfield active itself; remove `playfield_active` from those switches.
- `driverboards: sternSAM` goes under `hardware:`; under `p_roc:` MPF lowercases it and pypinproc rejects it.
- Platform classes use `__slots__`: patch at class level, not per instance.
- smart_virtual needs help: start with a full trough, make ejects move balls, shift trough switches
  toward the eject end (`virtual_hardware.py`).
- MPF waits for an empty playfield before the next ball; the ROM starts it (and the score display) as
  soon as the bonus ends. Restart the background deff at `ball_will_start`.

### GMC 1.0 + Godot 4.5 [GMC] [Godot]
- GMC parses each socket read as whole lines; MPF's big `settings` message splits across reads and kills
  GMC's BCP thread (no sound after that). `scripts/gmc_patch.py` keeps the unfinished tail; apply it
  idempotently after every GMC install.
- GMC maps `gmc.cfg [keyboard]` by key label only (AZERTY breaks); the same patch adds a US-position lookup.
- When the last slide ends GMC falls back to its base slide. The ROM never clears the DMD: keep the last
  frame until the next effect.
- `--headless` draws nothing: render under Xvfb with `--rendering-driver opengl3`.
- `--write-movie` runs faster than real time, MPF never connects: capture with a real-time autoload
  (`game/tools/dmd_capture.gd`, inert without `--capture-dir=`).
- Probing port 5050 with a connection makes GMC quit: probe by trying to bind, and probe IPv6 too
  (Windows Godot listens on IPv6 only).
- Regenerating media deletes Godot's `.import` files; reimport after. Generated media is git-ignored, so
  after any pull it is stale: stamp the inputs and regenerate automatically on launch.

### Portability
- utf-8 and LF for every generated file, `/` in `res://` paths, long paths on Windows.
- OneDrive folders: deletes/renames fail transiently; wrap them in retries (`scripts/fsutil.py`), and in
  shared caches keep the existing file when a replace races another worker.

### SAM hardware [SAM]
- Dedicated switches use SAM numbering D1-D24 (PinMAME `sam.c`): coin 3, flippers/EOS 9-12, upper EOS 14,
  tilt 17, slam 18, spare 20, service 21-24. PinMAME's comment swaps Plus/Minus; its input port (what
  runs) has Minus on 22, Plus on 23.
- P-ROC numbers (libpinproc `PRDecode`, SternSAM): matrix n → `32 + 8*((n-1)/8) + 7-((n-1)%8)` when
  `(n-1)%16 < 8`, else `32 + n-1`; dedicated n → `n+7`; coil n → `n+31`; lamp n →
  `80 + 16*(7-((n-1)%8)) + (n-1)/8`. Generate the address file, never hand-write it.
- Flippers: 40 ms pulse, hold 1 ms every 12 ms (`default_hold_power: 0.083`). Slings and pops are fired
  by CPU software on SAM; on a P-ROC make them hardware rules.
- Coil pulse widths live in the ROM's coil table and hardware rules (decoded for Tron: generate the MPF
  times from the asset repo's `rom_data/io/coils.csv`, as `scripts/gen_config.py` does); trace timings are
  16 ms samples, not widths.
- Pro and LE models of one title can share rules but not IO numbers. Keep the config in one model's ROM
  numbers, generate the other model's numbers as an overlay (unmatched devices on the virtual platform), and
  have the rules look devices up by name, never by the configured number (`tron/hw_numbers.py`).
- Aux-bus outputs (latched coils 33+, RGB tubes, GI relay bit) are not P-ROC drivers. A wrong aux address
  can fire a coil bank: keep such code off until checked with a logic analyzer.
- Coin door open comes from the IO board interlock status, which a P-ROC cannot read; wire a spare input.
- The sound system is on the CPU board; a CPU replacement means PC audio.
- PinMAME numbering for VPX differs from the P-ROC: tube lamps 101-106, sol 33 = fast-flip toggle,
  negative dedicated switch numbers. VPX loads `<table>.vbs` beside the `.vpx` as a script override;
  never rewrite the `.vpx` (VPX checks its MAC).

### ROM display semantics (where the first build looked wrong) [SAM]
- **Never an empty DMD in play**: after any foreground deff ends with nothing behind it, the deff rules
  restart the background deff (score display or the mode's).
- **Text arguments follow the ROM format string order**, not your call order. `%P` (plural) is not an
  argument; a non-number in a numeric spec prints nothing; `%,02lu` of 0 is `00`.
- **Values come from RAM, live**: status screens reprint timers/scores every refresh (`os.deff_live`).
  A printf line left blank is a bug; make the test fail on it.
- **One deff, several screens**: many deffs pick a screen by argument or phase; show only the selected one.
- **Reference captures are one run**: random choices (mystery awards, clip picks) and the status panel
  (score 00) are frozen in them. Build those deffs from the rules' arguments and draw the live panel over.
  Some captures hold two runs (sounds play twice); use the ROM run length.
- Fonts: the font table and glyph offsets are code data, not in the images; the font index is the image
  group index. Text drawn in Godot's default font anywhere is a bug (test for it).
- Sound calls `0x01-0x08` are channel stops; music calls replace the running music.

## 7. Working rules

- Spec conflicts: the rules spec wins on rules, the MPF package wins on media and names, the annotated
  decompiled C settles disputes. Mark anything inferred as `(inferred)` in code.
- Do not build code the ROM cannot reach (dead modes in the shipped version).
- Classic output must stay exact: any optional display mode (HD, colour) is a switch, and pixel-hash
  tests guard the classic frames. Re-take a hash only after rendering the same frames on the base branch.
- Stack branches, run `pytest` + the trace checks + `render_check` before every push; CI on 3 OSes.
- Write what a successor needs into memory or these docs; commit messages explain each fix.
