from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.media import check_asr_runtime, probe_media


class MediaRuntimeTests(unittest.TestCase):
    def test_check_asr_runtime_fails_fast_when_asr_missing(self):
        with patch("backend.media.importlib.util.find_spec", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "ASR runtime is missing"):
                check_asr_runtime("auto")

    def test_check_asr_runtime_selects_cuda_when_available(self):
        def find_spec(name):
            return object() if name in {"faster_whisper", "ctranslate2"} else None

        fake_ctranslate2 = type("FakeCT2", (), {"get_cuda_device_count": staticmethod(lambda: 1)})
        with patch("backend.media.importlib.util.find_spec", side_effect=find_spec),              patch.dict("sys.modules", {"ctranslate2": fake_ctranslate2}):
            result = check_asr_runtime("auto")
        self.assertEqual(result["selected_device"], "cuda")
        self.assertEqual(result["cuda_devices"], 1)

    def test_probe_media_rejects_missing_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "missing"):
                probe_media(Path(tmp) / "nope.mp4")

    def test_probe_media_accepts_valid_ffprobe_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "movie.mp4"
            source.write_bytes(b"movie")
            payload = {
                "format": {"duration": "12.5", "format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
                "streams": [
                    {"index": 0, "codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080},
                    {"index": 1, "codec_type": "audio", "codec_name": "aac", "channels": 2, "sample_rate": "48000"},
                ],
            }
            fake = type("Result", (), {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""})
            with patch("backend.media._bin", return_value="ffprobe"),                  patch("backend.media.subprocess.run", return_value=fake):
                result = probe_media(source)
            self.assertEqual(result["duration_sec"], 12.5)
            self.assertEqual(result["video_stream_count"], 1)
            self.assertEqual(result["audio_stream_count"], 1)


if __name__ == "__main__":
    unittest.main()
