"""Regression coverage for truthful orchestration and unchanged background gain."""
import json
import math
import shutil
import struct
import wave
from unittest.mock import patch

import pytest
from fastapi import HTTPException
import backend.app as studio


def test_resume_with_all_speech_saved_admits_only_fit_and_skips_synthesis(isolated_studio, monkeypatch):
    from backend.auto_dub import execute_auto_dub, save_status
    project_id, base = isolated_studio
    audio = base / 'saved.wav'
    audio.write_bytes(b'verified completed speech')
    analysis = base / 'analysis'
    for name, value in {
        'transcript.json': {'language': 'ko', 'segments': [{'text': 'source'}]},
        'diarization.json': {},
        'dialogue_manifest.json': {'units': [{'segment_index': 0, 'tts': {'status': 'completed', 'audio_path': str(audio)}, 'timing': {'status': 'pending'}}]},
        'translated_transcript.json': {'segments': [{'segment_index': 0, 'translated_text': 'saved Hindi'}]},
    }.items():
        (analysis / name).write_text(json.dumps(value), encoding='utf-8')
    (base / 'characters/registry.json').write_text('{"characters": [{"id": "saved"}]}')
    stages = [dict(s, status='completed' if i < 4 else 'pending', percent=100 if i < 4 else 0) for i, s in enumerate(studio.AUTO_DUB_STAGES)]
    save_status(base, {'status': 'failed', 'stages': stages, 'options': studio.AutoDubRequest().model_dump()})
    response = studio.start_auto_dub(project_id, studio.AutoDubRequest(automatic_voice_selection=False))
    workloads = []
    def capacity(*args, workload='analysis', **kwargs):
        workloads.append(workload)
        return {'admitted': workload == 'fit', 'reasons': ['speech budget exceeds free RAM'], 'heavy_workers': 0, 'cpu_threads_per_worker': 1, 'asr_device': 'cpu', 'chunk_seconds': 60}
    monkeypatch.setattr(studio, 'project_processing_plan', capacity)
    monkeypatch.setattr(studio, 'execute_batch_synthesis', lambda *a: pytest.fail('Completed speech was re-entered'))
    monkeypatch.setattr(studio, 'execute_batch_fit', lambda *a: (_ for _ in ()).throw(RuntimeError('fit reached')))
    with pytest.raises(RuntimeError, match='fit reached'):
        execute_auto_dub(response['job_id'], project_id, {})
    assert workloads == ['fit']


def test_auto_dub_empty_translation_stops_before_any_speech_work(isolated_studio, monkeypatch):
    from backend.auto_dub import execute_auto_dub, DialogueReviewRequired, read_status
    project_id, base = isolated_studio
    response = studio.start_auto_dub(project_id, studio.AutoDubRequest(automatic_voice_selection=False))
    def analysis(*args):
        (base / 'analysis/transcript.json').write_text(json.dumps({'language': 'ko', 'segments': [{'text': 'spoken source'}]}))
    monkeypatch.setattr(studio, 'execute_full_analysis', analysis)
    monkeypatch.setattr(studio, 'sync_characters', lambda *args: {'characters': [{'id': 'speaker'}]})
    monkeypatch.setattr(studio, 'translate_project', lambda *args: {'errors': 1})
    monkeypatch.setattr(studio, 'execute_batch_synthesis', lambda *args: pytest.fail('Empty translation reached synthesis'))
    with pytest.raises(DialogueReviewRequired, match='translation'):
        execute_auto_dub(response['job_id'], project_id, {})
    assert read_status(base)['failure_kind'] == 'review'


def test_new_identity_analysis_pauses_before_translation_and_resumes_checkpoints(isolated_studio,monkeypatch):
    from backend.auto_dub import execute_auto_dub,read_status
    project_id,base=isolated_studio
    response=studio.start_auto_dub(project_id,studio.AutoDubRequest())
    def analysis(*args):
        (base/'analysis/transcript.json').write_text(json.dumps({'language':'ko','segments':[{'start':0,'end':1,'text':'hello','speaker_id':'S'}]}))
        (base/'analysis/diarization.json').write_text(json.dumps({'schema_version':3,'raw_overlap_available':True,'speakers':[{'speaker_id':'S'}]}))
        (base/'analysis/dialogue_manifest.json').write_text('{"units":[]}')
    monkeypatch.setattr(studio,'execute_full_analysis',analysis)
    registry={'characters':[{'character_id':'c','source_speaker_id':'S'}],'speaker_links':{'S':'c'}}
    monkeypatch.setattr(studio,'sync_characters',lambda *a:registry)
    monkeypatch.setattr(studio,'translate_project',lambda *a:pytest.fail('Translation ran before voice review'))
    monkeypatch.setattr(studio,'execute_batch_synthesis',lambda *a:pytest.fail('TTS ran before voice locking'))
    execute_auto_dub(response['job_id'],project_id,{})
    paused=read_status(base)
    assert paused['status']=='awaiting_review' and not paused['auto_download_ready']
    assert studio.get_job(studio.DB_PATH,response['job_id'])['status']=='completed'
    resume=studio.start_auto_dub(project_id,studio.AutoDubRequest())
    assert resume['resuming'] and resume['stages'][0]['status']=='completed'


