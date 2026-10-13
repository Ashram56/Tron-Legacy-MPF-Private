# Visual Pinball X: the VPW table played by MPF

The VPW "Tron Legacy (Stern 2011) VPW Mod v1.1" table was written for PinMAME running the ROM. With the
`hw_vpx` overlay, Visual Pinball X keeps doing what it does well (the ball, the playfield, the mechanical
sounds) and **this MPF game replaces PinMAME**: MPF runs the rules, Godot draws the DMD and plays the ROM's
speech, music and effects. The table file is not modified.

```
VPX table script --COM--> TronMPF.Controller --BCP 5051--> MPF (hw_vpx, virtual_pinball) --BCP 5050--> Godot (DMD, sound)
 (core.vbs, sam.vbs)       scripts/vpx_bridge.py            game/tron/vpx_hardware.py
```

| Piece | What it does |
|---|---|
| `scripts/vpx_table.py` | Reads the script out of the `.vpx` and writes `<table name>.vbs` next to it. VPX (10.7 and later) loads a `.vbs` with the table's name instead of the script inside the table, so the table plays with MPF while the `.vbs` is there and with PinMAME once it is deleted or renamed. The only change: `LoadVPM ... "sam.VBS"` becomes `LoadMPF "sam.VBS"`, which loads the same VPinMAME helper scripts and creates `TronMPF.Controller` instead of `VPinMAME.Controller`. Rewriting the `.vpx` itself is not an option: VPX refuses a table whose script changed without its MAC hash being recomputed. |
| `scripts/vpx_bridge.py` | The `TronMPF.Controller` COM server (pywin32, out of process). Each controller call becomes an MPF `vpcom_bridge` BCP command, the protocol of MPF's `virtual_pinball` platform and of [mpf-vpcom-bridge](https://github.com/missionpinball/mpf-vpcom-bridge). `Run` starts the game when it is not running yet. `Stop` (the table closing) quits the game it started. |
| `game/config/hw_vpx.yaml` | The overlay: platform `virtual_pinball`, PinMAME's numbers for the SAM dedicated switches, the flippers, the ramp tubes' channels. |
| `game/tron/vpx_hardware.py` | Makes MPF answer as VPinMAME does (see "Device map"). |

## Set-up (Windows, once)

1. The workspace as usual (README, Getting started), plus the bridge's packages:
   `python scripts\setup.py --vpx` (olefile and pywin32).
2. Register the COM server, in a terminal opened **as Administrator**, in the repo folder:
   `.venv\Scripts\python scripts\vpx_bridge.py --register`
   (`--unregister` removes it). It is registered with this repo's path and venv: register again after moving
   the repo. If the table then says it cannot load TronMPF.Controller with a DLL error, run pywin32's
   post-install once, also as Administrator: `.venv\Scripts\python .venv\Scripts\pywin32_postinstall.py -install`.
3. Write the table's MPF script next to the table:
   `.venv\Scripts\python scripts\vpx_table.py "C:\Visual Pinball\Tables\Tron Legacy (Stern 2011) VPW Mod v1.1.vpx"`
4. `controller.vbs`, `core.vbs` and `sam.vbs` come from VPX's own `Scripts` folder, as before. VPinMAME is not
   needed while the `.vbs` is there.

## Playing

Start the game first, then the table:

```
python scripts\run.py --hw vpx
```

Godot opens the DMD window, MPF starts and waits for the table ("MPF waits for the Visual Pinball X table").
Then start the table in VPX. If the table is started first, the bridge starts `run.py --hw vpx` itself in a new
console and waits for it (VPX looks frozen during that time; the first start after a pull also regenerates the
media). Closing the table quits a game the bridge started.

Keys are VPX's own (the table script and `sam.vbs` turn them into switches): coin `5`, START `1`, flippers, plunger,
tilt (nudge) keys, slam tilt `Home`, service buttons `7` `8` `9` `0`, and `End` opens and closes the coin door
(as in PinMAME: "50V / 20V DISABLED" on the DMD and no coils until it is closed again, or `7` takes the warning away). Free play is on by default, as with
`--hw virtual`; `--no-free-play` brings back the factory pricing. The DMD window is Godot's: place it where
the table's DMD goes (`--dmd-size 1280x320` sets its size). The table's own DMD stays
empty. Other run.py options work as usual (`--dmd classic`, `--monitor` for MPF Monitor next to the table).

