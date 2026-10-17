from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.system_diagnostics import collect_diagnostics, _run_version


class SystemDiagnosticsTests(unittest.TestCase):
    def test_report_contains_required_local_components(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = collect_diagnostics(Path(tmp), "test-version")
        self.assertTrue(report["ok"])
        self.assertEqual(report["app"]["version"], "test-version")
        for key in ("system", "python", "ffmpeg", "ffprobe", "gpu", "memory", "disk", "optional_modules"):
            self.assertIn(key, report)
        self.assertIn("total_bytes", report["memory"])
        self.assertIn("free_bytes", report["disk"])
        self.assertIn("available", report["gpu"])

    def test_missing_executable_is_reported_not_raised(self):
        result = _run_version(["opendub-command-that-does-not-exist"])
        self.assertFalse(result["available"])
        self.assertEqual(result["status"], "missing")
        self.assertIn("not found", result["error"])


if __name__ == "__main__":
    unittest.main()
