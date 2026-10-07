# Tron Legacy MPF

Stern's **Tron Legacy Limited Edition** (code v1.74) rebuilt in the Mission Pinball Framework (MPF 0.80.1) with
a Godot DMD, from the reverse-engineered rules, media and effects in
[Ashram56/Tron-Legacy-LE-ROM-Decryption](https://github.com/Ashram56/Tron-Legacy-LE-ROM-Decryption). It runs on
Windows, macOS and Linux, on a desktop or on the real machine through a P-ROC.

## Install

Run the line for your OS in a terminal. It installs what is missing (Git, Python 3.11, the libraries), clones
this repository into a `Tron-Legacy-MPF-Private` folder in your home folder, and runs `scripts/setup.py`, which
downloads Godot, MPF and GMC and builds the media. The first run takes a while.

**Windows 10/11** (PowerShell or cmd):

```powershell
powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/Ashram56/Tron-Legacy-MPF-Private/main/scripts/install/install_prereqs_windows.ps1 | iex"
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
  macOS / Linux: `TRON_DIR=~/games/tron bash <(curl ...)`. The default is `%USERPROFILE%\Tron-Legacy-MPF-Private`
  on Windows, `~/Tron-Legacy-MPF-Private` elsewhere.
- **Branch / repository:** `TRON_BRANCH` and `TRON_REPO`, the same way. A folder that already holds a clone is
  updated with `git pull --ff-only` instead.
- **Private repositories:** git reads the private repositories (this one when it is private, and the assets if
  they are made private) with a GitHub token, never a password. The installer asks for it first, before the long
  installs (github.com > Settings > Developer settings > Personal access tokens; a fine-grained token with
  Contents: read-only). On Windows, paste it with a right-click: Ctrl+V does not paste into the hidden prompt. Or
  give it before the line, so nothing is asked: Windows `$env:TRON_GITHUB_TOKEN = "github_pat_..."` first,
  macOS / Linux `TRON_GITHUB_TOKEN=github_pat_... bash <(curl ...)`.
- **Options:** on macOS and Linux they go after the line, for example `bash <(curl ...) --no-monitor` to leave
  MPF Monitor out, `--proc` for the real machine, `--dry-run` to see the plan first. On Windows:
  `powershell -ExecutionPolicy Bypass -Command "& ([scriptblock]::Create((irm <the URL above>))) -NoMonitor"`.

On Windows, keep the folder out of OneDrive (the default, your home folder, is): OneDrive locks and
read-protects files while it syncs them. Setup copes with that, but it is slower and may leave stray files.

**If this repository is private**, the lines above get a 404: `curl` and `irm` need the token too. Give it
to them (in PowerShell on Windows; the same token is then used for git):

```powershell
$env:TRON_GITHUB_TOKEN = "github_pat_..."; irm -Headers @{Authorization = "token $env:TRON_GITHUB_TOKEN"} https://raw.githubusercontent.com/Ashram56/Tron-Legacy-MPF-Private/main/scripts/install/install_prereqs_windows.ps1 | iex
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
installer then asks for the GitHub token, as above, for the private repositories (git itself asks
for a token as the password when it clones a private repository).

## Play

From the install folder:

| | Windows | macOS / Linux |
|---|---|---|
| Start the game | `.venv\Scripts\python scripts\run.py` | `.venv/bin/python scripts/run.py` |
| ... with MPF Monitor | `... run.py --monitor` | `... run.py --monitor` |
| ... on the real machine (P-ROC) | `... run.py --hw proc` | `... run.py --hw proc` |

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
- `--dmd classic`: the original 128x32 dots instead of the HD DMD (the default on the desktop); `TRON_DMD=classic`
  in the environment does the same for every run.
- `--dmd-size 1920x480`: the DMD window's size (HD scales to any size). `--dmd-dots 2`: an HD dot-matrix look.
- `--dmd-tint orange`: the HD DMD in the original orange instead of Tron blue.
- `--dmd-text-color "#RRGGBB"`, `--dmd-text-glow X`: the HD text's colour and glow (none by default).

[docs/development.md](docs/development.md#running) has the details of the HD DMD.

## Update

From the install folder: `git pull`, then `python3 scripts/setup.py` (Windows: `py -3.11 scripts\setup.py`).
You can also run the install line again. Both are safe to repeat; setup only redoes what changed.

## More

- [docs/development.md](docs/development.md): the workspace in detail (layout, setup options, running by hand,
  tests and checks, the asset sync).
- [docs/requirements.md](docs/requirements.md): what a computer needs, per OS.
- [docs/hardware.md](docs/hardware.md): virtual hardware and the P-ROC.
- [docker/README.md](docker/README.md): the optional Docker setup for Linux hosts.
