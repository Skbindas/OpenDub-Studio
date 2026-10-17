# Long-form speed and test 2 recovery


## Current implementation and verified pilots — 2026-10-04

Episode confirmed by user: Flex X Cop S01E01. Hindi means everyday conversational speech, with Devanagari TTS input.

Implemented and checked:
- Parallel TTS now merges one line into a fresh translation snapshot under a thread/process metadata lock. Changed text or changed voice during inference rejects the stale take while retaining prior audio. CPU concurrency follows available memory; reference cloning stays single-GPU. Unexpected future exceptions propagate.
- Missing atomic source is an error even if an old destination exists. Interruption does not certify stale output as successful.
- Neural separation is strict in production mode; spectral subtraction remains an explicitly requested preview. Roformer `Other` labels map to instrumental, and model-name `vocals` substrings cannot swap stems. Both stems must exist. Source PCM/duration and recorded source hash validate cache reuse.
- Warm clone, CPU content-check and separation worker processes retain their model across a batch and release it at stage end. CPU content validation no longer competes for the GPU clone lock. Separator output directories move per chunk while weights stay resident.
- Stage-specific fit/separation admission replaces analysis-only admission. Separation now uses its own workload profile in both outer and inner checks. A resident warm model is not charged as a new model on every chunk.
- Long diarization PCM decodes into a disk-backed float tensor in bounded blocks instead of retaining raw, bytearray and multiple full-length float copies. Temporary mapping is cleaned on normal tensor release. Bounded-analysis admission retains model/feature/headroom and disk checks; low memory is not fictional capacity.
- Independent ASR/CTranslate2 and optional isolated Torch separation probes; the tested separation environment reuses compatible installed Python 3.13 GPU/main packages without replacing either environment. `python scripts/bootstrap.py --separation-runtime` recreates that arrangement and checks a real CUDA tensor. `OPENDUB_SEPARATION_PYTHON` supports a separate compatible interpreter. audio-separator 0.47 is the tested package range.
- Audio-only analysis skips scene decoding and emits one source-time scene. English/Korean text subtitles can be extracted without video frames and aligned to translation batches. Cast/story is context, never proof of a cluster's actor identity.
- Configured natural-Hindi provider validates exact IDs and nonempty Devanagari, retries malformed batches with smaller batches, and checkpoints successful results. It publishes only a complete transcript; failure retains the old complete target.
- Automatic reference selection aggregates multiple exclusive speaker intervals, verifies reference hashes and exact transcripts, keeps one assignment per speaker and disables synthetic theatrical/pitch modifications. It records automatic provenance separately from human approvals. Ambiguous voice register does not get a fabricated gender.
- Strict duration readiness is restored: 173 clamped timing warnings cannot automatically certify a finished output.

Live evidence:
- User-supplied replacement Gemini credential passed the live test; it remains only in local configuration, omitted from documentation/log output.
- All 735 natural-Hindi lines generated into `analysis/natural_hindi_transcript.json`, separately from the previous translation/audio. This draft is structurally complete, not a claim of listening or semantic perfection.
- Genuine reference-conditioned CUDA clone pilot: first short line 57.29 seconds including loading (12.02 seconds generation), second warm line 9.60 seconds (9.57 seconds generation), using 32 steps. Production uses its configured steps; these different sentences are not an apples-to-apples movie speed benchmark.
- Warm CPU content check: 11.14 seconds first line, 4.74 seconds second line; no substantial omission suspected in either. ASR is supporting evidence only.
- Roformer 12-second GPU pilot: both stems, 28.23 seconds including model/import overhead, about 7 seconds separation inference. Warm two-chunk pilot: 33.87 seconds total, 576000 frames at 48 kHz stereo, both stems assembled on the complete timeline.
- Targeted regression: 119 tests passed (automatic dialogue, concurrency, chunk execution/separation/mix, resource/progress, studio integrity, translation provider, diarization, bank gates, semantic adaptation and content checks).

AntiGravity audit outcome: preserve useful atomic retries, unique temporary names, Piper profile plumbing and MP4 subtitle conversion (`mov_text`). Corrected unsafe fixed TTS concurrency/stale JSON commits, swallowed futures, missing-source success, silent degraded separation and relaxed timing completion. The supplied recovery render is a Piper/spectral preview, not a verified cloned-voice/neural-stem movie; its existing files are retained. Earlier 732 clip hashes had already changed in the external rebuild; this work does not claim to have preserved those exact takes.

