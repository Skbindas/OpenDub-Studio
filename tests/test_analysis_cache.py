from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.analysis_pipeline import invalidate_downstream_artifacts


class AnalysisCacheTests(unittest.TestCase):
    def test_invalidate_downstream_artifacts_keeps_source_and_removes_generated_work(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "source").mkdir()
            (root / "analysis").mkdir()
            (root / "segments").mkdir()
            (root / "output").mkdir()
            (root / "source" / "original.mp4").write_bytes(b"source")
            (root / "analysis" / "timeline.json").write_text("{}", encoding="utf-8")
            (root / "segments" / "segment.wav").write_bytes(b"audio")
            (root / "output" / "dubbed_audio_mix.wav").write_bytes(b"mix")
            (root / "characters").mkdir()
            (root / "characters" / "registry.json").write_text("{}", encoding="utf-8")

            invalidate_downstream_artifacts(root, preserve_characters=True)

            self.assertTrue((root / "source" / "original.mp4").is_file())
            self.assertFalse((root / "analysis" / "timeline.json").exists())
            self.assertFalse((root / "segments" / "segment.wav").exists())
            self.assertFalse((root / "output" / "dubbed_audio_mix.wav").exists())
            self.assertTrue((root / "characters" / "registry.json").is_file())
            archived = list((root / ".history").glob("*/segments/segment.wav"))
            self.assertEqual(len(archived), 1)
            self.assertEqual(archived[0].read_bytes(), b"audio")
            self.assertEqual(next((root / ".history").glob("*/output/dubbed_audio_mix.wav")).read_bytes(), b"mix")


if __name__ == "__main__":
    unittest.main()
