"""Phase 28 Unit & Real-Media Integration Tests: Multi-Tier QA Engine."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from backend.character_engine import build_character_registry
from backend.emotion_prosody import analyze_project_emotion_prosody
from backend.qa_engine import (
    evaluate_tier1_segment_qa,
    evaluate_tier2_scene_qa,
    evaluate_tier3_character_qa,
    evaluate_tier4_movie_qa,
    generate_human_review_sample_pack,
)
from backend.voice_consistency import (
    assign_and_lock_character_voices,
    evaluate_voice_consistency_qa,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECT_DIR = REPO_ROOT / "runtime" / "projects" / "53ba81b5-cc7c-4a68-944e-ff553456a917"


class Phase28MultiLevelQATests(unittest.TestCase):
    """Tests for Phase 28 Tier 1-4 QA gates, CJK leakage detection, and human review sampling."""

    def test_01_tier1_detects_cjk_leakage_and_preserves_not_verifiable_lipsync(self) -> None:
        """Tier 1 QA fails on CJK character leakage and preserves NOT_VERIFIABLE lip-sync count."""
        segments = [
            {
                "segment_id": 1,
                "character_id": "CHAR_001",
                "target_duration": 2.0,
                "actual_fitted_duration": 2.0,
                "applied_tempo": 1.05,
                "adapted_text": "बस, भरोसा रख!",
                "speech_truncated": False,
                "atrim_used": False,
            },
            {
                "segment_id": 2,
                "character_id": "CHAR_001",
                "target_duration": 2.0,
                "actual_fitted_duration": 2.0,
                "applied_tempo": 1.02,
                "adapted_text": "यह एक लीक है 相信我",  # Untranslated Chinese characters!
                "speech_truncated": False,
                "atrim_used": False,
            },
        ]
        lipsync_lookup = {
            1: {"status": "NOT_VERIFIABLE"},
            2: {"status": "PASS"},
        }
        t1 = evaluate_tier1_segment_qa(segments, lipsync_Lookup=lipsync_lookup)
        self.assertEqual(t1["not_verifiable_lipsync_count"], 1)
        self.assertEqual(t1["original_language_leakage_count"], 1)
        self.assertEqual(t1["fail_count"], 1)
        self.assertEqual(t1["status"], "FAIL")

    def test_02_tier2_scene_qa_detects_overlap_collisions_and_drift(self) -> None:
        """Tier 2 Scene QA flags timeline overlap collisions or drift > 0.05s."""
        scenes = [
            {
                "scene_id": "SCENE_001",
                "start": 0.0,
                "end": 5.0,
                "segment_ids": [1, 2],
                "characters_present": ["CHAR_001", "CHAR_002"],
            }
        ]
        # Segment 1 bleeds 0.25s past Segment 2's start
        bad_segments = [
            {"segment_id": 1, "character_id": "CHAR_001", "start": 0.0, "end": 2.0, "target_duration": 2.0, "actual_fitted_duration": 2.35},
            {"segment_id": 2, "character_id": "CHAR_002", "start": 2.1, "end": 5.0, "target_duration": 2.9, "actual_fitted_duration": 2.9},
        ]
        t2 = evaluate_tier2_scene_qa(scenes, bad_segments)
        self.assertEqual(t2["total_scene_overlap_collisions"], 1)
        self.assertEqual(t2["status"], "FAIL")

    def test_03_human_review_sample_pack_generates_five_mandatory_categories(self) -> None:
        """generate_human_review_sample_pack returns all 5 PRD §18.5 review clip categories."""
        scenes = [
            {"scene_id": "SCENE_001", "start": 0.0, "end": 30.0, "duration_sec": 30.0, "segment_count": 8, "segment_ids": [1, 2], "characters_present": ["CHAR_001", "CHAR_002"]},
            {"scene_id": "SCENE_002", "start": 32.0, "end": 84.5, "duration_sec": 52.5, "segment_count": 20, "segment_ids": [3, 4], "characters_present": ["CHAR_001", "CHAR_002", "CHAR_003"]},
        ]
        pack = generate_human_review_sample_pack(84.5, scenes, [])
        self.assertEqual(pack["sample_count"], 5)
        categories = [s["category"] for s in pack["samples"]]
        self.assertEqual(
            categories,
            [
                "first_2_minutes",
                "middle_rapid_dialogue_scene",
                "high_emotion_scene",
                "multi_character_overlap_scene",
                "final_2_minutes",
            ],
        )

    def test_04_real_project_four_tier_qa_evaluation(self) -> None:
        """Run full Tier 1-4 QA across real project 53ba81b5-cc7c-4a68-944e-ff553456a917."""
        align_path = REPO_ROOT / "alignment_report_phase23.json"
        ls_path = REPO_ROOT / "lipsync_report_phase23.json"
        audio_path = PROJECT_DIR / "analysis" / "audio_mono_16k.wav"
        segments_dir = PROJECT_DIR / "segments"
        if not align_path.exists() or not ls_path.exists():
            self.skipTest("Phase 23 reports not present.")

        from backend.speaker_engine import normalize_phase23_alignment_segments

        align = normalize_phase23_alignment_segments(json.loads(align_path.read_text(encoding="utf-8")))
        ls_data = json.loads(ls_path.read_text(encoding="utf-8"))
        ls_lookup = {
            int(s.get("segment_id", s.get("segment_index", idx))): s
            for idx, s in enumerate(ls_data.get("segments", []))
        }

        registry = build_character_registry(align)
        locks = assign_and_lock_character_voices(registry["characters"], scenes=registry["scenes"])
        voice_qa = evaluate_voice_consistency_qa(
            registry["segments"],
            locks["voice_lock_map"],
            scenes=registry["scenes"],
            segments_dir=segments_dir,
        )
        prosody_report = analyze_project_emotion_prosody(
            audio_path,
            registry["segments"],
            characters=registry["characters"],
            segments_dir=segments_dir,
        )
        prosody_lookup = {int(q["segment_id"]): q for q in prosody_report["prosody_qa"]}

        t1 = evaluate_tier1_segment_qa(
            registry["segments"],
            lipsync_Lookup=ls_lookup,
            prosody_qa_lookup=prosody_lookup,
            voice_lock_map=locks["voice_lock_map"],
        )
        t2 = evaluate_tier2_scene_qa(
            registry["scenes"],
            registry["segments"],
            prosody_profiles=prosody_report["segments"],
            voice_lock_map=locks["voice_lock_map"],
        )
        t3 = evaluate_tier3_character_qa(registry["characters"], voice_qa)
        t4 = evaluate_tier4_movie_qa(
            source_duration_sec=84.50,
            output_duration_sec=84.50,
            tier1_report=t1,
            tier2_report=t2,
            tier3_report=t3,
            integrated_lufs=-16.0,
            true_peak_dbtp=-1.5,
            expected_segment_count=28,
            checkpoint_coverage_ratio=1.0,
        )

        self.assertEqual(t1["fail_count"], 0)
        self.assertEqual(t1["speech_truncation_count"], 0)
        self.assertEqual(t2["total_scene_overlap_collisions"], 0)
        self.assertEqual(t3["total_mid_movie_voice_switches"], 0)
        self.assertIn(t4["status"], ("PASS", "PASS_WITH_WARNINGS"))


if __name__ == "__main__":
    unittest.main()
