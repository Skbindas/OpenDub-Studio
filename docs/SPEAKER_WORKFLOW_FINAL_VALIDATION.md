# Speaker workflow final validation — 14 October 2026

The actual 84.497-second uploaded source completed assisted identity/casting review, Hindi synthesis, timing, background preservation and render. This validates the short-source workflow; it does not establish universal diarization or demographic accuracy.

## Actual artifacts

- Three reviewed dialogue identities plus one reviewed song cluster; 23 complete Hindi utterances. The initial model merged similar voices; source corrections retain `assistant_review` provenance and original analysis backups.
- 23 genuine OmniVoice reference-conditioned clips and 23 completed timing fits. The original eight successful clips and all 65 protected original voice/reference hashes are unchanged.
- User explicitly approved a single 0.27-second audio allowance for “शुक्रिया”. Source ASR remains 23.83–24.15; the Hindi window ends at 24.42. Source/text/speaker changes or another speaking turn invalidate the allowance.
- Final video SHA-256: `43dc8589dff62b9df0f6fd5b496b05b0c92ccafae7e964a3a33d927a929e4fee`. Automated render QA PASSED; full FFmpeg `-xerror` decode PASSED. Original and final video packet SHA-256 values are identical: video was copied without recompression.
- Neural instrumental is used during reviewed dialogue. Original PCM is retained outside dialogue, including excluded singing vocals. Actual 28.5–30.0-second song samples match the source exactly in the preserved background. BGM gain remains 0 dB; separation within dialogue still needs listening review.
- Signed PCM16's valid negative endpoint is -1.0; its positive endpoint is 32767/32768. The mix guard now handles that asymmetry while still rejecting floating overflow, without cutting speech or changing background gain.
- Previous successful output remains in `output/revisions/pre-selective-background/`. Private receipts: `analysis/final-verification-receipt.json` and `analysis/selective-background-receipt.json`.

## Optional tools and limits

Voice-trait inference ran locally and appeared in the UI. Raw ONNX input and softmaxed logits follow the [official audEERING exporter](https://github.com/audeering/w2v2-age-gender-how-to). Suggestions are editable, uncalibrated and sometimes unknown; they do not certify gender identity or exact age. Model weights are CC-BY-NC-SA-4.0, available only in explicit non-commercial research mode; they are not a commercial application default.

[SpeechBrain SepFormer](https://huggingface.co/speechbrain/sepformer-whamr16k), Apache-2.0, was pinned to revision `21a5b500c6f52fddc387c5d9e5fb13ffd6f039c5`. A controlled mixture of two real source voices was separated and transcribed on CPU and CUDA. Both Chinese channel texts were recovered, but one channel had weak signal separation. Ownership and completeness therefore remain review candidates; no movie overlap was invented and recovered words are not automatically accepted.

Dependencies are isolated under `runtime/speaker-tools/packages-v1`. Pinning ruamel.yaml 0.18.17 fixes the [upstream HyperPyYAML compatibility issue](https://github.com/speechbrain/HyperPyYAML/pull/32). Main and cloning environments remain unchanged. CUDA reuses the existing separation environment; device provenance distinguishes separation and ASR. Optional tools share the existing single-heavy-worker lock.

Queue admission, source/review revision binding, atomic validated audio caches and non-retrying setup failures are covered by regression tests. Stale recovery audio cannot be served as current evidence.

Actual picker upload was tested previously. Tests now verify that both drop surfaces forward the original File object to the real upload workflow. Human OS dragging remains unverified because the in-app automation API does not support it. Browser decode/playback cannot certify perceived voice identity, acting or audio cleanliness.

## Regression and UI verification

- Broad project suite: **372 passed, 2 skipped**, excluding four expensive media integration tests from the second run; all four passed in the earlier full run. One outdated fallback expectation was corrected to require failure when neural separation is unavailable.
- After final audio/tool changes: **96 relevant Python tests passed**. After final preview/API changes: **56 tests passed**.
- **9 frontend tests passed**, including File forwarding and restoring a cleared completed-video URL. JS syntax checks passed.
- A browser bug found during real playback verification was fixed: reselecting a project cleared the final media source but retained its loaded marker. The player now restores its URL and responds to updated render revisions.
- Updated script cache versions prevented the embedded browser from reusing the old player code. The actual final video reached `readyState=4`, played through about 25 seconds without a media error and was paused for review. Screenshot: `runtime/speaker-workflow-validation/verification/final-hindi-preview.jpg`. The localhost tab and main terminal remain open.

The source media, reference banks, previous successful renders and other projects remain preserved. Private media/model binaries were not staged or uploaded. No commit, push or publication was performed.
