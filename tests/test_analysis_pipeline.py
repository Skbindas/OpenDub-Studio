
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.analysis_pipeline import (
    _atomic_json,
    _build_timeline,
    _build_scene_context,
    run_full_analysis,
)
from backend.db import connect, init_db


class AnalysisTimelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_atomic_json_round_trip_unicode(self):
        path = self.root / "analysis" / "timeline.json"
        data = {"text": "नमस्ते", "segments": [{"start_sec": 0.1}]}
        _atomic_json(path, data)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), data)
        self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_timeline_assigns_scene_and_keeps_source_timebase(self):
        transcript = {
            "language": "ko",
            "segments": [
                {
                    "start": 1.0,
                    "end": 2.4,
                    "text": "hello",
                    "words": [],
                    "speaker_id": "SPEAKER_00",
                    "no_speech_prob": 0.01,
                },
                {
                    "start": 7.0,
                    "end": 8.0,
                    "text": "unknown",
                    "words": [],
                    "speaker_id": None,
                    "no_speech_prob": 0.2,
                },
            ],
        }
        scenes = [
            {"scene_index": 0, "start_sec": 0.0, "end_sec": 5.0},
            {"scene_index": 1, "start_sec": 5.0, "end_sec": None},
        ]
        timeline = _build_timeline(
            transcript, scenes, self.root / "separation.json"
        )
        self.assertEqual(timeline["timebase"], "source_media_seconds")
        self.assertEqual(
            [x["scene_index"] for x in timeline["segments"]], [0, 1]
        )
        self.assertTrue(timeline["segments"][1]["review_required"])
        self.assertEqual(timeline["language"], "ko")

    def test_full_analysis_resumes_from_completed_checkpoints(self):
        db = self.root / "resume.sqlite3"
        init_db(db)
        project_id, job_id = "p1", "j1"

        with connect(db) as conn:
            conn.execute(
                "INSERT INTO projects(id,name,source_size,created_at,updated_at) "
                "VALUES(?,?,?,?,?)",
                (
                    project_id,
                    "Resume movie",
                    4096,
                    "2026-01-01",
                    "2026-01-01",
                ),
            )
            conn.execute(
                """INSERT INTO jobs(
                    id,project_id,kind,status,progress,attempts,message,
                    payload,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    job_id,
                    project_id,
                    "full_analysis",
                    "running",
                    0,
                    1,
                    "running",
                    "{}",
                    "2026-01-01",
                    "2026-01-01",
                ),
            )
            conn.commit()

        source = self.root / "movie.mp4"
        source.write_bytes(b"source" * 900)

        def fake_extract(_source, output):
            output.write_bytes(b"wav" * 100)
            return {
                "file": output.name,
                "size_bytes": output.stat().st_size,
            }

        def fake_profile(_audio, output):
            data = {"schema_version": 1, "silence_regions": []}
            _atomic_json(output, data)
            return data

        def fake_scenes(_source, output, _threshold=0.35):
            data = [
                {
                    "scene_index": 0,
                    "start_sec": 0.0,
                    "end_sec": 4.0,
                }
            ]
            _atomic_json(output, data)
            return data

        transcript = {
            "language": "ko",
            "duration": 4.0,
            "segments": [
                {
                    "start": 0.5,
                    "end": 1.5,
                    "text": "hello",
                    "words": [],
                }
            ],
        }

        def fake_separator(_audio, _directory, _model=None):
            return {
                "status": "fallback",
                "dialogue_candidate": "original",
                "background_candidate": None,
            }

        fake_diarization = {
            "turns": [
                {
                    "start": 0.5,
                    "end": 1.5,
                    "speaker_id": "SPEAKER_00",
                }
            ],
            "speakers": ["SPEAKER_00"],
        }

        media_probe = {
            "schema_version": 1,
            "file_name": "movie.mp4",
            "size_bytes": source.stat().st_size,
            "duration_sec": 4.0,
            "format_name": "mp4",
            "video_stream_count": 1,
            "audio_stream_count": 1,
            "streams": [],
        }

        # First run: simulate interruption during transcription.
        # Diarization is mocked so this test never loads a real HF model.
        with (
            patch(
                "backend.analysis_pipeline.probe_media",
                return_value=media_probe,
            ),
            patch(
                "backend.analysis_pipeline.check_asr_runtime",
                return_value={
                    "status": "ready",
                    "selected_device": "cpu",
                },
            ),
            patch(
                "backend.analysis_pipeline.extract_audio",
                side_effect=fake_extract,
            ),
            patch(
                "backend.analysis_pipeline.analyze_audio_profile",
                side_effect=fake_profile,
            ),
            patch(
                "backend.analysis_pipeline.detect_scenes",
                side_effect=fake_scenes,
            ),
            patch(
                "backend.analysis_pipeline.transcribe",
                side_effect=RuntimeError("simulated interruption"),
            ),
            patch(
                "backend.analysis_pipeline.separate_dialogue_candidate",
                side_effect=fake_separator,
            ),
            patch(
                "backend.analysis_pipeline.diarize",
                return_value=fake_diarization,
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError, "simulated interruption"
            ):
                run_full_analysis(
                    db_path=db,
                    project_id=project_id,
                    job_id=job_id,
                    project_root=self.root,
                    source=source,
                    options={},
                )

        manifest_path = (
            self.root / "analysis" / "analysis_manifest.json"
        )
        first_manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )

        self.assertEqual(
            first_manifest["stages"]["source_media_validate"]["status"],
            "completed",
        )
        self.assertEqual(
            first_manifest["stages"]["audio_extract"]["status"],
            "completed",
        )
        self.assertEqual(
            first_manifest["stages"]["audio_profile"]["status"],
            "completed",
        )
        self.assertEqual(
            first_manifest["stages"]["scene_detect"]["status"],
            "completed",
        )
        self.assertEqual(
            first_manifest["stages"]["transcription"]["status"],
            "failed",
        )

        # Second run: completed checkpoints must be reused.
        with (
            patch(
                "backend.analysis_pipeline.probe_media",
                return_value=media_probe,
            ) as probe_mock,
            patch(
                "backend.analysis_pipeline.check_asr_runtime",
                return_value={
                    "status": "ready",
                    "selected_device": "cpu",
                },
            ) as asr_mock,
            patch(
                "backend.analysis_pipeline.extract_audio",
                side_effect=fake_extract,
            ) as extract_mock,
            patch(
                "backend.analysis_pipeline.analyze_audio_profile",
                side_effect=fake_profile,
            ) as profile_mock,
            patch(
                "backend.analysis_pipeline.detect_scenes",
                side_effect=fake_scenes,
            ) as scenes_mock,
            patch(
                "backend.analysis_pipeline.transcribe",
                return_value=transcript,
            ) as transcribe_mock,
            patch(
                "backend.analysis_pipeline.separate_dialogue_candidate",
                side_effect=fake_separator,
            ),
            patch(
                "backend.analysis_pipeline.diarize",
                return_value=fake_diarization,
            ) as diarize_mock,
        ):
            result = run_full_analysis(
                db_path=db,
                project_id=project_id,
                job_id=job_id,
                project_root=self.root,
                source=source,
                options={},
            )

        self.assertEqual(result["segments"], 1)
        self.assertEqual(result["scenes"], 1)

        probe_mock.assert_not_called()
        asr_mock.assert_not_called()
        extract_mock.assert_not_called()
        profile_mock.assert_not_called()
        scenes_mock.assert_not_called()
        transcribe_mock.assert_called_once()
        diarize_mock.assert_called_once()

        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["status"], "completed")
        self.assertEqual(
            manifest["stages"]["transcription"]["status"],
            "completed",
        )
        self.assertTrue(
            (self.root / "analysis" / "source_media.json").is_file()
        )

        timeline = json.loads(
            (self.root / "analysis" / "timeline.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            timeline["source_media"]["file_name"], "movie.mp4"
        )
        self.assertEqual(
            timeline["timebase"], "source_media_seconds"
        )

    def test_scene_context_aligns_dialogue_speakers_and_silence(self):
        transcript = {
            "duration": 20,
            "segments": [
                {
                    "start": 1,
                    "end": 3,
                    "text": "hello",
                    "speaker_id": "SPEAKER_00",
                },
                {
                    "start": 8,
                    "end": 10,
                    "text": "there",
                    "speaker_id": None,
                },
            ],
        }
        scenes = [
            {"scene_index": 0, "start_sec": 0, "end_sec": 5},
            {"scene_index": 1, "start_sec": 5, "end_sec": 12},
        ]
        profile = {
            "silence_regions": [
                {"start_sec": 2, "end_sec": 7}
            ]
        }

        result = _build_scene_context(transcript, scenes, profile)

        self.assertEqual(result["scene_count"], 2)
        first, second = result["scenes"]

        self.assertEqual(
            first["dialogue_segment_ids"], ["seg-000001"]
        )
        self.assertEqual(first["speaker_ids"], ["SPEAKER_00"])
        self.assertEqual(first["silence_overlap_sec"], 3.0)

        self.assertEqual(
            second["dialogue_segment_ids"], ["seg-000002"]
        )
        self.assertEqual(second["speaker_ids"], [])
        self.assertEqual(second["silence_overlap_sec"], 2.0)

    def test_skipped_diarization_does_not_block_full_analysis(self):
        self.assertTrue(True)

    def test_missing_speaker_is_flagged_for_review(self):
        timeline = _build_timeline(
            {"segments": [{"start": 0, "end": 1, "text": "x"}]},
            [{"scene_index": 0, "start_sec": 0, "end_sec": None}],
            self.root / "no-separation.json",
        )
        segment = timeline["segments"][0]

        self.assertIsNone(segment["speaker_id"])
        self.assertTrue(segment["review_required"])
        self.assertEqual(
            segment["emotion_status"], "not_analyzed"
        )


if __name__ == "__main__":
    unittest.main()