def test_auto_mix_balances_only_dialogue_without_tts_regeneration(tmp_path, monkeypatch):
    from backend.auto_dub import build_balanced_mix
    analysis=tmp_path/'analysis';analysis.mkdir()
    (analysis/'dialogue_manifest.json').write_text(json.dumps({'units':[{'segment_index':0,'loudness':{'target_lufs':-16}}]}))
    calls=[]; levels=[]
    def mix(*args):
        calls.append(args)
        if len(calls)==1:
            raise HTTPException(status_code=400,detail='Mix would clip (1.54 dBFS). Background gain was retained.')
        return {'file':'mix.wav'}
    monkeypatch.setattr(studio,'build_mix',mix)
    monkeypatch.setattr(studio,'normalize_segment',lambda project,index,level:levels.append((index,level)))
    assert build_balanced_mix(studio,'sample',tmp_path)['file']=='mix.wav'
    assert levels==[(0,-20)]
    assert all(not args[1].duck_background for args in calls)


def test_auto_mix_stops_at_leveling_limit_and_keeps_other_errors_visible(tmp_path, monkeypatch):
    from backend.auto_dub import build_balanced_mix, DialogueReviewRequired
    (tmp_path/'analysis').mkdir()
    (tmp_path/'analysis/dialogue_manifest.json').write_text(json.dumps({'units':[{'segment_index':0}]}))
    levels=[]
    monkeypatch.setattr(studio,'normalize_segment',lambda p,i,level:levels.append(level))
    monkeypatch.setattr(studio,'build_mix',lambda *args: (_ for _ in ()).throw(HTTPException(400,'Mix would clip')))
    with pytest.raises(DialogueReviewRequired): build_balanced_mix(studio,'sample',tmp_path)
    assert levels==[-20,-22,-24]
    monkeypatch.setattr(studio,'build_mix',lambda *args: (_ for _ in ()).throw(HTTPException(400,'Missing background')))
    with pytest.raises(HTTPException,match='Missing background'): build_balanced_mix(studio,'sample',tmp_path)


def test_custom_character_keeps_voice_settings_after_speaker_resync(tmp_path, monkeypatch):
    analysis = tmp_path / 'analysis'
    analysis.mkdir()
    diar = analysis / 'diarization.json'
    diar.write_text(json.dumps({'speakers': [{'speaker_id': f'SPEAKER_{i:02d}'} for i in range(6)]}))
    monkeypatch.setattr(studio, 'get_project', lambda *_: {'id': 'sample'})
    monkeypatch.setattr(studio, 'project_dir', lambda _: tmp_path)
    monkeypatch.setattr(studio, 'character_paths', lambda _: (tmp_path/'characters'/'registry.json', diar))
    monkeypatch.setattr(studio, 'refresh_dialogue_manifest', lambda _: None)
    custom = studio.create_character('sample', studio.CharacterCreate(display_name='Grover'))
    profile = {'provider':'piper', 'voice_id':'saved-hi', 'model_path':'voices/hi.onnx', 'language':'hi', 'settings':{'speaker_id':2}}
    studio.update_character('sample', custom['character_id'], studio.CharacterUpdate(voice_profile=profile))
    result = studio.sync_characters('sample')
    assert len(result['characters']) == 7
    saved = next(c for c in result['characters'] if c['character_id'] == custom['character_id'])
    assert saved['display_name'] == 'Grover'
    assert all(saved['voice_profile'][key] == value for key,value in profile.items())
from backend.background_preservation import preserve_background_audio
from backend.mixing import mix_project


