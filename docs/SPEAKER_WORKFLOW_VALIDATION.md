# Speaker foundation: implementation and validation

13 October 2026 local session (artifact timestamps extend into 14 October UTC).

## Implemented upload-to-review sequence

1. Upload original file through the local UI. Keep original bytes; validate container, duration and complete decode.
2. Extract the original audio clock and separate dialogue vocals using resumable neural separation chunks.
3. Transcribe the vocal stem with source-time word timestamps.
4. Run Community-1 in bounded overlapping windows. Save regular activity, exclusive alignment, actual model revision, learned embeddings, raw overlap events and source coverage.
5. Reconcile provisional project-wide speaking IDs, aggregate attribution per unique speaker and keep uncertain words unresolved.
6. Review source samples, correct source words/ownership, merge/remap clusters or split a turn into an explicitly manual identity. Splits have source-bound replay records; previous transcript/diarization revisions remain archived. Explicitly reviewed music/non-speech clusters can be excluded and restored while retaining raw evidence; clusters owning transcript words cannot be excluded.
7. Choose existing Hindi voice auditions. Accepted auditions appear first; lower/higher register and F0 are coarse suggestions. Casting and age-style labels are user notes, not factual demographic predictions or a guarantee that a provider generates a new age/style.
8. Explicitly lock configuration/reference evidence, including actual reference audio and transcript hashes. Identity aliases, casting notes, voice settings or live reference changes invalidate the old lock. Do not rewrite voice-bank source-quality acceptance flags.
9. Continue through Hindi translation, genuine configured speech generation, timing fit, original-background mixing and render/decode QA. New analysis blocks translation/synthesis while required source identities, missing speech, overlap review or voice choices remain unresolved.

Automatic analysis after upload is enabled by default and can be switched off. The white UI shows ordered stage status, real source snippets, accepted Hindi auditions, actionable review items and a continue button. Resume retains valid completed analysis. Unsupported overlap recovery remains visible instead of forcing one speaker's words onto everyone.

## Tests and real-media evidence

- **166 Python tests passed** across foundation, identity review, source alignment, analysis, casting, queue/integrity, resource progress, dependency state, voice profiles, diarization runtime, synthesis request validation and launcher suites.
- **7 frontend regression tests passed**; both editor scripts also passed Node syntax checking.
- A real **84.497-second local video** was uploaded using the Codex in-app browser at **localhost:7861**. Full source decode passed; uploaded original SHA-256 matched the source.
- Real neural separation completed in two cached chunks on the RTX 3050. Vocal and source analysis stems both retained exactly **84.4974375 seconds**. ASR ran on CUDA and reported Chinese, yielding **37 dialogue segments**.
- Community-1 produced **3 provisional IDs**, each with an actual **256-dimensional learned embedding**. Ordinary/exclusive views each contained 31 turns on this particular clip; the model detected no overlapping regions. This does not certify absence of all real overlap.
- Same-source reconciliation of the real saved embeddings preserved all three IDs. Full source coverage was retained. This checks persistence, not an independently labelled identity-accuracy score.
- The normal pipeline paused at **awaiting_review**: three uncertain dialogue turns, one detected identity without attributed transcript, and three unlocked voice choices. No new translated speech or final dub was claimed.
- Browser preview decoded and played an **8-second original source sample** and an existing **5.93-second accepted Hindi audition**, with no media error. Playback success does not certify audible source identity, demographic correctness or clone fidelity.
- An unchecked voice confirmation was rejected through the real UI. Pressing Continue again returned to the same review checkpoint in approximately one second, without restarting analysis or separation.
- The mobile breakpoint had no horizontal overflow (375-pixel content/viewport with scrollbar). A temporary browser viewport override was reset after verification.
- All **65 protected original reference/clone hashes** remained unchanged. The existing rendered project and its original queued analysis job remained untouched. Testing used a separate runtime/database and copied audition evidence.

Private receipts, screenshots, test source and audio remain under ignored `runtime/speaker-workflow-validation/`. No new media/model weights were staged or pushed. Existing tracked legacy voice samples were not changed or removed.

## Explicit limits and next acceptance gates

- Actual picker upload was tested. App drop handlers are implemented, but the browser automation API does not support dropping an OS file; manual drag/drop acceptance remains pending.
- The real test source remains at its expected review checkpoint. Human source/casting decisions were not manufactured to force a final render. Correct/recover the unresolved source turns and missing speech, choose/lock actual voices, then use Continue.
- Automatic speech/music classification, independently verified whole-film identity accuracy, calibrated embedding thresholds, evaluated per-speaker overlap recovery and visual active-speaker association remain research milestones. A bounded cache test is not a multi-hour movie benchmark.
- Manual splits and reassignment keep auditable backups; a general undo UI and multi-lane visual timeline are not part of this completed foundation batch.
- No new model framework was installed. The existing 4GB policy keeps diarization on CPU; separation/ASR used CUDA. No claim is made that every operation ran on the GPU.
- Local implementation has not been committed/published because this task did not authorize publishing the already dirty OpenDub checkout.

Research and primary-source comparison: `research/2026-10-13-speaker-identity-and-casting.md`. Approved execution batch: `SPEAKER_WORKFLOW_EXECUTION_PLAN.md`. Larger roadmap: `SPEAKER_IDENTITY_IMPLEMENTATION_PLAN.md`.
