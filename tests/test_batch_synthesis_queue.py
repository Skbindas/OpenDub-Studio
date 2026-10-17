import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import app as app_module
from backend.app import create_job, now
from backend.db import connect, init_db, get_job, request_job_cancel


class BatchSynthesisQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / "test_opendub.db"
        init_db(self.db_path)

        self.project_id = "test-batch-synthesis-proj"
        self.project = self.root / self.project_id
        (self.project / "analysis").mkdir(parents=True)
        (self.project / "segments").mkdir()

        # Seed projects table in SQLite to satisfy FOREIGN KEY constraint
        with connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO projects (id, name, status, created_at, updated_at) VALUES (?, ?, 'ready', ?, ?)",
                (self.project_id, "Test Project", now(), now()),
            )

        # Seed translated_transcript.json with 2 segments
        self.segments_data = {
            "segments": [
                {
                    "segment_index": 0,
                    "start": 0.0,
                    "end": 2.0,
                    "translated_text": "नमस्ते दुनिया",
                    "adaptation_mode": "manual_naturalization",
                    "speaker": "SPEAKER_00",
                },
                {
                    "segment_index": 1,
                    "start": 2.5,
                    "end": 5.0,
                    "translated_text": "शुभ प्रभात",
                    "adaptation_mode": "manual_naturalization",
                    "speaker": "SPEAKER_01",
                },
            ]
        }
        (self.project / "analysis" / "translated_transcript.json").write_text(
            json.dumps(self.segments_data, ensure_ascii=False), encoding="utf-8"
        )

        # Seed dialogue_manifest.json with 2 units
        self.manifest_data = {
            "project_id": self.project_id,
            "version": "1.0",
            "timebase": "source_media_seconds",
            "target_language": "hi",
            "units": [
                {
                    "segment_index": 0,
                    "character_id": "char-1",
                    "character_name": "Hero",
                    "speaker_id": "SPEAKER_00",
                    "start_sec": 0.0,
                    "end_sec": 2.0,
                    "tts": {"status": "pending", "provider": "piper"},
                },
                {
                    "segment_index": 1,
                    "character_id": "char-2",
                    "character_name": "Villain",
                    "speaker_id": "SPEAKER_01",
                    "start_sec": 2.5,
                    "end_sec": 5.0,
                    "tts": {"status": "pending", "provider": "piper"},
                },
            ],
        }
        (self.project / "analysis" / "dialogue_manifest.json").write_text(
            json.dumps(self.manifest_data, ensure_ascii=False), encoding="utf-8"
        )

        self.patches = [
            patch.object(app_module, "DB_PATH", self.db_path),
            patch.object(app_module, "get_project", side_effect=lambda _db, pid: {"id": pid} if pid == self.project_id else None),
            patch.object(app_module, "project_dir", return_value=self.project),
            patch.object(app_module, "synthesize_piper_segment", side_effect=self._fake_synthesis),
            patch.object(app_module, "ffprobe", return_value={"available": True, "duration_ms": 1800}),
        ]
        for item in self.patches:
            item.start()
        self.client = TestClient(app_module.app)

    @staticmethod
    def _fake_synthesis(text, output_path, voice_model, speaker_id=None, prosody=None):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"RIFF....WAVEfmt ....data....fake")
        return {"file": str(output_path), "size_bytes": output_path.stat().st_size}

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_synthesize_all_endpoint_enqueues_job(self):
        res = self.client.post(
            f"/api/projects/{self.project_id}/synthesize-all",
            json={"voice_model_path": "/fake/model.onnx", "force": False},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("job_id", data)

        job = get_job(self.db_path, data["job_id"])
        self.assertIsNotNone(job)
        self.assertEqual(job["kind"], "batch_synthesis")
        self.assertEqual(job["project_id"], self.project_id)

    def test_execute_batch_synthesis_processes_and_is_resumable(self):
        # 1. First run synthesizes both segments
        job_id = create_job(self.project_id, "batch_synthesis", {"voice_model_path": "/fake/model.onnx", "force": False})
        app_module.execute_batch_synthesis(job_id, self.project_id, {"voice_model_path": "/fake/model.onnx", "force": False})

        job = get_job(self.db_path, job_id)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["payload"]["synthesized_count"], 2)
        self.assertEqual(job["payload"]["skipped_count"], 0)
        self.assertEqual(job["payload"]["failed_count"], 0)

        seg0 = self.project / "segments" / "segment_000000_dub.wav"
        seg1 = self.project / "segments" / "segment_000001_dub.wav"
        self.assertTrue(seg0.is_file())
        self.assertTrue(seg1.is_file())

        # Verify dialogue manifest was updated with completed tts status
        manifest = json.loads((self.project / "analysis" / "dialogue_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["units"][0]["tts"]["status"], "completed")
        self.assertEqual(manifest["units"][1]["tts"]["status"], "completed")

        # 2. Second run with force=False skips both (resumability)
        job_id_2 = create_job(self.project_id, "batch_synthesis", {"voice_model_path": "/fake/model.onnx", "force": False})
        app_module.execute_batch_synthesis(job_id_2, self.project_id, {"voice_model_path": "/fake/model.onnx", "force": False})

        job2 = get_job(self.db_path, job_id_2)
        self.assertEqual(job2["status"], "completed")
        self.assertEqual(job2["payload"]["synthesized_count"], 0)
        self.assertEqual(job2["payload"]["skipped_count"], 2)

        # 3. Third run with force=True re-synthesizes both
        job_id_3 = create_job(self.project_id, "batch_synthesis", {"voice_model_path": "/fake/model.onnx", "force": True})
        app_module.execute_batch_synthesis(job_id_3, self.project_id, {"voice_model_path": "/fake/model.onnx", "force": True})

        job3 = get_job(self.db_path, job_id_3)
        self.assertEqual(job3["status"], "completed")
        self.assertEqual(job3["payload"]["synthesized_count"], 2)
        self.assertEqual(job3["payload"]["skipped_count"], 0)

    def test_execute_batch_synthesis_fault_tolerant(self):
        # Fail the first segment, let the second segment succeed
        def _failing_synthesis(text, output_path, voice_model, speaker_id=None, prosody=None):
            if "दुनिया" in text:
                raise RuntimeError("Piper crashed on symbol")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"RIFF....WAVEfmt ....data....fake")
            return {"file": str(output_path), "size_bytes": output_path.stat().st_size}

        with patch.object(app_module, "synthesize_piper_segment", side_effect=_failing_synthesis):
            job_id = create_job(self.project_id, "batch_synthesis", {"voice_model_path": "/fake/model.onnx", "force": True})
            app_module.execute_batch_synthesis(job_id, self.project_id, {"voice_model_path": "/fake/model.onnx", "force": True})

        job = get_job(self.db_path, job_id)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["payload"]["synthesized_count"], 1)
        self.assertEqual(job["payload"]["failed_count"], 1)

        # Verify unit 0 status is error in manifest
        manifest = json.loads((self.project / "analysis" / "dialogue_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["units"][0]["tts"]["status"], "error")
        self.assertEqual(manifest["units"][1]["tts"]["status"], "completed")

    def test_execute_batch_synthesis_cooperative_cancel(self):
        job_id = create_job(self.project_id, "batch_synthesis", {"voice_model_path": "/fake/model.onnx"})
        # Request cancel immediately
        request_job_cancel(self.db_path, job_id)

        app_module.execute_batch_synthesis(job_id, self.project_id, {"voice_model_path": "/fake/model.onnx"})

        job = get_job(self.db_path, job_id)
        self.assertEqual(job["status"], "cancelled")

    def test_get_segment_audio_endpoint(self):
        # Audio doesn't exist yet -> 404
        r404 = self.client.get(f"/api/projects/{self.project_id}/segments/0/audio")
        self.assertEqual(r404.status_code, 404)

        # Create audio file with standard naming pattern
        seg0 = self.project / "segments" / "segment_000000_dub.wav"
        seg0.write_bytes(b"RIFF1234WAVEfmt ")

        # A stale file must not be served for a pending/revised dialogue unit.
        stale = self.client.get(f"/api/projects/{self.project_id}/segments/0/audio")
        self.assertEqual(stale.status_code, 409)
        manifest_path = self.project / "analysis" / "dialogue_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["units"][0]["tts"]["status"] = "completed"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        r200 = self.client.get(f"/api/projects/{self.project_id}/segments/0/audio")
        self.assertEqual(r200.status_code, 200)
        self.assertEqual(r200.headers["content-type"], "audio/wav")
        self.assertEqual(r200.content, b"RIFF1234WAVEfmt ")

        # Non-existent segment -> 404
        r_nonexistent = self.client.get(f"/api/projects/{self.project_id}/segments/999/audio")
        self.assertEqual(r_nonexistent.status_code, 404)


if __name__ == "__main__":
    unittest.main()
