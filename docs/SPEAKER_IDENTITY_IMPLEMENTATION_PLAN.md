# Speaker identity first: implementation plan

Prepared 13 October 2026 from current-code audit and primary-source research. The user subsequently approved implementation. The foundation/upload execution batch is implemented and real-media tested; see `SPEAKER_WORKFLOW_VALIDATION.md` for current evidence and remaining research milestones. This document retains the larger roadmap, including adapters and accuracy benchmarks that are not complete. Preserve the existing dirty checkout and reviewed media assets.

## Goal

Before Hindi dubbing, identify provisional speaking identities across the whole video, retain rapid changes and simultaneous dialogue, let the user confirm character/casting choices, and lock one appropriate Hindi voice per character. Unknown ownership remains visible. Speaker identity, character identity and Hindi voice selection are separate contracts.

## Context

At the initial audit, the vocal-first path, source-time timestamps, pyannote Community-1 adapter, character UI and voice-profile persistence already existed. Main runtime contains pyannote.audio 4.0.7/PyTorch 2.11.0/faster-whisper 1.2.1. The actual NVIDIA adapter is RTX 3050 4GB. Existing phase-24 handcrafted features are not sufficient proof of same-voice identity recovery. Analysis previously persisted only exclusive diarization; the implemented foundation now retains regular and exclusive views plus native learned embeddings.

Read `.agents/rules/opendub-evidence.md` and existing handoff documentation before changing code. Accepted character auditions and their reference/hash histories remain protected. Read-only research did not run a new movie job or install alternative models.

## Step 1 — Add regression fixtures and dual-timeline contract

Files: `backend/diarization.py`, `tests/test_diarization.py`, `tests/test_diarization_runtime.py`, `tests/test_vocal_timeline.py`.

- Retain regular overlapping activity and exclusive alignment separately; derive overlap intervals without collapsing participants.
- Persist actual engine/model revision, input audio hash, timebase, effective execution device and schema version.
- Keep the existing `turns` compatibility view explicit; all callers requiring clean anchors must switch to regular turns.
- Sum union-duration per unique speaker before ranking temporal candidates. Different speaker candidates remain separate.
- Report temporal coverage as an overlap ratio, not a calibrated identity probability.

Verify first: same speaker in two adjacent turns stays A; A/B simultaneous activity survives; exclusive alignment does not certify clean audio; missing-word and word-level alignment paths behave conservatively; old projects load without deleting their artifacts. Stub CUDA-to-CPU retry must report CPU truthfully. Validate on a short annotated real exchange.

## Step 2 — Make clean-reference selection use real overlap evidence

Files: `backend/voice_bank_quality.py`, `backend/automatic_dialogue.py`, appropriate voice-bank tests.

- Subtract other-speaker regions from regular activity before choosing identity anchors and cloning references.
- Add voiced-duration, clipping, silence and overlap evidence; unresolved or mixed anchors cannot become technically clean by assertion.
- Preserve existing accepted takes and review histories. New analysis creates a new revision, not an overwrite of a reviewed source.
- Remove any factual age/gender claim derived only from F0 thresholds; preserve measured register and user/provider casting metadata.

Verify: an exclusive alignment winner inside an A/B overlap cannot be accepted as a one-speaker reference. Stable references retain exact hashes. Childlike/high-register samples outside the old F0 range stay explicitly uncertain rather than being assigned a stock adult voice.

## Step 3 — Establish an annotated evaluation harness

Files: new `scripts/evaluate_speaker_identity.py`, `backend/speaker_evaluation.py`, `tests/test_speaker_evaluation.py`; private fixtures/reports under ignored runtime storage.

- Use supplied/reviewed short real clips and a source-time RTTM/JSON ground truth. Record scoring settings and source/model hashes.
- Score DER components, speaker count, global ID swaps, overlap precision/recall, word ownership and reference contamination.
- Include multiple similar-register voices, rapid alternation, late speakers and long-gap returns. Synthetic pitch tones test only numerical helpers.
- Freeze a current Community-1 baseline before adding/changing engines. Record runtime, peak RAM/VRAM and cancellation/restart behavior.

Verify: known injected swaps and erased overlaps worsen the corresponding metrics. Repeating an unchanged evaluation reuses artifacts. Reports distinguish measured data, skipped fixtures and unverified categories.

## Step 4 — Add learned identity embeddings and project-wide reconciliation

Files: `backend/speaker_engine.py`, new `backend/speaker_embeddings.py`, `backend/analysis_pipeline.py`, registry tests.

- Define a pluggable embedding adapter. First evaluate the pyannote/WeSpeaker model already associated with the chosen baseline; ECAPA-TDNN is an alternate isolated pilot.
- Process bounded clean excerpts, retaining model/input hashes and multiple anchors per speaker. Do not preload a whole film as multiple waveform copies.
- Link independently processed overlapping chunks to one project-wide registry using embeddings, temporal agreement, best/second-best margins and cannot-link evidence.
- Resolve IDs deterministically without renumbering established identities when a late speaker arrives. Resume interrupted chunks and reconcile duplicates in overlap bands.
- Calibrate thresholds against the real evaluation set; pitch is supplementary, not a unique fingerprint. Low evidence means unresolved/new provisional ID.

Verify: two same-pitch people remain distinct; the same returning voice matches across scenes; whispers/shouts do not silently create a new identity; swapped chunk-local IDs reconcile; missing identity evidence never becomes a fabricated SPEAKER_00. Restart preserves mapping and anchors.

## Step 5 — Connect identity to the actual analysis pipeline

