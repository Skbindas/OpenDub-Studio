# Historical developer implementation checkpoints

For current source-release scope, see [known limits](RELEASE_READINESS.md). Dated checkpoints below describe earlier private development, not current visibility or blanket certification.

16 October 2026. This is an implementation checkpoint, not a public-release or voice-quality certification.

## Implemented

- Stable names for all 42 catalog entries; internal identifiers and accepted audio remain unchanged.
- Voice-library evidence and repairs follow the selected `OPENDUB_DATA_DIR` rather than a hardcoded old runtime.
- Known silent, mixed, missing-transcript, invalid-duration and explicitly rejected references are blocked from technical automatic admission. Legacy demographic auto-assignment requires reviewed default eligibility and does not guess unknown gender from a name.
- Casting suggestions prioritize matching measured vocal register ahead of unrelated accepted auditions. Register is not a gender/age/identity certificate.
- Named library search, audition/accepted/blocked filters, compact evidence panels, and prominent available repair auditions with an explicit review action.
- Local import of 25 pre-existing repair versions, providing 32 repaired-speaker auditions in the isolated test runtime. Imports preserve audio bytes and do not change selected references or review/acceptance flags.
- Models/manual steps and worker settings are collapsed under Advanced. Source/target language and the primary workflow stay visible.
- Waiting status no longer displays a stale 99% as whole-movie progress. Current-step counts and real download readiness drive the monitor.
- Original SVG logo/wordmark/favicon, quick-start and component-license documentation, and a read-only release inventory tool.
- The 50 movie-reference WAV files are removed from the current Git index and excluded by ignore rules. Every local file was hash-checked unchanged. Historical Git copies still exist and repository visibility remains private.

## Evidence

- Full appropriate local suite: 453 passed, 2 skipped, 1 feature-length test deselected. A subsequently added release-history regression test also passed separately. Final CI must be checked against the exact implementation commit.
- Frontend: 14 tests passed, covering measured progress, casting order, dialogue retention, upload behavior and review submission.
- Embedded browser: named library and 32 repair auditions loaded; repair review selected the correct candidate with zero approval boxes automatically checked; original and cloned repair endpoints returned actual WAV bytes.
- Desktop 1440px and mobile 390px width checks found no horizontal overflow. Real local screenshots saved under the ignored `runtime/public-alpha/screenshots` directory.
- Existing corrected movie remains subject to its separate technical QA and whole-render human listening review. No accepted dialogue was regenerated for this UI work.

## Next implementation increment

- Added private, permission-attested WAV reference intake, exact transcript and original preview. No generated-clone or public-distribution approval is fabricated.
- Added local first-run prerequisite checklist with separate model-access and real-preview states.
- Fixed clone-audition counts to follow the selected runtime. Casting uses original-reference playback when no valid generated clone exists.
- Added two actual ImageGen artworks, editable geometric SVG adaptations, seven workflow icons and a local brand review page. Exact image-model version is not exposed; see web/brand/PROVENANCE.json for prompts and provenance.
- Elnavix brand documentation was inspected read-only as a workflow reference; none of its pixels or product marks were imported.

Increment validation:465 Python tests passed,2 skipped,1 feature-length deselected;14 frontend tests passed. Intake HTTP tests use isolated signal fixtures and do not certify a real owner recording.

## Still open

Source/discovery follow-up: 4cffd08 passed exact-commit CI with 467 Python tests and 14 frontend tests. GitHub About description and 14 relevant topics are configured. A new isolated Windows core environment installed requirements and served five source/UI/API endpoints without copied developer packages or private voices; full optional-model installation/dubbing remains pending. README clone commands, local/Kaggle setup, community credits, code ownership and maintainer review guidance are now being added. None of these steps changes public visibility, publishes a demo or certifies branch-rule enforcement.

- Current technical inventory flags 18 references; a repair audition is not automatic approval. Whole-bank sound clarity, single-speaker identity, perceived type and naturalness still need listening review. No entry was promoted merely to raise the verified count.
- Owner chose their own / permission-cleared recordings for the public demo/default pack. Those actual recordings and permission records still need to be supplied and processed; movie-derived samples remain private.
- Complete model/license and historical secret-content audit, asset-clean public Git history, fresh-install verification without the private movie bank, and an explicitly authorized public alpha release.
- A fully automatic installer/download experience beyond the new guided readiness checklist and existing launcher still needs clean-machine implementation/testing. No untested GPU backend or model-access agreement is silently enabled.
- Full-movie, overlap-repair, provider GPU-withdrawal/replacement and additional language-pair acceptance remain unverified.

## Continuation

Keep the local launcher open. Preserve all private media, selected reference revisions, acceptance records and completed outputs. Continue with the owner-supplied recording pack and unresolved reference auditions; retry only changed units. Do not change repository visibility or force-rewrite its history as a routine cleanup step.