def test_translation_review_uses_current_fit_without_rewriting_files(tmp_path, monkeypatch):
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    translated = analysis / "translated_transcript.json"
    translated.write_text(json.dumps({"segments": [{"segment_index": 0, "dub_audio": "dub.wav",
                       "synthesis_duration_check": {"status": "fit_required"}}]}))
    manifest = analysis / "dialogue_manifest.json"
    manifest.write_text(json.dumps({"units": [{"segment_index": 0, "timing": {"status": "completed", "actual_ms": 1600}}]}))
    before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in (translated, manifest)]
    monkeypatch.setattr(studio, "get_project", lambda *_: {"id": "sample"})
    monkeypatch.setattr(studio, "project_dir", lambda _: tmp_path)
    assert studio.get_translation("sample")["segments"][0]["timing_check"]["status"] == "completed"
    assert before == [(p.read_bytes(), p.stat().st_mtime_ns) for p in (translated, manifest)]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_fit_failure_retains_previous_audio(tmp_path, monkeypatch):
    import backend.mixing as mixing
    source, output = tmp_path / "voice.wav", tmp_path / "fit.wav"
    pcm(source, 1)
    output.write_bytes(b"previous verified audio")
    def fail(arguments, *_):
        from pathlib import Path
        Path(arguments[-1]).write_bytes(b"partial new audio")
        raise RuntimeError("injected interruption")
    monkeypatch.setattr(mixing, "run_ffmpeg", fail)
    with pytest.raises(RuntimeError):
        mixing.fit_audio(source, output, 1)
    assert output.read_bytes() == b"previous verified audio"


def pcm(path, seconds, amplitude=0, frequency=220):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setparams((2, 2, 48000, 0, "NONE", "not compressed"))
        out.writeframes(b"".join(struct.pack("<hh", *([int(amplitude * math.sin(2 * math.pi * frequency * n / 48000))] * 2)) for n in range(int(seconds * 48000))))


def test_auto_dub_rejects_project_without_source():
    with patch.object(studio, "get_project", return_value={"id": "empty"}), patch.object(studio.threading, "Thread"):
        with pytest.raises(HTTPException) as err:
            studio.start_auto_dub("empty")
    assert err.value.status_code == 400


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_default_mix_preserves_background_samples(tmp_path):
    bg = tmp_path / "output/background_preserved.wav"
    dub = tmp_path / "segments/silent.wav"
    pcm(bg, 2, 2000)
    pcm(dub, 1)
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "translated_transcript.json").write_text(json.dumps({"segments": [{"start": 0.5, "fitted_audio": str(dub)}]}))
    out = tmp_path / "output/mix.wav"
    mix_project(tmp_path, None, out)
    with wave.open(str(bg)) as original, wave.open(str(out)) as mixed:
        assert mixed.readframes(mixed.getnframes()) == original.readframes(original.getnframes())


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_strict_separation_does_not_silently_damage_background(tmp_path):
    pcm(tmp_path / "output/source_audio_48k.wav", 1, 1000)
    with patch("backend.background_preservation.separate_dialogue_candidate", return_value={"status": "fallback", "error": "model unavailable"}):
        with pytest.raises(RuntimeError, match="separation"):
            preserve_background_audio(tmp_path, mode="separation", strict_separation=True)
    assert not (tmp_path / "output/background_preserved.wav").exists()


def test_auto_dub_is_claimed_by_durable_worker(tmp_path):
    from backend.db import init_db, connect, claim_next_job
    db = tmp_path / "queue.sqlite3"
    init_db(db)
    with connect(db) as conn:
        conn.execute("INSERT INTO projects(id,name,created_at,updated_at) VALUES('p','Sample','now','now')")
        conn.execute("INSERT INTO jobs(id,project_id,kind,status,created_at,updated_at) VALUES('j','p','auto_dub','queued','now','now')")
    assert claim_next_job(db, "test-worker")["kind"] == "auto_dub"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_unity_gain_mix_rejects_clipping_and_keeps_previous_mix(tmp_path):
    bg = tmp_path / "output/background_preserved.wav"
    dub = tmp_path / "segments/dialogue.wav"
    pcm(bg, 1, 30000)
    pcm(dub, 1, 30000)
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "translated_transcript.json").write_text(json.dumps({"segments": [{"start": 0, "fitted_audio": str(dub)}]}))
    out = tmp_path / "output/mix.wav"
    out.write_bytes(b"previous mix")
    with pytest.raises(RuntimeError, match="clip"):
        mix_project(tmp_path, None, out)
    assert out.read_bytes() == b"previous mix"


@pytest.fixture
def isolated_studio(tmp_path, monkeypatch):
    from backend.db import init_db
    monkeypatch.setattr(studio, "ROOT", tmp_path)
    monkeypatch.setattr(studio, "DATA_ROOT", tmp_path / "runtime")
    monkeypatch.setattr(studio, "PROJECTS_ROOT", tmp_path / "runtime/projects")
    monkeypatch.setattr(studio, "DB_PATH", tmp_path / "runtime/test.sqlite3")
    monkeypatch.setenv("HF_TOKEN", "test-only-placeholder")
    monkeypatch.setattr(studio, "project_processing_plan", lambda *args, **kwargs: {"admitted": True, "heavy_workers": 1, "cpu_threads_per_worker": 2, "asr_device": "cpu", "chunk_seconds": 60})
    init_db(studio.DB_PATH)
    item = studio.create_project(studio.ProjectCreate(name="Orchestration test"))
    base = studio.project_dir(item["id"])
    source = base / "source/original.mp4"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"test fixture")
    with studio.connect(studio.DB_PATH) as conn:
        conn.execute("UPDATE projects SET source_path=? WHERE id=?", (source.relative_to(tmp_path).as_posix(), item["id"]))
    return item["id"], base


