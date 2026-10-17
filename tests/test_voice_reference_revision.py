import copy
import pytest
from backend.pipeline import merge_dialogue_manifest_state

@pytest.mark.parametrize('field', ['reference_sha256','reference_text_sha256'])
def test_reference_revision_invalidates_only_affected_voice_audio(field):
    def unit(sid):
        return {'segment_id':sid,'source_text':'hello','character_id':sid,
                'voice':{'status':'configured','profile':{'provider':'omnivoice','voice_id':sid,
                    'reference_sha256':'audio-v1','reference_text_sha256':'text-v1'}},
                'tts':{'status':'pending'},'timing':{'status':'pending'},'loudness':{'status':'pending'}}
    new={'target_language':'hi','units':[unit('friend'),unit('main')]}
    old=copy.deepcopy(new)
    for u in old['units']:
        for stage in ('tts','timing','loudness'):u[stage]={'status':'completed','audio_path':u['segment_id']+'.wav'}
    new['units'][0]['voice']['profile'][field]='v2'
    merged=merge_dialogue_manifest_state(new,old)
    for stage in ('tts','timing','loudness'):
        assert merged['units'][0][stage]['status']=='pending'
        assert merged['units'][1][stage]['status']=='completed'
