# OpenDub Studio

Experimental local-first AI video dubbing with speaker review, Hindi/English dialogue workflows, resumable jobs and optional personal Kaggle processing.

![OpenDub Studio](web/brand/opendub-wordmark-v2.svg)

**Created and maintained by [Suhaib (@Skbindas)](https://github.com/Skbindas).**

**AI Assistant — Development Support: OpenAI Codex.** See [contributors and acknowledgments](CONTRIBUTORS.md).

**Experimental source alpha.** The MIT application code is provided without user recordings, voice references, rendered videos, transcript samples, training datasets or model weights. Review the setup guides and third-party model terms before processing your own media.

## Contents

- [Overview and capabilities](#overview-and-capabilities)
- [Architecture](#architecture)
- [System requirements and prerequisites](#system-requirements-and-prerequisites)
- [Installation and launch](#installation-and-launch)
- [Local models and configuration](#local-models-and-configuration)
- [Kaggle setup and recovery](#kaggle-setup-and-recovery)
- [End-to-end workflow](#end-to-end-workflow)
- [Troubleshooting](#troubleshooting)
- [Automated tests](#automated-tests)
- [Repository structure](#repository-structure)
- [Contributing and credits](#contributing-and-credits)
- [Privacy and project storage](#privacy-and-project-storage)
- [License](#license)
- [Brand assets](#brand-assets)

## Overview and capabilities

OpenDub Studio runs a Python backend on your computer and presents a browser workspace for video localization. It coordinates transcription, speaker review, translation, speech generation, timing, background separation, mixing and export. The core installation supplies the workspace; neural stages require optional packages, models and access.

| Capability | Current behavior and review boundary |
| --- | --- |
| Project workspace | Local project files, SQLite job records and persisted stage progress |
| Speech analysis | Optional ASR and diarization produce dialogue/speaker candidates; review missed speech and overlapping turns |
| Character casting | Review speaker groups and assign stable, authorized voice references; age/gender hints are not verified identities |
| Translation | Configured providers generate target dialogue; review meaning, language and timing before synthesis |
| Voice generation | Optional neural synthesis with clean reference audio; no bundled default movie voice pack |
| Timing and mix | Fit dialogue, estimate retained backgrounds and inspect speech/mix QA; separation and timing can require corrections |
| Export | Preview and render after review gates; technical QA does not establish listening quality or lip synchronization |
| Compute | Explicit local or personal Kaggle execution and checkpoint recovery; allocation is not guaranteed |

This is an experimental source alpha. A short successful scene does not establish unattended full-movie accuracy, perfect character detection or a fixed processing time.

## Architecture

```text
Browser workspace (web/)
        |
FastAPI API (backend/app.py)
        |
Project manifests + SQLite job queue
        |
Auto-dub orchestration / worker leases
        |
Analysis -> speaker review -> translation -> speech -> timing -> mix -> render QA
        |
Local optional engines OR explicitly selected Kaggle worker
```

The launcher starts the local API and normally its embedded worker. A separate worker is available for server operation. Credentials are resolved at execution time; model/runtime artifacts are not part of the source distribution. See [architecture and stage ownership](docs/ARCHITECTURE.md) and [server deployment](docs/DEPLOYMENT-SERVER.md).

### Workers and persistence

Long-running media and render jobs are persisted in SQLite and processed by a worker lease. Local `start.bat` uses an embedded worker by default. Server deployments can disable the embedded worker and run `python -m backend.worker` as a separate process. See `docs/DEPLOYMENT-SERVER.md` for the multi-worker and Docker profile.

## System requirements and prerequisites

Use Python 3.11 as the CI-aligned starting point, Git, FFmpeg and FFprobe on PATH. Core package metadata accepts Python 3.10+; optional engines can impose narrower constraints. Node.js is needed for frontend development checks, not ordinary studio use.

| Workload | Planning guidance, not a certified minimum |
| --- | --- |
| UI and project review | A current Windows/Linux computer with space and memory for Python and your media; the UI alone needs no discrete GPU |
| Local neural processing | Plan for 16 GB or more system RAM and a supported GPU where the engine supports one; actual VRAM depends on model, precision and batch size |
| CPU-only processing | Supported stages can run more slowly; optional engines have separate platform constraints |
| Kaggle | Your account, secure credentials, internet, required model permissions and available quota/accelerator |
| Storage | Allow space for source media, models, PCM audio, stems, speech takes and exports; intermediates can exceed source-video size |

No universal GPU/VRAM or movie-length runtime promise is made. Check **Setup & readiness** before a short real-media test. Windows is the primary local launcher path; Linux CI checks source behavior. Full macOS and AMD/Intel neural acceleration remain unverified. See [installation prerequisites](docs/INSTALL.md) and [local engine setup](docs/LOCAL_SETUP.md).

### System tools

OpenDub Studio requires the following external tools:

1. **FFmpeg & FFprobe:** Must be installed and available on `PATH`.
2. **Rubber Band (librubberband):** FFmpeg build with `--enable-librubberband` is strongly recommended for pitch- and formant-preserved dialogue time-stretching. If librubberband is not present in the FFmpeg build, OpenDub Studio safely falls back to standard `atempo` time-stretching.
3. **Environment Validation:** Run `python scripts/check_dependencies.py` to deterministically verify that all CLI executables, FFmpeg filters, and Python libraries are properly installed.

## Installation and launch

For a fresh install, use the shallow clone commands below so Git downloads only the current clean source snapshot. Anyone can fork the repository and propose a contribution. Install Git, Python and FFmpeg/FFprobe first; see [installation and download requirements](docs/INSTALL.md).

Windows PowerShell:

```powershell
git clone --depth 1 https://github.com/Skbindas/OpenDub-Studio.git
Set-Location OpenDub-Studio
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/check_dependencies.py
.\start.bat
```

Linux/macOS manual core path, after installing the system prerequisites:

```sh
git clone --depth 1 https://github.com/Skbindas/OpenDub-Studio.git
cd OpenDub-Studio
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/check_dependencies.py
sh start.sh
```

Open the URL printed by the launcher (default http://127.0.0.1:7860), keep its terminal open and check **Setup & readiness**. These commands install the **core studio**, not every neural model. Optional-model compatibility and access must be resolved before a real dub.

### Launcher behavior and private configuration

Use `start.bat` on Windows or `./start.sh` in a POSIX shell. The studio runs in the foreground and mirrors live output to `runtime/logs/studio.log`. Keep its terminal open. Ctrl+C asks for `yes` before an interactive shutdown; answering No keeps the server running. Reopening the launcher follows the existing instance's log. Closing that viewer does not stop the original instance.

The backend loads a local `.env` without overriding existing environment variables. Configure `HF_TOKEN` there for Community-1 speaker diarization. The token and project media are excluded from Git; credentials are read at execution time rather than stored in job payloads. Install optional translation, Piper, diarization and separation requirements for their respective stages.

Auto-dub executes real processing stages. Missing model access, unresolved timing, failed separation, clipping, or failed render QA stop automatic export. The default mix retains the estimated instrumental stem at unity gain, without background ducking or whole-mix loudness normalization. Neural stems still require listening review. Reopening dialogue review keeps saved lines; it does not rerun translation.

See the [first-run guide](docs/QUICK_START.md) for the actual UI workflow and troubleshooting.

## Local models and configuration

Complete [core installation](docs/INSTALL.md) first. Commands below are Windows PowerShell examples from the repository root. They download optional packages/models; review [component terms](THIRD_PARTY_LICENSES/COMPONENTS.md) before proceeding. Do not install GPU variants blindly or change a working environment while a job is running.

### 1. Transcription and speaker analysis

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-optional.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-diarization.txt
```

Faster-Whisper fetches the selected model when transcription starts; Small is the initial profile. Community-1 requires your own [Hugging Face access acceptance](https://huggingface.co/pyannote/speaker-diarization-community-1). Set HF_TOKEN privately in .env. Package installation does not accept that agreement for you. The diarization profile pins PyTorch/TorchCodec; on Windows their decoder compatibility can require matching shared FFmpeg DLLs. Use System check and the actual error before changing binary libraries.

### 2. Isolated voice-cloning environment

```powershell
python -m venv runtime/clone-env
.\runtime\clone-env\Scripts\python.exe -m pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cpu
.\runtime\clone-env\Scripts\python.exe -m pip install -r requirements-cloning.txt
```

This explicit PyTorch example is **CPU**, not a promise of GPU inference. For supported NVIDIA hardware, use the [official PyTorch version/platform instructions](https://pytorch.org/get-started/previous-versions/) to select a compatible build for the pinned model environment. Do not layer incompatible CPU/CUDA/ROCm wheels together. Other GPU vendors/backends require independent validation. The app recognizes runtime/clone-env or an explicitly configured OPENDUB_CLONE_PYTHON.

OmniVoice model files download on first real synthesis. Its pretrained weights currently have non-commercial terms. Do not call this an unrestricted commercial voice engine. Import your 3–10 second authorized single-speaker WAV in **Voice library → Add your own recording**, provide its exact words, and listen to the actual generated audition before locking it.

### 3. Separation and checkpoint download

For a CPU starting profile:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-separation.txt
.\.venv\Scripts\audio-separator.exe --list_models
```

Select the exact permitted checkpoint for your task and review its own terms. The following download-only example matches the backend's local default; it is not a claim of checkpoint redistribution permission:

```powershell
.\.venv\Scripts\audio-separator.exe --download_model_only --model_filename UVR-MDX-NET-Inst_HQ_3.onnx --model_file_dir runtime/models/separation
```

Models may include companion YAML/config files. Keep the checkpoint and required companions together. The cloud recipe may select `vocals_mel_band_roformer.ckpt`; that is a different model, not an interchangeable renamed file. Acquire/review that exact selected model before cloud submission. Do not rename an unrelated checkpoint to bypass setup.

Local CUDA separation uses an isolated runtime/explicit OPENDUB_SEPARATION_PYTHON; the existing `scripts/bootstrap.py --separation-runtime` helper is for compatible **already installed Windows main/clone environments** and shares packages. It is not a portable fresh GPU installer. CPU setup above and detection of a physical GPU do not establish CUDA separation readiness.

### 4. Translation

Natural dialogue needs a configured provider. Set OPENDUB_LLM_API_KEY, OPENDUB_LLM_BASE_URL and OPENDUB_LLM_MODEL privately in .env for your supported OpenAI-compatible Chat Completions service, or use the implemented GEMINI_API_KEY path with its supported model configuration. Use the actual provider's currently available model and terms. The .env.example default is an example, not a universal model recommendation. Provider billing and availability are separate from the MIT application.

An optional offline translation package can be installed with:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-translation.txt
```

Argos language-pair packages must be acquired separately. Installing Argos alone does not enable the natural-dialogue provider or certify every Auto-Dub stage; review configured capabilities in the UI.

### 5. Run a short scene before a movie

```powershell
.\.venv\Scripts\python.exe scripts/check_dependencies.py
.\start.bat
```

1. Inspect **Setup & readiness** and **System check**. Core diagnostics alone do not prove all optional models are ready.
2. Create a short test project, upload an authorized scene, select source/target languages and **My computer**.
3. Start analysis. Review speaker turns and overlaps; correct mappings. Audition each authorized voice and lock the reviewed mapping.
4. Continue translation/synthesis. Resolve unclear words and timing flags; do not approve silent or mixed-speaker references to force completion.
5. Listen to the preview through speaker changes and background sound. Export only an actual verified render, then play the downloaded file.

Keep free RAM/disk adequate for the model and scene; readiness can legitimately block execution. Complete model installation, first-download inference and owner-recording end-to-end acceptance on a fresh computer remain release checks. No full-movie completion time or all-hardware support is promised.

## Kaggle setup and recovery

This experimental backend uses **your own account**. Local remains the default. Validate your own short scene before a full movie. Human listening/identity acceptance and actual provider GPU-withdrawal/replacement need separate verification. See the [media distribution policy](docs/DEMO.md). No account is guaranteed an accelerator or quota.

### Install and launch from a clone

Complete [core installation](docs/INSTALL.md). From the repository root, Windows PowerShell:

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

### Account, models and processing

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

### What downloads where?

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

This downloads files; it does not accept gated access conditions, create a public dataset, or prove inference works. For separator download commands and exact-model cautions, see [local model setup](docs/LOCAL_SETUP.md). Model licensing applies even when a user's cloud account pays for execution.

### Troubleshooting

- **SDK missing / Python too old:** use the main environment with Python 3.11+ and rerun the helper; do not replace working runtimes blindly.
- **Vault unavailable:** configure a supported native OS keyring. The app intentionally has no plaintext/browser-storage fallback. Do not put a token into the repository to bypass it.
- **Account mismatch / authentication failed:** confirm the selected username matches the account for the saved modern token or legacy key. The modern API token is supported; a legacy key is not mandatory.
- **Queued / quota / unavailable accelerator:** wait for actual provider status or choose local explicitly when ready. Do not promise an immediate replacement GPU.
- **Gated snapshot or separator missing:** finish the authorized local acquisition and exact-model configuration before submission; an API token alone is not model access.
- **Remote notebook still active after choosing local:** inspect/stop it in Kaggle yourself; detaching local monitoring is not remote cancellation.
- **Interrupted transfer or uncertain submission:** retain the same saved job and handle; resume/reconcile instead of creating duplicate notebooks. An unfinished batch may need replay.

Checked against the current application and official CLI authentication documentation on 16 October 2026. Current live quota/account requirements should be checked in the user's own Kaggle UI; this guide does not hardcode a free-GPU-hour promise.

## End-to-end workflow

1. **Prepare and launch.** Complete the installation above, then configure [local engines](docs/LOCAL_SETUP.md) or [personal Kaggle processing](docs/KAGGLE_SETUP.md). Run `start.bat` or `sh start.sh`, open the printed URL and resolve missing items under **Setup & readiness**.
2. **Create a project and upload.** Add your authorized source video, choose the source and target languages, and select Local or Kaggle. A fresh clone supplies no private model cache, reference voice bank or sample film.
3. **Analyze the source.** Run analysis and inspect the transcript, dialogue boundaries and proposed speakers. Correct missed words, overlapping speech and split/merged speakers before assigning voices. Automatic age/gender hints require review.
4. **Choose consistent character voices.** Open **Voice library → Add your own recording** for a clean single-speaker 3–10 second WAV with its exact transcript and permission confirmations. Review actual voice auditions and lock a suitable assignment for each character. No default movie voice pack is supplied.
5. **Translate and review.** Continue the configured translation stage, then check meaning, language and speakable duration. Hindi/English workflows are implemented; validate the chosen source/target pair yourself. Editing translated text or changing target language invalidates affected speech and downstream outputs so old audio is not reused silently.
6. **Generate and fit speech.** Continue synthesis using the reviewed character assignments. Inspect content and timing flags, listen to difficult lines and correct takes before proceeding. Timing adjustment cannot guarantee natural delivery or perfect lip synchronization.
7. **Preserve backgrounds and mix.** Continue separation/mixing and listen for source speech leakage, missing ambience and clipping. The default uses the estimated instrumental stem; neural separation cannot promise lossless recovery of background music/effects.
8. **Preview, render and download.** Play the actual dubbed preview, checking every character and scene transition. Resolve review/QA blocks and render the final video. Technical verification supplements listening acceptance. Follow saved progress after refresh/restart instead of submitting duplicate remote jobs.

Advanced exposes manual stage/model controls. If processing waits for credentials, model access, voice review or Kaggle allocation, resolve that specific state. See [detailed workflow and recovery](docs/ARCHITECTURE.md) and [first-run troubleshooting](docs/QUICK_START.md).

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Localhost does not open / Failed to fetch | Keep the launcher terminal open, use its printed port and inspect `runtime/logs/studio.log`. |
| Core UI opens but a stage is blocked | Run Setup & readiness; install the relevant optional engine and resolve model access. Core installation alone does not install all models. |
| Voice is silent, unclear or assigned to the wrong character | Review speaker mapping and the actual reference/audition; correct it and regenerate affected speech. |
| A line cannot fit its dialogue window | Review wording and timing flags; preserve meaning and avoid overlapping another character without review. |
| Source speech remains in the mix | Inspect the selected separation model and listen to its estimated background stem before export. |
| Kaggle is queued or submission is uncertain | Follow saved provider status and reconcile the same handle; do not create duplicate jobs. |
| Export is blocked | Resolve speech, timing, separation, clipping or render-QA failures; play the actual resulting file after completion. |

See [first-run troubleshooting](docs/QUICK_START.md), [FAQ](docs/FAQ.md) and [security reporting](SECURITY.md).

## Automated tests

Run the application regression suite and frontend checks using the [testing guide](docs/TESTING.md). It documents CI dependencies, commands, skipped optional integrations and the distinction between technical checks and real-media listening acceptance.

From the repository root, with the development environment and test dependencies installed:

```sh
python scripts/check_dependencies.py
python -m pytest -v -W error::DeprecationWarning -k "not feature_length"
node --test tests/test_studio_frontend.cjs tests/test_public_alpha_frontend.cjs tests/test_voice_browser.cjs
git diff --check
```

Use `.\.venv\Scripts\python.exe` on Windows or `.venv/bin/python` on POSIX if your environment is not activated. Waveform integration tests need the additional CPU PyTorch dependency documented in the testing guide. Optional models and feature-length processing are not certified by a core test pass.

## Repository structure

```text
OpenDub-Studio/
├── backend/                 FastAPI, analysis, speakers, dubbing, jobs and QA
├── web/                     Browser studio, voice review and brand assets
├── scripts/                 Launcher, diagnostics and advanced utilities
├── tests/                   Automated software tests
├── docs/                    Installation, usage, Kaggle and deployment guides
├── THIRD_PARTY_LICENSES/    Component/model terms and notices
├── .github/                 CI, contribution templates and code ownership
├── requirements*.txt        Core and optional dependency groups
├── pyproject.toml           Python package metadata
├── start.bat / start.sh     Local launch entry points
└── LICENSE                  MIT application-code license
```

Generated `runtime/` state, project recordings, voice references, credentials, model weights and exports remain outside source distribution. See [component responsibilities](docs/ARCHITECTURE.md).

## Contributing and credits

Anyone may propose code, documentation, tests, translations, accessibility improvements or bug reports in this public repository. See [how to contribute](CONTRIBUTING.md). The maintainer reviews changes, tests, security/privacy and licenses before merging; submitting a PR does not automatically merge it.

Created and maintained by **Suhaib · [@Skbindas](https://github.com/Skbindas)**, with **OpenAI Codex** AI-assisted development support. See [contributors and acknowledgments](CONTRIBUTORS.md) and [how maintainers review contributions](docs/MAINTAINER_REVIEW.md). GitHub's contributor graph reflects actual eligible commits; Codex is acknowledged as a tool.

## Privacy and project storage

No user recordings, voice references, rendered videos, transcript samples, training datasets or model weights are bundled in this repository. Automated tests are source code; do not add private recordings or generated exports as test fixtures. Use your own authorized inputs locally.

Removed projects retain their local files and project metadata in `runtime/deleted_projects` for recovery. Stop active processing before removing a project. Removal is an archive operation, not a disk-space purge. Archives contain local media and remain outside Git.

A clean source checkout contains no bundled movie recordings or voice catalog. Legacy voice names are aliases only when corresponding private entries exist; they are not a supplied voice pack. Silent, mixed or unreviewed references must not become automatic defaults.

Local processing uses installed engines; configured translation providers may receive dialogue text. Kaggle receives selected inputs only after explicit cloud choices. Keep tokens in private configuration/native credential storage. See [security](SECURITY.md) and [media policy](docs/DEMO.md).

## License

This repository's application code is released under the MIT License. Third-party dependencies and model weights may have separate licenses; see `THIRD_PARTY_LICENSES/` and each upstream project's license terms before redistribution or commercial use.

OmniVoice code and pretrained weights have distinct terms; the selected pretrained weights have non-commercial restrictions. Check [component and asset terms](THIRD_PARTY_LICENSES/COMPONENTS.md) before use or redistribution. The application license does not grant rights to films or voice performances.

## Brand assets

<img src="web/brand/cover-ai-v1.png" alt="OpenDub Studio speech and audio concept illustration" width="420">

The illustration is conceptual brand artwork. This repository and its releases do not bundle user media or before-and-after video samples.

The [brand pack](web/brand/review.html) contains actual ImageGen sources, editable SVG adaptations, workflow icons and [generation prompts](web/brand/PROVENANCE.json). Open `/assets/brand/review.html` on your running localhost to review it. Exact image-model version was not exposed.

[Release notes](docs/RELEASE_NOTES_ALPHA.md) · [Additional documentation](docs/QUICK_START.md)