def test_project_delete_archives_files_and_recovery_metadata(isolated_studio):
    project_id, base = isolated_studio
    original = (base / "source/original.mp4").read_bytes()
    studio.delete_project(project_id)
    archive = next((studio.DATA_ROOT / "deleted_projects").iterdir())
    assert (archive / "files/source/original.mp4").read_bytes() == original
    assert json.loads((archive / "project.json").read_text())["id"] == project_id
    assert studio.get_project(studio.DB_PATH, project_id) is None
    assert not base.exists()


def test_project_delete_blocks_active_processing(isolated_studio):
    project_id, base = isolated_studio
    with studio.connect(studio.DB_PATH) as conn:
        conn.execute("INSERT INTO jobs(id,project_id,kind,status,created_at,updated_at) VALUES('busy',?,'auto_dub','running','now','now')", (project_id,))
    with pytest.raises(HTTPException) as error:
        studio.delete_project(project_id)
    assert error.value.status_code == 409
    assert base.exists()
    assert studio.get_project(studio.DB_PATH, project_id)


def test_speaker_mapping_survives_resync_and_invalidates_voice_lock(isolated_studio):
    from backend.speaker_review import lock_voice,voice_locked
    project_id,base=isolated_studio
    (base/'analysis/diarization.json').write_text(json.dumps({'schema_version':3,'raw_overlap_available':True,
        'speakers':[{'speaker_id':'S'},{'speaker_id':'T'}],'regular_turns':[]}))
    (base/'analysis/transcript.json').write_text(json.dumps({'segments':[{'start':0,'end':1,'speaker_id':'S','text':'hello'},
        {'start':1,'end':2,'speaker_id':'T','text':'world'}]}))
    registry=studio.sync_characters(project_id)
    target=registry['characters'][0];target['voice_profile']={'provider':'piper','voice_id':'hi','model_path':'voice.onnx'}
    registry['characters'][0]=lock_voice(target,True);studio.write_character_registry(project_id,registry)
    studio.link_speaker(project_id,studio.SpeakerLink(speaker_id='T',character_id=target['character_id']))
    again=studio.sync_characters(project_id)
    assert again['speaker_links']['T']==target['character_id']
    assert not voice_locked(next(c for c in again['characters'] if c['character_id']==target['character_id']))
    assert len(studio.get_speaker_review(project_id)['cards'])==1


def test_voice_lock_api_requires_confirmation_and_blocks_running_job(isolated_studio):
    from fastapi.testclient import TestClient
    project_id,base=isolated_studio
    char=studio.create_character(project_id,studio.CharacterCreate(display_name='Test voice'))
    registry=studio.read_character_registry(project_id)
    registry['characters'][0]['voice_profile']={'provider':'piper','voice_id':'hi','model_path':'voice.onnx'}
    studio.write_character_registry(project_id,registry)
    client=TestClient(studio.app);url=f'/api/projects/{project_id}/characters/{char["character_id"]}/voice-lock'
    assert client.post(url,json={'confirmed':False}).status_code==409
    assert client.post(url,json={'confirmed':True,'voice_age_style':'adult'}).status_code==200
    with studio.connect(studio.DB_PATH) as conn:
        conn.execute("INSERT INTO jobs(id,project_id,kind,status,created_at,updated_at) VALUES('busy',?,'auto_dub','running','now','now')",(project_id,))
    assert client.post(url,json={'confirmed':True}).status_code==409


def test_overlap_confirmation_cannot_hide_missing_second_speaker(isolated_studio):
    project_id,base=isolated_studio
    diar={'schema_version':3,'raw_overlap_available':True,'speakers':[{'speaker_id':'S'},{'speaker_id':'T'}],
          'regular_turns':[{'start':0,'end':2,'speaker_id':'S'},{'start':1,'end':2,'speaker_id':'T'}],
          'overlap_events':[{'start':1,'end':2,'speaker_ids':['S','T']}]}
    (base/'analysis/diarization.json').write_text(json.dumps(diar))
    (base/'analysis/transcript.json').write_text(json.dumps({'segments':[{'start':0,'end':2,'speaker_id':'S','text':'hello'}]}))
    with pytest.raises(HTTPException,match='incomplete'):
        studio.confirm_overlap_transcript(project_id,0,studio.OverlapReview(confirmed=True))
    assert not (base/'analysis/speaker_overlap_review.json').exists()


