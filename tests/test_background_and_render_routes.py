from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import app, DB_PATH
from backend.db import init_db, connect, now


class BackgroundAndRenderRoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ffmpeg = shutil.which("ffmpeg")
        cls.ffprobe = shutil.which("ffprobe")
        if not cls.ffmpeg or not cls.ffprobe:
            raise unittest.SkipTest("FFmpeg and ffprobe are required for route tests")

    def setUp(self):
        init_db(DB_PATH)
        self.client = TestClient(app)
        self.project_id = str(uuid.uuid4())

        # Create project in DB
        with connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO projects (id, name, status, source_language, target_language, created_at, updated_at) "
                "VALUES (?, ?, 'analyzed', 'en', 'hi', ?, ?)",
                (self.project_id, "Test Route Project", now(), now()),
            )
            conn.commit()

        from backend.app import project_dir
        self.base = project_dir(self.project_id)
        self.analysis = self.base / "analysis"
        self.output = self.base / "output"
        self.segments = self.base / "segments"
        for d in (self.analysis, self.output, self.segments):
            d.mkdir(parents=True, exist_ok=True)

        # Create source audio (2 seconds sine)
        self.source_audio = self.analysis / "source_16k_mono.wav"
        subprocess.run(
            [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=48000:duration=2.0",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                str(self.source_audio),
            ],
            check=True,
            capture_output=True,
        )

        # Create dialogue clip
        self.clip = self.segments / "segment_000000_dub.wav"
        subprocess.run(
            [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=800:sample_rate=48000:duration=1.0",
                "-c:a",
                "pcm_s16le",
                str(self.clip),
            ],
            check=True,
            capture_output=True,
        )

        # Create dialogue manifest and translated transcript
        self.manifest = self.analysis / "dialogue_manifest.json"
        self.manifest.write_text(
            json.dumps({
                "schema_version": 1,
                "units": [{
                    "segment_index": 0,
                    "start_sec": 0.5,
                    "end_sec": 1.5,
                    "tts": {"status": "completed", "output_path": str(self.clip)},
                    "timing": {"status": "completed", "fit_audio": str(self.clip)},
                }]
            }),
            encoding="utf-8",
        )
        self.transcript = self.analysis / "translated_transcript.json"
        self.transcript.write_text(
            json.dumps({
                "target_language": "hi",
                "segments": [{
                    "segment_index": 0,
                    "start": 0.5,
                    "end": 1.5,
                    "dub_audio": str(self.clip),
                }]
            }),
            encoding="utf-8",
        )

    def tearDown(self):
        with connect(DB_PATH) as conn:
            conn.execute("DELETE FROM projects WHERE id = ?", (self.project_id,))
            conn.commit()
        shutil.rmtree(self.base, ignore_errors=True)

    def test_background_preserve_missing_project_returns_404(self):
        resp = self.client.post("/api/projects/non-existent-id/background/preserve", json={})
        self.assertEqual(resp.status_code, 404)

    def test_background_preview_missing_before_preserve_returns_404(self):
        resp = self.client.get(f"/api/projects/{self.project_id}/background/preview")
        self.assertEqual(resp.status_code, 404)

    def test_background_preserve_and_preview_workflow(self):
        # 1. Preserve background
        resp = self.client.post(
            f"/api/projects/{self.project_id}/background/preserve",
            json={"mode": "ducking", "duck_db": -18.0},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["mode"], "ducking")
        self.assertTrue(Path(data["background_audio"]).is_file())

        # 2. Preview preserved background audio
        preview_resp = self.client.get(f"/api/projects/{self.project_id}/background/preview")
        self.assertEqual(preview_resp.status_code, 200)
        self.assertEqual(preview_resp.headers["content-type"], "audio/wav")
        self.assertGreater(len(preview_resp.content), 1000)

    def test_mix_endpoint_uses_preserved_background_and_saves_manifest(self):
        # First preserve background
        self.client.post(
            f"/api/projects/{self.project_id}/background/preserve",
            json={"mode": "ducking"},
        )

        # Build mix
        mix_resp = self.client.post(
            f"/api/projects/{self.project_id}/mix",
            json={"target_lufs": -16.0, "duck_background": True},
        )
        self.assertEqual(mix_resp.status_code, 200)
        mix_data = mix_resp.json()
        self.assertEqual(mix_data["dialogue_segments_mixed"], 1)
        self.assertTrue(mix_data["background_used"])
        self.assertTrue(Path(mix_data["file"]).is_file())

        # Preview mix
        preview_resp = self.client.get(f"/api/projects/{self.project_id}/mix/preview")
        self.assertEqual(preview_resp.status_code, 200)
        self.assertEqual(preview_resp.headers["content-type"], "audio/wav")

    def test_render_qa_endpoint_returns_404_before_render_and_json_after(self):
        # Before render
        resp_pre = self.client.get(f"/api/projects/{self.project_id}/render/qa")
        self.assertEqual(resp_pre.status_code, 404)

        # Create mock QA report
        qa_file = self.output / "render_qa_report.json"
        qa_file.write_text(json.dumps({
            "status": "PASSED",
            "render_duration_sec": 2.0,
            "checks": [{"name": "File existence & size", "status": "pass"}],
        }), encoding="utf-8")

        # After render report exists
        resp_post = self.client.get(f"/api/projects/{self.project_id}/render/qa")
        self.assertEqual(resp_post.status_code, 200)
        qa_data = resp_post.json()
        self.assertEqual(qa_data["status"], "PASSED")
        self.assertEqual(len(qa_data["checks"]), 1)


if __name__ == "__main__":
    unittest.main()
