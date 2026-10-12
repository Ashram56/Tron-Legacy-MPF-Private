# Jetson Xavier NX: findings

Everything learned running Tron Legacy MPF with the PuP Pack on a Jetson Xavier NX: the set-up that works, what
was wrong and how it was fixed, the settings measured, and what is left. Details: video decoding fixes in
[README.md](README.md), measuring and every setting's figures in [performance.md](../performance.md), reports for
other projects in [upstream_issues/](../upstream_issues/README.md).

**Board:** Jetson Xavier NX Developer Kit (t194), L4T R35.6.4 / JetPack 5.1.4, Ubuntu 20.04.6, Godot 4.6.3,
Vulkan with the Mobile renderer. Tested 2026-10-08 to 2026-10-09.

## Result

The whole game (`full_game_to_portal`, 620 s) on the cabinet layout, nvpmodel mode 5:

| | As installed | First fixes, one screen | Now (two screens) |
|---|---|---|---|
| FPS | 5.4 (30 s clip) | 52.6 | 57.8-57.9 |
| Longest stall | - | 2.4 s | 0.63 s (start-up) |
| Video frames skipped | - | 856 | 48 |

Light cycle DMD background on (PuP PR 14): 57.5 FPS against 57.7 with the plain frame, +0.4 W, about +20 MB video
memory. Board RAM peaks at 3.4 GB of 6.8 GB with Orbitron, no swap.

## Set-up

