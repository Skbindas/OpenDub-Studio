"""Measured per-phase work and a durable monotonic dashboard percentage."""
import json
import time
from contextvars import ContextVar
from contextlib import contextmanager
from pathlib import Path
from .atomic_files import replace_with_retry

PHASES = {
    "source_media_validate": (0, 2), "analysis_preflight": (2, 4),
    "audio_extract": (4, 6), "audio_profile": (6, 8), "scene_detect": (8, 10),
    "vocal_separation": (10, 24), "transcription": (24, 35),
    "speaker_diarization": (35, 42), "scene_context": (42, 44),
    "translation": (45, 60), "synthesis": (60, 70), "fit": (70, 82),
    "background": (82, 86), "mix": (86, 92), "render": (92, 99),
}
_context = ContextVar("opendub_work", default=None)


def read_work(base: Path) -> dict:
    try:
        return json.loads((base / "work_progress.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def record_work(base: Path, phase: str, completed: float, total: float, *, job_id=None, unit="items", now=None) -> dict:
    now = time.time() if now is None else now
    previous = read_work(base)
    start = previous.get("phase_started_at", now) if previous.get("phase") == phase and previous.get("job_id") == job_id else now
    completed = max(0, min(completed, total)) if total > 0 else 0
    elapsed = max(0, now - start)
    eta = round((total-completed) * elapsed / completed, 1) if completed > 0 and elapsed >= 1 else None
    lo, hi = PHASES.get(phase, (0, 0))
    overall = lo + (hi-lo) * completed / total if total > 0 else lo
    data = {"phase":phase,"completed":completed,"total":total,"remaining":max(0,total-completed),
            "unit":unit,"job_id":job_id,"phase_started_at":start,"updated_at":now,
            "overall_percent":round(max(previous.get("overall_percent",0),overall),2),
            "eta_seconds":eta,"eta_scope":"current_stage","phase_elapsed_seconds":round(elapsed,1)}
    base.mkdir(parents=True,exist_ok=True)
    target=base / "work_progress.json"
    import uuid
    temporary=base / f"work_progress.{uuid.uuid4().hex[:8]}.tmp"
    try:
        temporary.write_text(json.dumps(data),encoding="utf-8")
        replace_with_retry(temporary,target)
    except Exception:
        pass
    finally:
        temporary.unlink(missing_ok=True)
    if previous.get("phase") != phase or int(previous.get("overall_percent", -1)) != int(data["overall_percent"]):
        remaining = f"~ {eta:g}s remaining in stage" if eta is not None else "stage ETA calibrating"
        print(f"[OpenDub progress] {data['overall_percent']:g}% | {phase}: {completed:g}/{total:g} {unit} processed | {remaining}", flush=True)
    return data


@contextmanager
def track(base: Path, job_id: str, phase: str, unit="items"):
    token=_context.set((base,job_id,phase,unit))
    try:
        yield
    finally:
        _context.reset(token)


def emit(completed: float, total: float) -> None:
    context=_context.get()
    if context:
        base,job_id,phase,unit=context
        record_work(base,phase,completed,total,job_id=job_id,unit=unit)


def current_context():
    return _context.get()
