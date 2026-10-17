# OpenDub Studio — Master Product Requirements & Implementation Plan

**Document:** Master PRD + Engineering Roadmap  
**Version:** 1.0  
**Date:** 2026-09-27  
**Canonical working branch:** `phase-12-semantic-adaptation-provider`  
**Product:** OpenDub Studio — local-first, AI-assisted movie dubbing studio  
**Status:** Phase 14 active; Phase 13 is treated as complete per the latest project checkpoint, subject to a repeatable local smoke test.

> This document is the canonical forward implementation plan. Existing implementation is not to be duplicated. Before coding a phase, inspect the current branch, tests, artifacts and CI, then implement only the gaps. This plan distinguishes completed checkpoint claims, existing primitives, and future acceptance requirements.

---

## 1. Product vision

Enable a user to import a movie, automatically analyze its dialogue and characters, translate/adapt each line, assign a stable voice to every character, preserve emotional delivery, replace source dialogue while retaining music/SFX/ambience, and export a synchronized dubbed movie.

The application remains local-first: media processing, project data and generated audio live on the user's machine. External AI providers are optional adapters, not a mandatory runtime dependency. User-facing processing must be observable, resumable and cancellable.

### 1.1 Product goals

1. Maintain one immutable source-time dialogue timeline from analysis through final render.
2. Assign one persistent target voice profile per Character ID; reuse it for every scene and line.
3. Preserve line-level emotional intent and delivery variation without changing the character's underlying voice identity.
4. Preserve original background music, ambience and sound effects while attenuating/replacing original speech.
5. Provide a clear stage-by-stage UI with progress, logs, retry and review states.
6. Never silently claim a production-ready result if identity, translation, timing, source separation or render QA has unresolved errors.
7. Keep generated artifacts traceable to the source fingerprint, model/provider, settings and pipeline version.

### 1.2 Non-goals for the initial production release

- Fully automatic lip-sync or face/lip animation.
- Training a custom voice-cloning model as a default feature.
- Cloud upload of user movies as a requirement.
- Guaranteed perfect source separation for every soundtrack.
- Automatically cloning a real person's voice without user rights/consent.
- Replacing source video frames or changing the movie's visual edit.

---

## 2. Canonical phase map

| Phase | Scope | Working status |
|---|---|---|
| 13 | Existing render/audio foundation, long-render validation, artifact cleanup and integration baseline | Complete per last checkpoint; rerun smoke test |
| 14 | Character voice profiles, stable assignment and emotion/prosody metadata | Active |
| 15 | Character-aware TTS orchestration and synthesis artifact management | Planned/integration |
| 16 | Timing fit, dialogue alignment, loudness and true-peak control | Existing FFmpeg primitives; production integration |
| 17 | Source dialogue removal/separation and background preservation | Major planned implementation |
| 18 | Professional mix, final render and automated audio/video QA | Existing baseline; production hardening |
| 19 | End-to-end reliability, recovery, performance, packaging and release readiness | Planned |

The pipeline's data dependency is:

**Analysis → Character Identity → Translation/Adaptation → Voice Assignment → TTS → Timing → Loudness → Dialogue Removal → Background Preservation → Mix → Render → QA/Export**

Do not make downstream work run automatically merely because analysis finishes. Each stage becomes eligible only when its prerequisites and validations pass. Allow explicit user-approved overrides only where safe, and record the override in the project manifest.

---

## 3. Existing architecture and source of truth

### 3.1 Current stack

- Backend: Python + FastAPI.
- UI: vanilla HTML/CSS/JavaScript.
- Project metadata: SQLite.
- Media pipeline: FFmpeg/FFprobe.
- Analysis: faster-whisper, pyannote diarization, scene detection and checkpointed worker jobs.
- Translation: local Argos Translate baseline and provider abstraction work on the active branch.
- Local TTS baseline: Piper.
- Target hardware reference: Windows 11, 16 GB RAM, NVIDIA RTX 3050 Laptop GPU with 4 GB VRAM. GPU memory is constrained; model loading must be lazy and sequential where practical.

### 3.2 Master dialogue manifest

Canonical path: `analysis/dialogue_manifest.json`.

It is the sole source-time dialogue record. Later stages update the same unit; do not create a parallel independent timeline.

