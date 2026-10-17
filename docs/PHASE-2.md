# Phase 2 — Media ingest and timeline

Implemented: normalized 16 kHz mono WAV extraction, FFmpeg visual scene-change detection, optional faster-whisper transcript with word timestamps, automatic CUDA detection and CPU/int8 fallback.

Limitations: scene cuts are visual-change approximations, not semantic scene understanding. Transcripts are drafts requiring review. Diarization, separation, character matching, translation and TTS are subsequent phases. Model weights download on first ASR use and can consume disk space.
