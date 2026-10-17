from contextlib import nullcontext
import importlib.util
import json
from pathlib import Path
import sys

from backend.voice_bank_quality import fingerprint


def test_batch_retains_accepted_audition_and_tracks_unsafe_reference(tmp_path,monkeypatch):
    scripts=Path(__file__).resolve().parents[1]/"scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec=importlib.util.spec_from_file_location("bank_batch_test",scripts/"clone_voice_batch_worker.py")
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module,"ROOT",tmp_path)
    monkeypatch.setattr(module,"clone_worker_slot",nullcontext)
    folder=tmp_path/"runtime/voice-bank-audit"
    (folder/"records").mkdir(parents=True)
    (folder/"clones").mkdir()
    reference=tmp_path/"reference.wav"
    reference.write_bytes(b"unchanged reference")
    output=folder/"clones/accepted.wav"
    output.write_bytes(b"accepted audition")
    record={"voice_id":"accepted","sha256":fingerprint(reference),"reference_path":str(reference),
            "audit":{"status":"single_speaker_candidate","speech_text":"words"},"metrics":{"duration_sec":8},
            "clone":{"status":"completed","output_sha256":fingerprint(output),
                     "reference_sha256":fingerprint(reference),"ref_text":"words"}}
    (folder/"records/accepted.json").write_text(json.dumps(record))
    unsafe={**record,"voice_id":"unsafe","clone":{},"metrics":{"duration_sec":12}}
    (folder/"records/unsafe.json").write_text(json.dumps(unsafe))
    def forbidden_generation(_):
        raise AssertionError("Accepted/unsafe references must not be regenerated")
    monkeypatch.setattr(module,"generate",forbidden_generation)
    module.main()
    report=json.loads((folder/"batch-progress.json").read_text())
    assert report["retained"]==["accepted"]
    assert report["requires_reference_repair"]==["unsafe"]
    assert report["failed"]==[]
    assert output.read_bytes()==b"accepted audition"
