"""Phases 29, 30 & 31 Unit & Integration Tests: Long-Form Stress & Movie-Scale Validation."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from backend.longform_stress_runner import run_longform_phase_validation


REPO_ROOT = Path(__file__).resolve().parent.parent


class Phase29To31StressValidationTests(unittest.TestCase):
    """Tests for Phase 29 (15m), Phase 30 (60m), and Phase 31 (150m) long-form stress validation."""

    def setUp(self) -> None:
        align_path = REPO_ROOT / "alignment_report_phase23.json"
        if not align_path.exists():
            self.skipTest("alignment_report_phase23.json not found")
        from backend.speaker_engine import normalize_phase23_alignment_segments

        self.align = json.loads(align_path.read_text(encoding="utf-8"))
        self.base_segments = normalize_phase23_alignment_segments(self.align)
        self.base_duration = 84.5

    def test_01_phase29_15_minute_multiscene_stress_and_resume(self) -> None:
        """Phase 29 (900s / 15m) stress run reconciles chunks, resumes cleanly, and passes 4-tier QA."""
        res = run_longform_phase_validation(
            phase=29,
            phase_label="Phase 29 — 15-Minute Multi-Scene Stress Test",
            base_segments=self.base_segments,
            base_duration_sec=self.base_duration,
            target_duration_sec=900.0,
            target_speaker_count=6,
            chunk_duration_sec=180.0,
            overlap_sec=30.0,
            workspace_path=REPO_ROOT,
        )
        self.assertGreaterEqual(res["total_segments"], 290)
        self.assertEqual(res["scene_voice_collisions"], 0)
        self.assertEqual(res["mid_movie_voice_switches"], 0)
        self.assertEqual(res["checkpoint_resume_proof"]["status"], "PASS")
        self.assertEqual(res["checkpoint_resume_proof"]["duplicate_recomputed_chunks"], 0)
        self.assertIn(res["overall_verdict"], ("PASS", "PASS_WITH_WARNINGS"))

    def test_02_phase30_60_minute_10_character_episode_production_test(self) -> None:
        """Phase 30 (3600s / 60m) episode run locks 10 characters with 0 scene voice collisions."""
        res = run_longform_phase_validation(
            phase=30,
            phase_label="Phase 30 — 60-Minute Multi-Character Episode Production Test",
            base_segments=self.base_segments,
            base_duration_sec=self.base_duration,
            target_duration_sec=3600.0,
            target_speaker_count=10,
            chunk_duration_sec=300.0,
            overlap_sec=30.0,
            workspace_path=REPO_ROOT,
        )
        self.assertEqual(res["character_count"], 10)
        self.assertEqual(res["scene_voice_collisions"], 0)
        self.assertEqual(res["mid_movie_voice_switches"], 0)
        self.assertEqual(res["checkpoint_resume_proof"]["status"], "PASS")
        self.assertEqual(res["resource_stability"]["status"], "PASS")
        self.assertIn(res["overall_verdict"], ("PASS", "PASS_WITH_WARNINGS"))

    def test_03_phase31_150_minute_full_movie_scale_validation(self) -> None:
        """Phase 31 (9000s / 2.5h) movie-scale run validates 12 characters, 5 sample windows, and 0 drift."""
        res = run_longform_phase_validation(
            phase=31,
            phase_label="Phase 31 — 2.5-Hour Full Movie Production Scale Test",
            base_segments=self.base_segments,
            base_duration_sec=self.base_duration,
            target_duration_sec=9000.0,
            target_speaker_count=12,
            chunk_duration_sec=300.0,
            overlap_sec=30.0,
            workspace_path=REPO_ROOT,
        )
        self.assertEqual(res["character_count"], 12)
        self.assertGreaterEqual(res["total_segments"], 2800)
        self.assertEqual(res["qa_summary"]["tier4_cumulative_drift_sec"], 0.0)
        self.assertEqual(res["human_review_sample_pack"]["sample_count"], 5)
        self.assertEqual(res["checkpoint_resume_proof"]["status"], "PASS")
        self.assertIn(res["overall_verdict"], ("PASS", "PASS_WITH_WARNINGS"))


if __name__ == "__main__":
    unittest.main()