Files: `backend/analysis_pipeline.py`, `backend/chunked_asr.py`, relevant project state/API modules and cache tests.

- Wire bounded inference/registry reconciliation into the real Analyse flow, not just an offline phase report.
- Check full-duration coverage and absolute time offsets; retain silent spans in the clock.
- Preserve reliable existing word timestamps. Optional forced alignment must be language-compatible and dependency-isolated.
- Surface unresolved words and disagreements; do not choose a dominant voice simply to eliminate warnings.
- Version cache signatures by changed audio/model/embedding/schema/options. Recompute affected stages only.

Verify: start/end coverage, late arrivals and return after ten minutes; boundary deduplication; word timestamps unchanged by speaker reassignment; analysis resume and changed-input invalidation. Existing valid separation and accepted outputs remain untouched.

## Step 6 — Add a bounded overlap-specific processing branch

Files: new `backend/speaker_overlap.py`, analysis/timeline/mixing modules, overlap tests.

- First expose overlapping lanes accurately without claiming separate recovered words.
- Pilot speech-to-speech separation only on flagged crops. Match each separated output to global anchors; separator output order is not identity.
- Retain original audio and crop offsets. Test channel swaps, leakage and damaged/missing words against source context.
- Only enable automatic overlap transcription after a measured improvement. Unsupported three-plus/crowd regions remain review items; do not force a two-speaker separator onto them.
- Mixing must preserve intended overlap timing and original BGM/SFX; avoid shifting every second speaker after the first as a shortcut.

Verify: two overlapping streams yield independent correct ownership when supported; unresolved regions remain visible; speech is not silently dropped or doubled. Listen to source/crop/dubbed mix and verify decode/timing.

## Step 7 — Add casting recommendations and persistent voice locks

Files: `backend/automatic_dialogue.py`, `backend/voice_profiles.py`, `backend/voice_consistency.py`, character state and API modules.

- Maintain measured source descriptors separately from user-confirmed casting tags and target voice-bank metadata. Defaults are unknown where evidence is missing.
- Rank eligible Hindi references using reviewed quality, timbre/register compatibility, delivery, Hindi support and audible differentiation. Source re-identification scores cannot simply become target-voice similarity scores.
- Offer a few short auditions per character; preserve the existing genuine engine/reference contract and approval evidence.
- Persist provider/model, voice ID, selected reference/transcript hashes, settings, assignment revision and decision provenance.
- One locked character voice remains stable throughout the film. Support explicitly reviewed contextual variants without silent replacement. Changed evidence invalidates affected synthesis clips, not the whole movie.

Verify: no mid-film voice substitution; mapping survives restart; similar-pitch voices remain distinguishable in Hindi auditions; missing eligible references never produce a fake clone or unlabelled stock fallback. Human audition decisions are recorded, not manufactured by test flags.

## Step 8 — Add character review before expensive dubbing

Files: `web/app.js`, `web/index.html`, existing white-theme styles, API/review persistence and frontend tests.

- Show estimated speakers, unresolved clusters, analysed coverage and real stage progress.
- Cards show stable ID, first/last occurrence, multiple original examples, measured descriptors, editable casting tags, Hindi audition choices and voice lock.
- Add timeline navigation, simultaneous lanes, rename, merge, split/turn reassignment and undo. Changes create auditable revisions.
- Distinguish suggested, user-confirmed and locked states. A reviewed card count is not the same as unique actor/character accuracy.
- Preserve white UI, accessible focus, Hindi typography and the authorised embedded browser workflow.

Verify through real clicks and reload: corrections persist; only affected synthesis is invalidated; unresolved identity blocks automatic voice locking but supports an explicit user choice; controls represent real saved actions. Capture local UI proof.

## Step 9 — Optional visual evidence and model challenger pilots

- TalkNet-style active-speaking evidence may associate an anonymous face track with a voice; off-screen ownership stays audio-based. Reaction shots, occlusion and lip-sync mismatch must not force a wrong match. No actor-name/gender inference from face appearance.
- Compare Nemotron-3 with Community-1 on the same fixtures only when setup is authorised. Its eight-speaker capacity is a routing constraint, not the movie's cast limit.
- VibeVoice-ASR is a larger-hardware comparison, not a demonstrated 4GB default. Keep alternate dependencies isolated from the working main/clone environments.
- Save explicit licensing/model-revision evidence. Cloud comparison needs separate authorisation to upload the user's private audio; this research does not provide it.

Verify: before/after metrics, actual VRAM/time, late identity continuity and supported cast size. A new model is adopted only on demonstrated domain improvement, not a README speed claim.

## End-to-end acceptance

On a reviewed small real video, detect provisional identities, correct any uncertain ownership, audition/lock Hindi voices, synthesize, fit, preserve original music/effects and render. Verify every clip's identity/reference hash, source-time placement, complete audible dialogue, naturalness, overlap and full decode. Listen to the actual mix. Then evaluate a contiguous 10–15 minute scene sequence; whole-film processing follows only after these gates pass.

Maintain bounded workers, checkpoints, clear setup errors and measured CPU/GPU fallback. Preserve the three accepted voice auditions and successful artifacts required by existing project rules. No universal accuracy percentage, exact-age inference or perfect lip-sync claim is a release criterion supplied by this research.

## Execution batches

First implement and verify Steps 1–3 together: raw overlap preservation, unique-speaker attribution, safe reference windows and a real baseline. Then implement Steps 4–5 for global continuity, followed by casting/review. Overlap recovery and visual fusion are separate evaluated adapters; they must not delay preserving overlap evidence now.

Full findings and primary-source links: `docs/research/2026-10-13-speaker-identity-and-casting.md`.
