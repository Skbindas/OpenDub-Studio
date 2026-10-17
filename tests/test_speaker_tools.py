import pytest


def test_traits_are_suggestions_and_disagreement_stays_unknown():
    from backend.speaker_tools import summarize_traits
    result=summarize_traits([{'age':.28,'probabilities':[.92,.06,.02]}, {'age':.31,'probabilities':[.90,.08,.02]}])
    assert result['voice_style_suggestion']=='feminine' and result['age_band_suggestion']=='young'
    assert result['gender_identity']=='unknown' and not result['exact_age_inferred']
    result=summarize_traits([{'age':.15,'probabilities':[.9,.05,.05]}, {'age':.8,'probabilities':[.05,.9,.05]}])
    assert result['voice_style_suggestion']=='unknown' and result['age_band_suggestion']=='unknown'


def test_overlap_crop_is_bounded_and_rejects_crowds():
    from backend.speaker_tools import validate_overlap_request
    assert validate_overlap_request({'start':1,'end':3,'speaker_ids':['A','B']},20)==(1,3)
    with pytest.raises(ValueError):validate_overlap_request({'start':1,'end':3,'speaker_ids':['A','B','C']},20)
    with pytest.raises(ValueError):validate_overlap_request({'start':1,'end':12,'speaker_ids':['A','B']},20)


def test_source_recovery_combines_only_same_identity_without_losing_words():
    from backend.speaker_tools import join_reviewed_turns
    rows=[{'start':1,'end':2,'speaker_id':'A','text':'one','words':[{'text':'one'}]},
          {'start':2,'end':3,'speaker_id':'A','text':'two','words':[{'text':'two'}]},
          {'start':3,'end':4,'speaker_id':'B','text':'three','words':[{'text':'three'}]}]
    output=join_reviewed_turns(rows)
    assert len(output)==2 and output[0]['text']=='one two' and len(output[0]['words'])==2
    assert rows[0]['text']=='one'


def test_model_logits_are_converted_to_probabilities():
    from backend.speaker_tools import trait_prediction
    result=trait_prediction(.3,[3,-2,-4])
    assert sum(result['probabilities'])==pytest.approx(1)
    assert result['probabilities'][0]>.99
    with pytest.raises(ValueError):trait_prediction(.3,[float('nan'),0,0])


def test_invalid_age_and_probabilities_do_not_create_suggestions():
    from backend.speaker_tools import summarize_traits
    result=summarize_traits([{'age':3,'probabilities':[.9,.9,.9]}]*2)
    assert result['voice_style_suggestion']=='unknown' and result['age_band_suggestion']=='unknown'


def test_optional_results_are_bound_to_source_and_identity_revision(tmp_path):
    from backend.speaker_tools import tool_context, current_tool_result
    (tmp_path/'analysis').mkdir();(tmp_path/'characters').mkdir()
    (tmp_path/'analysis/diarization.json').write_text('{"identity_source_sha256":"one"}')
    result={'context_sha256':tool_context(tmp_path),'characters':{'C':{}}}
    assert current_tool_result(tmp_path,result)==result
    (tmp_path/'analysis/diarization.json').write_text('{"identity_source_sha256":"two"}')
    assert current_tool_result(tmp_path,result)=={}


def test_interrupted_overlap_cache_is_never_reused(tmp_path):
    from backend.speaker_tools import valid_overlap_cache
    import soundfile as sf
    import numpy as np
    paths=[tmp_path/'a.wav',tmp_path/'b.wav']
    sf.write(paths[0],np.ones(1600)*.1,16000)
    paths[1].write_bytes(b'interrupted')
    assert not valid_overlap_cache(paths,1600)


@pytest.mark.parametrize('kind',['voice_traits','overlap_recovery'])
def test_optional_speaker_tools_are_claimed_by_durable_queue(tmp_path,kind,monkeypatch):
    from backend.db import init_db,connect,claim_next_job,now,get_job
    database=tmp_path/'queue.sqlite3';init_db(database)
    with connect(database) as conn:
        conn.execute('INSERT INTO projects(id,name,created_at,updated_at) VALUES (?,?,?,?)',('p','test',now(),now()))
        conn.execute('INSERT INTO jobs(id,project_id,kind,status,created_at,updated_at) VALUES (?,?,?,?,?,?)',('j','p',kind,'queued',now(),now()))
    job=claim_next_job(database,'worker');assert job['id']=='j'
    from backend import speaker_tools
    from backend.worker import JobWorker
    def setup_failure(*args):
        with connect(database) as conn:conn.execute("UPDATE jobs SET status='failed',message='Review/setup needed' WHERE id='j'")
    monkeypatch.setattr(speaker_tools,'execute_speaker_tool',setup_failure)
    JobWorker(database,worker_id='worker')._dispatch(job)
    assert get_job(database,'j')['status']=='failed'
    assert get_job(database,'j')['attempts']==1
