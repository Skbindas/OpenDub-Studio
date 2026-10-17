"""Unit and integration tests for Phase 19: Reliability, Pre-flight Checks, and Support Bundle."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app import app, DB_PATH
from backend.reliability import (
    InsufficientDiskSpaceError,
    InvalidMediaError,
    check_disk_space,
    generate_support_bundle,
    migrate_dialogue_manifest,
    validate_media_file,
)


@pytest.fixture
def client():
    return TestClient(app)


def test_check_disk_space_success(tmp_path: Path):
    # With a small requirement (1 KB), it should pass on any active disk
    result = check_disk_space(tmp_path, min_bytes=1024)
    assert result["ok"] is True
    assert result["free_bytes"] >= 1024


def test_check_disk_space_failure(tmp_path: Path):
    # Mock disk_usage to return 100 bytes free
    Usage = type("Usage", (), {"total": 1000, "used": 900, "free": 100})
    with patch("shutil.disk_usage", return_value=Usage()):
        with pytest.raises(InsufficientDiskSpaceError) as exc_info:
            check_disk_space(tmp_path, min_bytes=1024 * 1024)
        assert "Insufficient disk space" in str(exc_info.value)


def test_validate_media_file_missing_and_empty(tmp_path: Path):
    missing = tmp_path / "nonexistent.mp4"
    with pytest.raises(InvalidMediaError) as exc_info:
        validate_media_file(missing)
    assert "does not exist or is 0 bytes" in str(exc_info.value)

    empty = tmp_path / "empty.mp4"
    empty.touch()
    with pytest.raises(InvalidMediaError) as exc_info:
        validate_media_file(empty)
    assert "does not exist or is 0 bytes" in str(exc_info.value)


def test_validate_media_file_valid(tmp_path: Path):
    # Create a 0.2s synthetic audio file with ffmpeg
    sample_wav = tmp_path / "sample.wav"
    import subprocess
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=1000:duration=0.2",
        "-c:a", "pcm_s16le", str(sample_wav)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    info = validate_media_file(sample_wav)
    assert info["ok"] is True
    assert info["stream_count"] >= 1
    assert info["has_audio"] is True


def test_migrate_dialogue_manifest():
    legacy_manifest = {
        "version": "0.8.0",
        "source_fingerprint": "abc12345",
        "units": [
            {
                "unit_id": "unit_0000",
                "source_text": "Hello world",
                "start_sec": 1.0,
                "end_sec": 3.0,
            }
        ]
    }

    migrated = migrate_dialogue_manifest(legacy_manifest)
    assert migrated["version"] == "1.0.0"
    assert migrated["migrated_from"] == "0.8.0"
    assert "migrated_at" in migrated
    assert len(migrated["units"]) == 1

    unit = migrated["units"][0]
    assert unit["duration_sec"] == 2.0
    assert "prosody" in unit
    assert unit["prosody"]["emotion"] == "neutral"
    assert "timing_budget" in unit
    assert unit["timing_budget"]["max_words"] >= 1


def test_generate_support_bundle(tmp_path: Path):
    data_root = tmp_path / "runtime"
    data_root.mkdir()
    db_file = data_root / "opendub.sqlite3"

    bundle = generate_support_bundle(data_root, db_file, app_version="1.0.0-test")
    assert bundle["support_bundle_version"] == "1.0.0"
    assert "bundle_id" in bundle
    assert "generated_at" in bundle
    assert bundle["app"]["version"] == "1.0.0-test"
    assert "system" in bundle
    assert "ffmpeg" in bundle
    assert "integrations" in bundle
    assert "stats" in bundle
    # Ensure no token values or secrets leaked
    raw_str = json.dumps(bundle)
    assert "hf_" not in raw_str
    assert "Bearer" not in raw_str


def test_support_bundle_api_endpoint(client: TestClient):
    res = client.get("/api/system/support-bundle")
    assert res.status_code == 200
    data = res.json()
    assert data["support_bundle_version"] == "1.0.0"
    assert "bundle_id" in data
    assert "stats" in data
    assert "system" in data
