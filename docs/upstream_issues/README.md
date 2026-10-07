# Upstream issue reports

Bugs found while running the PuP Pack videos with hardware decoding on a Jetson, ready to file with the
upstream projects. Each file is one issue: copy the title and the body into a new GitHub issue. The fixes we
carry until upstream has its own are in `scripts/gozen/`.

| File | Project | Problem |
|---|---|---|
| [jetson-ffmpeg-flush-hang.md](jetson-ffmpeg-flush-hang.md) | [gjrtimmer/jetson-ffmpeg](https://github.com/gjrtimmer/jetson-ffmpeg/issues) | `avcodec_flush_buffers()` on `*_nvmpi` hangs the next decode on JetPack 6 |
| [jetson-ffmpeg-slow-close-crash.md](jetson-ffmpeg-slow-close-crash.md) | [gjrtimmer/jetson-ffmpeg](https://github.com/gjrtimmer/jetson-ffmpeg/issues) | `nvmpi_decoder_close()` takes ~1 s, and closing mid-stream sometimes crashes |
| [jetson-ffmpeg-concurrent-decoders-hang.md](jetson-ffmpeg-concurrent-decoders-hang.md) | [gjrtimmer/jetson-ffmpeg](https://github.com/gjrtimmer/jetson-ffmpeg/issues) | With several decoders starting and stopping at once, one can hang forever |
| [gde-gozen-main-thread-stalls.md](gde-gozen-main-thread-stalls.md) | [VoylinsGamedevJourney/gde_gozen](https://github.com/VoylinsGamedevJourney/gde_gozen/issues) | `VideoPlayback` opens, loops and frees videos on the main thread |

Platform for all of them: Jetson AGX Orin Developer Kit, L4T R36.4.3 (JetPack 6.2), Ubuntu 22.04, `oot` kernel.
Not checked yet on Xavier NX (L4T R35, JetPack 5).

The `native_video` heap overrun is already reported upstream
([claytercek/godot-native-video#26](https://github.com/claytercek/godot-native-video/issues/26)).
