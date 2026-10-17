# Phase 7 — Timing and audio mix (initial implementation)

Implemented:
- Segment duration fit uses FFmpeg atempo (pitch-preserving) with bounded speed change and pad/trim to the requested source segment duration. Metadata flags when the desired tempo exceeds the configured range.
- Per-segment loudness normalization to a configurable target (default -16 LUFS, true peak -1.5 dB).
- Timeline mix places generated segment WAVs at original transcript start timestamps.
- Optional project-local background/instrumental WAV is ducked under the dialogue using FFmpeg sidechaincompress.
- API endpoints for fit, normalize, mix, and audio preview, plus UI controls for sequential fitting and preview.

Limitations:
- This is a basic automated mix, not a mastering chain. Dialogue timestamps depend on ASR quality; overlaps, scene cuts and source-language overlap require human review.
- No waveform UI, per-clip manual timing edits, true integrated loudness analysis report, EQ/compression controls, or final video mux yet.
- Background separation can contain dialogue leakage or artifacts. Choose and audition the background stem before mixing.
- Runtime behavior has not been tested on Windows/RTX 3050 or a full-length movie.
