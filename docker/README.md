# Running Tron Legacy MPF in Docker (Linux)

This is an optional alternative to the native install (`scripts/setup.py`, or the installers in
`scripts/install/`). One image holds the whole toolchain: Python 3.11 with MPF 0.80.1 and MPF Monitor 1.0.0,
Godot 4.6.3, and the libraries for X11, OpenGL/Vulkan, sound and the P-ROC's USB chip. Nothing is installed
on your computer except Docker.

The game runs as three containers. Each one opens its own window on your desktop, so you can put each window
on a different monitor:

| Service | What | Window |
|---|---|---|
| `setup` | One-shot job: generates the MPF config and media, fetches GMC, imports the Godot project. Skipped once everything is in place. | none |
| `godot` | GMC: draws the DMD, plays the sounds, BCP server on port 5050 | the DMD |
| `mpf` | The game (`hw_virtual`, or `hw_proc` on the real machine) | none (log, or text UI) |
| `monitor` | MPF Monitor: playfield, switches, lamps, events | MPF Monitor's windows |

`mpf` and `monitor` share `godot`'s network namespace, so BCP runs over localhost exactly as on a desktop (MPF
to GMC on 5050, MPF Monitor to MPF on 5051). No port is published to your network.

Your checkout is bind-mounted at `/workspace`. The generated config, sounds and Godot import land in your
checkout, git-ignored, and are the same files a native setup makes. The two setups can share a checkout.

## Requirements

- **Linux** with an X11 desktop, or Wayland with XWayland (GNOME, KDE Plasma and most others have it on by
  default). x86_64 or arm64.
