from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.media import analyze_audio_profile


class AudioProfileTests(unittest.TestCase):
    def test_parses_metrics_and_paired_silence_regions(self):
        diagnostics = """
[Parsed_astats_0] Peak level dB: -1.25
[Parsed_astats_0] RMS level dB: -18.50
[silencedetect] silence_start: 2.000
[silencedetect] silence_end: 3.250 | silence_duration: 1.250
"""
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "audio_profile.json"
            with patch("backend.media._bin", return_value="ffmpeg"), patch(
                "backend.media.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stderr=diagnostics),
            ):
                profile = analyze_audio_profile(Path("source.wav"), output)
            self.assertEqual(profile["peak_level_db"], -1.25)
            self.assertEqual(profile["rms_level_db"], -18.5)
            self.assertEqual(profile["silence_regions"], [
                {"start_sec": 2.0, "end_sec": 3.25, "duration_sec": 1.25}
            ])
            self.assertEqual(json.loads(output.read_text())["schema_version"], 1)

    def test_missing_metrics_remain_null(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "profile.json"
            with patch("backend.media._bin", return_value="ffmpeg"), patch(
                "backend.media.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stderr="astats: no samples"),
            ):
                profile = analyze_audio_profile(Path("source.wav"), output)
            self.assertIsNone(profile["peak_level_db"])
            self.assertIsNone(profile["rms_level_db"])


if __name__ == "__main__":
    unittest.main()