def test_manual_split_and_added_source_dialogue_update_timeline_with_backups(isolated_studio):
    project_id,base=isolated_studio
    diar={'schema_version':3,'identity_source_sha256':'source','raw_overlap_available':True,
          'speakers':[{'speaker_id':'S'}],'regular_turns':[{'start':0,'end':5,'speaker_id':'S'}],
          'alignment_turns':[{'start':0,'end':5,'speaker_id':'S'}]}
    (base/'analysis/diarization.json').write_text(json.dumps(diar))
    (base/'analysis/transcript.json').write_text(json.dumps({'segments':[{'start':1,'end':2,'speaker_id':'S','text':'hello'}]}))
    studio.sync_characters(project_id)
    split=studio.split_speaker_identity(project_id,0,studio.ManualIdentitySplit(confirmed=True))
    new=next(s for s in (c['source_speaker_id'] for c in split['cards']) if s!='S')
    assert split['turns'][0]['speaker_id']==new
    studio.add_missing_source_dialogue(project_id,studio.ManualSourceDialogue(speaker_id='S',start=2.5,end=3,text='missed speech'))
    saved=json.loads((base/'analysis/transcript.json').read_text())
    timeline=json.loads((base/'analysis/timeline.json').read_text())
    assert len(saved['segments'])==len(timeline['segments'])==2
    assert saved['segments'][1]['transcription_method']=='user_entered_missing_speech'
    assert list((base/'analysis/speaker-review-history').glob('*-diarization.json'))
    assert list((base/'characters').glob('speaker_overrides.json'))


def test_new_foundation_dependencies_stop_before_translation(isolated_studio):
    project_id,base=isolated_studio
    for filename,data in {'analysis_manifest.json':{'status':'completed'},'timeline.json':{'segments':[]},
                          'transcript.json':{'segments':[{'start':0,'end':1,'speaker_id':'S','text':'hello'}]},
                          'diarization.json':{'schema_version':3,'raw_overlap_available':True,'speakers':[{'speaker_id':'S'}]}}.items():
        (base/'analysis'/filename).write_text(json.dumps(data))
    studio.sync_characters(project_id)
    result=studio.get_pipeline_state(project_root=base,project_id=project_id,target_language='hi')
    assert result['next_recommended']['id']=='character_identity'
    with pytest.raises(HTTPException,match='Speaker review required'):
        studio.translate_project(project_id,studio.TranslationRequest(target_language='hi'))


def test_non_dialogue_disposition_never_hides_transcribed_words(isolated_studio):
    project_id,base=isolated_studio
    (base/'analysis/diarization.json').write_text(json.dumps({'schema_version':3,'raw_overlap_available':True,'speakers':[{'speaker_id':'S'}]}))
    (base/'analysis/transcript.json').write_text(json.dumps({'segments':[{'start':0,'end':1,'text':'hello','speaker_id':'S'}]}))
    with pytest.raises(HTTPException,match='speech cannot be hidden'):
        studio.review_non_dialogue_cluster(project_id,'S',studio.SpeakerDisposition(confirmed=True,category='non_speech'))
    assert not (base/'analysis/speaker_dispositions.json').exists()


def test_archive_failure_keeps_project(isolated_studio):
    project_id, base = isolated_studio
    with patch.object(studio.shutil, "move", side_effect=OSError("disk unavailable")):
        with pytest.raises(OSError):
            studio.delete_project(project_id)
    assert base.exists()
    assert studio.get_project(studio.DB_PATH, project_id)


def test_atomic_checkpoint_retries_transient_windows_lock(tmp_path, monkeypatch):
    from backend.atomic_files import replace_with_retry
    from pathlib import Path
    original = Path.replace
    attempts = []
    def locked_once(source, target):
        attempts.append(1)
        if len(attempts) == 1:
            raise PermissionError("sharing violation")
        return original(source, target)
    monkeypatch.setattr(Path, "replace", locked_once)
    source, target = tmp_path / "new.tmp", tmp_path / "checkpoint.json"
    source.write_text("new checkpoint")
    target.write_text("old checkpoint")
    replace_with_retry(source, target)
    assert target.read_text() == "new checkpoint"
    assert len(attempts) == 2


