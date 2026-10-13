# Tron Legacy MPF

Stern's **Tron Legacy Limited Edition** (code v1.74) rebuilt in the Mission Pinball Framework (MPF 0.80.1) with
a Godot DMD, from the reverse-engineered rules, media and effects in
[Ashram56/Tron-Legacy-LE-ROM-Decryption](https://github.com/Ashram56/Tron-Legacy-LE-ROM-Decryption). It runs on
Windows, macOS and Linux, on a desktop or on the real machine through a P-ROC.

It can also play Terry Red's "End of Line" PuP Pack on three screens: the backglass (4:3 videos), a large LCD
DMD (the game's DMD in a neon frame over a live 3D light cycle chase, or the pack's DMD panel art) and an
optional topper. The pack's soundtrack then replaces the ROM music. Without the pack, or with `TRON_PUP=0`, the
game is the ROM's alone. [docs/pup/README.md](docs/pup/README.md) has the details.

**Working with Claude, or rebuilding another Stern SAM game this way?** Start at the
[master plan](https://github.com/Ashram56/Stern-SAM-Decryption/blob/main/agents/README.md) in Stern-SAM-Decryption: what to provide (ROM, VPX table) and the
agents that do the work. Tron's own status and decisions: [docs/agents/README.md](docs/agents/README.md).

## Install

Run the line for your OS in a terminal. It installs what is missing (Git, Python 3.11, the libraries), clones
this repository into a `Tron-Legacy-MPF-Private` folder in your home folder, and runs `scripts/setup.py`, which
downloads Godot, MPF and GMC (and the PuP Pack when it can read it) and builds the media. The first run takes a
while.

**Windows 10/11** (PowerShell or cmd):

```powershell
powershell -ExecutionPolicy Bypass -Command "& ([scriptblock]::Create((irm https://raw.githubusercontent.com/Ashram56/Tron-Legacy-MPF-Private/main/scripts/install/install_prereqs_windows.ps1) -join [char]10))"
```

**macOS 12+:**

```sh
bash <(curl -fsSL https://raw.githubusercontent.com/Ashram56/Tron-Legacy-MPF-Private/main/scripts/install/install_prereqs_macos.sh)
```

**Linux** (Debian/Ubuntu, Fedora, Arch):

```sh
bash <(curl -fsSL https://raw.githubusercontent.com/Ashram56/Tron-Legacy-MPF-Private/main/scripts/install/install_prereqs_linux.sh)
```

You can change where the files go, and what is installed:

- **Folder:** set `TRON_DIR` before running the line. Windows: `$env:TRON_DIR = "D:\Tron"` first.
  macOS / Linux: `TRON_DIR=~/games/tron bash <(curl ...)`. The default is `%USERPROFILE%\Tron-Legacy-MPF-Private` on
  Windows, `~/Tron-Legacy-MPF-Private` elsewhere.
- **Branch / repository:** `TRON_BRANCH` and `TRON_REPO`, the same way. A folder that already holds a clone is
  updated with `git pull --ff-only` instead, after moving aside the untracked files the update adds (see
  "Update").
- **Private repositories:** git reads a private repository (the assets or the game if they are made private)
  with a GitHub token, never a password. The installer asks for it first, before the long installs (github.com > Settings > Developer settings > Personal access tokens; a fine-grained token with
  Contents: read-only). On Windows, paste it with a right-click: Ctrl+V does not paste into the hidden prompt. Or
  give it before the line, so nothing is asked: Windows `$env:TRON_GITHUB_TOKEN = "github_pat_..."` first,
  macOS / Linux `TRON_GITHUB_TOKEN=github_pat_... bash <(curl ...)`.
- **PuP Pack (optional):** the `pup_pack` submodule is a private repository: the installer uses it only with a
  token given before the line (`TRON_GITHUB_TOKEN`) or git credentials that can read it, and otherwise installs
  the game without the pack, asking nothing. To use the pack as its author publishes it instead (Terry Red's "End of Line" zip, from where the author shares it), set
  `TRON_PUP_ZIP` to the zip file or its https URL before the line (Windows: `$env:TRON_PUP_ZIP =
  "C:\Users\me\Downloads\Tron.zip"`), or give `--pup-zip FILE` (Windows `-PupZip FILE`). No access to the
  private repository is needed then. Already installed: `python scripts/pup/pup_setup.py --pup-zip FILE`.
- **Options:** on macOS and Linux they go after the line, for example `bash <(curl ...) --no-monitor` to leave
  MPF Monitor out, `--proc` for the real machine, `--dry-run` to see the plan first. On Windows:
  add them at the end of the line: `... -join [char]10)) -NoMonitor"`. (Never `irm ... | iex`: Windows
  PowerShell can run the script line by line and stop on line 1 with "the terminator #> is missing".)

On Windows, keep the folder out of OneDrive (the default, your home folder, is): OneDrive locks and
read-protects files while it syncs them. Setup copes with that, but it is slower and may leave stray files.

**If this repository is private**, the lines above get a 404: `curl` and `irm` need the token too. Give it
to them (in PowerShell on Windows; the same token is then used for git):

```powershell
$env:TRON_GITHUB_TOKEN = "github_pat_..."; & ([scriptblock]::Create((irm -Headers @{Authorization = "token $env:TRON_GITHUB_TOKEN"} https://raw.githubusercontent.com/Ashram56/Tron-Legacy-MPF-Private/main/scripts/install/install_prereqs_windows.ps1) -join [char]10))
```

```sh
export TRON_GITHUB_TOKEN=github_pat_...; bash <(curl -fsSL -H "Authorization: token $TRON_GITHUB_TOKEN" https://raw.githubusercontent.com/Ashram56/Tron-Legacy-MPF-Private/main/scripts/install/install_prereqs_linux.sh)
```

(`install_prereqs_macos.sh` on macOS.)

**Clone first** (if the lines above cannot fetch the script). Install Git, then:

```sh
git clone --recurse-submodules https://github.com/Ashram56/Tron-Legacy-MPF-Private.git
cd Tron-Legacy-MPF-Private
scripts/install/install_prereqs_linux.sh          # or install_prereqs_macos.sh
```

On Windows: `powershell -ExecutionPolicy Bypass -File scripts\install\install_prereqs_windows.ps1`. The
installer then asks for a GitHub token, as above, only if a repository it needs is private.

## Play

From the install folder:

| | Windows | macOS / Linux |
|---|---|---|
| Start the game | `.venv\Scripts\python scripts\run.py` | `.venv/bin/python scripts/run.py` |
| ... with MPF Monitor | `... run.py --monitor` | `... run.py --monitor` |
| ... on the real machine (P-ROC) | `... run.py --hw proc` | `... run.py --hw proc` |

With the PuP Pack installed, the three PuP windows open one under the other at the left of the screen:
backglass, DMD, then topper. You can resize each one, and keys pressed in any of them drive the game.

The game starts in **free play** (`game/config/free_play.yaml`): START begins a game without a coin.
`--no-free-play` keeps the factory pricing (3 coins = 1 credit). `Ctrl+C` in the terminal (or `Esc` in MPF's
text UI) quits; Godot's log is `game/logs/godot.log`.

With the DMD window focused, keys close the machine's switches (`game/gmc.cfg`, `[keyboard]`); in MPF Monitor,
click a switch instead. Keys work by label or by position on a US keyboard, so on **AZERTY** the unshifted
number row works (`(` is coin, `&` is START) and `!` is the right flipper; the arrow keys are the flippers on
any layout.

| Key | Switch |
|---|---|
| `5` | coin (`s_coin`, right slot: 3 coins = 1 credit at factory pricing) |
| `1` | START (`s_start_button`) |
| `Space` | plunge: the ball leaves the shooter lane |
| `Z` / `/` (or `←` / `→`) | left / right flipper |
| `T` | tilt (plumb bob) |
| `D` | coin door open / closed |
| `7` `8` `9` `0` | service buttons BACK, MINUS, PLUS, SELECT (FREE PLAY is adjustment 34 in STANDARD ADJUSTMENTS) |

## Settings

`scripts/run.py` takes the options; `python scripts/run.py --help` lists them all:

- `--monitor`: also MPF Monitor (installed by default; `run.py --monitor` installs it if it is missing).
- `--no-free-play`: coins as on the factory settings.
- `--scenario NAME`: plays a rule trace from `assets/rules/traces/` in real time.
- `--hw proc`: the real machine on a Multimorphic P-ROC ([docs/hardware.md](docs/hardware.md)).
- `--machine le`: a Tron Legacy LE's IO assignments; the default is the Pro (`--fiber-optics` drives the ramp
  light tubes on a Pro). See [docs/hardware.md](docs/hardware.md), "Pro or LE".
- `--hw vpx`: the Visual Pinball X table, with MPF instead of PinMAME (Windows; `setup.py --vpx` first, [docs/vpx.md](docs/vpx.md)).
- `--dmd classic`: the original 128x32 dots instead of the HD DMD (the default on the desktop); `TRON_DMD=classic`
  in the environment does the same for every run.
- `--dmd-size 1920x480`: the DMD window's size (HD scales to any size). `--dmd-dots 2`: an HD dot-matrix look.
- `--dmd-tint orange`: the HD DMD in the original orange instead of Tron blue.
- `--dmd-color off`: the HD DMD without the Serum colourisation (on by default in this private repository when
  setup built its colour frames; [docs/agents/colorization.md](docs/agents/colorization.md)).
- `--dmd-font NAME`: the HD text font: `rajdhani` (default, clean), `orbitron` (Tron style, wider), `godot` (Godot's
  default font), a `.ttf`/`.otf` file, or `rom` (the ROM's own dot fonts, smoothed). `--dmd-text-scale X`: its
  size, 1 = the ROM's capital height (default 0.85).
- `--dmd-text-color "#RRGGBB"`, `--dmd-text-glow X`: the HD text's colour and glow (0.8 by default; `--dmd-text-glow 0` turns it off).

[docs/development.md](docs/development.md#running) has the details of the HD DMD.

## Screens and PuP settings

Put your settings in `game/pup.local.cfg`. It uses the same sections as [`game/pup.cfg`](game/pup.cfg),
which documents every key. For a cabinet, put each window on its own monitor in fullscreen:

```ini
[pup]
layout="manual"
third_screen=false        ; no topper

[backglass]
screen=1
fullscreen=true
borderless=true

[dmd]
screen=2
fullscreen=true
borderless=true
```

`TRON_PUP=0` in the environment runs the original game without the PuP.

## Update

From the install folder: `git pull`, then `python3 scripts/setup.py` (Windows: `py -3.11 scripts\setup.py`).
You can also run the install line again. Both are safe to repeat; setup only redoes what changed.
If `git pull` stops on "untracked working tree files would be overwritten" (Godot writes a `.uid` file next to
each new script, and the update brings the same file), run the install line instead: it removes those Godot
files, and moves any other file of yours in the way to `<file>.local`, before pulling.

Git leaves a folder behind when a pull moves or deletes all its files. `python3 scripts/clean_tree.py` lists those
empty folders and `--delete` removes them; it never touches a folder holding a file, a Git-ignored folder or a
submodule.

## Folders

What is in the repository; *(PuP)* marks the PuP Pack's folders, used only when the pack is installed.

```
Tron-Legacy-MPF-Private/
├── assets/                  submodule: the ROM extraction (rules, traces, sounds, DMD frames); setup.py fetches it
├── pup_pack/                submodule (PuP, private): Terry Red's "End of Line" PuP Pack, read as is
├── game/                    the MPF + Godot game (MPF machine folder and Godot project in one)
│   ├── config/              MPF config: config.yaml, hardware overlays (hw_*), machine_pro/le, pup.yaml (PuP hook)
│   ├── modes/               MPF modes: attract, tron_service, pup (PuP)
│   ├── tron/                the game's rules, display and hardware code (Python and GDScript)
│   │   └── features/        one file per rule feature (modes, multiballs, hurry-ups, ...)
│   ├── slides/              Godot scenes for the DMD slides
│   ├── tools/               Godot helpers: DMD capture, font bake, HD DMD shaders, performance probe
│   ├── fonts_ttf/           the HD DMD fonts (Orbitron, Rajdhani)
│   ├── monitor/             MPF Monitor layout and playfield picture
│   ├── pup/                 (PuP) the PuP windows in Godot: video player, screens, DMD frame, light cycles
│   ├── tron_pup/            (PuP) the trigger engine in MPF; trigger_map.yaml maps pack triggers to game effects
│   ├── pup.cfg              (PuP) screen settings, every key documented; yours go in pup.local.cfg
│   └── gmc.cfg              keyboard and window settings of the Godot media controller
├── pup_addons/              (PuP) video add-ons setup.py copies into game/addons/
│   ├── native_video/        Windows and macOS: plays the pack's mp4s
│   ├── native_video_build/  the heap fix the macOS build applies
│   └── gde_gozen/           Linux and Jetson: GDE GoZen with the hardware decoder
├── scripts/                 setup.py (install), run.py (play), the generators and checks
│   ├── pup/                 (PuP) pup_setup (called by setup.py and run.py), gen_pup (media conversion),
│   │                        pup_captures (trigger map check), pup_check (screens check)
│   ├── install/             one-line installers per OS, P-ROC build, Jetson hardware decoder and self-test
│   ├── gozen/               (PuP) the GoZen and jetson-ffmpeg patches build_gozen.sh applies
│   ├── perf/                performance runs (docs/performance.md)
│   └── clean_tree.py        removes empty leftover folders
├── scenarios/               (PuP) game scripts for run.py --scenario (a whole game to Portal Multiball)
├── tests/                   unit tests (pytest -q tests) and the machine configs they load
├── docs/                    development, hardware, requirements, vpx, performance, rom_differences, agents/
│   ├── pup/                 (PuP) how the PuP is wired in; captures.md, the trigger map report
│   ├── jetson/              NVIDIA Jetson set-up and video fixes, Xavier NX results
│   └── upstream_issues/     reports for Godot, GoZen and jetson-ffmpeg, with their test programs
├── docker/                  optional Docker setup for Linux hosts
└── .github/workflows/       CI tests on Windows, macOS and Linux; the macOS native_video build
```

Setup and play create these, all ignored by Git: `.venv/` (Python), `tools/` (Godot), `pup_media/` (the converted
PuP media), `game/addons/` (GMC and the video add-ons), `game/logs/`, `game/data/`, `game/audits/`, the generated
`game/config/rom/`, `game/sounds/`, `game/media/` and `game/fonts/`, and `captures/`.

## More

- [docs/pup/README.md](docs/pup/README.md): the PuP Pack: setting it up, the screens, how it is wired in.
- [docs/development.md](docs/development.md): the workspace in detail (layout, setup options, running by hand,
  tests and checks, the asset sync).
- [docs/requirements.md](docs/requirements.md): what a computer needs, per OS.
- [docs/install_findings.md](docs/install_findings.md): what testing the one-line installers found (tokens, Windows, Linux arm64).
- [docs/hardware.md](docs/hardware.md): virtual hardware and the P-ROC.
- [docs/vpx.md](docs/vpx.md): Visual Pinball X played by MPF.
- [docs/jetson/README.md](docs/jetson/README.md): the game on an NVIDIA Jetson (Orin, Xavier NX).
- [docs/rom_differences.md](docs/rom_differences.md): where the game differs from the ROM, and ROM quirks that are not bugs.
- [docs/performance.md](docs/performance.md): the settings that keep every frame on time, and how to measure.
- [docs/jetson_image.md](docs/jetson_image.md):
  building and flashing the minimal Xavier NX image (SD or NVMe, from WSL or Linux).
- [docker/README.md](docker/README.md): the optional Docker setup for Linux hosts.
- [docs/agents/README.md](docs/agents/README.md): Tron's page for the AI agents (status, open work, decisions); the
  agents themselves and the master plan are in [Stern-SAM-Decryption](https://github.com/Ashram56/Stern-SAM-Decryption).
