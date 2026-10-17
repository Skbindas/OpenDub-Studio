from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import os
import shutil
import subprocess
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from .atomic_files import replace_with_retry, publish_audio_revision
from .kaggle_tasks import raise_if_waiting

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

from .db import connect, get_job, get_project, init_db, list_projects, requeue_stale_jobs, request_job_cancel, job_cancel_requested, mark_job_cancelled
from .media import detect_scenes, extract_audio, transcribe, separate_dialogue_candidate
from .diarization import assign_speakers, diarize
from .dubbing import translate_transcript, synthesize_piper_segment
from .mixing import fit_audio, normalize_audio, mix_project, preserve_background_audio
from .rendering import mux_movie, cleanup_intermediates, verify_render_qa
from .system_diagnostics import collect_diagnostics, format_diagnostics_for_log
from .reliability import (
    check_disk_space,
    validate_media_file,
    generate_support_bundle,
    MIN_DISK_SPACE_UPLOAD,
    MIN_DISK_SPACE_SEPARATION,
    MIN_DISK_SPACE_TTS,
    MIN_DISK_SPACE_RENDER,
    InsufficientDiskSpaceError,
    InvalidMediaError,
)
from .analysis_pipeline import invalidate_downstream_artifacts
from .pipeline import (
    build_dialogue_manifest,
    find_dialogue_manifest_unit,
    update_dialogue_manifest_tts,
    update_dialogue_manifest_timing,
    update_dialogue_manifest_loudness,
    get_pipeline_state,
    update_dialogue_manifest_translation,
    update_timeline_character_identity,
    next_character_display_name,
    normalize_auto_character_display_names,
    merge_dialogue_manifest_state,
    validate_translation_manifest,
    evaluate_adaptation_budget,
    validate_adaptation_candidate,
    suggest_dialogue_adaptation,
)
from .semantic_adaptation import (
    SemanticAdaptationError,
    propose_semantic_adaptation,
    semantic_provider_configured,
    format_character_context,
)
from .voice_profiles import (
    VoiceProfileError,
    normalize_voice_profile,
    DEFAULT_VOICE_PROFILES,
    VoiceProfile,
    select_demographic_voice_profile,
)
from .voice_cloning import (
    get_movie_cast_voice_bank,
    assign_movie_cast_voices,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / os.getenv("OPENDUB_DATA_DIR", "runtime")
PROJECTS_ROOT = DATA_ROOT / "projects"
DB_PATH = DATA_ROOT / "opendub.sqlite3"
WEB_ROOT = ROOT / "web"
LAST_DIAGNOSTICS: dict[str, Any] | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup()
    yield


app = FastAPI(
    title="OpenDub Studio",
    version="0.1.0",
    lifespan=lifespan,
)
app.mount("/assets", StaticFiles(directory=WEB_ROOT), name="assets")
from .compute_routes import router as compute_router
app.include_router(compute_router)
from .voice_intake_routes import router as voice_intake_router
app.include_router(voice_intake_router)

class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    target_language: str = "Hindi"

class ProjectRename(BaseModel):
    name: str = Field(min_length=1, max_length=180)

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

def project_dir(project_id: str) -> Path:
    return PROJECTS_ROOT / project_id

def safe_name(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in " -_()." else "_" for c in name).strip()
    return cleaned or "movie"

def ffprobe(path: Path) -> dict[str, Any]:
    executable = shutil.which("ffprobe")
    if not executable:
        return {"available": False, "error": "ffprobe is not installed or not on PATH"}

    cmd = [
        executable, "-v", "error", "-show_format", "-show_streams",
        "-of", "json", str(path)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            return {"available": True, "error": result.stderr.strip() or "ffprobe failed"}
        data = json.loads(result.stdout or "{}")
        duration = data.get("format", {}).get("duration")
        return {
            "available": True,
            "duration_ms": round(float(duration) * 1000) if duration else None,
            "format": data.get("format", {}).get("format_name"),
            "size": int(data.get("format", {}).get("size", path.stat().st_size)),
            "streams": [
                {
                    "index": s.get("index"),
                    "codec_type": s.get("codec_type"),
                    "codec_name": s.get("codec_name"),
                    "channels": s.get("channels"),
                    "sample_rate": s.get("sample_rate"),
                    "width": s.get("width"),
                    "height": s.get("height"),
                    "language": (s.get("tags") or {}).get("language"),
                }
                for s in data.get("streams", [])
            ],
        }
    except (subprocess.SubprocessError, OSError, ValueError, json.JSONDecodeError) as exc:
        return {"available": True, "error": str(exc)}

def create_job(project_id: str, kind: str, payload: dict[str, Any] | None = None, *, job_id: str | None = None) -> str:
    from .compute_settings import read_settings
    if read_settings(project_dir(project_id))['provider']=='kaggle':
        if kind in {'voice_traits','overlap_recovery'}:
            raise HTTPException(409,'This optional research tool has no Kaggle adapter. Explicitly select local processing to use it.')
        from .kaggle_operations import remote_plan
        plan=remote_plan(project_dir(project_id))
        if not plan['admitted']:raise HTTPException(409,' '.join(plan['reasons']))
    job_id = job_id or str(uuid.uuid4())
    timestamp = now()
    with connect(DB_PATH) as conn:
        conn.execute(
            """INSERT INTO jobs
            (id, project_id, kind, status, progress, attempts, message, payload, created_at, updated_at)
            VALUES (?, ?, ?, 'queued', 0, 0, ?, ?, ?, ?)""",
            (
                job_id, project_id, kind, "Queued",
                json.dumps(payload or {}), timestamp, timestamp,
            ),
        )
        conn.execute("UPDATE projects SET status = 'processing', updated_at = ? WHERE id = ?", (timestamp, project_id))
        conn.commit()
    return job_id

async def run_analysis(job_id: str, project_id: str) -> None:
    """Run one analysis attempt; the durable worker owns retries and attempt counts."""
    with connect(DB_PATH) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return
        conn.execute(
            "UPDATE jobs SET status='running', message=?, updated_at=? WHERE id=?",
            ("Reading media metadata…", now(), job_id),
        )
        conn.commit()

    source = get_project(DB_PATH, project_id)
    if not source or not source.get("source_path"):
        error = "No source movie found."
        with connect(DB_PATH) as conn:
            conn.execute("UPDATE jobs SET status='failed', message=?, updated_at=? WHERE id=?", (error, now(), job_id))
            conn.execute("UPDATE projects SET status='failed', updated_at=? WHERE id=?", (now(), project_id))
            conn.commit()
        return

    try:
        media = ffprobe(ROOT / source["source_path"])
        if not media.get("available"):
            raise RuntimeError(media.get("error") or "FFmpeg/ffprobe is not available.")
        if media.get("error"):
            raise RuntimeError(media["error"])

        with connect(DB_PATH) as conn:
            conn.execute(
                "UPDATE jobs SET progress=?, message=?, payload=?, updated_at=? WHERE id=?",
                (0.85, "Media metadata analyzed.", json.dumps(media), now(), job_id),
            )
            conn.execute(
                "UPDATE projects SET duration_ms=?, source_size=?, status='analyzed', updated_at=? WHERE id=?",
                (media.get("duration_ms"), media.get("size") or source.get("source_size", 0), now(), project_id),
            )
            conn.execute(
                "UPDATE jobs SET status='completed', progress=1, message=?, updated_at=? WHERE id=?",
                ("Analysis complete. Deep dialogue/character analysis is the next pipeline phase.", now(), job_id),
            )
            conn.commit()
    except Exception as exc:
        with connect(DB_PATH) as conn:
            conn.execute("UPDATE jobs SET status='failed', message=?, updated_at=? WHERE id=?", (str(exc), now(), job_id))
            conn.execute("UPDATE projects SET status='failed', updated_at=? WHERE id=?", (now(), project_id))
            conn.commit()


def execute_media_stage(job_id: str, project_id: str, stage: str, payload: dict[str, Any] | None = None) -> None:
    """Execute a single durable media pipeline stage claimed by a worker."""
    payload = payload or {}
    base = project_dir(project_id)
    analysis = base / "analysis"
    analysis.mkdir(parents=True, exist_ok=True)
    item = get_project(DB_PATH, project_id)
    if not item or not item.get("source_path"):
        raise RuntimeError("Upload a source movie before running media stages.")
    source = (ROOT / item["source_path"]).resolve()
    if base.resolve() not in source.parents or not source.is_file():
        raise RuntimeError("Source movie is missing or outside the project folder.")
    with connect(DB_PATH) as conn:
        conn.execute("UPDATE jobs SET status='running',progress=0.05,message=?,updated_at=? WHERE id=?",
                     (f"Starting {stage.replace('_',' ')}…", now(), job_id))
        conn.commit()
    try:
        if stage == "audio_extract":
            result = extract_audio(source, analysis / "source_16k_mono.wav")
            (analysis / "audio_extract.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        elif stage == "scene_detect":
            result = detect_scenes(source, analysis / "scenes.json", float(payload.get("threshold", 0.35)))
        elif stage == "transcribe":
            audio = analysis / "source_16k_mono.wav"
            if not audio.is_file():
                extract_audio(source, audio)
            result = transcribe(audio, str(payload.get("model_size", "small")),
                                payload.get("language"), str(payload.get("device", "auto")))
            (analysis / "transcript.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        elif stage == "diarize":
            transcript_path = analysis / "transcript.json"
            if not transcript_path.is_file():
                raise RuntimeError("Transcribe the movie before diarization.")
            transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
            audio = analysis / "source_16k_mono.wav"
            if not audio.is_file():
                extract_audio(source, audio)
            result = diarize(audio, analysis / "diarization.json", os.getenv("HF_TOKEN"))
            aligned = assign_speakers(transcript, result)
            (analysis / "transcript.json").write_text(json.dumps(aligned, ensure_ascii=False, indent=2), encoding="utf-8")
        elif stage == "separate":
            from .background_preservation import extract_full_fidelity_audio
            audio = extract_full_fidelity_audio(source, analysis / "source_48k_stereo.wav")
            result = separate_dialogue_candidate(audio, analysis / "separation", payload.get("model_filename"))
            (analysis / "separation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            raise RuntimeError(f"Unsupported media stage: {stage}")
        with connect(DB_PATH) as conn:
            conn.execute("UPDATE jobs SET status='completed',progress=1,message=?,payload=?,updated_at=? WHERE id=?",
                         (f"{stage.replace('_',' ').title()} complete.", json.dumps(result, ensure_ascii=False), now(), job_id))
            conn.commit()
    except Exception as exc:
        with connect(DB_PATH) as conn:
            conn.execute("UPDATE jobs SET status='failed',message=?,updated_at=? WHERE id=?", (str(exc), now(), job_id))
            conn.commit()
        raise

def execute_full_analysis(job_id: str, project_id: str, payload: dict[str, Any] | None = None) -> None:
    """Worker entrypoint for resumable full-movie analysis."""
    from .analysis_pipeline import run_full_analysis
    item = get_project(DB_PATH, project_id)
    if not item or not item.get("source_path"):
        raise RuntimeError("Upload a source movie before running full analysis.")
    base = project_dir(project_id)
    source = (ROOT / item["source_path"]).resolve()
    if base.resolve() not in source.parents or not source.is_file():
        raise RuntimeError("Source movie is missing or outside the project folder.")
    media = ffprobe(source)
    if not media.get("available") or media.get("error"):
        raise RuntimeError(media.get("error") or "FFprobe is unavailable.")
    with connect(DB_PATH) as conn:
        conn.execute("UPDATE projects SET duration_ms=?,source_size=?,status='analyzing',updated_at=? WHERE id=?",
                     (media.get("duration_ms"),media.get("size") or item.get("source_size",0),now(),project_id))
        conn.commit()
    result = run_full_analysis(db_path=DB_PATH, project_id=project_id, job_id=job_id,
                               project_root=base, source=source, options=payload or {})
    # Automatic speaker -> character registration is a backend responsibility, not a browser-side requirement.
    diarization_path = base / "analysis" / "diarization.json"
    if diarization_path.is_file():
        try:
            sync_characters(project_id)
        except Exception as exc:
            print(f"[OpenDub characters] Automatic sync warning: {type(exc).__name__}: {exc}", flush=True)
    with connect(DB_PATH) as conn:
        conn.execute("UPDATE projects SET status='analyzed',updated_at=? WHERE id=?",(now(),project_id))
        conn.execute("UPDATE jobs SET status=CASE WHEN kind='auto_dub' THEN 'running' ELSE 'completed' END,progress=1,message=?,payload=?,updated_at=? WHERE id=?",
                     ("Full movie analysis complete.",json.dumps(result,ensure_ascii=False),now(),job_id))
        conn.commit()


@app.post("/api/projects/{project_id}/analyze/full")
def enqueue_full_analysis(project_id: str, model_size: str = "small",
                          device: str = "auto", language: str | None = None,
                          scene_threshold: float = 0.35, transcribe_vocals: bool = True,
                          separation_model: str = 'vocals_mel_band_roformer.ckpt') -> dict[str, str]:
    """Queue complete analysis and resume from persisted stage checkpoints."""
    item = get_project(DB_PATH, project_id)
    if not item or not item.get("source_path"):
        raise HTTPException(status_code=400, detail="Upload a movie first")
    payload = {"model_size": model_size, "device": device, "language": language,
               "scene_threshold": scene_threshold, 'transcribe_vocals':transcribe_vocals,
               'separation_model':separation_model}
    return {"job_id": create_job(project_id, "full_analysis", payload)}


@app.post("/api/projects/{project_id}/pipeline/{stage}")
def enqueue_media_stage(project_id: str, stage: str, model_size: str = "small",
                        device: str = "auto", language: str | None = None) -> dict[str, str]:
    allowed = {"audio_extract", "scene_detect", "transcribe", "diarize", "separate"}
    if stage not in allowed:
        raise HTTPException(status_code=404, detail="Unknown media pipeline stage")
    item = get_project(DB_PATH, project_id)
    if not item or not item.get("source_path"):
        raise HTTPException(status_code=400, detail="Upload a movie first")
    payload = {"model_size": model_size, "device": device, "language": language}
    return {"job_id": create_job(project_id, stage, payload)}


async def resume_queued_jobs() -> None:
    await asyncio.sleep(0.5)
    while True:
        with connect(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT j.id, j.project_id FROM jobs j "
                "WHERE j.status='queued' AND j.kind='media_analysis' ORDER BY j.created_at ASC"
            ).fetchall()
        if not rows:
            return
        for row in rows:
            await run_analysis(row["id"], row["project_id"])

async def startup() -> None:
    PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)
    init_db(DB_PATH)
    try:
        global LAST_DIAGNOSTICS
        LAST_DIAGNOSTICS = collect_diagnostics(DATA_ROOT, app.version)
        print("[OpenDub diagnostics] Startup system report:", flush=True)
        print(format_diagnostics_for_log(LAST_DIAGNOSTICS), flush=True)
    except Exception as exc:
        print(f"[OpenDub diagnostics] Startup check failed: {type(exc).__name__}: {exc}", flush=True)
    recovered = requeue_stale_jobs(DB_PATH, lease_seconds=int(os.getenv("OPENDUB_JOB_LEASE_SECONDS", "120")))
    if recovered:
        print(f"[OpenDub worker] Re-queued {recovered} stale job(s) after restart.")
    if os.getenv("OPENDUB_EMBED_WORKER", "1").lower() not in {"0", "false", "no"}:
        from .worker import start_embedded_worker
        start_embedded_worker(DB_PATH)
        from .kaggle_controller import start as start_kaggle_controller
        start_kaggle_controller(PROJECTS_ROOT)

class CharacterCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)


class CharacterUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    character_type: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=2000)
    voice_profile: dict[str, Any] | None = None
    review_required: bool | None = None
    casting_label: str | None = Field(default=None,max_length=80)
    voice_age_style: str | None = Field(default=None,max_length=40)

class TranslationRequest(BaseModel):
    conversational_hindi: bool = False
    target_language: str = Field(min_length=2, max_length=40)
    source_language: str | None = Field(default=None, max_length=40)

class ProsodyEditRequest(BaseModel):
    emotion: str | None = Field(default=None, max_length=60)
    delivery: str | None = Field(default=None, max_length=80)
    rate: float = Field(default=1.0, ge=0.5, le=2.0)
    pitch: float | None = Field(default=None, ge=-12, le=12)
    volume: float | None = Field(default=None, ge=0, le=2.0)
    review_required: bool = True

class TranslationEditRequest(BaseModel):
    translated_text: str = Field(min_length=1, max_length=5000)
    adaptation_mode: str = Field(default="manual_naturalization", max_length=60)
    tone: str = Field(default="neutral", max_length=60)
    delivery_intent: str = Field(default="faithful", max_length=120)
    timing_budget_sec: float | None = Field(default=None, gt=0, le=600)
    max_words: int | None = Field(default=None, gt=0, le=1000)

class AdaptationReviewRequest(BaseModel):
    adaptation_mode: str = Field(default="conservative_assist", pattern="^(conservative_assist|llm_semantic_assist)$")
    decision: str = Field(pattern="^(approve|reject)$")
    suggested_text: str = Field(min_length=1, max_length=5000)
    tone: str = Field(default="neutral", max_length=60)
    delivery_intent: str = Field(default="faithful", max_length=120)
    timing_budget_sec: float | None = Field(default=None, gt=0, le=600)
    max_words: int | None = Field(default=None, gt=0, le=1000)

class FitRequest(BaseModel):
    target_duration: float | None = Field(default=None, gt=0, le=600)
    max_speedup: float = Field(default=1.25, ge=1, le=2)
    max_slowdown: float = Field(default=0.82, ge=0.5, le=1)

class FitAllRequest(BaseModel):
    max_speedup: float = Field(default=1.25, ge=1.0, le=2.0)
    max_slowdown: float = Field(default=0.82, ge=0.5, le=1.0)
    normalize: bool = True
    target_lufs: float = Field(default=-16.0, ge=-30.0, le=-5.0)
    force: bool = False

class MixRequest(BaseModel):
    background_path: str | None = Field(default=None, max_length=2000)
    target_lufs: float = Field(default=-16, ge=-30, le=-5)
    duck_background: bool = False
    protect_dialogue_peaks: bool = False

class BackgroundPreservationRequest(BaseModel):
    separation_workers: int | None = Field(default=None, ge=1, le=256)
    mode: str = Field(default="separation", pattern="^(ducking|separation|user_stem)$")
    duck_db: float = Field(default=0.0, ge=-60.0, le=0.0)
    attack_ms: float = Field(default=50.0, ge=5.0, le=500.0)
    release_ms: float = Field(default=150.0, ge=20.0, le=1500.0)
    user_stem_path: str | None = Field(default=None, max_length=2000)
    model_filename: str | None = Field(default=None, max_length=500)

class RenderRequest(BaseModel):
    cleanup_intermediates: bool = True

class SynthesisRequest(BaseModel):
    voice_model_path: str | None = Field(default=None, min_length=1, max_length=1000)
    speaker_id: int | None = Field(default=None, ge=0, strict=True)

class SpeakerLink(BaseModel):
    speaker_id: str = Field(min_length=1, max_length=120)
    character_id: str = Field(min_length=1, max_length=120)

def character_paths(project_id: str) -> tuple[Path, Path]:
    base = project_dir(project_id)
    return base / "characters" / "registry.json", base / "analysis" / "diarization.json"

def read_character_registry(project_id: str) -> dict[str, Any]:
    path, _ = character_paths(project_id)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"project_id": project_id, "characters": [], "speaker_links": {}, "version": 1}

def safe_replace(source: Path, target: Path) -> None:
    import time
    for attempt in range(5):
        try:
            source.replace(target)
            return
        except (PermissionError, OSError):
            if attempt == 4:
                shutil.copyfile(source, target)
                try:
                    source.unlink(missing_ok=True)
                except Exception:
                    pass
                return
            time.sleep(0.05 * (attempt + 1))

def write_character_registry(project_id: str, registry: dict[str, Any]) -> None:
    path, _ = character_paths(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    safe_replace(temp, path)


def reset_project_analysis_state(project_id: str, *, reset_characters: bool = False) -> None:
    """Clear stale analysis/downstream artifacts while preserving source media."""
    base = project_dir(project_id)
    invalidate_downstream_artifacts(base, preserve_characters=not reset_characters)
    (base / "auto_dub_status.json").unlink(missing_ok=True)
    (base / "work_progress.json").unlink(missing_ok=True)
    if reset_characters:
        write_character_registry(project_id, {
            "project_id": project_id,
            "characters": [],
            "speaker_links": {},
            "version": 1,
        })


def refresh_dialogue_manifest(project_id: str) -> dict[str, Any]:
    """Rebuild the source-timeline master dialogue manifest after identity changes."""
    base = project_dir(project_id)
    analysis = base / "analysis"
    transcript_path = analysis / "transcript.json"
    scenes_path = analysis / "scenes.json"
    if not transcript_path.exists():
        return {"status": "blocked", "reason": "Transcript not available."}
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    scenes = json.loads(scenes_path.read_text(encoding="utf-8")) if scenes_path.exists() else []
    registry = read_character_registry(project_id)
    item = get_project(DB_PATH, project_id) or {}
    previous_path = analysis / "dialogue_manifest.json"
    previous_manifest = None
    if previous_path.exists():
        try:
            previous_manifest = json.loads(previous_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous_manifest = None
    manifest = build_dialogue_manifest(
        project_id=project_id,
        transcript=transcript,
        scenes=scenes,
        registry=registry,
        output_path=previous_path,
        target_language=item.get("target_language"),
    )
    if previous_manifest:
        manifest = merge_dialogue_manifest_state(manifest, previous_manifest)
        temp = previous_path.with_suffix(previous_path.suffix + ".tmp")
        temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        replace_with_retry(temp, previous_path)
    translated_path=analysis/'translated_transcript.json'
    if translated_path.exists() and (analysis/'dub_timing_overrides.json').exists():
        from .reviewed_dub_timing import replay_reviewed_windows
        translated=json.loads(translated_path.read_text(encoding='utf-8'))
        replay_reviewed_windows(base,manifest,translated.get('segments',[]))
        persist_dialogue_manifest(previous_path,manifest)
        translated_path.write_text(json.dumps(translated,ensure_ascii=False,indent=2),encoding='utf-8')
    return {"status": "completed", "segment_count": manifest["segment_count"], "path": "analysis/dialogue_manifest.json"}

@app.get("/api/projects/{project_id}/characters")
def list_characters(project_id: str) -> dict[str, Any]:
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return read_character_registry(project_id)

@app.post("/api/projects/{project_id}/characters/sync")
def sync_characters(project_id: str) -> dict[str, Any]:
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    _, diarization_path = character_paths(project_id)
    if not diarization_path.exists():
        manifest_path = project_dir(project_id) / "analysis" / "analysis_manifest.json"
        manifest: dict[str, Any] = {}
        if manifest_path.exists():
            try:
                manifest = read_json_safe(manifest_path)
            except (OSError, json.JSONDecodeError):
                manifest = {}
        stage = (manifest.get("stages") or {}).get("speaker_diarization") or {}
        if stage.get("status") == "skipped":
            error = str(stage.get("error") or "")
            setup_required = "Hugging Face" in error or "HF_TOKEN" in error or "authorized" in error or "gated" in error
            return {"project_id": project_id, "characters": [], "speaker_links": {}, "version": 1,
                    "status": "setup_required" if setup_required else "skipped",
                    "notice": ("Hugging Face access to pyannote Community-1 is not authorized yet. "
                               "Accept the model conditions while signed in to the same Hugging Face account used by HF_TOKEN, then rerun analysis."
                               if setup_required else "Speaker diarization was skipped because it is not configured."),
                    "model_url": "https://huggingface.co/pyannote/speaker-diarization-community-1",
                    "stage_error": error if setup_required else None}
        raise HTTPException(status_code=409, detail="Run speaker diarization first")
    diar = json.loads(diarization_path.read_text(encoding="utf-8"))
    registry = read_character_registry(project_id)
    registry.setdefault("characters", [])
    registry.setdefault("speaker_links", {})
    transcript_path = project_dir(project_id) / "analysis" / "transcript.json"
    transcript = {}
    if transcript_path.exists():
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    segments = transcript.get("segments", []) if isinstance(transcript, dict) else []
    stats: dict[str, dict[str, float]] = {}
    for segment in segments:
        sid = str(segment.get("speaker_id") or "")
        if not sid:
            continue
        bucket = stats.setdefault(sid, {"count": 0.0, "duration": 0.0, "confidence_sum": 0.0, "confidence_count": 0.0})
        bucket["count"] += 1
        bucket["duration"] += max(0.0, float(segment.get("end", 0)) - float(segment.get("start", 0)))
        confidence = segment.get("speaker_confidence")
        if confidence is not None:
            bucket["confidence_sum"] += float(confidence)
            bucket["confidence_count"] += 1
    active_speakers = {str(row.get("speaker_id")) for row in diar.get("speakers", []) if row.get("speaker_id")}
    registry["speaker_links"] = {sid: cid for sid, cid in registry["speaker_links"].items() if sid in active_speakers}
    registry["characters"] = [character for character in registry["characters"]
                              if character.get("source_speaker_id") in active_speakers
                              or not character.get("auto_display_name", False)
                              or (character.get("voice_profile") or {}).get("provider")]
    normalize_auto_character_display_names(registry["characters"])
    by_speaker = {str(character.get("source_speaker_id")): character for character in registry["characters"] if character.get("source_speaker_id")}
    for sid in sorted(active_speakers):
        linked_id=registry['speaker_links'].get(sid)
        character=next((c for c in registry['characters'] if c['character_id']==linked_id),None) if linked_id else None
        character = character or by_speaker.get(sid)
        if character is None:
            character = {"character_id": str(uuid.uuid4()), "display_name": next_character_display_name(registry["characters"]),
                         "auto_display_name": True, "character_type": "unknown", "source_speaker_id": sid,
                         "aliases": [], "notes": "", "auto_notes": True,
                         "voice_profile": {"status": "not_configured", "reference_audio": None, "embedding_path": None, "engine": None, "settings": {}},
                         "review_required": True, "created_at": now(), "updated_at": now()}
            registry["characters"].append(character)
            by_speaker[sid] = character
        registry["speaker_links"][sid] = character["character_id"]
        stat = stats.get(sid, {})
        count = int(stat.get("count", 0))
        duration = float(stat.get("duration", 0.0))
        conf_count = int(stat.get("confidence_count", 0))
        avg_conf = float(stat.get("confidence_sum", 0.0)) / conf_count if conf_count else None
        auto_note = "Auto-detected speaker cluster " + sid + ". " + str(count) + " dialogue segment" + ("s" if count != 1 else "") + ", " + f"{duration:.1f}" + "s total speech"
        if avg_conf is not None:
            auto_note += ", average speaker confidence " + str(round(avg_conf * 100)) + "%"
        auto_note += ". Review identity before voice assignment."
        if not character.get("notes") or character.get("auto_notes", False):
            character["notes"] = auto_note
            character["auto_notes"] = True
        character["updated_at"] = now()
    write_character_registry(project_id, registry)
    update_timeline_character_identity(timeline_path=project_dir(project_id) / "analysis" / "timeline.json", registry=registry)
    if transcript_path.exists():
        for segment in transcript.get("segments", []):
            sid = str(segment.get("speaker_id") or "")
            character_id = registry["speaker_links"].get(sid)
            segment["character_id"] = character_id
            character = next((row for row in registry["characters"] if row.get("character_id") == character_id), None)
            segment["character_name"] = (character or {}).get("display_name")
        transcript_path.write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")
    refresh_dialogue_manifest(project_id)
    return registry

@app.post("/api/projects/{project_id}/characters")
def create_character(project_id: str, body: CharacterCreate) -> dict[str, Any]:
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    name = body.display_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Character name cannot be blank")
    registry = read_character_registry(project_id)
    item = {"character_id": str(uuid.uuid4()), "display_name": name,
            "auto_display_name": False, "character_type": "unknown", "source_speaker_id": None,
            "aliases": [], "notes": "", "auto_notes": False, "voice_profile": {},
            "review_required": True, "created_at": now(), "updated_at": now()}
    registry.setdefault("characters", []).append(item)
    write_character_registry(project_id, registry)
    return item


@app.get('/api/projects/{project_id}/speaker-review')
def get_speaker_review(project_id: str):
    if not get_project(DB_PATH,project_id):raise HTTPException(404,'Project not found')
    from .speaker_review import review_state
    return review_state(project_dir(project_id),read_character_registry(project_id))


_CASTING_CACHE={}
_CASTING_LOCK=threading.Lock()


class SpeakerToolRequest(BaseModel):
    task: str = Field(pattern='^(voice_traits|overlap_recovery)$')
    research_mode: bool = False
    event_index: int | None = Field(default=None,ge=0)


@app.post('/api/projects/{project_id}/speaker-tools')
def enqueue_speaker_tool(project_id: str,body: SpeakerToolRequest):
    if not get_project(DB_PATH,project_id):raise HTTPException(404,'Project not found')
    require_idle_speaker_review(project_id)
    base=project_dir(project_id)
    if not (base/'analysis/vocals_16k_mono.wav').exists():raise HTTPException(409,'Complete vocal-first analysis first.')
    if body.task=='voice_traits':
        if not body.research_mode:raise HTTPException(409,'Enable explicit non-commercial research mode for this optional model.')
        if not any((ROOT/'runtime/speaker-tools/models/voice-traits-research').rglob('*.onnx')):raise HTTPException(409,'Voice-trait research model download/setup is pending; current voices are retained.')
    else:
        from .speaker_tools import validate_overlap_request
        review=get_speaker_review(project_id)
        if body.event_index is None or not 0<=body.event_index<len(review['overlap_events']):raise HTTPException(409,'Select a detected overlap region first.')
        try:validate_overlap_request(review['overlap_events'][body.event_index],(get_project(DB_PATH,project_id).get('duration_ms') or 0)/1000)
        except ValueError as exc:raise HTTPException(409,str(exc)) from exc
    plan=project_processing_plan(project_id,workload='speech')
    if not plan['admitted']:raise HTTPException(409,'Speaker tool paused: '+' '.join(plan['reasons']))
    job=create_job(project_id,body.task,body.model_dump())
    return {'job_id':job,'status':'queued'}


@app.get('/api/projects/{project_id}/speaker-tools/overlaps/{index}/channels/{channel}')
def recovered_overlap_audio(project_id: str,index: int,channel: int):
    if not get_project(DB_PATH,project_id):raise HTTPException(404,'Project not found')
    from .speaker_review import read
    from .speaker_tools import current_tool_result
    base=project_dir(project_id);result=current_tool_result(base,read(base/'analysis/overlap_candidates.json',{}))
    event=result.get('events',{}).get(str(index));channels=(event or {}).get('channels',[])
    if not 0<=channel<len(channels):raise HTTPException(404,'Recovered channel not found')
    path=Path(channels[channel]['audio']).resolve()
    if base.resolve() not in path.parents or not path.is_file():raise HTTPException(404,'Recovered audio unavailable')
    return FileResponse(path,media_type='audio/wav')


@app.get('/api/casting-voices')
def casting_voices():
    with _CASTING_LOCK:
        return _casting_voices_uncached()


def _casting_voices_uncached():
    import hashlib
    from .voice_bank_quality import fingerprint
    paths=sorted((DATA_ROOT/'voice-bank-audit/records').glob('*.json'))
    version=(str(DATA_ROOT),tuple((p.name,p.stat().st_mtime_ns,p.stat().st_size) for p in paths))
    if _CASTING_CACHE.get('version')==version:return _CASTING_CACHE['result']
    from .automatic_dialogue import automatic_reference_candidates
    measured={v['voice_id']:v for v in automatic_reference_candidates(DATA_ROOT)}
    choices=[]
    for voice in get_movie_cast_voice_bank():
        vid=voice['character_id'];path=DATA_ROOT/'voice-bank-audit/records'/f'{vid}.json'
        if not path.exists():continue
        record=json.loads(path.read_text(encoding='utf-8'));reference=Path(record.get('reference_path',''))
        if not reference.is_file():continue
        from .voice_catalog import reference_blockers
        valid=(not reference_blockers(record) and record.get('audit',{}).get('status')=='single_speaker_candidate'
               and bool(record.get('audit',{}).get('speech_text'))
               and 3<=float(record.get('metrics',{}).get('duration_sec',0))<=10.01
               and fingerprint(reference)==record.get('sha256'))
        if valid:
            clone=record.get('clone',{});output=Path(clone.get('file',''))
            has_clone=(clone.get('status')=='completed' and clone.get('reference_conditioned')
                       and clone.get('reference_sha256')==record['sha256'] and output.is_file()
                       and fingerprint(output)==clone.get('output_sha256'))
            choices.append({'voice_id':vid,'label':voice.get('display_name',voice.get('character_name',vid)),
                                  'reference_text_sha256':hashlib.sha256(record['audit']['speech_text'].encode()).hexdigest(),
                                  'reference_sha256':record['sha256'],'audition_url':f'/api/voices/{vid}/clone-preview' if has_clone else f'/api/voices/{vid}/preview',
                                  'audition_kind':'generated_clone' if has_clone else 'reference_only',
                                  'audition_accepted':bool(voice.get('audition_accepted')),
                                  'source_identity_reviewed':bool(record.get('review',{}).get('identity_confirmed')),
                                  'vocal_type':measured.get(vid,{}).get('vocal_type','unknown'),
                                  'pitch_median_hz':measured.get(vid,{}).get('pitch_median_hz')})
    result={'voices':choices,'notice':'Technical reference candidates; voice-bank identity/quality review flags remain separate.'}
    _CASTING_CACHE.update(version=version,result=result)
    return result


class VoiceLockRequest(BaseModel):
    confirmed: bool = False
    reviewed_by: str = Field(default='user',pattern='^(user|assistant_review|automated_test)$')
    voice_id: str | None = Field(default=None,max_length=180)
    casting_label: str | None = Field(default=None,max_length=80)
    voice_age_style: str | None = Field(default=None,max_length=40)


def require_idle_speaker_review(project_id):
    with connect(DB_PATH) as conn:
        active=conn.execute("SELECT id FROM jobs WHERE project_id=? AND status IN ('queued','claimed','running','retrying') LIMIT 1",(project_id,)).fetchone()
    if active:raise HTTPException(409,'Wait for analysis to pause, or cancel processing, before changing identities or locked voices.')


def require_reviewed_new_speaker_foundation(project_id):
    from .speaker_review import read,review_state
    base=project_dir(project_id)
    if read(base/'analysis/diarization.json',{}).get('schema_version',0)<3:return
    review=review_state(base,read_character_registry(project_id))
    if not review['ready_for_dubbing']:raise HTTPException(409,'Speaker review required: '+' '.join(review['blocking']))


@app.post('/api/projects/{project_id}/characters/{character_id}/voice-lock')
def confirm_character_voice(project_id: str,character_id: str,body: VoiceLockRequest):
    if not get_project(DB_PATH,project_id):raise HTTPException(404,'Project not found')
    require_idle_speaker_review(project_id)
    from .speaker_review import lock_voice
    registry=read_character_registry(project_id)
    item=next((x for x in registry['characters'] if x['character_id']==character_id),None)
    if not item:raise HTTPException(404,'Character not found')
    if body.voice_id:
        choice=next((v for v in casting_voices()['voices'] if v['voice_id']==body.voice_id),None)
        if not choice:raise HTTPException(409,'Reference is unavailable or its evidence changed.')
        from .voice_bank_quality import fingerprint
        evidence=json.loads((DATA_ROOT/'voice-bank-audit/records'/f'{body.voice_id}.json').read_text(encoding='utf-8'))
        if fingerprint(Path(evidence['reference_path']))!=choice['reference_sha256']:raise HTTPException(409,'Reference changed; refresh voice candidates.')
        item={**item,'voice_profile':{'provider':'omnivoice','voice_id':choice['voice_id'],'language':'hi',
                                      'reference_text_sha256':choice['reference_text_sha256'],
                                      'reference_sha256':choice['reference_sha256'],'selection_method':'automatic_audio_reference',
                                      'casting_decision':'user','identity_status':'user_selected_cast_not_bank_identity_certification',
                                      'settings':{'rate':1,'pitch_semitones':0,'theatrical_shaping':False}}}
    if body.casting_label is not None:item={**item,'casting_label':body.casting_label}
    if body.voice_age_style is not None:
        if body.voice_age_style not in {'unknown','childlike','young','adult','mature','elder','other'}:raise HTTPException(422,'Invalid voice age style')
        item={**item,'voice_age_style':body.voice_age_style}
    try:locked=lock_voice(item,body.confirmed,body.reviewed_by)
    except ValueError as exc:raise HTTPException(409,str(exc)) from exc
    registry['characters']=[locked if c['character_id']==character_id else c for c in registry['characters']]
    write_character_registry(project_id,registry);refresh_dialogue_manifest(project_id)
    return locked


@app.get('/api/projects/{project_id}/characters/{character_id}/source-sample')
def character_source_sample(project_id: str,character_id: str,index: int=0):
    data=get_speaker_review(project_id);card=next((c for c in data['cards'] if c['character_id']==character_id),None)
    if not card or not 0<=index<len(card['source_windows']):raise HTTPException(404,'No clean source window; review or reanalyse speaker evidence.')
    return speaker_excerpt(project_id,card['source_windows'][index])


def speaker_excerpt(project_id,window):
    base=project_dir(project_id);audio=base/'analysis/vocals_16k_mono.wav'
    if not audio.exists():raise HTTPException(404,'Separated dialogue audio is unavailable.')
    from .voice_bank_quality import fingerprint
    import hashlib
    key=hashlib.sha256((fingerprint(audio)+json.dumps(window,sort_keys=True)).encode()).hexdigest()[:24]
    directory=base/'analysis/source-samples';directory.mkdir(exist_ok=True);output=directory/(key+'.wav')
    if not output.exists():
        temporary=output.with_name(output.stem+'.'+uuid.uuid4().hex+'.partial.wav')
        result=subprocess.run(['ffmpeg','-v','error','-y','-threads','1','-ss',str(window['start']),'-i',str(audio),
                               '-t',str(window['end']-window['start']),'-ac','1','-ar','16000','-c:a','pcm_s16le',str(temporary)],capture_output=True,timeout=30)
        if result.returncode:raise HTTPException(500,'Source excerpt could not be decoded.')
        safe_replace(temporary,output)
    return FileResponse(output,media_type='audio/wav')


class SpeakerTurnReview(BaseModel):
    speaker_id: str = Field(min_length=1,max_length=120)
    source_text: str | None = Field(default=None,min_length=1,max_length=5000)
    reviewed_by: str = Field(default='user',pattern='^(user|assistant_review|automated_test)$')


@app.post('/api/projects/{project_id}/speaker-review/turns/{index}')
def review_speaker_turn(project_id: str,index: int,body: SpeakerTurnReview):
    require_idle_speaker_review(project_id)
    data=get_speaker_review(project_id);base=project_dir(project_id)
    path=base/'analysis/transcript.json';transcript=json.loads(path.read_text(encoding='utf-8'))
    diar=json.loads((base/'analysis/diarization.json').read_text(encoding='utf-8'))
    if body.speaker_id not in {s['speaker_id'] for s in diar.get('speakers',[])}:raise HTTPException(422,'Choose a detected speaker')
    if not 0<=index<len(transcript['segments']):raise HTTPException(404,'Turn not found')
    from .analysis_pipeline import _atomic_json
    history=base/'analysis/speaker-review-history';history.mkdir(exist_ok=True)
    _atomic_json(history/(str(time.time_ns())+'.json'),transcript)
    row=transcript['segments'][index]
    row.update(speaker_id=body.speaker_id,speaker_review_required=False,speaker_review_reason=None,speaker_assignment_method=body.reviewed_by+'_confirmed')
    if body.source_text is not None and body.source_text.strip()!=row.get('text','').strip():
        row.update(text=body.source_text.strip(),words=[],timing_method='user_segment_timestamps',transcription_method='user_correction')
    for word in row.get('words',[]):word.update(speaker_id=body.speaker_id,speaker_review_required=False,speaker_review_reason=None)
    _atomic_json(path,transcript);sync_characters(project_id);invalidate_after_source_review(project_id)
    return get_speaker_review(project_id)


def invalidate_after_source_review(project_id):
    """Keep old output files; invalidate their resumable status after word/identity edits."""
    from .auto_dub import read_status,save_status
    from .speaker_review import read
    from .analysis_pipeline import _atomic_json,_build_timeline
    base=project_dir(project_id)
    transcript=read(base/'analysis/transcript.json',{})
    timeline=read(base/'analysis/timeline.json',{})
    reviewed=_build_timeline(transcript,read(base/'analysis/scenes.json',[]),base/'analysis/separation.json')
    timeline.update(reviewed)
    diar=read(base/'analysis/diarization.json',{})
    timeline['speaker_evidence']={k:diar.get(k) for k in ('schema_version','raw_overlap_available','overlap_events','coverage','identity_source_sha256')}
    _atomic_json(base/'analysis/timeline.json',timeline)
    update_timeline_character_identity(timeline_path=base/'analysis/timeline.json',registry=read_character_registry(project_id))
    base=project_dir(project_id);status=read_status(base)
    if not status:return
    for step in status.get('stages',[])[2:]:step.update(status='pending',percent=0)
    status.update(status='awaiting_review',auto_download_ready=False,rendered_video_url=None,
                  current_stage_label='Source dialogue changed; review cast, then continue from translation.')
    save_status(base,status)
    with connect(DB_PATH) as conn:
        conn.execute("UPDATE projects SET status='awaiting_review',updated_at=? WHERE id=?",(now(),project_id))


class ManualSourceDialogue(BaseModel):
    speaker_id: str = Field(min_length=1,max_length=120)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(min_length=1,max_length=5000)


@app.post('/api/projects/{project_id}/speaker-review/dialogue')
def add_missing_source_dialogue(project_id: str,body: ManualSourceDialogue):
    require_idle_speaker_review(project_id);data=get_speaker_review(project_id);base=project_dir(project_id)
    from .speaker_review import read
    from .analysis_pipeline import _atomic_json
    diar=read(base/'analysis/diarization.json',{});duration=(get_project(DB_PATH,project_id).get('duration_ms') or 0)/1000
    if body.end<=body.start or (duration and body.end>duration+.01):raise HTTPException(422,'Choose a valid source-time window inside the movie.')
    if body.speaker_id not in {s['speaker_id'] for s in diar.get('speakers',[])}:raise HTTPException(422,'Choose a detected/manual speaker first.')
    if not body.text.strip():raise HTTPException(422,'Enter the actual source-language words you heard.')
    path=base/'analysis/transcript.json';transcript=read(path,{})
    if not isinstance(transcript.get('segments'),list):raise HTTPException(409,'Analyse the source first.')
    history=base/'analysis/speaker-review-history';history.mkdir(exist_ok=True)
    _atomic_json(history/(str(time.time_ns())+'.json'),transcript)
    transcript['segments'].append({'start':body.start,'end':body.end,'text':body.text.strip(),'words':[],
        'speaker_id':body.speaker_id,'speaker_review_required':False,'speaker_assignment_method':'user_confirmed',
        'timing_method':'user_segment_timestamps','transcription_method':'user_entered_missing_speech'})
    transcript['segments'].sort(key=lambda r:(r['start'],r['end']))
    _atomic_json(path,transcript);sync_characters(project_id);invalidate_after_source_review(project_id)
    return get_speaker_review(project_id)


class ManualIdentitySplit(BaseModel):
    confirmed: bool = False
    reviewed_by: str = Field(default='user',pattern='^(user|assistant_review|automated_test)$')


class SpeakerDisposition(BaseModel):
    confirmed: bool = False
    reviewed_by: str = Field(default='user',pattern='^(user|assistant_review|automated_test)$')
    category: str = Field(pattern='^(music_or_singing|non_speech|dialogue)$')


@app.post('/api/projects/{project_id}/speaker-review/speakers/{speaker_id}/disposition')
def review_non_dialogue_cluster(project_id: str,speaker_id: str,body: SpeakerDisposition):
    require_idle_speaker_review(project_id);data=get_speaker_review(project_id);base=project_dir(project_id)
    if not body.confirmed:raise HTTPException(409,'Listen to this cluster and confirm its source role first.')
    from .speaker_review import read,overlap_evidence_hash
    from .analysis_pipeline import _atomic_json
    diar=read(base/'analysis/diarization.json',{})
    if speaker_id not in {s['speaker_id'] for s in diar.get('speakers',[])}:raise HTTPException(404,'Speaker not found')
    if body.category!='dialogue' and any(r.get('speaker_id')==speaker_id and r.get('text') for r in data['turns']):
        raise HTTPException(409,'This cluster owns transcript words. Correct their attribution before excluding non-dialogue; speech cannot be hidden.')
    path=base/'analysis/speaker_dispositions.json';decision=read(path,{})
    evidence=overlap_evidence_hash(diar)
    if decision.get('evidence_sha256')!=evidence:decision={'evidence_sha256':evidence,'speakers':{}}
    decision['speakers'][speaker_id]={'category':body.category,'confirmed':True,'confirmed_by':body.reviewed_by,'confirmed_at':now()}
    _atomic_json(path,decision)
    return get_speaker_review(project_id)


@app.post('/api/projects/{project_id}/speaker-review/turns/{index}/split')
def split_speaker_identity(project_id: str,index: int,body: ManualIdentitySplit):
    require_idle_speaker_review(project_id);data=get_speaker_review(project_id);base=project_dir(project_id)
    if not body.confirmed:raise HTTPException(409,'Confirm that this turn belongs to a different speaking identity after listening.')
    if not 0<=index<len(data['turns']):raise HTTPException(404,'Turn not found')
    row=data['turns'][index]
    if not row.get('speaker_id'):raise HTTPException(409,'Choose the current detected cluster before splitting it.')
    from .speaker_review import read
    from .speaker_corrections import apply_identity_overrides
    from .analysis_pipeline import _atomic_json
    path=base/'analysis/diarization.json';diar=read(path,{})
    history=base/'analysis/speaker-review-history';history.mkdir(exist_ok=True)
    _atomic_json(history/(str(time.time_ns())+'-diarization.json'),diar)
    overrides_path=base/'characters/speaker_overrides.json';overrides=read(overrides_path,{})
    if overrides.get('source_sha256')!=diar.get('identity_source_sha256'):
        overrides={'source_sha256':diar.get('identity_source_sha256'),'overrides':[]}
    new='MANUAL_'+uuid.uuid4().hex[:12]
    overrides['overrides'].append({'start':row['start'],'end':row['end'],'from_speaker':row['speaker_id'],'speaker_id':new,
        'confirmed_at':now(),'confirmed_by':body.reviewed_by})
    adjusted=apply_identity_overrides(diar,overrides)
    if new not in {s['speaker_id'] for s in adjusted.get('speakers',[])}:raise HTTPException(409,'No detected speech intersects this turn; review source timestamps first.')
    _atomic_json(overrides_path,overrides);_atomic_json(path,adjusted)
    return review_speaker_turn(project_id,index,SpeakerTurnReview(speaker_id=new,reviewed_by=body.reviewed_by))


@app.get('/api/projects/{project_id}/speaker-review/turns/{index}/sample')
def turn_source_sample(project_id: str,index: int):
    data=get_speaker_review(project_id)
    if not 0<=index<len(data['turns']):raise HTTPException(404,'Turn not found')
    row=data['turns'][index]
    return speaker_excerpt(project_id,{'start':max(0,row['start']-.5),'end':min(row['end']+.5,row['start']+8)})


@app.get('/api/projects/{project_id}/speaker-review/overlaps/{index}/sample')
def overlap_source_sample(project_id: str,index: int):
    data=get_speaker_review(project_id)
    if not 0<=index<len(data['overlap_events']):raise HTTPException(404,'Overlap not found')
    row=data['overlap_events'][index]
    return speaker_excerpt(project_id,{'start':max(0,row['start']-.5),'end':min(row['end']+.5,row['start']+8)})


class OverlapReview(BaseModel):
    confirmed: bool = False


@app.post('/api/projects/{project_id}/speaker-review/overlaps/{index}')
def confirm_overlap_transcript(project_id: str,index: int,body: OverlapReview):
    require_idle_speaker_review(project_id);data=get_speaker_review(project_id)
    if not body.confirmed:raise HTTPException(409,'Listen and confirm that every speaker has complete transcript words first.')
    if not 0<=index<len(data['overlap_events']):raise HTTPException(404,'Overlap not found')
    event=data['overlap_events'][index]
    covered={r['speaker_id'] for r in data['turns'] if r.get('text') and not r.get('speaker_review_required')
             and r['start']<event['end'] and r['end']>event['start']}
    missing=(set(event['speaker_ids'])-set(data.get('excluded_speakers',{})))-covered
    if missing:raise HTTPException(409,'Overlap transcript is incomplete for '+', '.join(sorted(missing))+'. Correct/recover those words before continuing.')
    from .speaker_review import read,overlap_evidence_hash
    from .analysis_pipeline import _atomic_json
    base=project_dir(project_id);diar=read(base/'analysis/diarization.json',{})
    path=base/'analysis/speaker_overlap_review.json';evidence=overlap_evidence_hash(diar);review=read(path,{})
    if review.get('evidence_sha256')!=evidence:review={'evidence_sha256':evidence,'events':{}}
    review['events'][str(index)]={'confirmed_at':now(),'confirmed_by':'user','method':'listened_and_reviewed_all_speakers'}
    _atomic_json(path,review)
    return get_speaker_review(project_id)


@app.patch("/api/projects/{project_id}/characters/{character_id}")
def update_character(project_id: str, character_id: str, body: CharacterUpdate) -> dict[str, Any]:
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    require_idle_speaker_review(project_id)
    registry = read_character_registry(project_id)
    item = next((c for c in registry["characters"] if c["character_id"] == character_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Character not found")
    changes = body.model_dump(exclude_unset=True)
    if "display_name" in changes and changes["display_name"] != item.get("display_name"):
        item["auto_display_name"] = False
    if "notes" in changes:
        item["auto_notes"] = False
    for key, value in changes.items():
        if key == "character_type" and value not in {"unknown", "adult", "child", "animal", "creature", "narrator", "other"}:
            raise HTTPException(status_code=422, detail="Unsupported character_type")
        if key == "voice_profile":
            # Metadata only: provider credentials and voice cloning artifacts are never stored here.
            try:
                merged = {**(item.get("voice_profile") or {}), **value}
                value = normalize_voice_profile(merged)
            except VoiceProfileError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        item[key] = value
    item["updated_at"] = now()
    write_character_registry(project_id, registry)
    update_timeline_character_identity(
        timeline_path=project_dir(project_id) / "analysis" / "timeline.json",
        registry=registry,
    )
    refresh_dialogue_manifest(project_id)
    return item

@app.post("/api/projects/{project_id}/characters/link-speaker")
def link_speaker(project_id: str, body: SpeakerLink) -> dict[str, Any]:
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    require_idle_speaker_review(project_id)
    registry = read_character_registry(project_id)
    target = next((c for c in registry["characters"] if c["character_id"] == body.character_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Character not found")
    _, diar_path = character_paths(project_id)
    if not diar_path.exists():
        raise HTTPException(status_code=409, detail="Run speaker diarization first")
    diar = json.loads(diar_path.read_text(encoding="utf-8"))
    if body.speaker_id not in {str(s.get("speaker_id")) for s in diar.get("speakers", [])}:
        raise HTTPException(status_code=404, detail="Speaker ID not present in diarization")
    previous = registry["speaker_links"].get(body.speaker_id)
    if previous and previous != body.character_id:
        old = next((c for c in registry["characters"] if c["character_id"] == previous), None)
        if old and body.speaker_id in old.get("aliases", []):
            old["aliases"].remove(body.speaker_id)
    registry["speaker_links"][body.speaker_id] = body.character_id
    target.setdefault("aliases", [])
    if body.speaker_id != target.get("source_speaker_id") and body.speaker_id not in target["aliases"]:
        target["aliases"].append(body.speaker_id)
    target["review_required"] = True
    target["updated_at"] = now()
    write_character_registry(project_id, registry)
    update_timeline_character_identity(
        timeline_path=project_dir(project_id) / "analysis" / "timeline.json",
        registry=registry,
    )
    # Reflect global character identity in transcript segments without changing original diarization.
    transcript_path = project_dir(project_id) / "analysis" / "transcript.json"
    if transcript_path.exists():
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
        for segment in transcript.get("segments", []):
            sid = segment.get("speaker_id")
            segment["character_id"] = registry["speaker_links"].get(sid)
        transcript_path.write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")
    refresh_dialogue_manifest(project_id)
    return {"speaker_id": body.speaker_id, "character_id": body.character_id, "display_name": target["display_name"]}

@app.delete("/api/projects/{project_id}/characters/{character_id}")
def delete_character(project_id: str, character_id: str) -> dict[str, bool]:
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    registry = read_character_registry(project_id)
    if not any(c["character_id"] == character_id for c in registry["characters"]):
        raise HTTPException(status_code=404, detail="Character not found")
    registry["characters"] = [c for c in registry["characters"] if c["character_id"] != character_id]
    registry["speaker_links"] = {sid: cid for sid, cid in registry["speaker_links"].items() if cid != character_id}
    write_character_registry(project_id, registry)
    update_timeline_character_identity(
        timeline_path=project_dir(project_id) / "analysis" / "timeline.json",
        registry=registry,
    )
    transcript_path = project_dir(project_id) / "analysis" / "transcript.json"
    if transcript_path.exists():
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
        for segment in transcript.get("segments", []):
            segment["character_id"] = registry["speaker_links"].get(str(segment.get("speaker_id")))
        transcript_path.write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")
    refresh_dialogue_manifest(project_id)
    return {"deleted": True}


class VoiceAssignmentUpdate(BaseModel):
    assignments: dict[str, Any] = Field(default_factory=dict)


@app.get("/api/voices/bank")
def get_voice_bank() -> dict[str, Any]:
    bank = get_movie_cast_voice_bank()
    enriched = []
    for v in bank:
        item = dict(v)
        cid = item.get("character_id")
        item["audio_url"] = f"/api/voices/{cid}/preview"
        enriched.append(item)
    from .clone_runtime import runtime_status
    return {"total": len(enriched), "voices": enriched, "clone_runtime": runtime_status(),
            "accepted_auditions": sum(v.get("audition_accepted", False) for v in enriched),
            "repaired_auditions": sum(r.get("clone",{}).get("status") == "completed" for v in enriched for r in v.get("repairs",[])),
            "verified": sum(v.get("eligible_for_defaults", False) for v in enriched)}


class VoiceReferenceReview(BaseModel):
    single_speaker: bool = False
    speech_present: bool = False
    background_clean: bool = False
    identity_confirmed: bool = False
    clone_identity_passed: bool = False
    naturalness_passed: bool = False
    dialogue_content_passed: bool = False
    perceived_type: str = "unknown"
    age_band: str = "unknown"
    notes: str = Field(default="", max_length=2000)
    reference_text: str | None = Field(default=None, max_length=4000)
    reference_version: str | None = None
    reference_index: int | None = None


@app.post("/api/voices/{voice_id}/review")
def review_voice_reference(voice_id: str, body: VoiceReferenceReview) -> dict:
    from .voice_bank_quality import write_report, AGE_BANDS, VOICE_TYPES, reviewed_eligibility
    valid_ids = {v["character_id"] for v in get_movie_cast_voice_bank()}
    if voice_id not in valid_ids:
        raise HTTPException(404, "Voice not found")
    if body.age_band not in AGE_BANDS or body.perceived_type not in VOICE_TYPES:
        raise HTTPException(422, "Unknown perceived voice type or apparent age band")
    path = DATA_ROOT / "voice-bank-audit/records" / f"{voice_id}.json"
    if not path.is_file():
        raise HTTPException(409, "Audit the reference before recording its review")
    data = json.loads(path.read_text(encoding="utf-8"))
    if body.reference_version is not None:
        from .voice_bank_quality import select_repaired_reference
        folder = (DATA_ROOT / "voice-bank-audit/repairs" / voice_id).resolve()
        repair_path = (folder / body.reference_version / "repair.json").resolve()
        if not body.identity_confirmed or not repair_path.is_relative_to(folder) or not repair_path.is_file():
            raise HTTPException(409, "Confirm the repaired speaker identity before selecting the reference")
        repair = json.loads(repair_path.read_text(encoding="utf-8"))
        index = body.reference_index
        candidates = repair.get("repairs", [])
        if repair.get("original_sha256") != data.get("catalog_reference_sha256", data["sha256"]) or index is None or index < 0 or index >= len(candidates):
            raise HTTPException(409, "Repair version does not match this catalog reference")
        candidate = candidates[index]
        if not Path(candidate.get("path", "")).resolve().is_relative_to(folder) or not Path(candidate.get("clone",{}).get("file", "")).resolve().is_relative_to(folder):
            raise HTTPException(409, "Repair files are outside their version folder")
        try:
            data = select_repaired_reference(data, candidate)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
    data["review"] = {k: v for k, v in body.model_dump().items() if k not in ("age_band", "perceived_type", "reference_text", "reference_version", "reference_index")}
    if body.reference_text is not None:
        data["audit"]["speech_text"] = body.reference_text.strip()
    data["review"].update(reviewed_at=now(), method="manual_listening_and_source_comparison")
    from .voice_bank_quality import fingerprint
    clone = data.get("clone", {})
    output = Path(clone.get("file", ""))
    if (body.clone_identity_passed and body.naturalness_passed and body.dialogue_content_passed and
        clone.get("reference_conditioned") and output.is_file() and fingerprint(output) == clone.get("output_sha256")):
        data["audition_acceptance"] = {"status":"user_accepted", "output_sha256":clone["output_sha256"], "method":"manual_review_form"}
    else:
        data["audition_acceptance"] = {}
    data["perceived_voice"] = {"type": body.perceived_type, "age_band": body.age_band,
                               "confidence": "manual_estimate", "exact_age": None}
    data["eligible_for_defaults"], data["review_blockers"] = reviewed_eligibility(data)
    write_report(path, data)
    return data


@app.get("/api/voices/{voice_id}/clone-preview")
def preview_cloned_voice(voice_id: str) -> FileResponse:
    if voice_id not in {v["character_id"] for v in get_movie_cast_voice_bank()}:
        raise HTTPException(404, "Voice not found")
    record_path = DATA_ROOT / "voice-bank-audit/records" / f"{voice_id}.json"
    record = json.loads(record_path.read_text(encoding="utf-8")) if record_path.is_file() else {}
    path = Path(record.get("clone",{}).get("file", "")).resolve()
    if not path.is_relative_to((DATA_ROOT / "voice-bank-audit").resolve()) or not path.is_file():
        raise HTTPException(404, "No genuine cloned audition generated yet")
    return FileResponse(path, media_type="audio/wav")


@app.get("/api/voices/{voice_id}/source-preview")
def preview_voice_source(voice_id: str) -> FileResponse:
    if voice_id not in {v["character_id"] for v in get_movie_cast_voice_bank()}:
        raise HTTPException(404, "Voice not found")
    path = DATA_ROOT / "voice-bank-audit/sources" / f"{voice_id}.wav"
    if not path.is_file():
        raise HTTPException(404, "Source excerpt has not been recovered")
    return FileResponse(path, media_type="audio/wav")


@app.get("/api/voices/{voice_id}/repair-preview/{version}/{index}")
def preview_repaired_voice(voice_id: str, version: str, index: int, cloned: bool = False) -> FileResponse:
    if voice_id not in {v["character_id"] for v in get_movie_cast_voice_bank()}:
        raise HTTPException(404, "Voice not found")
    folder = (DATA_ROOT / "voice-bank-audit/repairs" / voice_id).resolve()
    report_path = (folder / version / "repair.json").resolve()
    if not report_path.is_relative_to(folder) or not report_path.is_file():
        raise HTTPException(404, "Repair version not found")
    candidates = json.loads(report_path.read_text(encoding="utf-8")).get("repairs", [])
    if index < 0 or index >= len(candidates) or not candidates[index].get("path"):
        raise HTTPException(404, "Repair audio not available")
    selected = candidates[index].get("clone",{}) if cloned else candidates[index]
    path = Path(selected.get("file" if cloned else "path", "")).resolve()
    if not path.is_relative_to(folder) or not path.is_file():
        raise HTTPException(404, "Repair audio not found")
    return FileResponse(path, media_type="audio/wav")


@app.get("/api/voices/{voice_id}/repair-clone-preview/{version}/{index}")
def preview_repaired_clone(voice_id: str, version: str, index: int) -> FileResponse:
    return preview_repaired_voice(voice_id, version, index, cloned=True)


@app.get("/api/voices/{voice_id}/preview")
def preview_voice(voice_id: str) -> FileResponse:
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in voice_id)
    wav_path = ROOT / "storage" / "default_voice_bank" / "candidate_voices" / f"{safe_id}.wav"
    record_path = DATA_ROOT / "voice-bank-audit/records" / f"{safe_id}.json"
    if record_path.is_file():
        record = json.loads(record_path.read_text(encoding="utf-8"))
        selected = Path(record.get("reference_path", str(wav_path))).resolve()
        if selected.is_relative_to((DATA_ROOT / "voice-bank-audit").resolve()) or selected.is_relative_to((ROOT / "storage/default_voice_bank").resolve()):
            wav_path = selected
    if not wav_path.is_file():
        raise HTTPException(status_code=404, detail="Voice sample preview not found")
    return FileResponse(wav_path, media_type="audio/wav", filename=f"{safe_id}.wav")


@app.get("/api/projects/{project_id}/voice-assignments")
def get_project_voice_assignments(project_id: str) -> dict[str, Any]:
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")

    registry = read_character_registry(project_id)
    characters = registry.get("characters", [])

    assign_path = project_dir(project_id) / "analysis" / "voice_assignments.json"
    manual = {}
    if assign_path.is_file():
        try:
            manual = json.loads(assign_path.read_text(encoding="utf-8"))
        except Exception:
            manual = {}

    assigned_chars = assign_movie_cast_voices(characters, manual_overrides=manual.get("assignments"))
    return {
        "project_id": project_id,
        "characters": assigned_chars,
        "manual_assignments": manual.get("assignments", {})
    }


@app.post("/api/projects/{project_id}/voice-assignments")
def save_project_voice_assignments(project_id: str, body: VoiceAssignmentUpdate) -> dict[str, Any]:
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")

    bank = {v["character_id"]: v for v in get_movie_cast_voice_bank()}
    for mapping in body.assignments.values():
        vid = mapping.get("voice_id") if isinstance(mapping, dict) else mapping
        if vid not in bank or not bank[vid].get("eligible_for_defaults"):
            raise HTTPException(409, "Voice reference and genuine clone must pass review before assignment")
    analysis_dir = project_dir(project_id) / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    assign_path = analysis_dir / "voice_assignments.json"
    data = {
        "project_id": project_id,
        "updated_at": now(),
        "assignments": body.assignments
    }
    assign_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    registry = read_character_registry(project_id)
    bank = {v["character_id"]: v for v in get_movie_cast_voice_bank()}

    for char in registry.get("characters", []):
        cid = char.get("character_id")
        spk_id = char.get("source_speaker_id")
        mapping = body.assignments.get(cid) or (body.assignments.get(spk_id) if spk_id else None)
        if mapping:
            vid = mapping.get("voice_id") if isinstance(mapping, dict) else mapping
            rate = float(mapping.get("rate", 1.0)) if isinstance(mapping, dict) else 1.0
            pitch = float(mapping.get("pitch_semitones", 0.0)) if isinstance(mapping, dict) else 0.0
            if vid in bank:
                b_info = bank[vid]
                char["voice_profile"] = {
                    "status": "configured",
                    "provider": "cloned",
                    "voice_id": vid,
                    "language": "hi",
                    "gender": b_info.get("gender", "male"),
                    "style": "theatrical",
                    "reference_audio": b_info.get("reference_path"),
                    "settings": {
                        "reference_audio": b_info.get("reference_path"),
                        "ref_text": b_info.get("audit", {}).get("speech_text", ""),
                        "rate": rate,
                        "pitch_semitones": pitch,
                        "age_group": b_info.get("age_group", "adult"),
                        "description": b_info.get("character_name", ""),
                    }
                }
                char["updated_at"] = now()
    write_character_registry(project_id, registry)

    return {"status": "saved", "assigned_count": len(body.assignments)}


@app.get("/api/system/health")
def system_health_status() -> dict[str, Any]:
    bank = get_movie_cast_voice_bank()
    diag = collect_diagnostics() if "collect_diagnostics" in globals() else {}
    return {
        "status": "healthy",
        "theme": "light",
        "voice_bank": {
            "status": "online",
            "total_voices": len(bank),
            "verified_voices": sum(v.get("eligible_for_defaults", False) for v in bank),
            "purity": "Per-reference source and listening review required",
            "loudness": "Measured per reference; no universal broadcast certification"
        },
        "audio_engine": {
            "separation": "UVR available where configured; residual artifacts require review",
            "transcription": "Whisper ASR Multi-lingual",
            "cloning": "Genuine OmniVoice pilot/review required; no stock fallback as clone"
        },
        "diagnostics": diag
    }


@app.get("/api/projects/{project_id}/pipeline/state")
def pipeline_state(project_id: str, target_language: str | None = None) -> dict[str, Any]:
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    item = get_project(DB_PATH, project_id) or {}
    effective_target = target_language or item.get("target_language")
    return get_pipeline_state(
        project_root=project_dir(project_id),
        project_id=project_id,
        target_language=effective_target,
    )

@app.post("/api/projects/{project_id}/translate")
def translate_project(project_id: str, body: TranslationRequest) -> dict[str, Any]:
    require_reviewed_new_speaker_foundation(project_id)
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    base = project_dir(project_id)
    pipeline = get_pipeline_state(
        project_root=base,
        project_id=project_id,
        target_language=body.target_language,
    )
    identity = next(stage for stage in pipeline["stages"] if stage["id"] == "character_identity")
    if not identity["ready"]:
        raise HTTPException(status_code=409, detail="Complete movie analysis and automatic Character Registry sync before translation.")
    print(f"\n[OpenDub Translation] Starting translation for project {project_id} to '{body.target_language}'...", flush=True)
    refresh_dialogue_manifest(project_id)
    try:
        if body.conversational_hindi and body.target_language in {"hi", "hindi"}:
            from .automatic_dialogue import translate_natural_hindi, source_subtitle_context
            project = get_project(DB_PATH, project_id)
            source = (ROOT / project["source_path"]).resolve()
            cues = source_subtitle_context(source, base / "analysis")
            result = translate_natural_hindi(base / "analysis" / "transcript.json", base / "analysis" / "translated_transcript.json", context={"source_filename":source.name,"subtitle_cues":cues})
        else:
            result = translate_transcript(
            base / "analysis" / "transcript.json",
            base / "analysis" / "translated_transcript.json",
            body.target_language,
            body.source_language,
        )
        translated = json.loads((base / "analysis" / "translated_transcript.json").read_text(encoding="utf-8"))
        translated["engine"] = result.get("engine", "Argos Translate (local)")
        update_dialogue_manifest_translation(
            manifest_path=base / "analysis" / "dialogue_manifest.json",
            translated_result=translated,
        )
        print(f"[OpenDub Translation] Completed translation: {result.get('translated_segments', 0)} segments translated.\n", flush=True)
        return result
    except Exception as exc:
        print(f"[OpenDub Translation] Translation failed: {exc}", flush=True)
        raise HTTPException(status_code=400, detail=str(exc))

@app.patch("/api/projects/{project_id}/dialogue/{segment_index}/prosody")
def edit_dialogue_prosody(project_id: str, segment_index: int, body: ProsodyEditRequest) -> dict[str, Any]:
    from .atomic_files import project_mutation_lock
    with SYNTHESIS_FILE_LOCK, project_mutation_lock(project_dir(project_id)):
        if not get_project(DB_PATH, project_id):
            raise HTTPException(status_code=404, detail="Project not found")
        manifest_path = project_dir(project_id) / "analysis" / "dialogue_manifest.json"
        if not manifest_path.exists():
            raise HTTPException(status_code=409, detail="Run analysis to create the dialogue manifest first")
        try:
            manifest = read_json_safe(manifest_path)
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=500, detail=f"Dialogue manifest could not be read: {exc}") from exc
        units = manifest.get("units") or []
        unit = next((row for row in units if int(row.get("segment_index", -1)) == segment_index), None)
        if unit is None:
            raise HTTPException(status_code=404, detail="Dialogue segment not found")
        unit["prosody"] = {
            "schema_version": 1,
            **body.model_dump(),
            "provider_support": (unit.get("prosody") or {}).get("provider_support", "not_checked"),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"status": "saved", "segment_index": segment_index, "prosody": unit["prosody"]}

def invalidate_dialogue_audio(unit: dict, row: dict, *, include_tts: bool = True) -> None:
    """Keep prior files for review while preventing reuse for changed dialogue."""
    for stage in (("tts", "timing", "loudness") if include_tts else ("timing", "loudness")):
        unit[stage] = {"status": "pending", "updated_at": now()}
    for key in (("dub_audio", "fitted_audio", "normalized_audio", "synthesis_duration_check") if include_tts else ("fitted_audio", "normalized_audio")):
        row.pop(key, None)


@app.patch("/api/projects/{project_id}/dialogue/{segment_index}/translation")
def edit_translation(project_id: str, segment_index: int, body: TranslationEditRequest) -> dict[str, Any]:
    from .atomic_files import project_mutation_lock
    with SYNTHESIS_FILE_LOCK, project_mutation_lock(project_dir(project_id)):
        if not get_project(DB_PATH, project_id):
            raise HTTPException(status_code=404, detail="Project not found")
        base = project_dir(project_id)
        manifest_path = base / "analysis" / "dialogue_manifest.json"
        translation_path = base / "analysis" / "translated_transcript.json"
        if not manifest_path.exists() or not translation_path.exists():
            raise HTTPException(status_code=409, detail="Run translation first")
        try:
            manifest = read_json_safe(manifest_path)
            translated = json.loads(translation_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=500, detail=f"Translation artifacts could not be read: {exc}") from exc

        units = manifest.get("units") or []
        unit = next((row for row in units if int(row.get("segment_index", -1)) == segment_index), None)
        rows = translated.get("segments") or []
        row = next((item for item in rows if int(item.get("segment_index", -1)) == segment_index), None)
        if unit is None or row is None:
            raise HTTPException(status_code=404, detail="Dialogue segment not found")

        text = body.translated_text.strip()
        source_text = str(unit.get("source_text") or "")
        source_duration = float(unit.get("duration_sec") or max(0.1, float(unit.get("end_sec", 0)) - float(unit.get("start_sec", 0))))
        budget = evaluate_adaptation_budget(
            source_text=source_text,
            target_text=text,
            source_duration_sec=body.timing_budget_sec or source_duration,
            max_words=body.max_words,
        )
        unit["translation"] = {
            **(unit.get("translation") or {}),
            "status": "completed",
            "text": text,
            "adaptation": {
                "status": "manually_naturalized",
                "mode": body.adaptation_mode,
                "text": text,
                "tone": body.tone,
                "delivery_intent": body.delivery_intent,
                "timing_budget_sec": body.timing_budget_sec or source_duration,
                "max_words": budget["max_words"],
                "budget": budget,
            },
            "error": None,
        }
        if str(row.get("translated_text") or "") != text:
            invalidate_dialogue_audio(unit, row)
        row["translated_text"] = text
        row["translation_error"] = None
        row["adaptation_mode"] = body.adaptation_mode

        manifest["translation"] = {
            **(manifest.get("translation") or {}),
            "status": "completed",
            "reviewed_units": sum(
                1 for item in units
                if (item.get("translation") or {}).get("adaptation", {}).get("status") == "manually_naturalized"
            ),
            "updated_at": now(),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        translation_path.write_text(json.dumps(translated, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "segment_index": segment_index,
            "character_id": unit.get("character_id"),
            "character_name": unit.get("character_name"),
            "translated_text": text,
            "adaptation_mode": body.adaptation_mode,
        }

@app.get("/api/projects/{project_id}/translation/validate")
def validate_translation(project_id: str) -> dict[str, Any]:
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    base = project_dir(project_id)
    manifest_path = base / "analysis" / "dialogue_manifest.json"
    translation_path = base / "analysis" / "translated_transcript.json"
    if not manifest_path.exists() or not translation_path.exists():
        raise HTTPException(status_code=409, detail="Run translation first")
    try:
        manifest = read_json_safe(manifest_path)
        translated = json.loads(translation_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Translation artifacts could not be read: {exc}") from exc
    report = validate_translation_manifest(manifest, translated)
    manifest["translation_validation"] = {**report, "updated_at": now()}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return report

@app.post("/api/projects/{project_id}/dialogue/{segment_index}/adaptation/suggest")
def suggest_adaptation(project_id: str, segment_index: int, body: TranslationEditRequest) -> dict[str, Any]:
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    base = project_dir(project_id)
    manifest_path = base / "analysis" / "dialogue_manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=409, detail="Run translation first")
    try:
        manifest = read_json_safe(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Dialogue manifest could not be read: {exc}") from exc
    unit = next((row for row in (manifest.get("units") or []) if int(row.get("segment_index", -1)) == segment_index), None)
    if unit is None:
        raise HTTPException(status_code=404, detail="Dialogue segment not found")
    translation = unit.get("translation") or {}
    source_text = str(unit.get("source_text") or "")
    translated_text = str(body.translated_text or translation.get("text") or "")
    if not translated_text.strip():
        raise HTTPException(status_code=422, detail="Provide translated dialogue before requesting adaptation.")
    source_duration = body.timing_budget_sec or float(unit.get("duration_sec") or 0.1)
    if body.adaptation_mode == "llm_semantic_assist":
        if not semantic_provider_configured():
            raise HTTPException(
                status_code=503,
                detail="Semantic adaptation is optional and is not configured. Set OPENDUB_LLM_API_KEY to enable it.",
            )
        registry_path = base / "characters" / "registry.json"
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.is_file() else {}
        except (OSError, json.JSONDecodeError):
            # Registry metadata is advisory for prompting; corrupted metadata must not
            # break adaptation or cause the model to invent character details.
            registry = {}
        try:
            suggestion = propose_semantic_adaptation(
                source_text=source_text,
                translated_text=translated_text,
                source_language=str(manifest.get("source_language") or "unspecified"),
                target_language=str(manifest.get("target_language") or "unspecified"),
                character_identity=format_character_context(
                    registry, str(unit.get("character_id") or "")
                ),
                tone=body.tone,
                delivery_intent=body.delivery_intent,
                max_words=body.max_words,
                source_duration_sec=source_duration,
            )
        except SemanticAdaptationError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    else:
        suggestion = suggest_dialogue_adaptation(
            source_text=source_text,
            translated_text=translated_text,
            tone=body.tone,
            delivery_intent=body.delivery_intent,
            max_words=body.max_words,
        )
    suggestion["timing_budget_sec"] = source_duration
    suggestion["segment_index"] = segment_index
    suggestion["adaptation_mode"] = body.adaptation_mode
    if body.adaptation_mode == "llm_semantic_assist":
        timing_report = evaluate_adaptation_budget(
            source_text=source_text,
            target_text=str(suggestion.get("suggested_text") or ""),
            source_duration_sec=source_duration,
            max_words=body.max_words,
        )
        suggestion["validation"] = {
            "semantic_preservation": "pending_human_review",
            "character_identity": "preserved_from_manifest_context_not_independently_verified",
            "tone": "prompted_not_independently_verified",
            "timing": timing_report,
            "overall": "needs_review" if timing_report["status"] == "within_budget" else "timing_over_budget",
        }
        suggestion["validation_status"] = suggestion["validation"]["overall"]
        suggestion["production_ready"] = False
        suggestion["requires_review"] = True
    return suggestion

@app.post("/api/projects/{project_id}/dialogue/{segment_index}/adaptation/review")
def review_adaptation(project_id: str, segment_index: int, body: AdaptationReviewRequest) -> dict[str, Any]:
    """Explicitly accept/reject a proposed line; only approval writes synthesis input."""
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    base = project_dir(project_id)
    manifest_path = base / "analysis" / "dialogue_manifest.json"
    translation_path = base / "analysis" / "translated_transcript.json"
    if not manifest_path.exists() or not translation_path.exists():
        raise HTTPException(status_code=409, detail="Run translation first")
    try:
        manifest = read_json_safe(manifest_path)
        translated = json.loads(translation_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Translation artifacts could not be read: {exc}") from exc
    units = manifest.get("units") or []
    rows = translated.get("segments") or []
    unit = next((row for row in units if int(row.get("segment_index", -1)) == segment_index), None)
    row = next((item for item in rows if int(item.get("segment_index", -1)) == segment_index), None)
    if unit is None or row is None:
        raise HTTPException(status_code=404, detail="Dialogue segment not found")
    audit_path = base / "analysis" / "adaptation_review_audit.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    prior_events = []
    if audit_path.exists():
        try:
            prior_events = [
                json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, json.JSONDecodeError):
            raise HTTPException(status_code=500, detail="Adaptation review audit log is unreadable")
    segment_events = [event for event in prior_events if event.get("segment_index") == segment_index]
    revision = len(segment_events) + 1
    previous_text = str(row.get("translated_text") or "")
    text = body.suggested_text.strip()
    event = {
        "segment_index": segment_index, "revision": revision,
        "decision": "approved" if body.decision == "approve" else "rejected",
        "adaptation_mode": body.adaptation_mode,
        "previous_text": previous_text, "candidate_text": text,
        "reviewed_by": "user", "reviewed_at": now(),
        "tone": body.tone, "delivery_intent": body.delivery_intent,
    }
    if body.decision == "reject":
        with audit_path.open("a", encoding="utf-8") as audit:
            audit.write(json.dumps(event, ensure_ascii=False) + "\n")
        return {"segment_index": segment_index, "decision": "rejected", "revision": revision,
                "written": False, "audit_recorded": True,
                "requires_review": True, "production_ready": False}
    if not text:
        raise HTTPException(status_code=422, detail="Approved dialogue cannot be blank")
    duration = body.timing_budget_sec or float(unit.get("duration_sec") or 0.1)
    budget = evaluate_adaptation_budget(
        source_text=str(unit.get("source_text") or ""), target_text=text,
        source_duration_sec=duration, max_words=body.max_words,
    )
    validation = validate_adaptation_candidate(
        source_text=str(unit.get("source_text") or ""),
        target_text=text,
        expected_character_id=unit.get("character_id"),
        actual_character_id=row.get("character_id") or unit.get("character_id"),
        requested_tone=body.tone,
        recorded_tone=body.tone,
        delivery_intent=body.delivery_intent,
        recorded_delivery_intent=body.delivery_intent,
        source_duration_sec=duration,
        max_words=body.max_words,
    )
    unit["translation"] = {
        **(unit.get("translation") or {}),
        "status": "completed", "text": text,
        "adaptation": {
            "status": "human_approved", "mode": body.adaptation_mode,
            "text": text, "tone": body.tone, "delivery_intent": body.delivery_intent,
            "timing_budget_sec": duration, "max_words": budget["max_words"],
            "budget": budget, "validation": validation, "reviewed_by": "user", "review_decision": "approve",
            "reviewed_at": now(),
        }, "error": None,
    }
    if str(row.get("translated_text") or "") != text:
        invalidate_dialogue_audio(unit, row)
    row["translated_text"] = text
    row["translation_error"] = None
    row["adaptation_mode"] = body.adaptation_mode
    row["adaptation_review"] = {
        "decision": "approved", "reviewed_by": "user", "reviewed_at": now(),
        "timing_status": budget["status"], "validation_status": validation["status"],
    }
    manifest["translation"] = {
        **(manifest.get("translation") or {}), "status": "completed",
        "updated_at": now(),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    translation_path.write_text(json.dumps(translated, ensure_ascii=False, indent=2), encoding="utf-8")
    with audit_path.open("a", encoding="utf-8") as audit:
        audit.write(json.dumps(event, ensure_ascii=False) + "\n")
    return {
        "segment_index": segment_index, "decision": "approved", "revision": revision,
        "audit_recorded": True, "written": True,
        "requires_review": False, "production_ready": True,
        "timing": budget, "validation": validation, "warning": "Human approval recorded. Deterministic metadata and timing checks do not prove semantic equivalence or measured audio duration; listen to the synthesized audio.",
    }

@app.get("/api/projects/{project_id}/dialogue/{segment_index}/adaptation/history")
def adaptation_history(project_id: str, segment_index: int) -> dict[str, Any]:
    """Return append-only review history for one dialogue, newest revision first."""
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    audit_path = project_dir(project_id) / "analysis" / "adaptation_review_audit.jsonl"
    if not audit_path.exists():
        return {"segment_index": segment_index, "events": []}
    try:
        events = [
            json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Adaptation review audit log is unreadable") from exc
    selected = [event for event in events if int(event.get("segment_index", -1)) == segment_index]
    return {"segment_index": segment_index, "events": list(reversed(selected))}


@app.post("/api/projects/{project_id}/dialogue/{segment_index}/adaptation/restore/{revision}")
def restore_approved_adaptation(project_id: str, segment_index: int, revision: int) -> dict[str, Any]:
    """Restore an earlier human-approved revision by recording a new approval event."""
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    if revision < 1:
        raise HTTPException(status_code=422, detail="Revision must be positive")
    base = project_dir(project_id)
    audit_path = base / "analysis" / "adaptation_review_audit.jsonl"
    manifest_path = base / "analysis" / "dialogue_manifest.json"
    translation_path = base / "analysis" / "translated_transcript.json"
    if not audit_path.is_file() or not manifest_path.is_file() or not translation_path.is_file():
        raise HTTPException(status_code=409, detail="No review history or translation artifacts found")
    try:
        events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        manifest = read_json_safe(manifest_path)
        translated = json.loads(translation_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Review or translation artifacts are unreadable") from exc
    approved = next((event for event in events
                     if int(event.get("segment_index", -1)) == segment_index
                     and int(event.get("revision", -1)) == revision
                     and event.get("decision") == "approved"), None)
    if not approved:
        raise HTTPException(status_code=404, detail="Approved revision not found")
    unit = next((row for row in manifest.get("units", [])
                 if int(row.get("segment_index", -1)) == segment_index), None)
    row = next((item for item in translated.get("segments", [])
                if int(item.get("segment_index", -1)) == segment_index), None)
    if unit is None or row is None:
        raise HTTPException(status_code=404, detail="Dialogue segment not found")
    restored_text = str(approved.get("candidate_text") or "").strip()
    if not restored_text:
        raise HTTPException(status_code=409, detail="Approved revision contains blank text")
    latest_revision = max((int(event.get("revision", 0)) for event in events
                           if int(event.get("segment_index", -1)) == segment_index), default=0)
    timestamp = now()
    restore_event = {
        **approved, "revision": latest_revision + 1, "decision": "approved",
        "previous_text": str(row.get("translated_text") or ""),
        "candidate_text": restored_text, "restored_from_revision": revision,
        "reviewed_by": "user", "reviewed_at": timestamp,
    }
    if str(row.get("translated_text") or "") != restored_text:
        invalidate_dialogue_audio(unit, row)
    row["translated_text"] = restored_text
    row["translation_error"] = None
    row["adaptation_mode"] = approved.get("adaptation_mode") or "conservative_assist"
    row["adaptation_review"] = {
        "decision": "approved", "reviewed_by": "user", "reviewed_at": timestamp,
        "restored_from_revision": revision,
    }
    unit["translation"] = {
        **(unit.get("translation") or {}), "status": "completed", "text": restored_text,
        "adaptation": {
            **(unit.get("translation") or {}).get("adaptation", {}),
            "status": "human_approved", "mode": row["adaptation_mode"],
            "text": restored_text, "review_decision": "approve",
            "reviewed_by": "user", "reviewed_at": timestamp,
            "restored_from_revision": revision,
        }, "error": None,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    translation_path.write_text(json.dumps(translated, ensure_ascii=False, indent=2), encoding="utf-8")
    with audit_path.open("a", encoding="utf-8") as audit:
        audit.write(json.dumps(restore_event, ensure_ascii=False) + "\n")
    return {"segment_index": segment_index, "decision": "approved",
            "revision": latest_revision + 1, "restored_from_revision": revision,
            "written": True, "audit_recorded": True}


@app.get("/api/projects/{project_id}/translation")
def get_translation(project_id: str) -> dict[str, Any]:
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    path = project_dir(project_id) / "analysis" / "translated_transcript.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Translate the transcript first")
    result = json.loads(path.read_text(encoding="utf-8"))
    registry = read_character_registry(project_id)
    names = {c.get("character_id"): c.get("display_name") for c in registry.get("characters", [])}
    for row in result.get("segments", []):
        if row.get("character_id") in names:
            row["character_name"] = names[row["character_id"]]
    manifest_path = path.parent / "dialogue_manifest.json"
    if manifest_path.is_file():
        units = json.loads(manifest_path.read_text(encoding="utf-8")).get("units", [])
        timing = {unit.get("segment_index"): unit.get("timing") or {} for unit in units}
        for row in result.get("segments", []):
            row["timing_check"] = timing.get(row.get("segment_index"), {})
    return result

def find_translated_segment(rows: Any, segment_index: int) -> dict[str, Any] | None:
    """Find a translated segment dictionary by its explicit segment_index."""
    if not isinstance(rows, list) or segment_index < 0:
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_index = row.get("segment_index")
        try:
            if raw_index is not None and not isinstance(raw_index, bool) and int(raw_index) == segment_index:
                return row
        except (ValueError, TypeError):
            continue
    return None


def reconcile_short_speech_windows(base: Path, manifest: dict, rows: list[dict]) -> None:
    from .reviewed_dub_timing import replay_reviewed_windows
    replay_reviewed_windows(base,manifest,rows)
    from .pipeline import recover_short_speech_window
    diarization_path = base / 'analysis' / 'diarization.json'
    if not diarization_path.is_file():
        return
    turns = json.loads(diarization_path.read_text(encoding='utf-8')).get('turns') or []
    source_rows = [{**row, **(row.get('source_asr_timing') or {})} for row in rows]
    for index, row in enumerate(rows):
        if row.get('timing_window_source')=='user_approved_dialogue_gap':continue
        left, right = recover_short_speech_window(source_rows, index, turns)
        original = source_rows[index]
        if (left, right) == (float(original.get('start', 0)), float(original.get('end', 0))):
            continue
        row.setdefault('source_asr_timing', {'start': original['start'], 'end': original['end']})
        row.update(start=left, end=right, timing_window_source='exclusive_speaker_turn')
        unit = find_dialogue_manifest_unit(manifest, int(row.get('segment_index', index)))
        if unit is not None:
            unit.update(start_sec=left, end_sec=right, duration_sec=round(right-left, 6),
                        source_asr_timing=row['source_asr_timing'], timing_window_source='exclusive_speaker_turn')


SYNTHESIS_FILE_LOCK = threading.Lock()


def read_json_safe(path: Path, retries: int = 5, delay: float = 0.05) -> dict[str, Any]:
    for attempt in range(retries):
        try:
            raw = path.read_text(encoding="utf-8")
            if raw.strip():
                return json.loads(raw)
        except (OSError, json.JSONDecodeError):
            if attempt == retries - 1:
                raise
            time.sleep(delay)
    return json.loads(path.read_text(encoding="utf-8"))


def persist_dialogue_manifest(path: Path, manifest: dict) -> None:
    temporary = path.with_name(f"{path.stem}.{uuid.uuid4().hex[:8]}.tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    replace_with_retry(temporary, path)


def prepare_synthesis_inputs(project_id: str, segment_index: int, body: SynthesisRequest) -> dict[str, Any]:
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    require_reviewed_new_speaker_foundation(project_id)
    translated_path = project_dir(project_id) / "analysis" / "translated_transcript.json"
    if not translated_path.exists():
        raise HTTPException(status_code=409, detail="Translate transcript first")
    translated = read_json_safe(translated_path)
    rows = translated.get("segments", [])
    row = find_translated_segment(rows, segment_index)
    if row is None:
        raise HTTPException(status_code=404, detail="Segment index not found")
    if row.get("adaptation_mode") == "llm_semantic_assist":
        review = row.get("adaptation_review") or {}
        if review.get("decision") != "approved":
            raise HTTPException(
                status_code=409,
                detail="Semantic adaptation requires explicit human approval before synthesis",
            )
    text = row.get("translated_text", "")
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=422, detail="Translated dialogue cannot be empty")
    output = project_dir(project_id) / "segments" / f"segment_{segment_index:06d}_dub.wav"
    prosody = {}
    selected_model_path = body.voice_model_path if body else None
    selected_clone_profile = None
    profile = {}
    selected_speaker_id = body.speaker_id if body else None
    manifest_path = project_dir(project_id) / "analysis" / "dialogue_manifest.json"
    if manifest_path.is_file():
        try:
            manifest = read_json_safe(manifest_path)
            unit = find_dialogue_manifest_unit(manifest, segment_index)
            if unit is not None:
                if isinstance(unit.get("prosody"), dict):
                    prosody = unit["prosody"]
                voice = unit.get("voice") or {}
                profile = voice.get("profile") or {}
                if voice.get("status") == "configured" and profile:
                    provider = profile.get("provider")
                    if provider in {"cloned", "omnivoice"}:
                        from .voice_bank_quality import fingerprint
                        voice_id = profile.get("voice_id")
                        candidate = next((v for v in get_movie_cast_voice_bank() if v["character_id"] == voice_id), None)
                        audit_path = DATA_ROOT / "voice-bank-audit/records" / f"{voice_id}.json"
                        if not audit_path.is_file():
                            raise HTTPException(409, "Assigned clone reference evidence is missing")
                        evidence = json.loads(audit_path.read_text(encoding="utf-8"))
                        from .automatic_dialogue import automatic_reference_valid
                        if not (candidate and candidate.get("eligible_for_defaults")) and not automatic_reference_valid(evidence, profile):
                            raise HTTPException(409, "Assigned clone reference evidence is invalid")
                        reference = Path(evidence["reference_path"])
                        if fingerprint(reference) != evidence["sha256"]:
                            raise HTTPException(409, "Clone reference changed; review required")
                        selected_clone_profile = {"reference": reference, "ref_text": evidence["audit"]["speech_text"]}
                    elif provider != "piper":
                        raise HTTPException(status_code=409, detail=f"Assigned character voice provider '{provider}' is not supported by this synthesis endpoint yet.")
                    profile_model_path = profile.get("model_path")
                    if provider == "piper" and (not isinstance(profile_model_path, str) or not profile_model_path.strip()):
                        raise HTTPException(status_code=409, detail="Assigned character Piper profile has no model_path.")
                    selected_model_path = profile_model_path
                    profile_settings = profile.get("settings") or {}
                    if selected_speaker_id is None and isinstance(profile_settings, dict):
                        profile_speaker_id = profile_settings.get("speaker_id")
                        if isinstance(profile_speaker_id, int) and not isinstance(profile_speaker_id, bool):
                            selected_speaker_id = profile_speaker_id
                    if isinstance(profile_settings, dict):
                        for k in ("pitch_semitones", "rate", "style", "theatrical_shaping", "volume_db"):
                            if k in profile_settings and k not in prosody:
                                prosody[k] = profile_settings[k]
        except HTTPException:
            raise
        except (OSError, json.JSONDecodeError, TypeError, AttributeError):
            prosody = {}
    from .kaggle_tasks import project_for
    if project_for(output) and selected_clone_profile is None:
        raise HTTPException(409,'Kaggle synthesis requires a reviewed OmniVoice reference. Select local processing explicitly for Piper.')
    if not selected_model_path and selected_clone_profile is None:
        models_dir = DATA_ROOT / "models" / "piper"
        if not models_dir.is_dir():
            models_dir = DATA_ROOT / "models"
        available_models = sorted(models_dir.glob("*.onnx")) if models_dir.is_dir() else []
        if available_models:
            selected_model_path = str(available_models[0].resolve())
    if not selected_model_path and selected_clone_profile is None:
        raise HTTPException(status_code=409, detail="No Piper voice model assigned. Configure the character voice profile or provide voice_model_path for a legacy project.")
    return dict(translated_path=translated_path,translated=translated,rows=rows,row=row,text=text,output=output,
                prosody=prosody,selected_model_path=selected_model_path,selected_clone_profile=selected_clone_profile,
                profile=profile,selected_speaker_id=selected_speaker_id,manifest_path=manifest_path)


@app.post("/api/projects/{project_id}/segments/{segment_index}/synthesize")
def synthesize_segment(project_id: str, segment_index: int, body: SynthesisRequest) -> dict[str, Any]:
    values=prepare_synthesis_inputs(project_id,segment_index,body)
    translated_path,translated,rows,row=(values[k] for k in ('translated_path','translated','rows','row'))
    text,output,prosody=(values[k] for k in ('text','output','prosody'))
    selected_model_path,selected_clone_profile,profile,selected_speaker_id,manifest_path=(values[k] for k in ('selected_model_path','selected_clone_profile','profile','selected_speaker_id','manifest_path'))
    from .voice_bank_quality import fingerprint
    temp_output = output.with_name(f"{output.stem}.{uuid.uuid4().hex}.pending.wav")
    try:
        from .atomic_files import project_mutation_lock
        with SYNTHESIS_FILE_LOCK, project_mutation_lock(project_dir(project_id)):
            if manifest_path.is_file():
                try:
                    update_dialogue_manifest_tts(
                        manifest_path=manifest_path, segment_index=segment_index, status="running",
                    )
                except Exception:
                    pass
                manifest = read_json_safe(manifest_path)
                reconcile_short_speech_windows(project_dir(project_id), manifest, rows)
                persist_dialogue_manifest(manifest_path, manifest)

        prosody = {**prosody, "target_duration_sec": max(0, float(row.get("end", 0)) - float(row.get("start", 0)))}
        if selected_clone_profile is not None:
            from .clone_runtime import synthesize_reference
            result = synthesize_reference(text, selected_clone_profile["reference"], selected_clone_profile["ref_text"], temp_output, prosody)
            from .speech_content import verify_clone_dialogue, require_clone_content
            from .voice_bank_quality import write_report
            content_check = verify_clone_dialogue(text, temp_output)
            result["content_check"] = content_check
            write_report(temp_output.with_suffix(".content.json"), content_check)
            if content_check.get("substantial_omission_suspected"):
                import shutil
                review_dir = output.parent / "content-review"
                review_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(temp_output, review_dir / temp_output.name)
                write_report(review_dir / temp_output.with_suffix(".content.json").name, content_check)
            require_clone_content(content_check)
        else:
            result = synthesize_piper_segment(text, temp_output, Path(selected_model_path), selected_speaker_id, prosody)
        measured = ffprobe(temp_output)
        if not measured.get("available") or measured.get("error") or measured.get("duration_ms") is None:
            raise RuntimeError("Synthesized audio was created but its actual duration could not be verified: " +
                               str(measured.get("error") or "ffprobe returned no duration"))
        source_window_ms = max(0, round((float(row.get("end", 0)) - float(row.get("start", 0))) * 1000))
        actual_ms = int(measured["duration_ms"])
        delta_ms = actual_ms - source_window_ms
        tolerance_ms = max(120, round(source_window_ms * 0.08))
        duration_check = {
            "source_window_ms": source_window_ms,
            "actual_audio_ms": actual_ms,
            "delta_ms": delta_ms,
            "tolerance_ms": tolerance_ms,
            "within_tolerance": abs(delta_ms) <= tolerance_ms,
            "status": "within_tolerance" if abs(delta_ms) <= tolerance_ms else "fit_required",
            "measured_by": "ffprobe",
        }
        # Preserve any previously verified dub until this attempt passes ffprobe.
        with SYNTHESIS_FILE_LOCK, project_mutation_lock(project_dir(project_id)):
            # Another worker may have committed a different line after inference
            # started. Merge only this line into a FRESH translation snapshot.
            latest_translated = read_json_safe(translated_path)
            latest_row = find_translated_segment(latest_translated.get('segments', []), segment_index)
            if latest_row is None or latest_row.get('translated_text') != row.get('translated_text'):
                raise RuntimeError('Dialogue changed during synthesis; regenerate the changed line.')
            if manifest_path.is_file():
                current = read_json_safe(manifest_path)
                current_voice = ((find_dialogue_manifest_unit(current, segment_index) or {}).get('voice') or {}).get('profile') or {}
                if current_voice != profile:
                    raise RuntimeError('Voice assignment changed during synthesis; previous audio retained.')
            publish_audio_revision(temp_output, output)
            result['file'] = str(output)
            result['size_bytes'] = output.stat().st_size
            if selected_clone_profile is not None:
                result['output_sha256'] = fingerprint(output)
                write_report(output.with_suffix('.clone.json'), result)
                temp_output.with_suffix('.clone.json').unlink(missing_ok=True)
            latest_row.update({k: row[k] for k in ('start', 'end', 'source_asr_timing') if k in row})
            row = latest_row
            translated = latest_translated
            if manifest_path.is_file():
                current_manifest = read_json_safe(manifest_path)
                current_unit = next((u for u in current_manifest.get("units", []) if u.get("segment_index") == segment_index), None)
                if current_unit is not None:
                    invalidate_dialogue_audio(current_unit, row, include_tts=False)
                    current_unit["tts"] = {
                        "status": "completed",
                        "audio_path": str(output),
                        "duration_sec": actual_ms / 1000,
                        "updated_at": now(),
                    }
                    persist_dialogue_manifest(manifest_path, current_manifest)
            row["dub_audio"] = str(output)
            row["synthesis_duration_check"] = duration_check
            if selected_clone_profile is not None:
                row["clone_evidence"] = result
            temp_translated = translated_path.with_name(f"{translated_path.stem}.{uuid.uuid4().hex[:8]}.tmp")
            temp_translated.write_text(json.dumps(translated, ensure_ascii=False, indent=2), encoding="utf-8")
            replace_with_retry(temp_translated, translated_path)

        return {**result, "duration_check": duration_check}
    except Exception as exc:
        raise_if_waiting(exc)
        try:
            temp_output.unlink(missing_ok=True)
        except OSError:
            pass
        if manifest_path.is_file():
            with SYNTHESIS_FILE_LOCK, project_mutation_lock(project_dir(project_id)):
                try:
                    update_dialogue_manifest_tts(
                        manifest_path=manifest_path, segment_index=segment_index,
                        status="error", error=str(exc)[:1000],
                    )
                except Exception:
                    pass
        raise HTTPException(status_code=400, detail=str(exc))


def execute_batch_synthesis(job_id: str, project_id: str, payload: dict[str, Any] | None = None) -> None:
    """Worker job to synthesize all eligible dialogue units in a project with resumability and fault tolerance."""
    if job_cancel_requested(DB_PATH, job_id):
        mark_job_cancelled(DB_PATH, job_id, "Synthesis cancelled by user.")
        return

    payload = payload or {}
    override_model = payload.get("voice_model_path")
    if not override_model:
        models_dir = DATA_ROOT / "models" / "piper"
        if not models_dir.is_dir():
            models_dir = DATA_ROOT / "models"
        available_models = sorted(models_dir.glob("*.onnx")) if models_dir.is_dir() else []
        if available_models:
            override_model = str(available_models[0].resolve())
    force = bool(payload.get("force", False))
    with connect(DB_PATH) as conn:
        conn.execute("UPDATE jobs SET status='running', progress=0.01, message='Preparing dialogue synthesis…', updated_at=? WHERE id=?", (now(), job_id))
        conn.commit()

    base = project_dir(project_id)
    check_disk_space(base, min_bytes=MIN_DISK_SPACE_TTS)
    manifest_path = base / "analysis" / "dialogue_manifest.json"
    translated_path = base / "analysis" / "translated_transcript.json"

    if not manifest_path.is_file() or not translated_path.is_file():
        raise RuntimeError("Run translation and build dialogue manifest before synthesis.")

    try:
        manifest = read_json_safe(manifest_path)
        translated = read_json_safe(translated_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Dialogue artifacts could not be read: {exc}") from exc

    units = manifest.get("units") or []
    total = len(units)
    from .work_progress import record_work
    record_work(base, "synthesis", 0, total, job_id=job_id, unit="lines")
    if total == 0:
        with connect(DB_PATH) as conn:
            conn.execute("UPDATE jobs SET status=CASE WHEN kind='auto_dub' THEN 'running' ELSE 'completed' END, progress=1.0, message='No dialogue units to synthesize.', updated_at=? WHERE id=?", (now(), job_id))
            conn.commit()
        return

    completed_count = 0
    failed_count = 0
    skipped_count = 0
    last_error: str | None = None

    from .resource_plan import synthesis_worker_limit
    from .system_diagnostics import _memory
    has_clones = any(((u.get('voice') or {}).get('profile') or {}).get('provider') in {'cloned', 'omnivoice'} for u in units)
    workers = synthesis_worker_limit(_memory().get('available_bytes'), os.cpu_count() or 1, cloned=has_clones)
    from .kaggle_tasks import project_for,waiting_error
    if project_for(base):workers=1
    items_to_process = []
    for idx, unit in enumerate(units):
        seg_idx = int(unit.get("segment_index", idx))
        char_name = unit.get("character_name") or "Unknown"
        out_file = base / "segments" / f"segment_{seg_idx:06d}_dub.wav"
        if not force and (unit.get("tts") or {}).get("status") == "completed" and out_file.is_file() and out_file.stat().st_size > 0:
            skipped_count += 1
            continue
        items_to_process.append((idx, seg_idx, unit, char_name))

    print(f"[OpenDub TTS] {len(items_to_process)} lines to synthesize ({skipped_count} skipped). Spawning {workers} parallel workers.", flush=True)

    if project_for(base) and items_to_process:
        from .kaggle_operations import prefetch_synthesis
        # Resolve the SAME source/voice/semantic gates as individual synthesis before upload.
        reconcile_short_speech_windows(base,manifest,translated.get('segments',[]))
        persist_dialogue_manifest(manifest_path,manifest)
        persist_dialogue_manifest(translated_path,translated)
        prepared=[]
        for _,seg_idx,unit,_ in items_to_process:
            configured=(unit.get('voice') or {}).get('status')=='configured' and (unit.get('voice') or {}).get('profile')
            values=prepare_synthesis_inputs(project_id,seg_idx,SynthesisRequest(voice_model_path=None if configured else override_model))
            if values['selected_clone_profile'] is None:raise RuntimeError('Kaggle synthesis currently requires a reviewed OmniVoice reference; local Piper is not silently substituted.')
            prepared.append({'text':values['text'],**values['selected_clone_profile'],
                'prosody':{**values['prosody'],'target_duration_sec':max(0,float(values['row'].get('end',0))-float(values['row'].get('start',0)))}})
        prefetch_synthesis(base,prepared,cancelled=lambda:job_cancel_requested(DB_PATH,job_id))

    progress_lock = threading.Lock()
    processed_count = 0
    cancelled = False
    provider_wait=threading.Event()

    def save_state():
        persist_dialogue_manifest(manifest_path, manifest)
        temp_t = translated_path.with_name(f"{translated_path.stem}.{uuid.uuid4().hex[:8]}.tmp")
        temp_t.write_text(json.dumps(translated, ensure_ascii=False, indent=2), encoding="utf-8")
        replace_with_retry(temp_t, translated_path)

    def process_item(item):
        nonlocal completed_count, failed_count, last_error, processed_count, cancelled
        if provider_wait.is_set():
            from .kaggle_tasks import RemoteWaiting
            raise RemoteWaiting('Kaggle batch is waiting; previously completed lines retained.')
        if cancelled or job_cancel_requested(DB_PATH, job_id):
            cancelled = True
            return

        idx, seg_idx, unit, char_name = item
        unit_voice = unit.get("voice") or {}
        unit_configured = unit_voice.get("status") == "configured" and unit_voice.get("profile")
        req = SynthesisRequest(voice_model_path=None if unit_configured else override_model)

        try:
            synthesize_segment(project_id=project_id, segment_index=seg_idx, body=req)
            with progress_lock:
                completed_count += 1
                # Sync in-memory unit
                if unit.get("tts"):
                    unit["tts"]["status"] = "completed"
        except Exception as exc:
            with progress_lock:
                if waiting_error(exc):provider_wait.set()
                raise_if_waiting(exc)
                failed_count += 1
                last_error = str(exc)
                if unit.get("tts"):
                    unit["tts"]["status"] = "error"
                    unit["tts"]["error"] = str(exc)
            print(f"[OpenDub TTS] Line {idx + 1} ({char_name}) failed: {exc}", flush=True)

        with progress_lock:
            processed_count += 1
            cur_done = skipped_count + processed_count
            progress = round(cur_done / total, 3)
            msg = f"Synthesizing {char_name}: line {cur_done}/{total} ({completed_count} synthesized, {workers} parallel workers)"
            if processed_count % 5 == 0 or processed_count == len(items_to_process):
                print(f"[OpenDub TTS] {msg}", flush=True)
                with connect(DB_PATH) as conn:
                    conn.execute("UPDATE jobs SET progress=?, message=?, updated_at=? WHERE id=?", (progress, msg, now(), job_id))
                    conn.commit()
                record_work(base, "synthesis", cur_done, total, job_id=job_id, unit="lines")

    if items_to_process:
        # If job already cancelled before threadpool
        if job_cancel_requested(DB_PATH, job_id):
            mark_job_cancelled(DB_PATH, job_id, "Synthesis cancelled by user.")
            return
        from .clone_runtime import warm_clone_batch
        from .speech_content import warm_content_batch
        with warm_clone_batch(has_clones), warm_content_batch(has_clones), ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(process_item, it) for it in items_to_process]
            for f in as_completed(futures):
                f.result()  # Unexpected worker failures must never disappear.

    if cancelled or job_cancel_requested(DB_PATH, job_id):
        mark_job_cancelled(DB_PATH, job_id, "Synthesis cancelled by user.")
        return

    final_msg = f"Synthesis complete: {completed_count} synthesized, {skipped_count} skipped, {failed_count} failed ({total} total)."
    print(f"\n[OpenDub TTS] {final_msg}\n", flush=True)
    with connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE jobs SET status=CASE WHEN kind='auto_dub' THEN 'running' ELSE 'completed' END, progress=1.0, message=?, payload=?, updated_at=? WHERE id=?",
            (
                final_msg,
                json.dumps({
                    "completed": completed_count,
                    "synthesized_count": completed_count,
                    "skipped": skipped_count,
                    "skipped_count": skipped_count,
                    "failed": failed_count,
                    "failed_count": failed_count,
                    "total": total,
                    "last_error": last_error,
                }, ensure_ascii=False),
                now(),
                job_id,
            )
        )
        conn.commit()

@app.post("/api/projects/{project_id}/synthesize-all")
def enqueue_batch_synthesis(project_id: str, body: SynthesisRequest | None = None) -> dict[str, str]:
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    payload = body.model_dump() if body else {}
    return {"job_id": create_job(project_id, "batch_synthesis", payload)}

@app.get("/api/projects/{project_id}/segments/{segment_index}/audio")
def get_segment_audio(project_id: str, segment_index: int):
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    path = project_dir(project_id) / "segments" / f"segment_{segment_index:06d}_dub.wav"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Synthesized audio not found for this segment")
    manifest = project_dir(project_id) / "analysis/dialogue_manifest.json"
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        unit = next((u for u in data.get("units", []) if u.get("segment_index") == segment_index), None)
        if unit and (unit.get("tts") or {}).get("status") != "completed":
            raise HTTPException(status_code=409, detail="Dialogue changed. Regenerate this voice clip before preview.")
        if unit and (unit.get("timing") or {}).get("status") == "completed" and not (unit.get("timing") or {}).get("duration_fit_limited"):
            candidate = (unit.get("loudness") or {}).get("normalized_audio") or (unit.get("timing") or {}).get("fit_audio")
            if candidate:
                candidate_path = Path(candidate).resolve()
                if project_dir(project_id).resolve() in candidate_path.parents and candidate_path.is_file():
                    path = candidate_path
    return FileResponse(path, media_type="audio/wav", filename=path.name)

def execute_full_render(job_id: str, project_id: str, cleanup: bool) -> None:
    with connect(DB_PATH) as conn:
        conn.execute("UPDATE jobs SET status='running',progress=0.02,message='Preparing final render…',updated_at=? WHERE id=?", (now(), job_id))
        conn.commit()
    try:
        item = get_project(DB_PATH, project_id)
        if not item or not item.get("source_path"):
            raise RuntimeError("Project source missing")
        base = project_dir(project_id).resolve()
        check_disk_space(base, min_bytes=MIN_DISK_SPACE_RENDER)
        source = (ROOT / item["source_path"]).resolve()
        if base not in source.parents or not source.is_file():
            raise RuntimeError("Source path is outside this project folder.")
        mix = base / "output" / "dubbed_audio_mix.wav"
        if not mix.is_file():
            raise RuntimeError("Build the dubbed audio mix first.")
        dialogue = base / "analysis/dialogue_manifest.json"
        if dialogue.is_file():
            from .auto_dub import verify_dialogue_ready
            verify_dialogue_ready(base)
            if dialogue.stat().st_mtime_ns > mix.stat().st_mtime_ns:
                raise RuntimeError("Dialogue changed after this mix. Build a new mix before rendering.")
        out = base / "output" / (safe_name(Path(source).stem) + "_dubbed.mp4")
        with connect(DB_PATH) as conn:
            conn.execute("UPDATE jobs SET progress=0.15,message='Muxing original video with dubbed audio…',updated_at=? WHERE id=?", (now(), job_id))
            conn.commit()
        if job_cancel_requested(DB_PATH, job_id):
            mark_job_cancelled(DB_PATH, job_id, "Render cancelled before FFmpeg started.")
            return
        result = mux_movie(source, mix, out, cancel_check=lambda: job_cancel_requested(DB_PATH, job_id))

        # Phase 18: Automated QA verification
        with connect(DB_PATH) as conn:
            conn.execute("UPDATE jobs SET progress=0.85,message='Running automated audio & video QA verification…',updated_at=? WHERE id=?", (now(), job_id))
            conn.commit()
        manifest_path = base / "analysis" / "dialogue_manifest.json"
        mix_manifest_path = base / "output" / "mix_manifest.json"
        qa_report = verify_render_qa(
            source=source,
            output=out,
            dialogue_manifest_path=manifest_path if manifest_path.is_file() else None,
            mix_manifest_path=mix_manifest_path if mix_manifest_path.is_file() else None,
        )
        result["qa_report"] = qa_report
        if qa_report.get("status") == "FAILED":
            raise RuntimeError(f"Automated render QA verification failed: {qa_report}")

        result["cleanup"] = cleanup_intermediates(base) if cleanup else {"removed": [], "errors": [], "preserved": ["All regenerable intermediates; cleanup disabled"]}
        with connect(DB_PATH) as conn:
            conn.execute("UPDATE jobs SET status=CASE WHEN kind='auto_dub' THEN 'running' ELSE 'completed' END,progress=1,message='Final render completed and QA verified.',payload=?,updated_at=? WHERE id=?", (json.dumps(result, ensure_ascii=False), now(), job_id))
            conn.execute("UPDATE projects SET status='rendered',updated_at=? WHERE id=?", (now(), project_id))
            conn.commit()
    except InterruptedError as exc:
        mark_job_cancelled(DB_PATH, job_id, str(exc))
    except Exception as exc:
        raise_if_waiting(exc)
        if job_cancel_requested(DB_PATH, job_id):
            mark_job_cancelled(DB_PATH, job_id)
            return
        with connect(DB_PATH) as conn:
            conn.execute("UPDATE jobs SET status='failed',message=?,updated_at=? WHERE id=?", (str(exc), now(), job_id))
            conn.execute("UPDATE projects SET status='render_failed',updated_at=? WHERE id=?", (now(), project_id))
            conn.commit()


def execute_background_preservation(job_id: str, project_id: str, payload: dict[str, Any]) -> None:
    with connect(DB_PATH) as conn:
        conn.execute("UPDATE jobs SET status='running',progress=0.05,message='Preserving background audio…',updated_at=? WHERE id=?", (now(), job_id))
        conn.commit()
    try:
        item = get_project(DB_PATH, project_id)
        if not item:
            raise RuntimeError("Project not found")
        base = project_dir(project_id).resolve()
        source_movie = (ROOT / item["source_path"]).resolve() if item.get("source_path") else None

        mode = payload.get("mode", "ducking")
        duck_db = float(payload.get("duck_db", -18.0))
        attack_ms = float(payload.get("attack_ms", 50.0))
        release_ms = float(payload.get("release_ms", 150.0))
        user_stem_path = payload.get("user_stem_path")
        model_filename = payload.get("model_filename")

        with connect(DB_PATH) as conn:
            conn.execute("UPDATE jobs SET progress=0.25,message='Ducking dialogue / separating stems…',updated_at=? WHERE id=?", (now(), job_id))
            conn.commit()

        result = preserve_background_audio(
            project_root=base,
            source_movie=source_movie,
            mode=mode,
            duck_db=duck_db,
            attack_ms=attack_ms,
            release_ms=release_ms,
            user_stem_path=user_stem_path,
            model_filename=model_filename,
        )
        with connect(DB_PATH) as conn:
            conn.execute("UPDATE jobs SET status='completed',progress=1.0,message='Background preservation complete.',payload=?,updated_at=? WHERE id=?", (json.dumps(result, ensure_ascii=False), now(), job_id))
            conn.commit()
    except Exception as exc:
        raise_if_waiting(exc)
        with connect(DB_PATH) as conn:
            conn.execute("UPDATE jobs SET status='failed',message=?,updated_at=? WHERE id=?", (str(exc), now(), job_id))
            conn.commit()

@app.post("/api/projects/{project_id}/segments/{segment_index}/fit")
def fit_segment(project_id: str, segment_index: int, body: FitRequest) -> dict[str, Any]:
    if not get_project(DB_PATH, project_id): raise HTTPException(status_code=404, detail="Project not found")
    path=project_dir(project_id)/"analysis"/"translated_transcript.json"
    manifest_path=project_dir(project_id)/"analysis"/"dialogue_manifest.json"
    if not path.exists(): raise HTTPException(status_code=409, detail="Translate transcript first")
    data=json.loads(path.read_text(encoding="utf-8")); rows=data.get("segments",[])
    row = find_translated_segment(rows, segment_index)
    if row is None: raise HTTPException(status_code=404, detail="Segment index not found")
    src=row.get("dub_audio")
    if not src: raise HTTPException(status_code=409, detail="Synthesize this segment first")
    source=Path(src); source=source if source.is_absolute() else project_dir(project_id)/source
    target=body.target_duration or max(0.01,float(row.get("end",0))-float(row.get("start",0)))
    out=project_dir(project_id)/"segments"/f"segment_{segment_index:06d}_fit.wav"
    try:
        result=fit_audio(source,out,target,body.max_speedup,body.max_slowdown, trim_silence=True, pad_short=True); row["fitted_audio"]=str(out)
        path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
        if manifest_path.is_file():
            status_timing = "needs_review" if result.get("duration_fit_limited") else "completed"
            update_dialogue_manifest_timing(
                manifest_path=manifest_path,
                segment_index=segment_index,
                status=status_timing,
                fit_audio=str(out),
                required_tempo=result.get("required_tempo"),
                applied_tempo=result.get("applied_tempo"),
                duration_fit_limited=bool(result.get("duration_fit_limited")),
            )
        return result
    except Exception as exc: raise HTTPException(status_code=400,detail=str(exc))

@app.post("/api/projects/{project_id}/segments/{segment_index}/normalize")
def normalize_segment(project_id: str, segment_index: int, target_lufs: float = -16) -> dict[str, Any]:
    if not get_project(DB_PATH, project_id): raise HTTPException(status_code=404, detail="Project not found")
    path=project_dir(project_id)/"analysis"/"translated_transcript.json"
    manifest_path=project_dir(project_id)/"analysis"/"dialogue_manifest.json"
    if not path.exists(): raise HTTPException(status_code=409, detail="Translate transcript first")
    data=json.loads(path.read_text(encoding="utf-8")); rows=data.get("segments",[])
    row = find_translated_segment(rows, segment_index)
    if row is None: raise HTTPException(status_code=404, detail="Segment index not found")
    src=row.get("fitted_audio") or row.get("dub_audio")
    if not src: raise HTTPException(status_code=409, detail="Synthesize the segment first")
    source=Path(src); source=source if source.is_absolute() else project_dir(project_id)/source
    out=project_dir(project_id)/"segments"/f"segment_{segment_index:06d}_normalized.wav"
    try:
        result=normalize_audio(source,out,float(target_lufs)); row["normalized_audio"]=str(out)
        path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
        if manifest_path.is_file():
            update_dialogue_manifest_loudness(
                manifest_path=manifest_path,
                segment_index=segment_index,
                status="completed",
                normalized_audio=str(out),
                target_lufs=float(target_lufs),
            )
        return result
    except Exception as exc: raise HTTPException(status_code=400,detail=str(exc))

def execute_batch_fit(job_id: str, project_id: str, payload: dict[str, Any] | None = None) -> None:
    """Worker job to fit all synthesized dialogue clips to their source time windows and normalize loudness."""
    payload = payload or {}
    max_speedup = float(payload.get("max_speedup", 1.25))
    max_slowdown = float(payload.get("max_slowdown", 0.82))
    normalize = bool(payload.get("normalize", True))
    target_lufs = float(payload.get("target_lufs", -16.0))
    force = bool(payload.get("force", False))

    with connect(DB_PATH) as conn:
        conn.execute("UPDATE jobs SET status='running', progress=0.01, message='Preparing dialogue timing fit…', updated_at=? WHERE id=?", (now(), job_id))
        conn.commit()

    base = project_dir(project_id)
    manifest_path = base / "analysis" / "dialogue_manifest.json"
    translated_path = base / "analysis" / "translated_transcript.json"

    if not manifest_path.is_file() or not translated_path.is_file():
        raise RuntimeError("Dialogue artifacts missing. Run analysis, translation and synthesis first.")

    try:
        manifest = read_json_safe(manifest_path)
        translated = read_json_safe(translated_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Dialogue artifacts could not be read: {exc}") from exc

    units = manifest.get("units") or []
    translated_rows = translated.get("segments") or []
    reconcile_short_speech_windows(base, manifest, translated_rows)
    persist_dialogue_manifest(manifest_path, manifest)
    total = len(units)
    from .work_progress import record_work
    record_work(base, "fit", 0, total, job_id=job_id, unit="lines")
    if total == 0:
        with connect(DB_PATH) as conn:
            conn.execute("UPDATE jobs SET status=CASE WHEN kind='auto_dub' THEN 'running' ELSE 'completed' END, progress=1.0, message='No dialogue units to fit.', updated_at=? WHERE id=?", (now(), job_id))
            conn.commit()
        return

    fitted_count = 0
    normalized_count = 0
    skipped_count = 0
    needs_review_count = 0
    failed_count = 0
    last_error: str | None = None

    cloud_fits={}
    from .kaggle_tasks import project_for
    if project_for(base):
        from .kaggle_operations import fit_batch
        cloud_fits=fit_batch(base,units,translated_rows,max_speedup,max_slowdown,normalize,target_lufs,force,
                             lambda:job_cancel_requested(DB_PATH,job_id))

    for idx, unit in enumerate(units):
        if job_cancel_requested(DB_PATH, job_id):
            mark_job_cancelled(DB_PATH, job_id, "Timing fit cancelled by user.")
            return

        seg_idx = int(unit.get("segment_index", idx))
        row = find_translated_segment(translated_rows, seg_idx)

        # Source speech artifact
        tts_info = unit.get("tts") or {}
        tts_audio = tts_info.get("audio_path") or (row.get("dub_audio") if row else None)
        if not tts_audio:
            candidate = base / "segments" / f"segment_{seg_idx:06d}_dub.wav"
            if candidate.is_file():
                tts_audio = str(candidate)

        if not tts_audio or not Path(tts_audio).is_file():
            skipped_count += 1
            record_work(base, "fit", idx + 1, total, job_id=job_id, unit="lines")
            continue

        fit_out = base / "segments" / f"segment_{seg_idx:06d}_fit.wav"
        norm_out = base / "segments" / f"segment_{seg_idx:06d}_normalized.wav"

        # Check resumability
        timing_status = (unit.get("timing") or {}).get("status")
        loudness_status = (unit.get("loudness") or {}).get("status")
        timing = unit.get("timing") or {}
        from .pipeline import timing_fit_matches_policy
        policy_current = timing_fit_matches_policy(unit, max_speedup, max_slowdown)
        if not force and policy_current and timing_status in {"completed", "needs_review"} and fit_out.is_file():
            if not normalize or (loudness_status == "completed" and norm_out.is_file()):
                skipped_count += 1
                if timing_status == "needs_review":
                    needs_review_count += 1
                record_work(base, "fit", idx + 1, total, job_id=job_id, unit="lines")
                continue

        progress = round(idx / total, 3)
        msg = f"Fitting timing line {idx + 1}/{total}"
        print(f"[OpenDub Timing] {msg}", flush=True)
        with connect(DB_PATH) as conn:
            conn.execute("UPDATE jobs SET progress=?, message=?, updated_at=? WHERE id=?", (progress, msg, now(), job_id))
            conn.commit()

        try:
            target_dur = float(unit.get("duration_sec") or 0.0)
            if target_dur <= 0 and row:
                target_dur = max(0.01, float(row.get("end", 0)) - float(row.get("start", 0)))
            if target_dur <= 0:
                target_dur = 1.0

            fit_res = (cloud_fits.get(seg_idx) or {}).get('fit') or fit_audio(Path(tts_audio), fit_out, target_dur, max_speedup, max_slowdown,
                                trim_silence=True, pad_short=True)
            status_timing = "needs_review" if fit_res.get("duration_fit_limited") else "completed"
            if fit_res.get("duration_fit_limited"):
                needs_review_count += 1
            else:
                fitted_count += 1

            if row:
                row["fitted_audio"] = str(fit_out)

            update_dialogue_manifest_timing(
                manifest_path=manifest_path,
                segment_index=seg_idx,
                status=status_timing,
                fit_audio=str(fit_out),
                required_tempo=fit_res.get("required_tempo"),
                applied_tempo=fit_res.get("applied_tempo"),
                duration_fit_limited=bool(fit_res.get("duration_fit_limited")),
                fit_policy_version=2,
                max_speedup=max_speedup, max_slowdown=max_slowdown,
            )

            # Loudness normalization
            if normalize:
                norm_res = (cloud_fits.get(seg_idx) or {}).get('normalize') or normalize_audio(fit_out, norm_out, target_lufs)
                normalized_count += 1
                if row:
                    row["normalized_audio"] = str(norm_out)
                update_dialogue_manifest_loudness(
                    manifest_path=manifest_path,
                    segment_index=seg_idx,
                    status="completed",
                    normalized_audio=str(norm_out),
                    target_lufs=target_lufs,
                )

        except Exception as exc:
            raise_if_waiting(exc)
            failed_count += 1
            last_error = str(exc)
            update_dialogue_manifest_timing(
                manifest_path=manifest_path,
                segment_index=seg_idx,
                status="error",
                error=str(exc)[:500],
            )
        record_work(base, "fit", idx + 1, total, job_id=job_id, unit="lines")

    serialized = json.dumps(translated, ensure_ascii=False, indent=2)
    if translated_path.read_text(encoding="utf-8") != serialized:
        temporary = translated_path.with_suffix(".json.tmp")
        temporary.write_text(serialized, encoding="utf-8")
        replace_with_retry(temporary, translated_path)

    final_msg = f"Timing & loudness complete: {fitted_count} fitted, {normalized_count} normalized, {skipped_count} skipped, {needs_review_count} need review, {failed_count} failed ({total} total)."
    print(f"\n[OpenDub Timing & Loudness] {final_msg}\n", flush=True)
    with connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE jobs SET status=CASE WHEN kind='auto_dub' THEN 'running' ELSE 'completed' END, progress=1.0, message=?, payload=?, updated_at=? WHERE id=?",
            (
                final_msg,
                json.dumps({
                    "completed": fitted_count,
                    "fitted_count": fitted_count,
                    "normalized_count": normalized_count,
                    "skipped_count": skipped_count,
                    "needs_review_count": needs_review_count,
                    "failed_count": failed_count,
                    "total": total,
                    "last_error": last_error,
                }, ensure_ascii=False),
                now(),
                job_id,
            )
        )
        conn.commit()

@app.post("/api/projects/{project_id}/fit-all")
def enqueue_batch_fit(project_id: str, body: FitAllRequest | None = None) -> dict[str, str]:
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    payload = body.model_dump() if body else {}
    return {"job_id": create_job(project_id, "batch_fit", payload)}

def execute_background_preservation(job_id: str, project_id: str, payload: dict[str, Any] | None = None) -> None:
    """Worker job to execute background audio preservation asynchronously."""
    payload = payload or {}
    with connect(DB_PATH) as conn:
        conn.execute("UPDATE jobs SET status='running', progress=0.05, message='Preserving background audio…', updated_at=? WHERE id=?", (now(), job_id))
        conn.commit()
    try:
        item = get_project(DB_PATH, project_id)
        if not item:
            raise RuntimeError("Project not found")
        base = project_dir(project_id).resolve()
        check_disk_space(base, min_bytes=MIN_DISK_SPACE_SEPARATION)
        source_movie = (ROOT / item["source_path"]).resolve() if item.get("source_path") else None
        mode = payload.get("mode", "uvr")
        duck_db = float(payload.get("duck_db", -18.0))
        attack_ms = float(payload.get("attack_ms", 50.0))
        release_ms = float(payload.get("release_ms", 150.0))
        user_stem = payload.get("user_stem_path")
        user_stem_path = Path(user_stem) if user_stem else None
        model_filename = payload.get("model_filename")
        from .work_progress import track
        with track(base, job_id, "background", "chunks"):
            res = preserve_background_audio(
                project_root=base,
                source_movie=source_movie,
                mode=mode,
                duck_db=duck_db,
                attack_ms=attack_ms,
                release_ms=release_ms,
                user_stem_path=user_stem_path,
                model_filename=model_filename,
                separation_workers=payload.get('separation_workers'),
            )
        with connect(DB_PATH) as conn:
            conn.execute("UPDATE jobs SET status='completed', progress=1.0, message='Background audio preserved.', payload=?, updated_at=? WHERE id=?", (json.dumps(res, ensure_ascii=False), now(), job_id))
            conn.commit()
    except Exception as exc:
        with connect(DB_PATH) as conn:
            conn.execute("UPDATE jobs SET status='failed', message=?, updated_at=? WHERE id=?", (str(exc), now(), job_id))
            conn.commit()
        raise

@app.post("/api/projects/{project_id}/background/preserve")
def preserve_background_endpoint(project_id: str, body: BackgroundPreservationRequest | None = None) -> dict[str, Any]:
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    item = get_project(DB_PATH, project_id)
    base = project_dir(project_id).resolve()
    try:
        check_disk_space(base, min_bytes=MIN_DISK_SPACE_SEPARATION)
    except InsufficientDiskSpaceError as exc:
        raise HTTPException(status_code=507, detail=str(exc)) from exc
    source_movie = (ROOT / item["source_path"]).resolve() if item and item.get("source_path") else None
    req = body or BackgroundPreservationRequest()
    try:
        return preserve_background_audio(
            project_root=base,
            source_movie=source_movie,
            mode=req.mode,
            duck_db=req.duck_db,
            attack_ms=req.attack_ms,
            release_ms=req.release_ms,
            user_stem_path=req.user_stem_path,
            model_filename=req.model_filename,
            strict_separation=req.mode == "separation",
            separation_workers=req.separation_workers,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@app.get("/api/projects/{project_id}/background/preview")
def preview_background(project_id: str):
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    path = project_dir(project_id) / "output" / "background_preserved.wav"
    if not path.is_file():
        alt = project_dir(project_id) / "analysis" / "separation" / "background.wav"
        if alt.is_file():
            path = alt
        else:
            raise HTTPException(status_code=404, detail="Preserved background audio not found. Run background preservation first.")
    return FileResponse(path, media_type="audio/wav", filename=path.name)

@app.post("/api/projects/{project_id}/mix")
def build_mix(project_id: str, body: MixRequest) -> dict[str, Any]:
    if not get_project(DB_PATH, project_id): raise HTTPException(status_code=404, detail="Project not found")
    base=project_dir(project_id); background=None
    if (base / "analysis/dialogue_manifest.json").is_file():
        from .auto_dub import verify_dialogue_ready
        try:
            verify_dialogue_ready(base)
        except (RuntimeError, ValueError, OSError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        check_disk_space(base, min_bytes=MIN_DISK_SPACE_TTS)
    except InsufficientDiskSpaceError as exc:
        raise HTTPException(status_code=507, detail=str(exc)) from exc
    if body.background_path:
        p=Path(body.background_path); background=p if p.is_absolute() else (base/p).resolve()
        if base.resolve() not in background.parents or not background.is_file(): raise HTTPException(status_code=400, detail="Background audio must be a file inside the project")
    if background is None and not (base / "output/background_preserved.wav").is_file():
        raise HTTPException(status_code=409, detail="Preserve the original music and effects before building the mix.")
    out=base/"output"/"dubbed_audio_mix.wav"
    try: return mix_project(base,background,out,body.target_lufs,duck_background=body.duck_background,
                           protect_dialogue_peaks=body.protect_dialogue_peaks)
    except Exception as exc:
        raise_if_waiting(exc)
        raise HTTPException(status_code=400,detail=str(exc))

@app.get("/api/projects/{project_id}/mix/preview")
def preview_mix(project_id: str):
    if not get_project(DB_PATH, project_id): raise HTTPException(status_code=404, detail="Project not found")
    path=project_dir(project_id)/"output"/"dubbed_audio_mix.wav"
    if not path.exists(): raise HTTPException(status_code=404, detail="Build the mix first")
    return FileResponse(path,media_type="audio/wav",filename=path.name)

@app.post("/api/projects/{project_id}/render")
def start_render(project_id: str, body: RenderRequest) -> dict[str, str]:
    if not get_project(DB_PATH,project_id): raise HTTPException(status_code=404,detail="Project not found")
    if not (project_dir(project_id)/"output"/"dubbed_audio_mix.wav").is_file(): raise HTTPException(status_code=409,detail="Build the dubbed audio mix first")
    return {"job_id": create_job(project_id,"full_render",{"cleanup_intermediates":body.cleanup_intermediates})}

@app.get("/api/projects/{project_id}/render/download")
def download_render(project_id: str):
    return get_final_video(project_id, download=True)

@app.get("/api/projects/{project_id}/render/qa")
def get_render_qa(project_id: str) -> dict[str, Any]:
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    qa_path = project_dir(project_id) / "output" / "render_qa_report.json"
    if not qa_path.is_file():
        raise HTTPException(status_code=404, detail="Render QA report not found. Complete a render first.")
    try:
        return json.loads(qa_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read QA report: {exc}")

@app.get("/api/worker/queue")
def worker_queue() -> dict[str, Any]:
    with connect(DB_PATH) as conn:
        rows=conn.execute("SELECT status,COUNT(*) AS count FROM jobs GROUP BY status").fetchall()
    return {"counts":{r["status"]:r["count"] for r in rows},"lease_seconds":int(os.getenv("OPENDUB_JOB_LEASE_SECONDS","120"))}

@app.get("/api/worker/health")
def worker_health() -> dict[str, Any]:
    with connect(DB_PATH) as conn:
        row=conn.execute("SELECT COUNT(*) AS count, MAX(last_seen_at) AS last_seen_at FROM worker_heartbeats").fetchone()
    return {"active_workers":int(row["count"] or 0),"latest_heartbeat":row["last_seen_at"],"service":"opendub-worker"}

@app.get("/api/projects/{project_id}/analysis")
def get_analysis_summary(project_id: str, limit: int = 250) -> dict[str, Any]:
    """Return a bounded full-analysis summary for the UI without loading the whole timeline."""
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    limit = max(1, min(limit, 1000))
    base = project_dir(project_id) / "analysis"
    manifest_path = base / "analysis_manifest.json"
    timeline_path = base / "timeline.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Full analysis has not completed yet")
    try:
        manifest = read_json_safe(manifest_path)
        timeline = json.loads(timeline_path.read_text(encoding="utf-8")) if timeline_path.exists() else {}
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Analysis artifacts could not be read: {exc}") from exc
    segments = timeline.get("segments", [])
    scenes = timeline.get("scenes", [])
    registry = read_character_registry(project_id)
    character_map = {
        str(row.get("character_id")): row.get("display_name")
        for row in (registry.get("characters") or [])
        if row.get("character_id")
    }
    segments = [
        {**segment, "character_name": character_map.get(str(segment.get("character_id")))}
        for segment in segments
    ]
    return {
        "status": manifest.get("status"),
        "manifest": manifest,
        "summary": {
            "segments": len(segments),
            "scenes": len(scenes),
            "language": timeline.get("language"),
            "source_media": timeline.get("source_media"),
            "analysis_gaps": timeline.get("analysis_gaps", []),
        },
        "stage_status": {name: data.get("status") for name, data in (manifest.get("stages") or {}).items()},
        "segments": segments[:limit],
        "scenes": scenes[:limit],
        "truncated": len(segments) > limit or len(scenes) > limit,
    }

@app.get("/api/projects/{project_id}/transcript")
def get_transcript(project_id: str) -> dict[str, Any]:
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    path = project_dir(project_id) / "analysis" / "transcript.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Transcript not generated yet")
    return json.loads(path.read_text(encoding="utf-8"))

@app.get("/api/projects/{project_id}/separation")
def get_separation(project_id: str) -> dict[str, Any]:
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    path = project_dir(project_id) / "analysis" / "separation.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Separation has not been run yet")
    return json.loads(path.read_text(encoding="utf-8"))

@app.get("/api/projects/{project_id}/diarization")
def get_diarization(project_id: str) -> dict[str, Any]:
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    path = project_dir(project_id) / "analysis" / "diarization.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Diarization not generated yet")
    return json.loads(path.read_text(encoding="utf-8"))

@app.get("/api/projects/{project_id}/scenes")
def get_scenes(project_id: str) -> list[dict[str, Any]]:
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    path = project_dir(project_id) / "analysis" / "scenes.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Scene detection not run yet")
    return json.loads(path.read_text(encoding="utf-8"))

@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "opendub-studio", "version": app.version}


@app.get("/api/system/diagnostics")
def system_diagnostics(fresh: bool = False) -> dict[str, Any]:
    """Return cached startup diagnostics instantly, or refresh on demand."""
    global LAST_DIAGNOSTICS
    if LAST_DIAGNOSTICS is not None and not fresh:
        return LAST_DIAGNOSTICS
    try:
        LAST_DIAGNOSTICS = collect_diagnostics(DATA_ROOT, app.version)
        return LAST_DIAGNOSTICS
    except Exception as exc:
        print(f"[OpenDub diagnostics] ERROR: {type(exc).__name__}: {exc}", flush=True)
        raise HTTPException(status_code=500, detail=f"System diagnostics failed: {type(exc).__name__}: {exc}") from exc

@app.get("/api/system/support-bundle")
def download_support_bundle() -> dict[str, Any]:
    """Generate and return a sanitized, secret-free support diagnostics bundle."""
    return generate_support_bundle(DATA_ROOT, DB_PATH, app.version)


@app.get("/api/projects/{project_id}/processing-plan")
def project_processing_plan(project_id: str, model_size: str = "small", workload: str = "analysis", bounded_analysis: bool = False) -> dict[str, Any]:
    """Fresh RAM/disk admission with separately verified runtime capabilities."""
    from .system_diagnostics import _memory, _gpu
    from .resource_plan import plan_resources
    item = get_project(DB_PATH, project_id)
    if not item:
        raise HTTPException(status_code=404, detail="Project not found")
    from .kaggle_tasks import project_for
    if project_for(project_dir(project_id)):
        from .kaggle_operations import remote_plan
        return remote_plan(project_dir(project_id),float(item.get('duration_ms') or 0)/1000)
    report = dict(system_diagnostics())
    report["memory"] = _memory()
    report["gpu"] = _gpu()
    disk = shutil.disk_usage(project_dir(project_id))
    report["disk"] = {"free_bytes": disk.free}
    source = (ROOT / item["source_path"]).resolve() if item.get("source_path") else None
    return plan_resources(report, float(item.get("duration_ms") or 0) / 1000,
                          source.stat().st_size if source and source.is_file() else 0, model_size=model_size, workload=workload, bounded_analysis=bounded_analysis)

@app.get("/api/projects")
def projects() -> list[dict[str, Any]]:
    return list_projects(DB_PATH)

@app.post("/api/projects")
def create_project(body: ProjectCreate) -> dict[str, Any]:
    project_id = str(uuid.uuid4())
    path = project_dir(project_id)
    (path / "source").mkdir(parents=True, exist_ok=True)
    (path / "analysis").mkdir(exist_ok=True)
    (path / "characters").mkdir(exist_ok=True)
    (path / "segments").mkdir(exist_ok=True)
    (path / "cache").mkdir(exist_ok=True)
    (path / "output").mkdir(exist_ok=True)

    timestamp = now()
    with connect(DB_PATH) as conn:
        conn.execute(
            """INSERT INTO projects
            (id, name, source_path, source_size, duration_ms, source_language, target_language, status, created_at, updated_at)
            VALUES (?, ?, NULL, 0, NULL, 'Auto Detect', ?, 'created', ?, ?)""",
            (project_id, body.name, body.target_language, timestamp, timestamp),
        )
        conn.commit()
    return get_project(DB_PATH, project_id) or {}

@app.get("/api/projects/{project_id}")
def project(project_id: str) -> dict[str, Any]:
    item = get_project(DB_PATH, project_id)
    if not item:
        raise HTTPException(status_code=404, detail="Project not found")
    with connect(DB_PATH) as conn:
        jobs = conn.execute("SELECT * FROM jobs WHERE project_id=? ORDER BY created_at DESC", (project_id,)).fetchall()
    return {**item, "jobs": [dict(r) for r in jobs]}

@app.patch("/api/projects/{project_id}")
def rename_project(project_id: str, body: ProjectRename) -> dict[str, Any]:
    if not get_project(DB_PATH, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Project name cannot be empty")
    with connect(DB_PATH) as conn:
        conn.execute("UPDATE projects SET name=?, updated_at=? WHERE id=?", (name, now(), project_id))
        conn.commit()
    return get_project(DB_PATH, project_id) or {}

@app.post("/api/projects/{project_id}/source")
async def upload_source(project_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    item = get_project(DB_PATH, project_id)
    if not item:
        raise HTTPException(status_code=404, detail="Project not found")
    with connect(DB_PATH) as conn:
        active = conn.execute("SELECT id FROM jobs WHERE project_id=? AND status IN ('queued','running','retrying') LIMIT 1", (project_id,)).fetchone()
    if active:
        raise HTTPException(status_code=409, detail="Cancel or finish the active job before replacing the source video.")
    from .kaggle_jobs import active_jobs
    if active_jobs(project_dir(project_id)):
        raise HTTPException(409,'Reconcile active/detached Kaggle work before replacing its source. Existing remote results and checkpoints must keep their source identity.')

    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}:
        raise HTTPException(status_code=400, detail="Unsupported video format")

    source_dir = project_dir(project_id) / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    try:
        check_disk_space(source_dir, min_bytes=MIN_DISK_SPACE_UPLOAD)
    except InsufficientDiskSpaceError as exc:
        raise HTTPException(status_code=507, detail=str(exc)) from exc

    target = source_dir / f"original{ext}"
    pending = source_dir / f".upload-{uuid.uuid4().hex}{ext}"
    try:
        with pending.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                out.write(chunk)
        validate_media_file(pending)
        metadata = ffprobe(pending)
        pending.replace(target)
    except InvalidMediaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        pending.unlink(missing_ok=True)
    for old in source_dir.glob("original.*"):
        if old.is_file() and old != target:
            old.unlink()

    reset_project_analysis_state(project_id, reset_characters=True)
    relative = target.relative_to(ROOT).as_posix()
    timestamp = now()
    with connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE projects SET source_path=?, source_size=?, duration_ms=?, source_language=NULL, status='uploaded', updated_at=? WHERE id=?",
            (relative, target.stat().st_size, metadata.get("duration_ms"), timestamp, project_id),
        )
        conn.commit()
    return project(project_id)

@app.post("/api/projects/{project_id}/analyze")
def analyze_project(project_id: str) -> dict[str, str]:
    item = get_project(DB_PATH, project_id)
    if not item or not item.get("source_path"):
        raise HTTPException(status_code=400, detail="Upload a movie first")
    job_id = create_job(project_id, "media_analysis")
    return {"job_id": job_id}

@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, Any]:
    item = request_job_cancel(DB_PATH, job_id)
    if not item:
        raise HTTPException(status_code=404, detail="Job not found")
    return item

@app.get("/api/jobs/{job_id}")
def job(job_id: str) -> dict[str, Any]:
    item = get_job(DB_PATH, job_id)
    if not item:
        raise HTTPException(status_code=404, detail="Job not found")
    return item

class AutoDubRequest(BaseModel):
    review_before_dubbing: bool = True
    separation_workers: int | None = Field(default=None, ge=1, le=256)
    audio_only: bool = True
    conversational_hindi: bool = True
    automatic_voice_selection: bool = True
    separation_model: str = "vocals_mel_band_roformer.ckpt"
    transcribe_vocals: bool = True
    source_language: str = "auto"
    target_language: str = "hi"
    use_demographics: bool = False
    force_restart: bool = False
    experimental_chunk_asr: bool = False
    visible_helpers: bool = False
    model_size: str = Field(default="small", pattern="^(tiny|base|small|medium|large-v3)$")
    voice_model_path: str | None = None


AUTO_DUB_STAGES = [
    {"key": "frame_audio_extraction", "title": "Audio Extraction & Source Check", "activeLabel": "Extracting source audio & checking media..."},
    {"key": "language_detection", "title": "Automatic Source Language Detection", "activeLabel": "Auto-detecting source language..."},
    {"key": "character_voice_matching", "title": "Speaker & Voice Matching", "activeLabel": "Matching voices to detected speakers..."},
    {"key": "hindi_translation", "title": "Hindi Dialogue Translation & Adaptation", "activeLabel": "Hindi Dialogue Translation & Adaptation..."},
    {"key": "multi_character_tts", "title": "Multi-Character Neural TTS Generation", "activeLabel": "Generating multi-character Hindi TTS..."},
    {"key": "vocal_removal_render", "title": "Vocal Separation, BGM/SFX Sync & Final Video Render", "activeLabel": "Muting original vocals (preserving BGM/SFX) & rendering video..."},
]

_AUTO_DUB_STATUS: dict[str, dict[str, Any]] = {}
_AUTO_DUB_LOCK = threading.Lock()


def _set_auto_dub_stage(project_id: str, stage_idx: int, stage_status: str, percent: float, label: str = ""):
    with _AUTO_DUB_LOCK:
        if project_id not in _AUTO_DUB_STATUS:
            return
        st = _AUTO_DUB_STATUS[project_id]
        st["progress_percent"] = round(percent, 1)
        start = st.get("start_time", time.time())
        elapsed = max(0.0, time.time() - start)
        st["elapsed_seconds"] = round(elapsed, 1)
        if percent > 0:
            total_est = (elapsed / (percent / 100.0))
            st["eta_seconds"] = max(0.0, round(total_est - elapsed, 1))
        if 0 <= stage_idx < len(st["stages"]):
            st["current_stage"] = st["stages"][stage_idx]["key"]
            st["current_stage_label"] = label or st["stages"][stage_idx].get("activeLabel", st["stages"][stage_idx]["title"])
            st["stages"][stage_idx]["status"] = stage_status
            st["stages"][stage_idx]["percent"] = 100.0 if stage_status == "completed" else round(percent, 1)
            for prev in range(stage_idx):
                st["stages"][prev]["status"] = "completed"
                st["stages"][prev]["percent"] = 100.0


@app.post("/api/projects/{project_id}/auto-dub")
def start_auto_dub(project_id: str, body: AutoDubRequest | None = None) -> dict[str, Any]:
    from .auto_dub import read_status, save_status
    item = get_project(DB_PATH, project_id)
    if not item:
        raise HTTPException(status_code=404, detail="Project not found")
    if not item.get("source_path"):
        raise HTTPException(status_code=400, detail="Upload a source movie first")
    base = project_dir(project_id)
    req = body or AutoDubRequest()
    from .compute_settings import read_settings
    if read_settings(base)['provider']=='kaggle':
        from .kaggle_operations import remote_plan
        plan=remote_plan(base)
        if not plan['admitted']:raise HTTPException(409,' '.join(plan['reasons']))
    with _AUTO_DUB_LOCK:
        existing = read_status(base)
        active_job = get_job(DB_PATH, existing["job_id"]) if existing.get("job_id") else None
        if active_job and active_job["status"] in {"queued", "claimed", "running", "retrying"}:
            return get_auto_dub_status(project_id)
        resuming = existing.get("status") in {"failed", "cancelled", "awaiting_review", "waiting"} and not req.force_restart
        options = (existing.get("options") or req.model_dump()) if resuming else req.model_dump()
        if resuming:
            for field in ('visible_helpers','separation_workers'):
                if field in req.model_fields_set:
                    options = {**options,field:getattr(req,field)}
        if not resuming:
            (base / "work_progress.json").unlink(missing_ok=True)
        status = {
            "project_id": project_id, "status": "queued", "options": options,
            "progress_percent": 0, "elapsed_seconds": 0, "eta_seconds": None,
            "detected_language": req.source_language, "target_language": req.target_language,
            "current_stage": AUTO_DUB_STAGES[0]["key"], "current_stage_label": "Queued for processing",
            "stages": [dict(stage, status="pending", percent=0) for stage in AUTO_DUB_STAGES],
            "auto_download_ready": False, "rendered_video_url": None, "error": None,
        }
        if resuming:
            status.update(
                stages=existing.get("stages") or status["stages"],
                progress_percent=existing.get("progress_percent", 0),
                current_stage=existing.get("current_stage", status["current_stage"]),
                current_stage_label="Queued to resume the failed stage; completed files retained",
                detected_language=existing.get("detected_language", req.source_language),
                resuming=True,
            )
        status["job_id"] = str(uuid.uuid4())
        save_status(base, status)
        create_job(project_id, "auto_dub", options, job_id=status["job_id"])
    return status


@app.get("/api/projects/{project_id}/auto-dub-status")
def get_auto_dub_status(project_id: str) -> dict[str, Any]:
    from .auto_dub import read_status
    from .work_progress import read_work
    item = get_project(DB_PATH, project_id)
    if not item:
        raise HTTPException(status_code=404, detail="Project not found")
    status = read_status(project_dir(project_id))
    if status:
        task = get_job(DB_PATH, status["job_id"]) if status.get("job_id") else None
        if task and task["status"] in {"failed", "cancelled"}:
            status.update(status=task["status"], error=task.get("message"), auto_download_ready=False)
        if status.get("status") == "running":
            status["elapsed_seconds"] = round(time.time() - status.get("start_time", time.time()), 1)
        work = read_work(project_dir(project_id))
        if work and work.get("job_id") == status.get("job_id"):
            status["work"] = work
            status["progress_percent"] = max(status.get("progress_percent", 0), work.get("overall_percent", 0))
            status["eta_seconds"] = work.get("eta_seconds") if status.get("status") == "running" else None
            if status.get("status") == "running":
                status["current_stage_label"] = f"{work['phase'].replace('_', ' ').title()}: {work['completed']:g}/{work['total']:g} {work['unit']} processed; {work['remaining']:g} remaining"
        if status.get("status") == "completed" and status.get("auto_download_ready"):
            try:
                final=get_final_video(project_id)
                final_path=getattr(final,'path',None)
                if isinstance(final_path,(str,Path)) and Path(final_path).is_file():
                    status['rendered_video_revision']=str(Path(final_path).stat().st_mtime_ns)
            except HTTPException as exc:
                status.update(status="failed", auto_download_ready=False, error=str(exc.detail), current_stage_label=str(exc.detail))
        return {key: value for key, value in status.items() if key != "options"}
    return {
        "project_id": project_id, "status": "idle", "progress_percent": 0,
        "elapsed_seconds": 0, "eta_seconds": None, "current_stage_label": "Ready to start",
        "detected_language": item.get("source_language") or "auto",
        "target_language": item.get("target_language") or "hi",
        "stages": [dict(stage, status="pending", percent=0) for stage in AUTO_DUB_STAGES],
        "rendered_video_url": None, "auto_download_ready": False, "error": None,
    }


@app.get("/api/projects/{project_id}/final-video")
def get_final_video(project_id: str, download: bool = False):
    item = get_project(DB_PATH, project_id)
    if not item:
        raise HTTPException(status_code=404, detail="Project not found")

    base = project_dir(project_id)
    folder = base / "output"
    files: list[Path] = []
    if folder.exists():
        files.extend(sorted(folder.glob("*_dubbed.mp4"), key=lambda p: p.stat().st_mtime, reverse=True))
    if not files:
        raise HTTPException(status_code=404, detail="Final dubbed video not found. Run render first.")

    target = files[0]
    qa_path = folder / "render_qa_report.json"
    try:
        qa = json.loads(qa_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(status_code=409, detail="Render QA is unavailable. Render and verify the movie before download.")
    if qa.get("status") != "PASSED":
        raise HTTPException(status_code=409, detail="Render QA did not pass. Review the output report.")
    inputs = [base / "analysis/dialogue_manifest.json", folder / "dubbed_audio_mix.wav", folder / "background_preserved.wav"]
    if any(path.is_file() and path.stat().st_mtime_ns > target.stat().st_mtime_ns for path in inputs):
        raise HTTPException(status_code=409, detail="Dialogue or audio changed after this render. Mix and render again before download.")
    media_type = "video/x-matroska" if target.suffix.lower() == ".mkv" else "video/mp4"
    headers = {}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{target.name}"'
    return FileResponse(target, media_type=media_type, filename=target.name, headers=headers)


def studio_media_paths(project_id: str) -> dict[str, Path]:
    item = get_project(DB_PATH, project_id)
    if not item:
        raise HTTPException(status_code=404, detail="Project not found")
    base = project_dir(project_id).resolve()
    paths = {
        "vocals": base / "analysis/separation/vocals.wav",
        "background": base / "output/background_preserved.wav",
        "mix": base / "output/dubbed_audio_mix.wav",
    }
    if item.get("source_path"):
        paths["source"] = (ROOT / item["source_path"]).resolve()
    return {key: path for key, path in paths.items() if base in path.resolve().parents and path.is_file()}


@app.get("/api/projects/{project_id}/media-assets")
def studio_media_assets(project_id: str) -> dict[str, Any]:
    return {"assets": {key: {"url": f"/api/projects/{project_id}/media/{key}?v={path.stat().st_mtime_ns}", "bytes": path.stat().st_size}
                       for key, path in studio_media_paths(project_id).items()}}


@app.get("/api/projects/{project_id}/media/{kind}")
def studio_media_preview(project_id: str, kind: str):
    path = studio_media_paths(project_id).get(kind)
    if path is None:
        raise HTTPException(status_code=404, detail="Audio or video is not ready yet. Run its pipeline stage first.")
    return FileResponse(path)


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str) -> dict[str, bool]:
    folder = project_dir(project_id).resolve()
    if folder.parent != PROJECTS_ROOT.resolve():
        raise HTTPException(status_code=400, detail="Invalid project path")
    from .kaggle_jobs import active_jobs
    if active_jobs(folder):
        raise HTTPException(409,'Reconcile active/detached Kaggle notebooks before deleting this project. Remote runs are not cancelled by deleting a local folder.')
    archive = DATA_ROOT / "deleted_projects" / f"{project_id}-{uuid.uuid4()}"
    moved = False
    with connect(DB_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE")
        item = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not item:
            raise HTTPException(status_code=404, detail="Project not found")
        if conn.execute("SELECT 1 FROM jobs WHERE project_id=? AND status IN ('queued','running','retrying') LIMIT 1", (project_id,)).fetchone():
            raise HTTPException(status_code=409, detail="Stop active processing before removing this project.")
        archive.mkdir(parents=True)
        (archive / "project.json").write_text(json.dumps(dict(item), ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            if folder.exists():
                shutil.move(str(folder), str(archive / "files"))
                moved = True
            conn.execute("DELETE FROM jobs WHERE project_id=?", (project_id,))
            conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
            conn.commit()
        except Exception:
            if moved:
                shutil.move(str(archive / "files"), str(folder))
            raise
    return {"deleted": True}

@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(WEB_ROOT / "favicon.svg", media_type="image/svg+xml")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html")
