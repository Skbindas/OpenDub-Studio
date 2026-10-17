# Phase 14 — Character Voice Consistency & Prosody

Status: **Implementation in progress — core profile/prosody path implemented; provider and end-to-end validation remain**

## Goal
Give each global Character a stable target voice across the movie while allowing dialogue-level emotion and prosody to vary. The master dialogue manifest remains the single source of truth.

## Work plan
- [x] Define and validate a versioned Character voice profile schema (provider, voice/model identifier, language, stable settings, optional reference asset metadata); never store API keys or credentials in project JSON.
- [x] Add project APIs to create, edit, assign, and validate voice profiles by Character ID.
- [ ] Resolve each TTS request from the dialogue unit's Character ID and assigned profile; reject ambiguous or missing voice assignments with actionable errors.
- [x] Persist per-dialogue emotion/prosody metadata (emotion, intensity, delivery, pace, pitch/energy hints, pauses) on the existing master dialogue unit.
- [x] Surface unsupported Piper prosody controls as warnings; full provider capability negotiation across engines remains open.
- [x] Pass Piper speaking rate to synthesis and retain default rate behavior for existing projects; other prosody controls are reported unsupported.
- [x] Add UI for character voice assignment, profile review, and dialogue-level prosody editing.
- [x] Add automated tests for profile persistence, prosody persistence/rate mapping, unsupported Piper controls, and synthesis review gating; stable cross-scene resolution and broader migration coverage still need dedicated tests.
- [x] Run CI for the current implementation commits; latest integration-test commit `1d536d4` passed both push and pull-request workflows. Re-run CI after subsequent changes.

## Acceptance criteria
1. All dialogue units for a Character resolve to the same assigned voice profile unless the user explicitly changes it.
2. Scene-level emotion/prosody changes do not mutate the Character's stable voice identity.
3. TTS never silently falls back to a different character voice; missing/invalid profiles produce clear reviewable errors.
4. Voice profile and prosody metadata remain attached to the existing master dialogue manifest; no parallel timeline is introduced.
5. CI tests validate the above behavior.

## Constraints
- No voice cloning or reference-voice upload is implied by this phase; those require a separately reviewed provider, consent, licensing, and security design.
- No secrets or raw credentials in project files, logs, or API responses.
- Human review and listening remain required for production audio quality.