- **Docker Engine** with the **compose plugin** (`docker compose version` should print v2.20 or newer):
  [docs.docker.com/engine/install](https://docs.docker.com/engine/install/). Use the Engine, not Docker
  Desktop: Docker Desktop runs containers in a VM that cannot reach your X server's socket. Add yourself to
  the `docker` group, or use `sudo`.
- **xhost** to let the containers open windows: package `x11-xserver-utils` (Debian/Ubuntu), `xorg-xhost`
  (Fedora, Arch).
- The repository with its asset submodule: `git clone --recurse-submodules ...`, or
  `git submodule update --init --depth 1 assets` in an existing clone.
- About 1.5 GB for the image, plus the ~300 MB the setup generates into the checkout.

## Quick start

From the repository root:

```sh
docker/tron.sh build          # once, and after pulling changes to scripts/toolchain.py (about 5 minutes)
docker/tron.sh                # = up: setup, then the DMD, MPF and MPF Monitor
```

Stop with Ctrl+C, or with `docker/tron.sh down` when started with `up -d`. MPF's log is in
`docker/tron.sh logs -f mpf`, and in `game/logs/` as usual.

`docker/tron.sh` is a thin wrapper around `docker compose -f docker/docker-compose.yml`. It:

- exports your user and group id (`TRON_UID`, `TRON_GID`), so the containers run as you. Files they write into
  the checkout stay yours, and the X and sound servers accept them.
- runs `xhost +SI:localuser:$USER`, which lets programs of your own user (the containers) open windows.
  Nobody else gets access. `xhost -SI:localuser:$USER` takes it back.
- adds `gpu.yml` when `/dev/dri` exists, `audio.yml` when the PulseAudio/PipeWire socket exists, and
  `proc.yml` when `TRON_HW=proc` (see below). `TRON_DRY=1 docker/tron.sh` prints the command it would run.

Any other arguments go to `docker compose`: `docker/tron.sh up -d`, `docker/tron.sh ps`,
`docker/tron.sh restart godot`, `docker/tron.sh run --rm --no-deps test shell` (a shell in the image).

### Without the wrapper

```sh
export TRON_UID=$(id -u) TRON_GID=$(id -g)
xhost +SI:localuser:$(id -un)
docker compose -f docker/docker-compose.yml build
export TRON_PULSE_SOCKET=$XDG_RUNTIME_DIR/pulse/native    # for audio.yml
docker compose -f docker/docker-compose.yml -f docker/gpu.yml -f docker/audio.yml up
```

Leave out `-f docker/gpu.yml` without `/dev/dri`, and `-f docker/audio.yml` without a sound server.

## Settings

Settings are environment variables. Set them per command (`DMD_SCREEN=1 docker/tron.sh`) or once in
`docker/.env`: copy `docker/tron.env.example`, which lists them all. `.env` is git-ignored.

| Variable | Default | What |
|---|---|---|
| `TRON_HW` | `virtual` | `proc` for the real machine |
| `TRON_MACHINE` | `pro` | `le`: a Tron Legacy LE's IO assignments ([hardware.md](../docs/hardware.md), "Pro or LE") |
| `TRON_FIBER_OPTICS` | off | `1`: drive the ramp light tubes on a Pro |
| `DMD_SCREEN` | | Monitor number for the DMD window: 0, 1, 2... |
| `DMD_FULLSCREEN` | `0` | `1`: the DMD fills that monitor |
| `DMD_POSITION` | | Window position in desktop pixels, e.g. `1920,0` |
| `DMD_RESOLUTION` | `1024x256` (from the project) | Window size, e.g. `1920x480` |
| `TRON_DMD` | `hd` | `classic`: the original 128x32 dots instead of the HD DMD (the main README, "The DMD: HD or classic") |
| `TRON_DMD_DOTS` | `0` | HD with a dot-matrix look: N round dots per DMD dot |
| `DMD_DISPLAY` / `MONITOR_DISPLAY` | `$DISPLAY` | Another X screen or X server for that window, e.g. `:0.1` |
| `GODOT_RENDERING_DRIVER` | `opengl3` | `vulkan` works too with the GPU |
| `GODOT_ARGS` | | More Godot options, e.g. `--always-on-top` |
| `FREE_PLAY` | on with `TRON_HW=virtual` | `0`: factory pricing, insert coins (key `5` in the DMD window). START begins a game without a coin otherwise. |
| `MPF_TEXT_UI` | `0` | `1`: MPF's text UI. Open it with `docker attach tron-legacy-mpf-mpf-1`; leave with Ctrl+P Ctrl+Q. |
| `TRON_GPU`, `TRON_AUDIO` | `1` | `0` keeps `docker/tron.sh` from adding the GPU or sound |
| `TRON_FORCE_SETUP` | `0` | `1` makes the `setup` service redo the setup (after an asset update, for example) |

## Several monitors

On a normal Linux desktop, all monitors form one X screen (one `DISPLAY`, for example `:0`). A window can go to
any monitor, and the X server numbers the monitors 0, 1, 2... in the order of your display settings.

**The DMD.** Godot takes the monitor and the window geometry on its command line, which the `godot` service
builds from the variables above:

```sh
DMD_SCREEN=1 DMD_FULLSCREEN=1 docker/tron.sh       # DMD fills monitor 1 (for example a 4:1 panel in the backbox)
DMD_POSITION=1920,0 DMD_RESOLUTION=1920x480 docker/tron.sh   # exact place and size on the desktop
```

**MPF Monitor.** MPF Monitor opens several windows (main, playfield, devices, events...). Each one remembers
where you last put it, in `game/monitor/settings.ini` in your checkout. Drag them to the third monitor once,
and they open there next time. To start over, delete that file.

**Separate X screens or servers.** If your monitors are separate X screens (`:0.0`, `:0.1`), as in some
cabinet setups with `Xinerama` off, or you run a second X server for the cabinet, give each window its own
display:

```sh
DMD_DISPLAY=:0.1 MONITOR_DISPLAY=:0.0 docker/tron.sh
```

A typical cabinet: the playfield TV runs MPF Monitor (or nothing), the backbox LCD shows the DMD full screen
with `DMD_SCREEN=1 DMD_FULLSCREEN=1`, and the operator monitor shows the logs.

## Sound

Godot plays through your desktop's sound server. `audio.yml` mounts its socket
(`$XDG_RUNTIME_DIR/pulse/native`) into the `godot` container. PipeWire desktops (Fedora, Ubuntu 22.10+, Arch
with `pipewire-pulse`) provide the same socket. The container runs with your user id, which is what the
server checks. Without the socket, the game runs silently.

## GPU

`gpu.yml` passes `/dev/dri` (Intel, AMD, and NVIDIA with Nouveau) and adds the groups that own it
(`video`/`render`, found by `docker/tron.sh`). The Mesa drivers in the image do the rest. For NVIDIA's
proprietary driver, install the NVIDIA Container Toolkit and add `gpus: all` to the `godot` service instead.
Without a GPU, Mesa renders in software (llvmpipe). For a 128x32 DMD that is fine, but it keeps one or two
CPU cores busy.

## The real machine (P-ROC)

1. On the host, once: let your user open the P-ROC's USB device:
   `sudo cp scripts/install/99-pinproc.rules /etc/udev/rules.d/ && sudo udevadm control --reload-rules && sudo udevadm trigger`
   (or `scripts/install/install_prereqs_linux.sh --proc --no-setup`). Then plug the board in.
2. Build the image with libpinproc and pypinproc, then start with the P-ROC overlay:

```sh
TRON_HW=proc docker/tron.sh build
TRON_HW=proc docker/tron.sh
```

`proc.yml` sets `TRON_HW=proc` for MPF (`config,hw_proc`) and Godot (`--proc-dmd`). It passes `/dev/bus/usb`
into the `mpf` container, with a device rule so that replugging the board works without a restart. Read
[docs/hardware.md](../docs/hardware.md) before the first power-up.

## Headless (CI, a server, a quick check)

No screen or X server is needed for these. Godot runs under Xvfb inside the container:

```sh
docker/tron.sh run --rm render-check      # boots Godot + MPF, captures the DMD into captures/, fails if blank
RENDER_SECONDS=30 docker/tron.sh run --rm render-check
docker/tron.sh run --rm test              # pytest -q tests
```

Both run `setup` first if needed. `captures/dmd_latest_x8.png` shows the last DMD frame.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Authorization required` / `cannot open display` | `xhost +SI:localuser:$(id -un)` (the wrapper does this). Check `echo $DISPLAY` on the host; under Wayland it must be set by XWayland (usually `:0`). |
| No window, `/tmp/.X11-unix` empty | Your session has no XWayland. Enable it, or log in to an X11 session. |
| `assets/ is empty` | `git submodule update --init --depth 1 assets` on the host. |
| `GMC (godot service) did not open port 5050` | `docker/tron.sh logs godot`. Usually the display (above) or a failed import: `TRON_FORCE_SETUP=1 docker/tron.sh run --rm setup`. |
| Files in the checkout owned by another user (uid 1000) | You ran `docker compose` without `TRON_UID`/`TRON_GID`. Run `sudo chown -R $(id -u):$(id -g) game captures`, then use the wrapper. |
| No sound | Is there a `$XDG_RUNTIME_DIR/pulse/native` socket? (`pactl info` on the host.) Is `audio` listed in the wrapper's `extras:` line? |
| Slow, a CPU core at 100 % | No GPU: check `ls /dev/dri` and that `gpu` is in the wrapper's `extras:` line. |
| `permission denied` on the P-ROC | The udev rule (above) is missing, or the board was plugged in before it was added: replug it. |
| `pull access denied for tron-legacy-mpf` | Build first: `docker/tron.sh build`. |

## Limits

- **Linux hosts only** for the windowed setup. The image itself is plain Linux, but the windows need an X
  server that the containers can reach through a socket.
- **Windows (WSL2 + WSLg)** should work in principle: WSLg provides `DISPLAY=:0`, `/tmp/.X11-unix` and a
  PulseAudio socket (`/mnt/wslg/PulseServer`, so set `TRON_PULSE_SOCKET` to it). This is **untested**, and the
  P-ROC would need `usbipd-win`. The native Windows install is simpler.
- **macOS** would need XQuartz with "Allow connections from network clients" and `DISPLAY=host.docker.internal:0`
  over TCP, software rendering only, and no sound. This is **untested**. Use the native macOS install.
- MPF's text UI needs `MPF_TEXT_UI=1` and `docker attach`. By default MPF logs to the console instead.
- The image is built for the CPU of the machine that builds it (x86_64 or arm64).
