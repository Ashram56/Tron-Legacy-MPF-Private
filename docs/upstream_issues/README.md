# Upstream reports: issues and improvements

Everything this repository changed or found that belongs to another project, grouped by the project to report it
to. Bugs have a ready-to-file report (copy its title and body into a new GitHub issue); improvements list what to
send and where it lives here. The fixes we carry until upstream has its own are in `scripts/gozen/`, and the
Xavier NX results behind them are in [../jetson/xavier_nx.md](../jetson/xavier_nx.md).

## Godot ([godotengine/godot](https://github.com/godotengine/godot/issues))

| Report | Kind | Summary |
|---|---|---|
| [godot-separate-render-thread-glyph-cache.md](godot-separate-render-thread-glyph-cache.md) (test project `repro/godot_glyph_cache.zip`) | bug | With the separate render thread, a growing glyph cache logs `_texture_2d_update` errors (harmless, picture identical) |
| [godot-pipeline-cache-not-saved-separate-render-thread.md](godot-pipeline-cache-not-saved-separate-render-thread.md) (test project `repro/godot_pipeline_cache.zip`) | bug | With the separate render thread the pipeline cache save at exit fails, so every start recompiles every pipeline (4-5 s stalls) |
| [godot-msdf-glyphs-main-thread.md](godot-msdf-glyphs-main-thread.md) (test project `repro/godot_msdf_main_thread.zip`) | bug / feature | MSDF glyphs are generated on the main thread when first drawn: 6.8 s and 45 s for one font on a Xavier NX |

## GDE GoZen ([gozen/gde_gozen on Codeberg](https://codeberg.org/gozen/gde_gozen/issues); issues are off on GitHub)

| Report | Kind | Summary |
|---|---|---|
| [gde-gozen-main-thread-stalls.md](gde-gozen-main-thread-stalls.md) | bug | `VideoPlayback` opens, loops and frees videos on the main thread (1-2.5 s stalls with a hardware decoder) |
| `seek_frame()` retry loop | bug | Near the end of a clip a catch-up `seek_frame()` retried at EOF for minutes on a busy low-priority worker; the game froze (9 min at 10 W, 2 cores). We never seek from decode tasks ([../jetson/README.md](../jetson/README.md) fix 9) |
| Hardware decoder first (`<codec>_nvmpi`, fallback to software, `GOZEN_HWDEC=0`) | feature | `scripts/gozen/gozen.patch` |
| `GoZenVideo.set_target_size()` and native NV12 | feature | Frames decoded at the size they are shown at, as NV12 (Y as R8, UV as RG8; `nv12` switch in both YUV shaders): 4-8x fewer pixels per frame. `gozen.patch`, `pup_addons/gde_gozen/*.gdshader`, `video_playback.gd` `decode_to_display_size` |
| Frames decoded ahead | feature | `video_playback.gd`: up to 3 frames per video decoded on worker tasks; silent videos never drop a frame, videos with sound follow the audio clock. Video frames skipped 89 to 15 per clip, A/V drift 79-130 to 30-46 ms |
| `lean=yes` SConstruct option | feature | FFmpeg without libvpx, libaom, LibreSSL and zlib (`gozen.patch`) |

## jetson-ffmpeg ([gjrtimmer/jetson-ffmpeg](https://github.com/gjrtimmer/jetson-ffmpeg/issues))

All fixes are in `scripts/gozen/nvmpi_flush.patch`.

| Report | Kind | Summary |
|---|---|---|
| [jetson-ffmpeg-flush-hang.md](jetson-ffmpeg-flush-hang.md) | bug | `avcodec_flush_buffers()` on `*_nvmpi` hangs the next decode (JetPack 6 and 5) |
| [jetson-ffmpeg-slow-close-crash.md](jetson-ffmpeg-slow-close-crash.md) | bug | `nvmpi_decoder_close()` takes about 1 s, and closing mid-stream sometimes crashes |
| [jetson-ffmpeg-concurrent-decoders-hang.md](jetson-ffmpeg-concurrent-decoders-hang.md) | bug | With several decoders starting and stopping at once, one can hang forever (JetPack 5: segfaults) |
| Planes mapped once per buffer | performance | Each frame mapped and unmapped every plane for the CPU, about 11 ms of kernel time per 1080p frame on L4T R35: decode 74 to 203 fps, CPU 17 to 4 ms per frame ([../jetson/README.md](../jetson/README.md) fix 9) |

## Tron-Legacy-MPF ([Ashram56/Tron-Legacy-MPF](https://github.com/Ashram56/Tron-Legacy-MPF), the game this repo syncs from)

All ported to Tron-Legacy-MPF `main` (2026-10-09: font bake in PR #35, the rest in commit 4b8da5e), so they are
listed here for the record; the next upstream sync brings them back without conflicts. Measurements:
[../performance.md](../performance.md).

| Change | Files | Gain |
|---|---|---|
| Clean HD fonts baked at setup | `game/tools/bake_fonts.gd`, `game/tron/rom_text_hd.gd`, `scripts/setup.py` | Upstream PR [#35](https://github.com/Ashram56/Tron-Legacy-MPF/pull/35). 20-30 s freezes with Orbitron or Rajdhani gone |
| Letter glows off the main thread, none made with the glow off | `game/tron/letter_panel.gd` | Deff 94 created in 25-36 ms instead of 380 ms |
| Large display effects preloaded on worker threads (`tron/dmd/preload_min_frames=40`) | `game/tools/dmd_mode.gd`, `game/project.godot` | Deff 86 0.89 s to under 0.1 s, about 200 MB more memory |
| HD effect frames imported VRAM-compressed | `scripts/gen_media.py` | 7 to 1.5 ms per frame loaded, half the GPU memory; Light Cycle multiball stall 2.34 to 1.00 s |
| Separate render thread, `--no-render-thread` / `TRON_RENDER_THREAD=0` to turn it off | `game/project.godot`, `scripts/run.py`, `docker/entrypoint.py` | +2.3 FPS on the Xavier NX; captures (opengl3) kept on the main thread |
| Pipeline cache saved while running | `game/project.godot` | 4-5 s first-effect stalls gone from the second start |
| Worker pool `low_priority_thread_ratio=0.5` | `game/project.godot` | Video switch stalls 1.3 to 0.6-0.95 s |
| Core pinning (Linux, 4+ cores, `TRON_PIN=0` off) | `scripts/run.py` | +1.5 FPS, a third fewer late frames |
| Performance probe and reports | `game/tools/perf_probe.gd`, `scripts/perf/` | Off unless `TRON_PERF_DIR` is set |

Platform for the GoZen and jetson-ffmpeg reports: Jetson AGX Orin Developer Kit, L4T R36.4.3 (JetPack 6.2), and
Jetson Xavier NX Developer Kit, L4T R35.6.4 (JetPack 5.1.4). The close crash did not show on the Xavier NX in 100
runs; the other decoder bugs are on both.

The `native_video` heap overrun is already reported upstream
([claytercek/godot-native-video#26](https://github.com/claytercek/godot-native-video/issues/26)).
