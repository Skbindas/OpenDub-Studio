# Whole-film speaker identity and Hindi voice casting

Research and checkout audit: 13 October 2026. Scope: what should be implemented first so different characters keep appropriate, consistent Hindi dubbing voices. This document records findings and proposed architecture, not newly implemented detection or measured whole-film accuracy.

## Decision

Keep the existing vocal-first analysis and pyannote Community-1 as the initial baseline. Preserve both ordinary overlapping diarization and exclusive alignment output. Add learned speaker embeddings, a versioned project-wide identity registry, conservative assignment, clean reference selection and persistent voice locks. Compare alternative models on the same annotated movie excerpts before replacing this baseline.

Treat three questions separately:

1. **Who spoke when?** Audio speaker diarization provides provisional identities and activity intervals, including simultaneous speakers.
2. **Which story character is that?** Connect a speaker to an anonymous on-screen speaking track or a user-confirmed character. Off-screen dialogue remains valid. Audio alone cannot always distinguish one performer voicing two roles, or link two actors playing the same character at different ages.
3. **Which Hindi voice fits?** Rank compatible voices using clean reference quality, register, timbre, delivery and reviewed casting tags. A low/high pitch threshold is insufficient. Speaker identity, character identity and target voice ID must be separate fields.

Count detected **speaking identities**, with unresolved clusters shown separately; do not advertise this as the complete visual cast or an infallible character count.

## Actual checkout findings

Repository: OpenDub-Studio, branch `phase-12-semantic-adaptation-provider`. There are many pre-existing uncommitted edits. Those edits, movie files, successful takes and private voice-bank assets were preserved during this research.

| Evidence | Current behavior | Required improvement |
|---|---|---|
| `backend/analysis_pipeline.py:299–347` | Separated vocals feed ASR and diarization on a shared source-media clock; words are assigned to speaker turns | Preserve this working foundation; add overlap-aware attribution and reliable global IDs |
| `backend/diarization.py:248–278` | Prefers `exclusive_speaker_diarization` and saves only that timeline | Save regular turns **and** exclusive turns. Exclusive assignment is not proof that the original audio has only one speaker |
| `backend/voice_bank_quality.py:102`, `backend/automatic_dialogue.py:208–218` | Clean-reference windows are computed from saved turns | Subtract other speakers using the regular overlapping timeline; otherwise mixed voices can enter a supposedly exclusive reference |
| `backend/diarization.py:285–328` | Candidates are individual turns; top-two margin can compare two turns belonging to the same speaker | Aggregate the union of overlapping intervals per unique speaker before ambiguity checks |
| `backend/speaker_engine.py:233–252` | An acoustic vector has 16 manually constructed pitch/energy/spectral measurements | These are useful supporting descriptors, not a learned identity embedding; add a model-backed adapter |
| `backend/speaker_engine.py:561–639` | Phase-24 helper repartitions already labelled transcript segments and reconciles their acoustic features | This does not establish robust identity recovery from independently diarized movie chunks. Wire and evaluate real inference/global reconciliation in the actual analysis path |
| `backend/automatic_dialogue.py:93–114` | Uses at most five short windows and median F0; lower <165Hz, higher >195Hz, otherwise unknown; voiced F0 is filtered to 70–380Hz | Childlike/high-register or very low voices may fall outside that range. Retain pitch as one descriptor, not a gender/age classifier |
| `backend/automatic_dialogue.py:81–90` | Automatic reference choice ranks lower/higher-register references and pitch distance, with used voices deprioritized | Add timbre/style/reference eligibility and distinctness ranking; show several auditions before locking |
| `backend/diarization.py:_select_device/_run_pipeline` | Auto policy uses CPU on a 4GB card; CUDA fallback can move a pipeline to CPU | Benchmark actual stage peak memory; record effective fallback device rather than the originally requested device |
| Existing voice profiles | Some catalog/provider age/gender fields are metadata/defaults | Keep user/provider tags distinct from estimates. Do not present default `adult` or catalog metadata as source-character detection |

A read-only function reproduction confirmed the turn-aggregation defect: a segment covering two adjacent 0.5s turns by speaker A returned `speaker_id=None`, `ambiguous_overlap`, with A appearing twice in candidates. The correct combined ownership is A, not a two-person ambiguity. No production code was changed to hide this result.

Existing `tests/test_diarization.py` and `tests/test_vocal_timeline.py` passed: **6 tests in 3.87s**. These verify the existing alignment/control behavior; they do not establish real-movie identification accuracy or cover the reproduced aggregation defect. No new production detector has been implemented by this research task.

