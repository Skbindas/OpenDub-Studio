"""Phase 26 Unit & Real-Media Integration Tests: Character Voice Consistency Engine."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from backend.character_engine import build_character_registry
from backend.voice_consistency import (
    VoiceLockViolationError,
    assign_and_lock_character_voices,
    compute_voice_lock_hash,
    create_voice_lock_entry,
    evaluate_voice_consistency_qa,
    unlock_and_relock_character_voice,
    verify_voice_lock_integrity,
)
from backend.voice_profiles import VoiceProfileError, normalize_voice_profile


REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECT_DIR = REPO_ROOT / "runtime" / "projects" / "53ba81b5-cc7c-4a68-944e-ff553456a917"


class Phase26VoiceConsistencyTests(unittest.TestCase):
    """Tests for Phase 26 voice locking, multi-engine lock guard, and cross-scene consistency."""

    def test_01_voice_lock_schema_and_deterministic_sha256_hash(self) -> None:
        """PRD §14.3 voice lock entry produces deterministic SHA-256 configuration_hash."""
        entry1 = create_voice_lock_entry(
            character_id="CHAR_001",
            voice_engine="edge-tts",
            voice_id="hi-IN-MadhurNeural",
            base_rate="+0%",
            base_pitch="+0Hz",
            base_volume="+0%",
            locked=True,
            locked_at_phase=26,
        )
        entry2 = create_voice_lock_entry(
            character_id="CHAR_001",
            voice_engine="edge-tts",
            voice_id="hi-IN-MadhurNeural",
        )
        self.assertEqual(entry1["configuration_hash"], entry2["configuration_hash"])
        self.assertEqual(len(entry1["configuration_hash"]), 64)

    def test_02_multi_engine_and_voice_switch_lock_guard_rejects_drift(self) -> None:
        """Once locked to edge-tts + hi-IN-MadhurNeural, fallback to piper or another voice raises VoiceLockViolationError."""
        lock_map = {
            "CHAR_001": create_voice_lock_entry(
                character_id="CHAR_001",
                voice_engine="edge-tts",
                voice_id="hi-IN-MadhurNeural",
            )
        }
        # Valid request passes
        res = verify_voice_lock_integrity(
            character_id="CHAR_001",
            requested_engine="edge-tts",
            requested_voice_id="hi-IN-MadhurNeural",
            voice_lock_map=lock_map,
        )
        self.assertTrue(res["verified"])

        # Mid-character engine fallback to piper MUST be rejected
        with self.assertRaises(VoiceLockViolationError):
            verify_voice_lock_integrity(
                character_id="CHAR_001",
                requested_engine="piper",
                requested_voice_id="hi-IN-MadhurNeural",
                voice_lock_map=lock_map,
            )

        # Mid-character voice switch MUST be rejected
        with self.assertRaises(VoiceLockViolationError):
            verify_voice_lock_integrity(
                character_id="CHAR_001",
                requested_engine="edge-tts",
                requested_voice_id="hi-IN-SwaraNeural",
                voice_lock_map=lock_map,
            )

    def test_03_explicit_unlock_and_relock_updates_hash_with_audit_trail(self) -> None:
        """Explicit user unlock & relock updates configuration_hash and records previous_configuration_hash."""
        lock_map = {
            "CHAR_001": create_voice_lock_entry(
                character_id="CHAR_001",
                voice_engine="edge-tts",
                voice_id="hi-IN-MadhurNeural",
            )
        }
        old_hash = lock_map["CHAR_001"]["configuration_hash"]
        updated = unlock_and_relock_character_voice(
            character_id="CHAR_001",
            voice_lock_map=lock_map,
            new_voice_engine="edge-tts",
            new_voice_id="hi-IN-SwaraNeural",
            reason="director_recast",
        )
        self.assertEqual(updated["previous_configuration_hash"], old_hash)
        self.assertNotEqual(updated["configuration_hash"], old_hash)
        self.assertEqual(updated["configuration_hash"], compute_voice_lock_hash(updated))

    def test_04_scene_level_voice_collision_prevention_for_10_speakers(self) -> None:
        """10 characters sharing scenes receive distinct voice+register signatures with 0 scene collisions."""
        characters = [
            {
                "character_id": f"CHAR_{i:03d}",
                "role_classification": "primary" if i <= 2 else ("secondary" if i <= 5 else "minor"),
                "segment_count": 20 - i,
                "pitch_baseline_hz": 130.0 + (i % 2) * 85.0,
            }
            for i in range(1, 11)
        ]
        scenes = [
            {
                "scene_id": "SCENE_001",
                "characters_present": ["CHAR_001", "CHAR_002", "CHAR_003", "CHAR_004"],
            },
            {
                "scene_id": "SCENE_002",
                "characters_present": ["CHAR_001", "CHAR_005", "CHAR_006", "CHAR_007"],
            },
            {
                "scene_id": "SCENE_003",
                "characters_present": ["CHAR_002", "CHAR_008", "CHAR_009", "CHAR_010"],
            },
        ]
        assignment = assign_and_lock_character_voices(characters, scenes=scenes)
        self.assertEqual(assignment["locked_character_count"], 10)
        self.assertEqual(assignment["scene_voice_collision_count"], 0)

    def test_05_voice_profile_rejects_embedded_secrets_and_allows_edge_tts(self) -> None:
        """normalize_voice_profile supports edge-tts and strictly rejects API keys/tokens."""
        vp = normalize_voice_profile({"provider": "edge-tts", "voice_id": "hi-IN-MadhurNeural"})
        self.assertEqual(vp["status"], "configured")
        with self.assertRaises(VoiceProfileError):
            normalize_voice_profile({"provider": "edge-tts", "api_key": "sk-secret123"})

    def test_06_real_project_phase26_voice_consistency_audit(self) -> None:
        """Verify 0 mid-movie voice switches and cross-scene acoustic stability on project 53ba81b5."""
        align_path = REPO_ROOT / "alignment_report_phase23.json"
        segments_dir = PROJECT_DIR / "segments"
        if not align_path.exists():
            self.skipTest("Phase 23 alignment report not present.")

        from backend.speaker_engine import normalize_phase23_alignment_segments

        align = normalize_phase23_alignment_segments(json.loads(align_path.read_text(encoding="utf-8")))
        registry = build_character_registry(align)
        locks = assign_and_lock_character_voices(registry["characters"], scenes=registry["scenes"])
        qa = evaluate_voice_consistency_qa(
            segments=registry["segments"],
            voice_lock_map=locks["voice_lock_map"],
            scenes=registry["scenes"],
            segments_dir=segments_dir,
        )
        self.assertEqual(qa["mid_movie_voice_switches"], 0)
        self.assertEqual(qa["overall_status"], "PASS")


if __name__ == "__main__":
    unittest.main()
