from __future__ import annotations

import json

import pytest

from backend.pipeline import build_dialogue_manifest, find_dialogue_manifest_unit, update_dialogue_manifest_tts
from backend.voice_profiles import VoiceProfileError, normalize_voice_profile, resolve_character_voice


def test_profile_normalizes_legacy_piper_engine_and_model_path():
    profile = normalize_voice_profile({"engine": "piper", "model_path": "voices/hi.onnx", "settings": {"length_scale": 1.0}})
    assert profile["schema_version"] == 1
    assert profile["provider"] == "piper"
    assert profile["model_path"] == "voices/hi.onnx"
    assert profile["status"] == "configured"
    assert "engine" not in profile


def test_profile_rejects_credentials_recursively():
    with pytest.raises(VoiceProfileError, match="Credentials are not allowed"):
        normalize_voice_profile({"provider": "custom", "settings": {"api_key": "do-not-store"}})


def test_profile_rejects_invalid_speaker_id_setting():
    with pytest.raises(VoiceProfileError, match="speaker_id must be a non-negative integer"):
        normalize_voice_profile({"provider": "piper", "model_path": "voices/hi.onnx", "settings": {"speaker_id": -1}})
def test_profile_rejects_unknown_provider():
    with pytest.raises(VoiceProfileError, match="provider must be one of"):
        normalize_voice_profile({"provider": "unlisted-provider"})


def test_dialogue_manifest_resolves_same_character_voice_for_each_unit(tmp_path):
    registry = {
        "speaker_links": {"SPEAKER_00": "character-a"},
        "characters": [{
            "character_id": "character-a",
            "display_name": "Lead",
            "voice_profile": {"provider": "piper", "model_path": "voices/lead.onnx"},
        }],
    }
    transcript = {"language": "en", "segments": [
        {"start": 0.0, "end": 1.0, "speaker_id": "SPEAKER_00", "text": "Hello"},
        {"start": 2.0, "end": 3.0, "speaker_id": "SPEAKER_00", "text": "Again"},
    ]}
    manifest = build_dialogue_manifest(
        project_id="test-project",
        transcript=transcript,
        scenes=[],
        registry=registry,
        output_path=tmp_path / "dialogue_manifest.json",
        target_language="Hindi",
    )
    voices = [unit["voice"] for unit in manifest["units"]]
    assert len(voices) == 2
    assert all(voice["status"] == "configured" for voice in voices)
    assert all(voice["character_id"] == "character-a" for voice in voices)
    assert all(voice["profile"]["model_path"] == "voices/lead.onnx" for voice in voices)
    assert all(unit["prosody"]["review_required"] for unit in manifest["units"])
    persisted = json.loads((tmp_path / "dialogue_manifest.json").read_text(encoding="utf-8"))
    assert persisted["segment_count"] == 2


def test_unassigned_character_has_pending_voice():
    assert resolve_character_voice(None) == {"status": "pending", "character_id": None, "profile": None}


@pytest.mark.parametrize("speaker_id", [True, False, "2", 1.5])
def test_profile_rejects_non_integer_speaker_id_setting(speaker_id):
    with pytest.raises(VoiceProfileError, match="speaker_id must be a non-negative integer"):
        normalize_voice_profile({"provider": "piper", "model_path": "voices/hi.onnx", "settings": {"speaker_id": speaker_id}})


def test_profile_accepts_zero_speaker_id_setting():
    profile = normalize_voice_profile({"provider": "piper", "model_path": "voices/hi.onnx", "settings": {"speaker_id": 0}})
    assert profile["settings"]["speaker_id"] == 0


@pytest.mark.parametrize("units, expected", [
    ([{"segment_index": 1, "character_id": "second"}, {"segment_index": 0, "character_id": "first"}], "first"),
    ([{"segment_index": True, "character_id": "bool-index"}], None),
    ([{"segment_index": "0", "character_id": "string-index"}], None),
    ([], None),
])
def test_manifest_unit_lookup_uses_explicit_integer_segment_index(units, expected):
    unit = find_dialogue_manifest_unit({"units": units}, 0)
    assert (unit or {}).get("character_id") == expected


def test_tts_status_persists_success_and_failure_on_matching_manifest_unit(tmp_path):
    path = tmp_path / "dialogue_manifest.json"
    path.write_text(json.dumps({"units": [
        {"segment_index": 1, "tts": {"status": "pending"}},
        {"segment_index": 0, "tts": {"status": "pending"}},
    ]}), encoding="utf-8")

    update_dialogue_manifest_tts(
        manifest_path=path, segment_index=0, status="completed",
        audio_path="segments/segment_000000_dub.wav", duration_sec=2.4,
    )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["units"][1]["tts"]["status"] == "completed"
    assert manifest["units"][1]["tts"]["duration_sec"] == 2.4
    assert manifest["units"][0]["tts"]["status"] == "pending"

    update_dialogue_manifest_tts(manifest_path=path, segment_index=0, status="error", error="Piper failed")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["units"][1]["tts"]["status"] == "error"
    assert manifest["units"][1]["tts"]["error"] == "Piper failed"
    assert manifest["units"][1]["tts"]["audio_path"] is None


@pytest.mark.parametrize("status", ["success", "failed", "unknown"])
def test_tts_manifest_rejects_unsupported_status(tmp_path, status):
    path = tmp_path / "dialogue_manifest.json"
    path.write_text(json.dumps({"units": [{"segment_index": 0}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported TTS status"):
        update_dialogue_manifest_tts(manifest_path=path, segment_index=0, status=status)


def test_tts_manifest_rejects_negative_duration(tmp_path):
    path = tmp_path / "dialogue_manifest.json"
    path.write_text(json.dumps({"units": [{"segment_index": 0}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="duration_sec must be non-negative"):
        update_dialogue_manifest_tts(
            manifest_path=path, segment_index=0, status="completed", duration_sec=-0.1,
        )


def test_tts_manifest_records_running_state_without_stale_audio(tmp_path):
    path = tmp_path / "dialogue_manifest.json"
    path.write_text(json.dumps({"units": [{"segment_index": 0, "tts": {
        "status": "completed", "audio_path": "old.wav", "duration_sec": 3.0,
    }}]}), encoding="utf-8")
    update_dialogue_manifest_tts(manifest_path=path, segment_index=0, status="running")
    unit = json.loads(path.read_text(encoding="utf-8"))["units"][0]
    assert unit["tts"]["status"] == "running"
    assert unit["tts"]["audio_path"] is None
    assert unit["tts"]["duration_sec"] is None
    assert unit["tts"]["error"] is None