Every unit should retain at least:

- Stable `segment_id`, `segment_index`
- `start_sec`, `end_sec`, `duration_sec` (source timeline)
- `scene_index`
- `speaker_id`, confidence and review flags
- `character_id`, resolved display name
- `source_text`, word timestamps when available
- Translation: target language, translated/adapted text, provider/model, status, review metadata
- Voice: profile ID/version, Character ID, resolved model/voice/speaker ID
- Prosody: emotion, intensity, delivery intent, rate/pitch/energy controls and confidence
- TTS: status, output path, sample rate, channels, duration, model/provider, generation settings and content hash
- Timing: source target duration, measured TTS duration, applied tempo, fit quality and warnings
- Loudness: measured integrated LUFS, true peak, gain, normalization settings and output artifact
- Replacement/separation: source mask, speech estimate, background estimate, method, confidence, fallback/duck settings
- Mix/render provenance, validation results and error/retry history

All paths stored in manifests must be project-relative where possible. Write JSON atomically through temporary files and replace. Validate schema/version on read and support migration functions.

### 3.3 Artifact and cache contract

Every generated artifact should record:
- input artifact hashes/fingerprints;
- stage implementation version;
- relevant model/provider and model revision;
- user settings;
- output path/hash and creation time;
- status and structured error.

A cache hit is valid only when all relevant inputs/settings/versions match. On change, invalidate only the affected stage and its downstream dependents. Preserve source media, user-authored translations, manually edited Character names and explicit voice-profile choices unless their own dependency changes.

---

## 4. Phase 13 — Audio/render foundation and long-job baseline

**Checkpoint:** marked complete in the latest project conversation. Do not rebuild. Run a repeatable smoke test against the current branch before relying on it.

### 4.1 Existing baseline to retain

- FFmpeg-based media extraction and render/mux path.
- Durable/background job execution for long tasks.
- Temporary output and atomic finalization pattern for render.
- Source movie and core project metadata preserved during cleanup.
- Long-render CI/benchmark checkpoint previously reported: 90-minute render scenario, 74 tests, cleanup verification.

### 4.2 Required verification

1. Create a disposable project and import a valid test movie.
2. Run the existing analysis and downstream baseline render path.
3. Verify output is non-empty and FFprobe can read streams/duration.
4. Verify video stream is copied where supported, target audio is AAC at configured bitrate, subtitle streams/metadata behavior is documented.
5. Verify failed render removes only partial output and retains recoverable inputs.
6. Verify cleanup runs only after render validation succeeds.
7. Verify a 90-minute synthetic or approved test asset does not exhaust memory/disk or time out unexpectedly.
8. Record test input characteristics, duration, output size, peak memory, elapsed time and CI run URL.

### 4.3 Exit criteria

- Smoke test and CI green on the current implementation branch.
- Render output is probeable, complete, and not a zero-byte or partial file.
- Source, Character Registry, master manifest and required audit metadata survive cleanup.
- No phase 14–19 implementation begins by deleting or bypassing this baseline.

---

## 5. Phase 14 — Character Voice Profiles, Assignment and Prosody

**Status:** active. Existing checkpoint includes versioned voice profiles, API validation, Character-ID manifest resolution, per-line prosody metadata and Piper compatibility. Inspect current branch and tests before extending.

### 5.1 Requirements

**Voice identity**
- Each Character ID has one persistent voice profile, not one voice per segment.
- Every dialogue unit resolves voice from its `character_id`; no fallback to a global voice when a character-specific mapping exists.
- A character appearing in multiple scenes retains the same profile/model/voice and speaker ID.
- User can preview, assign, change, version and restore a Character's voice.
- Missing or incompatible voice assignments block TTS with an actionable message.

**Voice profile fields**
- `voice_profile_id`, display name, provider/engine, model path or provider voice ID.
- Model version/hash, language and locale, supported speaker IDs.
- Voice characteristics: optional pitch/rate/style descriptors, not claims about a real identity.
- Sample rate/channels, supported controls, default prosody, licensing/source note.
- Profile version, created/updated timestamps and validation status.