Settings, as environment variables for the bridge: `TRON_VPX_RUN_ARGS` (extra run.py arguments when the bridge
starts the game, for example `--dmd classic`), `TRON_VPX_LAUNCH=0` (never start it, only connect),
`TRON_MPF_HOST` / `TRON_MPF_PORT` (MPF on another computer: also give MPF's BCP server an outside address,
see mpf-vpcom-bridge's README). Logs: `game\logs\vpx_bridge.log` (bridge), MPF's console, `game\logs\godot.log`.

## Device map

The table uses PinMAME's numbering for Stern SAM, which for the matrix switches, coils and lamps is the ROM's
own numbering, the numbers `game/config` already uses. So every device keeps its MPF name; only these differ:

| Table (PinMAME) | MPF | Notes |
|---|---|---|
| switch 84 / 82 (`swLLFlip` / `swLRFlip`) | `s_left_flipper` / `s_right_flipper` | SAM dedicated #9 / #11. The upper left flipper is on the left button. |
| switch -7 (`swTilt`, the table's nudge tilt) | `s_plumb_bob_tilt` | |
| switch -6 (`swSlamTilt`) | `s_slam_tilt` | |
| switch 65 (`swCoin1`) | `s_coin` | Coins 2 and 3 (66, 67) are ignored, like any switch MPF does not have. |
| switches -3, -2, -1, 0 | `s_service_back`, `_minus`, `_plus`, `_select` | |
| switch -4 | `s_coin_door_open` | The table script's `End` key toggles it (`scripts/vpx_table.py` adds that line to the table's KeyDown; sam.vbs has no coin door switch). While it is on, every solenoid but 24 reads 0 and solenoid 33 is off, as the ROM masks its outputs with the door's power cut. |
| switch 41 | `s_disc_opto` | Not inverted here: the table closes it while the ball is on the disc. |
| solenoids 1-32 | the coils and flashers of the same number | Reported 0 or 255 (the table sets `UseVPMModSol`), pulses always reported at least once. |
| solenoid 33 | flippers enabled | On while MPF has the flipper rules on. `sam.vbs`'s fast flips then move the flippers straight from the keys; when MPF turns the flippers off (tilt, ball end, game over, service menu) solenoid 33 goes off and the flippers drop. The ticket outputs (MPF 33-35) are renumbered out of the way. |
| solenoids 15, 16, 12 | `c_left_flipper`, `c_right_flipper`, `c_upper_left_flipper` | Follow the flipper buttons while the rules are on, as the SAM CPU does. |
| lamps 1-80 | the lights of the same number | 0 or 1. |
| lamps 101-103 / 104-106 | `l_left_ramp_tube` / `l_right_ramp_tube` (blue, green, red) | PinMAME's numbering of the tubes' colour bits (strobe 0x10 / 0x20), reported 0-255 for the table's `RGB()`. |
| GI strings | none | MPF does not drive the GI relay; the table turns its GI on at start. |

The ball devices count the table's own trough (18-21), shooter lane (23) and VUK (11) switches: the table's
`bsTrough` starts with 4 balls, and MPF's ejects (solenoids 1, 2, 4) fire the table's kickers.

## Checked here, and what to check on Windows

Checked in the Linux workspace (VPX itself only runs on Windows):
- `tests/test_vpx.py`: the overlay's numbers, a game started through the bridge's calls (trough, START, trough
  kicker, flippers enabled, flipper coils following the button, lamps, the ramp tubes as RGB lamps, unknown
  switches), and the script rewrite.
- `python scripts/vpx_bridge.py --check`: the bridge's own client, without COM, against the real game. It
  started `run.py --hw vpx` (Godot and MPF), loaded the trough, pressed START, saw the trough kicker and the
  flippers enabled, held the left flipper, and quit the game on Stop.
- `scripts/vpx_table.py` on the VPW v1.1 table: one line changed (the loader), the rest byte for byte.

To check on Windows, in this order:
1. `python scripts\vpx_bridge.py --check` with nothing running: same result as above, on Windows.
2. Register, write the `.vbs`, start `run.py --hw vpx`, start the table: no message box; MPF's console shows
   the switches as VPX sets them; the trough holds 4 balls (MPF Monitor: `--monitor`).
3. Coin `5`, START `1`: the DMD and sound start a game, the trough kicks a ball to the shooter lane, the plunger
   launches it, the flippers work, and stop when the ball drains (ball end) or on a tilt.
4. Flashers and lamps follow the game (attract shows, the ramp tubes' colours); the drop targets reset
   (solenoid 3), the VUK kicks out (4), the recognizer and 3-bank motors move (6, 23), the orbit post (7).
5. Close the table: a game the bridge started quits too.