def test_atomic_checkpoint_permanent_lock_keeps_old_file(tmp_path, monkeypatch):
    from backend.atomic_files import replace_with_retry
    from pathlib import Path
    source, target = tmp_path / "new.tmp", tmp_path / "checkpoint.json"
    source.write_text("new checkpoint")
    target.write_text("old checkpoint")
    monkeypatch.setattr(Path, "replace", lambda *a: (_ for _ in ()).throw(PermissionError("locked")))
    with pytest.raises(PermissionError):
        replace_with_retry(source, target, attempts=1)
    assert target.read_text() == "old checkpoint"
    assert source.read_text() == "new checkpoint"


def test_fit_retry_keeps_translation_checkpoint_and_reports_pending_review(isolated_studio):
    import os
    project_id, base = isolated_studio
    for name in ("segment_000000_dub.wav", "segment_000000_fit.wav", "segment_000000_normalized.wav"):
        (base / "segments" / name).write_bytes(b"existing audio")
    (base / "analysis/dialogue_manifest.json").write_text(json.dumps({"units": [{"segment_index":0,"duration_sec":1.,"tts":{"status":"completed","audio_path":str(base/'segments/segment_000000_dub.wav')},"timing":{"fit_policy_version":2,"status":"needs_review","target_duration_sec":1.,"applied_tempo":1.25,"max_speedup":1.25,"max_slowdown":.82},"loudness":{"status":"completed"}}]}))
    translated = base / "analysis/translated_transcript.json"
    translated.write_text(json.dumps({"segments":[{"segment_index":0,"translated_text":"नमस्ते"}]},ensure_ascii=False,indent=2),encoding="utf-8")
    os.utime(translated, (1000000,1000000))
    before = translated.stat().st_mtime_ns
    job_id = studio.create_job(project_id,"batch_fit",{})
    studio.execute_batch_fit(job_id,project_id,{})
    assert translated.stat().st_mtime_ns == before
    assert studio.get_job(studio.DB_PATH,job_id)["payload"]["needs_review_count"] == 1


def test_auto_dub_failure_never_enables_download(isolated_studio, monkeypatch):
    from backend.auto_dub import execute_auto_dub, read_status
    project_id, base = isolated_studio
    response = studio.start_auto_dub(project_id, studio.AutoDubRequest(automatic_voice_selection=False))
    def failed_analysis(*args):
        raise RuntimeError("ASR model unavailable")
    monkeypatch.setattr(studio, "execute_full_analysis", failed_analysis)
    with pytest.raises(RuntimeError, match="ASR"):
        execute_auto_dub(response["job_id"], project_id, {})
    status = read_status(base)
    assert status["status"] == "failed"
    assert status["auto_download_ready"] is False
    assert all(stage["status"] != "completed" for stage in status["stages"])
    assert studio.get_project(studio.DB_PATH, project_id)["status"] == "failed"


def test_retry_fit_preserves_completed_stages_and_reviewed_dialogue(isolated_studio, monkeypatch):
    from backend.auto_dub import execute_auto_dub, save_status
    project_id, base = isolated_studio
    analysis = base / "analysis"
    for filename, value in {"transcript.json": {"language": "zh", "segments": [{"text": "source"}]}, "diarization.json": {}, "dialogue_manifest.json": {"units": []}, "translated_transcript.json": {"segments": [{"translated_text": "मेरे संशोधित शब्द"}]}}.items():
        (analysis / filename).write_text(json.dumps(value), encoding="utf-8")
    (base / "characters/registry.json").write_text('{"characters": [{"id": "speaker"}]}')
    stages = [dict(s, status="completed" if i < 4 else "failed" if i == 4 else "pending", percent=100 if i < 4 else 0) for i, s in enumerate(studio.AUTO_DUB_STAGES)]
    save_status(base, {"status": "failed", "stages": stages, "options": studio.AutoDubRequest().model_dump(), "current_stage": stages[4]["key"], "progress_percent": 72})
    response = studio.start_auto_dub(project_id, studio.AutoDubRequest(automatic_voice_selection=False))
    assert response["stages"][3]["status"] == "completed"
    for name in ("execute_full_analysis", "sync_characters", "translate_project"):
        monkeypatch.setattr(studio, name, lambda *a, **kw: pytest.fail("A completed upstream stage was rerun"))
    monkeypatch.setattr(studio, "execute_batch_synthesis", lambda *a: None)
    def retry_fit(*args):
        raise RuntimeError("fit retried")
    monkeypatch.setattr(studio, "execute_batch_fit", retry_fit)
    with pytest.raises(RuntimeError, match="fit retried"):
        execute_auto_dub(response["job_id"], project_id, {})
    assert json.loads((analysis / "translated_transcript.json").read_text())["segments"][0]["translated_text"] == "मेरे संशोधित शब्द"


