# System requirements

What a computer needs to run this workspace: MPF (the game), Godot with the GMC add-on (the DMD and sound),
optionally MPF Monitor (the virtual playfield) and the Multimorphic P-ROC (the real machine). Every version
below is what `scripts/setup.py` installs. They are pinned in `scripts/toolchain.py`.

The quickest route is the installer for your OS. It installs only what is missing and then runs
`scripts/setup.py`:

| OS | Command (in the repository) |
|---|---|
| Windows 10/11 | `powershell -ExecutionPolicy Bypass -File scripts\install\install_prereqs_windows.ps1` |
| macOS 12+ | `scripts/install/install_prereqs_macos.sh` |
| Linux | `scripts/install/install_prereqs_linux.sh` |

Each installer takes `--dry-run` (`-DryRun` on Windows), which prints the plan and changes nothing. With
`--proc` (`-Proc`) it also prepares the P-ROC. Arguments after `--` go to `setup.py`, for example
`-- --skip-media`. There is also a Docker option for Linux hosts: [docker/README.md](../docker/README.md).

## Summary

| | Windows | macOS | Linux |
|---|---|---|---|
| OS version | Windows 10 (1809+) or 11, 64-bit | macOS 12 Monterey or newer | glibc 2.28+ (Ubuntu 20.04+, Debian 11+, Fedora 36+, any current Arch). MPF Monitor's Qt 6.11 wheels need glibc 2.34 on x86_64 (Ubuntu 22.04+, Debian 12+) and 2.39 on arm64; on older systems pip picks an older Qt. |
| CPU | x86_64, or ARM64 (P-ROC: x86_64 only) | Intel or Apple silicon | x86_64 or arm64 (aarch64) |
| Python | **3.11** (3.10 to 3.14 work) | **3.11** | **3.11** |
| Git | 2.x | 2.x (Xcode Command Line Tools or Homebrew) | 2.x |
| Graphics | Vulkan 1.0 or OpenGL 3.3 | Metal (directly, or through MoltenVK) | Vulkan 1.0 or OpenGL 3.3 (Mesa 20+ is fine; Mesa's software renderer works too) |
| Sound | any (WASAPI) | any (CoreAudio) | PulseAudio or PipeWire (pipewire-pulse), else ALSA |
| Disk | 2 GB free (3 GB with MPF Monitor) | same | same |
| RAM | 4 GB | 4 GB | 4 GB |
| Network | for the first setup only | same | same |

## Python

**Use Python 3.11.** It is the version CI tests on all three OSes and the one the installers install.

MPF 0.80.1 accepts Python 3.10 to 3.14 (`Requires-Python: >=3.10,<3.15` in its package), so another version
in that range also works. `setup.py` refuses anything older than 3.10. Some notes on other versions:

- `ruamel.yaml.clib` is pinned to 0.2.14 for Python before 3.13. Version 0.2.15 renamed its metadata, and
  MPF's `pkg_resources` check then stops `mpf` from starting once MPF Monitor is installed (`scripts/toolchain.py`).
- MPF pins `setuptools~=72.2`, which `pkg_resources` comes from. MPF's dependencies have wheels for 3.11 on
  every OS listed here, so no compiler is needed.
- MPF's bundled P-ROC module for Windows has builds for Python 3.8 to 3.14 (x64 and 32-bit).

The installers find or install 3.11 like this:

| OS | Where Python 3.11 comes from |
|---|---|
| Windows | `winget install Python.Python.3.11` (current user), else the python.org 3.11.9 installer (the last 3.11 release with Windows installers). The script looks for it through the `py` launcher, never through the Microsoft Store's `python` stub. |
| macOS | `brew install python@3.11` with Homebrew, else the python.org 3.11.9 universal2 `.pkg` (asks for an admin password). The script then runs its "Install Certificates" step, because python.org builds have no CA certificates. |
| Debian 12 | the distribution's `python3.11`, `python3.11-venv` and `python3.11-dev` |
| Ubuntu 22.04 / 24.04 | the deadsnakes PPA (Ubuntu's own 22.04 package is a 3.11.0 release candidate, and 24.04 has none) |
| Fedora / RHEL 9 | `dnf install python3.11 python3.11-devel` |
| Arch, Debian 13, anything else | a standalone CPython 3.11 build installed with [uv](https://docs.astral.sh/uv/). The uv binary comes from its PyPI wheel. The build goes to `~/.local/share/uv/python`: no compiler, no system changes, no pyenv. |

On Windows the installer also puts Python 3.11 and its `Scripts` folder first in your user PATH (winget's
per-user Python does not), turns on long path support (`LongPathsEnabled`, a machine setting: Windows asks
for administrator rights once) and sets `git config --global core.longpaths true`. Open a new terminal
afterwards so it sees the new PATH.

On Linux, `--python-any` makes the installer accept any 3.10 to 3.14 already installed.

## Git and the asset submodule

`assets/` is a git submodule (the ROM decryption repository, about 300 MB). Clone with
`git clone --recurse-submodules ...`. Otherwise `setup.py` runs `git submodule update --init --depth 1 assets`
itself. Git LFS is not needed: setup sets `GIT_LFS_SKIP_SMUDGE=1`.

## Godot 4.6.3 (GMC 1.0.0)

`setup.py` downloads the official Godot 4.6.3 build for the OS and CPU into `tools/godot/` (about 130 MB
unpacked). GMC 1.0.0 goes into `game/addons/mpf-gmc/`. The project uses Godot's Mobile renderer, which draws
with Vulkan and falls back to OpenGL 3.3. The render check forces OpenGL with `--rendering-driver opengl3`.

- **Windows:** any GPU driver with Vulkan 1.0 or OpenGL 3.3 (Intel HD 4000 and newer, AMD GCN, NVIDIA Kepler).
  The Godot build is self-contained.
- **macOS:** the universal build runs natively on Intel and Apple silicon (Metal, directly or through
  MoltenVK). It is signed by the Godot project.
- **Linux:** Godot loads these libraries at run time. The Linux installer installs them (Debian/Ubuntu names):
  `libx11-6 libxcursor1 libxinerama1 libxrandr2 libxi6 libxext6 libxrender1 libxkbcommon0`, `libgl1 libegl1
  libgl1-mesa-dri libglx-mesa0`, `libvulkan1 mesa-vulkan-drivers`, `libwayland-client0 libwayland-cursor0
  libwayland-egl1 libdecor-0-0`, `libfontconfig1`, `libasound2 libpulse0`, `libdbus-1-3 libudev1`. Godot uses
  X11, or XWayland on a Wayland desktop.
- **Without a screen** (a server, CI): Xvfb (`xvfb`, `xauth`). `run.py` and the render check then start
  Godot under `xvfb-run`, which renders on the CPU (Mesa llvmpipe). The installer adds Xvfb when `DISPLAY` is
  not set, or with `--xvfb`.

## Sound

GMC plays the game's sounds (about 100 MB of generated audio in `game/sounds/`) through Godot. Any working
audio output is enough: WASAPI on Windows, CoreAudio on macOS, PulseAudio or PipeWire on Linux (with
`pipewire-pulse`, which current desktops ship). Godot falls back to ALSA, then to silence. On the real machine
the SAM sound board is gone (docs/hardware.md), so the PC feeds an amplifier.

## MPF Monitor (installed by default; `--no-monitor` leaves it out)

`mpf-monitor` 1.0.0 is a PyQt6 application. pip installs `PyQt6` and `PyQt6-Qt6` (about 250 MB) from wheels.
Qt brings its own libraries on Windows and macOS. On Linux it needs the X11/xcb libraries, which the
installer adds unless given `--no-monitor`: `libglib2.0-0 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4
libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1`
(Fedora: `glib2 libxkbcommon-x11 xcb-util-cursor xcb-util-image xcb-util-keysyms xcb-util-renderutil
xcb-util-wm`).

mpf-monitor 1.0.0 on PyPI (wheel and sdist, both published 2026-10-03) is missing its four Qt Designer
files (`mpfmonitor/core/ui/*.ui`). Without them, `mpf monitor` stops with
`searchable_tree.ui: No such file or directory`. `setup.py` copies them from the release's git tag
(`toolchain.MPF_MONITOR_UI_URL`) into the venv. It does nothing once a fixed release ships them.

## The P-ROC (optional: `--proc`, the real machine)

MPF talks to the P-ROC through `pypinproc` (Python module `pinproc`), which uses `libpinproc`. That uses
FTDI's USB library.

| OS | pypinproc | USB driver |
|---|---|---|
| Windows (x64) | Comes with MPF (`mpf/platforms/pinproc/windows/pinproc.cp3xx-win_amd64.pyd`). It needs the **Visual C++ 2015-2022 runtime** (`MSVCP140.dll`; `-Proc` installs it) and FTDI's `ftd2xx.dll`. | FTDI **D2XX** driver from [ftdichip.com](https://ftdichip.com/drivers/d2xx-drivers/), installed by hand. `-Proc` checks for it. Windows on ARM: no pypinproc build. |
| macOS | The module MPF bundles (`mpf/platforms/pinproc/osx/pinproc.so`) is an old i386/x86_64 build linked against `libpinproc`, `libftdi1` and `libusb-0.1` dylibs. It does not load on Apple silicon. `--proc` builds libpinproc and pypinproc instead (Homebrew `cmake pkg-config libusb libusb-compat libftdi`). | libusb/libftdi from Homebrew. If macOS claims the board as `/dev/tty.usbserial*`, install FTDI's D2xxHelper and reboot (libpinproc's README). |
| Linux | MPF has none. `--proc` builds [libpinproc](https://github.com/preble/libpinproc) (dev branch, pinned commit) as a shared library into `/usr/local`, and [pypinproc](https://github.com/missionpinball/pypinproc) (the Python 3 port) into `.venv`. Build packages: `build-essential cmake pkg-config libusb-1.0-0-dev libusb-dev libftdi1-dev`. | libftdi1 and libusb-1.0 (no kernel driver to install). The udev rule `scripts/install/99-pinproc.rules` lets non-root users open the board (FTDI 0403:6001 FT245RL and 0403:6015 FT240X). `--proc` installs it to `/etc/udev/rules.d/`. |

`scripts/install/build_pinproc.sh` does the build on Linux and macOS and is safe to re-run. P-ROC firmware
2.14 or newer is recommended (MPF warns about older firmware). docs/hardware.md covers the wiring and the
first power-up.

## Network

The first setup downloads from: pypi.org and files.pythonhosted.org (MPF and the Python packages),
github.com (Godot release, GMC, the asset submodule, libpinproc/pypinproc with `--proc`),
raw.githubusercontent.com (MPF Monitor's `.ui` files), and depending on the route python.org, Homebrew,
winget or your distribution's mirrors. After that, nothing is downloaded. At run time everything talks over
localhost only: GMC on TCP 5050, MPF's BCP server for MPF Monitor on 5051. On Windows, "private networks" is
enough when the firewall asks.

## Disk

| What | Size |
|---|---|
| Repository + asset submodule | ~450 MB |
| `.venv` (MPF, pillow, pytest) | ~110 MB (+ ~250 MB with MPF Monitor) |
| `tools/godot/` | ~130 MB (+ a 70 MB download during setup) |
| Generated config and media (`game/sounds`, `game/media`, ...) | ~220 MB (of which ~100 MB the HD DMD frames, grey and colour, and fonts) |
| HD upscale cache (`.cache/dmd_hd/`, makes regenerating the HD frames quick; with the colour frames) | ~100 MB |
| Godot import cache (`game/.godot/`) | ~160 MB |
| Docker image (optional) | ~1.5 GB |

## Performance

MPF, Godot and MPF Monitor together use a few hundred MB of RAM. The DMD is 128x32, so any GPU of the last ten
years is plenty; the HD DMD (the default on the desktop) draws the same layout at the window's resolution, with
1024x256 frames for the animations, which is still light work for any GPU. Building the HD frames
(`gen_media.py`, during setup or after a pull) takes about a minute of CPU the first time, seconds afterwards. Without a GPU (Mesa's software renderer, Xvfb, a container without `/dev/dri`), Godot keeps
one to two CPU cores busy drawing the window. That works, but use the GPU when you have one.
