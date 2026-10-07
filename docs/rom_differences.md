# Differences from the ROM

The game recreates Stern Tron Legacy LE v1.74 from the ROM-derived specs in `assets/rules/`, and the
trace tests (`tests/test_traces.py`, `scripts/trace_check.py`) compare it with recordings of the ROM.
This page is the one list of where the game is meant to behave differently, and of ROM behaviour that
looks like a bug but is the original. Read it before "fixing" a rule, and add to it whenever a change
departs from the ROM, for example a new mode.

## Rules for a departure

- **Record it here** in the same commit: what the ROM does, what the game does, why, and the switch that
  restores the ROM behaviour (if there is one).
- **Keep the ROM behaviour reachable** where that's practical (a command-line option, an MPF setting or a
  machine variable), so the trace tests keep checking the original.
- **Rules changes** (scoring, lighting, modes) get a scenario or unit test for the new behaviour; mark the
  trace checks they change on purpose rather than re-recording the traces.
- **New modes** that are not in the ROM go in their own feature module under `game/tron/features/`, listed
  in the table below, and must not change any ROM scenario.

## Intentional departures

| Area | ROM | This game | Back to the ROM |
|---|---|---|---|
| DMD look | 128x32 orange dots | HD by default: vector fonts and upscaled animations, drawn at any window size | `run.py --dmd classic` (exact ROM output; always used on the P-ROC and for render checks) |
| DMD text font (HD) | the ROM's dot fonts | a clean TrueType font (Orbitron by default; Rajdhani or Godot's default font selectable) in the ROM's place: same lines and alignment, 0.85 of the ROM's capital height (`--dmd-text-scale`), never wider than the ROM's text (squeezed when wider), black outline instead of the ROM's black cell, shaded big digits drawn flat at their top level | `--dmd-font rom` (the ROM's dots, smoothed), or `--dmd classic` |
| DMD colour | orange | Tron blue, text and animations | `--dmd-tint orange` |
| Text glow | none | a soft glow around HD text by default (0.75) | `--dmd-text-glow 0` |
| Animation colour | single colour | the Serum colourisation's colours by default | `--dmd-color off` |
| Pricing on the desktop | coins (factory settings) | free play with virtual hardware | `run.py --no-free-play` |
| Hardware | SAM CPU board | MPF on virtual hardware, a P-ROC, or the Visual Pinball X table | `--hw proc` drives the original driver boards |
| Machine | LE 1.74 ROM, LE hardware only | Pro hardware by default (the Pro 1.74 IO assignments, `assets/docs/PRO_VS_LE.md`) running the LE 1.74 rules; LE selectable. The Pro rules are not ported, so on a Pro: the TRON standups use the LE drop-target code with no reset coil; End of Line multiball and the LE-only adjustments stay; the Pro's light cycle ramp extra ball adjustments are missing. Pro coil behaviour follows the Pro decompile: ramp flashers on 19 / 25, lower flashers 22 / 23 fired with them (left/right pairing inferred) | `--machine le` (`hw_proc_le`, `hw_virtual_le`; `hw_vpx` is the LE). docs/hardware.md, "Pro or LE" |
| Service menu during a game | SELECT opens the menu at any time; in a game the game is suspended (`task_suspend(0, 0x800)`) and resumes when the menu is left (`FUN_0000f9b0` / `FUN_0000fa34`) | In attract mode SELECT opens the menu at once. In a game it asks "END GAME?"; a second SELECT within 5 s ends the game at once (no bonus, high score entry, match or game-over audits, as a GAME RESTART) and opens the menu; BACK or the timeout keeps the game. The game cannot be suspended: its timers run on MPF's clock | none (`os_layer.py` `_service_select`) |
| Fiber optics on a Pro | none (Pro ROM: no ramp light tube driver) | off by default; can be driven (the IO board's aux driver is there) | default (`fiber_optics` overlay turns them on) |

No scoring or rules departures yet.

## ROM behaviour that looks like a bug

| What you see | Why it is right | Source |
|---|---|---|
| "50V / 20V DISABLED / CLOSE COIN DOOR / OR PULL INTERLOCK SWITCH / TO RESTORE POWER" covers the game display for as long as the coin door is open, and dims after 30 s | Deff 4 has priority 247 and never ends by itself; the power handler starts it when the door opens and stops it when the door closes, BACK takes it away (sound 0x009) instead of giving a service credit. Coils do not fire meanwhile (only the optional coil 24 is powered) | `assets/code/tron_pro_decompiled.c:7368` (`FUN_000071a0`, LE `FUN_00007bc4`), `assets/code/tron_game_decompiled_v2.c:109314` (deff 4), `:16720` (BACK); `game/tron/os_layer.py` `_power_off_warning`, `tests/test_coin_door.py` |
| Shaker runs 200 / 384 / 1024 ms, longer than older notes said (75 / 265 / 1100 ms) | ROM table 0x040d3998, measured 203 / 390 / 1040 ms in the emulator | `assets/rom_data/io/README.md`, `game/tron/os_layer.py` `SHAKER_MS` |
| Disc Multiball: Gem, the ramps, the inner loops and the orbits all show "JACKPOT" with points | Only the spinning disc collects the Jackpot. The other blue shots score their own value and add it to the Jackpot, but the ROM plays the same "DISC MULTIBALL / JACKPOT" screen (deff 48) for them | `assets/rules/modes/disc_multiball.md` (blue shot row); the disc_multiball trace: a left-ramp hit grows the Jackpot 250k to 350k, only sw41 pays it; `game/tron/features/disc_multiball.py` `disc_mb_shot` |
| Sea of Simulation: completing a stage with its shot (e.g. the VUK for FLYNN, the right inner loop for GEM) pays only the shot value (100,000 x stage), not the (stage) million that a skipped stage pays | The (stage) x 1,000,000 bonus is only for stages skipped because their item was already collected, once per player (deff 115). A stage played by its shots pays (stage) x 100,000 per needed shot with deff 116+stage; collecting the item at the end of the stage only bumps its audit and item level, no score | `assets/rules/modes/sea_of_simulation.md:4,75-77`; `assets/code/tron_game_decompiled_v2.c:91908` (`sos_stage0_flynn_shot`: 0x186a0 = 100,000), `:93802` (`simulation_shot`: audit + `item_level_add`, no score), `:79822` (`item_level_add`); `assets/rules/traces/sea_of_simulation.jsonl:13683` (FLYNN VUK 100,000), `:16698` (GEM 200,000), `:17600` (CLU skipped 3,000,000), `:21323` (last ZUSE target 400,000, ZUSE collected, no bonus); `tests/test_wizard.py` `test_ladder_from_switches_to_portal` |
