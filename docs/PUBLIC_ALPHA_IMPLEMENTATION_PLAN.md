# OpenDub Studio public alpha implementation plan

Prepared 16 October 2026. Approved by the owner; implementation checkpoint is in PUBLIC_ALPHA_STATUS.md. Repository visibility is unchanged and no public media has been published.

## Goal

Make OpenDub Studio understandable to a first-time user: upload a video, choose the target language, review proposed character voices where needed, generate a short preview, and export a reviewed dub. Keep expert controls accessible without making them prerequisites for basic use.

## Current evidence

- Application code has an MIT license. GitHub repository is currently private.
- Inspected source commit: `6b6f35b30067137487236b214cf25137abce6e29`.
- The real 84-second test has a completed corrected render and a saved independent technical QA pass: 23 timing-ready dialogue clips, nine supporting-character clips using one reference, 14 unaffected clips unchanged, full media decode, and unchanged encoded source video packets. Whole-render human listening approval remains pending. This does not certify feature-length movies, every language, every GPU, or overlap recovery.
- Existing frontend is vanilla HTML/CSS/JavaScript with a white theme, OD monogram and SVG favicon. Preserve the stack.
- The currently open UI shows diagnostics unavailable / failed fetch. Restore and verify backend connectivity before collecting release screenshots; do not interpret an empty offline workspace as project deletion.
- README still describes early runtime foundations and does not explain the current first-run/Kaggle flow adequately.
- `THIRD_PARTY_LICENSES/` currently contains a generic README rather than a completed component inventory.
- Initial audit found50 tracked WAV files under the default candidate voice bank; implementation untracked them without changing local audio. Their publication rights and references need individual review. Ignore rules do not untrack existing files or remove historical versions.
- The existing 84-second source and its dub are private test material until public demonstration rights are established. User approval of audio quality is distinct from permission from the media/voice rights holders.

## Upstream license findings

- OmniVoice model card distinguishes Apache-2.0 code from CC-BY-NC pretrained weights: https://huggingface.co/k2-fsa/OmniVoice . Verify the exact pinned revision and license text before packaging; do not advertise the current model path as unrestricted commercial use.
- Faster-Whisper small converted checkpoint declares MIT: https://huggingface.co/Systran/faster-whisper-small . Retain applicable notices and audit other components separately.
- Community-1 declares CC-BY-4.0 and requires user acceptance/access setup: https://huggingface.co/pyannote/speaker-diarization-community-1 . Automatic setup must not silently accept conditions for users.
- Separation checkpoints, translation providers, voice packs, binaries, and any optional demographic tooling still require their own exact-version review. An open-source application license does not relicense third-party assets.

## Owner decisions

The owner selected their own / permission-cleared recordings for the public demo and default pack. Movie-derived voices remain private test assets. The actual consented recordings and their rights records still need to be supplied; this decision is not proof of permission for the existing movie.

## Release decision

Target a public alpha after the release gates below pass. Keep MIT for our application code. State model-specific restrictions openly. A commercial-ready distribution additionally needs a suitable licensed model path and verified distributable assets; changing UI labels cannot solve this.

## Steps

1. **License and release inventory** — complete `THIRD_PARTY_LICENSES/`, add a component/model matrix with repository, revision, license, attribution, download origin, usage restrictions, and bundling decision. Audit all tracked voice media and Git history for private data, credentials and unclear distribution rights. Preserve working local assets. Prepare an asset-clean release branch or separate clean repository if history cannot be safely published; do not rewrite shared history or delete local files as a routine cleanup.
   - Verify: every shipped asset has evidence of permission and required notices; no model weights, private project footage, credentials, or unapproved voice references appear in the proposed public Git history. Produce a reviewable inventory before any visibility change.

2. **First-run setup** — implement one setup screen for dependency checks, available RAM/storage/compute, supported language pairs, and required downloads. Offer Local and Kaggle explicitly; cloud selection explains private media upload and account requirements. Show download sizes and gated model access requirements. Store credentials outside project manifests and redact errors/logs. Keep model selection on a tested Recommended profile; expose overrides under Advanced. Retain existing manual options.
   - Files: launcher/setup scripts, diagnostics/provider settings backend, `web/index.html`, `web/compute.js`, existing frontend modules.
   - Verify: clean Windows profile can reach a ready state using documented steps; missing access, disk space or GPU capacity produces an actionable state. No silent cloud upload, provider switch or unaccepted license. Hardware detection reflects actual supported inference backends; do not promise CUDA support on every GPU.

3. **Simple workspace** — organize the main flow as Video -> Language -> Voices -> Preview -> Export. The initial view contains upload, automatic source-language detection with correction, target-language selection, compute location, and one primary action. Keep project navigation compact. Hide detailed model selectors, independent crop diagnostics, raw transcripts, waveform tools and per-segment controls behind contextual Advanced panels rather than showing all sections at once.
   - Files: `web/index.html`, `web/styles.css`, `web/app.js`, `web/studio.js`, `web/speaker-workflow.js`.
   - Verify: first-time user can complete the short-video path without knowing a model name; existing expert workflows remain reachable; keyboard focus, Hindi typography, mobile width and browser refresh work.

