# Kaggle implementation plan — 14 October 2026

Live corrections: install numerical dependencies before GPU imports; pin NumPy 2.2.6 for the observed metrics >=2.2.2 and Numba <2.3 bounds. Real corrected speaker inference passed. Batch up to 16 native CPU fit/normalize operations and dialogue headroom updates per immutable notebook, preserving per-line timing/review checks and completed outputs. This avoids per-line notebook startup. See [metrics metadata](https://pypi.org/project/pyannote-metrics/4.1/) and [NumPy troubleshooting](https://numpy.org/doc/stable/user/troubleshooting-importerror.html).

The user authorized requirements research followed by incremental implementation, with testing after implementation. Preserve the existing local pipeline and completed media. Stop at 95% five-hour usage and leave a resumable handoff.

## Goal and decisions

Each local installation uses its owner's Kaggle account. Local remains the default. Explicit project selection controls offloading; no automatic local fallback. Credentials stay in the operating-system credential vault (explicitly account-bound environment credentials are also supported; native Kaggle file/OAuth integration is a separate future adapter), never in project manifests, browser storage, source bundles or Git.

Use bounded private notebook jobs and content-addressed inputs. Keep completed outputs and manifests on the user's laptop; a later notebook may read a previously completed kernel's outputs. Do not rely on ephemeral scratch, live GPU migration or combined memory from two GPUs. An unfinished chunk can be replayed after session loss. Provider quota/availability remains unknown unless authoritative provider evidence reports it. Never work around quota, restrictions or account verification.

Alternatives considered: one whole-film notebook is simpler but has an unacceptable interruption/session-limit failure domain; a remote always-on HTTP worker would require infrastructure Kaggle notebooks do not provide reliably. Bounded notebooks cost model startup time but make recovery auditable.

## Verified sources and limits

- [Kaggle terms](https://www.kaggle.com/terms): internal/personal/non-commercial usage and no third-party account operation. BYO accounts do not override the terms; public commercial-worker support is not certified.
- [Notebook documentation](https://www.kaggle.com/docs/notebooks): documented session/storage limits are finite; do not claim arbitrary movie duration fits one session. Account limits are runtime facts, not a hardcoded remaining-quota counter.
- [GPU quota](https://www.kaggle.com/docs/efficient-gpu-usage): weekly quota is described as 30 hours or sometimes more; no guaranteed availability.
- [Official CLI authentication](https://github.com/Kaggle/kaggle-cli/blob/main/docs/README.md): OAuth, KAGGLE_API_TOKEN, native token file, legacy username/key. Current PyPI release checked: kaggle 2.2.4, Python 3.11+; keyring 25.7.0.
- [Kernel operations](https://github.com/Kaggle/kaggle-cli/blob/main/docs/kernels.md) and [metadata](https://github.com/Kaggle/kaggle-cli/blob/main/docs/kernels_metadata.md): private script metadata, push/status/output, accelerator request; some listed accelerators are restricted. Secrets require notebook UI authorization; do not place HF/translation credentials in submitted code.
- [Dataset operations](https://github.com/Kaggle/kaggle-cli/blob/main/docs/datasets.md): create private input datasets. Use owned media with explicit upload selection; never attach all runtime or the full private repository.

## Ordered implementation

1. **Account/config foundation** — optional requirements, backend credential-vault adapter and project compute settings, UI credential form and local/Kaggle selector. Secrets are write-only; no silent default-account substitution. Verification is deferred to step 6.
2. **Durable remote jobs** — separate SQLite ledger, immutable request fingerprint, deterministic unique kernel/dataset handle, pending/submitting/uncertain/queued/running/downloading/completed/review/waiting states. Save submission intent before API calls; reconcile uncertain responses rather than duplicate them. Serial admission, bounded polling and restart recovery.
3. **Private bounded worker** — allowlisted backend source archive, one source crop and manifest, pinned Linux dependencies, private notebook metadata, actual GPU provenance, hash-bound result receipt. Keep data submission separate from local preparation. No secrets or unrelated projects in the upload.
4. **Pipeline adapters** — start with separation and timestamped ASR, then gated diarization and reference-conditioned speech, then fit/mix/render with original video stream copy where supported. Preserve review gates, source clock, model/license provenance and completed checkpoint validation. Until all required stages are wired, the full Kaggle Auto-Dub route must report incomplete integration instead of quietly running locally.
5. **Recovery and choice** — import only matching, hash-verified output into local checkpoints; distinguish quota waiting from auth/model/code failures. Request a new eligible accelerator/session only after the old attempt is terminal/reconciled; retain completed outputs. UI offers explicit local choice, meaningful status, and pause/resume without regenerating completed clips.
6. **Testing last** — credential masking/no plaintext fallback; private metadata/bundle exclusion; at-most-once submission after timeout/restart; source/model change invalidation; malformed/traversal/stale output rejection; provider queue/quota/auth status mapping; real GPU operation, interruption/resume, actual small-video UI flow and media decode/listening QA. No long-film run until bounded real flow passes. User supplies credentials privately in localhost UI; no credential generation/account agreement acceptance on their behalf.

## Completion contract

Prepared, submitted, completed remotely, imported locally and final media verified are separate claims. Authentication, GPU eligibility and quota are UNVERIFIED until real account checks. Local checkpoint durability does not guarantee recovery of the last unfinished chunk or availability of a replacement GPU. Implementation and final testing progress are recorded in `KAGGLE_CONTINUATION.md`.

## Resumed implementation decisions

- Keep CLI/keyring/HF-download dependencies in `runtime/kaggle-env`; a stdin/stdout bridge prevents protobuf or SDK changes in the working main/clone/separation runtimes. Secrets are never command-line arguments or public bridge responses.
- Use Community-1's documented offline loading: stage an owner-authorized cached snapshot, license/provenance and exact file hashes as a private model input. Add a separate explicit model-upload choice. HF tokens stay on the laptop; no notebook Secrets binding is required for each retry. Never bypass the model's gated access/conditions. Public ASR/OmniVoice downloads use pinned HF commits.
- Extend the bounded contract to diarization, real reference-conditioned synthesis, fit/normalization, selective background, mix and stream-copy render. Control, hashing, review and small input preparation remain local; neural inference and heavy audio/video work run on Kaggle. Media-only jobs use remote CPU; allocated CUDA is required for neural jobs.
- Reuse immutable account-owned input/model datasets. Persist uncertain upload/submit intent before remote mutations and reconcile existing handles. Completed results are source/config/model/code-bound and never silently overwritten. Explicitly cancelled/detached work is not automatically restarted.
- Testing remains last and uses the supplied 84.497-second source in a separate project/copy, preserving the completed baseline and accepted takes.
- Synthesis uses batches of four reviewed lines with pinned CUDA Hindi ASR in the same notebook, after releasing the generator. Completed batches survive interruption; unfinished batches can replay. Media-only tasks remain separately checkpointed. Startup/transfer overhead is not a speed guarantee.