Outstanding full-episode work:
- SPEAKER_07 measured median 185.04 Hz from multiple exclusive source windows and is ambiguous under the conservative audio-register rule. Representative speech starts at 2060.519 seconds. A user clarification or validated richer classifier/clean stem evidence is needed before forcing a different voice.
- New 735-line draft has not replaced existing audio. Correct voice assignments, speech regeneration, duration-safe adaptation of overlong lines, full neural separation and the new final mix/render must still run and pass technical/content checks.
- No full 65-minute speed benchmark, 8-GB end-to-end benchmark, multi-CUDA-card scheduler or integrated-GPU model engine has been validated. Explicit multi-device routing and automatic OOM subdivision/resource-wait backoff remain planned. One Intel integrated display GPU plus one RTX is not two CUDA devices.
- Neural source separation estimates BGM/SFX and may retain dialogue bleed or remove effects. Exact 100% removal with perfect effects preservation requires an original dialogue-free/M&E stem; do not advertise an unattainable guarantee from mixed audio.
- User explicitly requested automatic processing without review queues. Automatic decisions must have real provenance; do not forge human acceptance. Unresolved correctness should be an actionable processing condition, not silent final export.


## Requested implementation update: Flex X Cop S01E01

User authorized planning followed by implementation, automatic operation without human review queues, natural colloquial Hindi stored in Devanagari, retained cloned voices, and bounded parallel work. This overrides the earlier preference to wait for approval of the performance plan. Existing outputs remain recoverable.

| Problem | Evidence / cause | Implementation and verification |
|---|---|---|
| Original Korean speech audible | Previous background is spectral center subtraction with -24 dB ducking, not genuine isolated accompaniment | Neural vocals/accompaniment separation, isolated compatible GPU runtime, overlapping bounded chunks, cached stems. Automatic pipeline must not silently substitute ducked original audio. Verify real sample, full timeline and stem provenance; no guarantee of mathematically perfect removal from a mixed source. |
| Unnatural/unintelligible Hindi | Literal Argos baseline, missing context, overly long Hindi and aggressive synthesis rate | Source-grounded conversational-Hindi translation with adjacent dialogue and series glossary; automatic bounded retry for malformed/empty output. Time-budget regeneration rather than removing words or stacking tempo/pitch effects. Verify text, meaning samples, audio duration and content checks. |
| Wrong voice at speaker turns | Hard-coded speaker-number/gender mapping in rebuild script; current profiles are stock Piper, not clones | Stable diarization speaker IDs, bounded exclusive speaker references, vocal features aggregated over multiple clean clips, deterministic matching to technically valid bank references. Preserve explicit assignments; match reference-conditioned voice directly rather than guessing character identity from cast listings. Record automatic selection separately from human acceptance. |
| Robotic/cracked speech | Synthetic pitch/vibrato/EQ and rate stretching on stock voices; timing overruns accepted as completed | Natural delivery default, reference-conditioned synthesis, modest tempo range, automatic shorter faithful translation/regeneration. Never claim unresolved timings are synchronized just because container QA passes. |
| Fixed RAM refusal / 8 GB machines | Full-length diarization PCM budget and fixed per-stage RAM thresholds; oversized worker count | Remove movie-duration RAM charging for bounded stages, stage/provider budgets, smaller chunks and one worker under pressure; disk-backed checkpointing, process lifecycle release. Real OOM or insufficient disk still needs retry/wait/error rather than silently destroying progress. Disk is storage, not interchangeable GPU RAM. |
| Slow / parallel workers unreliable | Six unconditionally submitted TTS workers; stale translation snapshots overwrite other workers' updates | Capacity-bounded scheduling, one coordinator for metadata, project-level process-safe mutation lock and fresh per-line merge; clone GPU serialization until device-specific routing is measured. Verify concurrent different-line commits and cancellation. |
| GPU misrouting | Windows Intel display GPU 0 is not CUDA GPU 0; ASR detection incorrectly depends on PyTorch CUDA | Probe engines independently; explicit CUDA device index, dedicated RTX for supported heavy engines and CPU for fit/mux. Report integrated GPU unsupported for CUDA instead of assigning it impossible model jobs. |
| Unnecessary frame work | Scene detection decodes video; cast cannot establish which person speaks each audio interval | Audio-only analysis option and optional scene/frame processing; cast/story glossary from metadata search, while audio diarization owns speaking turns. Verify analysis can run without scene decoding and keeps source timestamps. |

