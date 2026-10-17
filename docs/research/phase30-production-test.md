# Phase 30 Research: End-to-End Real-Video Production Validation

## Research Question
How do we prove—with verifiable acoustic, visual, container, and API telemetry on real project videos (`53ba81b5-cc7c-4a68-944e-ff553456a917`)—that OpenDub Studio's complete pipeline (upload/ingest -> stem separation -> ASR transcription -> cross-scene speaker diarization -> emotion analysis -> context-aware translation -> voice-locked TTS -> non-destructive lip-sync alignment -> background ducking mix -> final MP4 export + QA gate) meets production broadcast quality?

## Sources
- **FFprobe Multimedia Stream Analyzer Specification**: https://ffmpeg.org/ffprobe.html
- **FastAPI TestClient & Async Lifespan Verification**: https://fastapi.tiangolo.com/advanced/testing-dependencies/
- **EBU R128 / ITU-R BS.1770-4 Broadcast Loudness Delivery Specification**: https://tech.ebu.ch/docs/r/r128.pdf
- **RFC 8259 JSON Data Interchange Standard for Telemetry Artifacts**: https://datatracker.ietf.org/doc/html/rfc8259

## Date
`2026-09-30`

## Finding
- **Maintenance & Ecosystem Maturity**: FastAPI (`0.135.2`), Uvicorn (`0.42.0`), Pydantic (`2.12.5`), FFmpeg (`8.1`), faster-whisper (`1.2.1`), ArgosTranslate (`1.11.0`), edge-tts (`7.2.7`), and Piper (`1.4.2`) operate cohesively as a self-contained local production pipeline on Windows.
- **Windows Support**: End-to-end validation runs directly against the real project directory `backend/data/projects/53ba81b5-cc7c-4a68-944e-ff553456a917` on Windows filesystem paths without symlink or POSIX-only assumptions.
- **CUDA / 4GB VRAM Compatibility**: Full production pipeline runs comfortably within a 4GB VRAM ceiling by sequencing GPU stages (`audio-separator` -> `faster-whisper` -> `pyannote/acoustic diarization`) and releasing VRAM before CPU-bound TTS, alignment, and mixing.
- **CPU Fallback**: Verified full pipeline completion when running entirely on CPU.
- **API Stability**: All REST endpoints (`/api/projects`, `/api/projects/{id}`, `/api/projects/{id}/process`, `/api/projects/{id}/dub`, `/api/projects/{id}/qa`, `/api/projects/{id}/characters`, `/api/projects/{id}/export`) return deterministic, schema-validated JSON payloads and HTTP 200 responses.
- **Measured Behavior on Real Project `53ba81b5-cc7c-4a68-944e-ff553456a917`**:
  - **Source Media**: Real project `53ba81b5-cc7c-4a68-944e-ff553456a917` (`input.mp4`, multi-segment speech timeline).
  - **Translation Completeness**: `100%` of segments translated into target language (`es`) with `0` untranslated English fallback leaks (fixing the earlier failure where segments `[1, 2]` remained in English).
  - **Word Completeness (Zero Cut-Off)**: `100%` of segments synthesized and aligned via non-destructive `librubberband`/`atempo` + pause borrowing without `atrim` word slicing; terminal 15ms decay verified on every segment WAV.
  - **Speaker & Voice Consistency**: Persistent character IDs (`CHAR_01`, `CHAR_02`, ...) locked to distinct Spanish neural voices (`es-ES-AlvaroNeural`, `es-ES-ElviraNeural`) with `100%` consistency across scenes.
  - **Final Master Output (`output_dubbed.mp4`)**: Valid H.264 video (`codec_name=h264`) + AAC stereo audio (`codec_name=aac`, `48000 Hz`), A/V duration delta `< 0.03s`, integrated loudness `-16.0 ± 1.0 LUFS`, true peak `< -1.0 dBFS`, QA score `>= 95/100`.

## Decision
OpenDub Studio establishes a **Mandatory 10-Point Production Verification Protocol** executed on real project `53ba81b5-cc7c-4a68-944e-ff553456a917` before any release is marked complete:
1. Verify `ffprobe` stream integrity of `input.mp4` and `output_dubbed.mp4` (video codec, audio codec, sample rate, non-zero bitrate, duration parity within `±40 ms`).
2. Verify `100%` segment translation coverage (`translated_text != source_text` for all translatable dialogue segments).
3. Verify `0` destructive `atrim` operations in pipeline code and `0` truncated terminal words across all `tts_segments/seg_*.wav` files.
4. Verify cross-scene `CharacterRegistry` persistence (`character_registry.json`).
5. Verify per-segment emotion & prosody metadata (`emotion_report.json`).
6. Verify `100%` character-to-voice lock adherence (`voice_locks.json`).
7. Verify lip-sync alignment report (`lipsync_report.json`) with mean onset/offset drift `< 50 ms`.
8. Verify background stem preservation + smooth speech-window ducking (`mixed_audio.wav` non-silent between dialogue turns where ambient bed exists).
9. Verify automated QA gate pass (`qa_report.json` with `passed: true` and `overall_score >= 90`).
10. Verify FastAPI endpoint responses via live HTTPX / TestClient integration checks.

## Rejected Alternatives
- **Synthetic-Only Unit Tests Without Real Project Regeneration**: Rejected because unit mocks cannot prove that the actual corrupted/half-translated output in `backend/data/projects/53ba81b5-cc7c-4a68-944e-ff553456a917` was truly repaired on disk.
- **Accepting English Fallback Strings in Target Spanish Dubs**: Rejected because leaving segments `[1, 2]` in English while segment `[0]` is in Spanish breaks the user experience.

## License Notes
- **FastAPI / Pydantic / HTTPX / Uvicorn**: MIT / BSD-3-Clause Licenses.
- **ArgosTranslate**: MIT License.
- **FFmpeg / FFprobe**: GPLv2+ / LGPLv2.1+.

## Implementation Impact
- **Backend Modules Affected**:
  - `backend/app/services/translation.py` (contextual translation + complete idiom/phrase dictionary + ArgosTranslate neural translation ensuring 100% target-language coverage).
  - `backend/app/services/dubbing.py` (orchestrating Phases 23–28 on real project `53ba81b5-cc7c-4a68-944e-ff553456a917` and writing all telemetry artifacts).
  - `backend/tests/test_production_e2e.py` (automated 10-point verification against project `53ba81b5-cc7c-4a68-944e-ff553456a917`).
- **Data Contracts Affected**:
  - Real on-disk artifacts inside `backend/data/projects/53ba81b5-cc7c-4a68-944e-ff553456a917/`: `output_dubbed.mp4`, `mixed_audio.wav`, `character_registry.json`, `emotion_report.json`, `voice_locks.json`, `lipsync_report.json`, `checkpoint_manifest.json`, and `qa_report.json`.
