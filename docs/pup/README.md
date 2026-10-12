# PuP Pack: Tron Legacy "End of Line" on three screens

The game plays Terry Red's "End of Line" PuP Pack (`trn_174h`) when it is installed: its videos play on the
backglass, around the DMD and on an optional topper, and its OST replaces the ROM music. The pack is optional:
without it, or with the PuP off, the game is the ROM's alone (docs/rom_differences.md lists both departures).
It comes from the author's zip, or from the `pup_pack` submodule, a private copy
([Ashram56/Tron-LE-PuP-Pack](https://github.com/Ashram56/Tron-LE-PuP-Pack)) only its owner can read. Until
2026-10-10 this work lived in a fork, [Tron-Legacy-MPF-PuP](https://github.com/Ashram56/Tron-Legacy-MPF-PuP),
now merged here.

## Setting it up

The [README](../../README.md#install) has the one-line install. By hand, from a clone:

```sh
python scripts/setup.py               # venv, MPF, Godot, GMC, the game's media + the PuP media
python scripts/run.py                 # the game, with the PuP windows
```

`run.py` prints `PuP on: ...` before it starts Godot, or what is missing. `setup.py` calls
`scripts/pup/pup_setup.py`, which fetches the `pup_pack` submodule and runs `scripts/pup/gen_pup.py`: it turns
every video into Theora (`.ogv`, the only video format Godot plays) and copies the mp3s and
pictures. It needs an ffmpeg with libtheora (ffmpeg on the PATH, or `FFMPEG=<path>`); without one it
installs `imageio-ffmpeg` in the venv. The whole pack
takes a while (Theora encodes on one core per file; all cores are used); `--max-height 720` makes smaller
videos for a slower PC. Without the converted media the PuP stays off and the game runs without it.

**The pack from its author's zip.** Without a zip the source is the `pup_pack` submodule (this project's
private copy of the pack; the installers use it only with a token or git credentials that can read it). `TRON_PUP_ZIP=<zip or https URL>` in the environment of `setup.py` (or the installers'
`--pup-zip` / `-PupZip`, or `python scripts/pup/pup_setup.py --pup-zip <zip>`) takes the pack from the zip its author
publishes instead, so a player downloads it from the author, who gets the credit:
`pup_setup.py` finds the folder holding `triggers.pup` in the zip (at any depth, e.g. `PUPVideos/trn_174h/`),
extracts it into `pup_pack/trn_174h/` and notes the zip's SHA-256 in `pup_pack/trn_174h/.pup_zip`, so the same zip
is not extracted twice; the installers then don't ask for access to the pack's repository. A pack already
checked out by the submodule is left alone (delete the folder to switch). A different release of the pack can
change the captures or the trigger rows: run `python scripts/pup/pup_captures.py` after switching and fix the
lines it flags in `game/tron_pup/trigger_map.yaml`.

**Linux and Windows: GDE GoZen.** On Linux (x86_64 and arm64) and Windows (x86_64), `setup.py` installs GDE
GoZen (`pup_addons/gde_gozen`, copied to the git-ignored `game/addons/gde_gozen/`), an FFmpeg add-on: the pack's
mp4s play as they are and nothing is converted. Both platforms share the same player (`game/pup/gozen_player.gd`,
GoZen's `video_playback.gd` with the frame queue and worker-thread opens, the NV12 upload). The GPU decodes:
- **Windows**: Direct3D 11 Video, else DXVA2, built into FFmpeg (NVIDIA, AMD and Intel GPUs, nothing to install).
  Godot's log says `GoZen: hardware decoding h264 (d3d11va)` for each video, or that the GPU cannot decode it
  and software is used. `GOZEN_HWDEC=0` forces software decoding, `GOZEN_HWDEC=dxva2` asks for DXVA2 only.
- **Jetson** (JetPack 5 or 6): the hardware decoder once libnvmpi is installed (the Linux install line does it,
  or `scripts/install/install_jetson_hwdec.sh`, see `pup_addons/gde_gozen/README.md`, and [jetson/README.md](../jetson/README.md)
  for the fixes it needs); other Linux PCs decode in software.

`python scripts/pup/video_check.py` checks the decoding without the game: it decodes a few pack videos on the GPU,
then in software (`GOZEN_HWDEC=0`), and prints per video `GPU (NV12)` or `software` and how many times faster
than real time it decodes (`game/tools/gozen_check.gd`).

`TRON_GOZEN=0 python scripts/setup.py` leaves GoZen out (Linux: back to Theora; Windows: native_video). The
binaries are rebuilt from pinned sources with `scripts/build_gozen.sh` (Docker).

**macOS, and Windows' fallback: native_video.** On macOS, and on Windows next to GoZen, `setup.py` installs the
`native_video` add-on (`pup_addons/native_video`, copied to the git-ignored `game/addons/native_video/`), which
plays the mp4s with the OS's decoder (AVFoundation, Media Foundation). On Windows it plays only when picked:
`video_player="native"` under `[pup]` in `game/pup.local.cfg`, or `TRON_VIDEO_PLAYER=native` for one run; the
log says `PuP video player: native_video` (or `GDE GoZen`). This build carries a fix for a heap overrun in the
upstream release ([issue 26](https://github.com/claytercek/godot-native-video/issues/26),
`pup_addons/native_video_build/`), so do not replace it with an upstream zip: the macOS dylibs come from the
`native_video macOS build` workflow, the Windows DLLs from `pup_addons/native_video/FIX.md`. The add-on needs
Godot 4.6+ and a RenderingDevice renderer (the game uses Mobile). `TRON_NATIVE_VIDEO=0` in the environment for
`setup.py` leaves it out; with no add-on loaded the PuP plays the converted Theora videos.

## The three screens

| Window | Shows | PuP screens |
|---|---|---|
| `backglass` (4:3) | background and mode loops, event videos popping over them | 2 (underlay), 12 (top layer) |
| `dmd` (large LCD) | the game's 128x32 DMD in a neon frame over a live light cycle chase (or the pack's DMD panel art, `background="frame"`) | the game's DMD |
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
  the game without the PuP.
- `[backglass] fit`: the videos are 16:9 and the backglass 4:3: `fit` (black bars, `align` places the video),
  `fill` (crops the sides) or `stretch`.
- `[dmd] background`: `lightcycles` (the default) draws the DMD in a neon frame over a live 3D chase
  (`game/pup/lightcycles.gd`): two 1982-style light cycles on a grid, their trails fading after about 3 s, a
  cycle that hits a trail, a wall or the other cycle derezzes and comes back. The middle of the DMD is a wall
  and the cells behind the rest of it an avoid zone the cycles steer out of, so the chase stays around the
  DMD; `lightcycles_dmd` is the DMD's width as a share of the window's and `lightcycles_dmd_height` the most of
  its height it may take (0.68 and 0.62, the DMD's share of the pack's own panel art: 870x218 on a 1280x390
  bar, 1190x298 on 1920x480; until 2026-10-10 0.6 and 0.5, which left a 1920x480 bar's DMD at half its
  height). It is
  a few hundred triangles; `background="frame"` is the PuP Pack's DMD panel art instead.
- `[dmd] frame_crop` / `dmd_rect` (`background="frame"`) place the art and the DMD (pixels of the art image),
  `dots` draws round dots.
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
   frames contain that capture, found by `scripts/pup/pup_captures.py` (all 98 captures against every recorded frame,
   variant and ROM library animation; report in [captures.md](captures.md)). `W<n>` are switches
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

`python scripts/pup/pup_check.py` plays a rules scenario with the PuP windows and saves them to `captures/pup/`.
`tests/test_pup.py` covers the map, the engine and the music hand-over.

## When the game changes

The PuP touches the game in a few places only: the `pup.yaml` include in `game/config/config.yaml`, the `Pup`
autoload in `game/project.godot`, the `pup_pack` submodule in `.gitmodules`, one `pup_setup` call each in
`scripts/setup.py` and `scripts/run.py`; everything else is in its own files. It needs Godot 4.6+ (the native
video add-on). What can need a hand after a game change:

- a DMD animation or effect number changed: `scripts/pup/pup_captures.py` marks the captures whose mapped effect no
  longer draws them (**check** in `docs/pup/captures.md`); fix those lines of `trigger_map.yaml`;
- the media bridge (`game/tron/media_bridge.py`) renamed `sound`, `music_key` or its sound pools:
  `tests/test_pup.py` fails on the music hand-over (`game/tron_pup/mode.py`, `set_music_mute`).