### StemKit suitability

Inspected `https://github.com/danielravina/stemkit` and its Python Roformer/Demucs and Electron pipeline. It offers useful local stem extraction and progress/model-device patterns. It is not a dubbing, translation, character-identification or clone engine. Its Roformer implementation reads the whole WAV into arrays, sends the mix to the device and allocates full-length result/counter tensors; therefore do not run it directly on a 1–3 hour movie. Use compatible neural separation models through the existing audio-separator adapter, with bounded contextual chunks and streaming assembly. Do not import the separate desktop application, YouTube downloading or telemetry into OpenDub. Model selection needs a real speech/BGM/SFX sample benchmark.

References: StemKit README and `python/roformer.py`, `python/separate.py`, `src/main/pipeline.ts`; audio-separator upstream model/API documentation. For series context: https://en.wikipedia.org/wiki/Flex_X_Cop and https://www.imdb.com/title/tt30413306/fullcredits/ . Cast is context, not a verified speaker-ID mapping.

### Execution order

1. Preserve existing project/changed-source evidence; audit AntiGravity changes and reproduce concurrency/fallback defects with tests.
2. Fix shared-file commit races, unsafe resource selection, and explicit engine/device routing.
3. Add strict neural separation and isolated model runtime; verify a small real episode excerpt before scheduling full length.
4. Add context-aware Hindi translation and automatic stable reference voice assignment; remove artificial defaults causing distortion.
5. Add audio-only mode, automatic fit regeneration and automatic repair attempts; leave true processing failures visible with retained checkpoints.
6. Run focused regressions, real separation/translation/clone pilot, then corrected mix/render only when those mechanisms are actually usable. Record any external model/API blockers and exactly what remains.

Prepared: 2026-10-03. Verified continuation: 2026-10-04. Status: rendered preview available; timing/background listening review remains. Performance architecture below is a proposed implementation plan.

## Verified continuation result, 2026-10-04

- Current saved state has 735 completed TTS units; 562 timing fits completed and 173 require review. A render completed between the earlier session and this continuation; it was not rerun here.
- `output/original_dubbed.mp4` exists, 415,867,872 bytes, matching the saved PASSED technical QA report. The mix lists all 735 dialogue units. QA records source duration 3906.816 seconds and render duration 3905.131 seconds, a 1.685-second difference accepted by its current tolerance; this does not prove exact-duration preservation.
- Background metadata identifies spectral center-vocal subtraction, confidence `requires_listening_review`, with -24 dB subtle ducking. This is a degraded preview; clean neural separation and unchanged BGM/SFX are not verified.
- Current source permits clamped `needs_review` timing in non-strict readiness checks. Consequently PASSED container/decode/coverage QA does not certify natural delivery or resolved timing.
- The intervening rebuild changed all 732 original clip hashes compared with the recovery snapshot. This continuation did not regenerate clips. Preserve the current render and inspect rebuild provenance before any future recovery claims.
- Cleared the stale RAM error from completed runtime status after verifying file size and QA; retained it under `previous_processing_error` and backed up the prior status. Added timing/background listening-review flags.
- Full pending timing list: `runtime/projects/17ccfbc8-07e3-4dff-a79b-aad6499da4c6/output/recovery_review.json`.
- Targeted regression run: 45 passed across translation providers, resource/progress planning and studio integrity. This is not a GPU throughput benchmark or proof of the full performance architecture.
- Next quality work: review/adapt the 173 overlong lines, confirm complete speech and timing, replace or listen-review the spectral background, and verify final duration. Next performance work follows the measured rollout sequence below.

## Goal

Resume only missing work in test 2, preserve 732 existing synthesized clips, complete timing, background separation, mixing and verified rendering where quality checks permit. Make future 1–3 hour jobs bounded in memory, speech-aware, parallel where useful, and resumable per unit. Do not promise a fixed movie turnaround without measurements on the selected machine/model.

## Verified context

