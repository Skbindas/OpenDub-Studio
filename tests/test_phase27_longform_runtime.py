"""Phase 27 Unit & Integration Tests: Long-Form Checkpointing, Resume & Resource Manager."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.longform_runtime import (
    PIPELINE_STAGES,
    BoundedRetryPolicy,
    CheckpointManager,
    DiskSpaceCircuitBreakerError,
    ModelLifecycleManager,
    ResourceMonitor,
    StructuredAuditLogger,
    atomic_write_bytes,
    redact_secrets,
    sha256_bytes,
)


class Phase27LongformRuntimeTests(unittest.TestCase):
    """Tests for Phase 27 checkpoint/resume, atomic writes, retries, resource monitor, and secret redaction."""

    def test_01_all_12_pipeline_stages_checkpoint_and_resume_skip_verified(self) -> None:
        """Completed units with matching input/output SHA-256 are skipped on resume; modified inputs re-run."""
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            ckpt_mgr = CheckpointManager(
                project_id="53ba81b5-cc7c-4a68-944e-ff553456a917",
                checkpoint_dir=base_dir / "checkpoints",
                phase=27,
            )
            self.assertEqual(len(PIPELINE_STAGES), 12)

            out_file = base_dir / "segments" / "seg_14_fitted.wav"
            payload = b"RIFF_DUMMY_WAV_PAYLOAD_SEG_14"
            atomic_write_bytes(out_file, payload)
            in_hash = sha256_bytes(b"seg_14_input_v1")

            entry = ckpt_mgr.record_checkpoint(
                stage="segment_duration_fitting",
                unit_id="seg_14",
                input_hash=in_hash,
                output_path=out_file,
                duration_sec=3.56,
                attempt=1,
                base_dir=base_dir,
            )
            self.assertEqual(entry["output_path"], "segments/seg_14_fitted.wav")

            # Reload manager from disk to simulate process restart after crash/interruption
            resumed_mgr = CheckpointManager(
                project_id="53ba81b5-cc7c-4a68-944e-ff553456a917",
                checkpoint_dir=base_dir / "checkpoints",
                phase=27,
            )
            valid, reason, _ = resumed_mgr.is_unit_valid(
                stage="segment_duration_fitting",
                unit_id="seg_14",
                expected_input_hash=in_hash,
                base_dir=base_dir,
            )
            self.assertTrue(valid)
            self.assertEqual(reason, "verified_reusable")

            # Changing input hash invalidates cache
            valid_changed, reason_changed, _ = resumed_mgr.is_unit_valid(
                stage="segment_duration_fitting",
                unit_id="seg_14",
                expected_input_hash=sha256_bytes(b"seg_14_input_v2"),
                base_dir=base_dir,
            )
            self.assertFalse(valid_changed)
            self.assertEqual(reason_changed, "input_hash_changed")

            # Tampering with output file invalidates cache
            atomic_write_bytes(out_file, b"CORRUPTED_BYTES")
            valid_corrupt, reason_corrupt, _ = resumed_mgr.is_unit_valid(
                stage="segment_duration_fitting",
                unit_id="seg_14",
                expected_input_hash=in_hash,
                base_dir=base_dir,
            )
            self.assertFalse(valid_corrupt)
            self.assertEqual(reason_corrupt, "output_hash_mismatch")

    def test_02_interrupted_tmp_files_cleaned_up_on_resume(self) -> None:
        """Leftover .tmp files from a killed process are automatically cleaned up."""
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            ckpt_mgr = CheckpointManager("test-proj", base_dir / "checkpoints")
            stale_tmp = base_dir / "segments" / "seg_09_fitted.wav.tmp"
            stale_tmp.parent.mkdir(parents=True, exist_ok=True)
            stale_tmp.write_bytes(b"PARTIAL_UNFINISHED_WRITE")

            removed = ckpt_mgr.cleanup_stale_tmp_files(base_dir)
            self.assertEqual(len(removed), 1)
            self.assertFalse(stale_tmp.exists())

    def test_03_bounded_retry_policy_recovers_transient_and_stops_on_permanent(self) -> None:
        """BoundedRetryPolicy retries transient failures up to max_attempts and fails fast on ValueError."""
        policy = BoundedRetryPolicy(max_attempts=3, base_delay_sec=0.001)
        counter = {"calls": 0}

        def flaky_op(attempt: int) -> str:
            counter["calls"] += 1
            if attempt < 3:
                raise RuntimeError("Transient network timeout")
            return "recovered_ok"

        result, attempts, history = policy.execute("tts_synthesis_seg_01", flaky_op)
        self.assertEqual(result, "recovered_ok")
        self.assertEqual(attempts, 3)
        self.assertEqual(len(history), 3)

        # Permanent error does not loop
        perm_calls = {"calls": 0}

        def broken_config(attempt: int) -> None:
            perm_calls["calls"] += 1
            raise ValueError("Invalid configuration schema")

        with self.assertRaises(ValueError):
            policy.execute("bad_op", broken_config)
        self.assertEqual(perm_calls["calls"], 1)

    def test_04_resource_monitor_and_disk_circuit_breaker(self) -> None:
        """ResourceMonitor captures RSS/VRAM/Disk telemetry and trips circuit breaker when disk threshold exceeded."""
        with tempfile.TemporaryDirectory() as tmp:
            mon = ResourceMonitor(Path(tmp), min_free_disk_mb=1.0)
            snap = mon.capture_snapshot("stage_01_start")
            self.assertGreater(snap["disk_free_mb"], 1.0)
            stability = mon.analyze_stability()
            self.assertEqual(stability["status"], "PASS")
            self.assertFalse(stability["memory_leak_detected"])

            # Unrealistically high threshold trips DiskSpaceCircuitBreakerError
            strict_mon = ResourceMonitor(Path(tmp), min_free_disk_mb=1e12)
            with self.assertRaises(DiskSpaceCircuitBreakerError):
                strict_mon.capture_snapshot("impossible_disk_requirement")

    def test_05_model_lifecycle_prevents_simultaneous_heavy_models(self) -> None:
        """ModelLifecycleManager unloads ASR before loading Diarization to protect 4GB VRAM."""
        mgr = ModelLifecycleManager()
        mgr.acquire_model("faster-whisper-large-v3", device="cpu")
        self.assertEqual(list(mgr.active_models.keys()), ["faster-whisper-large-v3"])

        mgr.acquire_model("pyannote-community-1", device="cpu")
        self.assertEqual(list(mgr.active_models.keys()), ["pyannote-community-1"])
        self.assertEqual(len(mgr.lifecycle_log), 3)  # acquire ASR, release ASR, acquire pyannote

    def test_06_secret_redaction_in_structured_audit_logger(self) -> None:
        """StructuredAuditLogger strips HF tokens, API keys, and Bearer tokens before writing."""
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "audit.jsonl"
            logger = StructuredAuditLogger(log_path)
            entry = logger.log(
                stage="speaker_diarization_reconciliation",
                event_type="auth_check",
                details={
                    "hf_token": "hf_" + "x" * 34,
                    "nested": {"api_key": "sk-1234567890abcdef"},
                    "message": "Using token hf_secret9876543210abc and Bearer eyJhbGciOiJIUzI1NiJ9",
                },
            )
            self.assertEqual(entry["details"]["hf_token"], "[REDACTED]")
            self.assertEqual(entry["details"]["nested"]["api_key"], "[REDACTED]")
            self.assertNotIn("hf_secret9876543210abc", entry["details"]["message"])
            self.assertNotIn("eyJhbGciOiJIUzI1NiJ9", entry["details"]["message"])


if __name__ == "__main__":
    unittest.main()
