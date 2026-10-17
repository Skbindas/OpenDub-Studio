from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.db import (
    claim_next_job, connect, get_job, heartbeat, init_db,
    purge_dead_workers, requeue_stale_jobs, release_job, request_job_cancel, job_cancel_requested, mark_job_cancelled,
)

class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Path(self.tmp.name)/"test.sqlite3"
        init_db(self.db)
        with connect(self.db) as conn:
            conn.execute("INSERT INTO projects(id,name,created_at,updated_at) VALUES('p1','Test','2026-01-01','2026-01-01')")
            conn.execute("""INSERT INTO jobs(id,project_id,kind,status,progress,attempts,payload,created_at,updated_at)
              VALUES('j1','p1','transcribe','queued',0,0,'{}','2026-01-01','2026-01-01')""")
            conn.commit()

    def tearDown(self):
        self.tmp.cleanup()

    def test_claim_is_atomic_and_increments_attempt(self):
        item=claim_next_job(self.db,"worker-a")
        self.assertEqual(item["id"],"j1")
        self.assertEqual(item["status"],"claimed")
        self.assertEqual(item["claimed_by"],"worker-a")
        self.assertEqual(item["attempts"],1)
        self.assertIsNone(claim_next_job(self.db,"worker-b"))

    def test_full_analysis_kind_is_claimable(self):
        db = Path(self.tmp.name) / "full_analysis.sqlite3"
        init_db(db)
        with connect(db) as conn:
            conn.execute("INSERT INTO projects(id,name,created_at,updated_at) VALUES('p2','Movie','2026-01-01','2026-01-01')")
            conn.execute("""INSERT INTO jobs(id,project_id,kind,status,progress,attempts,payload,created_at,updated_at)
              VALUES('j2','p2','full_analysis','queued',0,0,'{}','2026-01-01','2026-01-01')""")
            conn.commit()
        item = claim_next_job(db, "worker-full")
        self.assertEqual(item["id"], "j2")
        self.assertEqual(item["kind"], "full_analysis")
        self.assertEqual(item["status"], "claimed")


    def test_release_requeues_and_allows_reclaim(self):
        claim_next_job(self.db,"worker-a")
        release_job(self.db,"j1","worker-a","queued","retry")
        again=claim_next_job(self.db,"worker-b")
        self.assertEqual(again["claimed_by"],"worker-b")
        self.assertEqual(again["attempts"],2)

    def test_heartbeat_upsert_and_purge(self):
        heartbeat(self.db,"w1","host",["transcribe"])
        with connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM worker_heartbeats").fetchone()[0],1)
        self.assertEqual(purge_dead_workers(self.db,timeout_seconds=3600),0)


    def test_queued_job_cancellation_is_persisted_and_not_claimable(self):
        cancelled = request_job_cancel(self.db, "j1")
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["cancel_requested"], 1)
        self.assertTrue(job_cancel_requested(self.db, "j1"))
        self.assertIsNone(claim_next_job(self.db, "worker-cancel"))

    def test_running_job_cancellation_is_cooperative_and_terminal(self):
        claim_next_job(self.db, "worker-a")
        with connect(self.db) as conn:
            conn.execute("UPDATE jobs SET status='running' WHERE id='j1'")
            conn.commit()
        requested = request_job_cancel(self.db, "j1")
        self.assertEqual(requested["status"], "running")
        self.assertTrue(job_cancel_requested(self.db, "j1"))
        mark_job_cancelled(self.db, "j1")
        self.assertEqual(get_job(self.db, "j1")["status"], "cancelled")
        self.assertIsNone(claim_next_job(self.db, "worker-b"))

    def test_migration_adds_worker_columns_to_legacy_db(self):
        legacy=Path(self.tmp.name)/"legacy.sqlite3"
        with connect(legacy) as conn:
            conn.execute("""CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT,created_at TEXT,updated_at TEXT)""")
            conn.execute("""CREATE TABLE jobs(id TEXT PRIMARY KEY,project_id TEXT,kind TEXT,status TEXT,progress REAL,
              attempts INTEGER,message TEXT,payload TEXT,created_at TEXT,updated_at TEXT)""")
        init_db(legacy)
        with connect(legacy) as conn:
            cols={r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
        self.assertIn("claimed_by",cols)
        self.assertIn("claimed_at",cols)
        self.assertIn("cancel_requested",cols)

if __name__=="__main__":
    unittest.main()