1. **Install:** the Linux one line, then `bash scripts/install/install_jetson_hwdec.sh` (libnvmpi with our patch,
   NVIDIA packages pinned to the board's own L4T release, no idle blanking), then
   `bash scripts/install/jetson_selftest.sh --stock` (must pass every check). [README.md](README.md) "To bring one
   up".
2. **Session:** X11 with openbox, autologin on tty1, no display manager. Godot places one window per monitor only
   on X11.
3. **Power:** `sudo nvpmodel -m 5` (10 W desktop, 4 cores at 1.9 GHz; the module's default) or 8 (20 W, level with
   5, twice the GPU clock in reserve). Per-core speed matters more than the number of cores: Godot's main thread is
   the critical path. Modes 3 and 4 are not playable. `jetson_clocks` gains nothing.
4. **Sound:** the devkit's ALSA default (`/etc/asound.conf`) is the APE I2S card, which has nothing connected, so
   Godot had no sound. `install_jetson_hwdec.sh` writes a `~/.asoundrc` sending the default to HDMI (`hw:HDA,7`
   through dmix) when no PulseAudio or PipeWire is installed.
5. **Media:** `scripts/setup.py` (or `scripts/gen_media.py`) after every update: the HD effect frames are imported
   VRAM-compressed, and the clean fonts are baked (about 100 s on the Xavier NX, 65 MB, `game/fonts_ttf/baked/`).

## Screens

- **The devkit's DisplayPort has no DP++ dual mode:** a passive DP to HDMI adapter fails (AUX errors, "edid read
  prepare failed", output disconnected), and the NVIDIA driver refuses a forced mode on a disconnected output
  (`xrandr --addmode`: BadMatch). Use a native DP monitor or an active adapter (one with a converter chip). The
  USB-C port has no video.
- **Bar panel** (LTA149B780F, 14.9", 1280x390, generic controller board) on HDMI: its EDID reads fine, native mode
  1280x390 at 59.60 Hz (39.00 MHz, 1600x409 total; range 50-76 Hz), stereo LPCM announced.
- **60 Hz on the bar panel is not possible with this driver:** an EDID copy with the pixel clock raised to 39.26 MHz
  (59.99 Hz) installed with `CustomEDID` was accepted by X but ignored; only a device-tree change could do it. The
  effect of 59.6 Hz: vsync follows the backglass monitor (60 Hz), so the DMD shows one frame twice about every
  2.5 s, which is hard to see.
- **Vsync per window:** on the R35 X11 Vulkan driver each vsync'd window waits for its own vertical blank, so four
  windows made every frame four refreshes long. `pup_player.gd` keeps vsync on the backglass window only.
- **Cabinet layout** (backglass and topper on the monitor, the PuP DMD on the bar panel) goes in the untracked
  `game/pup.local.cfg`, never in `game/pup.cfg`. For the 1280x390 bar panel, the DMD frame cropped to the DMD panel
  alone, so it centres vertically (an example; the monitor index depends on the wiring):

  ```ini
  [pup]
  layout="manual"

  [dmd]
  screen=1                     ; the bar panel's monitor index
  fullscreen=true
  borderless=true
  size=[960, 193]
  frame_crop=[0, 1126, 1920, 386]
  ```

  A DMD-only screen (no backglass monitor): `[backglass] enabled=false`.

## Video decoding (NVDEC)

Hardware decoding through jetson-ffmpeg's `h264_nvmpi` in GDE GoZen. Ten fixes, all in [README.md](README.md):

- jetson-ffmpeg bugs that are on JetPack 5 too: a loop or seek hung the next decode (fix 1), closing a decoder took
  about 1 s (fix 2), several decoders starting at once segfaulted (fix 4). Self-test results against stock
  jetson-ffmpeg in [README.md](README.md) "Xavier NX checklist".
- 5 FPS as installed (fix 9): libnvmpi mapped every plane of every frame for the CPU (11 ms of kernel time per
  1080p frame on R35); decoding on the main thread fell behind; four vsync'd windows. 55.5 FPS after.
- Frames decoded at the size they are shown at, as NV12 (fix 10): 4 to 8 times fewer pixels per frame.
- Up to 3 frames decoded ahead per video on worker threads; videos with sound follow the audio clock.
- Headroom: three 1080p30 videos at once use about a fifth of NVDEC (430-446 fps in total when decoding flat out).
  tegrastats on R35 shows only the decoder's clock, not its load.

## Godot settings (all platforms)

Measured with the clip suite in mode 5; figures in [performance.md](../performance.md) "Settings measured".

| Setting | Where | Effect on the Xavier NX |
|---|---|---|
| Separate render thread (`thread_model=2`) | `game/project.godot`; off: `run.py --no-render-thread` or `TRON_RENDER_THREAD=0` | Main thread 27-28% of a core instead of 44-46%; +2.3 FPS. Logs harmless glyph-cache errors (Godot bug) |
| Pipeline cache saved while running (`save_chunk_size_mb=0.1`) | `game/project.godot` | With the render thread the save at exit fails, so every start recompiled: 4-5 s stall at the first light cycle derez. Gone from the second start |
| Worker pool `low_priority_thread_ratio=0.5` | `game/project.godot` | Video switch stalls 1.3 to 0.6-0.95 s |
| Effects with 40+ frames preloaded | `tron/dmd/preload_min_frames` | Deff 86 0.89 s to under 0.1 s; +200 MB. Preloading every effect: +130 MB video memory, 5 s longer start, not kept |
| HD effect frames VRAM-compressed (ETC2) | `scripts/gen_media.py` | 7 to 1.5 ms per frame loaded, half the memory; no visible difference |
| Letter glows on worker threads | `game/tron/letter_panel.gd` | Deff 94 380 ms to 25-36 ms; the glow costs nothing when drawn |
| Clean fonts baked at setup | `game/tools/bake_fonts.gd` | Orbitron froze the game 20-30 s (MSDF made on the main thread); now 55.2 / 57.2 FPS, the same as the ROM font |
| Core pinning (Godot's main thread alone on the last core) | `scripts/run.py`, Linux 4+ cores, `TRON_PIN=0` off | +1.5 FPS, a third fewer late frames |

## Costs

- **Orbitron** (the default HD font) against the ROM font: about +1 W, +450 MB Godot memory, +150 MB Godot video
  memory, mostly its wide glow outline copy (`WIDE_RANGE=192` in `game/tron/rom_text_hd.gd`). A smaller range
  costs less and gives a tighter glow.
- **Light cycle background:** +0.4 W, about +20 MB video memory, GPU about 45%.
- **Memory, full game:** Godot resident 972 MB at 10 s, 1.65 GB peak; Godot video memory peak 466 MB; board RAM
  3.0 GB average, 3.4 GB peak with Orbitron.

## Known leftovers

- A start-up stall of about 0.6 s, and short stalls at some scene switches while a video opens.
- About 170-190 frames per 10-minute game held 3 vblanks or more.
- Decoder leftovers in [README.md](README.md) "Known leftovers" (lost trailing frames on a recreated decoder, a
  0.1 s hold at some loop points).

## Tools

- `bash scripts/perf/run.sh --suite 5`: the trouble-spot clips with frame, video, A/V, memory and power figures
  ([performance.md](../performance.md)).
- `scripts/install/jetson_selftest.sh --stock`: the decoder checks, patched against stock.
- A stuck Godot: `sudo gdb -batch -p $(pgrep -f Godot_v | head -1) -ex 'thread apply all bt 25'`.
