# Phase 8 — Final render and cleanup

Implemented:
- Background render job muxes original video stream with the generated dubbed mix using FFmpeg. Video stream is copied where possible; output audio is AAC.
- Temporary output is written with a .partial suffix and promoted only after FFmpeg exits successfully and produces a non-empty file.
- Render status is persisted as a job; queued full-render jobs are re-enqueued after application restart.
- Download endpoint and UI progress/download control.
- Optional cleanup runs only after successful final file verification. It removes regenerable extracted mono audio, separation working folder and segment WAVs. Original source, transcript/scene metadata, character registry, final mix and final movie are preserved.

Limitations:
- The render task is resumable by rerunning the mux job, not by resuming FFmpeg from an internal frame checkpoint.
- No cancel/pause, codec selector, subtitle burn-in, chapter preservation guarantees, or multi-audio-track selection UI.
- Container compatibility can vary; current output is MP4 with copied video and AAC audio. Source videos with codecs unsupported by MP4 may require transcoding.
- No full-length movie or Windows runtime tests have been performed.
