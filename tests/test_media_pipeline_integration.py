
"""Tiny deterministic, redistributable media fixtures for pipeline integration tests.

Generated locally with FFmpeg lavfi; no third-party copyrighted media is included.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
import json
import wave
import math
import struct
from pathlib import Path

from backend.mixing import mix_project
from backend.rendering import mux_movie


class TranslationSynthesisRenderIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ffmpeg = shutil.which("ffmpeg")
        cls.ffprobe = shutil.which("ffprobe")
        if not cls.ffmpeg or not cls.ffprobe:
            raise unittest.SkipTest(
                "FFmpeg and ffprobe are required for media integration tests"
            )
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name) / "fixture-project"
        cls.analysis = cls.root / "analysis"
        cls.segments = cls.root / "segments"
        cls.output = cls.root / "output"
        for folder in (cls.analysis, cls.segments, cls.output):
            folder.mkdir(parents=True, exist_ok=True)

        cls.source = cls.root / "source_fixture.mp4"
        subprocess.run([
            cls.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=12:d=1.5",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1.5",
            "-shortest", "-c:v", "mpeg4", "-pix_fmt", "yuv420p", "-c:a", "aac",
            str(cls.source)
        ], check=True, capture_output=True, timeout=30)

        cls.dub_clip = cls.segments / "synthetic_dialogue.wav"
        with wave.open(str(cls.dub_clip), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(48000)
            frames = bytearray()
            for n in range(48000):
                sample = int(7000 * math.sin(2 * math.pi * 660 * n / 48000))
                frames.extend(struct.pack("<h", sample))
            wav.writeframes(frames)

        (cls.analysis / "translated_transcript.json").write_text(
            json.dumps({
                "target_language": "hi",
                "segments": [{
                    "segment_index": 0,
                    "start": 0.2,
                    "end": 1.2,
                    "translated_text": "नमस्ते",
                    "dub_audio": str(cls.dub_clip)
                }]
            }, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_sixty_second_render_resource_and_artifact_profile(self):
        # One-minute generated fixture exercises a longer timeline without checked-in media.
        source = self.root / "sixty_second_source.mp4"
        subprocess.run([
            self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=darkblue:s=640x360:r=24:d=60",
            "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=60",
            "-shortest", "-c:v", "mpeg4", "-q:v", "8", "-threads", "2",
            "-c:a", "aac", "-b:a", "96k", str(source)
        ], check=True, capture_output=True, timeout=120)

        audio = self.output / "sixty_second_dub.wav"
        subprocess.run([
            self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "sine=frequency=660:sample_rate=48000:duration=60",
            "-c:a", "pcm_s16le", str(audio)
        ], check=True, capture_output=True, timeout=60)

        output = self.output / "sixty_second_render.mp4"
        started = __import__("time").monotonic()
        result = mux_movie(source, audio, output, video_codec="mpeg4")
        elapsed = __import__("time").monotonic() - started

        self.assertEqual(result["status"], "completed")
        self.assertGreater(result["size_bytes"], 250_000)

        # FFmpeg peak RSS sampling is supported on Linux CI.
        # Windows may report 0 because its process resource sampling differs.
        if os.name != "nt":
            self.assertGreater(
                result.get("peak_process_rss_bytes", 0),
                0,
                "FFmpeg peak RSS should be sampled on Linux CI"
            )

        self.assertLess(
            elapsed, 180,
            f"60-second render exceeded 180s budget: {elapsed:.1f}s"
        )

        probe = subprocess.run([
            self.ffprobe, "-v", "error", "-show_entries", "format=duration,size",
            "-of", "json", str(output)
        ], check=True, capture_output=True, text=True, timeout=30)

        metadata = json.loads(probe.stdout)["format"]
        self.assertGreaterEqual(float(metadata["duration"]), 59.0)
        self.assertGreater(int(metadata["size"]), 250_000)
        self.assertFalse(
            (self.output / "sixty_second_render.partial.mp4").exists()
        )

        # Retain observed runtime and output bytes in unittest diagnostics for CI artifacts/logs.
        print(
            f"STRESS_PROFILE duration_s=60 elapsed_s={elapsed:.2f} "
            f"output_bytes={result['size_bytes']} "
            f"peak_ffmpeg_rss_bytes={result.get('peak_process_rss_bytes', 0)}"
        )

    def test_extended_render_stress_and_cancellation_cleanup(self):
        long_source = self.root / "stress_source.mp4"
        subprocess.run([
            self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:duration=20",
            "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=20",
            "-shortest", "-c:v", "mpeg4", "-q:v", "5", "-c:a", "aac",
            str(long_source)
        ], check=True, capture_output=True, timeout=60)

        long_audio = self.output / "stress_mix.wav"
        subprocess.run([
            self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "sine=frequency=660:sample_rate=48000:duration=20",
            "-c:a", "pcm_s16le", str(long_audio)
        ], check=True, capture_output=True, timeout=30)

        long_output = self.output / "stress_dubbed.mp4"
        result = mux_movie(
            long_source, long_audio, long_output, video_codec="mpeg4"
        )
        self.assertEqual(result["status"], "completed")
        self.assertGreater(result["size_bytes"], 100_000)
        self.assertFalse(
            (self.output / "stress_dubbed.partial.mp4").exists()
        )

        cancelled_output = self.output / "cancelled_dubbed.mp4"
        with self.assertRaisesRegex(InterruptedError, "Render cancelled"):
            mux_movie(
                long_source,
                long_audio,
                cancelled_output,
                video_codec="mpeg4",
                cancel_check=lambda: True
            )

        self.assertFalse(cancelled_output.exists())
        self.assertFalse(
            (self.output / "cancelled_dubbed.partial.mp4").exists()
        )

    def test_feature_length_timeline_render_and_failure_cleanup(self):
        # 90-minute synthetic timeline using low-frame-rate static video and compressed audio
        # keeps CI storage modest while exercising long-duration timestamp/container handling.
        duration = 5400
        source = self.root / "feature_length_source.mp4"
        subprocess.run([
            self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:r=1:d={duration}",
            "-f", "lavfi", "-i", f"sine=frequency=180:sample_rate=48000:duration={duration}",
            "-shortest", "-c:v", "mpeg4", "-q:v", "10", "-threads", "1",
            "-c:a", "aac", "-b:a", "48k", str(source)
        ], check=True, capture_output=True, timeout=180)

        audio = self.output / "feature_length_dub.m4a"
        subprocess.run([
            self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"sine=frequency=660:sample_rate=48000:duration={duration}",
            "-c:a", "aac", "-b:a", "64k", str(audio)
        ], check=True, capture_output=True, timeout=180)

        output = self.output / "feature_length_render.mp4"
        started = __import__("time").monotonic()
        result = mux_movie(source, audio, output, video_codec="copy")
        elapsed = __import__("time").monotonic() - started

        self.assertEqual(result["status"], "completed")

        # RSS sampling can return 0 on Windows; enforce this check on Linux CI.
        if os.name != "nt":
            self.assertGreater(
                result.get("peak_process_rss_bytes", 0),
                0,
                "FFmpeg peak RSS should be sampled on Linux CI"
            )

        probe = subprocess.run([
            self.ffprobe, "-v", "error", "-show_entries", "format=duration,size",
            "-of", "json", str(output)
        ], check=True, capture_output=True, text=True, timeout=60)

        metadata = json.loads(probe.stdout)["format"]
        rendered_duration = float(metadata["duration"])
        self.assertGreaterEqual(rendered_duration, duration - 2)
        self.assertGreater(int(metadata["size"]), 1_000_000)
        self.assertFalse(
            (self.output / "feature_length_render.partial.mp4").exists()
        )

        failed = self.output / "failed_codec_render.mp4"
        with self.assertRaises(RuntimeError):
            mux_movie(
                source,
                audio,
                failed,
                video_codec="definitely_invalid_codec"
            )

        self.assertFalse(failed.exists())
        self.assertFalse(
            (self.output / "failed_codec_render.partial.mp4").exists()
        )

        print(
            f"FEATURE_RENDER_PROFILE timeline_s={duration} "
            f"observed_s={rendered_duration:.2f} elapsed_s={elapsed:.2f} "
            f"output_bytes={result['size_bytes']} "
            f"peak_ffmpeg_rss_bytes={result.get('peak_process_rss_bytes', 0)}"
        )

    def test_synthetic_fixture_translation_synthesis_mix_and_render(self):
        # Fixture transcript represents the output contract of translation; the generated
        # WAV represents deterministic TTS output, avoiding external model downloads.
        transcript = json.loads(
            (self.analysis / "translated_transcript.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            transcript["segments"][0]["translated_text"], "नमस्ते"
        )
        self.assertTrue(
            self.dub_clip.is_file() and self.dub_clip.stat().st_size > 1000
        )

        mixed = self.output / "dubbed_audio_mix.wav"
        mix_result = mix_project(self.root, None, mixed)
        self.assertEqual(mix_result["dialogue_segments_mixed"], 1)
        self.assertTrue(mixed.is_file() and mixed.stat().st_size > 1000)

        rendered = self.output / "fixture_dubbed.mp4"
        render_result = mux_movie(
            self.source, mixed, rendered, video_codec="mpeg4"
        )
        self.assertEqual(render_result["status"], "completed")
        self.assertTrue(
            rendered.is_file() and rendered.stat().st_size > 1000
        )

        probe = subprocess.run([
            self.ffprobe, "-v", "error", "-show_entries", "stream=codec_type",
            "-of", "json", str(rendered)
        ], check=True, capture_output=True, text=True, timeout=30)

        stream_types = {
            stream["codec_type"]
            for stream in json.loads(probe.stdout)["streams"]
        }
        self.assertIn("video", stream_types)
        self.assertIn("audio", stream_types)


if __name__ == "__main__":
    unittest.main()