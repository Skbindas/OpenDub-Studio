"""Phase 27: Long-Form Runtime Architecture, Checkpointing, Resume & Resource Manager.

Implements PRD Section 15, Section 16, Section 17 & Section 28:
1. Atomic stage-level and segment-level checkpointing across all 12 pipeline stages
   with SHA-256 input/output hash verification and atomic .tmp file replacement.
2. Deterministic resume verification: skips valid completed units and re-executes
   only missing, corrupted, or hash-invalidated units.
3. Bounded retry policy with exponential backoff and error classification.
4. Resource & VRAM monitor (CPU, RAM RSS, GPU VRAM via torch/nvidia-smi, disk free space)
   with minimum free-disk circuit breaker and monotonic memory growth leak detector.
5. Model lifecycle manager preventing simultaneous heavy model residency on 4GB VRAM GPUs.
6. Secret-redacting structured audit logger.
"""
from __future__ import annotations

import gc
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


PIPELINE_STAGES: tuple[str, ...] = (
    "source_ingestion_probe",
    "audio_extraction",
    "vocal_accompaniment_separation",
    "asr_transcription",
    "speaker_diarization_reconciliation",
    "character_registry_voice_locking",
    "translation_semantic_adaptation",
    "emotion_prosody_planning",
    "segment_tts_synthesis",
    "segment_duration_fitting",
    "scene_full_timeline_mixing",
    "final_video_mux_qa_audit",
)

_SECRET_PATTERNS = (
    re.compile(r"(hf_[A-Za-z0-9]{10,})"),
    re.compile(r"(sk-[A-Za-z0-9_\-]{12,})"),
    re.compile(r"(Bearer\s+[A-Za-z0-9_\-\.]+)", re.IGNORECASE),
)
_SECRET_KEY_NAMES = {
    "hf_token", "api_key", "apikey", "secret", "password", "access_token", "authorization", "token"
}


class DiskSpaceCircuitBreakerError(RuntimeError):
    """Raised when available disk space drops below the safety threshold."""


class CheckpointIntegrityError(RuntimeError):
    """Raised when a checkpoint or output artifact fails integrity verification."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Stream-compute SHA-256 of a file without loading the full file into RAM."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def sha256_json(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def atomic_write_bytes(target_path: Path, data: bytes) -> Path:
    """Write bytes to a .tmp sibling file and atomically replace target_path (PRD §15.3)."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_suffix(target_path.suffix + ".tmp")
    with tmp_path.open("wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, target_path)
    return target_path


def atomic_write_json(target_path: Path, payload: Any) -> Path:
    """Atomically write formatted JSON via a .tmp file and os.replace."""
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    return atomic_write_bytes(target_path, text.encode("utf-8"))


def redact_secrets(value: Any) -> Any:
    """Recursively redact tokens, API keys, and credentials from logs/reports (PRD §22)."""
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for k, v in value.items():
            k_norm = str(k).strip().lower().replace("-", "_")
            if k_norm in _SECRET_KEY_NAMES or any(s in k_norm for s in ("token", "secret", "password", "api_key")):
                cleaned[k] = "[REDACTED]"
            else:
                cleaned[k] = redact_secrets(v)
        return cleaned
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str):
        out = value
        for pat in _SECRET_PATTERNS:
            out = pat.sub("[REDACTED_SECRET]", out)
        return out
    return value


