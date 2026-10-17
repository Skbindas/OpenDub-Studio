# Optional Kaggle processing

This experimental backend uses **your own account**. Local remains the default. A real 84-second Hindi cloud dub passed technical checks; human listening/identity acceptance, full movies and actual provider GPU-withdrawal/replacement remain unverified. See [the current evidence checkpoint](KAGGLE_CONTINUATION.md). No account is guaranteed an accelerator or quota.

## Install and launch from a clone

Complete [core installation](INSTALL.md). From the repository root, Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe scripts/setup_kaggle.py
.\start.bat
```

POSIX equivalent (core Python must be 3.11+ for this helper):

```sh
.venv/bin/python scripts/setup_kaggle.py
sh start.sh
```

The helper creates runtime/kaggle-env and installs the pinned SDK/vault/download requirements there. Do not install them into an existing clone or separation environment. Kaggle performs the selected heavy neural stages; the localhost application must remain running for upload, control, review, downloads and checkpoint persistence.

## Account, models and processing

1. From the repository, run the app's Python: `python scripts/setup_kaggle.py`. It creates `runtime/kaggle-env` without installing SDK dependencies into the main/clone/separation environments.
2. Open the local app, select a separate small test project and expand **Processing location · Local / Kaggle**.
3. Enter your username and existing Kaggle API token, or legacy key, in **Secure API credentials** and **Save securely**. Credentials use the native OS vault; no plaintext fallback. Do not put keys in chat, notebook code or Git. For explicit environment credentials bind `KAGGLE_USERNAME` to the selected account with `KAGGLE_API_TOKEN` or `KAGGLE_KEY`.
4. Select Kaggle and an accelerator. Select the separate private media and model-file choices, then **Save processing choice**. Selected media, reviewed references, dialogue and worker code become private inputs in your own account. Full mux/decode tasks also upload the source video. GitHub is never used for these media transfers.
5. Accept gated-model conditions yourself and acquire an authorized Community-1 snapshot locally. The app packages pinned offline files privately; HF tokens stay local. The selected separator must also be locally available to bind its checksum. ASR and OmniVoice use immutable public model revisions.
6. Start Auto-Dub. Source checks, ASR/stems and learned speakers precede review. Review identities and lock voices before continuing translation/synthesis, timing, background, mix and render. Speaker suggestions remain provisional.
7. Monitor actual task states. A queued GPU is not an allocated GPU. Unknown submissions are reconciled against the same handle; do not manually create duplicates. Finished outputs are downloaded and hash-checked before reuse.
8. After confirmed terminal session loss, bounded recovery can request replacement allocation while retaining completed batches. It cannot migrate live GPU memory or guarantee a replacement GPU. An unfinished synthesis batch, up to four lines, may replay. Model/code/content issues require correction/review.
9. To choose local, pause active work, save **My computer**, then explicitly resume. This detaches monitoring; it does **not** cancel a remote notebook. Monitor/stop an already queued or running notebook on Kaggle. Unresolved remote work blocks source replacement/project deletion so checkpoints keep their identity.

Neural tasks require allocated CUDA; media-only tasks use remote CPU. Video is stream-copied where supported. Small preparation/control/signal work remains local. Notebook startup/transfer overhead means no full-movie completion time is promised.

Review [Kaggle terms](https://www.kaggle.com/terms), [notebook limits](https://www.kaggle.com/docs/notebooks) and [official CLI authentication](https://github.com/Kaggle/kaggle-cli/blob/main/docs/README.md). BYO credentials do not override provider restrictions; this does not certify a public commercial-worker service.

## What downloads where?

| Item | Location / action |
| --- | --- |
| SDK and native-vault support | setup_kaggle.py → runtime/kaggle-env |
| ASR / OmniVoice public checkpoints | Worker downloads the pinned public revision for its selected operation |
| Community-1 gated checkpoint | Obtain locally with your own approved HF access; pinned offline files are uploaded privately only with your explicit model-upload choice |
| Separator checkpoint / companion configuration | Obtain the exact selected permitted model under runtime/models/separation; cloud request binds file hashes before upload |
| Source scene / reviewed reference inputs | Private inputs in the selected user's Kaggle account after explicit choices |
| Completed outputs / checkpoints | Validated and downloaded into the local project, outside Git source |

To explicitly pre-download the approved Community-1 snapshot using the main environment after its Hugging Face/ASR helper installation, with HF_TOKEN already set privately in .env:

```powershell
.\.venv\Scripts\python.exe -m pip install "huggingface-hub>=0.36,<2"
.\.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(); import os; from huggingface_hub import snapshot_download; snapshot_download('pyannote/speaker-diarization-community-1', token=os.environ.get('HF_TOKEN'))"
```

This downloads files; it does not accept gated access conditions, create a public dataset, or prove inference works. For separator download commands and exact-model cautions, see [local model setup](LOCAL_SETUP.md). Model licensing applies even when a user's cloud account pays for execution.

## Troubleshooting

- **SDK missing / Python too old:** use the main environment with Python 3.11+ and rerun the helper; do not replace working runtimes blindly.
- **Vault unavailable:** configure a supported native OS keyring. The app intentionally has no plaintext/browser-storage fallback. Do not put a token into the repository to bypass it.
- **Account mismatch / authentication failed:** confirm the selected username matches the account for the saved modern token or legacy key. The modern API token is supported; a legacy key is not mandatory.
- **Queued / quota / unavailable accelerator:** wait for actual provider status or choose local explicitly when ready. Do not promise an immediate replacement GPU.
- **Gated snapshot or separator missing:** finish the authorized local acquisition and exact-model configuration before submission; an API token alone is not model access.
- **Remote notebook still active after choosing local:** inspect/stop it in Kaggle yourself; detaching local monitoring is not remote cancellation.
- **Interrupted transfer or uncertain submission:** retain the same saved job and handle; resume/reconcile instead of creating duplicate notebooks. An unfinished batch may need replay.

Checked against the current application and official CLI authentication documentation on 16 October 2026. Current live quota/account requirements should be checked in the user's own Kaggle UI; this guide does not hardcode a free-GPU-hour promise.
