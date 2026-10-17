import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from backend.authorized_voices import import_reference, load_authorized_voices


def audio(tmp_path, seconds=4, silent=False):
    path=tmp_path/'input.wav'
    # Signal fixture only; this does not simulate a real successful speech audit.
    samples=np.zeros(int(seconds*24000)) if silent else np.random.default_rng(2).normal(0,.05,int(seconds*24000))
    sf.write(path,samples,24000,subtype='PCM_16')
    return path


def test_intake_requires_explicit_permission_and_single_speaker_confirmation(tmp_path):
    path=audio(tmp_path)
    for permission,single in [(False,True),(True,False)]:
        with pytest.raises(ValueError):
            import_reference(tmp_path/'data',path,'My voice','नमस्ते।',permission,single,True)
    assert not list((tmp_path/'data').glob('**/*.json'))


@pytest.mark.parametrize('seconds,silent',[(1,False),(11,False),(4,True)])
def test_invalid_engine_window_or_silence_is_rejected(tmp_path,seconds,silent):
    with pytest.raises(ValueError):
        import_reference(tmp_path/'data',audio(tmp_path,seconds,silent),'My voice','नमस्ते।',True,True,True)


def test_import_preserves_source_and_does_not_fabricate_model_or_clone_review(tmp_path):
    path=audio(tmp_path);before=path.read_bytes();root=tmp_path/'data'
    first=import_reference(root,path,'My own voice','नमस्ते।',True,True,True)
    second=import_reference(root,path,'Another take','नमस्ते।',True,True,True)
    assert first['voice_id']!=second['voice_id']
    assert path.read_bytes()==before==Path(first['reference_path']).read_bytes()
    assert first['audit']['method']=='user_reviewed_upload'
    assert first['audit'].get('speaker_count_detected') is None
    assert first['clone']['status']=='not_tested'
    assert not first['review'].get('clone_identity_passed')
    assert not first['eligible_for_defaults']
    assert first['permissions']['public_distribution_verified'] is False
    assert len(load_authorized_voices(root))==2


def test_changed_reference_is_not_loaded_as_usable(tmp_path):
    root=tmp_path/'data';row=import_reference(root,audio(tmp_path),'My voice','Hello',True,True,True)
    Path(row['reference_path']).write_bytes(b'changed')
    assert load_authorized_voices(root)==[]


def test_upload_preview_and_casting_distinguish_reference_from_uncreated_clone(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend import app as studio, automatic_dialogue
    root=tmp_path/'data'
    monkeypatch.setenv('OPENDUB_DATA_DIR',str(root))
    monkeypatch.setattr(studio,'DATA_ROOT',root)
    monkeypatch.setattr(automatic_dialogue,'automatic_reference_candidates',lambda root: [])
    client=TestClient(studio.app)
    raw=audio(tmp_path).read_bytes()
    response=client.post('/api/voices/import',files={'file':('../../my.wav',raw,'audio/wav')},
                         data={'name':'My recording','transcript':'Hello there',
                               'permission':'on','single_speaker':'on','clean_background':'on'})
    assert response.status_code==200,response.text
    receipt=response.json();vid=receipt['voice_id']
    assert not receipt['eligible_for_defaults']
    assert client.get(receipt['audio_url']).content==raw
    bank=client.get('/api/voices/bank').json()
    assert next(v for v in bank['voices'] if v['character_id']==vid)['display_name']=='My recording'
    casting=client.get('/api/casting-voices').json()
    choice=next(v for v in casting['voices'] if v['voice_id']==vid)
    assert choice['audition_kind']=='reference_only'
    assert choice['audition_url']==receipt['audio_url']
    assert client.get(f'/api/voices/{vid}/clone-preview').status_code!=200


def test_empty_runtime_does_not_claim_another_runtimes_clone_auditions(tmp_path, monkeypatch):
    from backend.clone_runtime import runtime_status
    monkeypatch.setenv('OPENDUB_DATA_DIR',str(tmp_path/'clean'))
    assert runtime_status()['completed_auditions']==0
