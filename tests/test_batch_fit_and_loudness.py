import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from backend import app as app_module
from backend.app import create_job, now
from backend.db import connect, init_db, get_job, request_job_cancel
from backend.pipeline import (
    get_pipeline_state,
    update_dialogue_manifest_timing,
    update_dialogue_manifest_loudness,
)


class BatchFitAndLoudnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / "test_opendub.db"
        init_db(self.db_path)

        self.project_id = "test-fit-loudness-proj"
        self.project = self.root / self.project_id
        (self.project / "analysis").mkdir(parents=True)
        (self.project / "segments").mkdir()
        (self.project / "characters").mkdir()

        # Seed projects table
        with connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO projects (id, name, status, created_at, updated_at) VALUES (?, ?, 'ready', ?, ?)",
                (self.project_id, "Test Project", now(), now()),
            )

        # Create 2 synthesized audio segment files
        self.seg0_dub = self.project / "segments" / "segment_000000_dub.wav"
        self.seg1_dub = self.project / "segments" / "segment_000001_dub.wav"
        self.seg0_dub.write_bytes(b"RIFF....WAVEfmt ....data....fake1")
        self.seg1_dub.write_bytes(b"RIFF....WAVEfmt ....data....fake2")

        # Seed translated_transcript.json
        self.segments_data = {
            "segments": [
                {
                    "segment_index": 0,
                    "start": 0.0,
                    "end": 2.0,
                    "translated_text": "नमस्ते दुनिया",
                    "dub_audio": str(self.seg0_dub),
                    "speaker": "SPEAKER_00",
                },
                {
                    "segment_index": 1,
                    "start": 2.5,
                    "end": 5.0,
                    "translated_text": "शुभ प्रभात",
                    "dub_audio": str(self.seg1_dub),
                    "speaker": "SPEAKER_01",
                },
            ]
        }
        (self.project / "analysis" / "translated_transcript.json").write_text(
            json.dumps(self.segments_data, ensure_ascii=False), encoding="utf-8"
        )

        # Seed dialogue_manifest.json with TTS completed
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
                    "duration_sec": 2.0,
                    "tts": {"status": "completed", "audio_path": str(self.seg0_dub)},
                    "timing": {"status": "pending"},
                    "loudness": {"status": "pending"},
                },
                {
                    "segment_index": 1,
                    "character_id": "char-2",
                    "character_name": "Villain",
                    "speaker_id": "SPEAKER_01",
                    "duration_sec": 2.5,
                    "tts": {"status": "completed", "audio_path": str(self.seg1_dub)},
                    "timing": {"status": "pending"},
                    "loudness": {"status": "pending"},
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
            patch.object(app_module, "fit_audio", side_effect=self._fake_fit_audio),
            patch.object(app_module, "normalize_audio", side_effect=self._fake_normalize_audio),
        ]
        for item in self.patches:
            item.start()
        self.client = TestClient(app_module.app)

    @staticmethod
    def _fake_fit_audio(src, out, target, max_speedup=1.25, max_slowdown=0.82, **kwargs):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"RIFF....WAVEfmt ....data....fitted")
        return {
            "file": str(out),
            "source_duration": target * 1.1,
            "target_duration": target,
            "required_tempo": 1.1,
            "applied_tempo": 1.1,
            "duration_fit_limited": False,
        }

    @staticmethod
    def _fake_normalize_audio(src, out, target_lufs=-16.0):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"RIFF....WAVEfmt ....data....normalized")
        return {"file": str(out), "target_lufs": target_lufs}

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_update_dialogue_manifest_timing_and_loudness(self):
        manifest_path = self.project / "analysis" / "dialogue_manifest.json"

        # Test timing update
        res = update_dialogue_manifest_timing(
            manifest_path=manifest_path,
            segment_index=0,
            status="completed",
            fit_audio="/path/to/fit.wav",
            required_tempo=1.05,
            applied_tempo=1.05,
            duration_fit_limited=False,
        )
        unit0 = res["units"][0]
        self.assertEqual(unit0["timing"]["status"], "completed")
        self.assertEqual(unit0["timing"]["fit_audio"], "/path/to/fit.wav")
        self.assertFalse(unit0["timing"]["duration_fit_limited"])

        # Test loudness update
        res2 = update_dialogue_manifest_loudness(
            manifest_path=manifest_path,
            segment_index=0,
            status="completed",
            normalized_audio="/path/to/norm.wav",
            target_lufs=-16.0,
        )
        unit0_l = res2["units"][0]
        self.assertEqual(unit0_l["loudness"]["status"], "completed")
        self.assertEqual(unit0_l["loudness"]["target_lufs"], -16.0)

    def test_single_segment_fit_and_normalize_endpoints(self):
        # Fit segment 0
        res_fit = self.client.post(
            f"/api/projects/{self.project_id}/segments/0/fit",
            json={"target_duration": 2.0, "max_speedup": 1.25, "max_slowdown": 0.82},
        )
        self.assertEqual(res_fit.status_code, 200)
        self.assertIn("file", res_fit.json())

        # Verify manifest was updated
        manifest = json.loads((self.project / "analysis" / "dialogue_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["units"][0]["timing"]["status"], "completed")

        # Normalize segment 0
        res_norm = self.client.post(
            f"/api/projects/{self.project_id}/segments/0/normalize?target_lufs=-16",
        )
        self.assertEqual(res_norm.status_code, 200)

        # Verify manifest was updated
        manifest = json.loads((self.project / "analysis" / "dialogue_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["units"][0]["loudness"]["status"], "completed")

    def test_enqueue_batch_fit_endpoint(self):
        res = self.client.post(
            f"/api/projects/{self.project_id}/fit-all",
            json={"max_speedup": 1.25, "max_slowdown": 0.82, "normalize": True, "target_lufs": -16.0},
        )
        self.assertEqual(res.status_code, 200)
        job_id = res.json()["job_id"]
        job = get_job(self.db_path, job_id)
        self.assertEqual(job["kind"], "batch_fit")

    def test_execute_batch_fit_processes_and_resumes(self):
        # 1. First run fits & normalizes both segments
        job_id = create_job(self.project_id, "batch_fit", {"normalize": True, "force": False})
        app_module.execute_batch_fit(job_id, self.project_id, {"normalize": True, "force": False})

        job = get_job(self.db_path, job_id)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["payload"]["fitted_count"], 2)

        self.assertEqual(job["payload"]["normalized_count"], 2)
        self.assertEqual(job["payload"]["skipped_count"], 0)

        fit0 = self.project / "segments" / "segment_000000_fit.wav"
        norm0 = self.project / "segments" / "segment_000000_normalized.wav"
        self.assertTrue(fit0.is_file())
        self.assertTrue(norm0.is_file())

        manifest = json.loads((self.project / "analysis" / "dialogue_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["units"][0]["timing"]["status"], "completed")
        self.assertEqual(manifest["units"][0]["loudness"]["status"], "completed")

        # 2. Second run with force=False skips both (resumability)
        job_id_2 = create_job(self.project_id, "batch_fit", {"normalize": True, "force": False})
        app_module.execute_batch_fit(job_id_2, self.project_id, {"normalize": True, "force": False})

        job2 = get_job(self.db_path, job_id_2)
        self.assertEqual(job2["status"], "completed")
        self.assertEqual(job2["payload"]["fitted_count"], 0)
        self.assertEqual(job2["payload"]["skipped_count"], 2)

    def test_cloud_batch_does_not_repeat_individual_remote_transforms(self):
        job_id=create_job(self.project_id,'batch_fit',{})
        def prepared(*args):
            result={}
            for index,source,target in ((0,self.seg0_dub,2.),(1,self.seg1_dub,2.5)):
                fit=self.project/'segments'/f'segment_{index:06d}_fit.wav'
                norm=self.project/'segments'/f'segment_{index:06d}_normalized.wav'
                result[index]={'fit':self._fake_fit_audio(source,fit,target),
                               'normalize':self._fake_normalize_audio(fit,norm)}
            return result
        with patch('backend.kaggle_tasks.project_for',return_value=self.project),patch('backend.kaggle_operations.fit_batch',side_effect=prepared):
            app_module.execute_batch_fit(job_id,self.project_id,{})
        app_module.fit_audio.assert_not_called()
        app_module.normalize_audio.assert_not_called()
        job=get_job(self.db_path,job_id)
        self.assertEqual(job['payload']['fitted_count'],2)
        self.assertEqual(job['payload']['normalized_count'],2)

    def test_resume_rechecks_old_review_policy_without_resynthesizing(self):
        for unit in self.manifest_data['units']:
            unit['timing'] = {'status':'needs_review'}
            index = unit['segment_index']
            (self.project/'segments'/f'segment_{index:06d}_fit.wav').write_bytes(b'old fit')
            (self.project/'segments'/f'segment_{index:06d}_normalized.wav').write_bytes(b'old normalized')
            unit['loudness'] = {'status':'completed'}
        manifest = self.project/'analysis'/'dialogue_manifest.json'
        manifest.write_text(json.dumps(self.manifest_data), encoding='utf-8')
        before = self.seg0_dub.read_bytes(), self.seg1_dub.read_bytes()
        job_id = create_job(self.project_id, 'batch_fit', {})
        app_module.execute_batch_fit(job_id, self.project_id, {})
        result = get_job(self.db_path, job_id)['payload']
        self.assertEqual(result['fitted_count'], 2)
        self.assertEqual(result['needs_review_count'], 0)
        self.assertEqual(before, (self.seg0_dub.read_bytes(), self.seg1_dub.read_bytes()))

    def test_execute_batch_fit_flags_needs_review_on_limited_fit(self):
        # Mock fit_audio returning duration_fit_limited=True for segment 0
        def _limited_fit(src, out, target, max_speedup=1.25, max_slowdown=0.82, **kwargs):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"RIFF....WAVEfmt ....data....limited")
            return {
                "file": str(out),
                "source_duration": target * 2.0,
                "target_duration": target,
                "required_tempo": 2.0,
                "applied_tempo": max_speedup,
                "duration_fit_limited": True,
            }

        with patch.object(app_module, "fit_audio", side_effect=_limited_fit):
            job_id = create_job(self.project_id, "batch_fit", {"normalize": True, "force": True})
            app_module.execute_batch_fit(job_id, self.project_id, {"normalize": True, "force": True})

        job = get_job(self.db_path, job_id)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["payload"]["needs_review_count"], 2)

        manifest = json.loads((self.project / "analysis" / "dialogue_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["units"][0]["timing"]["status"], "needs_review")
        self.assertTrue(manifest["units"][0]["timing"]["duration_fit_limited"])

    def test_execute_batch_fit_cancellation(self):
        job_id = create_job(self.project_id, "batch_fit", {})
        request_job_cancel(self.db_path, job_id)

        app_module.execute_batch_fit(job_id, self.project_id, {})

        job = get_job(self.db_path, job_id)
        self.assertEqual(job["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
