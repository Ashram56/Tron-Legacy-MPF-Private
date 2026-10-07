# libnvmpi: nvmpi_decoder_close() takes about 1 s, and closing mid-stream sometimes crashes (JetPack 6)

**Project:** https://github.com/gjrtimmer/jetson-ffmpeg

## Environment

- Jetson AGX Orin Developer Kit (t234), L4T R36.4.3 (JetPack 6.2), Ubuntu 22.04, `oot` kernel
- jetson-ffmpeg at `8d70c17efeee57f4d956df500fec78a73f8c27d4` (libnvmpi built with `scripts/build.sh --install`)

An application that switches between short videos (a pinball PuP pack: several videos a minute on three
screens) closes and opens decoders all the time. Two problems show up there.

## 1. close() takes about 1 s

`nvmpi_decoder_close()` takes about 1 s when the decoder never saw a resolution change, for example a decoder
closed right after it was created or recreated. During that time the `dec_capture` thread waits out two 500 ms
`dqEvent()` timeouts before it notices `eos`. The application stalls on every video switch.

**Fix we use:** a `closing` flag set at the start of `nvmpi_decoder_close()`. The capture loop waits in 50 ms
`dqEvent()` slices, and when `closing` is set it exits without waiting for a resolution-change event. Close now
takes about 55 ms.

## 2. Closing mid-stream sometimes crashes

When a decoder is closed while a video is still playing, NVIDIA's decoder thread sometimes crashes (SIGSEGV)
inside `libnvmmlite_video`: 9 of 100 runs of the repro below crashed with libnvmpi at `8d70c17`. The crash happens
inside `v4l2_close`, or after the CAPTURE DMA buffers were freed. It looks like the decoder still writes a frame
into a buffer that `deinitDecoderCapturePlane()` has already destroyed.

**Fix we use, in `nvmpi_decoder_close()`:**

1. Let the decoder finish the queued bitstream first. For at most 300 ms, dequeue OUTPUT buffers until none is
   queued. Meanwhile the capture thread drops frames instead of waiting for the pool while `closing` is set.
2. Stop the capture plane (`setStreamStatus(false)`, `reqbufs(DMABUF, 0)`) and `delete ctx->dec` *before*
   freeing the CAPTURE DMA buffers and the frame pool. `deinitDecoderCapturePlane()` skips that part when `dec`
   is already gone.

After this change there were 0 crashes in 100 runs of the same repro on the board, and 2 and 5 minute games
ran clean.

## How to reproduce

[`repro/nvmpi_seek_close.c`](repro/nvmpi_seek_close.c) (build line at its top), with any H.264 mp4:

- `./nvmpi_seek_close in.mp4 close` prints the close time: 1061 ms for a decoder that got no packet yet,
  17 ms after 30 decoded frames.
- `./nvmpi_seek_close in.mp4 crash` decodes 100 frames and closes the decoder mid-stream, three times. Run it
  in a loop: `for i in $(seq 100); do ./nvmpi_seek_close in.mp4 crash > /dev/null || echo crashed; done`

Patch (against `8d70c17`, `src/` part):
https://github.com/Ashram56/Tron-Legacy-MPF-PuP/blob/main/scripts/gozen/nvmpi_flush.patch

Not checked yet on JetPack 5 (Xavier, L4T R35).
