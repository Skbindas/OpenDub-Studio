# Cleanup and Kaggle handoff — 14 October 2026

## Cleanup boundary

The current tested dubbing code, tests and portable documentation are the delivery baseline. Source media, successful renders, reference/clone banks, checkpoints, secrets and model binaries remain local. No Kaggle worker has been implemented or tested yet.

An import/path search found no active Chatterbox provider or reference to the obsolete optional speaker-tools package target. These were removed from the checkout into a recoverable local sibling archive:

- `runtime/chatterbox-env`: 5,596,506,703 bytes.
- `runtime/speaker-tools/packages`: 19,322,233 bytes; superseded by the pinned `packages-v1` target.
- `scratch`, `temp_frames`, `temp_p23_tests`: historical scripts, derived frames and test audio, retained locally for recovery.
- Four obsolete one-time scripts: `patch_auto_dub.py`, `patch_background_preservation.py`, `patch_character_voice.py`, `rebuild_test2_dubbing.py`.

Permanent removal was blocked by automatic approval review. Archiving removes these from the working project without freeing disk space. Restore only to the same original paths while workers are idle. A private archive receipt contains the exact source/destination paths.

Keep the main, OmniVoice cloning and separation environments: the latter reuses compatible packages from the other two. Keep Piper, separation, diarization/ASR caches, SepFormer and the explicitly restricted research voice-trait model; these have actual code or workflow consumers. No blanket uninstallation of transitive packages or shared user model caches was performed.

Ignore rules now exclude scratch, old temporary audio and Kaggle/other credential files. `requirements-speaker-tools.txt` is explicitly publishable; the earlier uppercase TXT exclusion accidentally hid it on this Windows checkout. New private video/model binaries are excluded from the source delivery.

## Verification and continuation

Post-cleanup validation passed: **376 Python tests passed, 2 skipped**, excluding the expensive media-integration module already exercised in the preceding real-media work; **9 frontend tests passed**, Python compilation and speaker-workflow JS syntax passed, and `pip check` reported no broken requirements. Private before/after receipts verified the source/final video hashes, all 65 protected voice/reference files, 8 initial completed clips and unchanged queue state. The running localhost API still exposes the completed final video. Preserve that 23-utterance real-source dub; do not restart its analysis or synthesis to test cleanup. See `SPEAKER_WORKFLOW_FINAL_VALIDATION.md` for the earlier real-media evidence and remaining quality limits.

The in-app browser's Kaggle home page showed the already signed-in account. Account GPU verification, available accelerators, quota and API access are not yet verified. Credentials must be entered by the account owner and must stay outside Git.

## Next implementation boundary

Before a Kaggle adapter, verify the current [Kaggle terms](https://www.kaggle.com/terms), [notebook limits](https://www.kaggle.com/docs/notebooks) and [CLI kernel operations](https://github.com/Kaggle/kaggle-cli/blob/main/docs/kernels.md). A user-supplied account does not override service usage restrictions. Do not advertise a public commercial worker until its intended use is allowed.

1. Add explicit local/Kaggle selection and secure local credential storage; never silently upload media or switch providers.
2. Package a Linux-compatible, versioned worker with pinned dependencies/model revisions and a source/config fingerprint.
3. Persist the chunk manifest, validated outputs and hashes outside each ephemeral notebook session. Resume only compatible completed checkpoints.
4. Map actual provider status to queued/waiting/running/recovering/review/completed. Show quota or accelerator unavailability honestly and offer local processing by user choice.
5. On session loss, reconcile the remote run before submitting another; do not blindly duplicate uncertain submissions. Start another eligible session only when available. An unfinished chunk may need replay; completed chunks must remain unchanged. No GPU availability or instantaneous hot swap guarantee.
6. Verify interrupted-job recovery and changed-input invalidation on a small real source before attempting a full movie. Check data licensing, private dataset/notebook access and each model's separate license.

The first published run passed 378 tests but failed the new disk-mapped waveform test because the core-only Linux runner lacked optional PyTorch. CI now explicitly installs CPU PyTorch 2.11.0 from the [official CPU wheel index documented by PyTorch](https://pytorch.org/get-started/previous-versions/); no local environment or default application requirement was expanded. The actual waveform test remains enabled.

Publication receipt and exact-commit CI status belong in the local continuation handoff after the authorized GitHub push.
