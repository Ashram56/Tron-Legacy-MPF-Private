# libnvmpi: with several decoders starting and stopping at once, a decoder can hang forever (JetPack 6)

**Project:** https://github.com/gjrtimmer/jetson-ffmpeg

## Environment

- Jetson AGX Orin Developer Kit (t234), L4T R36.4.3 (JetPack 6.2), Ubuntu 22.04, `oot` kernel
- jetson-ffmpeg at `8d70c17efeee57f4d956df500fec78a73f8c27d4`, `h264_nvmpi` in FFmpeg 7.1

## What happens

An application with three video screens opens and closes `h264_nvmpi` decoders from several threads. Now and
then one decoder stops for good, and the thread feeding it blocks forever in `avcodec_send_packet()`:

- The feeding thread is in `nvmpi_decoder_put_packet()` → `NvV4l2ElementPlane::dqBuffer()` on the OUTPUT plane
  (`TegraV4L2_Poll_OPlane`).
- That decoder's `dec_capture` thread has exited. Its CAPTURE-plane `dqBuffer()` failed with `EINVAL` while other
  decoders were being created and closed; the plane is then in error, `dec_capture_loop_fcn()` leaves its loop
  and nothing ever returns OUTPUT buffers.

In a game this froze everything: Godot's main thread waited for the stuck decode.

## How to reproduce

[`repro/nvmpi_concurrent.c`](repro/nvmpi_concurrent.c): `./nvmpi_concurrent in.mp4 3 40 10` (three threads, 40
decoders each). With libnvmpi at `8d70c17`, 4 of 6 runs hung. It also hung with our other fixes in
`nvmpi_flush.patch` applied.

## Fix we use

1. A global mutex serialises decoder setup and teardown: `nvmpi_create_decoder()`, the teardown part of
   `nvmpi_decoder_close()` (after the capture thread is joined), and `respondToResolutionEvent()`. That made the
   `EINVAL` rare, but 1 run in 8 still hung.
2. When the capture thread stops on a decoder error (not `closing`, `isInError()`), it STREAMOFFs the OUTPUT
   plane. That wakes a `put_packet()` blocked in `dqBuffer()` with an error, and `put_packet()` returns -1 at
   once while the decoder is in error. The application sees a failed decode instead of a hang, and can recreate
   the decoder.

With both: 0 hangs in 20 runs of the repro (3 decoders recovered from the error), plus the earlier seek, close
and crash repros still pass.

Patch (against `8d70c17`, `src/` part):
https://github.com/Ashram56/Tron-Legacy-MPF-PuP/blob/main/scripts/gozen/nvmpi_flush.patch

The root cause, why the CAPTURE plane's DQBUF fails with `EINVAL` while another decoder starts or stops, is
probably in NVIDIA's libtegrav4l2 / NvMMLite and may be worth a report on the NVIDIA developer forum.

On JetPack 5 (Jetson Xavier NX, L4T R35.6.4), stock libnvmpi: 5 of 20 runs of `in.mp4 3 40 10` segfaulted instead of
hanging, one after `NVMMLITE_NVVIDEODEC cbDisplayPicture ErrorInfo = VideoErrorInfo_NullFrameBuffer`; 0 of 20 with
the patch.
