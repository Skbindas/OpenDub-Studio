# Active continuation: speaker review to real Hindi dub

User requested the remaining local review/dubbing work and later explicitly authorised source-only Kaggle implementation publication to GitHub. Media, weights and credentials must not be pushed. Modifying accepted voice-bank quality flags is not authorised.

16 October listening correction: the owner rejected the supporting girl's Padma delivery as masculine/inconsistent, then rejected the Vidhya replacement audition for unclear speech. The earlier technical render remains preserved, not sound-approved. See VOICE_CONSISTENCY_REVIEW.md and the private runtime voice-consistency receipt before resuming; do not publish the rejected candidates.

16 October delivery checkpoint: the separate 84-second Kaggle Hindi dub is technically complete, with 23 clips, strict timing/loudness, preserved-background mix, final render and independent full-decode/source-video/hash QA passed. The in-app final player plays the actual output. See the top of KAGGLE_CONTINUATION.md and the private runtime/cleanup-verification/current-kaggle-handoff.json for current artifacts. Human sound/identity acceptance and actual provider GPU-withdrawal/replacement are not certified; the older pending-processing notes below are historical.

## Usage stop rule

Stop agent work at **95% used / 5% remaining** in the current five-hour window. The earlier 75%-used snapshot is historical; refresh live usage at bounded milestones. Before stopping, request checkpoint-preserving cancellation for any test job still running, record exact phase/artifacts, and leave the local server and original assets intact. This is an active-turn rule, not a background automation.

Previous window stopped at **95% used / 5% remaining**. User resumed on 14 October. Real-video continuation is now **COMPLETE**, with 39% of the five-hour window remaining at the final usage check (61% used). The 95%-used stopping rule still applies to future requested work.

## Preserved workspace and current checkpoint

- Repository: OpenDub-Studio, branch `phase-12-semantic-adaptation-provider`; many pre-existing dirty edits. Do not reset or mass-stage.
- Follow `.agents/rules/opendub-evidence.md` and `docs/ANTIGRAVITY_HANDOFF_AND_VERIFICATION_PLAN.md`.
- Main runtime rendered project and queued analysis must remain untouched. Test runtime: `runtime/speaker-workflow-validation`, localhost **7861**.
- Test project: `b277fa57-5507-41b3-84e6-52e078722790`, original duration 84.497s, Chinese ASR, 37 segments, 3 provisional clusters. Current status `awaiting_review`.
- Uncertain rows: 16 (34.60–34.92), 19 (36.98–37.54), 25 (52.12–52.52). Do not assign by pitch alone or erase warnings to force export.
- SPK_0003 has short activity around 23.926, 28.448–30.035 and 79.968–80.272 but no attributed words; investigate missing speech versus song/non-dialogue.
- 166 Python and 7 frontend tests passed in prior batch; no final dub from this source yet. Details: `docs/SPEAKER_WORKFLOW_VALIDATION.md`.
- Original reference/clone ledger: `runtime/speaker-workflow-validation/protected-source-hashes.json` (65 protected files). `<LOCAL_CLEANUP_ARCHIVE>/scratch/verify_speaker_workflow.py` validates hashes and current evidence.
- Server was left running in exec terminal session 20911, process 12136; verify before reusing. Do not start default runtime on 7860, which could claim the unrelated queued job.

## Next bounded milestones after explicit resume

1. Inspect actual source/context and recover uncertain word ownership or missing words with real local ASR/embedding evidence. Preserve revisions and source clock. Review counts are not actor-count accuracy.
2. Fact-check model licensing/runtime, then add conservative age/voice-style suggestions and bounded two-speaker overlap recovery with confidence/provenance. Exact age or gender identity must not be presented as factual. Do not install non-commercial weights as an unrestricted application default.
3. Complete source/casting review in the isolated test with explicit automated/test provenance; retain human bank acceptance flags. Generate actual Hindi voice clips and finish fitting/mix/render as approved capabilities permit.
4. Verify drag/drop with the available browser capability; if OS drag remains unsupported, test the actual File/DataTransfer handler through a supported developer interface and clearly distinguish it from human OS dragging.
5. Verify output decode/timing/BGM gains, retain UI proof and update this handoff after each milestone. Check usage before starting each expensive step.

## Current tools and constraints

Codex in-app browser via `mcp__cua_repl` is available. Native app APIs are disabled. Raw CDP file drag is rejected by the browser API; picker upload was actually tested. Do not silently launch external Chrome.

RTX 3050 Laptop 4GB; CUDA separation/ASR already work, native diarization currently chooses CPU. Main `.venv`, `runtime/separation-env`, and `runtime/clone-env` must remain compatible. Reuse existing caches rather than rerunning full analysis. Secrets remain in local environment and must not be printed.

