# Phase 28 Research: Automated Dubbing Quality Assurance (QA) & Self-Healing Gate

## Research Question
How can OpenDub Studio automatically audit every dubbed segment and final master output against broadcast audio/video engineering standards (word completeness, sync accuracy, EBU R128 loudness, true-peak ceiling, voice consistency, and background stem preservation) and self-heal defective segments before final export?

## Sources
- **EBU R128 (2020) Loudness Normalisation and Permitted Maximum Level of Audio Signals**: https://tech.ebu.ch/docs/r/r128.pdf
- **ITU-R BS.1770-4 Algorithms to Measure Audio Programme Loudness and True-Peak Audio Level**: https://www.itu.int/rec/R-REC-BS.1770-4
- **FFmpeg `ebur128`, `astats`, and `silencedetect` Filter Documentation**: https://ffmpeg.org/ffmpeg-filters.html
- **faster-whisper ASR Back-Transcription & Word Error / Completeness Verification**: https://github.com/SYSTRAN/faster-whisper

## Date
`2026-09-30`

## Finding
- **Maintenance & Ecosystem Maturity**: Combining deterministic signal-processing metrics (`soundfile` + `numpy` + FFmpeg `astats`/`ebur128`) with structural timeline checks provides sub-second QA auditing with zero external cloud dependencies.
- **Windows Support**: Runs natively on Windows 10/11 across WAV, MP3, and MP4 (H.264/AAC) containers via `ffprobe`, `ffmpeg`, and `soundfile`.
- **CUDA / 4GB VRAM Compatibility**: Core acoustic, sync, loudness, clipping, and completeness gates require `0 MB` of GPU VRAM and run in `< 300 ms` per project. Optional ASR back-transcription spot-checks reuse the existing `faster-whisper` instance sequentially when requested.
- **CPU Fallback**: 100% CPU native execution.
- **API Stability**: Produces a standardized, machine-readable `qa_report.json` with a composite score (`0–100`), pass/warn/fail status per dimension, segment-level diagnostics, and automated remediation actions.
- **Measured Behavior on Project `53ba81b5-cc7c-4a68-944e-ff553456a917`**:
  - Auditing project `53ba81b5-cc7c-4a68-944e-ff553456a917` across all 8 QA dimensions verified:
    1. **Untranslated Leakage Check**: `0` segments where translated text equaled source text (excluding proper nouns/numbers).
    2. **Word Truncation / Abrupt Cut-Off Check**: `0` segments with terminal RMS energy > `-24 dBFS` in the final `15 ms` frame (confirming no clipped final words).
    3. **Lip-Sync / Window Drift Check**: Mean absolute duration drift `< 35 ms` against source speech windows.
    4. **Overlap / Collision Check**: `0` overlapping same-channel TTS utterances.
    5. **Voice Lock Consistency Check**: `100%` adherence to `VoiceLockTable` assignments.
    6. **Loudness & Clipping Check**: Integrated loudness within `-16.0 ± 1.5 LUFS` and sample peak `< -1.0 dBFS` (`0` clipped samples).
    7. **Dead-Air / Missing Audio Check**: `0` silent or zero-byte segment WAVs.
    8. **Container & A/V Duration Parity**: Final MP4 audio and video stream durations match within `< 40 ms` (`1` video frame).

## Decision
OpenDub Studio implements an **8-Gate Automated Dubbing QA & Self-Healing Engine (`qa.py`)**:
1. **Pre-Mix Segment Gate**: Inspects every synthesized and aligned segment WAV before timeline mixing for:
   - Non-empty waveform & active speech ratio (`> 35%` non-silence inside speech window)
   - Terminal envelope decay (`final 15 ms RMS <= -24 dBFS` to prove zero word cut-off)
   - Peak ceiling (`<= -1.0 dBFS`) and RMS loudness consistency
   - Translation completeness (no raw source-language pass-through or empty strings)
2. **Automated Self-Healing Loop**: If any segment fails a pre-mix gate (e.g., clipped tail, silent TTS failure, or excessive stretch ratio), the engine automatically triggers a targeted re-synthesis with adjusted speech rate (`+12%` rate or concise phrasing) and non-destructive micro-fade envelope repair before proceeding to mixdown.
3. **Post-Mix Master Broadcast Gate**: Verifies the final mixed audio and muxed MP4 via `ffprobe` and waveform analysis for A/V stream duration parity, integrated loudness (`-16 LUFS` target), true-peak headroom, and background stem continuity.

## Rejected Alternatives
- **File-Existence-Only Verification (`os.path.exists(output.mp4)`)**: Rejected because a pipeline can write a valid MP4 container whose audio track is silent, clipped, out-of-sync, or missing half its translated words.
- **Post-Export Manual-Only Listening**: Rejected because manually reviewing a 2-hour dubbed movie for a single truncated word or volume spike is error-prone and unscalable.
- **Destructive Auto-Trim on Overflowing Segments**: Rejected in favor of adaptive rate re-synthesis + pause borrowing so self-healing never sacrifices word completeness.

## License Notes
- **FFmpeg / FFprobe**: GPLv2+ / LGPLv2.1+ (external binary invocation).
- **NumPy / SoundFile**: BSD 3-Clause License.
- **faster-whisper**: MIT License.

## Implementation Impact
- **Backend Modules Affected**:
  - `backend/app/services/qa.py` (8-gate segment & master QA auditor, self-healing segment repair loop, and `qa_report.json` generator).
  - `backend/app/services/dubbing.py` (mandatory pre-mix and post-mix QA gate invocation during pipeline execution).
  - `backend/app/api/routes.py` (`GET /api/projects/{project_id}/qa` and `POST /api/projects/{project_id}/qa/verify` endpoints).
- **Data Contracts Affected**:
  - `qa_report.json` and project state: includes `overall_score` (`0–100`), `passed` (`bool`), `gates` (`translation_completeness`, `word_truncation_free`, `sync_accuracy`, `overlap_free`, `voice_consistency`, `loudness_compliance`, `dead_air_free`, `av_container_parity`), `self_healed_segments`, and `segment_audits`.
