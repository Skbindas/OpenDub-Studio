from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from backend.mixing import mix_project
from backend.rendering import cleanup_intermediates, mux_movie, verify_render_qa


class MixAndRenderQATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ffmpeg = shutil.which("ffmpeg")
        cls.ffprobe = shutil.which("ffprobe")
        if not cls.ffmpeg or not cls.ffprobe:
            raise unittest.SkipTest("FFmpeg/ffprobe required for mix and render QA tests")

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.analysis_dir = self.root / "analysis"
        self.output_dir = self.root / "output"
        self.segments_dir = self.root / "segments"
        for d in (self.analysis_dir, self.output_dir, self.segments_dir):
            d.mkdir(parents=True, exist_ok=True)

        # 1. Create a 3-second source movie fixture
        self.source_movie = self.root / "source_movie.mp4"
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
                "color=c=black:s=320x240:r=24:d=3.0",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=48000:duration=3.0",
                "-shortest",
                "-c:v",
                "mpeg4",
                "-c:a",
                "aac",
                str(self.source_movie),
            ],
            check=True,
            capture_output=True,
        )

        # 2. Create a dialogue clip (1 second, 48kHz mono)
        self.dialogue_clip = self.segments_dir / "seg_000000_fit.wav"
        with wave.open(str(self.dialogue_clip), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(48000)
            frames = bytearray()
            for n in range(48000):
                s = int(8000 * math.sin(2 * math.pi * 600 * n / 48000))
                frames.extend(struct.pack("<h", s))
            w.writeframes(frames)

        # 3. Create translated_transcript.json
        self.transcript_file = self.analysis_dir / "translated_transcript.json"
        self.transcript_file.write_text(
            json.dumps(
                {
                    "target_language": "hi",
                    "segments": [
                        {
                            "segment_index": 0,
                            "start": 0.5,
                            "end": 1.5,
                            "translated_text": "नमस्ते दुनिया",
                            "fitted_audio": str(self.dialogue_clip),
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        # 4. Create dialogue_manifest.json
        self.manifest_file = self.analysis_dir / "dialogue_manifest.json"
        self.manifest_file.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "units": [
                        {
                            "segment_index": 0,
                            "start_sec": 0.5,
                            "end_sec": 1.5,
                            "timing": {
                                "status": "completed",
                                "output_path": str(self.dialogue_clip),
                            },
                        }
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        # 5. Create background_preserved.wav in output
        self.preserved_bg = self.output_dir / "background_preserved.wav"
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
                "sine=frequency=220:sample_rate=48000:duration=3.0",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                str(self.preserved_bg),
            ],
            check=True,
            capture_output=True,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_mix_project_auto_resolves_preserved_background(self):
        mixed_out = self.output_dir / "dubbed_audio_mix.wav"
        # Passing background=None triggers auto-discovery of background_preserved.wav
        res = mix_project(self.root, background=None, out=mixed_out, target_lufs=-16.0)

        self.assertTrue(mixed_out.is_file())
        self.assertEqual(res["dialogue_segments_mixed"], 1)
        self.assertTrue(res["background_used"])
        self.assertEqual(res["background_path"], str(self.preserved_bg))

        # Check mix_manifest.json
        mix_manifest_file = self.output_dir / "mix_manifest.json"
        self.assertTrue(mix_manifest_file.is_file())
        manifest = json.loads(mix_manifest_file.read_text(encoding="utf-8"))
        self.assertEqual(manifest["target_lufs"], -16.0)
        self.assertEqual(manifest["dialogue_segments_mixed"], 1)
        self.assertTrue(manifest["background_used"])

    def test_verify_render_qa_full_workflow_passes(self):
        mixed_out = self.output_dir / "dubbed_audio_mix.wav"
        mix_project(self.root, background=None, out=mixed_out)

        rendered_mp4 = self.output_dir / "final_dubbed.mp4"
        mux_res = mux_movie(self.source_movie, mixed_out, rendered_mp4, video_codec="mpeg4")
        self.assertEqual(mux_res["status"], "completed")

        # Run automated QA verification
        qa = verify_render_qa(
            source=self.source_movie,
            output=rendered_mp4,
            dialogue_manifest_path=self.manifest_file,
            mix_manifest_path=self.output_dir / "mix_manifest.json",
        )

        self.assertEqual(qa["status"], "PASSED")
        self.assertAlmostEqual(qa["render_duration_sec"], 3.0, delta=0.5)

        # Verify all core checks passed
        check_names = {c["name"]: c["status"] for c in qa["checks"]}
        self.assertEqual(check_names.get("File existence & size"), "pass")
        self.assertEqual(check_names.get("Container integrity"), "pass")
        self.assertEqual(check_names.get("Video stream"), "pass")
        self.assertEqual(check_names.get("Audio stream"), "pass")
        self.assertEqual(check_names.get("Duration alignment"), "pass")
        self.assertEqual(check_names.get("Dialogue coverage"), "pass")
        self.assertEqual(check_names.get("Cleanup integrity"), "pass")

        # Verify report was persisted
        report_path = self.output_dir / "render_qa_report.json"
        self.assertTrue(report_path.is_file())

    def test_verify_render_qa_detects_missing_file(self):
        missing_mp4 = self.output_dir / "does_not_exist.mp4"
        qa = verify_render_qa(source=self.source_movie, output=missing_mp4)
        self.assertEqual(qa["status"], "FAILED")
        self.assertEqual(qa["checks"][0]["status"], "fail")

    def test_cleanup_intermediates_preserves_critical_artifacts(self):
        # Place dummy intermediate files
        source_16k = self.analysis_dir / "source_16k_mono.wav"
        source_16k.write_text("dummy", encoding="utf-8")
        dummy_seg = self.segments_dir / "dummy_intermediate.wav"
        dummy_seg.write_text("dummy", encoding="utf-8")

        res = cleanup_intermediates(self.root)
        self.assertIn("source movie", res["preserved"])
        self.assertIn("final render", res["preserved"])
        self.assertIn("final audio mix", res["preserved"])

        # Regenerable intermediates are removed
        self.assertFalse(source_16k.exists())
        self.assertFalse(self.segments_dir.exists())

        # Source movie and manifests are strictly preserved
        self.assertTrue(self.source_movie.is_file())
        self.assertTrue(self.manifest_file.is_file())
        self.assertTrue(self.transcript_file.is_file())


if __name__ == "__main__":
    unittest.main()