## Resume launch if necessary

In PowerShell from repository root: set `OPENDUB_DATA_DIR=runtime/speaker-workflow-validation`, `OPENDUB_PORT=7861`, `OPENDUB_OPEN_BROWSER=0`, then run `.venv\Scripts\python.exe scripts\launch.py` in an open terminal. Read test status and active jobs before launching/cancelling work.

## Latest stop checkpoint — 14 October 2026

The preceding initial-checkpoint description is historical. Current source review is complete **as an assisted test review**, not an automatically validated general identity benchmark:

- Source frames and local learned-embedding/ASR probes showed two similar dialogue voices had been merged, while an English song vocalist was an additional cluster. Private evidence: `analysis/recovery-probe/{probe.json,anchor-comparisons.json}` and `verification/{source-storyboard.jpg,turn-context.jpg}`.
- `<LOCAL_CLEANUP_ARCHIVE>/scratch/apply_assisted_source_review.py` applied anonymous source/utterance annotations, preserved original transcript/diarization/registry under `analysis/assisted-review-backup/`, split the merged identity and retained source-bound overrides. Do **not rerun** that script; `analysis/assisted-review-receipt.json` marks it already applied.
- There are now **3 active dialogue identities**, plus one reviewed song cluster, and **23 joined complete utterances**. Assigned labels describe clothing/hair, not inferred gender identity or exact age. Review provenance is `assistant_review`.
- Three provisional Hindi choices are locked: Anu for the braided-hair speaker, Padma for the pink-outfit speaker, and Sathyam for the blue-shirt speaker. Padma is a technical reference. None was promoted to a verified default; the seven human bank quality gates were not changed. All 65 protected original hashes were rechecked unchanged at stopping.
- All **23 Hindi translations are saved** in `analysis/translated_transcript.json`; analysis/separation were reused.
- Auto-dub job **608a5170-9b31-44eb-924e-4ab9285bca47** reached real reference-conditioned synthesis. At the stop request, units **1–8 were completed**, unit **9 was running**, unit **0 failed Hindi content verification**, and units 10–22 were pending. Re-read the manifest for the final count after cancellation.
- Cancellation was requested via the local API at the 5% threshold. Initial response: `running`, message `Cancellation requested; waiting for a safe checkpoint.` A current utterance may finish before the durable job becomes cancelled. Do not kill the warm clone worker just to stop faster, and do not erase completed clips.
- Cancellation subsequently **verified**: job status `cancelled`, message `Job cancelled at a safe checkpoint.` The isolated localhost server remains open; no new model inference was started after the stop threshold.
- Final manifest counts after cancellation: **8 completed clips, 2 error-state units, 13 pending**. Unit 0 is the Hindi-content verification failure; unit 9 was interrupted at cancellation and needs retry, rather than being treated as a second proven content failure. All 23 translated utterances remain saved. Stop screenshot: `runtime/speaker-workflow-validation/verification/usage-stop.jpg`.
- Unit 0 error: `Generated Hindi words need review before replacing project audio: . Previous successful audio retained.` Investigate its private pending WAV/content reports and expected Hindi words. Do not weaken content or timing gates. Final mix/render has **not** been completed.

### New optional-tool code and verification

- New source: `backend/speaker_tools.py`, `scripts/speaker_tools_worker.py`, `tests/test_speaker_tools.py`.
- API/queue wiring added in `backend/app.py` and `backend/worker.py`: tasks `voice_traits` and `overlap_recovery`. The white review UI has research-style inference and bounded two-speaker recovery controls plus a local job poller.
- The running server was **not restarted** during active dubbing, so its in-memory app/worker may still lack these new routes/job kinds. After the current job is safely cancelled, restart only the isolated 7861 server to load them. Preserve the unrelated main-runtime queued job.
- SpeechBrain **1.1.1**, HyperPyYAML **1.2.3**, and ruamel.yaml **0.19.1** installed with `--no-deps --target runtime/speaker-tools/packages`; isolated SpeechBrain import succeeded. Main/clone environments were not modified.
- Optional worker inference is serialized with the existing cross-process clone-worker lock. Recovery accepts exactly two speakers and crops at most eight seconds; source channel order is not speaker identity. Recovered channels/transcripts remain review candidates.
- SepFormer source: `speechbrain/sepformer-whamr16k`, Apache-2.0. **Weights/inference and a controlled real-audio overlap fixture remain unverified.** The actual test source had no model-detected overlap; do not invent an overlap event to claim verification.
- audEERING 6-layer ONNX voice-trait model **finished downloading and checksum verification** at stopping: `runtime/speaker-tools/models/voice-traits-research/{model.onnx,model.yaml,provenance.json}`. Archive SHA-256: `ee6b1a69aef08f2f6fdd8e91aa88cc055aab97288b3bbd5dfa4a4997c94fe17f`. Official source: `https://doi.org/10.5281/zenodo.7761387`. License is **CC-BY-NC-SA-4.0**, so the endpoint requires explicit non-commercial research mode; this is not an unrestricted commercial default.
- **Trait inference remains unverified.** Inspect `model.yaml` and actual ONNX input/output/normalization before running the worker. Suggestions must remain approximate, confidence-labelled and editable; gender identity stays unknown and exact age is never certified.
- Last relevant suite: **54 passed** (speaker tools/review, studio integrity, worker queue). Final focused suite: **10 passed** (speaker tools and speaker review). JS syntax and Python compilation passed. The earlier 166-test baseline belongs to the preceding batch; broad regressions should run again after new-tool live validation.
- Manual OS drag/drop remains unsupported by the in-app automation API. Actual picker upload was verified earlier. A developer-level handler test and/or human OS drag still needs verification; do not claim that a mocked drop is a real OS drop.

