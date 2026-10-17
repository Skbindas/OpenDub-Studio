import pytest
import soundfile as sf
import numpy as np
from backend import analysis_pipeline as pipeline


def test_vocal_audio_keeps_source_clock_and_rejects_short_stem(tmp_path, monkeypatch):
    stem=tmp_path/'vocals.wav'
    data=np.zeros(32000,dtype=np.float32);data[16000:]=.1
    sf.write(stem,data,16000)
    def convert(source,target):
        target.write_bytes(source.read_bytes())
    monkeypatch.setattr(pipeline,'extract_audio',convert)
    output=tmp_path/'asr.wav'
    pipeline.prepare_vocal_audio({'status':'completed','vocals_stem':str(stem)},output,2)
    assert sf.info(output).duration==2
    assert np.all(sf.read(output)[0][:16000]==0)
    with pytest.raises(RuntimeError,match='duration'):
        pipeline.prepare_vocal_audio({'status':'completed','vocals_stem':str(stem)},output,3)
    with pytest.raises(RuntimeError,match='separation'):
        pipeline.prepare_vocal_audio({'status':'fallback','dialogue_candidate':str(stem)},output,2)


def test_word_speaker_changes_split_dialogue_without_moving_word_times():
    transcript={'language':'ko','segments':[{'start':10,'end':12,'text':'hello yes',
        'words':[{'start':10,'end':10.8,'text':'hello'}, {'start':11.1,'end':12,'text':' yes'}]}]}
    diar={'turns':[{'start':10,'end':10.9,'speaker_id':'SPEAKER_A'},
                    {'start':11,'end':12,'speaker_id':'SPEAKER_B'}]}
    aligned=pipeline.align_word_speakers(transcript,diar)
    assert [r['speaker_id'] for r in aligned['segments']]==['SPEAKER_A','SPEAKER_B']
    assert [(r['start'],r['end']) for r in aligned['segments']]==[(10,10.8),(11.1,12)]
    assert [r['text'] for r in aligned['segments']]==['hello','yes']
    assert transcript['segments'][0]['words'][0].get('speaker_id') is None


def test_ambiguous_word_does_not_get_a_fabricated_speaker():
    transcript={'segments':[{'start':0,'end':1,'text':'yes','words':[{'start':0,'end':1,'text':'yes'}]}]}
    turns=[{'start':0,'end':1,'speaker_id':s} for s in ('A','B')]
    aligned=pipeline.align_word_speakers(transcript,{'turns':turns})
    assert aligned['segments'][0]['speaker_id'] is None
    assert aligned['segments'][0]['speaker_review_required']


def test_full_vocal_analysis_separates_before_asr_and_uses_same_audio_for_speakers(tmp_path,monkeypatch):
    import json
    from backend.db import init_db,connect
    from backend import background_preservation
    db=tmp_path/'jobs.sqlite3';init_db(db)
    with connect(db) as c:
        c.execute("insert into projects(id,name,created_at,updated_at) values ('p','movie','now','now')")
        c.execute("insert into jobs(id,project_id,kind,status,created_at,updated_at) values ('j','p','full_analysis','running','now','now')")
    source=tmp_path/'movie.mkv';source.write_bytes(b'movie')
    root=tmp_path/'project';events=[]
    def extract(source,output):
        output.parent.mkdir(parents=True,exist_ok=True)
        sf.write(output,np.zeros(48000),16000)
        return {'file':str(output)}
    monkeypatch.setattr(pipeline,'extract_audio',extract)
    def stereo(source,output):
        sf.write(output,np.zeros((144000,2)),48000)
        return output
    monkeypatch.setattr(background_preservation,'extract_full_fidelity_audio',stereo)
    def separate(source,folder,model,**kwargs):
        events.append('separate');folder.mkdir(parents=True)
        vocal=folder/'vocals.wav';sf.write(vocal,np.zeros((144000,2)),48000)
        return {'status':'completed','vocals_stem':str(vocal),'dialogue_candidate':str(vocal)}
    monkeypatch.setattr(pipeline,'separate_dialogue_candidate',separate)
    def transcribe(audio,*args):
        events.append('transcribe');assert audio.name=='vocals_16k_mono.wav'
        return {'language':'ko','duration':3,'segments':[{'start':1,'end':2,'text':'hi',
                'words':[{'start':1,'end':2,'text':'hi'}]}]}
    monkeypatch.setattr(pipeline,'transcribe',transcribe)
    def diarize(audio,output,token,**options):
        events.append('diarize');assert audio.name=='vocals_16k_mono.wav'
        data={'turns':[{'start':1,'end':2,'speaker_id':'A'}]}
        pipeline._atomic_json(output,data);return data
    monkeypatch.setattr(pipeline,'diarize',diarize)
    monkeypatch.setattr(pipeline,'probe_media',lambda *a,**kw:{'duration_sec':3})
    monkeypatch.setattr(pipeline,'check_asr_runtime',lambda *a:{'status':'ready'})
    def profile(audio,output):
        pipeline._atomic_json(output,{});return {}
    monkeypatch.setattr(pipeline,'analyze_audio_profile',profile)
    pipeline.run_full_analysis(db_path=db,project_id='p',job_id='j',project_root=root,source=source,
        options={'transcribe_vocals':True,'audio_only':True,'hf_token':'test'})
    assert events==['separate','transcribe','diarize']
    transcript=json.loads((root/'analysis/transcript.json').read_text(encoding='utf-8'))
    assert transcript['audio_source']=='separated_vocals'
    assert transcript['segments'][0]['speaker_id']=='A'
    assert transcript['segments'][0]['start']==1
