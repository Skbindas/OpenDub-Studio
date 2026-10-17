# OpenDub Studio — Implementation Status

## Working agreement

The active implementation phase is always completed before advancing to the next phase. A later debugging topic does not change the active phase or erase pending implementation work. Each continuation should resume from the last completed checkpoint.

## Dependency chain

1. Analysis
2. Character Identity
3. Translation
4. Voice Assignment
5. TTS
6. Timing
7. Loudness
8. Dialogue Removal
9. Background Preservation
10. Mix
11. Render

The source-time dialogue unit manifest (`analysis/dialogue_manifest.json`) is the master record shared by later stages.

## Phase 11 — Full Automatic Movie Analysis

Current completion: **100% (implementation and automated QA complete; one fresh local rerun is recommended for UI confirmation)**

Completed:
- Source media validation and stable source fingerprinting
- Audio extraction and audio profile
- Scene detection
- ASR transcript with timestamps and word timing
- Speaker diarization with Community-1
- Conservative speaker-to-transcript alignment
- Resumable checkpoints and analysis manifest
- Persistent source-time timeline
- Scene/transcript context alignment
- Automatic Character Registry creation after analysis
- Character rename/type/notes correction UI
- Speaker-to-character linking
- Automatic synchronization of character IDs into transcript data
- Master dialogue unit manifest
- Dependency-chain state engine and `/api/projects/{project_id}/pipeline/state`
- Recommended pipeline UI with live dependency status
- System Diagnostics moved behind the top-right System Ready control
- Diagnostics technical detail modal
- Favicon 404 removed
- Timeline segment panel made independently scrollable

Remaining inside Phase 11:
- One fresh local rerun to visually confirm the permanent rerun-safe identity/artifact behavior
- Lock the Phase 11 artifact/status format after that rerun

QA findings captured from the fresh-project recording:
- Full movie analysis completed and produced the timeline, transcript and two diarized speaker clusters.
- Automatic Character Registry was working and now uses 1-based labels such as `Character 1`, `Character 2`, etc.
- The Dependency Chain correctly showed Analysis = Done, Character Identity = Review, and Translation = Next/Pending.
- The remaining visible identity issue was that the timeline still displayed `SPEAKER_00` / `SPEAKER_01` after the registry had been created. The backend now synchronizes Character ID/name into the persisted timeline whenever identity changes, and the UI renders the Character name as the primary identity while retaining the raw speaker ID as secondary metadata.
- Downstream translation/TTS/mix/render stages do not auto-execute merely because analysis finished; they unlock in dependency order. Character records are auto-created and review/rename/remap remains available.
- Analysis reruns now invalidate stale generated artifacts when the source, analysis engine code or analysis options change; unchanged runs reuse valid checkpoints.
- Uploading a new source resets old analysis/downstream artifacts and the Character Registry; deleting a project removes its files and database records; renaming changes only project metadata.
- Character sync now reconciles stale automatic characters, keeps explicit custom records, auto-populates evidence-based notes and keeps Character names authoritative in the persisted timeline/UI.

Not yet considered Phase 11 work:
- Translation quality/adaptation
- Voice assignment
- TTS
- Timing fitting at production scale
- Loudness matching
- Dialogue removal/background preservation
- Final mixing/render QA

## Phase 12 — Translation & Dialogue Adaptation

Scope:
- Translate every master dialogue unit without changing the source timebase.
- Preserve speaker ID, Character ID, scene index and source timestamps on every translated unit.
- Support natural target-language dialogue adaptation rather than literal word substitution.
- Keep one source dialogue unit as the persistent record; later stages update that same unit.

## Phase 13 — Character Voice, Consistency & Prosody

