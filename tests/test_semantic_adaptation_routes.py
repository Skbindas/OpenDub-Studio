import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import app as app_module


class SemanticAdaptationRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project_id = "route-test-project"
        self.project = self.root / self.project_id
        (self.project / "analysis").mkdir(parents=True)
        (self.project / "characters").mkdir()
        manifest = {
            "source_language": "English",
            "target_language": "Hindi",
            "units": [{
                "segment_index": 0,
                "source_text": "How did you get here?",
                "duration_sec": 2.0,
                "character_id": "char-1",
                "translation": {"text": "तुम यहाँ कैसे आए?"},
            }],
        }
        (self.project / "analysis" / "dialogue_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        self.patches = [
            patch.object(app_module, "get_project",
                         side_effect=lambda _db, pid: {"id": pid} if pid == self.project_id else None),
            patch.object(app_module, "project_dir", side_effect=lambda pid: self.project if pid == self.project_id else self.root / pid),
            patch.object(app_module, "semantic_provider_configured", return_value=True),
            patch.object(app_module, "propose_semantic_adaptation", return_value={
                "suggested_text": "अरे, तुम यहाँ कैसे आए?",
                "requires_review": True,
                "production_ready": False,
                "validation_status": "pending",
            }),
        ]
        for item in self.patches:
            item.start()
        self.client = TestClient(app_module.app)

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_prosody_patch_persists_validated_values(self):
        response = self.client.patch(
            f"/api/projects/{self.project_id}/dialogue/0/prosody",
            json={"emotion": "warm", "delivery": "soft", "rate": 1.1, "pitch": 2, "volume": 0.9, "review_required": False},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["prosody"]["emotion"], "warm")
        saved = json.loads((self.project / "analysis" / "dialogue_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["units"][0]["prosody"]["rate"], 1.1)
        self.assertEqual(saved["units"][0]["prosody"]["provider_support"], "not_checked")

    def test_prosody_patch_rejects_out_of_range_rate(self):
        response = self.client.patch(
            f"/api/projects/{self.project_id}/dialogue/0/prosody",
            json={"rate": 4.0},
        )
        self.assertEqual(response.status_code, 422)

    def test_prosody_patch_unknown_segment_returns_404(self):
        response = self.client.patch(
            f"/api/projects/{self.project_id}/dialogue/99/prosody",
            json={"rate": 1.0},
        )
        self.assertEqual(response.status_code, 404)

    def payload(self):
        return {"translated_text": "तुम यहाँ कैसे आए?", "adaptation_mode": "llm_semantic_assist"}

    def test_missing_project_returns_404(self):
        response = self.client.post("/api/projects/missing/dialogue/0/adaptation/suggest", json=self.payload())
        self.assertEqual(response.status_code, 404)

    def test_invalid_segment_returns_404(self):
        response = self.client.post(f"/api/projects/{self.project_id}/dialogue/99/adaptation/suggest", json=self.payload())
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Dialogue segment not found")

    def test_provider_unavailable_returns_503(self):
        with patch.object(app_module, "semantic_provider_configured", return_value=False):
            response = self.client.post(f"/api/projects/{self.project_id}/dialogue/0/adaptation/suggest", json=self.payload())
        self.assertEqual(response.status_code, 503)
        self.assertIn("not configured", response.json()["detail"])

    def test_corrupt_registry_falls_back_and_response_remains_review_only(self):
        (self.project / "characters" / "registry.json").write_text("{broken", encoding="utf-8")
        response = self.client.post(f"/api/projects/{self.project_id}/dialogue/0/adaptation/suggest", json=self.payload())
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result["requires_review"])
        self.assertFalse(result["production_ready"])
        self.assertEqual(result["validation"]["overall"], "needs_review")
        app_module.propose_semantic_adaptation.assert_called_once()
        call = app_module.propose_semantic_adaptation.call_args
        self.assertIn("do not infer identity traits", call.kwargs["character_identity"])

    def test_successful_suggestion_does_not_mutate_master_manifest(self):
        manifest_path = self.project / "analysis" / "dialogue_manifest.json"
        before = manifest_path.read_bytes()

        response = self.client.post(
            f"/api/projects/{self.project_id}/dialogue/0/adaptation/suggest",
            json=self.payload(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["requires_review"])
        self.assertFalse(response.json()["production_ready"])
        self.assertEqual(manifest_path.read_bytes(), before)

    def test_successful_suggestion_does_not_mutate_translated_transcript(self):
        translated_path = self.project / "analysis" / "translated_transcript.json"
        translated = {
            "segments": [{
                "segment_index": 0,
                "translated_text": "तुम यहाँ कैसे आए?",
                "start": 0.0,
                "end": 2.0,
            }]
        }
        translated_path.write_text(
            json.dumps(translated, ensure_ascii=False), encoding="utf-8"
        )
        before = translated_path.read_bytes()

        response = self.client.post(
            f"/api/projects/{self.project_id}/dialogue/0/adaptation/suggest",
            json=self.payload(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(translated_path.read_bytes(), before)
        self.assertEqual(
            json.loads(translated_path.read_text(encoding="utf-8"))["segments"][0]["translated_text"],
            "तुम यहाँ कैसे आए?",
        )

    def test_untrusted_provider_flags_cannot_mark_suggestion_production_ready(self):
        with patch.object(
            app_module, "propose_semantic_adaptation",
            return_value={
                "suggested_text": "अरे, तुम यहाँ कैसे आए?",
                "requires_review": False,
                "production_ready": True,
                "validation_status": "approved",
                "validation": {"overall": "passed"},
            },
        ):
            response = self.client.post(
                f"/api/projects/{self.project_id}/dialogue/0/adaptation/suggest",
                json=self.payload(),
            )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result["requires_review"])
        self.assertFalse(result["production_ready"])
        self.assertEqual(result["validation"]["overall"], "needs_review")
        self.assertEqual(result["validation_status"], "needs_review")

    def test_over_budget_suggestion_remains_review_only_with_timing_warning(self):
        with patch.object(
            app_module, "propose_semantic_adaptation",
            return_value={
                "suggested_text": "यह बहुत लंबा संवाद है जो दो सेकंड में बोला नहीं जा सकता बिल्कुल भी",
                "requires_review": False,
                "production_ready": True,
                "validation_status": "approved",
            },
        ):
            response = self.client.post(
                f"/api/projects/{self.project_id}/dialogue/0/adaptation/suggest",
                json=self.payload(),
            )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["validation"]["timing"]["status"], "over_budget")
        self.assertEqual(result["validation"]["overall"], "timing_over_budget")
        self.assertTrue(result["requires_review"])
        self.assertFalse(result["production_ready"])

    def test_review_reject_does_not_write_translation(self):
        translation_path = self.project / "analysis" / "translated_transcript.json"
        original = {"segments": [{"segment_index": 0, "translated_text": "मूल अनुवाद"}]}
        translation_path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
        before = translation_path.read_bytes()
        response = self.client.post(
            f"/api/projects/{self.project_id}/dialogue/0/adaptation/review",
            json={"decision": "reject", "suggested_text": "अस्वीकृत सुझाव"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["written"])
        self.assertEqual(translation_path.read_bytes(), before)

    def test_review_approval_writes_approved_text_to_synthesis_input(self):
        translation_path = self.project / "analysis" / "translated_transcript.json"
        translation_path.write_text(json.dumps({
            "segments": [{"segment_index": 0, "translated_text": "मूल अनुवाद"}]
        }, ensure_ascii=False), encoding="utf-8")
        response = self.client.post(
            f"/api/projects/{self.project_id}/dialogue/0/adaptation/review",
            json={"decision": "approve", "suggested_text": "अरे, तुम यहाँ कैसे आए?", "adaptation_mode": "llm_semantic_assist"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["written"])
        self.assertEqual(response.json()["decision"], "approved")
        persisted = json.loads(translation_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["segments"][0]["translated_text"], "अरे, तुम यहाँ कैसे आए?")
        self.assertEqual(persisted["segments"][0]["adaptation_review"]["decision"], "approved")
        manifest = json.loads((self.project / "analysis" / "dialogue_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["units"][0]["translation"]["adaptation"]["status"], "human_approved")
        self.assertEqual(manifest["units"][0]["translation"]["adaptation"]["mode"], "llm_semantic_assist")

    def test_review_audit_log_records_rejection_and_incrementing_revisions(self):
        translation_path = self.project / "analysis" / "translated_transcript.json"
        translation_path.write_text(json.dumps({
            "segments": [{"segment_index": 0, "translated_text": "मूल अनुवाद"}]
        }, ensure_ascii=False), encoding="utf-8")
        url = f"/api/projects/{self.project_id}/dialogue/0/adaptation/review"
        rejected = self.client.post(url, json={
            "decision": "reject", "suggested_text": "पहला सुझाव",
            "adaptation_mode": "llm_semantic_assist",
        })
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(rejected.json()["revision"], 1)
        self.assertTrue(rejected.json()["audit_recorded"])
        approved = self.client.post(url, json={
            "decision": "approve", "suggested_text": "स्वीकृत संवाद",
            "adaptation_mode": "llm_semantic_assist",
        })
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["revision"], 2)
        audit_path = self.project / "analysis" / "adaptation_review_audit.jsonl"
        events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([event["decision"] for event in events], ["rejected", "approved"])
        self.assertEqual([event["revision"] for event in events], [1, 2])
        self.assertEqual(events[0]["previous_text"], "मूल अनुवाद")
        self.assertEqual(events[1]["candidate_text"], "स्वीकृत संवाद")

    def test_review_invalid_decision_is_rejected(self):
        response = self.client.post(
            f"/api/projects/{self.project_id}/dialogue/0/adaptation/review",
            json={"decision": "auto_approve", "suggested_text": "किसी भी तरह"},
        )
        self.assertEqual(response.status_code, 422)

    def _write_synthesis_input(self, review=None):
        path = self.project / "analysis" / "translated_transcript.json"
        row = {
            "segment_index": 0,
            "translated_text": "अरे, तुम यहाँ कैसे आए?",
            "start": 0.0, "end": 2.0,
            "adaptation_mode": "llm_semantic_assist",
        }
        if review is not None:
            row["adaptation_review"] = review
        path.write_text(json.dumps({"segments": [row]}, ensure_ascii=False), encoding="utf-8")
        return path

    def test_synthesis_blocks_unreviewed_semantic_adaptation(self):
        self._write_synthesis_input()
        with patch.object(app_module, "synthesize_piper_segment") as synth:
            response = self.client.post(
                f"/api/projects/{self.project_id}/segments/0/synthesize",
                json={"voice_model_path": "/tmp/test-voice.onnx"},
            )
        self.assertEqual(response.status_code, 409)
        self.assertIn("human approval", response.json()["detail"])
        synth.assert_not_called()

    @staticmethod
    def _fake_synthesis(text, output_path, voice_model, speaker_id=None, prosody=None):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake wav bytes")
        return {"status": "ok", "file": str(output_path), "size_bytes": output_path.stat().st_size}

    def test_synthesis_allows_human_approved_semantic_adaptation(self):
        self._write_synthesis_input({"decision": "approved", "reviewed_by": "user"})
        with patch.object(app_module, "synthesize_piper_segment", side_effect=self._fake_synthesis) as synth, patch.object(app_module, "ffprobe", return_value={"available": True, "duration_ms": 1900}):
            response = self.client.post(
                f"/api/projects/{self.project_id}/segments/0/synthesize",
                json={"voice_model_path": "/tmp/test-voice.onnx"},
            )
        self.assertEqual(response.status_code, 200)
        synth.assert_called_once()
        persisted = json.loads((self.project / "analysis" / "translated_transcript.json").read_text(encoding="utf-8"))
        self.assertEqual(persisted["segments"][0]["dub_audio"], str(self.project / "segments" / "segment_000000_dub.wav"))

    def test_synthesis_passes_saved_manifest_prosody_to_piper(self):
        self._write_synthesis_input({"decision": "approved", "reviewed_by": "user"})
        manifest_path = self.project / "analysis" / "dialogue_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["units"][0]["prosody"] = {
            "emotion": "warm", "delivery": "soft", "rate": 1.2,
            "pitch": 1, "volume": 0.9,
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        with patch.object(app_module, "synthesize_piper_segment", side_effect=self._fake_synthesis) as synth, \
             patch.object(app_module, "ffprobe", return_value={"available": True, "duration_ms": 1900}):
            response = self.client.post(
                f"/api/projects/{self.project_id}/segments/0/synthesize",
                json={"voice_model_path": "/tmp/test-voice.onnx"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(synth.call_args.args[4], {**manifest["units"][0]["prosody"], "target_duration_sec": 2.0})

    def test_synthesis_uses_assigned_character_piper_profile(self):
        self._write_synthesis_input({"decision": "approved", "reviewed_by": "user"})
        manifest_path = self.project / "analysis" / "dialogue_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["units"][0]["voice"] = {"status": "configured", "character_id": "character-a", "profile": {"provider": "piper", "model_path": "voices/lead.onnx", "settings": {"speaker_id": 3}}}
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        with patch.object(app_module, "synthesize_piper_segment", side_effect=self._fake_synthesis) as synth, patch.object(app_module, "ffprobe", return_value={"available": True, "duration_ms": 1900}):
            response = self.client.post(f"/api/projects/{self.project_id}/segments/0/synthesize", json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Path(synth.call_args.args[2]).as_posix(), "voices/lead.onnx")
        self.assertEqual(synth.call_args.args[3], 3)
    def test_synthesis_uses_explicit_segment_index_not_list_position(self):
        self._write_synthesis_input({"decision": "approved", "reviewed_by": "user"})

        path = self.project / "analysis" / "translated_transcript.json"
        path.write_text(json.dumps({
            "segments": [
                {
                    "segment_index": 1,
                    "translated_text": "WRONG_SEGMENT_ONE",
                    "start": 2.0,
                    "end": 4.0,
                },
                {
                    "segment_index": 0,
                    "translated_text": "RIGHT_SEGMENT_ZERO",
                    "start": 0.0,
                    "end": 2.0,
                    "adaptation_mode": "llm_semantic_assist",
                    "adaptation_review": {"decision": "approved"},
                },
            ]
        }), encoding="utf-8")

        with patch.object(
            app_module,
            "synthesize_piper_segment",
            side_effect=self._fake_synthesis,
        ) as synth, patch.object(
            app_module,
            "ffprobe",
            return_value={"available": True, "duration_ms": 1900},
        ):
            response = self.client.post(
                f"/api/projects/{self.project_id}/segments/0/synthesize",
                json={"voice_model_path": "/tmp/test-voice.onnx"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        synth.assert_called_once()
        self.assertEqual(synth.call_args.args[0], "RIGHT_SEGMENT_ZERO")

    def test_synthesis_rejects_unimplemented_assigned_provider(self):
        self._write_synthesis_input({"decision": "approved", "reviewed_by": "user"})
        manifest_path = self.project / "analysis" / "dialogue_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["units"][0]["voice"] = {"status": "configured", "character_id": "character-a", "profile": {"provider": "openai_compatible", "voice_id": "voice-a"}}
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        with patch.object(app_module, "synthesize_piper_segment") as synth:
            response = self.client.post(f"/api/projects/{self.project_id}/segments/0/synthesize", json={})
        self.assertEqual(response.status_code, 409)
        self.assertIn("not supported", response.json()["detail"])
        synth.assert_not_called()
    def test_provider_error_returns_502(self):
        with patch.object(
            app_module, "propose_semantic_adaptation",
            side_effect=app_module.SemanticAdaptationError("upstream provider failed"),
        ):
            response = self.client.post(
                f"/api/projects/{self.project_id}/dialogue/0/adaptation/suggest",
                json=self.payload(),
            )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "upstream provider failed")

    def test_blank_translated_text_returns_422(self):
        payload = self.payload()
        payload["translated_text"] = "   "
        response = self.client.post(
            f"/api/projects/{self.project_id}/dialogue/0/adaptation/suggest",
            json=payload,
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("Provide translated dialogue", response.json()["detail"])

    def test_missing_manifest_returns_409(self):
        (self.project / "analysis" / "dialogue_manifest.json").unlink()
        response = self.client.post(f"/api/projects/{self.project_id}/dialogue/0/adaptation/suggest", json=self.payload())
        self.assertEqual(response.status_code, 409)


    def test_fit_uses_explicit_segment_index_and_updates_correct_segment(self):
        seg0_audio = self.project / "segments" / "segment_000000_dub.wav"
        seg1_audio = self.project / "segments" / "segment_000001_dub.wav"
        seg0_audio.parent.mkdir(parents=True, exist_ok=True)
        seg0_audio.write_bytes(b"audio zero")
        seg1_audio.write_bytes(b"audio one")

        path = self.project / "analysis" / "translated_transcript.json"
        path.write_text(json.dumps({
            "segments": [
                {
                    "segment_index": 1,
                    "translated_text": "SEGMENT_ONE",
                    "start": 2.0, "end": 4.0,
                    "dub_audio": str(seg1_audio),
                },
                {
                    "segment_index": 0,
                    "translated_text": "SEGMENT_ZERO",
                    "start": 0.0, "end": 2.0,
                    "dub_audio": str(seg0_audio),
                },
            ]
        }), encoding="utf-8")

        with patch.object(
            app_module, "fit_audio",
            return_value={"status": "fitted", "duration_sec": 2.0},
        ) as mock_fit:
            response = self.client.post(
                f"/api/projects/{self.project_id}/segments/0/fit",
                json={"max_speedup": 1.25, "max_slowdown": 0.8},
            )

        self.assertEqual(response.status_code, 200, response.text)
        mock_fit.assert_called_once()
        self.assertEqual(Path(mock_fit.call_args.args[0]), seg0_audio)
        saved = json.loads(path.read_text(encoding="utf-8"))["segments"]
        self.assertIn("fitted_audio", saved[1])
        self.assertNotIn("fitted_audio", saved[0])
        self.assertEqual(saved[1]["segment_index"], 0)

    def test_normalize_uses_explicit_segment_index_and_updates_correct_segment(self):
        seg0_audio = self.project / "segments" / "segment_000000_fit.wav"
        seg1_audio = self.project / "segments" / "segment_000001_fit.wav"
        seg0_audio.parent.mkdir(parents=True, exist_ok=True)
        seg0_audio.write_bytes(b"fit audio zero")
        seg1_audio.write_bytes(b"fit audio one")

        path = self.project / "analysis" / "translated_transcript.json"
        path.write_text(json.dumps({
            "segments": [
                {
                    "segment_index": 1,
                    "translated_text": "SEGMENT_ONE",
                    "start": 2.0, "end": 4.0,
                    "fitted_audio": str(seg1_audio),
                },
                {
                    "segment_index": 0,
                    "translated_text": "SEGMENT_ZERO",
                    "start": 0.0, "end": 2.0,
                    "fitted_audio": str(seg0_audio),
                },
            ]
        }), encoding="utf-8")

        with patch.object(
            app_module, "normalize_audio",
            return_value={"status": "normalized", "lufs": -16.0},
        ) as mock_norm:
            response = self.client.post(
                f"/api/projects/{self.project_id}/segments/0/normalize?target_lufs=-16",
            )

        self.assertEqual(response.status_code, 200, response.text)
        mock_norm.assert_called_once()
        self.assertEqual(Path(mock_norm.call_args.args[0]), seg0_audio)
        saved = json.loads(path.read_text(encoding="utf-8"))["segments"]
        self.assertIn("normalized_audio", saved[1])
        self.assertNotIn("normalized_audio", saved[0])
        self.assertEqual(saved[1]["segment_index"], 0)

    def test_missing_explicit_segment_index_returns_404(self):
        self._write_synthesis_input({"decision": "approved", "reviewed_by": "user"})
        res_synth = self.client.post(
            f"/api/projects/{self.project_id}/segments/99/synthesize",
            json={"voice_model_path": "/tmp/test-voice.onnx"},
        )
        self.assertEqual(res_synth.status_code, 404)
        self.assertEqual(res_synth.json()["detail"], "Segment index not found")

        res_fit = self.client.post(
            f"/api/projects/{self.project_id}/segments/99/fit",
            json={},
        )
        self.assertEqual(res_fit.status_code, 404)
        self.assertEqual(res_fit.json()["detail"], "Segment index not found")

        res_norm = self.client.post(
            f"/api/projects/{self.project_id}/segments/99/normalize",
        )
        self.assertEqual(res_norm.status_code, 404)
        self.assertEqual(res_norm.json()["detail"], "Segment index not found")

    def test_malformed_segment_entries_do_not_crash_application(self):
        path = self.project / "analysis" / "translated_transcript.json"
        path.write_text(json.dumps({
            "segments": [
                None,
                "not-a-dict",
                12345,
                {"no_segment_index": True},
                {"segment_index": "not_an_int"},
                {
                    "segment_index": 0,
                    "translated_text": "VALID_ZERO",
                    "start": 0.0,
                    "end": 2.0,
                    "adaptation_mode": "llm_semantic_assist",
                    "adaptation_review": {"decision": "approved"},
                },
            ]
        }), encoding="utf-8")

        with patch.object(
            app_module,
            "synthesize_piper_segment",
            side_effect=self._fake_synthesis,
        ) as synth, patch.object(
            app_module,
            "ffprobe",
            return_value={"available": True, "duration_ms": 1900},
        ):
            response = self.client.post(
                f"/api/projects/{self.project_id}/segments/0/synthesize",
                json={"voice_model_path": "/tmp/test-voice.onnx"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        synth.assert_called_once()
        self.assertEqual(synth.call_args.args[0], "VALID_ZERO")

        res_missing = self.client.post(
            f"/api/projects/{self.project_id}/segments/99/synthesize",
            json={"voice_model_path": "/tmp/test-voice.onnx"},
        )
        self.assertEqual(res_missing.status_code, 404)

    def test_approval_checks_apply_to_correct_reordered_segment(self):
        path = self.project / "analysis" / "translated_transcript.json"
        path.write_text(json.dumps({
            "segments": [
                {
                    "segment_index": 1,
                    "translated_text": "UNAPPROVED_ONE",
                    "start": 2.0, "end": 4.0,
                    "adaptation_mode": "llm_semantic_assist",
                    "adaptation_review": {"decision": "rejected"},
                },
                {
                    "segment_index": 0,
                    "translated_text": "APPROVED_ZERO",
                    "start": 0.0, "end": 2.0,
                    "adaptation_mode": "llm_semantic_assist",
                    "adaptation_review": {"decision": "approved"},
                },
            ]
        }), encoding="utf-8")

        with patch.object(
            app_module,
            "synthesize_piper_segment",
            side_effect=self._fake_synthesis,
        ), patch.object(
            app_module,
            "ffprobe",
            return_value={"available": True, "duration_ms": 1900},
        ):
            res_0 = self.client.post(
                f"/api/projects/{self.project_id}/segments/0/synthesize",
                json={"voice_model_path": "/tmp/test-voice.onnx"},
            )
        self.assertEqual(res_0.status_code, 200, res_0.text)

        res_1 = self.client.post(
            f"/api/projects/{self.project_id}/segments/1/synthesize",
            json={"voice_model_path": "/tmp/test-voice.onnx"},
        )
        self.assertEqual(res_1.status_code, 409)
        self.assertIn("human approval", res_1.json()["detail"])


if __name__ == "__main__":
    unittest.main()
