# avcodec_flush_buffers() on *_nvmpi hangs the next decode on JetPack 6 (L4T R36.4)

**Project:** https://github.com/gjrtimmer/jetson-ffmpeg

## Environment

- Jetson AGX Orin Developer Kit (t234), L4T R36.4.3 (JetPack 6.2), Ubuntu 22.04, `oot` kernel
- jetson-ffmpeg at `8d70c17efeee57f4d956df500fec78a73f8c27d4`, FFmpeg 7.1 patched with `scripts/ffpatch.sh`
- Decoder: `h264_nvmpi` (1080p H.264 decodes at about 350 fps, so the hardware path itself works)

## What happens

After `avcodec_flush_buffers()` on an `h264_nvmpi` context, the next `avcodec_send_packet()` never returns. This
happens every time, with mp4, mkv and ts input. Any seek therefore freezes the application, and so does looping
a video, which is a seek to 0.

Thread state while it hangs:

- The caller's thread is blocked in `nvmpi_decoder_put_packet()` → `NvV4l2ElementPlane::dqBuffer()` on the
  OUTPUT plane, waiting for a free bitstream buffer.
- The `dec_capture` thread spins in `dqEvent()`, waiting for a resolution-change event.

## Cause (as far as we can tell)

`nvmpi_flush_decoder()` calls `nvmpi_decoder_flush()`, which resets the decoder in place (STREAMOFF/STREAMON).
On R36 the V4L2 decoder then sends no new `V4L2_EVENT_RESOLUTION_CHANGE` for the same stream, because the size
did not change. The capture plane is never set up again, no OUTPUT buffer is ever returned, and `put_packet()`
blocks forever.

We tried re-arming the capture plane in place inside libnvmpi, but on R36 the capture plane returns `EINVAL`
after STREAMOFF/STREAMON.

## How to reproduce

```c
// open an H.264 mp4 with h264_nvmpi, decode a few frames, then:
avcodec_flush_buffers(ctx);
av_seek_frame(fmt, -1, 0, AVSEEK_FLAG_BACKWARD);
av_read_frame(fmt, pkt);
avcodec_send_packet(ctx, pkt);   // never returns
```

The same flush also happens on every loop of `ffmpeg -stream_loop 9 -c:v h264_nvmpi -i in.mp4 -f null -`.

A complete program: [`repro/nvmpi_seek_close.c`](repro/nvmpi_seek_close.c) (build line at its top).
`./nvmpi_seek_close in.mp4 flush` prints `pass 0: 100 frames` and then hangs, checked with libnvmpi at
`8d70c17`.

## Workaround we use

In `ffmpeg/dev/common/libavcodec/nvmpi_dec.c`, the flush closes the decoder (`nvmpi_decoder_close()`), and the
next `nvmpi_decode()` creates a new one from the saved `nvDecParam` and primes it with the extradata again. The
decoder is created lazily, so a flush right before the codec is freed does not create one for nothing. A flush
also does nothing when no packet was sent since the decoder was created. Creating a decoder takes about 20 ms on
an AGX Orin.

With this change, on the board:

- 3 loops and 3 mid-stream seeks pass for mp4, mkv and ts.
- `ffmpeg -stream_loop 9 -c:v h264_nvmpi` completes (5879 frames).

Patch (against `8d70c17`, `nvmpi_dec.c` part):
https://github.com/Ashram56/Tron-Legacy-MPF-PuP/blob/main/scripts/gozen/nvmpi_flush.patch

Known leftover, not caused by this change: on a recreated decoder, draining at EOF can lose up to about 10
trailing frames.

Also on JetPack 5: Jetson Xavier NX, L4T R35.6.4, the `flush` mode hangs the same way with stock libnvmpi (and passes
with the patch).
