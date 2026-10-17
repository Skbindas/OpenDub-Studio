# OpenDub Studio: AntiGravity handoff and remaining implementation plan

Prepared 3 October 2026. This is a continuation plan, not a claim that the remaining work has been implemented. Read current code/files before acting; counts below are the last measured checkpoint.

## Goal and current evidence

Finish a reusable, reviewed Hindi cloned-voice bank, prove correct voice reuse and preserved-background dubbing on a small real video, then validate bounded-resource long-video processing. Preserve accepted work and publish only evidence-backed results.

- Repository: <PROJECT_ROOT>.
- Branch: phase-12-semantic-adaptation-provider; last verified pushed commit: 1013e58d204b710d46bc56959d538a57082bf53e.
- CI: https://github.com/Skbindas/OpenDub-Studio/actions/runs/37116254577 — success; 306 Python tests passed, 2 skipped, 1 feature-length test deselected; 7 frontend tests passed. This does not prove a complete cloned feature-length movie.
- Private delivery report: runtime/voice-bank-audit/delivery-report.json. 42 catalog entries; 23 original-reference auditions; 32 repaired-speaker auditions; 55 total takes. Every catalog ID has at least one hash-verified candidate without substantial speech omission detected by local ASR. Minor phonetic differences remain listening checks.
- Original audit: 35 provisional single-speaker, 2 multiple-speaker, 1 no reliable speech, 4 requiring review; 14 references exceeded the engine's duration range. Repaired versions preserve originals.
- Four original takes with missing speech: char_11_mother_sithara, char_21_home_minister_sharath, char_37_vidhya_college_friend, char_41_garage_elder_adviser. One bounded retry did not solve them. Real separation of expanded movie context produced better exclusive-speaker references and complete-sentence auditions; suspect originals remain available for comparison.
- Accepted takes: char_01_sathyam_mohanlal, char_03_anand_action_ntr, char_09_anu_nithya_menen. Exact hashes are in their local record audition_acceptance fields. Preserve these bytes and histories.
- Existing test project: 36f54de4-c32e-4278-b74e-52d4158e0ee0, named test, 84.497 seconds/25 lines, completed Piper stock-voice render. It proves that tested pipeline path, not genuine-clone whole-movie rendering. Do not delete it or overwrite its successful render during new tests.
- Local app: http://127.0.0.1:7860/. Last observed running, main visible terminal retained. PID is not durable; verify current process before any restart.
- Hardware last measured: RTX 3050 laptop 4 GiB, i5-12450H, roughly 15.7 GiB RAM. Re-detect current free resources.

## Why verified defaults are still zero

backend/voice_bank_quality.py::reviewed_eligibility requires all seven explicit checks:
single_speaker, speech_present, background_clean, identity_confirmed, clone_identity_passed, naturalness_passed, dialogue_content_passed.

The three accepted auditions have the last three sound-quality checks saved. That acceptance does not automatically certify the other four source checks. Other candidates also need listening/identity review and, where applicable, selection of the right repaired reference. Genuine engine status, actual file hashes, exact reference transcript and 3–10 second duration must match as well. Therefore generated, user-accepted audition and verified default are different states.

promote_defaults requires complete eligible coverage of the target catalog before switching the bank. Do not bypass the gate, force checkboxes, delete suspect evidence or remove legacy voices to make the number increase. Current human review is the next acceptance dependency, not proof that generation failed.

## Preserve and reuse

Private movie source:
<PRIVATE_SOURCE_VIDEO>

Short test source: <PRIVATE_SOURCE_VIDEO>

HF credentials are local. Never print their contents or commit them. Main runtime is .venv; genuine generation uses runtime/clone-env with OmniVoice 0.2.1, CUDA synthesis and CPU audio tokenizer. Do not replace the main environment or start duplicate alternative-engine downloads. VoiceStudio compatibility is documented in docs/VOICESTUDIO_COMPATIBILITY_REVIEW.md; the whole Electron app was not integrated.

Retain runtime/voice-bank-audit/{records,repairs,clones,sources,prompts}, clone history, storage/default_voice_bank and runtime/projects. A Git clone alone cannot reconstruct these private assets.

## Phase 1 — Verify and complete voice evidence

1. **Establish the checkpoint.** Inspect Git status/diff, instructions, delivery report, 42 records, selected reference paths, physical hashes and model availability. Use read-only checks first. Create a local per-voice review ledger with ID, candidate/version, source timecode, transcript, reference/output hashes, review flags, unresolved issue and evidence path.
   - Verify: all expected files decode; counts reconcile; accepted hashes match; no hidden successful-output overwrite. Do not rerun generation solely to confirm files exist.
2. **Resolve speaker identity and reference cleanliness.** Compare movie context, original excerpt, isolated repair and audition. Multi-speaker entries must select the correct actor's exclusive turn. Group duplicate identities and style variants; do not equate diarization SPEAKER_00 across different contexts. Perceived type/age bands are estimates, exact ages unknown without external identity evidence.
   - Files: scripts/repair_voice_reference.py, backend/voice_bank_quality.py, existing per-version repair.json and review UI.
   - Verify: one actual speaker, real intelligible speech, no audible BGM/SFX contamination or clipped speech, suitable 3–10 second reference, justified character identity. Tool inability to judge sound/source identity is a manual-review blocker; report it.
3. **Correct uncertain reference words selectively.** ASR transcripts are provisional. Save exact spoken words after source comparison. A changed transcript invalidates matching clone eligibility; retain the prior accepted take and regenerate a separate candidate only if needed, without overwriting accepted evidence.
   - Files: backend/app.py review routes, backend/voice_cloning.py, scripts/clone_voice_worker.py, clone manifests/history.
   - Verify: transcript and reference hash used in generation match the selected reference; unchanged accepted outputs remain identical.