**Prosody/emotion per line**
- Record emotion class (neutral, calm, warm, serious, angry, sad, excited, fearful, urgent, comedic, etc.), intensity, delivery intent, pace, pitch/energy controls and pause intent.
- Separate stable Character voice identity from scene/line-level emotion.
- Use source audio and dialogue context where available; preserve manual user edits.
- Confidence and review-required flag for ambiguous emotion. Never silently force a high-intensity emotion from weak evidence.
- For providers that do not support a control, map to supported controls conservatively and show an unsupported-control warning.

### 5.2 Backend implementation

1. Inspect existing voice-profile modules/routes and tests on the active branch.
2. Define/validate a versioned profile schema and migration strategy.
3. Implement CRUD/preview/assign APIs with path validation and safe provider IDs.
4. Implement a single resolver: dialogue unit → Character ID → active profile version → provider/model voice parameters.
5. Validate language compatibility, model existence, Piper speaker ID bounds and supported prosody controls.
6. Persist resolved profile version and prosody snapshot onto the dialogue unit before synthesis.
7. Add audit history when a user changes a Character's voice. A profile change should mark only that Character's dependent TTS/timing/loudness artifacts stale.
8. Add tests for repeated scenes, missing profiles, profile version changes, speaker-ID validation and unsupported emotion controls.

### 5.3 Frontend implementation

- Character Registry gets a voice-profile selector and profile status badge.
- Add preview button and per-character voice settings panel.
- Dialogue review rows show inferred emotion, intensity, delivery intent and confidence.
- Allow per-line override without changing the Character's global voice profile.
- Show whether an emotion value is automatic, user-edited or unsupported by the selected TTS engine.
- Show “voice missing / incompatible / ready” state and block next stage if invalid.

### 5.4 Acceptance criteria

- A Character speaking in 20 different scenes uses the same profile/version unless explicitly changed.
- Two different Characters can use different profiles.
- Changing Character A's voice invalidates A's generated audio, not Character B's artifacts.
- Per-line emotion varies while the Character's stable voice identity remains unchanged.
- Missing voice/profile produces a visible actionable validation error.
- Tests cover all of the above and CI passes.

---

## 6. Phase 15 — Character-aware TTS orchestration

### 6.1 Requirements

Generate one target-language speech artifact per dialogue unit using the resolved Character voice and line-level prosody. TTS must be resumable, deterministic where the provider permits, and safe to retry.

### 6.2 Backend

1. Define a provider adapter contract: validate capability, synthesize, return artifact metadata, report structured errors.
2. Keep Piper as the local baseline adapter; add other providers only behind the same interface and explicit user configuration.
3. Build a durable synthesis queue with per-unit states: pending, queued, running, completed, failed, cancelled, needs_review.
4. Resolve voice from the Character profile snapshot stored on each dialogue unit.
5. Pass translated/adapted text, locale, speaker ID, rate/pitch/style/emotion controls supported by the provider.
6. Write to a temporary file, probe duration/format, then atomically promote to the canonical artifact path.
7. Store provider, model/version, voice profile version, settings, hashes, duration, sample rate, channels, error and retry count.
8. Add concurrency and resource limits. On 4 GB VRAM, avoid loading several large models concurrently; CPU fallback should be explicit and observable.
9. Implement cancellation, retry with backoff for transient errors, and no retry loops for invalid text/model/configuration.
10. Never synthesize an empty translation or silently substitute another Character's voice.

### 6.3 Frontend

- “Synthesize all ready lines” and per-line synthesize/retry.
- Live progress: completed/total, current Character/segment, elapsed time, queued/failed count.
- Play generated line, compare source/target, regenerate selected line.
- Preserve successful outputs when one line fails.
- Show model download/install separately from synthesis and never imply an absent model is installed.

### 6.4 Acceptance criteria

- Same Character profile resolves consistently across all units.
- Interrupted synthesis resumes without regenerating valid artifacts.
- One failed segment does not destroy successful segment audio.
- All generated audio is probeable and manifest-linked.
- UI progress reflects actual queue state, not a simulated percentage.
- Unit tests + integration tests for success, timeout, cancellation, invalid model, missing Piper, retry and resume.

---

## 7. Phase 16 — Timing fit, alignment and loudness

### 7.1 Requirements