### Resume priority

1. Read final cancellation state and current unit counts; preserve completed source, translations, generated clips and protected reference hashes.
2. Diagnose unit 0 content mismatch, then resume only failed/missing synthesis and timing. Do not regenerate accepted voice-bank auditions or restart source analysis.
3. Restart isolated server when idle; verify the research trait ONNX pipeline and new API/UI route behavior. Run the optional overlap model on a clearly labelled controlled real-audio fixture, then evaluate identity attribution/word preservation before enabling automatic application.
4. Finish timing/background mix/render and real decode/playback QA. Add missing drag/drop verification and report accuracy limits honestly.

No commit/push/publication was performed. Private source media, model weights and test evidence remain under ignored runtime storage. This handoff is a workspace checkpoint; the private knowledge base and global memories were not edited.

## Active resumed checkpoint — 14 October, 09:00 UTC

- Restarted isolated 7861 server only: process 20152, exec terminal 59665. Original runtime remains untouched.
- First Hindi line was too verbose for its 0.96-second source window; adapted to “एक बात पूछूँ?” through the translation API. It now passed real content verification.
- Browser Resume Auto-Dub created job `873c1827-645a-483b-a6bd-f39349755705`: 11 new clips succeeded, all 8 previous clips reused, 4 failed content verification (indices 9–12). Total 19 complete; no final mix/render yet. Do not restart source analysis.
- Failed 9/10 returned empty ASR at 0.32/0.64-second generation targets; 11/12 omitted a sentence clause. Private duration probe is testing 9 at 0.6/0.8 and 10 at 0.8. Existing files remain intact. Follow actual probe results, not assumptions.
- Fixed optional traits raw logits → softmax and raw ONNX PCM input; invalid age/probability outputs stay unknown. Results are now bound to source/identity revisions. New tests verified invalid/stale outputs are rejected.
- Pinned SepFormer revision `21a5b500c6f52fddc387c5d9e5fb13ffd6f039c5`; WAV caches validate duration/rate/channels and publish atomically. Controlled mixture uses real source crops at 1.54 and 35.62 seconds; explicitly not movie-overlap evidence. Model downloading via `<LOCAL_CLEANUP_ARCHIVE>/scratch/prepare_overlap_validation.py`.
- Actual upload handlers verified with an original File object on both drop surfaces; 8 frontend tests pass. OS drag interaction remains unverified because browser automation does not support file dragging.
- In-memory server predates latest source-context/logit/cache changes; restart when idle before optional-tool API/UI verification.

## Final checkpoint — supersedes the historical partial states above

See `docs/SPEAKER_WORKFLOW_FINAL_VALIDATION.md` for current evidence and capability limits.