Current main environment reports pyannote.audio 4.0.7, PyTorch 2.11.0 and faster-whisper 1.2.1. SpeechBrain and NeMo are not installed there. NVIDIA enumeration reports RTX 3050 Laptop GPU, 4096MiB total. This does not prove model access, inference speed or quality: no new model was downloaded, no cloud audio upload was made, and no whole-film benchmark was run.

The older phase24 research file contains strong accuracy/latency and pitch-to-gender claims. Existing synthetic-vector tests and a reconciliation report do not substantiate general film accuracy. Treat those claims as historical proposals until a labelled real-media evaluation supports them.

## Primary-source comparison

| Component | Verified purpose and constraints | Recommendation |
|---|---|---|
| [pyannote Community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) | Counts/assigns speakers, regular and exclusive outputs, local/offline and CUDA execution; weights CC-BY-4.0, gated access conditions | Initial baseline already integrated. Retain raw overlaps and provenance. Its published errors vary substantially by dataset; AVA-AVD is 44.6% DER, which rules out a universal perfect-accuracy promise |
| [NVIDIA Nemotron-3 Diarization](https://huggingface.co/nvidia/Nemotron-3-Diarization) | Streaming/offline, up to eight speakers, arrival-order speaker cache; chunked duration is not capped; OpenMDW-1.1 | Compare on bounded excerpts, including long-gap returns. Do not force a film with more than eight identities into eight channels. Published input-buffer latency is not total job processing time |
| [WeSpeaker](https://github.com/wenet-e2e/wespeaker) | Learned speaker embedding/verification toolkit; Apache-2.0 code; model variants have their own provenance | Prefer evaluating the existing pyannote embedding family first; use WeSpeaker as an explicit adapter when required |
| [SpeechBrain ECAPA-TDNN](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb) | Speaker verification and embeddings from VoxCeleb-trained models; Apache-2.0 | Useful alternative for global identity linking. Verification benchmark performance is not movie diarization accuracy or child-voice validation |
| [WhisperX](https://github.com/m-bain/whisperX) | Forced alignment/word timestamps with diarization integration; repository currently BSD-2-Clause; README acknowledges overlapping speech and imperfect diarization | Optional alignment adapter after a dependency-isolated pilot. Do not replace the functioning main environment blindly; forced alignment alone cannot recover a missed simultaneous speaker |
| [SpeechBrain SepFormer-WHAMR](https://huggingface.co/speechbrain/sepformer-whamr) | Speech separation trained on noisy/reverberant WSJ-derived mixtures; this checkpoint expects 8kHz mono; Apache-2.0 | Overlap-only research adapter. Not a universal multilingual multi-character solution; never force three-speaker/crowd audio into an unverified two-output separator or use 8kHz results as a fidelity master |
| [TalkNet-ASD](https://github.com/TaoRuijie/TalkNet-ASD) | Audio-visual active-speaker detection, MIT code; authors discuss cross-domain difficulty | Later optional evidence: which visible face is speaking. It is not an actor-name lookup, gender detector or replacement for off-screen audio diarization |
| [audEERING age/gender checkpoint](https://huggingface.co/audeering/wav2vec2-large-robust-24-ft-age-gender) | Statistical audio predictions; CC-BY-NC-SA-4.0 model | Research reference, not a commercial-app default. Its outputs must not be converted into factual personal gender identity or exact age. Prefer editable casting style tags and uncertainty |
| [Microsoft VibeVoice-ASR](https://github.com/microsoft/VibeVoice/blob/main/docs/vibevoice-asr.md) | Unified ASR/speaker/timestamp output; a 7B model documents up to 60-minute single-pass input | Larger-hardware comparison candidate. A 7B model is not a demonstrated fit for this 4GB GPU; films longer than its context need a separate continuity strategy |

These are different tasks and models, not interchangeable packages. Freeze code/model revisions and record model licenses separately from framework licenses. No installation or gated-condition acceptance was performed during research.

## Existing products: useful patterns, not accuracy proof

[ElevenLabs Dubbing Studio](https://elevenlabs.io/docs/eleven-creative/products/dubbing/dubbing-studio) documents speaker cards, per-speaker voice selection and editable clip transcripts. It is currently in maintenance mode; study the interaction pattern rather than treating it as a new open-source dependency. Its [current dubbing overview](https://elevenlabs.io/docs/overview/capabilities/dubbing) describes speaker preservation, but vendor capability claims are not OpenDub test results.

[Voice-Pro](https://github.com/abus-aikorea/voice-pro) is a GPL-3.0 workflow reference for separation/ASR/cloning. Its current README says WhisperX was removed because of dependency conflicts. [VoiceStudio](https://github.com/debpalash/VoiceStudio) is an AGPL-3.0 local application reference; its application licensing and individual model rights are separate. Neither README establishes correct identity tracking for this user's entire film. Study their workflow/error handling; retain OpenDub's existing accepted voice assets.

Movie diarization is harder than clean two-person conversation. The primary [AVA-AVD paper](https://arxiv.org/abs/2111.14448) specifically addresses diverse scenes, acoustic conditions and off-screen speakers. [Late audio-visual fusion research](https://arxiv.org/abs/2211.01299) supports investigating visual evidence alongside audio, not assuming a visible listener is the current speaker.

## Proposed end-to-end flow

Source media → preserve original mix/stereo → duration-validated dialogue/vocal stem → voice activity + regular overlapping diarization → word-aligned transcript → global identity reconciliation → character review/casting → locked Hindi voice synthesis → time fitting/overlap-aware mixing → original BGM/SFX-preserving render and QA.

1. **Full coverage.** Scan the entire duration, including late-entering characters, returns after long silence and off-screen dialogue. Keep absolute source seconds; do not remove silence or concatenate separated excerpts into a new clock.
2. **Two diarization views.** Regular turns describe all active speakers; exclusive turns simplify ordinary ASR alignment. Derive overlap regions from regular activity. Preserve unresolved candidates rather than manufacturing one winner.
3. **Clean identity anchors.** Gather multiple non-overlapping single-speaker excerpts per identity, preferably several 2–5s segments across scenes. Keep SNR/voiced-duration/clipping/overlap evidence. Short “hi”/“yes” remains provisional until stronger evidence exists. Exclude music/singing/crowd-contaminated anchors.
4. **Global registry.** Match learned embeddings with calibrated score and best/second-best margin, temporal evidence and same-window cannot-link constraints. Keep multiple anchor centroids when one speaker whispers or shouts. If no reliable match exists, propose a new ID or review item; do not silently merge. Chunk IDs must never be treated as character IDs.
5. **Overlap branch.** Two people simultaneously speaking remain two timeline lanes. Separate only flagged overlap crops when an evaluated model helps, then transcribe/reassign each separated stream using known anchors. Check continuity on the original stem; separation can damage speech or swap output channels. Three-plus speakers and uncertainty stay explicit.
6. **Vocal profile.** Automatically measure register range, timbre descriptors, pace and audible delivery. Offer childlike/adultlike/mature-like **voice-style** suggestions with uncertainty. These are casting aids, not factual gender identity or chronological age. Provider/user-confirmed male/female/child/elder voice-library tags remain editable metadata.
7. **Casting.** Use the existing genuinely reviewed Hindi references and model capabilities. Rank clean reference compatibility, timbre, register, delivery, supported Hindi pronunciation and audible distinctness. Source-identity embedding scores and cross-language target-voice resemblance are different scoring problems. Generate bounded short Hindi auditions, show top candidates and let the user lock the choice. Best clean contiguous 3–10s references remain compatible with the existing clone contract.
8. **Persistent voice lock.** Every character reuses the selected provider, model, voice/reference hash and settings. Expression can vary without replacing identity. Changed reference, transcript or model invalidates affected cache entries only; accepted unrelated takes remain intact.

## UI acceptance

Before expensive dubbing, show “Estimated speakers: N · unresolved: M”, coverage/completion and a review queue. Each card has stable ID, first appearance, speaking duration, several original samples, optional speaking-frame evidence, measured voice descriptors, editable casting tags, Hindi auditions and a lock action. Timeline controls: jump to source, rename, merge, split/reassign a turn, view simultaneous lanes and undo. “Auto suggested”, “user confirmed” and “voice locked” are separate states.

A user changing one ambiguous turn should not rerun the full movie or unrelated voices. Missing diarization/model access must produce an actionable setup/review state, never a fictitious one-speaker success.

## Evaluation before claiming accuracy

Create reviewed fixtures for different speakers with similar pitch; childlike versus high-register adult delivery; mature delivery; whispers/shouts; rapid alternation; 2-speaker and 3-speaker overlap; late arrival; long-gap return; off-screen lines; music/singing; scene cuts and actor/character ambiguity. Keep source hashes, original-clock annotations and actual speaker labels.

Measure DER with overlap included and speaker confusion/missed speech/false alarm separated; count error; cross-scene ID swaps; overlap precision/recall; word ownership error; and reference contamination. Compare all candidates on exactly the same audio and scoring settings. Evaluate Hindi auditions separately for identity consistency, complete content, pronunciation, naturalness and fitting. No percentage target is a verified result until measured.

Start with short real excerpts, then a contiguous 10–15 minute sequence and only then a full film. Preserve successful checkpoints and accepted voices. One admitted GPU-heavy stage at a time on this 4GB machine; actual memory/speed measurements decide whether any stage can overlap. Proposed windows/thresholds remain configuration, not untested guarantees.

Implementation order and explicit verification tasks are in `docs/SPEAKER_IDENTITY_IMPLEMENTATION_PLAN.md`.