Fit each generated line into the original source-time window while preserving intelligibility and natural pacing. Loudness must be measured and normalized using integrated loudness and true-peak constraints, not peak amplitude alone.

### 7.2 Timing engine

- Source window is `start_sec` to `end_sec` from the master manifest and is immutable.
- Measure actual TTS duration with FFprobe.
- Use conservative time-stretch limits configurable by provider/language; current FFmpeg `atempo` primitive is a baseline, not a guarantee of natural speech.
- Prefer synthesis rate control/regeneration before extreme post-stretching where the provider supports it.
- If fit exceeds quality limits, flag “timing review required” instead of aggressively compressing.
- Add configurable pre/post padding, leading/trailing silence trim and crossfade metadata.
- Preserve word-level timing when available; do not invent word timings if only segment timing exists.

### 7.3 Loudness

- Measure source dialogue and synthesized dialogue separately where source separation provides reliable stems.
- Use FFmpeg loudnorm / EBU R128-compatible measurement and true peak; store measured values and applied gain.
- Establish project-level target loudness and true-peak ceiling as configurable profiles. Defaults should be documented and tested, not hidden constants.
- Avoid normalizing every tiny line independently in a way that causes audible pumping; support per-character/scene continuity and a final mix loudness pass.
- Detect clipping, silence, unexpectedly low level and large loudness jumps.

### 7.4 Acceptance criteria

- Fitted line duration matches source window within configured tolerance, with all deviations recorded.
- Extreme tempo adjustments are flagged for review.
- Loudness reports include measured integrated LUFS, true peak and applied gain.
- No output exceeds the configured true-peak ceiling beyond measurement tolerance.
- Regression tests cover short/long lines, silence, low-volume input, clipping and speech-duration extremes.

---

## 8. Phase 17 — Source dialogue removal and background preservation

**This is a critical audio-quality phase.** Never simply mute the entire original audio track during dialogue. Preserve music, ambience and effects as much as technically possible.

### 8.1 Processing modes

**Mode A — Source separation (preferred when quality and resources permit)**
- Input original movie audio.
- Produce dialogue/speech estimate and background/music/SFX estimate.
- Validate duration, sample rate, channels, clipping and separation confidence.
- Keep the background stem; replace/attenuate speech stem with dubbed dialogue.
- Store model/method/version, input hash, stem paths, quality metrics and review flags.

**Mode B — Dialogue-time ducking fallback**
- Use the source dialogue intervals from the master timeline.
- Apply configurable gain reduction only during dialogue windows.
- Add attack/release ramps and crossfades to avoid hard cuts/clicks.
- Preserve source audio between dialogue windows.
- Clearly label the result as ducking fallback, not isolated dialogue removal.
- Allow user to adjust reduction, ramp lengths and safety margins.

**Mode C — User-supplied stems**
- Allow a user to supply dialogue-free background or separate stems.
- Validate media compatibility and align duration/timebase.
- Record provenance and do not overwrite the original source.

### 8.2 Backend implementation

1. Define a separation adapter interface and supported model capability metadata.
2. Make models optional downloads with license/source information and disk-space checks.
3. Implement audio chunking/overlap-add for long movies where model context/memory requires it.
4. Use the local hardware budget (RTX 3050 4 GB) to select chunk size, precision and CPU fallback; never assume a model fits VRAM.
5. Keep a canonical background artifact and optional dialogue stem, both tied to source fingerprint.
6. Apply speech masks with smoothed boundaries; support overlapping dialogue and uncertain diarization.
7. When separation fails or confidence is low, keep source audio and offer ducking/user-supplied stems; never silently output silence.
8. Add A/B preview: original, estimated background, dialogue estimate, final replacement.
9. Store the selected mode and all settings on each affected timeline unit and project mix manifest.

### 8.3 Acceptance criteria

- Source audio is never destructively overwritten.
- A separation failure does not delete source audio or prevent a recoverable fallback.
- Background output duration aligns with source duration within a documented tolerance.
- No hard-cut clicks at dialogue boundaries in automated boundary checks and listening QA.
- Overlapping speakers and uncertain intervals are flagged.
- Test clips include dialogue over music, effects, silence, overlapping dialogue and loud transient effects.

---

## 9. Phase 18 — Professional mix, final render and QA

### 9.1 Mix requirements

