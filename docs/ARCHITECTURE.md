# Architecture and processing workflow

OpenDub Studio is a local browser application backed by FastAPI. Its core coordinates optional engines rather than shipping every model in the application install. See [local setup](LOCAL_SETUP.md) or [Kaggle setup](KAGGLE_SETUP.md) before selecting a compute path.

## Components

| Source | Responsibility |
| --- | --- |
| `web/` | Browser workspace, readiness, character/voice review, compute controls and progress |
| `backend/app.py` | HTTP API and project operations |
| `backend/db.py`, `backend/worker.py` | Persisted jobs and worker leases |
| `backend/auto_dub.py`, `backend/pipeline.py` | Stage orchestration, manifests and readiness/review gates |
| `backend/analysis_pipeline.py`, `backend/diarization.py` | Analysis and optional speaker diarization |
| `backend/speaker_review.py`, `backend/voice_profiles.py` | Speaker corrections and voice assignments |
| `backend/semantic_adaptation.py`, `backend/voice_cloning.py` | Translation/adaptation and optional speech generation |
| `backend/mixing.py`, `backend/rendering.py`, `backend/qa_engine.py` | Audio fitting/mix, export and technical checks |
| `backend/kaggle_*.py`, `scripts/kaggle_*.py` | Explicit remote submission, monitoring, retrieval and recovery |
| `scripts/launch.py`, `scripts/check_dependencies.py` | Local launcher and dependency diagnostics |

## End-to-end workflow

1. **Readiness:** install core dependencies, then configure the engines and credentials required by your chosen local or Kaggle path. The UI alone does not prove model readiness.
2. **Project and upload:** create a project, supply authorized video, choose source/target language and compute location. Keep original media outside Git.
3. **Analysis:** inspect transcription, dialogue boundaries and proposed speakers. Correct missing lines, overlapping turns and incorrectly split/merged speakers.
4. **Cast review:** assign and lock an appropriate voice for each reviewed character. Use a clean single-speaker reference and listen to its actual audition. A demographic hint is not proof of identity.
5. **Translation:** generate and review target-language dialogue for meaning and speakable duration. Changing text or target language invalidates affected generated speech and downstream outputs; unchanged dialogue can remain reusable.
6. **Speech and timing:** synthesize reviewed lines, inspect content/timing flags and fit takes within available windows. Do not shorten meaning or move dialogue into occupied time merely to pass a check.
7. **Background and mix:** separate/retain the estimated background and combine fitted dialogue. Listen for source-speech leakage, missing ambience, clipping and unnatural levels.
8. **Preview and export:** inspect the actual output, resolve blocked review/QA states and render. Decode/technical checks supplement human listening; they do not certify perfect voices or lip synchronization.

See [the UI quick start](QUICK_START.md) for user controls and troubleshooting.

## Persistence and recovery

SQLite job state and project artifacts persist independently of the browser tab. Local launch normally includes a worker; [server deployment](DEPLOYMENT-SERVER.md) explains separate workers. Recovery reuses validated persisted work, not a live GPU's memory. An interrupted remote batch may replay unfinished work. Reconcile an uncertain Kaggle submission before submitting another job.

Project removal archives local files in `runtime/deleted_projects`; it is not a disk-space purge. Stop active processing first. Keep `.env`, credentials, runtime media, model downloads, voice references and generated exports outside source commits.

## Repository structure

```text
backend/                 API, pipeline, engines, persistence and remote adapters
web/                     Browser UI and brand assets
scripts/                 Launch, diagnostics and advanced utilities
tests/                   Automated tests and generated test fixtures
docs/                    Installation, usage, deployment and contributor guides
THIRD_PARTY_LICENSES/    Component/model terms and notices
.github/                 CI, issue/PR templates and maintainer ownership
requirements*.txt        Core and optional engine dependency groups
start.bat / start.sh     Local entry points
runtime/                 Local generated state; not distributed source
LICENSE                  MIT application-code license
```

Advanced scripts are not promises of a fully automatic supported workflow. Prefer the documented UI and guides for first use.