4. **Automatic recommendations with review** — propose speaker IDs, persistent character-to-voice assignments and usable source references. Present compact character cards with original and dubbed sample buttons, Change voice, and a correction control for mistaken identities. Clearly mark uncertain matches, overlap, missing words or excessive timing compression. A verified selection persists across scenes and restart; rerun only affected units when changed. Do not infer perfect age/gender/identity from diarization or bypass uncertain cases.
   - Verify: two female characters stay distinct, accepted choices persist, and uncertain/overlapping turns lead to review rather than a false completed dub. Test with consented material.

5. **Truthful processing and recovery** — show current stage, measured completed/total units, elapsed time and optional evidence-based ETA. Separate Kaggle waiting, remote execution, download, fit, mix and render. Remove misleading near-complete percentages when substantial work remains. Provide safe pause/resume/retry from retained checkpoints; explain provider limits without a fabricated finish time.
   - Files: auto-dub/job status backend and frontend status renderers.
   - Verify: queue waiting never looks like a finished render; refresh/restart retains state, changes invalidate only affected outputs, and no duplicate notebook is submitted. Actual GPU-withdrawal recovery remains unverified until an induced end-to-end test passes.

6. **Preview and export** — put synchronized original/dubbed comparison and short character auditions next to the review tasks. Make only failed/changed line retry the default correction action. Show export readiness only after technical QA; distinguish it from the user's listening approval. Keep the source video intact and expose original/dubbed audio and subtitles only when generated.
   - Verify: actual generated media plays in the embedded browser, dialogue is intelligible, background artifacts are reviewed, and export preserves the intended video stream/encoding behavior. No claim of perfect separation or guaranteed lip sync.

7. **Branding** — retain the working name OpenDub Studio, with proposed attribution 'by Elnavix' subject to owner preference and a separate name-availability check. Create an original scalable SVG mark combining dialogue/waveform imagery with a simple wordmark; deliver favicon, app icon, README header and social card. Preserve white surfaces, dark text, blue primary actions, restrained teal/amber states, and readable Hindi/English. Existing OD branding is a starting point, not an absent asset.
   - Verify: icon is legible at small sizes, no third-party logo copying, bilingual text is readable, and screenshots contain no personal project paths or credentials.

8. **GitHub presentation and documentation** — rewrite README around actual capabilities, release status, installation, quick start, Local/Kaggle setup, supported/tested configurations and language pairs, limitations, privacy/data flow, licenses and troubleshooting. Add architecture flow, contributing/security guidance, issue templates, changelog, and four real UI screenshots: upload, character review, processing, final comparison. Show measured sample timing with its configuration, not a universal performance claim.
   - Verify: a new user follows README from a clean checkout without undocumented local caches or private sample assets. Screenshots show the running product; illustration is not evidence of functionality.

9. **Public before/after demo** — prepare a short original-language versus Hindi example only from owner-recorded, permission-cleared or suitably licensed material, with voice permission and required attribution. The current test can remain a private demo while its rights are unresolved. Publish only a specifically reviewed demonstration clip, not the user's full uploads or project directories. Prefer a GitHub release/demo link and small README thumbnail over committing large videos; normal project exports remain excluded.
   - Verify: rights record, captions, language labels and audio listening review are complete. Changing the language does not itself establish redistribution rights.

10. **Public alpha gate** — run focused regressions and the full appropriate existing suite once, frontend checks, fresh-clone setup, embedded-browser upload/character correction/preview/export, checkpoint recovery, export decode QA, and release secret/asset inventory. Record PASS/FAIL/UNVERIFIED. Prepare a tagged alpha and reviewable release checklist. Change repository visibility only after explicit owner authorization of the prepared release.
    - Verify: CI is green for the exact release commit; no critical blocker remains, known limits are documented, and public assets have permission. A short clip pass is not a feature-length acceptance test.

## Non-goals

No public visibility change in this planning task. No deletion of private source media or accepted voice assets. No claim of fully automatic perfect casting, age/gender classification, overlap repair, unlimited free Kaggle GPU, commercially unrestricted model weights, or full-movie readiness from one short test.

## Risks and fallback

- Unclear asset rights: keep those assets private and ship a consented demonstration pack or a user-supplied-reference workflow.
- Restrictive model terms: label the research/non-commercial path clearly, and evaluate a separately licensed replacement before commercial distribution.
- Kaggle unavailable: show waiting and an explicit local choice if supported; retain checkpoints rather than silently starting over.
- UI regression: preserve existing API contracts and project schemas; check the accepted sample before and after UI-only changes.

## Verification and order

Order: release/asset inventory -> setup and supported default profile -> simple workflow and real progress -> character/preview correction UX -> branding -> documentation and permission-cleared demo -> fresh-install and end-to-end QA -> reviewed public alpha. Source implementation begins after the plan is approved. Public release remains a separate final action.
