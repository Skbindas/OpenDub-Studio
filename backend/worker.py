
from __future__ import annotations

import argparse
import asyncio
import os
import socket
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

from .db import (
    claim_next_job,
    connect,
    get_job,
    heartbeat,
    init_db,
    purge_dead_workers,
    refresh_job_lease,
    requeue_stale_jobs,
    release_job,
    job_cancel_requested,
    mark_job_cancelled,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / os.getenv("OPENDUB_DATA_DIR", "runtime")
DB_PATH = DATA_ROOT / "opendub.sqlite3"

DEFAULT_KINDS = (
    "media_analysis",
    "full_analysis",
    "audio_extract",
    "scene_detect",
    "transcribe",
    "diarize",
    "separate",
    "full_render",
    "batch_synthesis",
    "batch_fit",
    "auto_dub",
    "voice_traits",
    "overlap_recovery",
)

class JobWorker:
    def __init__(self, db_path: Path = DB_PATH, worker_id: str | None = None,
                 poll_seconds: float = 1.5, lease_seconds: int = 120) -> None:
        self.db_path = db_path
        self.worker_id = worker_id or f"worker-{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self.poll_seconds = max(0.2, poll_seconds)
        self.lease_seconds = max(30, lease_seconds)
        self.stop_event = threading.Event()
        self.current_job: str | None = None
        self._lease_thread: threading.Thread | None = None

    def start(self) -> None:
        init_db(self.db_path)
        print(f"[OpenDub worker] {self.worker_id} online")
        self.run()

    def stop(self) -> None:
        self.stop_event.set()

    def _heartbeat(self) -> None:
        capabilities = list(DEFAULT_KINDS)
        while not self.stop_event.is_set():
            try:
                heartbeat(self.db_path, self.worker_id, socket.gethostname(), capabilities)
                purge_dead_workers(self.db_path, self.lease_seconds * 2)
                requeue_stale_jobs(self.db_path, self.lease_seconds)
                if self.current_job:
                    refresh_job_lease(self.db_path, self.current_job, self.worker_id)
            except Exception as exc:
                print(f"[OpenDub worker] heartbeat error: {exc}")
            self.stop_event.wait(max(5, self.lease_seconds // 3))

    def _run_heartbeat_thread(self) -> None:
        self._lease_thread = threading.Thread(target=self._heartbeat, name="opendub-heartbeat", daemon=True)
        self._lease_thread.start()

    def run(self) -> None:
        self._run_heartbeat_thread()
        while not self.stop_event.is_set():
            try:
                job = claim_next_job(self.db_path, self.worker_id)
                if not job:
                    self.stop_event.wait(self.poll_seconds)
                    continue
                self.current_job = job["id"]
                print(f"[OpenDub worker] claimed {job['id']} ({job['kind']})")
                self._dispatch(job)
            except Exception as exc:
                print(f"[OpenDub worker] loop error: {exc}")
                self.stop_event.wait(2)
            finally:
                self.current_job = None

    def _dispatch(self, job: dict[str, Any]) -> None:
        kind = str(job["kind"])
        job_id = str(job["id"])
        project_id = str(job["project_id"])
        print(f"\n[OpenDub Worker] >>> STARTING JOB: {kind} (ID: {job_id[:8]}) for Project {project_id[:8]}", flush=True)
        try:
            if kind == "media_analysis":
                from .app import run_analysis
                asyncio.run(run_analysis(job_id, project_id))
            elif kind == "full_analysis":
                from .app import execute_full_analysis
                payload = job.get("payload") or {}
                execute_full_analysis(job_id, project_id, payload)
            elif kind in {"audio_extract", "scene_detect", "transcribe", "diarize", "separate"}:
                from .app import execute_media_stage
                payload = job.get("payload") or {}
                execute_media_stage(job_id, project_id, kind, payload)
            elif kind == "full_render":
                from .app import execute_full_render
                payload = job.get("payload") or {}
                cleanup = bool(payload.get("cleanup_intermediates", True))
                execute_full_render(job_id, project_id, cleanup)
            elif kind == "batch_synthesis":
                from .app import execute_batch_synthesis
                payload = job.get("payload") or {}
                execute_batch_synthesis(job_id, project_id, payload)
            elif kind == "auto_dub":
                from .auto_dub import execute_auto_dub
                execute_auto_dub(job_id, project_id, job.get("payload") or {})
            elif kind in {'voice_traits','overlap_recovery'}:
                from .speaker_tools import execute_speaker_tool
                execute_speaker_tool(job_id,project_id,{**(job.get('payload') or {}),'task':kind})
            elif kind == "batch_fit":
                from .app import execute_batch_fit
                payload = job.get("payload") or {}
                execute_batch_fit(job_id, project_id, payload)
            elif kind == "background_preservation":
                from .app import execute_background_preservation
                payload = job.get("payload") or {}
                execute_background_preservation(job_id, project_id, payload)
            else:
                release_job(self.db_path, job_id, self.worker_id, "failed", f"Unsupported worker job kind: {kind}")
                return

            final = get_job(self.db_path, job_id)
            if job_cancel_requested(self.db_path, job_id):
                print(f"[OpenDub Worker] Job {job_id[:8]} cancelled.", flush=True)
                mark_job_cancelled(self.db_path, job_id)
                return
            if not final:
                return
            print(f"[OpenDub Worker] <<< COMPLETED JOB: {kind} (ID: {job_id[:8]}): status={final.get('status')}, message={final.get('message')}\n", flush=True)
            if final["status"] == "failed":
                max_attempts = int(os.getenv("OPENDUB_MAX_JOB_ATTEMPTS", "3"))
                attempts = int(final.get("attempts") or 0)
                if kind not in {'voice_traits','overlap_recovery'} and attempts < max_attempts:
                    release_job(self.db_path, job_id, self.worker_id, "queued",
                                f"Retry queued automatically ({attempts}/{max_attempts}).")
                else:
                    release_job(self.db_path, job_id, self.worker_id, "failed",
                                final.get("message") or "Worker job failed.")
            elif final["status"] in {"completed"}:
                release_job(self.db_path, job_id, self.worker_id, "completed", final.get("message"))
            elif final['status']=='waiting':
                release_job(self.db_path,job_id,self.worker_id,'waiting',final.get('message'))
            elif final["status"] in {"running", "claimed"}:
                release_job(self.db_path, job_id, self.worker_id, "queued",
                            "Worker exited before marking job complete; queued again.")
        except Exception as exc:
            from .kaggle_tasks import waiting_error
            if job_cancel_requested(self.db_path, job_id):
                mark_job_cancelled(self.db_path, job_id)
                return
            if waiting_error(exc):
                release_job(self.db_path,job_id,self.worker_id,'waiting',str(waiting_error(exc)));return
            final = get_job(self.db_path, job_id)
            attempts = int((final or {}).get("attempts") or 0)
            max_attempts = int(os.getenv("OPENDUB_MAX_JOB_ATTEMPTS", "3"))
            # Auto-dub review/setup failures require a correction, not repeated
            # model downloads or destructive re-analysis of the same source.
            target = "queued" if kind not in {'auto_dub','voice_traits','overlap_recovery'} and attempts < max_attempts else "failed"
            release_job(self.db_path, job_id, self.worker_id, target, str(exc))

_embedded_started = False
_embedded_lock = threading.Lock()

def start_embedded_worker(db_path: Path = DB_PATH) -> None:
    global _embedded_started
    with _embedded_lock:
        if _embedded_started:
            return
        if os.getenv("OPENDUB_EMBED_WORKER", "1").lower() in {"0", "false", "no"}:
            return
        _embedded_started = True
        worker = JobWorker(
            db_path=db_path,
            worker_id=f"embedded-{socket.gethostname()}-{uuid.uuid4().hex[:6]}",
            poll_seconds=float(os.getenv("OPENDUB_WORKER_POLL_SECONDS", "1.5")),
            lease_seconds=int(os.getenv("OPENDUB_JOB_LEASE_SECONDS", "120")),
        )
        threading.Thread(target=worker.start, name="opendub-embedded-worker", daemon=True).start()

def main() -> None:
    parser = argparse.ArgumentParser(description="OpenDub Studio durable SQLite job worker")
    parser.add_argument("--once", action="store_true", help="Claim and process one job, then exit")
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--poll", type=float, default=float(os.getenv("OPENDUB_WORKER_POLL_SECONDS", "1.5")))
    parser.add_argument("--lease", type=int, default=int(os.getenv("OPENDUB_JOB_LEASE_SECONDS", "120")))
    args = parser.parse_args()
    if args.once:
        worker = JobWorker(db_path=DB_PATH, worker_id=args.worker_id, poll_seconds=args.poll, lease_seconds=args.lease)
        job = claim_next_job(worker.db_path, worker.worker_id)
        if job:
            worker.current_job = job["id"]
            worker._dispatch(job)
        return
    worker = JobWorker(db_path=DB_PATH, worker_id=args.worker_id, poll_seconds=args.poll, lease_seconds=args.lease)
    try:
        worker.start()
    except KeyboardInterrupt:
        worker.stop()

if __name__ == "__main__":
    main()