- Align background and each dubbed line to the source movie timebase.
- Support dialogue bus, background bus, optional music/effects stems and final master bus.
- Apply dialogue ducking to the background only when configured; use smooth attack/release.
- Apply per-line fades/crossfades and avoid clicks at joins.
- Keep stereo/channel layout explicit; do not silently downmix multichannel source without recording the policy.
- Apply final loudness/true-peak pass to the complete mix.
- Detect clipping, silence, missing lines, duplicated lines, overlap anomalies, duration mismatch and channel-layout mismatch.
- Save a mix report and reproducible settings snapshot.

### 9.2 Render requirements

- Mux original video with the final mix while preserving video stream where compatible.
- Keep expected subtitle/metadata behavior explicit and test container compatibility.
- Write to a partial/temp path; only atomically promote after FFprobe and QA pass.
- Keep render resumable/retryable where possible; never expose a partial output as “completed”.
- Offer output container/audio bitrate settings with safe defaults.
- Preserve source, manifest, Character Registry, voice profiles and final QA report after cleanup.

### 9.3 Automated QA gates

Required checks:
1. File exists, size > 0, FFprobe succeeds.
2. Video and audio streams present; expected codecs and channels.
3. Render duration matches source within configured tolerance.
4. No unexpected early termination.
5. Audio peak/true peak within project ceiling.
6. Detect near-silence and missing dubbed segments.
7. Compare expected dialogue unit count against successful TTS/mix inclusion.
8. Verify all audio paths referenced by the mix manifest exist.
9. Verify no partial/temp artifact is marked final.
10. Produce a human-readable QA report with pass, warning, fail and skipped statuses.

A hard-fail QA item blocks “Release-ready” status. Warnings may permit export only with explicit user acknowledgement recorded in the project.

### 9.4 Acceptance criteria

- Render only starts after mix and required QA gates pass.
- A failed render retains all source and intermediate artifacts required for retry.
- Successful output is probeable and can be played.
- Final QA report and exact render settings are saved.
- Long-render test (including 90-minute profile) is repeated on CI or a controlled benchmark runner, with runtime, peak memory and output size recorded.

---

## 10. Phase 19 — Reliability, performance, packaging and release readiness

### 10.1 Reliability

- Durable jobs survive application restart; stale running jobs are reconciled to recoverable states.
- Each stage supports cancel, retry, resume and idempotent rerun.
- Structured logs include project ID, job ID, stage ID, unit ID and error category; avoid logging access tokens or private text unnecessarily.
- Add clear disk-space checks before model download, separation, TTS batch and render.
- Validate uploaded file size, extension, media probe and path traversal.
- Keep source files safe from accidental deletion; deletion requires explicit project action and clear confirmation.

### 10.2 Performance

- Measure CPU/GPU/RAM/VRAM/disk use per stage.
- Limit concurrent heavy model jobs based on detected hardware.
- Stream/chunk large audio rather than loading entire long movies into RAM.
- Cache models and analysis outputs with versioned fingerprints.
- Provide progress based on completed work units or measured duration; no fake progress.
- Maintain graceful CPU fallback and clearly indicate slower mode.

### 10.3 Packaging and release

- Document Windows setup, FFmpeg shared build, Python environment and optional models.
- Validate dependency pins and optional extras (ASR, diarization, translation, TTS, separation).
- Provide a diagnostics report and copyable support bundle that excludes secrets by default.
- Maintain migration tests for project manifest versions.
- Add clean-install smoke test and upgrade test.
- Document model licenses, voice rights, third-party dependencies and data locality.
- Create versioned releases with changelog, known limitations and test evidence.

### 10.4 Acceptance criteria

- Clean install and update path are tested.
- Project migration is tested from the previous manifest version.
- App restart during each major job stage is recoverable.
- Logs and support bundle contain no raw API keys/tokens.
- Release is tagged only after required CI, smoke tests and QA checklist pass.

---

## 11. Frontend information architecture

Recommended user journey:

