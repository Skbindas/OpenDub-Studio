"""Genuine reference-conditioned synthesis in an isolated optional environment."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import threading
from contextlib import contextmanager

from .voice_bank_quality import fingerprint

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def clone_worker_slot():
    """One memory-heavy clone worker across app/CLI; OS releases locks on crashes."""
    lock_path = ROOT / "runtime/voice-bank-audit/clone-worker.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock:
        if lock_path.stat().st_size == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("Another clone worker is running; saved project data is retained. Resume when it finishes.") from exc
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def clone_python() -> Path:
    configured = os.getenv("OPENDUB_CLONE_PYTHON")
    path = Path(configured) if configured else ROOT / "runtime/clone-env" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return path


def runtime_status() -> dict:
    path = clone_python()
    completed = []
    data_root=ROOT / os.getenv("OPENDUB_DATA_DIR", "runtime")
    for manifest in sorted((data_root / "voice-bank-audit/records").glob("*.json")):
        try:
            record=json.loads(manifest.read_text(encoding="utf8"));data=record.get("clone",{})
            output=Path(data.get("file", ""))
            if (data.get("reference_conditioned") and data.get("status")=="completed"
                and data.get("reference_sha256")==record.get("sha256") and output.is_file()
                and fingerprint(output)==data.get("output_sha256")):
                completed.append(data)
        except (ValueError, OSError):
            continue
    return {"provider": "omnivoice", "model": "k2-fsa/OmniVoice", "environment_available": path.is_file(),
            "status": ("auditions_available_review_required" if completed else "pilot_required") if path.is_file() else "unavailable",
            "completed_auditions": len(completed), "last_device": completed[-1].get("device") if completed else None,
            "reference_seconds": {"min": 3, "max": 10, "preferred_min": 8},
            "emotion_support": "reference_delivery_only; dialogue emotion controls require measured validation",
            "notice": "An installed environment is not proof of a loaded model or a verified cloned voice."}


_warm_process = None
_warm_log = None
_warm_enabled = False
_warm_guard = threading.Lock()


@contextmanager
def warm_clone_batch(enabled=True):
    global _warm_enabled, _warm_process, _warm_log
    _warm_guard.acquire()
    _warm_enabled = enabled
    try:
        yield
    finally:
        _warm_enabled = False
        if _warm_process is not None:
            _warm_process.stdin.close()
            try:
                _warm_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _warm_process.terminate()
                _warm_process.wait(timeout=10)
            _warm_process = None
        if _warm_log is not None:
            _warm_log.close()
            _warm_log = None
        _warm_guard.release()


def _warm_generate(request_path: Path, python: Path):
    global _warm_process, _warm_log
    if _warm_process is None or _warm_process.poll() is not None:
        if _warm_log is not None:
            _warm_log.close()
        _warm_log = (ROOT / "runtime/clone-batch.log").open("a", encoding="utf-8")
        _warm_process = subprocess.Popen([str(python), str(ROOT / "scripts/clone_voice_worker.py"), "--serve"],
            stdin=subprocess.PIPE, stdout=_warm_log, stderr=subprocess.STDOUT, text=True, encoding="utf-8", env={**os.environ,"PYTHONIOENCODING":"utf-8"})
    _warm_process.stdin.write(str(request_path) + "\n")
    _warm_process.stdin.flush()
    done = request_path.with_name("worker-result.json")
    deadline = time.monotonic() + 3600
    while not done.is_file():
        if _warm_process.poll() is not None:
            raise RuntimeError("Warm clone worker exited; completed clips retained. Inspect runtime/clone-batch.log")
        if time.monotonic() > deadline:
            _warm_process.terminate()
            _warm_process.wait(timeout=10)
            raise RuntimeError("Warm clone request timed out; completed clips retained")
        time.sleep(.1)
    data = json.loads(done.read_text(encoding="utf-8"))
    if not data.get("ok"):
        raise RuntimeError(data.get("error") or "Warm clone request failed")
    return data["result"]


def synthesize_reference(text: str, reference: Path, ref_text: str, output: Path,
                         prosody: dict | None = None, prompt_dir: Path | None = None) -> dict:
    if not text.strip() or not ref_text.strip():
        raise ValueError("Target and exact reference transcript are required for cloning")
    if not reference.is_file():
        raise FileNotFoundError("Verified reference audio is missing")
    from .kaggle_tasks import project_for
    if project_for(output):
        from .kaggle_operations import synthesize
        return synthesize(text,reference,ref_text,output,prosody)
    python = clone_python()
    if not python.is_file():
        raise RuntimeError("Clone runtime unavailable. Install requirements-cloning.txt in runtime/clone-env.")
    output.parent.mkdir(parents=True, exist_ok=True)
    request = {"text": text, "reference": str(reference.resolve()), "ref_text": ref_text,
               "output": str(output.resolve()), "prosody": prosody or {},
               "prompt_dir": str((prompt_dir or ROOT / "runtime/voice-bank-audit/prompts").resolve()),
               "reference_sha256": fingerprint(reference)}
    with tempfile.TemporaryDirectory(prefix="clone-request-", dir=output.parent) as folder:
        req = Path(folder) / "request.json"
        req.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        log_path = output.with_suffix(".clone.log")
        started = time.monotonic()
        if _warm_enabled:
            _warm_generate(req, python)
            returncode = 0
        else:
            with clone_worker_slot(), log_path.open("w", encoding="utf-8") as log:
                result = subprocess.run([str(python), str(ROOT / "scripts/clone_voice_worker.py"), str(req)],
                                        stdout=log, stderr=subprocess.STDOUT, timeout=3600)
            returncode = result.returncode
        manifest = output.with_suffix(".clone.json")
        if returncode or not output.is_file() or not manifest.is_file():
            raise RuntimeError(f"Genuine cloning failed; previous output retained. Details: {log_path}")
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if data.get("status") != "completed" or not data.get("reference_conditioned"):
            raise RuntimeError("Clone worker did not verify reference conditioning")
        data["worker_elapsed_sec"] = data["elapsed_sec"]
        data["elapsed_sec"] = round(time.monotonic() - started, 2)
        from .voice_bank_quality import write_report
        write_report(manifest, data)
        return data
