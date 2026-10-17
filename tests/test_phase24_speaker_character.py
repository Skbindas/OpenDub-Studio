"""Phase 24 Unit & Real-Media Integration Tests: Speaker & Character Engine."""
from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from backend.character_engine import (
    build_character_registry,
    classify_character_role,
    detect_scene_boundaries,
)
from backend.speaker_engine import (
    analyze_project_speakers,
    classify_overlap_and_interruptions,
    extract_speaker_acoustic_features,
    normalize_phase23_alignment_segments,
    reconcile_chunk_speakers,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECT_DIR = REPO_ROOT / "runtime" / "projects" / "53ba81b5-cc7c-4a68-944e-ff553456a917"


class Phase24SpeakerCharacterTests(unittest.TestCase):
    """Tests for Phase 24 global speaker reconciliation, character separation, and overlaps."""

    def test_01_acoustic_feature_extraction_distinguishes_registers(self) -> None:
        """Acoustic feature extractor measures distinct F0 and embeddings for low vs high voice."""
        sr = 16000
        low_samples = [0.4 * math.sin(2.0 * math.pi * 115.0 * i / sr) for i in range(sr)]
        high_samples = [0.4 * math.sin(2.0 * math.pi * 235.0 * i / sr) for i in range(sr)]

        low_feats = extract_speaker_acoustic_features(low_samples, sample_rate=sr)
        high_feats = extract_speaker_acoustic_features(high_samples, sample_rate=sr)

        self.assertGreater(low_feats["voiced_ratio"], 0.7)
        self.assertGreater(high_feats["voiced_ratio"], 0.7)
        self.assertTrue(100.0 <= low_feats["f0_mean_hz"] <= 130.0)
        self.assertTrue(215.0 <= high_feats["f0_mean_hz"] <= 255.0)
        self.assertEqual(len(low_feats["embedding"]), 16)

    def test_02_cross_chunk_speaker_reconciliation_prevents_id_reset(self) -> None:
        """Chunk-local SPEAKER_00/SPEAKER_01 swapped in chunk 2 reconcile to stable global IDs."""
        emb_male = [0.45, 0.45, 0.1, 0.4, 0.5, 0.1, 0.9, 0.3, 0.1, 0.2, 0.1, 0.2, 0.1, 0.2, 0.1, 0.1]
        emb_female = [0.85, 0.85, 0.2, 0.8, 0.9, 0.1, 0.9, 0.3, 0.1, 0.4, 0.1, 0.5, 0.1, 0.5, 0.1, 0.4]

        chunks = [
            {
                "chunk_id": "chunk_000",
                "chunk_start": 0.0,
                "chunk_end": 300.0,
                "overlap_with_previous_start": 0.0,
                "overlap_with_previous_end": 0.0,
                "speakers": [
                    {"speaker_id": "LOCAL_A", "f0_mean_hz": 125.0, "embedding": emb_male},
                    {"speaker_id": "LOCAL_B", "f0_mean_hz": 225.0, "embedding": emb_female},
                ],
                "turns": [
                    {"start": 10.0, "end": 25.0, "speaker_id": "LOCAL_A", "f0_mean_hz": 125.0, "embedding": emb_male},
                    {"start": 275.0, "end": 290.0, "speaker_id": "LOCAL_B", "f0_mean_hz": 225.0, "embedding": emb_female},
                ],
            },
            {
                "chunk_id": "chunk_001",
                "chunk_start": 270.0,
                "chunk_end": 570.0,
                "overlap_with_previous_start": 270.0,
                "overlap_with_previous_end": 300.0,
                # Note swapped local labels in chunk_001!
                "speakers": [
                    {"speaker_id": "SPK_X", "f0_mean_hz": 223.0, "embedding": emb_female},
                    {"speaker_id": "SPK_Y", "f0_mean_hz": 127.0, "embedding": emb_male},
                ],
                "turns": [
                    {"start": 275.0, "end": 290.0, "speaker_id": "SPK_X", "f0_mean_hz": 223.0, "embedding": emb_female},
                    {"start": 320.0, "end": 345.0, "speaker_id": "SPK_Y", "f0_mean_hz": 127.0, "embedding": emb_male},
                ],
            },
        ]

        reconciled = reconcile_chunk_speakers(chunks)
        self.assertEqual(reconciled["global_speaker_count"], 2)
        c0_map = reconciled["chunk_mappings"]["chunk_000"]
        c1_map = reconciled["chunk_mappings"]["chunk_001"]
        self.assertEqual(c0_map["LOCAL_A"], c1_map["SPK_Y"])
        self.assertEqual(c0_map["LOCAL_B"], c1_map["SPK_X"])

    def test_03_overlap_and_interruption_four_categories(self) -> None:
        """Verify all 4 PRD §12.4 overlap categories are accurately classified."""
        turns = [
            # Accidental overlap (< 0.15s boundary bleed)
            {"segment_id": 1, "start": 0.0, "end": 2.05, "speaker_id": "SPEAKER_00", "rms_mean": 0.08},
            {"segment_id": 2, "start": 2.00, "end": 4.00, "speaker_id": "SPEAKER_01", "rms_mean": 0.08},
            # Background speech (short backchannel nested inside dominant turn)
            {"segment_id": 3, "start": 10.0, "end": 16.0, "speaker_id": "SPEAKER_00", "rms_mean": 0.09},
            {"segment_id": 4, "start": 12.0, "end": 12.8, "speaker_id": "SPEAKER_01", "rms_mean": 0.04},
            # Interruption (starts near tail of turn 5 and takes over floor)
            {"segment_id": 5, "start": 20.0, "end": 23.0, "speaker_id": "SPEAKER_00", "rms_mean": 0.08},
            {"segment_id": 6, "start": 22.6, "end": 25.5, "speaker_id": "SPEAKER_01", "rms_mean": 0.09},
            # True overlap (sustained simultaneous dialogue)
            {"segment_id": 7, "start": 30.0, "end": 34.0, "speaker_id": "SPEAKER_00", "rms_mean": 0.09},
            {"segment_id": 8, "start": 30.5, "end": 34.2, "speaker_id": "SPEAKER_01", "rms_mean": 0.09},
        ]
        res = classify_overlap_and_interruptions(turns)
        self.assertEqual(res["total_overlap_events"], 4)
        self.assertEqual(res["category_counts"]["accidental_overlap"], 1)
        self.assertEqual(res["category_counts"]["background_speech"], 1)
        self.assertEqual(res["category_counts"]["interruption"], 1)
        self.assertEqual(res["category_counts"]["true_overlap"], 1)

    def test_04_speaker_vs_character_identity_separation_and_roles(self) -> None:
        """Multiple speaker clusters (e.g. normal + phone filter) can map to one Character ID."""
        segments = [
            {"segment_id": i, "start": i * 3.0, "end": i * 3.0 + 2.0, "speaker_id": "SPEAKER_00", "speaker_confidence": 0.94}
            for i in range(1, 8)
        ] + [
            # Phone-filtered cluster of the same narrative character CHAR_001
            {"segment_id": 8, "start": 25.0, "end": 27.0, "speaker_id": "SPEAKER_03", "speaker_confidence": 0.88},
            # Secondary character
            {"segment_id": 9, "start": 30.0, "end": 32.5, "speaker_id": "SPEAKER_01", "speaker_confidence": 0.91},
            {"segment_id": 10, "start": 33.0, "end": 35.5, "speaker_id": "SPEAKER_01", "speaker_confidence": 0.90},
            {"segment_id": 11, "start": 36.0, "end": 38.5, "speaker_id": "SPEAKER_01", "speaker_confidence": 0.92},
            # Background character with low confidence requiring human review
            {"segment_id": 12, "start": 50.0, "end": 51.0, "speaker_id": "SPEAKER_02", "speaker_confidence": 0.52},
        ]
        registry = build_character_registry(
            segments,
            speaker_to_character_overrides={"SPEAKER_00": "CHAR_001", "SPEAKER_03": "CHAR_001"},
        )
        chars_by_id = {c["character_id"]: c for c in registry["characters"]}
        self.assertIn("CHAR_001", chars_by_id)
        self.assertEqual(chars_by_id["CHAR_001"]["speaker_ids"], ["SPEAKER_00", "SPEAKER_03"])
        self.assertEqual(chars_by_id["CHAR_001"]["role_classification"], "primary")
        self.assertEqual(chars_by_id["CHAR_002"]["role_classification"], "secondary")
        self.assertEqual(chars_by_id["CHAR_003"]["role_classification"], "background")
        self.assertTrue(chars_by_id["CHAR_003"]["human_review_required"])

    def test_05_real_project_phase24_speaker_and_character_pipeline(self) -> None:
        """Verify Phase 24 against real project 53ba81b5-cc7c-4a68-944e-ff553456a917 audio & segments."""
        audio_path = PROJECT_DIR / "analysis" / "audio_mono_16k.wav"
        align_path = REPO_ROOT / "alignment_report_phase23.json"
        if not audio_path.exists() or not align_path.exists():
            self.skipTest("Real project audio or Phase 23 alignment report not present.")

        align = normalize_phase23_alignment_segments(json.loads(align_path.read_text(encoding="utf-8")))
        speaker_report = analyze_project_speakers(audio_path, align, chunk_duration_sec=45.0, overlap_sec=15.0)
        registry = build_character_registry(speaker_report["segments"], speaker_report["reconciliation"])

        self.assertEqual(len(registry["segments"]), 28)
        self.assertEqual(registry["character_count"], 3)
        for ch in registry["characters"]:
            self.assertGreater(ch["pitch_baseline_hz"], 80.0)
            self.assertIn(ch["role_classification"], ("primary", "secondary", "minor", "background"))


if __name__ == "__main__":
    unittest.main()