1. **Create Project / Upload** — file progress, actual upload percentage, media validation.
2. **Analyze** — stage progress, transcript/timeline, scene and speaker review.
3. **Characters** — Character 1…N, rename/type/notes, voice profile and preview.
4. **Translate & Adapt** — source/target dialogue, translation provider, tone, intent, word/timing budget, suggest/edit/save/validate.
5. **Voice & Emotion** — character-level voice and line-level prosody.
6. **Synthesize** — queue progress, preview, retry failed lines.
7. **Timing & Loudness** — duration fit warnings, LUFS/true-peak reports.
8. **Dialogue Removal / Background** — separation vs ducking vs user stem, A/B preview.
9. **Mix** — dialogue/background buses, levels and final loudness.
10. **Render & QA** — output settings, render progress, validation report and final export.

Keep advanced controls collapsed by default but accessible. Each screen must explain blockers and the exact next action. The pipeline state endpoint remains the authoritative source for stage status.

---

## 12. API and module contracts

Use the existing FastAPI route conventions and project-scoped paths. Confirm actual route names before adding new ones; do not create duplicate endpoints.

Suggested logical API capabilities:

- Voice profiles: list/create/update/validate/preview; assign profile to Character ID.
- Prosody: read/update per dialogue unit; confidence and source metadata.
- TTS: queue selected/all eligible units, status, cancel, retry, preview.
- Timing: fit selected/all units, report, retry flagged lines.
- Loudness: measure/normalize and return LUFS/true peak/gain report.
- Separation: run/cancel/status, inspect stems and confidence.
- Background: select stem/fallback, set duck envelopes and preview.
- Mix: build, preview, report and invalidate on upstream changes.
- Render: start/status/cancel/retry, QA report and final artifact.
- Pipeline state: stage readiness, blockers, artifact freshness, progress and next recommended stage.

All mutating routes must validate project ownership/existence, payload bounds, path safety and prerequisite readiness. Return consistent structured errors with code, message, stage, retryability and actionable remediation.

---

## 13. GitHub engineering and delivery workflow

### 13.1 Branch and scope

Canonical working branch for the active implementation stream:
`phase-12-semantic-adaptation-provider`

Do not push unreviewed phase work directly to a release tag. Keep each logical phase increment small enough to review and revert.

### 13.2 Before each implementation task

On Windows PowerShell:

```powershell
cd "$env:USERPROFILE\OneDrive\Desktop\OpenDub-Studio"
git status --short --branch
git fetch origin
git switch phase-12-semantic-adaptation-provider
git pull --ff-only origin phase-12-semantic-adaptation-provider
```

If local work is uncommitted, inspect and preserve it; do not run reset/clean or overwrite user changes. Confirm branch and current HEAD before editing.

### 13.3 Implementation loop

For each feature:

1. Inspect the current implementation, API route, manifest schema and relevant tests.
2. Write acceptance criteria and identify downstream invalidation.
3. Add/modify backend module and schema validation.
4. Add API endpoint or update existing endpoint only when needed.
5. Add frontend controls with real callbacks and server-backed progress.
6. Add unit tests for logic and failure cases.
7. Add API/integration tests for prerequisite gates, persistence and rerun behavior.
8. Run format/compile/test commands locally where the environment supports them.
9. Review `git diff` for accidental generated media, secrets, unrelated changes and destructive operations.
10. Commit one coherent change with a descriptive message.
11. Push the active branch and inspect GitHub Actions.
12. Read failing job logs; fix the root cause, not just the workflow label.
13. Re-run CI until green; report run URL, commit SHA, test count and any skipped hardware-dependent tests.
14. Update `docs/IMPLEMENTATION_STATUS.md` and this PRD with actual completion evidence.
15. Merge only after CI and phase acceptance criteria pass.

### 13.4 Suggested PowerShell validation

Use the repository's actual scripts/workflow commands when available. At minimum:

```powershell
python -m compileall backend tests
python -m unittest discover -s tests -v
```

Run frontend syntax checks using the existing CI command/package if configured. Run a local app smoke test with the documented `start.bat`; verify health, diagnostics, pipeline state and the changed API/UI.

Do not claim a test passed unless the command or GitHub Actions result was observed. Hardware-dependent separation/GPU/render tests should be marked skipped/not run when the runner lacks required hardware, and then executed on a controlled local test machine.

### 13.5 Commit and push

```powershell
git status
git diff --check
git diff
git add <specific-files>
git commit -m "Phase NN: concise feature description"
git push origin phase-12-semantic-adaptation-provider
```