class CheckpointManager:
    """Manages stage-level and unit-level checkpoints with SHA-256 verification (PRD §15)."""

    def __init__(self, project_id: str, checkpoint_dir: Path, phase: int = 27) -> None:
        self.project_id = str(project_id)
        self.checkpoint_dir = Path(checkpoint_dir)
        self.phase = int(phase)
        self.manifest_path = self.checkpoint_dir / "checkpoint_manifest.json"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, dict[str, Any]] = {}
        self._load()

    @staticmethod
    def _make_key(stage: str, unit_id: str) -> str:
        return f"{stage}::{unit_id}"

    def _load(self) -> None:
        if not self.manifest_path.exists():
            self._records = {}
            return
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            items = data.get("checkpoints", [])
            self._records = {
                self._make_key(str(item["stage"]), str(item["unit_id"])): item
                for item in items
                if isinstance(item, dict) and "stage" in item and "unit_id" in item
            }
        except Exception:
            self._records = {}

    def save_manifest(self) -> Path:
        payload = {
            "project_id": self.project_id,
            "phase": self.phase,
            "updated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "checkpoint_count": len(self._records),
            "checkpoints": [self._records[k] for k in sorted(self._records.keys())],
        }
        return atomic_write_json(self.manifest_path, payload)

    def record_checkpoint(
        self,
        stage: str,
        unit_id: str,
        input_hash: str,
        output_path: Path,
        duration_sec: float = 0.0,
        attempt: int = 1,
        status: str = "completed",
        base_dir: Path | None = None,
    ) -> dict[str, Any]:
        """Record a verified checkpoint per PRD §15.2 schema."""
        if stage not in PIPELINE_STAGES:
            raise ValueError(f"Unknown pipeline stage: {stage}")
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise CheckpointIntegrityError(f"Cannot checkpoint missing or empty output file: {output_path}")

        out_hash = sha256_file(output_path)
        rel_path = (
            str(output_path.relative_to(base_dir)).replace("\\", "/")
            if base_dir and output_path.is_relative_to(base_dir)
            else str(output_path).replace("\\", "/")
        )
        entry = {
            "project_id": self.project_id,
            "phase": self.phase,
            "stage": stage,
            "unit_id": str(unit_id),
            "status": status,
            "input_hash": str(input_hash),
            "output_path": rel_path,
            "output_hash": out_hash,
            "duration_sec": round(float(duration_sec), 3),
            "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "attempt": int(attempt),
        }
        key = self._make_key(stage, str(unit_id))
        self._records[key] = entry
        self.save_manifest()
        return entry

    def is_unit_valid(
        self,
        stage: str,
        unit_id: str,
        expected_input_hash: str,
        base_dir: Path | None = None,
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """Verify whether a stage/unit can be skipped on resume per PRD §15.3."""
        key = self._make_key(stage, str(unit_id))
        rec = self._records.get(key)
        if not rec:
            return False, "missing_checkpoint", None
        if rec.get("status") != "completed":
            return False, f"checkpoint_status_{rec.get('status')}", rec
        if str(rec.get("input_hash")) != str(expected_input_hash):
            return False, "input_hash_changed", rec

        raw_out = str(rec.get("output_path") or "")
        out_path = (base_dir / raw_out) if (base_dir and not Path(raw_out).is_absolute()) else Path(raw_out)

        # Reject leftover .tmp artifacts or missing output
        tmp_sibling = out_path.with_suffix(out_path.suffix + ".tmp")
        if tmp_sibling.exists():
            try:
                tmp_sibling.unlink()
            except OSError:
                pass

        if not out_path.exists():
            return False, "output_file_missing", rec
        if out_path.stat().st_size == 0:
            return False, "output_file_empty", rec

        actual_out_hash = sha256_file(out_path)
        if actual_out_hash != str(rec.get("output_hash")):
            return False, "output_hash_mismatch", rec

        return True, "verified_reusable", rec

    def cleanup_stale_tmp_files(self, search_dir: Path) -> list[str]:
        """Remove any interrupted .tmp files left behind by a killed process."""
        removed: list[str] = []
        if not search_dir.exists():
            return removed
        for tmp_file in search_dir.rglob("*.tmp"):
            if tmp_file.is_file():
                try:
                    tmp_file.unlink()
                    removed.append(str(tmp_file))
                except OSError:
                    pass
        return removed


class BoundedRetryPolicy:
    """Bounded retry executor with error classification and backoff (PRD §17)."""

    def __init__(self, max_attempts: int = 3, base_delay_sec: float = 0.02) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.max_attempts = int(max_attempts)
        self.base_delay_sec = float(base_delay_sec)

    @staticmethod
    def classify_error(exc: BaseException) -> str:
        text = str(exc).lower()
        if isinstance(exc, (ValueError, KeyError, TypeError, DiskSpaceCircuitBreakerError)):
            return "permanent_error"
        if "out of memory" in text or "cuda" in text or "vram" in text:
            return "resource_exhaustion_recoverable"
        return "transient_error"

    def execute(
        self,
        operation_name: str,
        fn: Callable[[int], Any],
        on_retry: Callable[[int, BaseException, str], None] | None = None,
    ) -> tuple[Any, int, list[dict[str, Any]]]:
        """Execute fn(attempt) up to max_attempts; returns (result, attempts_used, retry_history)."""
        history: list[dict[str, Any]] = []
        last_exc: BaseException | None = None

        for attempt in range(1, self.max_attempts + 1):
            t0 = time.perf_counter()
            try:
                result = fn(attempt)
                elapsed = round(time.perf_counter() - t0, 4)
                history.append({
                    "operation": operation_name,
                    "attempt": attempt,
                    "status": "succeeded",
                    "duration_sec": elapsed,
                })
                return result, attempt, history
            except BaseException as exc:
                elapsed = round(time.perf_counter() - t0, 4)
                err_class = self.classify_error(exc)
                last_exc = exc
                history.append({
                    "operation": operation_name,
                    "attempt": attempt,
                    "status": "failed",
                    "error_class": err_class,
                    "error_type": type(exc).__name__,
                    "error_message": redact_secrets(str(exc)),
                    "duration_sec": elapsed,
                })
                if err_class == "permanent_error" or attempt >= self.max_attempts:
                    break
                if on_retry is not None:
                    on_retry(attempt, exc, err_class)
                if self.base_delay_sec > 0:
                    time.sleep(self.base_delay_sec * (2 ** (attempt - 1)))

        assert last_exc is not None
        raise last_exc


class ResourceMonitor:
    """Monitors CPU, RSS RAM, GPU VRAM, and free disk space with leak detection (PRD §16)."""

    def __init__(
        self,
        workspace_path: Path,
        min_free_disk_mb: float = 512.0,
    ) -> None:
        self.workspace_path = Path(workspace_path)
        self.min_free_disk_mb = float(min_free_disk_mb)
        self.snapshots: list[dict[str, Any]] = []

    @staticmethod
    def _read_process_rss_mb() -> float:
        # Linux /proc/self/status VmRSS
        status_file = Path("/proc/self/status")
        if status_file.exists():
            try:
                for line in status_file.read_text(encoding="utf-8").splitlines():
                    if line.startswith("VmRSS:"):
                        parts = line.split()
                        if len(parts) >= 2 and parts[1].isdigit():
                            return round(int(parts[1]) / 1024.0, 2)
            except Exception:
                pass
        try:
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return round(float(usage) / 1024.0, 2)
        except Exception:
            return 0.0

    @staticmethod
    def _read_gpu_vram_mb() -> dict[str, Any]:
        try:
            import torch
            if torch.cuda.is_available():
                free_b, total_b = torch.cuda.mem_get_info()
                used_b = total_b - free_b
                return {
                    "gpu_available": True,
                    "vram_used_mb": round(used_b / 1048576.0, 2),
                    "vram_free_mb": round(free_b / 1048576.0, 2),
                    "vram_total_mb": round(total_b / 1048576.0, 2),
                }
        except Exception:
            pass

        nvsmi = shutil.which("nvidia-smi") or (
            "/usr/bin/nvidia-smi" if Path("/usr/bin/nvidia-smi").exists() else None
        )
        if nvsmi:
            try:
                proc = subprocess.run(
                    [
                        nvsmi,
                        "--query-gpu=memory.used,memory.free,memory.total",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    first = proc.stdout.strip().splitlines()[0]
                    parts = [p.strip() for p in first.split(",")]
                    if len(parts) >= 3:
                        return {
                            "gpu_available": True,
                            "vram_used_mb": float(parts[0]),
                            "vram_free_mb": float(parts[1]),
                            "vram_total_mb": float(parts[2]),
                        }
            except Exception:
                pass

        return {
            "gpu_available": False,
            "vram_used_mb": 0.0,
            "vram_free_mb": 0.0,
            "vram_total_mb": 0.0,
        }

    def capture_snapshot(self, label: str, enforce_disk_guard: bool = True) -> dict[str, Any]:
        """Record a resource telemetry point and enforce the disk-space circuit breaker."""
        disk = shutil.disk_usage(str(self.workspace_path if self.workspace_path.exists() else Path(".")))
        free_disk_mb = round(disk.free / 1048576.0, 2)
        total_disk_mb = round(disk.total / 1048576.0, 2)
        rss_mb = self._read_process_rss_mb()
        gpu = self._read_gpu_vram_mb()

        snap = {
            "index": len(self.snapshots) + 1,
            "label": str(label),
            "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "process_rss_mb": rss_mb,
            "disk_free_mb": free_disk_mb,
            "disk_total_mb": total_disk_mb,
            **gpu,
        }
        self.snapshots.append(snap)

        if enforce_disk_guard and free_disk_mb < self.min_free_disk_mb:
            raise DiskSpaceCircuitBreakerError(
                f"Free disk space ({free_disk_mb:.1f} MB) is below safety threshold ({self.min_free_disk_mb:.1f} MB)."
            )
        return snap

    def analyze_stability(self, max_allowed_rss_growth_mb: float = 250.0) -> dict[str, Any]:
        """Evaluate whether memory usage remained bounded without runaway leaks."""
        if not self.snapshots:
            return {
                "snapshot_count": 0,
                "rss_start_mb": 0.0,
                "rss_end_mb": 0.0,
                "rss_peak_mb": 0.0,
                "rss_growth_mb": 0.0,
                "memory_leak_detected": False,
                "status": "PASS",
            }
        rss_vals = [float(s["process_rss_mb"]) for s in self.snapshots]
        start_mb = rss_vals[0]
        end_mb = rss_vals[-1]
        peak_mb = max(rss_vals)
        growth_mb = round(end_mb - start_mb, 2)

        # Check if strictly increasing across >= 5 consecutive checkpoints AND exceeds growth budget
        monotonic_steps = sum(
            1 for i in range(1, len(rss_vals)) if rss_vals[i] > rss_vals[i - 1] + 2.0
        )
        leak_detected = bool(
            growth_mb > max_allowed_rss_growth_mb
            and len(rss_vals) >= 5
            and monotonic_steps >= int(0.8 * (len(rss_vals) - 1))
        )

        return {
            "snapshot_count": len(self.snapshots),
            "rss_start_mb": start_mb,
            "rss_end_mb": end_mb,
            "rss_peak_mb": peak_mb,
            "rss_growth_mb": growth_mb,
            "vram_peak_mb": max((float(s.get("vram_used_mb", 0.0)) for s in self.snapshots), default=0.0),
            "min_disk_free_mb": min((float(s.get("disk_free_mb", 0.0)) for s in self.snapshots), default=0.0),
            "memory_leak_detected": leak_detected,
            "status": "FAIL" if leak_detected else "PASS",
        }


class ModelLifecycleManager:
    """Ensures heavy models (ASR, diarization, vocal separation) never co-reside in 4GB VRAM."""

    def __init__(self) -> None:
        self.active_models: dict[str, str] = {}
        self.lifecycle_log: list[dict[str, Any]] = []

    def acquire_model(self, model_key: str, device: str = "cpu") -> dict[str, Any]:
        # Unload any previously active heavy model before loading a new one
        for existing_key in list(self.active_models.keys()):
            if existing_key != model_key:
                self.release_model(existing_key)
        self.active_models[model_key] = device
        event = {
            "action": "acquire_model",
            "model_key": model_key,
            "device": device,
            "active_models": list(self.active_models.keys()),
            "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        self.lifecycle_log.append(event)
        return event

    def release_model(self, model_key: str) -> dict[str, Any]:
        dev = self.active_models.pop(model_key, "cpu")
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        event = {
            "action": "release_model",
            "model_key": model_key,
            "previous_device": dev,
            "active_models": list(self.active_models.keys()),
            "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        self.lifecycle_log.append(event)
        return event


class StructuredAuditLogger:
    """Secret-safe structured JSON logger for long-form pipeline execution."""

    def __init__(self, log_path: Path) -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.events: list[dict[str, Any]] = []

    def log(self, stage: str, event_type: str, details: dict[str, Any]) -> dict[str, Any]:
        safe_details = redact_secrets(details)
        entry = {
            "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "stage": str(stage),
            "event_type": str(event_type),
            "details": safe_details,
        }
        self.events.append(entry)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry
