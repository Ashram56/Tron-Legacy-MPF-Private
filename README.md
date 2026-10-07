# Tron Legacy MPF + PuP Pack

Stern's **Tron Legacy Limited Edition** (code v1.74) rebuilt in the Mission Pinball Framework (MPF 0.80.1) with
a Godot DMD, from the reverse-engineered rules, media and effects in
[Ashram56/Tron-Legacy-LE-ROM-Decryption](https://github.com/Ashram56/Tron-Legacy-LE-ROM-Decryption). It runs on
Windows, macOS and Linux, on a desktop or on the real machine through a P-ROC.

This fork adds Terry Red's "End of Line" PuP Pack on three screens: the backglass (4:3 videos), a large LCD
DMD (the pack's DMD panel art, with the game's DMD in the middle) and an optional topper. The pack's
soundtrack replaces the ROM music. [docs/pup.md](docs/pup.md) has the details.

## Install

Run the line for your OS in a terminal. It installs what is missing (Git, Python 3.11, the libraries), clones
this repository into a `Tron-Legacy-MPF-PuP` folder in your home folder, and runs `scripts/setup.py`, which
downloads Godot, MPF, GMC and the PuP Pack and builds the media. The first run takes a while.

**Windows 10/11** (PowerShell or cmd):

```powershell
powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/Ashram56/Tron-Legacy-MPF-PuP/main/scripts/install/install_prereqs_windows.ps1 | iex"
```

**macOS 12+:**

```sh
bash <(curl -fsSL https://raw.githubusercontent.com/Ashram56/Tron-Legacy-MPF-PuP/main/scripts/install/install_prereqs_macos.sh)
```

**Linux** (Debian/Ubuntu, Fedora, Arch):

```sh
bash <(curl -fsSL https://raw.githubusercontent.com/Ashram56/Tron-Legacy-MPF-PuP/main/scripts/install/install_prereqs_linux.sh)
```

You can change where the files go, and what is installed:

- **Folder:** set `TRON_DIR` before running the line. Windows: `$env:TRON_DIR = "D:\Tron"` first.
  macOS / Linux: `TRON_DIR=~/games/tron bash <(curl ...)`. The default is `%USERPROFILE%\Tron-Legacy-MPF-PuP` on
  Windows, `~/Tron-Legacy-MPF-PuP` elsewhere.
- **Branch / repository:** `TRON_BRANCH` and `TRON_REPO`, the same way. A folder that already holds a clone is
  updated with `git pull --ff-only` instead.
- **Private repositories:** if the assets (or the game) repository is private, the installer asks first for a
  GitHub token that can read it (github.com > Settings > Developer settings > Personal access tokens; a
  fine-grained token with Contents: read-only), instead of a password. Or set `TRON_GITHUB_TOKEN` before the line.
- **Options:** on macOS and Linux they go after the line, for example `bash <(curl ...) --no-monitor` to leave
  MPF Monitor out, `--proc` for the real machine, `--dry-run` to see the plan first. On Windows:
  `powershell -ExecutionPolicy Bypass -Command "& ([scriptblock]::Create((irm <the URL above>))) -NoMonitor"`.

On Windows, keep the folder out of OneDrive (the default, your home folder, is): OneDrive locks and
read-protects files while it syncs them. Setup copes with that, but it is slower and may leave stray files.

**Clone first** (if the lines above cannot fetch the script: they need the repository to be public, and a
private repository answers 404 to `curl`/`irm` without a token). Install Git, then:

```sh
git clone --recurse-submodules https://github.com/Ashram56/Tron-Legacy-MPF-PuP.git
cd Tron-Legacy-MPF-PuP
scripts/install/install_prereqs_linux.sh          # or install_prereqs_macos.sh
```

On Windows: `powershell -ExecutionPolicy Bypass -File scripts\install\install_prereqs_windows.ps1`. Git asks
for your GitHub login (or a token) when the repository is private.

## Play

From the install folder:

| | Windows | macOS / Linux |
|---|---|---|
| Start the game | `.venv\Scripts\python scripts\run.py` | `.venv/bin/python scripts/run.py` |
| ... with MPF Monitor | `... run.py --monitor` | `... run.py --monitor` |
| ... on the real machine (P-ROC) | `... run.py --hw proc` | `... run.py --hw proc` |

The three PuP windows open one under the other at the left of the screen: backglass, DMD, then topper. You
can resize each one, and keys pressed in any of them drive the game.

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
- `--dmd-font NAME`: the HD text font: `orbitron` (default, Tron style), `rajdhani` (clean, narrower), `godot` (Godot's
  default font), a `.ttf`/`.otf` file, or `rom` (the ROM's own dot fonts, smoothed). `--dmd-text-scale X`: its
  size, 1 = the ROM's capital height (default 0.85).
- `--dmd-text-color "#RRGGBB"`, `--dmd-text-glow X`: the HD text's colour and glow (0.75 by default; `--dmd-text-glow 0` turns it off).
- `--dmd-color off`: the HD animations in the DMD's single colour instead of the Serum colours.

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

## More

- [docs/pup.md](docs/pup.md): how the PuP Pack is wired in, and keeping up with the upstream game.
- [docs/development.md](docs/development.md): the workspace in detail (layout, setup options, running by hand,
  tests and checks, the asset sync).
- [docs/requirements.md](docs/requirements.md): what a computer needs, per OS.
- [docs/hardware.md](docs/hardware.md): virtual hardware and the P-ROC.
- [docs/vpx.md](docs/vpx.md): Visual Pinball X played by MPF.
- [docs/rom_differences.md](docs/rom_differences.md): where the game differs from the ROM, and ROM quirks that are not bugs.
- [docker/README.md](docker/README.md): the optional Docker setup for Linux hosts.
