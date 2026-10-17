from __future__ import annotations

import unittest

from backend.diarization import assign_speakers


class SpeakerAssignmentTests(unittest.TestCase):
    def test_assigns_clear_overlap_with_confidence(self):
        transcript = {"segments": [{"start": 1.0, "end": 3.0, "text": "hello"}]}
        diarization = {"turns": [
            {"start": 0.5, "end": 2.8, "speaker_id": "SPEAKER_00"},
            {"start": 4.0, "end": 5.0, "speaker_id": "SPEAKER_01"},
        ]}
        result = assign_speakers(transcript, diarization)
        row = result["segments"][0]
        self.assertEqual(row["speaker_id"], "SPEAKER_00")
        self.assertEqual(row["speaker_review_required"], False)
        self.assertGreaterEqual(row["speaker_confidence"], 0.8)
        self.assertIsNone(row["speaker_review_reason"])
        self.assertEqual(row["speaker_candidates"][0]["speaker_id"], "SPEAKER_00")

    def test_flags_ambiguous_and_low_overlap_assignments(self):
        transcript = {"segments": [
            {"start": 1.0, "end": 5.0, "text": "ambiguous"},
            {"start": 10.0, "end": 14.0, "text": "weak"},
        ]}
        diarization = {"turns": [
            {"start": 1.0, "end": 2.9, "speaker_id": "A"},
            {"start": 2.9, "end": 4.9, "speaker_id": "B"},
            {"start": 10.0, "end": 10.5, "speaker_id": "C"},
        ]}
        result = assign_speakers(transcript, diarization)
        ambiguous, weak = result["segments"]
        self.assertIsNone(ambiguous["speaker_id"])
        self.assertTrue(ambiguous["speaker_review_required"])
        self.assertEqual(ambiguous["speaker_review_reason"], "ambiguous_overlap")
        self.assertIsNone(weak["speaker_id"])
        self.assertEqual(weak["speaker_review_reason"], "low_overlap")


if __name__ == "__main__":
    unittest.main()
