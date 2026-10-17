import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import app as app_module


class SynthesisDurationVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project_id = "duration-check-project"
        self.project = self.root / self.project_id
        (self.project / "analysis").mkdir(parents=True)
        (self.project / "segments").mkdir()
        (self.project / "analysis" / "translated_transcript.json").write_text(json.dumps({
            "segments": [{
                "segment_index": 0, "start": 3.0, "end": 5.0,
                "translated_text": "नमस्ते", "adaptation_mode": "manual_naturalization"
            }]
        }, ensure_ascii=False), encoding="utf-8")
        self.patches = [
            patch.object(app_module, "get_project", side_effect=lambda _db, pid: {"id": pid}),
            patch.object(app_module, "project_dir", return_value=self.project),
            patch.object(app_module, "synthesize_piper_segment", side_effect=self._fake_synthesis),
            patch.object(app_module, "ffprobe", return_value={"available": True, "duration_ms": 2100}),
        ]
        for item in self.patches:
            item.start()
        self.client = TestClient(app_module.app)

    @staticmethod
    def _fake_synthesis(text, output_path, voice_model, speaker_id=None, prosody=None):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake wav bytes")
        return {"file": str(output_path), "size_bytes": output_path.stat().st_size}

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_synthesis_persists_measured_duration_and_fit_warning(self):
        response = self.client.post(
            f"/api/projects/{self.project_id}/segments/0/synthesize",
            json={"voice_model_path": "/tmp/fake-voice.onnx"},
        )
        self.assertEqual(response.status_code, 200)
        check = response.json()["duration_check"]
        self.assertEqual(check["source_window_ms"], 2000)
        self.assertEqual(check["actual_audio_ms"], 2100)
        self.assertTrue(check["within_tolerance"])
        persisted = json.loads((self.project / "analysis" / "translated_transcript.json").read_text(encoding="utf-8"))
        self.assertEqual(persisted["segments"][0]["synthesis_duration_check"], check)

    def test_synthesis_flags_audio_outside_source_window_tolerance(self):
        with patch.object(app_module, "ffprobe", return_value={"available": True, "duration_ms": 2800}):
            response = self.client.post(
                f"/api/projects/{self.project_id}/segments/0/synthesize",
                json={"voice_model_path": "/tmp/fake-voice.onnx"},
            )
        self.assertEqual(response.status_code, 200)
        check = response.json()["duration_check"]
        self.assertEqual(check["status"], "fit_required")
        self.assertFalse(check["within_tolerance"])

    def test_synthesis_fails_closed_when_audio_duration_cannot_be_measured(self):
        with patch.object(app_module, "ffprobe", return_value={"available": False, "error": "ffprobe unavailable"}):
            response = self.client.post(
                f"/api/projects/{self.project_id}/segments/0/synthesize",
                json={"voice_model_path": "/tmp/fake-voice.onnx"},
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("duration could not be verified", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
