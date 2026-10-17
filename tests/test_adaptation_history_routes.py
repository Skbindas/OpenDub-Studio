import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import app as app_module


class AdaptationHistoryRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project_id = "history-test-project"
        self.project = self.root / self.project_id
        (self.project / "analysis").mkdir(parents=True)
        (self.project / "analysis" / "dialogue_manifest.json").write_text(json.dumps({
            "units": [{"segment_index": 0, "source_text": "Hello", "duration_sec": 2,
                       "translation": {"text": "नमस्ते"}}]
        }, ensure_ascii=False), encoding="utf-8")
        (self.project / "analysis" / "translated_transcript.json").write_text(json.dumps({
            "segments": [{"segment_index": 0, "translated_text": "नमस्ते"}]
        }, ensure_ascii=False), encoding="utf-8")
        self.patches = [
            patch.object(app_module, "get_project",
                         side_effect=lambda _db, pid: {"id": pid} if pid == self.project_id else None),
            patch.object(app_module, "project_dir",
                         side_effect=lambda pid: self.project if pid == self.project_id else self.root / pid),
        ]
        for item in self.patches:
            item.start()
        self.client = TestClient(app_module.app)

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_history_returns_events_newest_first_and_filters_segment(self):
        audit = self.project / "analysis" / "adaptation_review_audit.jsonl"
        audit.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in [
            {"segment_index": 0, "revision": 1, "decision": "approved", "candidate_text": "पहला"},
            {"segment_index": 1, "revision": 1, "decision": "approved", "candidate_text": "दूसरा"},
            {"segment_index": 0, "revision": 2, "decision": "rejected", "candidate_text": "तीसरा"},
        ]) + "\n", encoding="utf-8")
        response = self.client.get(f"/api/projects/{self.project_id}/dialogue/0/adaptation/history")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([event["revision"] for event in response.json()["events"]], [2, 1])

    def test_restore_approved_revision_appends_new_audit_event(self):
        audit = self.project / "analysis" / "adaptation_review_audit.jsonl"
        audit.write_text(json.dumps({
            "segment_index": 0, "revision": 1, "decision": "approved",
            "candidate_text": "पुराना स्वीकृत संवाद", "adaptation_mode": "llm_semantic_assist",
            "tone": "warm", "delivery_intent": "friendly",
        }, ensure_ascii=False) + "\n", encoding="utf-8")
        response = self.client.post(
            f"/api/projects/{self.project_id}/dialogue/0/adaptation/restore/1"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["restored_from_revision"], 1)
        self.assertEqual(response.json()["revision"], 2)
        translated = json.loads((self.project / "analysis" / "translated_transcript.json").read_text(encoding="utf-8"))
        self.assertEqual(translated["segments"][0]["translated_text"], "पुराना स्वीकृत संवाद")
        events = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(events), 2)
        self.assertEqual(events[-1]["restored_from_revision"], 1)
        self.assertEqual(events[-1]["decision"], "approved")

    def test_restore_rejects_non_approved_revision(self):
        audit = self.project / "analysis" / "adaptation_review_audit.jsonl"
        audit.write_text(json.dumps({
            "segment_index": 0, "revision": 1, "decision": "rejected",
            "candidate_text": "अस्वीकृत",
        }, ensure_ascii=False) + "\n", encoding="utf-8")
        response = self.client.post(
            f"/api/projects/{self.project_id}/dialogue/0/adaptation/restore/1"
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
