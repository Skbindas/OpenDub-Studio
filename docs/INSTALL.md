# Clone, install and launch

The repository is public; cloning requires no GitHub token or owner-granted access. Do not add credentials to a clone URL. These commands assume a terminal opened in your chosen parent folder, with Git and Python already installed.

## Downloads and accounts

| Needed for | Install / obtain | Included in Git? |
| --- | --- | --- |
| Core studio | Git, Python, requirements.txt, FFmpeg/FFprobe on PATH | Application/requirements only |
| Local transcription | requirements-optional.txt; Faster-Whisper checkpoint downloads on first ASR | No weights |
| Local speakers | requirements-diarization.txt; your own Community-1 access and HF token | No gated weights/token |
| Local clone | Separate clone environment; requirements-cloning.txt; compatible PyTorch and OmniVoice checkpoint | No weights/voice pack |
| Local separation | requirements-separation.txt; selected checkpoint and any companion config | No weights/binaries |
| Hindi/English translation | Your configured supported provider/model and its credentials, or separately configured local service | No credentials |
| Kaggle execution | Python 3.11+, requirements-kaggle.txt via setup helper, your account/token and available accelerator/quota | SDK requirements/worker code only |
| Audition/demo | Your clean single-speaker recordings and source scene, with appropriate permissions | No private recordings |

Core Python requires 3.10+; Kaggle's SDK requires 3.11+. The current Windows core smoke used Python 3.13.7; CI uses Python 3.11. Optional neural packages have their own Python/OS/CUDA constraints. These are not blanket platform support certificates.

## Windows PowerShell: core installation

Install [Git](https://git-scm.com/downloads), [Python](https://www.python.org/downloads/) and an appropriate [FFmpeg build](https://ffmpeg.org/download.html). Make both ffmpeg and ffprobe available on PATH, then reopen the terminal. A winget alternative for the user to run is:

```powershell
winget install --exact --id Git.Git
winget install --exact --id Gyan.FFmpeg
```

Choose/install Python separately, then:

```powershell
git clone --depth 1 https://github.com/Skbindas/OpenDub-Studio.git
Set-Location OpenDub-Studio
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/check_dependencies.py
.\start.bat
```

Commands use the environment interpreter directly; PowerShell activation or execution-policy changes are unnecessary. `start.bat` can invoke the existing Windows bootstrap if .venv is missing. Core setup gives you the UI, not all neural engines. Open the localhost URL printed by the launcher; default is http://127.0.0.1:7860. Keep the terminal open.

## Linux / macOS: manual core path

Install Python, Git and FFmpeg/FFprobe using your OS's supported package manager. On Ubuntu/Debian, the usual prerequisite command is:

```sh
sudo apt-get update
sudo apt-get install git python3 python3-venv ffmpeg
git clone --depth 1 https://github.com/Skbindas/OpenDub-Studio.git
cd OpenDub-Studio
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/check_dependencies.py
sh start.sh
```

The current bootstrap.py installer targets Windows paths; use this manual path on POSIX. CI tests source on Linux, but end-to-end macOS/AMD/Intel neural acceleration is unverified. CPU/backend selection and optional-model compatibility need their own test. No install.sh exists.

## Private configuration

Only if .env does not already exist, copy .env.example to .env and edit it locally. Never overwrite a working configuration just to follow a guide. Add HF_TOKEN for your authorized Community-1 access and the supported translation-provider variables you intend to use. The backend loads .env on launch. Restart the launcher after configuration changes when no work is active.

Do not commit .env, paste tokens in issues or put credentials in command-line arguments. Models, recordings, job data and exports are outside ordinary source pushes. A configured third-party translation service may receive dialogue text; Kaggle receives explicitly selected worker inputs.

## Next steps

- [Local models and first dub](LOCAL_SETUP.md)
- [Kaggle setup and execution](KAGGLE_SETUP.md)
- [UI workflow / troubleshooting](QUICK_START.md)
- [Component and asset terms](../THIRD_PARTY_LICENSES/COMPONENTS.md)
- [Contributor workflow](../CONTRIBUTING.md)

Evidence: a new isolated core environment with freshly installed requirements served the UI, readiness/guide/casting endpoints and brand gallery without the developer's private voices. This is not a full neural-model installation or clean-machine dubbing certification.
