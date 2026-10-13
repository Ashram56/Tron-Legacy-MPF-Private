# VideoPlayback stalls the main thread when it opens, loops or closes a video

**Project:** https://github.com/VoylinsGamedevJourney/gde_gozen

## Environment

- GDE GoZen at `f9448619324ad7d0d4e79d3bd501bde477ea4b7f`, Godot 4.6.3, Linux arm64
- Jetson AGX Orin, L4T R36.4.3 (JetPack 6.2), with FFmpeg's `h264_nvmpi` hardware decoder (jetson-ffmpeg).
  Opening, seeking and closing a decoder takes tens of ms there, so the stalls are easy to see. The same code
  paths run on the main thread with software decoding too.

## What happens

A game that switches short videos often froze for 1 to 2.5 s on every switch. The video work itself is on a
worker thread, but `video_playback.gd` still waits for it, or does part of it, on the main thread:

1. **`set_video_path()`** starts `_open_video` on the `WorkerThreadPool` but calls `_open_audio()` on the main
   thread, which opens a second FFmpeg context.
2. **`_process()`** calls `WorkerThreadPool.wait_for_task_completion(_video_thread)` on the first frame after
   the task started, not once it has finished. The main thread then blocks until the file is open.
3. **Looping:** at the end of a looping video, `_process()` calls `seek_frame(0)` on the main thread. With a
   hardware decoder, a seek recreates the decoder, which takes about 0.1 s.
4. **`close()`** sets `video = null` on the main thread, so the last reference is dropped there. Freeing the
   `GoZenVideo` closes its decoder on the main thread.

Every window drawn by the same Godot process stalls meanwhile. In our case that is three PuP screens and the
game's DMD.

## Changes we use (all in `video_playback.gd`)

- `_open_video(with_audio)` opens the `AudioStreamFFmpeg` on the worker thread with the video. The main thread
  only assigns `audio_player.stream` afterwards.
- `_process()` checks `WorkerThreadPool.is_task_completed(_video_thread)` before
  `wait_for_task_completion()`.
- A new `restart()` goes back to the first frame by running `seek_frame(0)` on a worker task. The current frame
  stays up until then, and looping uses it.
- `close()` hands the last reference to the closed `GoZenVideo` to a worker task (`_release_video`), so it is
  freed there. `_exit_tree()` waits for those tasks.

Measured with timing logs over a 2-minute game on the Orin (hardware decoding), the longest video step on the
main thread went from 2.4 s (a `close()`; opening averaged 0.8 s) to 10 ms. With software decoding, the same
steps took up to about 0.1 s before the changes.

Our copy of the file, with the changes:
https://github.com/Ashram56/Tron-Legacy-MPF-PuP/blob/main/pup_addons/gde_gozen/video_playback.gd

## Possibly related: hardware decoder selection

We also patch `GoZenVideo::open()` so that it asks FFmpeg for `<codec>_nvmpi` first, falls back to the software
decoder, and can be turned off with `GOZEN_HWDEC=0`
(https://github.com/Ashram56/Tron-Legacy-MPF-PuP/blob/main/scripts/gozen/gozen.patch). A generic option to
prefer a named decoder, or FFmpeg hwaccels, would make this unnecessary.
