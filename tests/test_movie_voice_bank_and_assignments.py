"""Unit tests for OpenDub Studio Movie Cast Voice Bank & Adaptive Assignment."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
import wave
import tempfile
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.voice_cloning import get_movie_cast_voice_bank, assign_movie_cast_voices


class MovieVoiceBankTests(unittest.TestCase):
    def setUp(self):
        # Metadata-only algorithm fixtures; never read the private film bank.
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        root = Path(self.workspace.name)
        folder = root / 'storage/default_voice_bank/candidate_voices'
        folder.mkdir(parents=True)
        rows = []
        for index in range(1, 43):
            rows.append({'character_id': f'char_{index:02d}_fixture',
                         'character_name': f'Test voice {index}',
                         'gender': 'female' if index % 2 else 'male',
                         'age_group': 'elderly' if index % 4 < 2 else 'adult',
                         'hindi_dialogue_text': 'यह परीक्षण है।'})
        rows[-1].update(character_id='char_42_police_inspector_officer',
                        character_name='फील्ड पुलिस अधिकारी')
        (folder / 'all_extracted_characters_summary.json').write_text(
            json.dumps({'characters': rows}), encoding='utf8')
        context = patch('backend.voice_cloning.__file__', str(root / 'backend/voice_cloning.py'))
        context.start()
        self.addCleanup(context.stop)

    def test_movie_cast_voice_bank_size_and_purity(self):
        bank = get_movie_cast_voice_bank()
        self.assertEqual(len(bank), 42, f"Expected 42 movie characters, got {len(bank)}")

        # Verify all 42 reference entries have valid character_id, gender, name, and valid audio if present
        for char in bank:
            cid = char["character_id"]
            self.assertTrue(cid.startswith("char_"), f"Invalid ID format: {cid}")
            self.assertIn(char["gender"], ("male", "female"))
            self.assertTrue(len(char["character_name"]) > 0)
            self.assertTrue(len(char["hindi_dialogue_text"]) > 0)

            self.assertFalse(char['sample_available'])

    def test_sample_42_police_inspector_officer(self):
        bank = get_movie_cast_voice_bank()
        c42 = next((c for c in bank if c["character_id"] == "char_42_police_inspector_officer"), None)
        self.assertIsNotNone(c42, "Character #42 missing from bank")
        self.assertEqual(c42["gender"], "male")
        self.assertIn("फील्ड पुलिस अधिकारी", c42["character_name"])

        self.assertFalse(c42['sample_available'])

    def test_adaptive_voice_assignment_small_cast(self):
        # Simulate a project with 4 detected characters (2 males, 2 females)
        mock_detected_characters = [
            {"character_id": "c_lead_hero", "display_name": "Hero Anand", "gender": "male", "age_group": "adult", "pitch_f0_hz": 120.0},
            {"character_id": "c_elderly_father", "display_name": "Father Sathyam", "gender": "male", "age_group": "elderly", "pitch_f0_hz": 95.0},
            {"character_id": "c_lead_heroine", "display_name": "Heroine Bujji", "gender": "female", "age_group": "adult", "pitch_f0_hz": 240.0},
            {"character_id": "c_mother", "display_name": "Mother Padma", "gender": "female", "age_group": "elderly", "pitch_f0_hz": 180.0},
        ]

        # Algorithm fixture: actual unreviewed movie references are not defaults.
        fixture = [{**v, "eligible_for_defaults": True} for v in get_movie_cast_voice_bank()]
        with patch("backend.voice_cloning.get_movie_cast_voice_bank", return_value=fixture):
            assigned = assign_movie_cast_voices(mock_detected_characters)
        self.assertEqual(len(assigned), 4)

        assigned_voice_ids = set()
        for char in assigned:
            self.assertIn("assigned_voice", char, f"Character {char['character_id']} missing voice assignment")
            v = char["assigned_voice"]
            self.assertEqual(v["gender"], char["gender"], f"Gender mismatch for {char['character_id']}: expected {char['gender']}, got {v['gender']}")
            assigned_voice_ids.add(v["character_id"])

        # All 4 assigned voices must be distinct
        self.assertEqual(len(assigned_voice_ids), 4, f"Duplicate voice assigned in small cast: {assigned_voice_ids}")

    def test_manual_voice_override_precedence(self):
        mock_detected = [
            {"character_id": "char_speaker_1", "display_name": "Speaker 1", "gender": "male", "age_group": "adult"},
            {"character_id": "char_speaker_2", "display_name": "Speaker 2", "gender": "female", "age_group": "adult"},
        ]

        # User manually mapped Speaker 1 to char_42_police_inspector_officer
        manual = {
            "char_speaker_1": {
                "voice_id": "char_42_police_inspector_officer",
                "rate": 1.05,
                "pitch_semitones": -1.0
            }
        }

        assigned = assign_movie_cast_voices(mock_detected, manual_overrides=manual)
        spk1 = next(c for c in assigned if c["character_id"] == "char_speaker_1")
        self.assertEqual(spk1["assigned_voice"]["character_id"], "char_42_police_inspector_officer")
        self.assertEqual(spk1["assigned_voice"]["applied_rate"], 1.05)
        self.assertEqual(spk1["assigned_voice"]["applied_pitch_semitones"], -1.0)


if __name__ == "__main__":
    unittest.main()