- Project `17ccfbc8-07e3-4dff-a79b-aad6499da4c6`, name `test 2`, duration 3906.816 seconds; 735 Korean transcript units translated to Hindi.
- Supplied log: 732 synthesized, three failures at display lines 256, 501, 539 (indices 255, 500, 538). All three target translations were empty, with no translation error recorded. These are speech, not silent scenes.
- Resume failed before processing: speech admission required 3 GiB available; recorded available memory was 2,530,668,544 bytes. This is an admission refusal, not evidence of a CUDA out-of-memory exception.
- All 735 timing states were pending at inspection. 70% is a weighted stage progress indicator, not 70% of movie duration or a reliable time fraction.
- Hardware snapshot: approximately 15.7 GiB usable RAM; RTX 3050 Laptop, 4096 MiB dedicated VRAM, about 3962 MiB free. Running studio process held about 3 GB working set. Inspect capabilities independently; hardware presence does not prove usable CUDA libraries.
- `auto_dub.py` performs a global admission check before resuming. `resource_plan.py` uses a fixed 2 GiB reserve plus 1 GiB for all resumed speech work.
- `execute_batch_synthesis` and `execute_batch_fit` in `backend/app.py` loop sequentially. Piper launches a subprocess per line. Naively calling these endpoints concurrently would race shared JSON read/modify/write operations.
- Chunk infrastructure already exists: `chunk_execution.py`, `chunk_worker.py`, `chunked_asr.py`, `chunked_separation.py`, `chunked_mix.py`. ASR chunking is opt-in (`experimental_chunk_asr=false` in this run); VAD is already enabled in existing ASR.
- Default heavyweight model routing uses CUDA device 0; integrated and discrete GPU memory cannot be added together. Worker count in a plan is not the number of running worker processes.

## Immediate recovery, authorized in the request

1. **Snapshot and inventory** — copy manifest, translations, progress/status to `runtime/backups/test2-recovery-*`; hash every completed dub clip. Verify project has no running/queued job before editing.
   - Verify: 732 hashes captured, original source/translation retained.
2. **Repair only the three missing translations** — use the existing translation edit endpoint; retain source text and record AI-authored repairs for listening review. Run resumable batch synthesis.
   - Verify: 3 synthesized, 732 skipped, 0 failed; every previous clip hash unchanged.
3. **Fit and normalize** — use the existing bounded per-line batch job, preserving the auto-dub tempo limit (1.15 maximum). Save valid fit checkpoints. Separate failed processing from dialogue that exceeds its speaking window.
   - Verify: count completed, failed and review-needed lines; do not hide overruns, shorten the movie, or label unresolved speech as complete.
4. **Fix the causal validation bug** — regression-test blank/whitespace translation output, record per-line failure and preserve valid rows; stop/review at the translation boundary instead of discovering it after all TTS.
   - Verify: test fails before fix, passes afterwards; existing provider tests remain passing.
5. **Background, mix, render** — inspect whether valid stems exist; run separation only if missing and admitted. Mix in bounded windows; retain BGM/SFX unity gain. Render only after dialogue readiness and output QA pass.
   - Verify: full timeline coverage, no missing clips, unchanged video duration, no clipping, decodable video/audio, render QA passed. If content or resources prevent this, report the precise remaining work and saved checkpoints; never manufacture a successful final.

## Performance implementation sequence

1. **Measure and expose real bottlenecks** — `work_progress.py`, `system_diagnostics.py`, `auto_dub.py`, UI progress. Record stage start/end, speech duration, real-time factor, queue wait, model load versus inference time, worker/device identity, peak RSS/VRAM, retry counts and cumulative elapsed time across resumes. Separate processed/failed/review-needed/completed counts.
   - Verify: resumed elapsed time never resets to a misleading one-second movie run; ETA is based on measured remaining units; logging polls do not obscure worker failures.
2. **Stage-specific admission and process lifetime** — `resource_plan.py`, `worker.py`, `chunk_worker.py`, `auto_dub.py`. Estimate additional memory for the next actual unit/provider, reserve headroom, release completed model processes, and continuously account for active reservations. Use separate profiles for analysis, Piper, cloning, fit, separation, mix and render. Persist `waiting_for_resources`; retry with bounded backoff, reduce concurrency/chunk size after OOM, and resume after memory returns. Unknown resource state remains explicit. Do not simply delete safety checks or apply Piper's budget to cloning.
   - Verify: low-RAM speech/fit resumes without charging ASR again; real insufficiency waits without losing progress or busy-looping; cancellation and restart work while waiting; heavy admission remains conservative.
3. **Durable dialogue queue with one writer** — `db.py`, `worker.py`, new dialogue-task module, `app.py`. Tasks include project, segment, stage, source/text/voice/model/settings fingerprint, output hash, attempt and lease. Workers write isolated temporary outputs; one coordinator validates and atomically commits metadata. Retry only transient failed units; deterministic empty-text failures enter a repair queue. Schedule other valid units independently; final export still requires every required unit.
   - Verify: terminate a worker mid-task; no double commits, torn JSON, duplicated dialogue or loss of successful output. Edited text/voice invalidates only dependent tasks. Same project cannot have competing coordinators.
