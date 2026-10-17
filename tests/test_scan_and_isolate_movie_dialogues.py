"""Unit tests for scripts/scan_and_isolate_movie_dialogues.py.

Verifies:
  1. Cross-platform path resolution (Windows <-> WSL).
  2. FFmpeg binary resolution.
  3. Dialogue text cleaning and Whisper music/noise filtering.
  4. Contiguous dialogue utterance chaining into [6.0s - 12.0s] windows.
  5. Atomic manifest writing and resume capability.
  6. End-to-end pipeline simulation with mocked FFmpeg and WhisperModel.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import sys
import unittest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.scan_and_isolate_movie_dialogues import (
    build_dialogue_chains,
    clean_transcript_text,
    format_seconds,
    is_valid_speech_utterance,
    isolate_dialogue_clip,
    resolve_ffmpeg,
    resolve_system_path,
    run_pipeline,
    save_manifest_atomic,
    MIN_CLIP_DURATION,
    MAX_CLIP_DURATION,
)


class TestScanAndIsolateMovieDialogues(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_movie_vocal_"))

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_format_seconds(self):
        self.assertEqual(format_seconds(0.0), "00:00:00.000")
        self.assertEqual(format_seconds(65.5), "00:01:05.500")
        self.assertEqual(format_seconds(3661.125), "01:01:01.125")

    def test_resolve_system_path(self):
        # Local relative path
        p = resolve_system_path("scripts")
        self.assertTrue(p.exists())

        # Windows path translation in Linux/WSL
        win_path = r"C:\Users\test\file.mp4"
        resolved = resolve_system_path(win_path)
        # Should translate to /mnt/c/Users/test/file.mp4 if on Linux/WSL
        self.assertTrue(str(resolved).startswith("/mnt/c/") or str(resolved).startswith("C:"))

    def test_resolve_ffmpeg(self):
        ffmpeg_bin = resolve_ffmpeg()
        self.assertTrue(isinstance(ffmpeg_bin, str))
        self.assertTrue(len(ffmpeg_bin) > 0)

        # Custom non-existent path falls back safely
        fallback = resolve_ffmpeg("non_existent_ffmpeg_bin_12345")
        self.assertTrue(len(fallback) > 0)

    def test_clean_transcript_text(self):
        raw = "  [Music]  नमस्ते भाई   ♪♪ (Applause)  कैसा है तू?  "
        cleaned = clean_transcript_text(raw)
        self.assertEqual(cleaned, "नमस्ते भाई कैसा है तू?")

        hindi_tag = "[संगीत] जनता गराज [तालियाँ]"
        self.assertEqual(clean_transcript_text(hindi_tag), "जनता गराज")

    def test_is_valid_speech_utterance(self):
        # Valid dialogue
        self.assertTrue(is_valid_speech_utterance(
            text="मुझसे पंगा मत लेना",
            no_speech_prob=0.05,
            avg_logprob=-0.2,
            compression_ratio=1.1,
        ))

        # Pure music / noise prob too high
        self.assertFalse(is_valid_speech_utterance(
            text="ला ला ला",
            no_speech_prob=0.85,
            avg_logprob=-0.2,
        ))

        # Low confidence logprob
        self.assertFalse(is_valid_speech_utterance(
            text="...",
            no_speech_prob=0.1,
            avg_logprob=-1.6,
        ))

        # Whisper repetitive hallucination
        self.assertFalse(is_valid_speech_utterance(
            text="हा हा हा हा हा हा हा हा हा हा हा हा",
            no_speech_prob=0.1,
            avg_logprob=-0.3,
            compression_ratio=2.8,
        ))

        # Pure music tag
        self.assertFalse(is_valid_speech_utterance(
            text="[Music]",
            no_speech_prob=0.1,
            avg_logprob=-0.2,
        ))

    def test_build_dialogue_chains_contiguous(self):
        # Test 1: Single segment already in [6.0s - 12.0s]
        single = [
            {"start": 10.0, "end": 17.5, "duration": 7.5, "text": "मैं यहाँ का कानून हूँ", "clean_text": "मैं यहाँ का कानून हूँ"}
        ]
        chains = build_dialogue_chains(single, min_clip_sec=6.0, max_clip_sec=12.0)
        self.assertEqual(len(chains), 1)
        self.assertEqual(chains[0]["start_sec"], 10.0)
        self.assertEqual(chains[0]["end_sec"], 17.5)
        self.assertEqual(chains[0]["duration"], 7.5)

        # Test 2: Two contiguous utterances (3.0s + gap 0.4s + 4.0s = 7.4s)
        contiguous = [
            {"start": 20.0, "end": 23.0, "duration": 3.0, "text": "गाड़ी रोक", "clean_text": "गाड़ी रोक"},
            {"start": 23.4, "end": 27.4, "duration": 4.0, "text": "और चाबी मुझे दे", "clean_text": "और चाबी मुझे दे"},
        ]
        chains = build_dialogue_chains(contiguous, min_clip_sec=6.0, max_clip_sec=12.0, max_gap=1.0)
        self.assertEqual(len(chains), 1)
        self.assertEqual(chains[0]["start_sec"], 20.0)
        self.assertEqual(chains[0]["end_sec"], 27.4)
        self.assertEqual(chains[0]["duration"], 7.4)
        self.assertIn("गाड़ी रोक", chains[0]["text"])
        self.assertIn("चाबी मुझे दे", chains[0]["text"])

        # Test 3: Short utterance with large gap (>1.0s) should NOT chain and should be discarded
        separated = [
            {"start": 30.0, "end": 32.5, "duration": 2.5, "text": "हाँ", "clean_text": "हाँ"},
            {"start": 36.0, "end": 38.0, "duration": 2.0, "text": "नहीं", "clean_text": "नहीं"},
        ]
        chains = build_dialogue_chains(separated, min_clip_sec=6.0, max_clip_sec=12.0, max_gap=1.0)
        self.assertEqual(len(chains), 0)

    def test_build_dialogue_chains_long_monologue_partition(self):
        # Monologue of 18 seconds should be partitioned into <=12s chunks
        long_mono = [
            {"start": 50.0, "end": 68.0, "duration": 18.0, "text": "यह शहर हमारा है और हम इस शहर को कभी बर्बाद नहीं होने देंगे", "clean_text": "यह शहर हमारा है और हम इस शहर को कभी बर्बाद नहीं होने देंगे"}
        ]
        chains = build_dialogue_chains(long_mono, min_clip_sec=6.0, max_clip_sec=12.0)
        self.assertTrue(len(chains) >= 2)
        for c in chains:
            self.assertTrue(MIN_CLIP_DURATION <= c["duration"] <= MAX_CLIP_DURATION + 0.1)

    def test_save_manifest_atomic(self):
        manifest_path = self.test_dir / "dialogue_manifest.json"
        data = [
            {"clip_id": "dialogue_0001", "start_sec": 10.0, "end_sec": 17.0, "duration": 7.0, "text": "टेस्ट", "clip_path": "test.wav"}
        ]
        save_manifest_atomic(manifest_path, data)
        self.assertTrue(manifest_path.is_file())

        with open(manifest_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["clip_id"], "dialogue_0001")

    @patch("scripts.scan_and_isolate_movie_dialogues.isolate_dialogue_clip")
    @patch("scripts.scan_and_isolate_movie_dialogues.extract_master_audio")
    @patch("scripts.scan_and_isolate_movie_dialogues.detect_movie_dialogues")
    def test_pipeline_resumption_and_execution(self, mock_detect, mock_extract, mock_isolate):
        mock_extract.return_value = True
        mock_isolate.return_value = True
        mock_detect.return_value = [
            {
                "start": 100.0,
                "end": 107.5,
                "duration": 7.5,
                "text": "जनता गराज में सबका स्वागत है",
                "clean_text": "जनता गराज में सबका स्वागत है",
                "no_speech_prob": 0.05,
                "avg_logprob": -0.15,
                "compression_ratio": 1.2,
            },
            {
                "start": 200.0,
                "end": 208.0,
                "duration": 8.0,
                "text": "प्रकृति के साथ खिलवाड़ मत करो",
                "clean_text": "प्रकृति के साथ खिलवाड़ मत करो",
                "no_speech_prob": 0.02,
                "avg_logprob": -0.10,
                "compression_ratio": 1.1,
            },
        ]

        dummy_movie = self.test_dir / "dummy_movie.mp4"
        dummy_movie.write_bytes(b"dummy_mp4_bytes")

        output_dir = self.test_dir / "output_test"

        summary = run_pipeline(
            movie_path_str=str(dummy_movie),
            ffmpeg_path_str="ffmpeg",
            output_dir_str=str(output_dir),
            model_size="small",
            device="cpu",
            language="hi",
            min_clip_sec=6.0,
            max_clip_sec=12.0,
            resume=True,
        )

        self.assertEqual(summary["status"], "success")
        self.assertEqual(summary["total_dialogues_extracted"], 2)

        manifest_file = output_dir / "dialogue_manifest.json"
        self.assertTrue(manifest_file.is_file())
        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(len(manifest), 2)
        self.assertEqual(manifest[0]["clip_id"], "dialogue_0001")
        self.assertEqual(manifest[0]["start_sec"], 100.0)
        self.assertEqual(manifest[0]["duration"], 7.5)
        self.assertEqual(manifest[1]["clip_id"], "dialogue_0002")
        self.assertEqual(manifest[1]["start_sec"], 200.0)
        self.assertEqual(manifest[1]["duration"], 8.0)

    @patch("scripts.scan_and_isolate_movie_dialogues.isolate_dialogue_clip")
    @patch("scripts.scan_and_isolate_movie_dialogues.extract_master_audio")
    @patch("scripts.scan_and_isolate_movie_dialogues.detect_movie_dialogues")
    def test_pipeline_resumes_existing_clips(self, mock_detect, mock_extract, mock_isolate):
        mock_extract.return_value = True
        mock_detect.return_value = [
            {"start": 10.0, "end": 17.0, "duration": 7.0, "text": "पहला संवाद", "clean_text": "पहला संवाद"},
            {"start": 30.0, "end": 38.0, "duration": 8.0, "text": "दूसरा संवाद", "clean_text": "दूसरा संवाद"},
        ]

        dummy_movie = self.test_dir / "movie.mp4"
        dummy_movie.write_bytes(b"dummy")
        output_dir = self.test_dir / "output_resume"
        raw_clips = output_dir / "raw_clips"
        raw_clips.mkdir(parents=True, exist_ok=True)

        # Pre-create dialogue_0001.wav as already extracted
        clip1_path = raw_clips / "dialogue_0001.wav"
        clip1_path.write_bytes(b"x" * 3000)

        # Pre-seed manifest with dialogue_0001
        manifest_path = output_dir / "dialogue_manifest.json"
        existing_data = [
            {
                "clip_id": "dialogue_0001",
                "start_sec": 10.0,
                "end_sec": 17.0,
                "duration": 7.0,
                "text": "पहला संवाद",
                "clip_path": "storage/movie_vocal_extraction/raw_clips/dialogue_0001.wav",
            }
        ]
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(existing_data, f)

        mock_isolate.return_value = True

        run_pipeline(
            movie_path_str=str(dummy_movie),
            ffmpeg_path_str="ffmpeg",
            output_dir_str=str(output_dir),
            model_size="small",
            device="cpu",
            language="hi",
            resume=True,
        )

        # isolate_dialogue_clip should have been called only ONCE (for dialogue_0002)
        self.assertEqual(mock_isolate.call_count, 1)


if __name__ == "__main__":
    unittest.main()

