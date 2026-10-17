# OpenDub Studio roadmap

## Phase 1 — Local foundation
- Local web studio
- Persistent SQLite projects
- Browser refresh/restart persistence
- Project deletion with local artifact cleanup
- Windows install/start scripts
- FFmpeg detection
- Restart-safe job state

## Phase 2 — Media analysis
- FFmpeg media extraction
- scene detection
- audio extraction
- timeline model
- VAD / ASR
- source-language detection

## Phase 3 — Dialogue intelligence
- [x] Optional pyannote diarization adapter and timestamped speaker turns
- [x] Overlap-based speaker assignment to ASR segments with coverage confidence
- [x] Persist diarization JSON and expose speaker-aware transcript UI/API
- [ ] Speaker embeddings, dialogue editor, loudness / peak / speech-rate measurements
- [ ] Durable worker recovery for every media stage (in-process background tasks still limit restart recovery)

## Phase 4 — Global character engine
- [x] Persistent project-level character registry with stable character IDs
- [x] Character name/type/notes/review metadata and voice-profile placeholder schema
- [x] Link multiple acoustic speaker clusters to one global character
- [x] Speaker-to-character IDs reflected into transcript segments
- [ ] Visual character evidence, automated cross-scene clustering and actual voice embeddings/reference capture

## Phase 5 — Source separation
- [x] Optional UVR/audio-separator vocal-stem adapter
- [x] Preserve original extracted mix in analysis folder
- [x] Return vocal and instrumental candidates when produced
- [x] Safe original-audio passthrough fallback when dependency/model fails
- [ ] Dedicated dialogue-vs-singing classifier, quality scoring, and user-reviewed stem audition/mix controls

## Phase 6 — Translation and TTS
- [x] Local Argos translation adapter and per-segment translated transcript
- [x] Local Piper CLI TTS adapter for individual segment WAV generation
- [x] Sequential synthesize-all UI action with user-supplied voice model path
- [ ] Character-specific voice lock, emotion/prosody controls, voice reference management, automatic language package/model setup

## Phase 7 — Timing and mix
- [x] Pitch-preserving atempo fit with bounded rate and exact pad/trim to segment window
- [x] Per-segment loudness normalization
- [x] Timestamp-based clip placement and background sidechain ducking
- [x] Mix preview endpoint and in-browser audio player
- [ ] Waveform editing, interactive clip nudging, EQ/compression presets and listening-based quality review

## Phase 8 — Full render
- [x] FFmpeg video/audio mux preserving source video stream when possible
- [x] Background job with persisted job status and restart recovery
- [x] Final MP4 download endpoint and UI action
- [x] Optional cleanup after successful output verification (source and metadata retained)
- [ ] Chunked/incremental render checkpoints, cancel controls, codec/container selection and full-length stress tests

## Phase 9 — Server workers
- [x] Durable SQLite-backed worker queue with atomic job claiming and leases
- [x] Embedded local worker plus standalone external worker process
- [x] Worker heartbeat, stale-lease recovery and configurable retries
- [x] API queue/worker health endpoints
- [x] Docker server profile with separate API and worker services
- [x] Persistent shared filesystem contract via OPENDUB_DATA_DIR
- [ ] Object-storage adapter for S3/GCS/Azure
- [ ] GPU-specific worker images, distributed artifact cache and true remote rendering

## Phase 10 — Reliability and QA
- [x] Backward-compatible SQLite migrations for worker lease/heartbeat tables
- [x] Atomic job claiming with attempt counters and owner-bound lease updates
- [x] Worker heartbeat upsert and stale-worker cleanup
- [x] Queue unit tests for claim/release, heartbeat and legacy database migration
- [x] CI runs queue tests on every push and pull request
- [x] End-to-end media fixtures and FFmpeg render integration test (CI Run #284)
- [x] Durable cancellation and cooperative safe-checkpoint handling (CI Runs #298–#299; long-stage resume remains tied to persisted artifact checkpoints)
- [x] Frontend project-state restore and job reconnect after browser refresh (CI Run #298)


## Phase 12 — Semantic dialogue adaptation (completed; CI verified 2026-09-26)
- [x] Optional OpenAI-compatible semantic adaptation provider with conservative fallback
- [x] Review-only suggestion API; provider output cannot self-approve or write translation artifacts
- [x] Human approve/reject workflow and separate frontend review panel
- [x] Append-only JSONL decision audit with per-dialogue revisions and previous/candidate text
- [x] Backend synthesis gate for unapproved semantic adaptation
- [x] Deterministic candidate checks for non-empty text, character ID consistency, tone/delivery metadata, and heuristic timing
- [x] CI Run #248: 62 tests passed, Python compile and frontend JavaScript validation passed
- Note: semantic equivalence and measured audio duration are not machine-proven; human review and listening remain required.

## Phase 13 — Production hardening and end-to-end media QA (completed; CI verified 2026-09-26)

Implementation tracker (checked only after code and CI verification):
- [x] 13.1 — Redistributable generated media fixtures and end-to-end translation → synthetic TTS WAV → mix → FFmpeg render test (CI Run #284; actual video/audio streams verified)
- [x] 13.2 — Verify synthesized audio duration against each source dialogue window (ffprobe measurement persisted per segment; fit-required warning; CI Run #278)
- [x] 13.3 — Audit/revision history UI and restore prior approved revision (history/restore API, UI, append-only restore event; CI Run #278)
- [x] 13.4 — Durable cancellation requests, FFmpeg process termination/partial cleanup, worker retry suppression, persisted job state and browser refresh recovery (CI Runs #298–#299)
- [x] 13.5 — 90-minute synthetic feature-length render, duration verification, elapsed/output/peak-RSS profile, cancellation and failed-render cleanup tests (CI Run #307; 5,400s output duration, 223.28s render time, 49,320,644 output bytes, 109,936,640-byte peak FFmpeg RSS; 74 tests passed)
- [x] Add representative, redistributable generated media fixtures and an end-to-end translation-to-synthesis/render test
- [x] Verify synthesized audio duration against each source dialogue window (ffprobe duration measurement and fit-required warning; CI Run #278)
- [x] Add UI for inspecting revision/audit history and restoring a prior approved revision (history/restore API, UI, append-only restore event; CI Run #278)
- [x] Add cooperative cancellation checkpoints, durable cancellation state and browser refresh recovery for long-running jobs (CI Runs #298–#299)
- [x] Run full-length render and resource-usage stress tests (CI Run #307: synthetic 90-minute output duration verified; 223.28s elapsed, 49,320,644 output bytes, 109,936,640-byte peak FFmpeg RSS; 74 tests passed)

## Phase 14 — Character Voice Consistency & Prosody (started 2026-09-26)
- [ ] Versioned per-character voice profile schema and project APIs
- [ ] Stable voice resolution by Character ID for every dialogue unit
- [ ] Per-dialogue emotion/prosody metadata on the master dialogue manifest
- [ ] Provider capability negotiation and safe fallback warnings
- [ ] TTS integration with assigned character voice and supported prosody controls
- [ ] UI for voice assignment and prosody review/editing
- [ ] Regression tests for persistence, consistency, and backward compatibility
- Scope and acceptance criteria: `docs/PHASE-14-CHARACTER-VOICE-PROSODY.md`