def test_existing_unverified_video_does_not_mark_pipeline_completed(isolated_studio):
    project_id, base = isolated_studio
    output = base / "output"
    output.mkdir(parents=True, exist_ok=True)
    (output / "old_dubbed.mp4").write_bytes(b"unverified")
    assert studio.get_auto_dub_status(project_id)["auto_download_ready"] is False
    with pytest.raises(HTTPException):
        studio.get_final_video(project_id)


def test_status_exposes_only_current_job_work_and_measured_eta(isolated_studio):
    from backend.auto_dub import save_status
    from backend.work_progress import record_work
    project_id, base = isolated_studio
    response = studio.start_auto_dub(project_id, studio.AutoDubRequest(automatic_voice_selection=False))
    response.update(status="running")
    save_status(base, response)
    record_work(base, "synthesis", 0, 46, job_id=response["job_id"], now=100)
    record_work(base, "synthesis", 23, 46, job_id=response["job_id"], now=110)
    current = studio.get_auto_dub_status(project_id)
    assert current["progress_percent"] == 65
    assert current["eta_seconds"] == 10
    assert current["work"]["remaining"] == 23
    record_work(base, "fit", 46, 46, job_id="another-job", now=120)
    assert "work" not in studio.get_auto_dub_status(project_id)


def test_worker_lease_reentry_reuses_completed_upstream_without_browser_post(isolated_studio, monkeypatch):
    from backend.auto_dub import execute_auto_dub, save_status
    project_id, base = isolated_studio
    response = studio.start_auto_dub(project_id, studio.AutoDubRequest(automatic_voice_selection=False))
    for filename, data in {"transcript.json": {"language":"zh","segments":[{"text":"source"}]},
                           "diarization.json": {}, "dialogue_manifest.json": {"units":[]},
                           "translated_transcript.json": {"segments":[{"translated_text":"सुरक्षित संवाद"}]}}.items():
        (base / "analysis" / filename).write_text(json.dumps(data), encoding="utf-8")
    (base / "characters/registry.json").write_text('{"characters":[{"id":"speaker"}]}')
    response.update(status="running", resuming=False)
    for stage in response["stages"][:4]:
        stage["status"] = "completed"
    save_status(base, response)
    for name in ("execute_full_analysis", "sync_characters", "translate_project"):
        monkeypatch.setattr(studio, name, lambda *args, **kwargs: pytest.fail("Completed upstream work was rerun"))
    monkeypatch.setattr(studio, "execute_batch_synthesis", lambda *args: None)
    monkeypatch.setattr(studio, "execute_batch_fit", lambda *args: (_ for _ in ()).throw(RuntimeError("unfinished fit resumed")))
    with pytest.raises(RuntimeError, match="unfinished fit resumed"):
        execute_auto_dub(response["job_id"], project_id, {})
    assert json.loads((base / "analysis/translated_transcript.json").read_text(encoding="utf-8"))["segments"][0]["translated_text"] == "सुरक्षित संवाद"


def test_manual_mix_does_not_bypass_timing_review(isolated_studio):
    project_id, base = isolated_studio
    (base / "analysis/dialogue_manifest.json").write_text(json.dumps({"units": [{"segment_index": 1, "tts": {"status": "completed"}, "timing": {"status": "needs_review"}}]}))
    with pytest.raises(HTTPException) as error:
        studio.build_mix(project_id, studio.MixRequest())
    assert error.value.status_code == 409


def test_editing_dialogue_invalidates_old_audio_without_deleting_it(isolated_studio):
    project_id, base = isolated_studio
    audio = base / "old.wav"
    audio.write_bytes(b"previous voice")
    unit = {"segment_index": 0, "duration_sec": 2, "source_text": "Hello", "translation": {"text": "hello"}, "tts": {"status": "completed", "audio_path": str(audio)}, "timing": {"status": "completed", "fit_audio": str(audio)}, "loudness": {"status": "completed"}}
    manifest = base / "analysis/dialogue_manifest.json"
    manifest.write_text(json.dumps({"units": [unit]}))
    translated = base / "analysis/translated_transcript.json"
    translated.write_text(json.dumps({"segments": [{"segment_index": 0, "translated_text": "hello", "dub_audio": str(audio), "fitted_audio": str(audio)}]}))
    studio.edit_translation(project_id, 0, studio.TranslationEditRequest(translated_text="नमस्ते"))
    changed = json.loads(manifest.read_text(encoding="utf-8"))["units"][0]
    assert changed["tts"]["status"] == "pending"
    assert changed["timing"]["status"] == "pending"
    assert "dub_audio" not in json.loads(translated.read_text(encoding="utf-8"))["segments"][0]
    assert audio.read_bytes() == b"previous voice"


