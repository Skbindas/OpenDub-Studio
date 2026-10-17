from __future__ import annotations

import os
import unittest
from types import ModuleType
from unittest.mock import patch

from backend.diarization import _is_hf_access_error, diarization_runtime_status


class DiarizationRuntimeTests(unittest.TestCase):
    def test_runtime_status_does_not_expose_token(self):
        with patch.dict(os.environ, {"HF_TOKEN": "secret-token"}, clear=False):
            result = diarization_runtime_status()
        self.assertIn("hf_token_configured", result)
        self.assertTrue(result["hf_token_configured"])
        self.assertNotIn("secret-token", str(result))

    def test_gated_huggingface_errors_are_classified_as_access_errors(self):
        self.assertTrue(_is_hf_access_error(RuntimeError(
            "403 Client Error. Cannot access gated repo; you are not in the authorized list."
        )))
        self.assertTrue(_is_hf_access_error(RuntimeError(
            "Access to model pyannote/speaker-diarization-community-1 is restricted"
        )))
        self.assertFalse(_is_hf_access_error(RuntimeError("CUDA out of memory")))

    def test_model_access_requires_huggingface_authorization(self):
        from backend.diarization import check_model_access

        with patch.dict(os.environ, {"HF_TOKEN": "hf-test"}, clear=True):
            fake_api = type("FakeApi", (), {
                "__init__": lambda self, token=None: None,
                "auth_check": lambda self, _name: (_ for _ in ()).throw(
                    RuntimeError("403 Client Error: gated model access restricted")
                )
            })
            fake_hub = ModuleType("huggingface_hub")
            fake_hub.HfApi = fake_api
            with patch.dict("sys.modules", {"huggingface_hub": fake_hub}):
                result = check_model_access()
        self.assertEqual(result["status"], "authorization_required")
        self.assertFalse(result["authorized"])
        self.assertNotIn("hf-test", str(result))

    def test_runtime_status_needs_setup_without_token(self):
        with patch.dict(os.environ, {}, clear=True):
            result = diarization_runtime_status()
        self.assertFalse(result["hf_token_configured"])
        self.assertEqual(result["status"], "needs_setup")


if __name__ == "__main__":
    unittest.main()
