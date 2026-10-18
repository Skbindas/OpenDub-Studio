# Automated tests and verification

Install the [core dependencies](INSTALL.md) and make FFmpeg/FFprobe available on PATH. For the waveform integration tests, CI additionally installs CPU PyTorch. Use a compatible Python environment; CI currently runs Python 3.11 on Linux. Node.js is required for the JavaScript checks.

From the repository root with your virtual environment active:

```sh
python scripts/check_dependencies.py
python -m compileall -q backend scripts
python -m pytest -v -W error::DeprecationWarning -k "not feature_length"
node --test tests/test_studio_frontend.cjs tests/test_public_alpha_frontend.cjs tests/test_voice_browser.cjs
git diff --check
```

On Windows without activation, replace `python` with `.\.venv\Scripts\python.exe`; on POSIX use `.venv/bin/python`. To match CI's CPU waveform dependency in an isolated development environment:

```sh
python -m pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cpu
```

This is the CI test dependency, not a CUDA installation recipe. See [.github/workflows/ci.yml](../.github/workflows/ci.yml) for the authoritative test environment and frontend syntax checks. Optional model integration requires its own dependencies/access. Some tests skip unavailable optional capabilities; inspect the summary rather than assuming every model ran.

## What these checks establish

Tests exercise application contracts, pipeline state, API behavior, generated media fixtures and regression cases. They do not download a public user's private film, certify voice identity, establish human listening approval or guarantee full-movie throughput. The default CI command excludes feature-length tests; longer resource-intensive verification must be planned separately.

For a real-media acceptance check, use a short authorized scene, inspect speaker assignments and transcript coverage, listen to each character, check translated meaning and timing, then play the decoded final export. Do not commit that media, transcripts, reference voices, credentials or generated reports. Report the exact command and remaining limitations in your PR.

See [contributing](../CONTRIBUTING.md) and [maintainer review](MAINTAINER_REVIEW.md).
