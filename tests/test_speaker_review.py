import json
import pytest


def test_voice_lock_requires_confirmation_and_changes_invalidate_it():
    from backend.speaker_review import lock_voice,voice_locked
    character={'character_id':'c','source_speaker_id':'S','review_required':True,
               'voice_profile':{'provider':'piper','voice_id':'hindi','model_path':'voice.onnx'}}
    with pytest.raises(ValueError):lock_voice(character,confirmed=False)
    locked=lock_voice(character,confirmed=True)
    assert voice_locked(locked) and not locked['review_required']
    locked['voice_profile']['voice_id']='different'
    assert not voice_locked(locked)


def test_assistant_casting_does_not_claim_human_review():
    from backend.speaker_review import lock_voice
    result=lock_voice({'source_speaker_id':'S','voice_profile':{'provider':'piper','voice_id':'hi'}},True,'assistant_review')
    assert result['voice_lock']['confirmed_by']=='assistant_review'


def test_review_gate_preserves_uncertain_words_even_with_locked_cast(tmp_path):
    from backend.speaker_review import review_state,lock_voice
    (tmp_path/'analysis').mkdir()
    (tmp_path/'analysis'/'diarization.json').write_text(json.dumps({'schema_version':3,'raw_overlap_available':True,'speakers':[{'speaker_id':'S'}]}))
    (tmp_path/'analysis'/'transcript.json').write_text(json.dumps({'segments':[{'start':0,'end':1,'speaker_id':None,'speaker_review_required':True,'text':'yes'}]}))
    character=lock_voice({'character_id':'c','source_speaker_id':'S','voice_profile':{'provider':'piper','voice_id':'hindi'}},True)
    state=review_state(tmp_path,{'characters':[character]})
    assert not state['ready_for_dubbing'] and state['unresolved_turns']==[0]
    assert state['locked_voices']==1


def test_review_card_source_windows_exclude_simultaneous_speech(tmp_path):
    from backend.speaker_review import review_state
    (tmp_path/'analysis').mkdir()
    raw=[{'start':0,'end':4,'speaker_id':'S'},{'start':1,'end':3,'speaker_id':'T'}]
    (tmp_path/'analysis/diarization.json').write_text(json.dumps({'schema_version':3,'regular_turns':raw,'raw_overlap_available':True,'speakers':[{'speaker_id':'S'},{'speaker_id':'T'}]}))
    state=review_state(tmp_path,{'characters':[{'character_id':'c','source_speaker_id':'S'}]})
    assert all(not(w['start']<3 and w['end']>1) for w in state['cards'][0]['source_windows'])


def test_review_blocks_missing_speech_and_unreviewed_overlap(tmp_path):
    from backend.speaker_review import review_state,lock_voice
    (tmp_path/'analysis').mkdir()
    diar={'schema_version':3,'raw_overlap_available':True,'speakers':[{'speaker_id':'S'},{'speaker_id':'T'}],
          'regular_turns':[{'start':0,'end':2,'speaker_id':'S'},{'start':1,'end':2,'speaker_id':'T'}],
          'overlap_events':[{'start':1,'end':2,'speaker_ids':['S','T']}]}
    (tmp_path/'analysis/diarization.json').write_text(json.dumps(diar))
    (tmp_path/'analysis/transcript.json').write_text(json.dumps({'segments':[{'start':0,'end':2,'text':'hello','speaker_id':'S'}]}))
    active=lock_voice({'character_id':'active','source_speaker_id':'S','voice_profile':{'provider':'piper','voice_id':'hi'}},True)
    unused={'character_id':'old','source_speaker_id':'OLD'}
    state=review_state(tmp_path,{'characters':[active,unused],'speaker_links':{'S':'active','T':'active'}})
    assert len(state['cards'])==1 and state['cards'][0]['speaker_ids']==['S','T']
    assert state['untranscribed_speakers']==['T'] and state['unresolved_overlap_events']==[0]
    assert not state['ready_for_dubbing']


def test_explicit_non_dialogue_review_can_exclude_only_an_untranscribed_cluster(tmp_path):
    from backend.speaker_review import review_state,overlap_evidence_hash,lock_voice
    (tmp_path/'analysis').mkdir()
    diar={'schema_version':3,'identity_source_sha256':'source','raw_overlap_available':True,
          'speakers':[{'speaker_id':'S'},{'speaker_id':'MUSIC'}],'regular_turns':[]}
    (tmp_path/'analysis/diarization.json').write_text(json.dumps(diar))
    (tmp_path/'analysis/transcript.json').write_text(json.dumps({'segments':[{'start':0,'end':1,'text':'hello','speaker_id':'S'}]}))
    (tmp_path/'analysis/speaker_dispositions.json').write_text(json.dumps({'evidence_sha256':overlap_evidence_hash(diar),
        'speakers':{'MUSIC':{'category':'music_or_singing','confirmed':True}}}))
    character=lock_voice({'character_id':'c','source_speaker_id':'S','voice_profile':{'provider':'piper','voice_id':'hi'}},True)
    state=review_state(tmp_path,{'characters':[character,{'character_id':'m','source_speaker_id':'MUSIC'}],
                                  'speaker_links':{'S':'c','MUSIC':'m'}})
    assert state['estimated_speakers']==2 and state['active_speakers']==1
    assert state['ready_for_dubbing'] and state['untranscribed_speakers']==[]


def test_reference_text_change_invalidates_live_voice_evidence(tmp_path):
    import hashlib
    from backend.speaker_review import reference_matches_lock
    directory=tmp_path/'voice-bank-audit/records';directory.mkdir(parents=True)
    audio=tmp_path/'reference.wav';audio.write_bytes(b'preserved reference')
    evidence={'reference_path':str(audio),'audit':{'speech_text':'original words'}}
    record=directory/'voice.json';record.write_text(json.dumps(evidence))
    profile={'provider':'omnivoice','voice_id':'voice','reference_sha256':hashlib.sha256(audio.read_bytes()).hexdigest(),
             'reference_text_sha256':hashlib.sha256(b'original words').hexdigest()}
    assert reference_matches_lock(profile,tmp_path)
    evidence['audit']['speech_text']='corrected words';record.write_text(json.dumps(evidence))
    assert not reference_matches_lock(profile,tmp_path)
