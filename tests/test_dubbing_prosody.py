import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.dubbing import synthesize_piper_segment


class PiperProsodyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.model = self.root / "voice.onnx"
        self.model.write_bytes(b"model")
        self.output = self.root / "out" / "segment.wav"

    def tearDown(self):
        self.temp.cleanup()

    def _run_piper(self, prosody):
        def fake_run(command, **kwargs):
            self.command = command
            self.output.write_bytes(b"wav")
            class Result:
                returncode = 0
                stderr = ""
            return Result()

        with patch("backend.dubbing.shutil.which", return_value="piper"), \
             patch("backend.dubbing.subprocess.run", side_effect=fake_run):
            result = synthesize_piper_segment(
                "Hello there", self.output, self.model, speaker_id=2, prosody=prosody
            )
        return result

    def test_rate_maps_to_inverse_piper_length_scale(self):
        result = self._run_piper({"rate": 1.25})
        self.assertIn("--length_scale", self.command)
        scale_index = self.command.index("--length_scale") + 1
        self.assertEqual(self.command[scale_index], "0.8000")
        self.assertEqual(self.command[self.command.index("--speaker") + 1], "2")
        self.assertEqual(result["prosody_applied"]["rate"], 1.25)
        self.assertEqual(result["prosody_status"], "applied")
        self.assertEqual(result["prosody_unsupported"], [])

    def test_unsupported_prosody_is_reported(self):
        result = self._run_piper({
            "rate": 1.0, "emotion": "warm", "delivery": "whisper",
            "pitch": 2, "volume": 0.8,
        })
        self.assertEqual(
            result["prosody_unsupported"], ["emotion", "delivery", "pitch", "volume"]
        )
        self.assertEqual(result["prosody_status"], "partial")

    def test_out_of_range_rate_is_rejected(self):
        with patch("backend.dubbing.shutil.which", return_value="piper"):
            with self.assertRaisesRegex(RuntimeError, "between 0.5 and 2.0"):
                synthesize_piper_segment("Hello", self.output, self.model, prosody={"rate": 2.1})


if __name__ == "__main__":
    unittest.main()
