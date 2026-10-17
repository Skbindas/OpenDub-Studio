from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, source_path TEXT,
    source_size INTEGER NOT NULL DEFAULT 0, duration_ms INTEGER,
    source_language TEXT, target_language TEXT, status TEXT NOT NULL DEFAULT 'created',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, kind TEXT NOT NULL,
    status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0, message TEXT, payload TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    claimed_by TEXT, claimed_at TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS worker_heartbeats (
    worker_id TEXT PRIMARY KEY, hostname TEXT, capabilities TEXT,
    last_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_queue ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_workers_seen ON worker_heartbeats(last_seen_at);
"""

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

class ClosingConnection(sqlite3.Connection):
    """SQLite connection that closes after its context manager exits."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        db_path,
        timeout=60,
        factory=ClosingConnection,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
        if "claimed_by" not in cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN claimed_by TEXT")
        if "claimed_at" not in cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN claimed_at TEXT")
        if "cancel_requested" not in cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_claim ON jobs(status, claimed_at)")
        conn.commit()

def project(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return None if row is None else dict(row)

def job(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None: return None
    item = dict(row)
    try: item["payload"] = json.loads(item["payload"]) if item["payload"] else None
    except (json.JSONDecodeError, TypeError): pass
    return item

def list_projects(db_path: Path) -> list[dict[str, Any]]:
    with connect(db_path) as conn: rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
    return [project(r) for r in rows]

def get_project(db_path: Path, project_id: str) -> dict[str, Any] | None:
    with connect(db_path) as conn: row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    return project(row)

def get_job(db_path: Path, job_id: str) -> dict[str, Any] | None:
    with connect(db_path) as conn: row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return job(row)

def heartbeat(db_path: Path, worker_id: str, hostname: str, capabilities: list[str]) -> None:
    with connect(db_path) as conn:
        conn.execute("""INSERT INTO worker_heartbeats(worker_id,hostname,capabilities,last_seen_at)
          VALUES(?,?,?,?) ON CONFLICT(worker_id) DO UPDATE SET hostname=excluded.hostname,
          capabilities=excluded.capabilities,last_seen_at=excluded.last_seen_at""",
          (worker_id, hostname, json.dumps(capabilities), now()))
        conn.commit()

def purge_dead_workers(db_path: Path, timeout_seconds: int = 240) -> int:
    cutoff = (datetime.now(timezone.utc)-timedelta(seconds=timeout_seconds)).isoformat()
    with connect(db_path) as conn:
        cur=conn.execute("DELETE FROM worker_heartbeats WHERE last_seen_at < ?",(cutoff,))
        conn.commit()
        return cur.rowcount

def requeue_stale_jobs(db_path: Path, lease_seconds: int = 120) -> int:
    cutoff=(datetime.now(timezone.utc)-timedelta(seconds=lease_seconds)).isoformat()
    with connect(db_path) as conn:
        rows=conn.execute("""SELECT id FROM jobs WHERE status IN ('claimed','running','retrying')
          AND (claimed_at IS NULL OR claimed_at < ? OR updated_at < ?)""",(cutoff,cutoff)).fetchall()
        if not rows: return 0
        conn.executemany("""UPDATE jobs SET status='queued',message='Recovered stale worker lease; queued again.',
          claimed_by=NULL,claimed_at=NULL,updated_at=? WHERE id=?""",[(now(),r["id"]) for r in rows])
        conn.commit()
        return len(rows)

def claim_next_job(db_path: Path, worker_id: str) -> dict[str, Any] | None:
    kinds = (
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
        "background_preservation",
        "auto_dub",
        "voice_traits",
        "overlap_recovery",
    )
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        placeholders=",".join("?" for _ in kinds)
        row=conn.execute(f"SELECT id FROM jobs WHERE status='queued' AND kind IN ({placeholders}) ORDER BY created_at LIMIT 1",kinds).fetchone()
        if row is None:
            conn.commit(); return None
        ts=now()
        cur=conn.execute("""UPDATE jobs SET status='claimed',claimed_by=?,claimed_at=?,
          updated_at=?,attempts=attempts+1,message='Claimed by worker.' WHERE id=? AND status='queued'""",
          (worker_id,ts,ts,row["id"]))
        conn.commit()
        return get_job(db_path,row["id"]) if cur.rowcount else None

def refresh_job_lease(db_path: Path, job_id: str, worker_id: str) -> None:
    with connect(db_path) as conn:
        conn.execute("UPDATE jobs SET claimed_at=?,updated_at=? WHERE id=? AND claimed_by=? AND status IN ('claimed','running')",(now(),now(),job_id,worker_id))
        conn.commit()

def release_job(db_path: Path, job_id: str, worker_id: str, status: str="queued", message: str|None=None) -> None:
    with connect(db_path) as conn:
        conn.execute("""UPDATE jobs SET status=?,claimed_by=NULL,claimed_at=NULL,message=?,updated_at=?
          WHERE id=? AND claimed_by=?""",(status,message,now(),job_id,worker_id))
        conn.commit()


def request_job_cancel(db_path: Path, job_id: str) -> dict[str, Any] | None:
    """Persist cancellation intent; queued jobs cancel immediately, active jobs cooperatively."""
    with connect(db_path) as conn:
        row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return None
        status = row["status"]
        if status in {"completed", "failed", "cancelled"}:
            return get_job(db_path, job_id)
        ts = now()
        if status in {"queued","waiting"}:
            conn.execute("""UPDATE jobs SET status='cancelled',cancel_requested=1,
                message='Cancelled before worker start.',updated_at=? WHERE id=?""", (ts, job_id))
        else:
            conn.execute("""UPDATE jobs SET cancel_requested=1,message='Cancellation requested; waiting for a safe checkpoint.',
                updated_at=? WHERE id=?""", (ts, job_id))
        conn.commit()
    return get_job(db_path, job_id)


def job_cancel_requested(db_path: Path, job_id: str) -> bool:
    with connect(db_path) as conn:
        row = conn.execute("SELECT cancel_requested,status FROM jobs WHERE id=?", (job_id,)).fetchone()
    return bool(row and (row["cancel_requested"] or row["status"] == "cancelled"))


def mark_job_cancelled(db_path: Path, job_id: str, message: str = "Job cancelled at a safe checkpoint.") -> None:
    with connect(db_path) as conn:
        conn.execute("""UPDATE jobs SET status='cancelled',message=?,claimed_by=NULL,claimed_at=NULL,
            updated_at=? WHERE id=? AND status NOT IN ('completed','failed')""", (message, now(), job_id))
        conn.commit()
