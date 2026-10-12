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
| DMD text font (HD) | the ROM's dot fonts | a clean TrueType font (Rajdhani by default; Orbitron or Godot's default font selectable) in the ROM's place: same lines and alignment, 0.85 of the ROM's capital height (`--dmd-text-scale`), never wider than the ROM's text (squeezed when wider), black outline instead of the ROM's black cell, shaded big digits drawn flat at their top level | `--dmd-font rom` (the ROM's dots, smoothed), or `--dmd classic` |
| DMD colour | orange | Tron blue, text and animations | `--dmd-tint orange` |
| Text in recorded animations (HD) | baked into the captured frames in the ROM's dot fonts | found at build time (`scripts/frame_text.py`), cleared from the HD frames and drawn live in the clean font at the same place and level; partly drawn lines show their whole letters only; the ZEN zoom (deff 100) is the clean ZEN scaled down from 3x instead of the ROM's scattered blocks (the ZUSE/TRON target letters stay the ROM's pictures); effects whose pictures are only frames and blocks have them drawn as sharp rectangles | `--dmd-font rom`, or `--dmd classic` |
| Text glow | none | a soft glow around HD text by default (0.8) | `--dmd-text-glow 0` |
| Display adjustments in the service menu | ADJUSTMENTS holds STANDARD and FEATURE ADJUSTMENTS | a third item, DISPLAY ADJUSTMENTS: TEXT GLOW (OFF to 300%, factory 80%) and TEXT SIZE (50% to 110% of the ROM's capital height, factory 85%; capped at 110%, larger stacked lines touch) of the HD text, shown on the display while they are edited and kept across power cycles; a stored value replaces `--dmd-text-glow` / `--dmd-text-scale`, the factory value (and RESET FACTORY SETTINGS) gives them back; no effect in classic | leave both at FACTORY, or `--dmd classic` |
| Pricing on the desktop | coins (factory settings) | free play with virtual hardware | `run.py --no-free-play` |
| Hardware | SAM CPU board | MPF on virtual hardware, a P-ROC, or the Visual Pinball X table | `--hw proc` drives the original driver boards |
| Machine | LE 1.74 ROM, LE hardware only | Pro hardware by default (the Pro 1.74 IO assignments, `assets/docs/PRO_VS_LE.md`) running the LE 1.74 rules; LE selectable. The Pro rules are not ported, so on a Pro: the TRON standups use the LE drop-target code with no reset coil; End of Line multiball and the LE-only adjustments stay; the Pro's light cycle ramp extra ball adjustments are missing. Pro coil behaviour follows the Pro decompile: ramp flashers on 19 / 25, lower flashers 22 / 23 fired with them (left/right pairing inferred) | `--machine le` (`hw_proc_le`, `hw_virtual_le`; `hw_vpx` is the LE). docs/hardware.md, "Pro or LE" |
| Service menu during a game | SELECT opens the menu at any time; in a game the game is suspended (`task_suspend(0, 0x800)`) and resumes when the menu is left (`FUN_0000f9b0` / `FUN_0000fa34`) | In attract mode SELECT opens the menu at once. In a game it asks "END GAME?"; a second SELECT within 5 s ends the game at once (no bonus, high score entry, match or game-over audits, as a GAME RESTART) and opens the menu; BACK or the timeout keeps the game. The game cannot be suspended: its timers run on MPF's clock | none (`os_layer.py` `_service_select`) |
| Extra screens (PuP Pack) | the DMD alone | with the PuP Pack installed (docs/pup/README.md): the pack's videos on a backglass, a large DMD window (the DMD in a neon frame over a light cycle chase) and an optional topper, started by the effects the game shows and by switches | `TRON_PUP=0` or `[pup] enabled=false` in `game/pup.local.cfg`; without the pack nothing changes |
| Music (PuP Pack) | the ROM's music | with the PuP Pack installed and its player ready, the pack's soundtrack instead; speech and effects stay the ROM's | `[pup] ost_music=false` (keeps the videos), or the PuP off |
| Fiber optics on a Pro | none (Pro ROM: no ramp light tube driver) | off by default; can be driven (the IO board's aux driver is there) | default (`fiber_optics` overlay turns them on) |

No scoring or rules departures yet.

## ROM behaviour that looks like a bug

| What you see | Why it is right | Source |
|---|---|---|
| "50V / 20V DISABLED / CLOSE COIN DOOR / OR PULL INTERLOCK SWITCH / TO RESTORE POWER" covers the game display for as long as the coin door is open, and dims after 30 s | Deff 4 has priority 247 and never ends by itself; the power handler starts it when the door opens and stops it when the door closes, BACK takes it away (sound 0x009) instead of giving a service credit. Coils do not fire meanwhile (only the optional coil 24 is powered) | `assets/code/tron_pro_decompiled.c:7368` (`FUN_000071a0`, LE `FUN_00007bc4`), `assets/code/tron_game_decompiled_v2.c:109314` (deff 4), `:16720` (BACK); `game/tron/os_layer.py` `_power_off_warning`, `tests/test_coin_door.py` |
| Shaker runs 200 / 384 / 1024 ms, longer than older notes said (75 / 265 / 1100 ms) | ROM table 0x040d3998, measured 203 / 390 / 1040 ms in the emulator | `assets/rom_data/io/README.md`, `game/tron/os_layer.py` `SHAKER_MS` |
| Disc Multiball: Gem, the ramps, the inner loops and the orbits all show "JACKPOT" with points | Only the spinning disc collects the Jackpot. The other blue shots score their own value and add it to the Jackpot, but the ROM plays the same "DISC MULTIBALL / JACKPOT" screen (deff 48) for them | `assets/rules/modes/disc_multiball.md` (blue shot row); the disc_multiball trace: a left-ramp hit grows the Jackpot 250k to 350k, only sw41 pays it; `game/tron/features/disc_multiball.py` `disc_mb_shot` |
| Sea of Simulation: completing a stage with its shot (e.g. the VUK for FLYNN, the right inner loop for GEM) pays only the shot value (100,000 x stage), not the (stage) million that a skipped stage pays | The (stage) x 1,000,000 bonus is only for stages skipped because their item was already collected, once per player (deff 115). A stage played by its shots pays (stage) x 100,000 per needed shot with deff 116+stage; collecting the item at the end of the stage only bumps its audit and item level, no score | `assets/rules/modes/sea_of_simulation.md:4,75-77`; `assets/code/tron_game_decompiled_v2.c:91908` (`sos_stage0_flynn_shot`: 0x186a0 = 100,000), `:93802` (`simulation_shot`: audit + `item_level_add`, no score), `:79822` (`item_level_add`); `assets/rules/traces/sea_of_simulation.jsonl:13683` (FLYNN VUK 100,000), `:16698` (GEM 200,000), `:17600` (CLU skipped 3,000,000), `:21323` (last ZUSE target 400,000, ZUSE collected, no bonus); `tests/test_wizard.py` `test_ladder_from_switches_to_portal` |
| Only Light Cycle and Quorra Multiball stack; Disc, End of Line, Portal and Sea of Simulation never run with another multiball | Each start checks the others' running flags (and the Disc restart window); Light Cycle and Quorra do not check each other. All multiballs end together when fewer than 2 balls are in play | `assets/rules/developer_guide.md` 3.3; `assets/code/tron_game_decompiled_v2.c` `lc_can_start` (0x0101b0dc), `quorra_can_start` (0x0101f2f8), `multiball_end` (0x0101bcec) |
| Quorra (or Light Cycle) started at a later scoop shot while the other runs adds no ball: a second multiball on the same balls. Started on the same scoop shot, they make 3 balls | Both ask for `balls_in_play + 1`, and the ROM's balls in play leave out the ball held in the scoop. The launch count is worked out once the scoop has kicked that ball back into play, so the request is already met. On the same scoop shot the multiball task still runs, so balls in play is the first request (2) and the second asks for 3 | code: `FUN_0001e738` (launch count), `balls_in_play` (0x0001e4a8), `quorra_mb_start` caller 0x0101f5ac; observed only for the same-shot case (`assets/rules/traces/light_cycle_multiball_repeat_and_stack.jsonl`: 2 then 3); `tests/test_ball_tracking.py` `test_later_stack_adds_no_ball` |
| After PINBALL MISSING, if the stuck ball comes free and drains, the ball ends while the served ball is still on the playfield | Lost ball recovery (adj 63, after the 5th failed ball search) takes the missing balls off the installed count and serves new ones; a drain is then counted against the balls in play. The ROM adds the found ball back to the installed count only when the trough holds more balls than it expects | code: `ball_search_start` (0x0001f79c), `trough_drain_check` (0x0001dd90); `game/tron/os_layer.py` `_lost_ball_feed`; `tests/test_ball_tracking.py` |
