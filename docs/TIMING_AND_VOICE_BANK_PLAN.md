# Timing, resume and character fixes — 3 October 2026

## Current priority and implementation

1. Give Piper the source speech duration before synthesis. Estimate Hindi delivery duration, adjust the requested rate by at most 10%, and record the estimate explicitly. Do not rewrite meaning or promise that an estimate is a measured fit.
2. Measure generated speech, remove boundary silence, and apply pitch-preserving FFmpeg fitting within the existing natural rate limits. Short utterances use bounded slowdown followed by silence padding; excessive overrun requires a shorter reviewed translation. Never cut spoken words or force extreme speed.
   For isolated utterances under 0.6 seconds, recover missing ASR speech edges only from a matching, exclusive detected speaker turn within 0.35 seconds of each edge. Reject overlap with another dialogue or speaker. Retain original ASR timestamps as provenance; never enlarge into an arbitrary silent gap.
3. Version the fitting policy. Resume rechecks old timing results using existing TTS files, retaining previous audio revisions and upstream analysis/translation. Once a current policy result exists, reuse it.
4. Use workload-specific RAM admission on resume. Completed analysis must not impose ASR/diarization memory requirements on line synthesis. Keep resource checks for genuinely heavy work and retain files on interruption.
   Reuse completed separation only after comparing the recorded source PCM, model and stem durations. Recheck heavy-work admission if valid stems are unavailable.
5. Cache diagnostics in the UI, share an outstanding request, and reprobe only for an explicit diagnostics Refresh. Live processing admission continues to measure free resources.
6. Support custom character creation without a cast-size cap. Preserve saved voice profiles across speaker resync and render current character names in dialogue. Provider, voice ID, model path, language and speaker settings persist in the registry.
7. Verify in the existing embedded browser with project `test`; inspect real logs, resume synthesis/fit, and report remaining translation or timing issues honestly. Run regression tests, push the focused changes, and check GitHub workflows.
8. Protect rare overlapping dialogue peaks with a smooth 20 ms envelope on dialogue alone. Read context around chunk boundaries for continuous gain. Reject sustained attenuation, excessive energy loss or an unsafe background. If necessary, retry bounded dialogue-only normalization at -20/-22/-24 LUFS. Keep background gain unchanged and avoid TTS regeneration. If these limits cannot produce a safe mix, retain checkpoints and require review rather than clipping or muting speech.

## JANTA GARAGE reusable voice bank — next implementation

Inventory found 42 catalog records and 42 distinct existing WAV files, none missing or byte-identical. Durations range from 3.0 to 17.2 seconds. This establishes reference-audio availability, not clean speaker isolation or completed voice cloning. Catalog actor labels and stock neural voice IDs are not proof of the audible speaker identity; this is a Hindi dubbed movie.

1. Preserve existing references and compare their recorded timecodes against the supplied movie. Review speaker identity, mixed speakers, background leakage, noise, clipping and intelligibility. Mark uncertain records as unverified rather than assigning guessed cast names.
2. Select roughly 10 seconds of clean speech per verified speaker, including side/one-time speakers. Extract only missing or unsuitable references instead of scanning the whole movie again. Retain source hash, timecode, extraction method, original reference and review status.
3. Audit installed Hindi-capable cloning engines and hardware requirements. Connect a real reference-conditioned engine to the synthesis endpoint; never substitute a stock voice while labeling it a clone. Do not automatically install heavyweight models before confirming runtime compatibility and resource budgets.
4. Create a global reusable library with stable voice IDs, display names, verified reference paths, provider/model configuration, language, capabilities and version. Store project-specific character-to-library assignments separately. Keep API credentials outside profiles.
5. Provide reference audition, cloned Hindi audition and explicit selection per character in the white-theme UI. New projects can reuse selected defaults; avoid guessing assignments from actor labels or pitch alone.
6. Pass source-duration budgets into cloning synthesis and reuse the same measured fit rules. Preserve background stems at unity gain and verify timing, completeness and speaker consistency before final export.
7. Validate persistence across restart/new projects and listen to matched reference/generated samples before promoting voices to defaults. Catalog existence alone must never be reported as cloning success.
