# Local models and your first dub

Complete [core installation](INSTALL.md) first. Commands below are Windows PowerShell examples from the repository root. They download optional packages/models; review [component terms](../THIRD_PARTY_LICENSES/COMPONENTS.md) before proceeding. Do not install GPU variants blindly or change a working environment while a job is running.

## 1. Transcription and speaker analysis

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-optional.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-diarization.txt
```

Faster-Whisper fetches the selected model when transcription starts; Small is the initial profile. Community-1 requires your own [Hugging Face access acceptance](https://huggingface.co/pyannote/speaker-diarization-community-1). Set HF_TOKEN privately in .env. Package installation does not accept that agreement for you. The diarization profile pins PyTorch/TorchCodec; on Windows their decoder compatibility can require matching shared FFmpeg DLLs. Use System check and the actual error before changing binary libraries.

## 2. Isolated voice-cloning environment

```powershell
python -m venv runtime/clone-env
.\runtime\clone-env\Scripts\python.exe -m pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cpu
.\runtime\clone-env\Scripts\python.exe -m pip install -r requirements-cloning.txt
```

This explicit PyTorch example is **CPU**, not a promise of GPU inference. For supported NVIDIA hardware, use the [official PyTorch version/platform instructions](https://pytorch.org/get-started/previous-versions/) to select a compatible build for the pinned model environment. Do not layer incompatible CPU/CUDA/ROCm wheels together. Other GPU vendors/backends require independent validation. The app recognizes runtime/clone-env or an explicitly configured OPENDUB_CLONE_PYTHON.

OmniVoice model files download on first real synthesis. Its pretrained weights currently have non-commercial terms. Do not call this an unrestricted commercial voice engine. Import your 3–10 second authorized single-speaker WAV in **Voice library → Add your own recording**, provide its exact words, and listen to the actual generated audition before locking it.

## 3. Separation and checkpoint download

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

## 4. Translation

Natural dialogue needs a configured provider. Set OPENDUB_LLM_API_KEY, OPENDUB_LLM_BASE_URL and OPENDUB_LLM_MODEL privately in .env for your supported OpenAI-compatible Chat Completions service, or use the implemented GEMINI_API_KEY path with its supported model configuration. Use the actual provider's currently available model and terms. The .env.example default is an example, not a universal model recommendation. Provider billing and availability are separate from the MIT application.

An optional offline translation package can be installed with:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-translation.txt
```

Argos language-pair packages must be acquired separately. Installing Argos alone does not enable the natural-dialogue provider or certify every Auto-Dub stage; review configured capabilities in the UI.

## 5. Run a short scene before a movie

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
