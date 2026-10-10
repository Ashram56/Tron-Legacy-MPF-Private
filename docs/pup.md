# PuP Pack: Tron Legacy "End of Line" on three screens

This repository is the MPF game of [Ashram56/Tron-Legacy-MPF](https://github.com/Ashram56/Tron-Legacy-MPF)
plus the PuP Pack of [Ashram56/Tron-LE-PuP-Pack](https://github.com/Ashram56/Tron-LE-PuP-Pack) (Terry Red's
"End of Line" pack, `trn_174h`): its videos play on the backglass, around the DMD and on an optional topper,
and its OST replaces the ROM music.

## Setting it up

The [README](../README.md#install) has the one-line install. By hand, from a clone:

```sh
python scripts/setup.py               # venv, MPF, Godot, GMC, the game's media + the PuP media
python scripts/run.py                 # the game, with the PuP windows
```

`run.py` prints `PuP on: ...` before it starts Godot, or what is missing. `setup.py` calls
`scripts/pup_setup.py`, which fetches the `pup_pack` submodule and runs `scripts/gen_pup.py`: it turns
every video into Theora (`.ogv`, the only video format Godot plays) and copies the mp3s and
pictures. It needs an ffmpeg with libtheora (ffmpeg on the PATH, or `FFMPEG=<path>`); without one it
installs `imageio-ffmpeg` in the venv. The whole pack
takes a while (Theora encodes on one core per file; all cores are used); `--max-height 720` makes smaller
videos for a slower PC. Without the converted media the PuP stays off and the game runs as upstream.

**Windows and macOS: native mp4 playback.** On Windows and macOS, `setup.py` installs the `native_video` add-on
(`pup_addons/native_video`, copied to the git-ignored `game/addons/native_video/`) and the pack's mp4s play as
they are, with hardware decoding (Media Foundation, AVFoundation): nothing is converted, `gen_pup.py --native`
only lists the videos. This build carries a fix for a heap overrun in the upstream release
([issue 26](https://github.com/claytercek/godot-native-video/issues/26), `pup_addons/native_video_build/`), so do
not replace it with an upstream zip: the macOS dylibs come from the `native_video macOS build` workflow, the
Windows DLLs from `pup_addons/native_video/FIX.md`. The add-on needs Godot 4.6+ and a RenderingDevice renderer
(the game uses Mobile). `TRON_NATIVE_VIDEO=0` in the environment for `setup.py` converts the videos instead and
removes the add-on; without it loaded the PuP plays the converted Theora videos.

**Linux: GDE GoZen.** On Linux (x86_64 and arm64), `setup.py` installs GDE GoZen (`pup_addons/gde_gozen`,
copied to the git-ignored `game/addons/gde_gozen/`), an FFmpeg add-on: the pack's mp4s play as they are and
nothing is converted. On a Jetson (JetPack 5 or 6) it uses the hardware decoder once libnvmpi is installed
(the Linux install line does it, or `scripts/install/install_jetson_hwdec.sh`, see
`pup_addons/gde_gozen/README.md`, and [jetson.md](jetson.md) for the fixes it needs); everywhere else FFmpeg
decodes in software.
`TRON_GOZEN=0 python scripts/setup.py` goes back to Theora. The binaries are rebuilt from pinned sources with
`scripts/build_gozen.sh` (Docker).

## The three screens

| Window | Shows | PuP screens |
|---|---|---|
| `backglass` (4:3) | background and mode loops, event videos popping over them | 2 (underlay), 12 (top layer) |
| `dmd` (large LCD) | the pack's DMD panel art, the game's 128x32 DMD in its black middle | the game's DMD |
| `topper` (optional) | mode info, TRON / ZUSE letters, light cycles | 13 (underlay), 14 (top layer) |
| (no window) | OST music | 15 |

By default (`[pup] layout="stack"`) the windows open one under the other at the left of the main monitor,
backglass at the top, then the DMD, then the topper, as large as the monitor's height allows. Every window
can be resized and its content follows; `run.py --dmd-size WxH` sets the DMD window's size. For a cabinet,
`layout="manual"` puts each window at its own `screen`/`position`/`size`, or fullscreen.

Everything is set in `game/pup.cfg`. Do not edit it for your cabinet: put the keys you change in
`game/pup.local.cfg` (git-ignored, same sections), for example:

```ini
[pup]
layout="manual"           ; each window where its section says
third_screen=false        ; no topper window and no topper videos

[backglass]
screen=1                  ; monitor index
fullscreen=true
borderless=true

[dmd]
screen=2
fullscreen=true
borderless=true
```

- `[pup] third_screen=false` turns the third screen off.
- `[pup] ost_music=false` keeps the ROM music (the videos still play).
- `[pup] enabled=false`, or `TRON_PUP=0` in the environment, turns the whole PuP off: the game is then exactly
  the upstream game.
- `[backglass] fit`: the videos are 16:9 and the backglass 4:3: `fit` (black bars, `align` places the video),
  `fill` (crops the sides) or `stretch`.
- `[dmd] frame_crop` / `dmd_rect` place the art and the DMD (pixels of the art image), `dots` draws round dots.
  The game's own 128x32 window is minimised (`hide_main_window`); it stays the source of the DMD picture, so
  `render_check.py` and the P-ROC DMD output work as before. Keys pressed in any PuP window drive the game as
  in the DMD window.

**Linux cabinet (Jetson).** Use an X11 session (on Ubuntu's login screen, the gear icon: "Ubuntu on Xorg"):
Godot places one window per monitor only on X11. Nobody touches a keyboard or mouse while playing, so the
screens must not blank: `install_jetson_hwdec.sh` turns off GNOME's idle blanking, dimming, lock and suspend
for the cabinet user (`--keep-blanking` leaves them), and `run.py` turns off the X screen saver and DPMS for
the session. To start without a login, turn on automatic login in `/etc/gdm3/custom.conf`:

```ini
[daemon]
AutomaticLoginEnable=true
# the cabinet user's name
AutomaticLogin=cabinet
# an X11 session by default
WaylandEnable=false
```

(GDM's file takes no comments at the end of a line.)

## How it works

1. **Triggers.** The pack's `triggers.pup`, `playlists.pup` and `screens.pup` are read as they are, so a new
   pack version needs no code change. In Visual Pinball, `D<n>` fires when the DMD shows the inside of the
   purple rectangle of `PupCapture/<n>.bmp`. Here the game says what it shows: it posts `tron_deff_<id>` when
   display effect `<id>` takes the DMD. `game/tron_pup/trigger_map.yaml` maps each `D<n>` to the effects whose
   frames contain that capture, found by `scripts/pup_captures.py` (all 98 captures against every recorded frame,
   variant and ROM library animation; report in [pup_captures.md](pup_captures.md)). `W<n>` are switches
   (by name, so the P-ROC numbering does not matter). The one `W11=1,L35=1` row (Arcade Mystery) is mapped to the
   Flynn's Arcade award effect.
2. **MPF side** (`game/tron_pup/`, loaded as the never-started mode `pup`): the engine fires the rows of an
   event, applies their `RestSeconds`, and sends each as a BCP `pup_play` to Godot.
3. **Godot side** (`game/pup/`, autoload `Pup`): the windows, and per PuP screen the PinUP Player rules:
   priorities, `Loop`, `SetBG`, `StopFile`, `StopPlayer`, `SkipSamePrty`, playlists in order (`AlphaSort`) or
   at random, pop-up top layers.
4. **Music.** When Godot's PuP player is ready (it answers MPF's `pup_hello` with `pup_ready`), MPF drops the
   ROM's music calls (the sound pools on the `music` track) and stops the running ROM music; speech and effects
   still play. Without a ready PuP player the ROM music plays as before.

`python scripts/pup_check.py` plays a rules scenario with the PuP windows and saves them to `captures/pup/`.
`tests/test_pup.py` covers the map, the engine and the music hand-over.

## Keeping up with the upstream game

The upstream MPF game keeps changing (rules, DMD animations). Its history is this repository's history, so
upstream changes merge in:

```sh
python scripts/sync_upstream.py                 # merges upstream/main, then re-checks everything
python scripts/sync_upstream.py --branch NAME   # another upstream branch
```

The PuP touches upstream files in a few one-line places only: the `pup.yaml` include in
`game/config/config.yaml`, the `Pup` autoload in `game/project.godot`, the `pup_pack` submodule in
`.gitmodules`, three `.gitignore` lines, the README (the PuP paragraphs, the fork's install URLs and the screens section), the installers' default
repository and folder (`Tron-Legacy-MPF-PuP`), CI's checkout (no submodules: the PuP Pack repo is
private, `setup.py` fetches `assets/`), one `pup_setup` call each in `scripts/setup.py` and `scripts/run.py`.
One upstream change is not a hook and would be best made upstream too: Godot 4.6.3 instead of 4.5.2
(`scripts/toolchain.py`, the docs and tests that name it; the native video add-on needs 4.6). Everything else is in its own files, so a merge seldom conflicts.
After the merge the script updates the submodules, regenerates the config and media, re-runs the capture
match and the tests. What can need a hand after an upstream change:

- a DMD animation or effect number changed: `scripts/pup_captures.py` marks the captures whose mapped effect no
  longer draws them (**check** in `docs/pup_captures.md`); fix those lines of `trigger_map.yaml`;
- the media bridge (`game/tron/media_bridge.py`) renamed `sound`, `music_key` or its sound pools:
  `tests/test_pup.py` fails on the music hand-over (`game/tron_pup/mode.py`, `set_music_mute`).