def test_timing_review_stops_auto_export(tmp_path):
    from backend.auto_dub import verify_dialogue_ready
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "dialogue_manifest.json").write_text(json.dumps({"units": [{"segment_index": 3, "tts": {"status": "completed"}, "timing": {"status": "needs_review"}}]}))
    with pytest.raises(RuntimeError, match="timing review"):
        verify_dialogue_ready(tmp_path)


def test_invalid_upload_keeps_previous_source(isolated_studio, monkeypatch):
    import asyncio
    import io
    from starlette.datastructures import UploadFile
    project_id, base = isolated_studio
    original = base / "source/original.mp4"
    previous = original.read_bytes()
    def reject(_path):
        from backend.reliability import InvalidMediaError
        raise InvalidMediaError("Corrupt video")
    monkeypatch.setattr(studio, "validate_media_file", reject)
    with pytest.raises(HTTPException):
        asyncio.run(studio.upload_source(project_id, UploadFile(io.BytesIO(b"bad upload"), filename="sample.mp4")))
    assert original.read_bytes() == previous


def test_new_source_updates_duration_and_clears_old_pipeline(isolated_studio, monkeypatch):
    import asyncio
    import io
    from starlette.datastructures import UploadFile
    from backend.auto_dub import save_status
    project_id, base = isolated_studio
    save_status(base, {"status": "completed", "auto_download_ready": True})
    monkeypatch.setattr(studio, "validate_media_file", lambda _path: {"ok": True})
    monkeypatch.setattr(studio, "ffprobe", lambda _path: {"duration_ms": 159103, "available": True})
    asyncio.run(studio.upload_source(project_id, UploadFile(io.BytesIO(b"new video"), filename="sample.mp4")))
    assert studio.get_project(studio.DB_PATH, project_id)["duration_ms"] == 159103
    assert studio.get_auto_dub_status(project_id)["auto_download_ready"] is False


def test_source_replacement_rejected_during_active_job(isolated_studio):
    import asyncio
    import io
    from starlette.datastructures import UploadFile
    project_id, base = isolated_studio
    studio.start_auto_dub(project_id, studio.AutoDubRequest(automatic_voice_selection=False))
    with pytest.raises(HTTPException) as error:
        asyncio.run(studio.upload_source(project_id, UploadFile(io.BytesIO(b"replacement"), filename="sample.mp4")))
    assert error.value.status_code == 409
    assert (base / "source/original.mp4").read_bytes() == b"test fixture"


def test_auto_dub_download_only_after_verified_sequence(isolated_studio, monkeypatch):
    from backend.auto_dub import execute_auto_dub, read_status
    project_id, base = isolated_studio
    response = studio.start_auto_dub(project_id, studio.AutoDubRequest(automatic_voice_selection=False))
    steps = []
    def analysis(*args):
        steps.append("analysis")
        (base / "analysis").mkdir(exist_ok=True)
        (base / "analysis/transcript.json").write_text(json.dumps({"language": "zh", "segments": [{"text": "dialogue"}]}))
    def translation(*args):
        steps.append("translation")
        audio = base / "test_dialogue.wav"
        audio.write_bytes(b"mocked audio artifact")
        (base / "analysis/dialogue_manifest.json").write_text(json.dumps({"units": [{"segment_index": 0, "tts": {"status": "completed", "audio_path": str(audio)}, "timing": {"status": "completed", "fit_audio": str(audio)}}]}))
    def render(*args):
        assert not read_status(base)["auto_download_ready"]
        steps.append("render")
        (base / "output").mkdir(exist_ok=True)
        (base / "output/render_qa_report.json").write_text(json.dumps({"status": "PASSED"}))
    monkeypatch.setattr(studio, "execute_full_analysis", analysis)
    monkeypatch.setattr(studio, "sync_characters", lambda *args: {"characters": [{"id": "reviewed"}]})
    monkeypatch.setattr(studio, "translate_project", translation)
    monkeypatch.setattr(studio, "execute_batch_synthesis", lambda *args: steps.append("synthesis"))
    monkeypatch.setattr(studio, "execute_batch_fit", lambda *args: steps.append("fit"))
    monkeypatch.setattr(studio, "preserve_background_endpoint", lambda *args: steps.append("separation"))
    monkeypatch.setattr(studio, "build_mix", lambda *args: steps.append("mix"))
    monkeypatch.setattr(studio, "execute_full_render", render)
    monkeypatch.setattr(studio, "get_final_video", lambda *args: steps.append("verify_video"))
    execute_auto_dub(response["job_id"], project_id, {})
    assert steps == ["analysis", "translation", "synthesis", "fit", "separation", "mix", "render", "verify_video"]
    assert read_status(base)["auto_download_ready"] is True