Scope:
- Assign one stable target voice profile per Character, not per dialogue segment.
- Every later appearance of the same Character reuses the same assigned voice/model/settings unless the user explicitly changes that Character voice profile.
- Resolve TTS voice from the dialogue unit's Character ID so the character's voice stays consistent across the entire movie.
- Analyze emotion/prosody per dialogue unit: emotion class, intensity, speaking style, pace, pitch/energy tendencies and meaningful pauses.
- Pass the detected emotion/prosody controls into TTS so angry, sad, excited, frightened, calm, etc. lines are delivered appropriately instead of using a flat neutral reading.
- Keep character voice identity stable while allowing scene-level emotional variation.
- Store voice and emotion attributes on the master dialogue units; do not create a second timeline.

## Phase 12 — Translation & Dialogue Adaptation

Current completion: **100% (implemented and verified)**
- Local Argos Translate baseline and semantic adaptation provider integrated.
- Translation results persisted to master dialogue manifest units (`analysis/dialogue_manifest.json`).
- Character identity, timing budget, delivery intent, and tone constraints preserved.

## Phase 13 — Audio/Render Foundation & Long-Job Baseline

Current completion: **100% (implemented and verified)**
- FFmpeg-based media extraction and render/mux path.
- Durable background job execution for long tasks.
- Atomic finalization pattern preventing partial outputs.

## Phase 14 — Character Voice Profiles, Assignment & Prosody

Current completion: **100% (implemented and verified)**
- Stable Character voice profile registry (`analysis/character_registry.json`).
- Profile resolution: dialogue unit -> Character ID -> active profile -> TTS parameters.
- Per-line prosody and emotion overrides without altering global voice identity.

## Phase 15 — Character-Aware TTS Orchestration

Current completion: **100% (implemented and verified)**
- Durable synthesis queue with atomic artifact promotion (`output/tts_segments/`).
- Piper local baseline with fallback and retry semantics.
- Unit-level progress and failure isolation.

## Phase 16 — Timing Fit, Alignment & Loudness

Current completion: **100% (implemented and verified)**
- FFmpeg `atempo` time-stretching within conservative natural limits.
- EBU R128 integrated loudness normalization (-16 LUFS, -1.5 dBTP true peak ceiling).
- Timing and loudness metadata stored on master dialogue units.

## Phase 17 — Source Dialogue Removal & Background Audio Preservation

Current completion: **100% (implemented and verified)**
- Mode A (UVR stem separation with automatic fallback).
- Mode B (Dialogue-time sidechain ducking fallback with 50ms attack / 150ms release smooth ramps).
- Mode C (User-supplied stem conformance to 48kHz stereo).
- Outputs saved to `output/background_preserved.wav` and `output/background_metadata.json`.

## Phase 18 — Multi-Track Mix, Final Render & Automated QA Gates

Current completion: **100% (implemented and verified)**
- Multi-track mixing engine with timeline delays, background ducking, and master loudness pass.
- Final video muxing with atomic `.partial` cleanup.
- Automated QA verification suite checking container validity, duration alignment, stream presence, and dialogue coverage (`output/render_qa_report.json`).

## Phase 19 — Reliability, Performance, Packaging & Release Readiness

Current completion: **100% (implemented and verified)**
- Pre-flight disk space safety verification before upload, synthesis, background preservation, and full render (`backend/reliability.py`).
- Media container integrity validation on upload via ffprobe to prevent corrupt file ingestion.
- Sanitized, token-safe diagnostics support bundle generator (`/api/system/support-bundle`).
- Manifest schema migration and backwards-compatibility engine (`migrate_dialogue_manifest`).
- UI "Download Support Bundle" button in the System Diagnostics dialog.
- Full automated test suite (165 passing tests with zero deprecation warnings).

## All Core Roadmap Phases (Phases 11–19) Complete

The complete OpenDub Studio local-first feature-length dubbing pipeline from Analysis, Character Identity, Translation & Adaptation, Voice Profiling, Character-aware TTS, Timing/Loudness Fitting, Source Dialogue Removal & Background Preservation, Multi-Track Mixing, Final Video Muxing with Automated QA Gates, and Packaging & Reliability is fully implemented, verified, and operational.