4. **Confirm generated Hindi content and similarity.** Review requested text against real playback. Use scripts/validate_clone_auditions.py --model small --include-repairs for supporting evidence. Investigate substantial omissions through source/reference evidence, not repeated random retries. Minor ASR spelling variations do not automatically mean bad speech.
   - Verify: every requested word audible, pronunciation acceptable, recognizable reference identity, natural delivery, no tone/silence/stock substitution. Mark only actually supported checks; human reviewer decisions must be attributed and saved.
5. **Select, save and audit review.** Use Reference to review after confirming the repaired speaker identity. Existing selection saves the actual file and resets stale review flags. Investigate any incorrect review persistence or default count without changing the acceptance standard.
   - Files: web/voice-library.js, backend/app.py, backend/voice_bank_quality.py, tests/test_voice_bank_quality.py, tests/test_studio_frontend.cjs.
   - Verify: saved values survive library reload/app restart; previews play the selected files; wrong hashes/transcripts block eligibility; selected repaired audition is reused without regeneration. Every remaining blocker is visible in the ledger.

Exit: a justified decision for every catalog entry; incomplete identities stay pending. If 42 IDs include repeated people/style variants, define and document the intended replacement set with the user before changing the all-or-nothing promotion contract.

## Phase 2 — Prove defaults and real dubbing reuse

6. **Activate only the reviewed replacement set.** Once every target is eligible, use the existing promotion gate. Preserve the previous bank as a recoverable rollback snapshot; legacy deletion is a separate irreversible action requiring explicit authorization at that time.
   - Verify: incomplete set is rejected; complete set activates atomically; active state survives restart; rollback restores the previous selection. Do not claim activation from a counter alone.
7. **Prove saved voice assignments.** Create a separate small test project/copy. Assign several reviewed identities and persist provider, voice ID, selected reference, exact transcript, language and supported delivery settings. Reopen and verify new-project reuse.
   - Files: backend/app.py assignment/synthesis routes, backend/voice_cloning.py, character registry and persisted profiles.
   - Verify: each real generated clip uses the saved identity/reference manifest; swapping assignments changes the requested provider/reference correctly; no silent Piper fallback called cloning. Missing model/files produce a truthful recoverable error.
8. **Verify timing and expression with real evidence.** Test short/long Hindi lines and source anger/sadness/neutral delivery using suitable same-speaker references. Do not claim that an emotion selector proves audible expression. Prefer duration-aware text/generation; apply measured bounded time fitting, retain naturalness and never truncate speech simply to fit.
   - Verify: complete words, natural delivery, correct timeline placement, no overlap or cut endings; unsupported prosody is reported. Longer audio needs speeding up, shorter audio needs slowing down within acceptable limits; excessive adjustment requires adaptation/regeneration rather than distorted speech.
9. **Run a genuine-clone end-to-end preview.** On a source confirmed usable by ffprobe/decode checks, execute extraction, dialogue/background separation, transcript, identity mapping, Hindi adaptation, genuine synthesis, fit, mix and render. Use the authorized embedded browser, collect runtime/logs/studio.log and actual outputs. Keep the completed stock-voice test intact.
   - Verify: source video retained; original dialogue removed sufficiently by listening; original music/effects timeline/gain preserved subject to measured separation artifacts; all Hindi lines present and synchronized; final file decodes and plays. Compare original/background/dubbed tracks audibly. Record failures instead of claiming perfection.
10. **Test recovery and realistic capacity.** Interrupt an owned worker at a controlled saved checkpoint in the disposable test, restart and resume. Then validate chunk planning and resource admission for longer durations before running a whole movie. Do not perform network disruption or close unrelated processes.
    - Verify: earlier valid clips retain their hashes; only incomplete work reruns; changed inputs invalidate dependent outputs; progress/remaining/ETA derives from measured work; main terminal remains open. CPU/GPU/RAM/storage limits prevent unsafe concurrency while permitting justified smaller chunks/offloading. One successful 84-second run does not certify arbitrary multi-hour input.

## Phase 3 — Delivery and independent verification

11. **Run checks appropriate to actual changes.** Focused regression first, then required suite once. Existing commands:
    - .venv/Scripts/python.exe -m pytest -q -W error::DeprecationWarning -k "not feature_length"
    - node --test tests/test_studio_frontend.cjs
    - node --check web/app.js; node --check web/diagnostics.js; node --check web/studio.js; node --check web/voice-library.js
    - .venv/Scripts/python.exe -m compileall -q backend scripts
    - git diff --check
    - Real browser playback/review/assignment/resume/render checks above; mocks do not replace them.
12. **Inspect and deliver.** Review staged paths/diff, exclude runtime/media/tokens, push intended code within authorization and monitor every applicable workflow for the exact commit. Investigate failed jobs and verify the fix. Update audit/plan with implemented versus pending status and evidence links.
    - Exit: required checks pass; real preview is available; manual judgments recorded; pending feature-length, expression or identity work explicitly listed. No unsupported “all perfect” or “permanent guarantee” claims.

## Prioritize with limited usage

First complete review of existing candidates and fix only measured defects. Preserve the three accepted voices and reuse the 55 existing auditions. Avoid another engine, duplicate model downloads, cosmetic redesign, repeated full tests or feature-length generation before a successful small genuine-clone render. Stop for specific missing human evidence, preserve the ledger, and continue from that gate after the user's response.

## Risks and non-goals

Source separation can leave artifacts; local ASR can mishear Hindi; the catalog may misidentify actors; 4 GiB VRAM limits concurrency. Address these with better source evidence, bounded work, isolated environments, listening and rollback. This handoff does not implement the remaining steps, certify exact ages, promise studio-perfect similarity/emotion, or authorize deleting old voices before complete replacement verification.