4. **Warm bounded TTS workers and CPU fit pool** — `dubbing.py`, new persistent Piper worker, `app.py`. Reuse a loaded Piper voice across compatible requests; cap thread count and model cache size. Select concurrency from measured memory; start at one under pressure, then benchmark two/four workers. Put fit/normalize on a bounded CPU pool and overlap it with new TTS when resources allow. Keep clone workers in their compatible runtime and enforce voice consistency.
   - Verify: output text, voice identity, speed/pitch policy and timing equivalent to serial baseline; compare 100-line throughput and model-load cost; crash recovery retains completed clips. No concurrent JSON writers.
5. **Speech-aware ASR batching** — `media.py`, `chunked_asr.py`, `chunk_worker.py`. Reuse existing VAD; persist absolute speech intervals. Benchmark faster-whisper batched inference and `int8_float16` against current mode; adapt batch size to measured VRAM with OOM fallback. Keep context overlap, word timestamps, stable absolute timing and global speaker reconciliation.
   - Verify: speech on chunk edges appears exactly once; quiet dialogue is retained; silence-only intervals create no fabricated TTS. Compare transcript accuracy, speaker consistency, peak memory and speed on the same reference clip before enabling by default.
6. **Device-specific execution** — `system_diagnostics.py`, worker registry and routing. Probe CTranslate2, PyTorch and ONNX providers independently in their actual runtimes, then run a small inference test. Route by device ID, compatible engine and free VRAM. On this 4 GB GPU begin with one resident heavy model; overlap lightweight CPU tasks. Evaluate Intel/AMD ONNX support only where the model/provider is supported and faster than CPU. Never treat shared integrated memory as additional dedicated VRAM.
   - Verify: CPU-only, 4 GB NVIDIA, larger NVIDIA, and available integrated GPU profiles; incompatible runtime gives an actionable fallback reason. No aggregate multi-card allocation.
7. **Speech-region separation and streaming audio** — `chunked_separation.py`, `background_preservation.py`, `chunked_mix.py`, `mixing.py`. Separate expanded dialogue regions with overlap/crossfades; copy original no-dialogue BGM/SFX sections. Persist per-region stems and reuse models between regions. Keep bounded audio reads, output hashes, timeline coverage and streamed QA. Singing/off-screen/quiet speech needs conservative detection and review.
   - Verify: region seam continuity, no source speech left by misclassified silence, BGM/SFX preservation, 1/2/3-hour peak RAM bounded by chunk size rather than full duration; restart does not re-separate valid chunks.
8. **Launch and UI controls** — launcher plus web upload/progress views. Offer upload-only versus auto-dub, Fast/Balanced/Quality choices with visible tradeoffs, worker/device dashboard and optional terminal log viewers. Workers remain managed background processes; a visible terminal is a viewer, not extra compute capacity. Show failed-line repair and resume separately from restart.
   - Verify: upload-only schedules no inference; retry never repeats 732 valid clips; user can inspect workers and cancel them without orphan processes.
9. **Dependency changes only after benchmark** — keep existing faster-whisper, CTranslate2, Piper and FFmpeg first. Add pinned optional GPU/provider requirement groups only after compatibility testing in an isolated environment; avoid replacing the active environment mid-recovery. Verify package/model licenses and cache readiness.
   - Verify: install smoke test, actual inference, reproducible environment; rollback leaves current voice/model outputs usable.

## Benchmark and rollout gate

Use the same media/model/quality settings for baseline versus candidate. First a 5–10 minute representative sample (quiet dialogue, crowded speech, music, silence, chunk boundary). Then this 65-minute episode, then 2-hour and 3-hour trials. Record stage seconds, total wall time, speech seconds, peak RAM/VRAM, failures, resumed/skipped units and quality issues. A speed claim requires measured improvement with no dropped dialogue or weakened QA. Long jobs may still take substantial time on CPU or small GPUs; do not promise a universal fixed runtime.

## Risks and non-goals

