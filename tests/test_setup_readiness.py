from backend.setup_readiness import setup_status


def report():
    return {'ffmpeg':{'status':'ok'},'ffprobe':{'status':'ok'},
            'optional_modules':{'faster_whisper':True},'memory':{'available_bytes':4*1024**3},
            'integrations':{'diarization_ready':False}}


def test_installed_tools_do_not_certify_model_or_gpu_readiness():
    state=setup_status(report(),clone_environment=True,separator_files=True,translation_configured=True,owned_voices=1)
    assert state['status']=='setup_required'
    assert state['gpu_allocation_verified'] is False
    assert state['model_loaded_verified'] is False
    assert any(x['key']=='speakers' and x['status']=='action_required' for x in state['checks'])


def test_missing_voice_pack_has_an_action_without_claiming_bundled_movie_voices():
    state=setup_status(report(),clone_environment=False,separator_files=False,translation_configured=False,owned_voices=0)
    voices=next(x for x in state['checks'] if x['key']=='voices')
    assert voices['status']=='action_required'
    assert 'recording' in voices['action'].lower()
    assert state['recommended_asr']=='small'


def test_even_complete_setup_requires_a_real_preview():
    data=report();data['integrations']['diarization_ready']=True
    state=setup_status(data,clone_environment=True,separator_files=True,translation_configured=True,owned_voices=1)
    assert state['status']=='preview_required'
    assert not state['model_loaded_verified']
