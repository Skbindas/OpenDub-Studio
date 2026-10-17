import json
import wave
from pathlib import Path

import pytest


def test_missing_atomic_source_must_not_certify_old_target(tmp_path):
    from backend.atomic_files import replace_with_retry
    target = tmp_path / 'saved.json'
    target.write_text('old')
    with pytest.raises(FileNotFoundError):
        replace_with_retry(tmp_path / 'missing.tmp', target, attempts=1)
    assert target.read_text() == 'old'


def test_automatic_worker_budget_serializes_clones_and_scales_cpu():
    from backend.resource_plan import synthesis_worker_limit
    assert synthesis_worker_limit(800 * 1024**2, 12, cloned=False) == 1
    assert synthesis_worker_limit(8 * 1024**3, 12, cloned=False) > 1
    assert synthesis_worker_limit(8 * 1024**3, 12, cloned=True) == 1


def test_hindi_batch_preserves_ids_and_rejects_missing_text():
    from backend.automatic_dialogue import validate_hindi_batch
    rows = [{'segment_index': 2}, {'segment_index': 5}]
    good = {'lines': [{'segment_index': 5, 'text': 'रुको, मैं आता हूँ।'}, {'segment_index': 2, 'text': 'तुम ठीक हो?'}]}
    result = validate_hindi_batch(good, rows)
    assert result == {2: 'तुम ठीक हो?', 5: 'रुको, मैं आता हूँ।'}
    good['lines'][0]['text'] = ''
    with pytest.raises(ValueError, match='Hindi'):
        validate_hindi_batch(good, rows)


def test_cast_hints_do_not_override_audio_speaker_identity():
    from backend.automatic_dialogue import select_reference_voice
    voices = [
        {'voice_id': 'm', 'vocal_type': 'lower', 'reference_valid': True},
        {'voice_id': 'f', 'vocal_type': 'higher', 'reference_valid': True},
    ]
    assert select_reference_voice('higher', voices)['voice_id'] == 'f'
    assert select_reference_voice('lower', voices)['voice_id'] == 'm'
    assert select_reference_voice('unknown', voices) is None


def test_neural_separation_never_silently_uses_ducking(tmp_path, monkeypatch):
    from backend import background_preservation as bg
    source = tmp_path / 'analysis/source_16k_mono.wav'
    source.parent.mkdir()
    with wave.open(str(source), 'wb') as wav:
        wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        wav.writeframes(b'\0\0' * 32000)
    monkeypatch.setattr(bg, 'separate_dialogue_candidate', lambda *a, **kw: {'error': 'model missing'})
    with pytest.raises(RuntimeError, match='separation unavailable'):
        bg.preserve_background_audio(tmp_path, mode='separation')


def test_natural_hindi_resume_retains_batches_and_old_target(tmp_path, monkeypatch):
    import json
    from backend import automatic_dialogue as dialogue
    source, target = tmp_path/'source.json', tmp_path/'translated.json'
    source.write_text(json.dumps({'segments':[{'start':i,'end':i+1,'text':str(i)} for i in range(3)]}))
    target.write_text('old complete translation')
    calls = []
    def provider(rows, context):
        calls.append(rows[0]['segment_index'])
        if rows[0]['segment_index'] == 1:
            raise RuntimeError('provider unavailable')
        return {r['segment_index']:'नमस्ते' for r in rows}
    monkeypatch.setattr(dialogue,'generate_hindi_batch',provider)
    with pytest.raises(RuntimeError):
        dialogue.translate_natural_hindi(source,target,batch_size=1)
    assert target.read_text() == 'old complete translation'
    assert len(list((tmp_path/'natural_hindi_batches').glob('*.json'))) == 1
    monkeypatch.setattr(dialogue,'generate_hindi_batch',lambda rows,context: {r['segment_index']:'नमस्ते' for r in rows})
    result = dialogue.translate_natural_hindi(source,target,batch_size=1)
    assert result['translated_segments'] == 3
    assert len(list((tmp_path/'natural_hindi_batches').glob('*.json'))) == 3


def test_project_metadata_lock_prevents_lost_parallel_updates(tmp_path):
    import json
    from concurrent.futures import ThreadPoolExecutor
    from backend.atomic_files import project_mutation_lock
    from backend.chunk_execution import save_json
    path=tmp_path/'state.json'
    save_json(path, {'count':0})
    def increment(_):
        with project_mutation_lock(tmp_path):
            state=json.loads(path.read_text())
            state['count']+=1
            save_json(path,state)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(increment,range(20)))
    assert json.loads(path.read_text())['count'] == 20