- Real project `b277fa57-5507-41b3-84e6-52e078722790`: **23/23 completed Hindi clips, 23/23 completed timing fits, final render QA PASSED**. Full decode and identical original video-packet hashes verified. Original 8 completed clips and all 65 protected reference/clone files remain unchanged.
- Final output: `runtime/speaker-workflow-validation/projects/b277fa57-5507-41b3-84e6-52e078722790/output/original_dubbed.mp4`; SHA-256 `43dc8589dff62b9df0f6fd5b496b05b0c92ccafae7e964a3a33d927a929e4fee`.
- User approved exactly **0.27 seconds** of dialogue-gap allowance for line 9. Original source ASR clock 23.83–24.15 is retained; reviewed Hindi ends at 24.42. Source/text/speaker-bound replay does not accumulate time. Do not rerun `<LOCAL_CLEANUP_ARCHIVE>/scratch/apply_approved_dub_gap.py` or the earlier assisted source-review script.
- Original soundtrack now survives outside reviewed dialogue; neural instrumental is used during dialogue with bounded transitions. The 28.5–30.0-second song window matches original PCM exactly. Previous successful render/background/mix retained in `output/revisions/pre-selective-background/`.
- Trait job `7bef22d3-cc89-4e98-a14d-9d28fa7c87e3` completed in real UI. Pinned SepFormer ran on controlled real-voice mixtures using both CPU and CUDA, including CUDA ASR. One recovery channel was weak; candidates remain review-only and ownership unknown. Actual source has zero model-detected overlaps.
- Optional dependencies now live in `runtime/speaker-tools/packages-v1`, pinned by `requirements-speaker-tools.txt`; main/clone environments remain unchanged. New jobs are claimable, failed setup jobs do not retry blindly, result revisions are validated, and WAV caches publish atomically.
- Fixed the completed-preview URL being cleared on project reselection, and render revision changes now refresh the player.
- Final browser verification: updated script cache versions loaded, video `readyState=4`, actual playback advanced through about 25 seconds without error and was paused. Proof: `runtime/speaker-workflow-validation/verification/final-hindi-preview.jpg`; in-app tab retained.
- Validation: broad **372 passed / 2 skipped**; final relevant audio/tools/workflow group **96 passed**; final API/preview group **56 passed**; **9 frontend tests passed**. Earlier four expensive media integration tests also passed. No further broad test run is needed without new changes/failures.
- Current isolated server: localhost **7861**, process **17268**, exec terminal **69698**. Leave it open; do not launch default 7860 or touch the original runtime's queued analysis.
- Exact age/gender identity, independently annotated whole-film accuracy, visual speaker fusion, automatic approval of recovered words and human OS drag are not certified. Picker upload and actual File drop-handler forwarding are verified. Listening for acting/voice fidelity and separation artifacts remains a delivery review.

No commit/push/publication or knowledge-base/global-memory edits were performed at that validation checkpoint. Media/model weights remain local under ignored runtime storage.

## Cleanup / authorized publication checkpoint — 14 October 2026

- The user subsequently authorized cleanup and a GitHub-plugin push before Kaggle implementation. See `CLEANUP_AND_KAGGLE_HANDOFF.md` for the cleanup boundary and next adapter steps.
- Unused Chatterbox environment and obsolete speaker-tools package target moved to a recoverable sibling cleanup archive. Old scratch/temp folders and four one-time patch/rebuild scripts were also archived. Permanent deletion was blocked by automatic approval review; the archive does not free disk space.
- Earlier `scratch/...` commands now refer to archived history. Do not execute their mutations again. Original private handoff/document copies are retained under `runtime/cleanup-verification/private-document-originals`.
- Post-cleanup **376 Python tests passed / 2 skipped**, **9 frontend tests passed**, compilation, JS syntax, dependency integrity and staged whitespace checks passed. Source/output hashes, 65 protected references, 8 initial completed clips and the original queue are unchanged. Localhost 7861 still exposes the completed render.
- Kaggle home is open in the in-app browser, already signed in. API credentials, GPU eligibility/quota and remote jobs remain unverified. No Kaggle media upload or worker implementation has occurred.
- Only source/tests/portable docs are staged; no new media/model binaries or credentials. GitHub-plugin publication follows this checkpoint. Exact commit and CI result are recorded privately in `runtime/cleanup-verification/publication-receipt.json`; inspect that receipt and Git before resuming, rather than repeating the completed cleanup.
- Continue to stop at 95% used in the five-hour account window. Main terminal/localhost test project stay open. Do not start the unrelated queued original-runtime analysis or regenerate completed clips.

## Latest Kaggle continuation

Read `KAGGLE_CONTINUATION.md` first; it supersedes older Kaggle implementation notes above. The experimental main adapters, model pinning/offline transfer, reviewed four-line speech batches and bounded terminal-session recovery are now implemented. Local checks: **400 Python passed, 2 skipped, 1 deselected; expanded cloud suite 26 passed; frontend 9 passed**. The SDK is isolated in runtime/kaggle-env. The new backend runs on localhost 7861, with the active log terminal left open. A separate `Kaggle · real 84s validation` project contains the original video copied through the live API; its baseline remains intact. The owner was asked to enter their API token themselves in the visible localhost secure panel. **Actual Kaggle authentication/allocation, real GPU tasks, interruption and final remote dub remain UNVERIFIED.** No Kaggle dataset/notebook/media upload occurred. Source remains uncommitted/unpushed; baseline CI is not evidence for these changes. Private receipt: `runtime/cleanup-verification/kaggle-local-verification.json`. Do not start default 7860 or regenerate accepted takes.
