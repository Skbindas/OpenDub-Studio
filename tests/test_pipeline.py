from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.pipeline import (
    build_dialogue_manifest,
    get_pipeline_state,
    next_character_display_name,
    normalize_auto_character_display_names,
    stage_definitions,
    update_dialogue_manifest_translation,
    update_timeline_character_identity,
    merge_dialogue_manifest_state,
    validate_translation_manifest,
    evaluate_adaptation_budget,
    validate_adaptation_candidate,
    suggest_dialogue_adaptation,
)


class DialoguePipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "analysis").mkdir(parents=True)
        (self.root / "characters").mkdir()
        (self.root / "output").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_adaptation_validation_checks_identity_tone_intent_and_timing(self):
        result = validate_adaptation_candidate(
            source_text="I never said that.",
            target_text="मैंने यह कभी नहीं कहा।",
            expected_character_id="char-a",
            actual_character_id="char-b",
            requested_tone="serious",
            recorded_tone="comic",
            delivery_intent="denial",
            recorded_delivery_intent="confession",
            source_duration_sec=0.5,
            max_words=2,
        )
        self.assertFalse(result["valid"])
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["checks"]["semantic_equivalence"], "requires_human_review")
        self.assertEqual(result["checks"]["character_identity"], "failed")
        self.assertEqual(result["checks"]["tone_metadata"], "failed")
        self.assertEqual(result["checks"]["delivery_intent_metadata"], "failed")
        self.assertEqual(result["checks"]["timing_budget"], "over_budget")
        self.assertGreaterEqual(len(result["issues"]), 4)

    def test_adaptation_validation_does_not_claim_semantic_equivalence(self):
        result = validate_adaptation_candidate(
            source_text="Hello",
            target_text="नमस्ते",
            expected_character_id="char-a",
            actual_character_id="char-a",
            requested_tone="warm",
            recorded_tone="warm",
            delivery_intent="greeting",
            recorded_delivery_intent="greeting",
            source_duration_sec=3.0,
        )
        self.assertTrue(result["valid"])
        self.assertEqual(result["checks"]["semantic_equivalence"], "requires_human_review")
        self.assertIn("do not prove semantic equivalence", result["warning"])

    def test_dependency_chain_order_is_stable(self):
        stages = stage_definitions()
        self.assertEqual(
            [stage["id"] for stage in stages],
            [
                "analysis", "character_identity", "translation", "voice_assignment",
                "tts", "timing", "loudness", "dialogue_removal",
                "background_preservation", "mix", "render",
            ],
        )

    def test_character_labels_start_at_one_and_skip_existing_numbers(self):
        characters = [
            {"display_name": "Character 1"},
            {"display_name": "Character 3"},
            {"display_name": "Director"},
        ]
        self.assertEqual(next_character_display_name(characters), "Character 2")

    def test_legacy_automatic_speaker_labels_are_migrated(self):
        characters = [
            {"display_name": "Speaker 00", "source_speaker_id": "SPEAKER_00"},
            {"display_name": "Speaker 01", "source_speaker_id": "SPEAKER_01"},
        ]
        changed = normalize_auto_character_display_names(characters)
        self.assertTrue(changed)
        self.assertEqual([row["display_name"] for row in characters], ["Character 1", "Character 2"])
        self.assertTrue(all(row.get("auto_display_name") for row in characters))

    def test_build_dialogue_manifest_preserves_source_timebase_and_identity(self):
        transcript = {
            "language": "zh",
            "segments": [
                {
                    "start": 1.2,
                    "end": 2.8,
                    "text": "你好",
                    "words": [{"start": 1.2, "end": 1.8, "text": "你好"}],
                    "speaker_id": "SPEAKER_00",
                    "speaker_confidence": 0.94,
                    "speaker_review_required": False,
                }
            ],
        }
        scenes = [{"scene_index": 0, "start_sec": 0.0, "end_sec": 5.0}]
        registry = {
            "speaker_links": {"SPEAKER_00": "char-1"},
            "characters": [{
                "character_id": "char-1",
                "display_name": "Character 1",
                "voice_profile": {"status": "not_configured"},
            }],
        }
        output = self.root / "analysis" / "dialogue_manifest.json"
        result = build_dialogue_manifest(
            project_id="project-1",
            transcript=transcript,
            scenes=scenes,
            registry=registry,
            output_path=output,
            target_language="hi",
        )
        self.assertEqual(result["timebase"], "source_media_seconds")
        self.assertEqual(result["segment_count"], 1)
        unit = result["units"][0]
        self.assertEqual(unit["speaker_id"], "SPEAKER_00")
        self.assertEqual(unit["character_id"], "char-1")
        self.assertEqual(unit["character_name"], "Character 1")
        self.assertEqual(unit["scene_index"], 0)
        self.assertEqual(unit["start_sec"], 1.2)
        self.assertEqual(unit["end_sec"], 2.8)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["units"][0]["translation"]["status"], "pending")

    def test_character_identity_refresh_updates_timeline_names(self):
        timeline = self.root / "analysis" / "timeline.json"
        timeline.write_text(
            json.dumps({"segments": [{"speaker_id": "SPEAKER_00", "text": "x"}]}),
            encoding="utf-8",
        )
        registry = {
            "speaker_links": {"SPEAKER_00": "char-1"},
            "characters": [{"character_id": "char-1", "display_name": "Character 1"}],
        }
        self.assertTrue(update_timeline_character_identity(timeline_path=timeline, registry=registry))
        row = json.loads(timeline.read_text(encoding="utf-8"))["segments"][0]
        self.assertEqual(row["character_id"], "char-1")
        self.assertEqual(row["character_name"], "Character 1")

    def test_translation_writes_back_to_master_dialogue_units(self):
        path = self.root / "analysis" / "dialogue_manifest.json"
        path.write_text(
            json.dumps({"units": [{"segment_index": 0, "translation": {"status": "pending"}}]}),
            encoding="utf-8",
        )
        result = update_dialogue_manifest_translation(
            manifest_path=path,
            translated_result={
                "target_language": "hi",
                "engine": "Argos Translate (local)",
                "segments": [{"segment_index": 0, "translated_text": "नमस्ते", "translation_error": None}],
            },
        )
        self.assertEqual(result["units"][0]["translation"]["status"], "completed")
        self.assertEqual(result["units"][0]["translation"]["text"], "नमस्ते")

    def test_manifest_state_merge_preserves_valid_identity_and_translation_state(self):
        new_manifest = {
            "target_language": "hi",
            "units": [{
                "segment_id": "seg-000001",
                "source_text": "hello",
                "character_id": "char-1",
                "translation": {"status": "pending"},
                "voice": {"status": "pending"},
            }],
        }
        old_manifest = {
            "target_language": "hi",
            "units": [{
                "segment_id": "seg-000001",
                "source_text": "hello",
                "character_id": "char-1",
                "translation": {"status": "completed", "text": "नमस्ते"},
                "voice": {"status": "completed", "model_path": "voice.onnx"},
                "tts": {"status": "completed", "audio_path": "dub.wav"},
            }],
        }
        merged = merge_dialogue_manifest_state(new_manifest, old_manifest)
        self.assertEqual(merged["units"][0]["translation"]["status"], "completed")
        self.assertEqual(merged["units"][0]["translation"]["text"], "नमस्ते")
        self.assertEqual(merged["units"][0]["voice"]["status"], "completed")
        self.assertEqual(merged["units"][0]["tts"]["audio_path"], "dub.wav")

    def test_manifest_state_merge_does_not_keep_state_after_character_remap(self):
        new_manifest = {
            "target_language": "hi",
            "units": [{
                "segment_id": "seg-000001",
                "source_text": "hello",
                "character_id": "char-2",
                "translation": {"status": "pending"},
                "voice": {"status": "pending"},
            }],
        }
        old_manifest = {
            "target_language": "hi",
            "units": [{
                "segment_id": "seg-000001",
                "source_text": "hello",
                "character_id": "char-1",
                "translation": {"status": "completed", "text": "नमस्ते"},
                "voice": {"status": "completed"},
            }],
        }
        merged = merge_dialogue_manifest_state(new_manifest, old_manifest)
        self.assertEqual(merged["units"][0]["translation"]["status"], "completed")
        self.assertEqual(merged["units"][0]["voice"]["status"], "pending")

    def test_manifest_state_merge_invalidates_only_changed_character_audio_artifacts(self):
        old_manifest = {
            "target_language": "hi",
            "units": [
                {
                    "segment_id": "seg-000001",
                    "source_text": "hello from character 1",
                    "character_id": "char-1",
                    "translation": {"status": "completed", "text": "नमस्ते 1"},
                    "voice": {
                        "status": "configured",
                        "character_id": "char-1",
                        "profile": {"provider": "piper", "model_path": "voices/lead_v1.onnx"},
                        "model_path": "voices/lead_v1.onnx",
                    },
                    "tts": {"status": "completed", "audio_path": "lead_v1.wav"},
                    "timing": {"status": "completed", "fit_audio": "lead_v1_fit.wav"},
                    "loudness": {"status": "completed", "normalized_audio": "lead_v1_norm.wav"},
                },
                {
                    "segment_id": "seg-000002",
                    "source_text": "hello from character 2",
                    "character_id": "char-2",
                    "translation": {"status": "completed", "text": "नमस्ते 2"},
                    "voice": {
                        "status": "configured",
                        "character_id": "char-2",
                        "profile": {"provider": "piper", "model_path": "voices/support.onnx"},
                        "model_path": "voices/support.onnx",
                    },
                    "tts": {"status": "completed", "audio_path": "support.wav"},
                    "timing": {"status": "completed", "fit_audio": "support_fit.wav"},
                    "loudness": {"status": "completed", "normalized_audio": "support_norm.wav"},
                },
            ],
        }

        # Character 1's voice is changed to lead_v2; Character 2's voice remains unchanged
        new_manifest = {
            "target_language": "hi",
            "units": [
                {
                    "segment_id": "seg-000001",
                    "source_text": "hello from character 1",
                    "character_id": "char-1",
                    "translation": {"status": "pending"},
                    "voice": {
                        "status": "configured",
                        "character_id": "char-1",
                        "profile": {"provider": "piper", "model_path": "voices/lead_v2.onnx"},
                        "model_path": "voices/lead_v2.onnx",
                    },
                    "tts": {"status": "pending", "audio_path": None},
                    "timing": {"status": "pending", "fit_audio": None},
                    "loudness": {"status": "pending", "normalized_audio": None},
                },
                {
                    "segment_id": "seg-000002",
                    "source_text": "hello from character 2",
                    "character_id": "char-2",
                    "translation": {"status": "pending"},
                    "voice": {
                        "status": "configured",
                        "character_id": "char-2",
                        "profile": {"provider": "piper", "model_path": "voices/support.onnx"},
                        "model_path": "voices/support.onnx",
                    },
                    "tts": {"status": "pending", "audio_path": None},
                    "timing": {"status": "pending", "fit_audio": None},
                    "loudness": {"status": "pending", "normalized_audio": None},
                },
            ],
        }

        merged = merge_dialogue_manifest_state(new_manifest, old_manifest)

        # Character 1's voice is updated to v2 and its downstream audio artifacts are invalidated (reset to pending)
        unit1 = merged["units"][0]
        self.assertEqual(unit1["voice"]["model_path"], "voices/lead_v2.onnx")
        self.assertEqual(unit1["voice"]["profile"]["model_path"], "voices/lead_v2.onnx")
        self.assertEqual(unit1["tts"]["status"], "pending")
        self.assertIsNone(unit1["tts"]["audio_path"])
        self.assertEqual(unit1["timing"]["status"], "pending")
        self.assertEqual(unit1["loudness"]["status"], "pending")
        # Translation is preserved
        self.assertEqual(unit1["translation"]["status"], "completed")

        # Character 2's voice was unchanged: its tts and audio artifacts remain valid
        unit2 = merged["units"][1]
        self.assertEqual(unit2["voice"]["model_path"], "voices/support.onnx")
        self.assertEqual(unit2["tts"]["status"], "completed")
        self.assertEqual(unit2["tts"]["audio_path"], "support.wav")
        self.assertEqual(unit2["timing"]["status"], "completed")
        self.assertEqual(unit2["loudness"]["status"], "completed")

    def test_manifest_state_merge_preserves_line_level_prosody_when_voice_changes(self):
        old_manifest = {
            "target_language": "hi",
            "units": [
                {
                    "segment_id": "seg-000001",
                    "source_text": "urgent warning",
                    "character_id": "char-1",
                    "translation": {"status": "completed", "text": "चेतावनी"},
                    "voice": {
                        "status": "configured",
                        "character_id": "char-1",
                        "profile": {"provider": "piper", "model_path": "voices/lead_v1.onnx"},
                        "model_path": "voices/lead_v1.onnx",
                    },
                    "prosody": {
                        "emotion": "urgent",
                        "delivery": "shouting",
                        "rate": 1.3,
                        "pitch": 2.0,
                        "volume": 1.5,
                        "review_required": False,
                    },
                    "tts": {"status": "completed", "audio_path": "urgent_v1.wav"},
                }
            ],
        }

        new_manifest = {
            "target_language": "hi",
            "units": [
                {
                    "segment_id": "seg-000001",
                    "source_text": "urgent warning",
                    "character_id": "char-1",
                    "translation": {"status": "pending"},
                    "voice": {
                        "status": "configured",
                        "character_id": "char-1",
                        "profile": {"provider": "piper", "model_path": "voices/lead_v2.onnx"},
                        "model_path": "voices/lead_v2.onnx",
                    },
                    "prosody": {"emotion": None, "rate": 1.0, "review_required": True},
                    "tts": {"status": "pending", "audio_path": None},
                }
            ],
        }

        merged = merge_dialogue_manifest_state(new_manifest, old_manifest)
        unit = merged["units"][0]
        # Line-level emotion and delivery intent are preserved from user edits
        self.assertEqual(unit["prosody"]["emotion"], "urgent")
        self.assertEqual(unit["prosody"]["delivery"], "shouting")
        self.assertEqual(unit["prosody"]["rate"], 1.3)
        # Voice is updated to v2 and audio is invalidated
        self.assertEqual(unit["voice"]["model_path"], "voices/lead_v2.onnx")
        self.assertEqual(unit["tts"]["status"], "pending")
        self.assertIsNone(unit["tts"]["audio_path"])

    def test_adaptation_suggestion_is_conservative_and_reviewable(self):
        result = suggest_dialogue_adaptation(
            source_text="hello",
            translated_text="Um, hello hello",
            tone="calm",
            delivery_intent="reassurance",
            max_words=4,
        )
        self.assertEqual(result["mode"], "conservative_assist")
        self.assertTrue(result["requires_review"])
        self.assertFalse(result["semantic_rewrite"])
        self.assertEqual(result["suggested_text"], "hello")
        self.assertEqual(result["tone"], "calm")
        self.assertEqual(result["delivery_intent"], "reassurance")

    def test_adaptation_budget_detects_overlong_target_dialogue(self):
        budget = evaluate_adaptation_budget(
            source_text="hello there",
            target_text="this target sentence is deliberately much longer than the available line budget",
            source_duration_sec=1.0,
            max_words=3,
        )
        self.assertEqual(budget["status"], "over_budget")
        self.assertTrue(budget["issues"])

    def test_adaptation_budget_accepts_line_inside_budget(self):
        budget = evaluate_adaptation_budget(
            source_text="hello there",
            target_text="नमस्ते",
            source_duration_sec=1.0,
            max_words=3,
        )
        self.assertEqual(budget["status"], "within_budget")

    def test_adaptation_budget_enforces_duration_even_without_explicit_word_limit(self):
        budget = evaluate_adaptation_budget(
            source_text="hello",
            target_text="one two three four five six seven",
            source_duration_sec=1.0,
        )
        self.assertEqual(budget["status"], "over_budget")
        self.assertEqual(budget["duration_word_limit"], 3)
        self.assertTrue(any("Estimated speech duration" in issue for issue in budget["issues"]))
        self.assertIn("heuristics", budget["note"])

    def test_adaptation_budget_enforces_both_explicit_and_duration_limits(self):
        budget = evaluate_adaptation_budget(
            source_text="hello",
            target_text="one two three four",
            source_duration_sec=2.0,
            max_words=10,
            words_per_second=2.0,
        )
        self.assertEqual(budget["status"], "within_budget")
        self.assertEqual(budget["max_words"], 4)
        self.assertEqual(budget["explicit_max_words"], 10)

    def test_translation_validation_catches_timebase_and_identity_drift(self):
        manifest = {
            "target_language": "hi",
            "units": [{
                "segment_index": 0,
                "segment_id": "seg-000001",
                "source_text": "hello",
                "start_sec": 1.0,
                "end_sec": 3.0,
                "character_id": "char-1",
            }],
        }
        translated = {
            "target_language": "hi",
            "segments": [{
                "segment_index": 0,
                "source_text": "hello",
                "translated_text": "नमस्ते",
                "start": 1.1,
                "end": 3.0,
                "character_id": "char-2",
            }],
        }
        report = validate_translation_manifest(manifest, translated)
        self.assertFalse(report["valid"])
        self.assertTrue(any("source-timebase drift" in issue.lower() for issue in report["issues"]))
        self.assertTrue(any("character identity drift" in issue.lower() for issue in report["issues"]))

    def test_translation_validation_passes_matching_units(self):
        manifest = {
            "target_language": "hi",
            "units": [{
                "segment_index": 0,
                "segment_id": "seg-000001",
                "source_text": "hello",
                "start_sec": 1.0,
                "end_sec": 3.0,
                "character_id": "char-1",
            }],
        }
        translated = {
            "target_language": "hi",
            "segments": [{
                "segment_index": 0,
                "source_text": "hello",
                "translated_text": "नमस्ते",
                "start": 1.0,
                "end": 3.0,
                "character_id": "char-1",
            }],
        }
        report = validate_translation_manifest(manifest, translated)
        self.assertTrue(report["valid"])

    def test_translation_validation_normalizes_language_name_and_code(self):
        manifest = {
            "target_language": "Hindi",
            "units": [{
                "segment_index": 0,
                "segment_id": "seg-000001",
                "source_text": "hello",
                "start_sec": 1.0,
                "end_sec": 3.0,
                "character_id": "char-1",
            }],
        }
        translated = {
            "target_language": "hi",
            "segments": [{
                "segment_index": 0,
                "source_text": "hello",
                "translated_text": "नमस्ते",
                "start": 1.0,
                "end": 3.0,
                "character_id": "char-1",
            }],
        }
        report = validate_translation_manifest(manifest, translated)
        self.assertTrue(report["valid"])
        self.assertEqual(report["issues"], [])

    def test_pipeline_state_blocks_translation_without_character_identity(self):
        transcript_path = self.root / "analysis" / "transcript.json"
        timeline_path = self.root / "analysis" / "timeline.json"
        manifest_path = self.root / "analysis" / "analysis_manifest.json"
        transcript_path.write_text(
            json.dumps({"language": "zh", "segments": [{"speaker_id": "SPEAKER_00", "text": "x"}]}),
            encoding="utf-8",
        )
        timeline_path.write_text(json.dumps({"segments": [{"text": "x"}]}), encoding="utf-8")
        manifest_path.write_text(json.dumps({"status": "completed"}), encoding="utf-8")
        state = get_pipeline_state(project_root=self.root, project_id="project-1", target_language="hi")
        self.assertEqual(state["next_recommended"]["id"], "character_identity")
        identity = next(stage for stage in state["stages"] if stage["id"] == "character_identity")
        self.assertFalse(identity["ready"])

    def test_pipeline_state_recognizes_automatic_character_identity(self):
        (self.root / "analysis" / "transcript.json").write_text(
            json.dumps({"language": "zh", "segments": [{"speaker_id": "SPEAKER_00", "text": "x"}]}),
            encoding="utf-8",
        )
        (self.root / "analysis" / "timeline.json").write_text(
            json.dumps({"segments": [{"text": "x"}]}), encoding="utf-8"
        )
        (self.root / "analysis" / "analysis_manifest.json").write_text(
            json.dumps({"status": "completed"}), encoding="utf-8"
        )
        (self.root / "characters" / "registry.json").write_text(
            json.dumps({
                "speaker_links": {"SPEAKER_00": "char-1"},
                "characters": [{
                    "character_id": "char-1",
                    "display_name": "Character 1",
                    "review_required": True,
                }],
            }),
            encoding="utf-8",
        )
        state = get_pipeline_state(project_root=self.root, project_id="project-1", target_language="hi")
        identity = next(stage for stage in state["stages"] if stage["id"] == "character_identity")
        self.assertTrue(identity["ready"])
        self.assertEqual(identity["status"], "review_required")
        self.assertEqual(state["next_recommended"]["id"], "translation")

    def test_pipeline_state_reflects_background_preservation_mix_and_render(self):
        output_dir = self.root / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        bg_file = output_dir / "background_preserved.wav"
        mix_file = output_dir / "dubbed_audio_mix.wav"
        render_file = output_dir / "movie_dubbed.mp4"

        # Initially not started
        state = get_pipeline_state(project_root=self.root, project_id="project-1", target_language="hi")
        stages = {s["id"]: s for s in state["stages"]}
        self.assertFalse(stages["dialogue_removal"]["ready"])
        self.assertFalse(stages["background_preservation"]["ready"])
        self.assertFalse(stages["mix"]["ready"])
        self.assertFalse(stages["render"]["ready"])

        # When background is preserved
        bg_file.write_text("dummy", encoding="utf-8")
        state = get_pipeline_state(project_root=self.root, project_id="project-1", target_language="hi")
        stages = {s["id"]: s for s in state["stages"]}
        self.assertTrue(stages["dialogue_removal"]["ready"])
        self.assertEqual(stages["dialogue_removal"]["status"], "completed")
        self.assertTrue(stages["background_preservation"]["ready"])
        self.assertEqual(stages["background_preservation"]["status"], "completed")
        self.assertEqual(stages["mix"]["status"], "ready")

        # When mix is built
        mix_file.write_text("dummy", encoding="utf-8")
        state = get_pipeline_state(project_root=self.root, project_id="project-1", target_language="hi")
        stages = {s["id"]: s for s in state["stages"]}
        self.assertTrue(stages["mix"]["ready"])
        self.assertEqual(stages["mix"]["status"], "completed")
        self.assertEqual(stages["render"]["status"], "ready")

        # When render is completed
        render_file.write_text("dummy", encoding="utf-8")
        state = get_pipeline_state(project_root=self.root, project_id="project-1", target_language="hi")
        stages = {s["id"]: s for s in state["stages"]}
        self.assertTrue(stages["render"]["ready"])
        self.assertEqual(stages["render"]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
