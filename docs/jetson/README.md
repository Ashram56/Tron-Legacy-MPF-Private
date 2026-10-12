# Jetson: hardware video decoding fixes

This page lists every change we carry so that the PuP Pack's videos play with the Jetson's hardware decoder (NVDEC)
without freezes or crashes: what was wrong, the fix, where it lives and how it was checked. Start here when
bringing up another Jetson, such as the Xavier NX. Everything else learned on the Xavier NX (screens, power, Godot
settings, costs): [xavier_nx.md](xavier_nx.md).

**Tested:** Jetson AGX Orin Developer Kit (t234), L4T R36.4.3 / JetPack 6.2, Ubuntu 22.04, `oot` kernel, Godot
4.6.3, one 1920x1080 DisplayPort screen with the three PuP windows on it (git tag `jetson-agx-orin-l4t-r36.4.3`).
**Tested:** Jetson Xavier NX Developer Kit (t194), L4T R35.6.4 / JetPack 5.1.4, Ubuntu 20.04.6, X11 + openbox
(no display manager), Godot 4.6.3, one 1920x1080 HDMI screen with the three PuP windows on it, HDMI audio: decoder
self-test and both game scenarios in five power modes (2026-10-09). Use nvpmodel mode 5 (10W desktop, the module's
default) or 8 (20W): see [Xavier NX power modes](#xavier-nx-power-modes).

## The video stack

| Layer | What it is | Ours | Built by |
|---|---|---|---|
| PuP screens | `game/pup/pup_screen.gd`, `game/pup/gozen_player.gd` | changed | - |
| GoZen player script | `pup_addons/gde_gozen/video_playback.gd` (GDE GoZen's `VideoPlayback` node) | changed | - |
| GoZen GDExtension | `pup_addons/gde_gozen/bin/libgozen.linux.*.so`, GDE GoZen at `f9448619` + FFmpeg 7.1 linked in | `scripts/gozen/gozen.patch` | `scripts/build_gozen.sh` (Docker) |
| FFmpeg nvmpi wrapper | jetson-ffmpeg's `*_nvmpi` decoders, compiled into GoZen's FFmpeg (`nvmpi_dec.c`) | `scripts/gozen/nvmpi_flush.patch` (`ffmpeg/` part) | `scripts/build_gozen.sh` |
| libnvmpi | jetson-ffmpeg at `8d70c17` (v3.10.0), installed in `/usr/local/lib`, loaded by the wrapper at run time | `scripts/gozen/nvmpi_flush.patch` (`src/` part) | `scripts/install/install_jetson_hwdec.sh` |
| NVIDIA | V4L2 decoder, NvMMLite, NvBufSurface (L4T BSP, `nvidia-l4t-multimedia*`) | - | JetPack |

The wrapper and libnvmpi share one patch file. `build_gozen.sh` and `install_jetson_hwdec.sh` both apply the whole
file to their jetson-ffmpeg checkout, so GoZen's FFmpeg and the board's libnvmpi always carry the same fixes.
Changing only the `src/` part needs a new install on the board but no GoZen rebuild. Changing the `ffmpeg/`
part (or `gozen.patch`) needs `bash scripts/build_gozen.sh arm64` and committing the new `.so` (fix 10: build from
a clean work folder).

## Fixes

### 1. Looping or seeking a video froze the game forever (FFmpeg wrapper)
- **Symptom:** the first loop or seek of any video hung the next decode; every time; mp4, mkv and ts.
- **Cause:** `avcodec_flush_buffers()` resets libnvmpi's decoder in place (STREAMOFF/STREAMON). On L4T R36 the
  V4L2 decoder sends no new resolution-change event for the same stream, so the capture plane never restarts and
  `put_packet()` blocks in the OUTPUT plane's `dqBuffer()`. Re-arming the capture plane in place was tried: its
  DQBUF then fails with `EINVAL`.
- **Fix:** `nvmpi_flush_decoder()` closes the decoder and `nvmpi_decode()` creates a new one from the saved
  `nvDecParam` with the next packet (lazily, primed with the extradata again). A flush with nothing decoded since
  the decoder was created does nothing (GoZen flushes right after opening and right before freeing).
- **Checked:** 3 loops and 3 mid-stream seeks pass for mp4/mkv/ts; `ffmpeg -stream_loop 9 -c:v h264_nvmpi`
  completes. Report: [upstream_issues/jetson-ffmpeg-flush-hang.md](../upstream_issues/jetson-ffmpeg-flush-hang.md).

### 2. Closing a decoder took about 1 s (libnvmpi)
- **Symptom:** every video switch froze the whole game for 1 to 2.5 s (software decoding: about 0.1 s).
- **Cause:** a decoder that has not output a frame yet (just created, or recreated by fix 1) waits out two
  500 ms `dqEvent()` timeouts in its capture thread before `close()` can join it.
- **Fix:** a `closing` flag set first in `nvmpi_decoder_close()`; the capture thread's event wait runs in 50 ms
  slices and skips its extra 500 ms "race guard" wait when closing.
- **Checked:** close 1061 ms → 55 ms. Report:
  [upstream_issues/jetson-ffmpeg-slow-close-crash.md](../upstream_issues/jetson-ffmpeg-slow-close-crash.md).

### 3. Closing a decoder mid-video sometimes crashed (libnvmpi)
- **Symptom:** SIGSEGV in NVIDIA's decoder thread (`libnvmmlite_video.so`), inside `v4l2_close` or after the
  buffers were freed; 9 of 100 runs of the repro with stock libnvmpi.
- **Cause:** the decoder was torn down while it was still decoding queued bitstream, and its CAPTURE DMA buffers
  were freed while the decoder device was still open.
- **Fix:** in `nvmpi_decoder_close()`, wait at most 300 ms for the OUTPUT plane to drain (the capture thread drops
  frames instead of waiting for the frame pool while closing), then stop the capture plane, delete the decoder,
  and only then free the CAPTURE buffers and the frame pool.
- **Checked:** 0 crashes in 100 runs. Same report as fix 2.

### 4. The game froze when several screens switched videos at once (libnvmpi)
- **Symptom:** in a long game, one screen's video stopped, and Godot's main thread waited for it forever.
- **Cause:** with decoders created and closed from several threads, a decoder's CAPTURE DQBUF now and then fails
  with `EINVAL`. Its capture thread exits, nothing returns OUTPUT buffers, and `put_packet()` blocks forever.
  4 of 6 runs of the 3-thread repro hung, with stock libnvmpi too.
- **Fix:** a global mutex `nvmpi_dec_setup_mutex` serialises decoder creation, teardown (after the capture thread
  is joined) and `respondToResolutionEvent()`. When the capture thread stops on an error, it STREAMOFFs the
  OUTPUT plane, which wakes a blocked `put_packet()` with an error, and `put_packet()` fails at once while the
  decoder is in error. GoZen then ends or restarts that video with a new decoder (fix 1).
- **Checked:** 0 hangs in 20 runs (3 decoders recovered from the error). Report:
  [upstream_issues/jetson-ffmpeg-concurrent-decoders-hang.md](../upstream_issues/jetson-ffmpeg-concurrent-decoders-hang.md).

### 5. Video work stalled Godot's main thread (GoZen player script)
- **Symptom:** every stall above hit all three PuP windows and the DMD, because they are drawn by the same
  Godot process.
- **Fix, in `video_playback.gd`:**
  - the audio stream opens on the worker thread with the video;
  - `_process()` takes the opened video only once `WorkerThreadPool.is_task_completed()` (it used to wait on the
    first frame);
  - `close()` hands the closed `GoZenVideo` to a worker task, so its decoder is freed there; `_exit_tree()` waits
    for those tasks;
  - new `restart()`: back to the first frame on a worker task, showing the current frame meanwhile. Looping uses
    it, and so does `gozen_player.gd`'s `play()`.
  - `close()` never waits for an open or a restart still running: the video goes to the worker that frees it once
    that task is done (`_open_video()` and `_seek_start()` take the video they work on). A playlist switch during a
    loop restart froze every screen 0.3-0.6 s (2026-10-12, Xavier NX, docs/performance.md).
- **Checked:** with timing logs over a 2-minute game, the longest video step on the main thread went from
  2.4 s to 10 ms. Report: [upstream_issues/gde-gozen-main-thread-stalls.md](../upstream_issues/gde-gozen-main-thread-stalls.md).

### 6. The topper went black between videos (PuP screens)
- **Cause:** `pup_screen.gd` stopped the player, which hides the picture, before opening the next video.
- **Fix:** with GoZen it opens the next video directly; the previous video's last frame stays up until the next
  one's first frame is ready.

### 7. Hardware decoder selection and safe fallback (GoZen, earlier PRs)
- `gozen.patch`: GoZen asks FFmpeg for `<codec>_nvmpi` first, then the software decoder; `GOZEN_HWDEC=0` forces
  software.
- `gozen_player.gd`: no decoder device in `/dev` (`nvmap` plus `nvhost-nvdec*` or `v4l2-nvdec`) → software
  decoding, because NVIDIA's libraries crash rather than fail without them.

### 8. Install and cabinet (install scripts, run.py)
- `install_jetson_hwdec.sh` pins NVIDIA's packages to the board's own L4T release (the r36.4 apt repo also offers
  36.4.7), keeps existing config files instead of stopping on a dpkg prompt, reads the whole loader cache when it
  looks for libnvmpi, and applies `nvmpi_flush.patch` before building libnvmpi.
- No blanking mid-game: the install turns off GNOME's idle blanking, dimming, lock and suspend (`--keep-blanking`
  leaves them), and `run.py` runs `xset s off -dpms`. Without both, the screen went black after 5 minutes.
- GDM automatic login and an X11 session (Godot places one window per monitor only on X11): [pup/README.md](../pup/README.md).

### 9. 5 FPS on the Xavier NX (libnvmpi, GoZen player script, PuP windows)
Measured on the Xavier NX (L4T R35.6.4), `clu_hurryup` for 30 s: 5.4 FPS as installed, 55.5 FPS (median frame
16.67 ms, GPU 32%, 7.3 W) with all three fixes. Without the PuP it already ran at 56 FPS.
- **libnvmpi:** each frame mapped and unmapped every plane of its buffer for the CPU, about 11 ms of kernel time per
  1080p frame on R35. Now a buffer's planes are mapped once and unmapped when the buffer is destroyed
  (`nvmpi_flush.patch`): decode 74 -> 203 fps, CPU 17 -> 4 ms per frame.
- **`video_playback.gd`:** the next frame is decoded on a worker task, one frame ahead, so Godot's main thread only
  uploads it; a frame not ready yet is shown late instead of waited for. Before, three videos decoding on the main
  thread fell behind, and the catch-up decoding made it worse. Decode tasks never seek (at most 1 s of frames per
  task) and are high priority: a catch-up `seek_frame()` near the end of a clip retried for minutes on the one thread
  Godot gives low-priority tasks here, and the game froze (9 min at 10W, 2 cores).
- **`pup_player.gd`:** vsync stays on the backglass window only. On the R35 X11 Vulkan driver each vsync'd window
  waits for its own vertical blank, so four windows made every frame four refreshes long (67 ms). The DMD and
  topper windows can tear in principle; they redraw every frame anyway.
- **Audio (Xavier NX devkit):** the system ALSA default (`/etc/asound.conf`) is the APE I2S card, which has nothing
  connected, so Godot fell back to no sound. A `~/.asoundrc` sending the default to HDMI (`hw:HDA,7` through dmix)
  fixes it; `install_jetson_hwdec.sh` writes it when no PulseAudio or PipeWire is installed, and keeps an existing
  one.

### 10. Frames decoded at the size they are shown at, as NV12 (GoZen, nvmpi decoder options)
jetson-ffmpeg's nvmpi decoders can scale in hardware (the VIC, option `resize=WxH`) and output NV12
(`output_format=nv12`). `gozen.patch` adds `GoZenVideo.set_target_size()`: with an nvmpi decoder, frames come as
NV12 and, when the video is shown smaller than its file, scaled down to that size (aspect kept, never up). NV12 is
used natively (Y as R8, UV as one RG8 plane; the two YUV shaders take a `nv12` switch), where any format but
YUV420P used to go through a CPU conversion. `video_playback.gd` asks for it with `decode_to_display_size`, which
`gozen_player.gd` turns on: on one 1920x1080 screen holding the three PuP windows, a 1080p video is decoded at
868x488 (backglass) or 868x254 (topper), 4 to 8 times fewer pixels to copy and upload per frame. Godot's main thread
44-46% of a core instead of 51-55%; clip suite 52.9 / 54.7 -> 53.4 / 55.7 FPS, frames over 2 vblanks 19 / 33 -> 18 /
26 (docs/performance.md). With a `.so` without these methods the script keeps the three-plane path.

Rebuilding GoZen: start from a clean work folder (`scripts/build_gozen.sh` with a fresh `GOZEN_WORK`, or delete its
`godot_cpp/bin` and object files). The committed `.so` files are the cross build on x86_64 (reproducible from any
x86 machine); a native arm64 build on a Jetson has the same code, data and symbols and differs only by Ubuntu's
SystemTap probe sections (`.note.stapsdt`, `.stapsdt.base`: its native libstdc++ has them, the cross one does not).
Record the `.so`'s sha256 in the commit message.

## Known leftovers
- A recreated decoder can lose up to about 10 trailing frames when it drains at the end of a video.
- About every 10 to 20 s, around a video switch, the game hitches for about 0.1 s. The same happens with
  software decoding.
- A loop point can hold the last frame for about 0.1 s (the new decoder's first frame), while everything else
  keeps moving.
- When a screen closes a video that is still opening, `close()` waits for the open (seen once, 0.4 s, at start-up).

## How the fixes were checked
- Repro programs, built against GoZen's patched FFmpeg (build line at the top of each):
  [nvmpi_seek_close.c](../upstream_issues/repro/nvmpi_seek_close.c) (`flush`, `close`, `crash` modes) and
  [nvmpi_concurrent.c](../upstream_issues/repro/nvmpi_concurrent.c) (`in.mp4 3 40 10`).
  `scripts/install/jetson_selftest.sh` builds and runs them all on a board.
- Decode speed: 1080p H.264 at about 350 fps on NVDEC, against about 70 fps on one CPU core.
- Games on the board: `scripts/run.py --scenario clu_hurryup --seconds 120`, with Godot's log showing
  `GoZen: hardware decoder h264_nvmpi` per video. `scripts/run.py --scenario full_game_to_portal`
  (`scenarios/full_game_to_portal.txt`) plays a whole game to Portal Multiball in about 10 minutes.

## Xavier NX checklist
For the board's OS, the minimal L4T 35.6.4 image and how to flash it (SD or NVMe) are in
[jetson_image.md](jetson_image.md).

JetPack 5 (L4T R35, t194) differs from the Orin in ways that touch these fixes:
- NVIDIA's libraries are in `/usr/lib/aarch64-linux-gnu/tegra/` instead of `.../nvidia/` (the install and the
  self-test handle it). R35's Multimedia API already has `nvbufsurface.h`, so libnvmpi builds on the same NvUtils
  path (`WITH_NVUTILS`) as on the Orin, not on the legacy `nvbuf_utils` one.
- The Xavier NX has fewer NVDEC sessions and less memory than the AGX Orin: check three screens decoding at once.

**On the board** (Xavier NX Developer Kit, L4T R35.6.4, minimal image, no nvpmodel mode set: 6 CPUs at 1.9 GHz),
`jetson_selftest.sh --stock` with `pup_pack/trn_174h/AttractMode/AttractMode-Trailer1.mp4` (1080p30 H.264):

| Check | Patched | Stock jetson-ffmpeg `8d70c17` |
|---|---|---|
| flush (fix 1) | pass | hang (killed after 60 s): the in-place reset fails on R35 too |
| close (fix 2) | 59 ms / 48 ms | 1086 ms / 24 ms (no packet / after 30 frames) |
| crash (fix 3), 100 runs | 0 crashed | 0 crashed (the Orin: 9) |
| concurrent (fix 4), 20 runs | 0 failed | 5 segfaults (the Orin hung instead) |

So fixes 1, 2 and 4 are needed on JetPack 5 too; fix 3 is kept (no cost).

**Checked without the board** (an arm64 Ubuntu 20.04 root under qemu, posing as a Xavier NX with L4T R35.4.1 and
NVIDIA's r35.4 apt packages): the full Linux install (`install_prereqs_linux.sh --yes`) passes, including Python
3.11 from uv, MPF Monitor, Godot 4.6.3 arm64, the PuP Pack and the Godot import; `nvmpi_flush.patch` applies and
libnvmpi builds with NvUtils against R35.4.1 and links NVIDIA's own `libv4l2.so.0`. The self-test's ffmpeg 7.1 with nvmpi and
both repro programs build and link there too. The GoZen arm64 `.so` needs
glibc 2.29 at most (Ubuntu 20.04 has 2.31). Decoding itself needs the board.

To bring one up:
1. `bash scripts/install/install_jetson_hwdec.sh` (or the full Linux install), and check that libnvmpi is in
   `ldconfig -p`.
2. `bash scripts/install/jetson_selftest.sh --stock`: builds the `--test` ffmpeg and the repro programs, then runs
   `flush`, `close`, `crash` (100 runs) and `nvmpi_concurrent in.mp4 3 40 10` (20 runs), each with a time limit,
   against our patched build and then against jetson-ffmpeg without the patch. The patched build must pass every
   check (exit status 0); the stock results show which bugs R35 has on its own: note them under "Not checked yet
   on JetPack 5" in the matching report. Logs: `~/.cache/tron-legacy-mpf/selftest/`.
3. Play `scripts/run.py --scenario clu_hurryup --seconds 120`, then `scripts/run.py --scenario full_game_to_portal`, on the
   screen. Watch for freezes and black screens, and check `game/logs/godot.log` for `h264_nvmpi` and errors.
4. Record the result in the "Tested" line at the top of this page and in the headers of `nvmpi_flush.patch` and
   `gozen.patch`.
5. If a hunk does not apply or behaves differently on R35, change `nvmpi_flush.patch` and re-run step 1; when its
   `ffmpeg/` part changes, also rebuild GoZen (`bash scripts/build_gozen.sh arm64`) and commit the `.so`.

## Xavier NX power modes
Xavier NX, L4T R35.6.4, with fixes 1 to 9. Each mode set with `sudo nvpmodel -m N` (no reboot needed), then
`clu_hurryup` for 120 s and `full_game_to_portal` for 620 s. Every run: 0 black screens, 0 Godot errors,
`h264_nvmpi` on every video, no freeze; CPU at most 47.5 °C. Modes 0, 1, 6 and 7 were not run (2- and 4-core
modes, slower per core than 5).

| Mode (CPUs / GPU max MHz) | Test | FPS avg | Worst 1 s | Median ms | Frames > 50 / > 100 ms | Video frames skipped | Video lag avg | A/V drift avg / max ms | CPU / GPU / NVDEC % | W avg |
|---|---|---|---|---|---|---|---|---|---|---|
| 3: 10W 2-core (2 × 1.50 GHz / 803) | hurryup | 19.8 | 9 | 38.9 | 437 / 67 | 1788 | 1084 ms | – | 87 / 17 / 81 | 5.2 |
| | full game | 20.3 | 1 | 37.5 | 3049 / 456 | 11685 | 475 ms | 186 / 1122 | 86 / 19 / 95 | 5.3 |
| 4: 10W 4-core (4 × 1.19 GHz / 803) | hurryup | 32.0 | 5 | 33.3 | 93 / 21 | 655 | 142 ms | 92 / 301 | 62 / 25 / 91 | 5.6 |
| | full game | 36.9 | 3 | 22.2 | 334 / 121 | 2776 | 183 ms | 113 / 910 | 53 / 27 / 97 | 5.6 |
| **5: 10W desktop (4 × 1.91 GHz / 510)** | hurryup | 54.4 | 29 | 16.7 | 26 / 9 | 146 | 47 ms | 138 / 163 | 46 / 35 / 94 | 6.6 |
| | full game | 52.6 | 8 | 16.7 | 161 / 68 | 856 | 68 ms | 91 / 521 | 43 / 36 / 98 | 6.5 |
| 2: 15W 6-core (6 × 1.42 GHz / 1109) | hurryup | 49.5 | 23 | 18.1 | 35 / 14 | 198 | 58 ms | 59 / 109 | 44 / 31 / 93 | 6.1 |
| | full game | 49.4 | 4 | 16.9 | 214 / 100 | 1274 | 122 ms | 192 / 1811 | 35 / 34 / 98 | 5.9 |
| 8: 20W 6-core (6 × 1.42 GHz / 1109) | hurryup | 52.9 | 26 | 17.1 | 25 / 12 | 173 | 69 ms | 48 / 261 | 39 / 34 / 93 | 6.5 |
| | full game | 50.7 | 3 | 16.7 | 218 / 96 | 1181 | 116 ms | 189 / 1749 | 34 / 35 / 98 | 6.4 |

- Per-core speed matters more than the number of cores: Godot's main thread (game logic and render submission) is
  the critical path. MPF uses about 6% of a core.
- Mode 5 is the smoothest and draws about 6.5 W. Mode 8 is level with it and has twice the GPU clock in reserve.
  Modes 3 and 4 are not playable.
- The A/V drift maxima are single samples right after a video switch; the averages are the better figure.
- Every mode has a 2.4–3.8 s stall at the same moment of the full game (about 118 s in): game side.

## Updating a pin
To move jetson-ffmpeg or GDE GoZen to a newer revision:
1. Change `JETSON_FFMPEG_REV` / `GOZEN_REV` in `scripts/build_gozen.sh` and the jetson-ffmpeg revision in
   `scripts/install/install_jetson_hwdec.sh`. Both must name the same jetson-ffmpeg revision: the wrapper in GoZen
   and the library on the board have to match.
2. Check that both patches still apply (`git apply --check`) and drop the hunks upstream has fixed (see the reports
   in `docs/upstream_issues/`).
3. Rebuild GoZen, re-run the Jetson install, then repeat steps 2 and 3 of the checklist.
