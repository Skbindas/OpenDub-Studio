"""Unit tests for scripts/cluster_and_catalog_movie_characters.py.

Verifies:
1. Autocorrelation F0 pitch tracking (50 Hz - 500 Hz range).
2. Spectral centroid & formant extraction.
3. Gender and demographic classification.
4. Agglomerative clustering and silhouette optimization.
5. Quality ranking and 8-10s acapella reference candidate export.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import tempfile
import unittest

import sys
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.cluster_and_catalog_movie_characters import (
    classify_age_group,
    classify_gender,
    cluster_dialogue_clips,
    compute_frame_f0_autocorrelation,
    compute_spectral_features,
    extract_clip_acoustic_features,
    format_timecode,
    match_theatrical_profile,
    run_speaker_clustering_pipeline,
    write_synthetic_vocal_clip,
    write_wav_pcm16,
)


class MovieCharacterClusteringTests(unittest.TestCase):
    """Test suite for movie character clustering and voice cataloging."""

    def test_01_timecode_formatting(self):
        self.assertEqual(format_timecode(0.0), "00:00:00")
        self.assertEqual(format_timecode(75.0), "00:01:15")
        self.assertEqual(format_timecode(3665.0), "01:01:05")

    def test_02_autocorrelation_f0_pitch_detection(self):
        sr = 16000
        # Test low male pitch (95 Hz)
        sig_95 = [math.sin(2.0 * math.pi * 95.0 * i / sr) for i in range(720)]
        f0_95, corr_95 = compute_frame_f0_autocorrelation(sig_95, sr, min_f0_hz=50.0, max_f0_hz=500.0)
        self.assertIsNotNone(f0_95)
        self.assertGreater(corr_95, 0.90)
        self.assertTrue(90.0 <= f0_95 <= 100.0)

        # Test female pitch (220 Hz)
        sig_220 = [math.sin(2.0 * math.pi * 220.0 * i / sr) for i in range(720)]
        f0_220, corr_220 = compute_frame_f0_autocorrelation(sig_220, sr, min_f0_hz=50.0, max_f0_hz=500.0)
        self.assertIsNotNone(f0_220)
        self.assertGreater(corr_220, 0.90)
        self.assertTrue(210.0 <= f0_220 <= 230.0)

    def test_03_demographic_classification_and_theatrical_matching(self):
        # Male Elderly (< 100 Hz)
        self.assertEqual(classify_gender(92.0), "male")
        self.assertEqual(classify_age_group(92.0, "male"), "elderly")
        t_elder = match_theatrical_profile("male", "elderly", 92.0)
        self.assertEqual(t_elder["theatrical_profile_id"], "hi_avengers_elder_chief")

        # Male Adult (125 Hz)
        self.assertEqual(classify_gender(125.0), "male")
        self.assertEqual(classify_age_group(125.0, "male"), "adult")
        t_hero = match_theatrical_profile("male", "adult", 125.0)
        self.assertEqual(t_hero["theatrical_profile_id"], "hi_avengers_hero_male")

        # Female Adult (210 Hz)
        self.assertEqual(classify_gender(210.0), "female")
        self.assertEqual(classify_age_group(210.0, "female"), "adult")
        t_female = match_theatrical_profile("female", "adult", 210.0)
        self.assertEqual(t_female["theatrical_profile_id"], "hi_avengers_lead_female")

    def test_04_silhouette_speaker_clustering(self):
        # 3 distinct speaker profiles (male elder 92Hz, male adult 125Hz, female lead 215Hz)
        clips = []
        for _ in range(3):
            clips.append({
                "f0_median_hz": 92.0,
                "spectral_centroid_hz": 600.0,
                "formant_ratio_1_2": 1.5,
                "formant_ratio_2_3": 1.2,
                "voiced_ratio": 0.85,
                "zcr_mean": 0.04,
                "snr_db": 30.0,
            })
            clips.append({
                "f0_median_hz": 125.0,
                "spectral_centroid_hz": 950.0,
                "formant_ratio_1_2": 1.2,
                "formant_ratio_2_3": 1.1,
                "voiced_ratio": 0.85,
                "zcr_mean": 0.05,
                "snr_db": 30.0,
            })
            clips.append({
                "f0_median_hz": 215.0,
                "spectral_centroid_hz": 1600.0,
                "formant_ratio_1_2": 0.8,
                "formant_ratio_2_3": 0.9,
                "voiced_ratio": 0.85,
                "zcr_mean": 0.06,
                "snr_db": 30.0,
            })

        labels, meta = cluster_dialogue_clips(clips, min_k=2, max_k=5)
        self.assertGreaterEqual(meta["optimal_k"], 2)
        self.assertGreater(meta["best_silhouette"], 0.30)
        self.assertEqual(len(labels), len(clips))

    def test_05_end_to_end_pipeline_execution(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            raw_clips_dir = tmp / "raw_clips"
            manifest_file = tmp / "dialogue_manifest.json"
            out_bank = tmp / "candidate_voices"

            # Create 4 synthetic clips (2 male elder, 2 female lead)
            clip1 = raw_clips_dir / "clip_01.wav"
            clip2 = raw_clips_dir / "clip_02.wav"
            clip3 = raw_clips_dir / "clip_03.wav"
            clip4 = raw_clips_dir / "clip_04.wav"

            write_synthetic_vocal_clip(clip1, duration_sec=8.5, f0_hz=92.0, gender="male")
            write_synthetic_vocal_clip(clip2, duration_sec=9.0, f0_hz=92.0, gender="male")
            write_synthetic_vocal_clip(clip3, duration_sec=8.8, f0_hz=215.0, gender="female")
            write_synthetic_vocal_clip(clip4, duration_sec=9.2, f0_hz=215.0, gender="female")

            manifest_data = [
                {"clip_id": "clip_0001", "audio_path": "raw_clips/clip_01.wav", "start_sec": 10.0, "end_sec": 18.5, "text": "संवाद एक"},
                {"clip_id": "clip_0002", "audio_path": "raw_clips/clip_02.wav", "start_sec": 30.0, "end_sec": 39.0, "text": "संवाद दो"},
                {"clip_id": "clip_0003", "audio_path": "raw_clips/clip_03.wav", "start_sec": 60.0, "end_sec": 68.8, "text": "संवाद तीन"},
                {"clip_id": "clip_0004", "audio_path": "raw_clips/clip_04.wav", "start_sec": 90.0, "end_sec": 99.2, "text": "संवाद चार"},
            ]
            manifest_file.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

            summary = run_speaker_clustering_pipeline(
                manifest_path=manifest_file,
                clips_dir=raw_clips_dir,
                output_dir=out_bank,
                min_k=2,
                max_k=3,
            )

            self.assertEqual(summary["total_dialogue_clips_processed"], 4)
            self.assertEqual(summary["distinct_speakers_discovered"], 2)
            self.assertEqual(len(summary["characters"]), 2)

            for char in summary["characters"]:
                c_wav = Path(char["candidate_acapella_wav"])
                c_json = c_wav.with_suffix(".json")
                self.assertTrue(c_wav.is_file())
                self.assertTrue(c_json.is_file())
                self.assertIn(char["gender"], ("male", "female"))
                self.assertTrue(8.0 <= char["duration_sec"] <= 10.5)


if __name__ == "__main__":
    unittest.main()