Use specific paths in `git add`; do not blindly add large movies, model weights, generated audio, credentials or local project databases. Keep test fixtures small and synthetic where possible.

### 13.6 CI failure protocol

- Identify exact failed workflow run, job and step.
- Fetch full logs and first failing assertion/traceback.
- Determine whether failure is code, test fixture, dependency/environment, flaky external service or hardware capability.
- Reproduce locally when feasible.
- Add a regression test before or with the fix.
- Commit the fix separately if it is a distinct concern.
- Re-run the workflow and verify the latest HEAD is green, not merely an earlier commit.
- Record run ID/URL and final conclusion in the implementation status.

---

## 14. Test strategy and release gates

### Unit tests
- Manifest schema, migration and artifact invalidation.
- Character voice resolution and profile versioning.
- Prosody validation and provider capability mapping.
- Translation/timing budget and line-level metadata.
- TTS artifact promotion, retries and state transitions.
- Timing fit and loudness calculations/report parsing.
- Separation masks, duck envelopes and crossfade generation.
- Mix graph construction and render command generation.

### Integration tests
- Analysis → Character Registry → translation → voice resolution → TTS → fit → loudness → separation/background → mix → render.
- Rename project, rerun unchanged, change source, change analysis settings, change Character mapping and change voice profile; verify only dependent artifacts invalidate.
- Stop/restart the app during each durable job and verify recovery.
- Simulate missing FFmpeg/Piper/model, corrupt input, disk full, timeout, provider error and invalid profile.

### Audio QA corpus
Maintain short, licensed/synthetic clips for:
- one speaker; multiple speakers; same character in distant scenes;
- emotional shifts by the same character;
- dialogue over music and sound effects;
- overlapping dialogue;
- silence and abrupt transients;
- long speech, very short interjections and non-speech vocalization;
- stereo and multichannel input;
- different source/target language pairs.

Store expected metadata and measurable tolerance bands. Human listening remains required for subjective separation, emotion naturalness and intelligibility; automated metrics alone cannot certify these.

### Release gate
A phase is complete only when:
- implementation and docs are committed;
- required unit/API/integration tests pass;
- latest relevant CI run on the intended HEAD is green;
- no known data-loss or source-overwrite defect remains;
- acceptance criteria are checked off;
- limitations and hardware-skipped tests are recorded;
- a local smoke test is completed when CI cannot exercise actual media/GPU behavior.

---

## 15. Phase completion tracking template

Copy this section for each phase in `docs/IMPLEMENTATION_STATUS.md`:

- Phase and scope:
- Starting commit / branch:
- Files/modules changed:
- API/schema changes:
- UI changes:
- Tests added:
- Local commands and outcomes:
- CI run ID / URL / conclusion:
- Hardware-dependent tests skipped and reason:
- Acceptance criteria passed:
- Known limitations:
- Artifacts/schema migrations:
- Downstream stages invalidated:
- Completion percentage:
- Next exact implementation task:

A percentage is an engineering estimate, not a test result. Mark a phase complete only after its defined exit criteria pass.

---

## 16. Immediate execution order from the current checkpoint

1. Pull and inspect the current active branch; confirm Phase 14 files and tests actually exist on that branch.
2. Run current CI and relevant voice-profile/prosody tests; reconcile the older Phase 13/14 naming in implementation docs.
3. Finish Phase 14 voice profile UI, per-character assignment, per-line emotion editing/review, provider capability validation and regression tests.
4. Implement Phase 15 TTS queue using the saved Character voice-profile version and per-line prosody snapshot.
5. Integrate Phase 16 timing/loudness into the master dialogue manifest and pipeline readiness gates.
6. Implement Phase 17 source separation with explicit fallback to dialogue-time ducking or user-supplied background stems.
7. Implement Phase 18 professional mix, render and automated QA gates.
8. Complete Phase 19 recovery/performance/packaging/release checks.
9. Run the complete end-to-end test corpus and long-render benchmark; publish a release only after evidence is recorded.

**Do not skip ahead to Phase 17/18 while Phase 14's Character-to-voice resolution and Phase 15's TTS artifacts are not stable.** Every later stage depends on those identity and artifact contracts.
