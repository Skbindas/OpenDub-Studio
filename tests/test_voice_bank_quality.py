from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pytest
import soundfile as sf

from backend.voice_bank_quality import (classify_reference, exclusive_windows, audio_metrics,
    fingerprint, reviewed_eligibility, promote_defaults)


def test_instrumental_or_silent_reference_is_not_a_verified_clone():
    result = classify_reference({"rms_dbfs":-20,"duration_sec":8}, {"segments":[]}, {"turns":[]})
    assert result["status"] == "rejected_no_speech"
    assert result["eligible_for_defaults"] is False


def test_metadata_cannot_prove_single_speaker():
    result = classify_reference({"rms_dbfs":-20,"duration_sec":8}, None, None)
    assert result["status"] == "needs_review"


def test_two_sequential_speakers_require_split():
    result = classify_reference({"rms_dbfs":-20,"duration_sec":8},
        {"segments":[{"text":"Hindi speech"}]}, {"turns":[{"speaker_id":"a","start":0,"end":4},
        {"speaker_id":"b","start":4,"end":8}]})
    assert result["status"] == "multiple_speakers"
    assert result["speaker_count_detected"] == 2


def test_simultaneous_speakers_never_become_a_single_crop():
    turns = [{"speaker_id":"a","start":0,"end":10}, {"speaker_id":"b","start":2,"end":8}]
    assert exclusive_windows(turns,"a") == []
    result = classify_reference({"duration_sec":10}, {"segments":[{"text":"words"}]}, {"turns":turns})
    assert result["status"] == "overlapping_speakers"


def test_split_keeps_source_boundaries_and_limits_reference_duration():
    turns = [{"speaker_id":"a","start":0,"end":15}, {"speaker_id":"b","start":10,"end":15}]
    assert exclusive_windows(turns,"a") == [{"start":0,"end":10,"speaker_id":"a"}]


def test_same_speaker_natural_pauses_are_kept_without_other_speakers():
    turns=[{"speaker_id":"a","start":1.8,"end":3.9},
           {"speaker_id":"a","start":4.4,"end":5.7},
           {"speaker_id":"a","start":6.2,"end":7},
           {"speaker_id":"a","start":8.2,"end":10.4}]
    assert exclusive_windows(turns,"a")==[{"start":1.8,"end":10.4,"speaker_id":"a"}]
    turns.append({"speaker_id":"b","start":4,"end":4.3})
    windows=exclusive_windows(turns,"a")
    assert all(not (window["start"]<4.3 and window["end"]>4) for window in windows)


def test_fixed_synthetic_tone_is_rejected(tmp_path):
    path = tmp_path/"tone.wav"
    time = np.arange(24000*3)/24000
    sf.write(path,np.sin(2*np.pi*130*time)*.2,24000)
    metrics = audio_metrics(path)
    assert metrics["fixed_tone_suspected"]
    assert classify_reference(metrics,None,None)["status"] == "rejected_non_speech"


def verified_record(tmp_path):
    reference, output = tmp_path/"ref.wav",tmp_path/"clone.wav"
    reference.write_bytes(b"reference")
    output.write_bytes(b"real generation")
    return {"voice_id":"voice", "reference_path":str(reference), "sha256":fingerprint(reference),
            "audit":{"status":"single_speaker_candidate","speech_text":"reference words"},
            "metrics":{"duration_sec":8,"clipped_fraction":0,"fixed_tone_suspected":False},
            "review":{key:True for key in ("single_speaker","speech_present","background_clean","identity_confirmed","clone_identity_passed","naturalness_passed","dialogue_content_passed")},
            "clone":{"status":"completed","reference_conditioned":True,"ref_text":"reference words",
                     "reference_sha256":fingerprint(reference),"file":str(output),"output_sha256":fingerprint(output)}}


def test_promotion_is_atomic_and_requires_every_target_voice(tmp_path):
    record = verified_record(tmp_path)
    destination = tmp_path/"active.json"
    destination.write_text('{"old":true}')
    with pytest.raises(ValueError,match="blocked"):
        promote_defaults([record],{"voice","missing"},destination)
    assert json.loads(destination.read_text()) == {"old":True}
    result = promote_defaults([record],{"voice"},destination)
    assert result["legacy_defaults_active"] is False


def test_reference_or_transcript_change_requires_fresh_clone_review(tmp_path):
    record = verified_record(tmp_path)
    assert reviewed_eligibility(record)[0]
    record["audit"]["speech_text"] = "different words"
    assert "clone_reference_transcript_mismatch" in reviewed_eligibility(record)[1]
    Path(record["reference_path"]).write_bytes(b"changed reference")
    assert "reference_missing_or_changed" in reviewed_eligibility(record)[1]


def test_missing_clone_runtime_never_substitutes_a_stock_voice(tmp_path, monkeypatch):
    from backend import clone_runtime
    monkeypatch.setenv("OPENDUB_CLONE_PYTHON",str(tmp_path/"missing-python"))
    reference = tmp_path/"ref.wav"
    reference.write_bytes(b"reference")
    output = tmp_path/"existing.wav"
    output.write_bytes(b"keep previous output")
    with pytest.raises(RuntimeError,match="unavailable"):
        clone_runtime.synthesize_reference("target",reference,"words",output)
    assert output.read_bytes() == b"keep previous output"


def test_manual_checkboxes_cannot_promote_mixed_or_oversized_reference(tmp_path):
    record = verified_record(tmp_path)
    record["audit"]["status"] = "multiple_speakers"
    assert not reviewed_eligibility(record)[0]
    record["audit"]["status"] = "single_speaker_candidate"
    record["metrics"]["duration_sec"] = 12
    assert not reviewed_eligibility(record)[0]


def test_second_clone_worker_is_rejected_without_stale_lock(monkeypatch, tmp_path):
    from backend import clone_runtime
    monkeypatch.setattr(clone_runtime,"ROOT",tmp_path)
    with clone_runtime.clone_worker_slot():
        with pytest.raises(RuntimeError,match="Another clone worker"):
            with clone_runtime.clone_worker_slot():
                pytest.fail("concurrent worker acquired the same slot")
    with clone_runtime.clone_worker_slot():
        pass


def test_selecting_repair_retains_original_and_invalidates_old_review(tmp_path):
    from backend.voice_bank_quality import select_repaired_reference
    original=verified_record(tmp_path)
    reference, output=tmp_path/"repaired.wav",tmp_path/"repaired-clone.wav"
    reference.write_bytes(b"new exclusive speaker")
    output.write_bytes(b"new audition")
    candidate={"path":str(reference),"sha256":fingerprint(reference),
               "audit":{"status":"single_speaker_candidate","speech_text":"new reference words"},
               "metrics":{"duration_sec":8},
               "clone":{"status":"completed","reference_conditioned":True,"file":str(output),
                        "output_sha256":fingerprint(output),"reference_sha256":fingerprint(reference),
                        "ref_text":"new reference words"}}
    selected=select_repaired_reference(original,candidate)
    assert selected["reference_path"]==str(reference)
    assert selected["catalog_reference_sha256"]==original["sha256"]
    assert selected["reference_history"][0]["reference_path"]==original["reference_path"]
    assert selected["review"]=={}
    assert Path(original["reference_path"]).read_bytes()==b"reference"
    output.write_bytes(b"changed output")
    with pytest.raises(ValueError,match="changed"):
        select_repaired_reference(original,candidate)
    assert original["review"]["background_clean"] is True
