"""Phase 25 Unit & Real-Media Integration Tests: Emotion & Prosody Preservation Engine."""
from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from backend.emotion_prosody import (
    analyze_audio_prosody_features,
    analyze_project_emotion_prosody,
    build_segment_prosody_profile,
    evaluate_prosody_qa,
)
from backend.speaker_engine import normalize_phase23_alignment_segments


REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECT_DIR = REPO_ROOT / "runtime" / "projects" / "53ba81b5-cc7c-4a68-944e-ff553456a917"


class Phase25EmotionProsodyTests(unittest.TestCase):
    """Tests for Phase 25 multimodal emotion/prosody analysis, bounded TTS controls, and QA."""

    def test_01_audio_disambiguates_urgent_shout_vs_whispered_urgency(self) -> None:
        """Identical urgent text with high-energy vs low-energy audio yields distinct emotion profiles."""
        sr = 16000
        loud_samples = [0.45 * math.sin(2.0 * math.pi * (180.0 + 35.0 * math.sin(i / 800.0)) * i / sr) for i in range(sr)]
        quiet_samples = [0.02 * math.sin(2.0 * math.pi * 150.0 * i / sr) for i in range(sr)]

        loud_feats = analyze_audio_prosody_features(loud_samples, sample_rate=sr, duration_sec=1.5)
        quiet_feats = analyze_audio_prosody_features(quiet_samples, sample_rate=sr, duration_sec=1.5)

        seg = {
            "segment_id": 99,
            "character_id": "CHAR_001",
            "source_text": "快走！危险！",
            "adapted_text": "जल्दी चलो! खतरा है!",
            "target_duration": 1.5,
        }
        baseline = {"pitch_baseline_hz": 165.0, "energy_baseline": 0.065, "speaking_rate_baseline": 4.2}

        loud_profile = build_segment_prosody_profile(seg, loud_feats, character_baseline=baseline)
        quiet_profile = build_segment_prosody_profile(seg, quiet_feats, character_baseline=baseline)

        self.assertEqual(loud_profile["primary_emotion"], "urgent_alert")
        self.assertEqual(quiet_profile["primary_emotion"], "whispered_urgent")
        self.assertGreater(loud_profile["intensity"], quiet_profile["intensity"])
        self.assertNotEqual(loud_profile["tts_controls"]["volume"], quiet_profile["tts_controls"]["volume"])

    def test_02_segment_07_matches_prd_section_13_2_schema(self) -> None:
        """Segment 07 ('就这样，相信我。' -> 'बस, भरोसा रख!') produces reassuring_urgent prosody & emphasis."""
        sr = 16000
        samples = [0.12 * math.sin(2.0 * math.pi * (175.0 - 20.0 * (i / sr)) * i / sr) for i in range(int(1.64 * sr))]
        feats = analyze_audio_prosody_features(samples, sample_rate=sr, duration_sec=1.64)
        seg_07 = {
            "segment_id": 7,
            "character_id": "CHAR_001",
            "source_text": "就这样，相信我。",
            "adapted_text": "बस, भरोसा रख!",
            "target_duration": 1.64,
        }
        profile = build_segment_prosody_profile(seg_07, feats)

        self.assertEqual(profile["segment_id"], 7)
        self.assertEqual(profile["primary_emotion"], "reassuring_urgent")
        self.assertEqual(profile["secondary_emotion"], "protective")
        self.assertIn("भरोसा", profile["emphasis_tokens"])
        for key in ("rate", "pitch", "volume"):
            self.assertIn(key, profile["tts_controls"])

    def test_03_bounded_tts_controls_never_exceed_safe_limits(self) -> None:
        """TTS rate/pitch/volume adjustments remain strictly within non-cartoon bounds."""
        sr = 16000
        extreme_samples = [0.8 * math.sin(2.0 * math.pi * 350.0 * i / sr) for i in range(sr)]
        feats = analyze_audio_prosody_features(extreme_samples, sample_rate=sr, duration_sec=0.8)
        seg = {
            "segment_id": 1,
            "character_id": "CHAR_001",
            "source_text": "快点！快点！马上过来！",
            "adapted_text": "जल्दी करो! तुरंत यहाँ आओ!",
            "target_duration": 0.8,
        }
        profile = build_segment_prosody_profile(seg, feats)
        rate_val = int(profile["tts_controls"]["rate"].replace("%", ""))
        pitch_val = int(profile["tts_controls"]["pitch"].replace("Hz", ""))
        vol_val = int(profile["tts_controls"]["volume"].replace("%", ""))

        self.assertTrue(-15 <= rate_val <= 15)
        self.assertTrue(-6 <= pitch_val <= 6)
        self.assertTrue(-8 <= vol_val <= 8)

    def test_04_prosody_qa_detects_flat_robotic_delivery(self) -> None:
        """Prosody QA flags flatness_warning when an expressive source has a monotone dubbed output."""
        src_feats = {
            "duration_sec": 2.0,
            "f0_mean_hz": 185.0,
            "f0_range_hz": 62.0,
            "rms_db": -18.0,
            "dynamic_range_db": 14.0,
            "voiced_ratio": 0.65,
            "pause_after_ms": 40,
        }
        monotone_dub_feats = {
            "duration_sec": 2.0,
            "f0_mean_hz": 150.0,
            "f0_range_hz": 3.0,
            "rms_db": -19.0,
            "dynamic_range_db": 1.8,
            "voiced_ratio": 0.70,
            "pause_after_ms": 40,
        }
        qa = evaluate_prosody_qa(
            source_features=src_feats,
            dubbed_features=monotone_dub_feats,
            prosody_profile={"segment_id": 5, "character_id": "CHAR_001", "pause_after_ms": 40},
            target_duration_sec=2.0,
        )
        self.assertTrue(qa["flatness_warning"])
        self.assertEqual(qa["status"], "WARNING")

    def test_05_real_project_phase25_emotion_prosody_evaluation(self) -> None:
        """Run Phase 25 emotion/prosody analysis across all 28 real project segments."""
        audio_path = PROJECT_DIR / "analysis" / "audio_mono_16k.wav"
        segments_dir = PROJECT_DIR / "segments"
        align_path = REPO_ROOT / "alignment_report_phase23.json"
        if not audio_path.exists() or not align_path.exists():
            self.skipTest("Real project audio or Phase 23 alignment report not present.")

        align = normalize_phase23_alignment_segments(json.loads(align_path.read_text(encoding="utf-8")))
        report = analyze_project_emotion_prosody(
            source_audio_path=audio_path,
            segments=align,
            segments_dir=segments_dir,
        )
        self.assertEqual(report["segment_count"], 28)
        self.assertEqual(len(report["prosody_qa"]), 28)
        self.assertGreaterEqual(len(report["emotion_distribution"]), 3)


if __name__ == "__main__":
    unittest.main()
