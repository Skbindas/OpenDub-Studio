"""OpenDub Studio Phase 19: Reliability, Pre-flight Checks, and Support Bundle Packaging."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .system_diagnostics import collect_diagnostics

logger = logging.getLogger(__name__)

# Minimum free disk space thresholds (in bytes)
MIN_DISK_SPACE_UPLOAD = 500 * 1024 * 1024       # 500 MB
MIN_DISK_SPACE_SEPARATION = 1024 * 1024 * 1024   # 1 GB
MIN_DISK_SPACE_TTS = 250 * 1024 * 1024          # 250 MB
MIN_DISK_SPACE_RENDER = 500 * 1024 * 1024       # 500 MB


class InsufficientDiskSpaceError(RuntimeError):
    """Raised when available disk space is below safety threshold."""
    pass


class InvalidMediaError(RuntimeError):
    """Raised when an uploaded media file is corrupt or unreadable by ffprobe."""
    pass


def check_disk_space(target_path: Path, min_bytes: int = MIN_DISK_SPACE_UPLOAD) -> dict[str, Any]:
    """Check available disk space for target path.
    
    Raises InsufficientDiskSpaceError if free space < min_bytes.
    """
    check_dir = target_path if target_path.exists() else target_path.parent
    if not check_dir.exists():
        check_dir = Path(".")
    
    try:
        usage = shutil.disk_usage(check_dir)
        free_bytes = usage.free
        if free_bytes < min_bytes:
            req_mb = min_bytes // (1024 * 1024)
            free_mb = free_bytes // (1024 * 1024)
            raise InsufficientDiskSpaceError(
                f"Insufficient disk space on {check_dir.resolve()}: {free_mb} MB available, "
                f"minimum required is {req_mb} MB."
            )
        return {
            "ok": True,
            "path": str(check_dir.resolve()),
            "total_bytes": usage.total,
            "free_bytes": usage.free,
            "used_bytes": usage.used,
            "required_bytes": min_bytes,
        }
    except OSError as exc:
        logger.warning("Failed to query disk usage on %s: %s", check_dir, exc)
        return {"ok": True, "path": str(check_dir), "warning": str(exc)}


def validate_media_file(file_path: Path) -> dict[str, Any]:
    """Validate media file existence and container integrity via ffprobe.
    
    Raises InvalidMediaError if probe fails or no streams found.
    """
    if not file_path.exists() or file_path.stat().st_size == 0:
        raise InvalidMediaError(f"Media file does not exist or is 0 bytes: {file_path}")
    
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration,size,format_name:stream=index,codec_type,codec_name,duration,channels,sample_rate",
        "-of", "json",
        str(file_path),
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        data = json.loads(res.stdout or "{}")
        streams = data.get("streams", [])
        if not streams:
            raise InvalidMediaError(f"No media streams detected in {file_path.name}")
        return {
            "ok": True,
            "format": data.get("format", {}),
            "stream_count": len(streams),
            "has_video": any(s.get("codec_type") == "video" for s in streams),
            "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        }
    except subprocess.CalledProcessError as exc:
        raise InvalidMediaError(f"ffprobe failed on {file_path.name}: {exc.stderr.strip()}") from exc
    except json.JSONDecodeError as exc:
        raise InvalidMediaError(f"Invalid ffprobe JSON output for {file_path.name}: {exc}") from exc


def migrate_dialogue_manifest(manifest_data: dict[str, Any]) -> dict[str, Any]:
    """Ensure manifest adheres to canonical v1 schema with backwards compatibility.
    
    Upgrades older unversioned or partial manifests to include required fields:
    version, units, prosody metadata, character mapping, and timing budgets.
    """
    migrated = dict(manifest_data)
    current_version = migrated.get("version", "0.9.0")
    migrated["version"] = "1.0.0"
    migrated["migrated_from"] = current_version
    migrated["migrated_at"] = datetime.now(timezone.utc).isoformat()
    
    units = migrated.get("units", [])
    migrated_units = []
    for idx, u in enumerate(units):
        unit = dict(u)
        unit.setdefault("unit_id", f"unit_{idx:04d}")
        unit.setdefault("character_id", f"char_{idx:02d}")
        unit.setdefault("character_name", f"Character {idx + 1}")
        unit.setdefault("source_text", "")
        unit.setdefault("target_text", "")
        unit.setdefault("start_sec", 0.0)
        unit.setdefault("end_sec", 0.0)
        unit.setdefault("duration_sec", max(0.0, float(unit.get("end_sec", 0.0)) - float(unit.get("start_sec", 0.0))))
        unit.setdefault("prosody", {
            "emotion": "neutral",
            "intensity": 0.5,
            "pace": 1.0,
            "pitch_shift": 0.0,
        })
        unit.setdefault("timing_budget", {
            "max_words": max(1, int(float(unit.get("duration_sec", 2.0)) * 2.5)),
            "target_wps": 2.2,
        })
        migrated_units.append(unit)
    
    migrated["units"] = migrated_units
    return migrated


def generate_support_bundle(
    data_root: Path,
    db_path: Path,
    app_version: str = "unknown",
) -> dict[str, Any]:
    """Generate a sanitized, copyable/downloadable support diagnostics bundle.
    
    Excludes private API keys (HF_TOKEN, etc.), secrets, and raw dialogue text,
    while capturing environment, hardware, project statistics, and recent job outcomes.
    """
    diag = collect_diagnostics(data_root, app_version)
    
    # Query database for aggregate project and worker stats without sensitive payloads
    project_stats = []
    job_stats = []
    if db_path.exists():
        import sqlite3
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Aggregate project info
            projects = cursor.execute(
                "SELECT id, name, status, source_size, duration_ms, source_language, target_language, created_at FROM projects"
            ).fetchall()
            for p in projects:
                project_stats.append({
                    "id": p["id"],
                    "name": p["name"],
                    "status": p["status"],
                    "source_size_bytes": p["source_size"],
                    "duration_ms": p["duration_ms"],
                    "source_language": p["source_language"],
                    "target_language": p["target_language"],
                    "created_at": p["created_at"],
                })
            
            # Recent jobs (limit 50)
            jobs = cursor.execute(
                "SELECT id, project_id, kind, status, message, created_at, updated_at FROM jobs ORDER BY created_at DESC LIMIT 50"
            ).fetchall()
            for j in jobs:
                job_stats.append({
                    "id": j["id"],
                    "project_id": j["project_id"],
                    "kind": j["kind"],
                    "status": j["status"],
                    "message": j["message"],
                    "created_at": j["created_at"],
                    "updated_at": j["updated_at"],
                })
            conn.close()
        except Exception as exc:
            logger.warning("Failed to collect database stats for support bundle: %s", exc)
    
    return {
        "support_bundle_version": "1.0.0",
        "bundle_id": str(uuid.uuid4()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "app": diag.get("app", {}),
        "system": diag.get("system", {}),
        "python": diag.get("python", {}),
        "ffmpeg": diag.get("ffmpeg", {}),
        "ffprobe": diag.get("ffprobe", {}),
        "gpu": diag.get("gpu", {}),
        "memory": diag.get("memory", {}),
        "disk": diag.get("disk", {}),
        "optional_modules": diag.get("optional_modules", {}),
        "integrations": {
            "huggingface_configured": diag.get("integrations", {}).get("huggingface_token_configured", False),
            "diarization_installed": diag.get("integrations", {}).get("diarization_runtime_installed", False),
            "diarization_ready": diag.get("integrations", {}).get("diarization_ready", False),
        },
        "stats": {
            "total_projects": len(project_stats),
            "total_recent_jobs": len(job_stats),
            "projects": project_stats,
            "recent_jobs": job_stats,
        },
    }
