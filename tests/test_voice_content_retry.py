from contextlib import nullcontext
import importlib.util
import json
from pathlib import Path
from backend.voice_bank_quality import fingerprint


def test_content_retry_does_not_regenerate_accepted_or_previously_retried_take(tmp_path,monkeypatch):
    scripts=Path(__file__).resolve().parents[1]/"scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec=importlib.util.spec_from_file_location("retry_test",scripts/"retry_voice_bank_content.py")
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module,"ROOT",tmp_path)
    monkeypatch.setattr(module,"clone_worker_slot",nullcontext)
    folder=tmp_path/"runtime/voice-bank-audit/records"
    folder.mkdir(parents=True)
    audio=tmp_path/"accepted.wav"
    audio.write_bytes(b"accepted audio")
    clone={"file":str(audio),"output_sha256":fingerprint(audio),"seed":42,
           "content_check":{"substantial_omission_suspected":True}}
    accepted={"voice_id":"accepted","clone":clone,"audition_acceptance":{"output_sha256":fingerprint(audio)}}
    retried={"voice_id":"retried","clone":{**clone,"seed":43}}
    for record in (accepted,retried):
        (folder/f"{record['voice_id']}.json").write_text(json.dumps(record))
    def forbidden(_):
        raise AssertionError("Accepted takes and bounded retries must be preserved")
    monkeypatch.setattr(module,"generate",forbidden)
    module.main()
    assert audio.read_bytes()==b"accepted audio"


def test_repaired_batch_retains_audition_after_reference_selection(tmp_path,monkeypatch):
    scripts=Path(__file__).resolve().parents[1]/"scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec=importlib.util.spec_from_file_location("repair_batch_test",scripts/"clone_repaired_bank_worker.py")
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module,"ROOT",tmp_path)
    monkeypatch.setattr(module,"clone_worker_slot",nullcontext)
    folder=tmp_path/"runtime/voice-bank-audit"
    (folder/"records").mkdir(parents=True)
    version=folder/"repairs/voice/version"
    version.mkdir(parents=True)
    reference=version/"speaker.wav"
    reference.write_bytes(b"selected reference")
    output=version/"speaker-clone.wav"
    output.write_bytes(b"retained genuine audition")
    candidate={"speaker_id":"speaker","path":str(reference),"audit":{"status":"single_speaker_candidate","speech_text":"reference text"},
               "clone":{"status":"completed","output_sha256":fingerprint(output),"reference_sha256":fingerprint(reference),"ref_text":"reference text"}}
    (folder/"records/voice.json").write_text(json.dumps({"sha256":fingerprint(reference),"catalog_reference_sha256":"original"}))
    (version/"repair.json").write_text(json.dumps({"voice_id":"voice","original_sha256":"original","repairs":[candidate]}))
    def forbidden(_):
        raise AssertionError("Selected repaired auditions must be reused")
    monkeypatch.setattr(module,"generate",forbidden)
    module.main()
    progress=json.loads((folder/"repaired-clone-progress.json").read_text())
    assert progress["retained"]==["voice/version/speaker"]
    assert not progress["completed"]