def test_automatic_clone_selection_never_claims_human_approval(tmp_path):
    from backend.automatic_dialogue import automatic_reference_valid
    from backend.voice_bank_quality import fingerprint
    reference=tmp_path/'ref.wav'
    reference.write_bytes(b'a verified reference')
    record={'reference_path':str(reference),'sha256':fingerprint(reference),'metrics':{'duration_sec':8},
            'audit':{'status':'single_speaker_candidate','speech_text':'नमस्ते'}}
    profile={'selection_method':'automatic_audio_reference','reference_sha256':record['sha256']}
    assert automatic_reference_valid(record,profile)
    assert 'review' not in record
    reference.write_bytes(b'changed')
    assert not automatic_reference_valid(record,profile)


def test_bounded_longform_admission_accounts_for_disk_backed_pcm():
    from backend.resource_plan import plan_resources,GIB
    report={'system':{'logical_cpu_count':8},'memory':{'available_bytes':3*GIB},
            'disk':{'free_bytes':100*GIB}}
    plan=plan_resources(report,3906.816,bounded_analysis=True)
    assert plan['admitted']
    assert plan['required_available_ram_bytes'] < 3*GIB
    assert not plan_resources(report,3906.816)['admitted']


def test_warm_clone_server_reuses_process_and_reports_each_request(tmp_path,monkeypatch):
    import importlib.util,io,json,sys
    from contextlib import nullcontext
    from backend import clone_runtime
    spec=importlib.util.spec_from_file_location('clone_worker_test',Path('scripts/clone_voice_worker.py'))
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    paths=[]
    for index in range(2):
        folder=tmp_path/str(index); folder.mkdir()
        request=folder/'request.json'; request.write_text(json.dumps({'index':index}))
        paths.append(request)
    calls=[]
    def generate(request):
        calls.append(request['index'])
        return {'index':request['index']}
    monkeypatch.setattr(module,'main',generate)
    monkeypatch.setattr(clone_runtime,'clone_worker_slot',lambda: nullcontext())
    monkeypatch.setattr(sys,'stdin',io.StringIO(''.join(str(p)+'\n' for p in paths)))
    module.serve()
    assert calls == [0,1]
    for index,request in enumerate(paths):
        result=json.loads(request.with_name('worker-result.json').read_text())
        assert result == {'ok':True,'result':{'index':index}}


def test_roformer_other_stem_is_not_misread_as_vocals_from_model_name():
    from backend.background_preservation import identify_separator_stems
    other=Path('episode_(other)_vocals_mel_band_roformer.wav')
    vocal=Path('episode_(vocals)_vocals_mel_band_roformer.wav')
    assert identify_separator_stems([other,vocal]) == (vocal,other)
    assert identify_separator_stems([Path('instrumental.wav'),Path('vocals.wav')]) == (Path('vocals.wav'),Path('instrumental.wav'))


def test_diarization_pcm_uses_disk_mapping_and_cleans_temporary_file(tmp_path):
    import gc,numpy as np
    from backend.diarization import _load_pcm_wav
    path=tmp_path/'source.wav'
    pcm=np.array([0,16384,-16384,32767],dtype='<i2')
    with wave.open(str(path),'wb') as writer:
        writer.setnchannels(1);writer.setsampwidth(2);writer.setframerate(16000);writer.writeframes(pcm.tobytes())
    waveform,rate=_load_pcm_wav(path)
    assert rate==16000 and tuple(waveform.shape)==(1,4)
    assert waveform.tolist()[0] == pytest.approx([0,.5,-.5,32767/32768])
    assert len(list(tmp_path.glob('diarization-*.f32')))==1
    del waveform;gc.collect()
    assert not list(tmp_path.glob('diarization-*.f32'))


def test_user_confirmation_resolves_ambiguous_register_without_faking_measurement():
    from backend.automatic_dialogue import confirmed_vocal_type
    measured={'vocal_type':'unknown','pitch_median_hz':185,'exact_gender_inferred':False}
    evidence={'gender':'male','confirmed_by':'user','scope':'speaker gender only'}
    kind,confirmation=confirmed_vocal_type('SPEAKER_07',measured,{'SPEAKER_07':evidence})
    assert kind=='lower' and confirmation is evidence
    assert measured['vocal_type']=='unknown' and not measured['exact_gender_inferred']
    assert confirmed_vocal_type('SPEAKER_08',measured,{'SPEAKER_07':evidence}) == ('unknown',None)


def test_matching_prefers_similar_register_within_confirmed_voice_type():
    from backend.automatic_dialogue import select_reference_voice
    voices=[{'voice_id':'a_deep','reference_valid':True,'vocal_type':'lower','pitch_median_hz':95},
            {'voice_id':'b_light','reference_valid':True,'vocal_type':'lower','pitch_median_hz':158}]
    assert select_reference_voice('lower',voices,target_pitch=185)['voice_id']=='b_light'
    assert select_reference_voice('higher',voices,target_pitch=185) is None