- More processes can reduce throughput on 4 GB VRAM or low system RAM. Control concurrency and model residency rather than opening arbitrary terminals.
- Existing translations can be semantically weak or exceed timing; speed work does not automatically fix translation quality. Keep actionable failed-line diagnostics; the user requested automatic processing without review queues.
- OneDrive may temporarily lock files. Use atomic replace/retry and checkpoint validation; consider a local non-synced runtime directory as a separate user-selectable storage setting.
- Do not replace completed analysis, change speakers, bypass human semantic-adaptation gates, remove source media, auto-install untested GPU stacks or silently export an incomplete movie.

## Primary technical references

- faster-whisper batching, quantization and VAD: https://github.com/SYSTRAN/faster-whisper
- ONNX provider routing: https://onnxruntime.ai/docs/execution-providers/
- CUDA version/runtime compatibility: https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html
- DirectML constraints: https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html

These describe available mechanisms, not measured performance of this repository.

## User confirmations and queued full recovery — 2026-10-04

- User listened and confirmed SPEAKER_07 (2060.519–2064.519 seconds) is male, then SPEAKER_11 (3694.711–3698.711 seconds) is male dialogue. Confirmation scope is speaker gender/dialogue only; clone identities/naturalness were not falsely human-approved. Local evidence is `analysis/speaker_voice_confirmations.json`.
- All 12 speaker profiles now use real reference-conditioned OmniVoice with validated reference hashes/transcripts and stable speaker mapping. Within the required register, matching prefers available references closest to the source pitch; this is acoustic matching, not proof of age/actor identity. Corrected the inherited `Young Female` label for user-confirmed male SPEAKER_11.
- Published the separately generated 735-line natural Hindi draft and invalidated stale synthesis metadata without deleting previous clips/video. Metadata backup: `runtime/backups/test2-quality-rebuild-20261004-090144`.
- Full neural separation job `b384f22e-2830-4ee3-8186-6430cfade591` is running in a persistent worker, with 66 resumable chunks. First four chunks completed at the verification snapshot.
- Auto-dub continuation job `c38cc306-17cb-4df8-b43f-49afdb0d0709` is queued behind separation, with completed analysis/identity/translation checkpoints reused and 735 new clone synthesis units pending. The worker serializes these GPU-heavy jobs. Final mix/render has not completed; saved old preview is retained.
- Latest targeted confirmation/matching regression: 57 passed across automatic dubbing, studio integrity and voice-bank gates.
- Earlier outstanding SPEAKER_07 ambiguity is resolved by the user; the full-episode and hardware benchmark/quality limitations above remain until actual jobs finish.

## Capacity-based parallel separation — 2026-10-04

- Added Auto or custom 1–256 separation worker requests in the studio and API (`separation_workers`). `OPENDUB_SEPARATION_WORKERS` provides a default. Requests are capped by free RAM, CPU budget and per-device NVIDIA VRAM; specifying 20 does not force 20 models into a 4 GB GPU.
- Multiple admitted CUDA workers are bound to physical GPU UUIDs. Each worker keeps its model loaded across chunks. When visible helpers are enabled, each active worker gets one persistent terminal for the batch.
- Completed checkpoints retain their validated output hashes and original chunk boundaries across worker/device/thread changes. Resume reuses legacy checkpoint folders; the shorter final chunk cannot change the recovered partition size. Missing or corrupt outputs are retried.
- The already-running test 2 worker was not restarted, stopped or reconfigured. These source changes take effect on the next normal studio/worker launch. This RTX 3050 4 GB machine remains a one-heavy-worker configuration; high-capacity worker tests use simulated hardware and do not constitute a 20-model GPU benchmark.

## Disk-stop recovery — 2026-10-04

- Separation stopped after 56/66 chunks when C: had approximately 2 GiB free. The job exhausted three retries; the queued auto-dub job subsequently failed its disk admission. Terminal absence was a consequence of stopped jobs, not CPU-only inference.
- Purged the regenerable pip download cache (7.6 GB reported by pip). Removed 2.53 GiB of separation context/raw duplicate stems only after each completed checkpoint passed output size/hash validation. Original media, final previews and validated checkpoint output stems remain intact.
- Added automatic validated separation scratch cleanup and corrected speech/fit storage estimates to budget their own pending audio/scratch rather than full analysis intermediates again. Disk/RAM admission remains enabled. Targeted regression checks: 72 passed.
- Restarted only the idle recovery worker after confirming no active jobs; requeued the existing separation and auto-dub job IDs with force_restart=false. Enabled visible helpers. New worker log: `runtime/test2-resume-worker.log`. CUDA warm-worker inference was measured at 100% RTX usage and 3743 MiB VRAM. At the first continuation check, 59/66 chunks were retained.
