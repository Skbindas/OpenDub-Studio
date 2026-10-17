"""Cloud contract tests: no credentials, uploads, model downloads or GPU required."""
import json
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
import pytest
from backend import compute_settings as settings,kaggle_jobs as jobs,kaggle_tasks as tasks
from backend.chunk_execution import digest,save_json
from backend.kaggle_transport import ProviderError,provider_status,dataset_ready


@pytest.fixture
def project(tmp_path,monkeypatch):
    from backend import app as studio
    from backend.db import init_db
    base=tmp_path/'projects'/'movie';base.mkdir(parents=True)
    db=tmp_path/'test.sqlite3';init_db(db);monkeypatch.setattr(studio,'DB_PATH',db)
    monkeypatch.setattr(studio,'DATA_ROOT',tmp_path)
    settings.write_settings(base,'kaggle','Owner','NvidiaTeslaT4',True,True)
    monkeypatch.setattr(tasks,'recipe',lambda *a:{'revision':'pinned'})
    monkeypatch.setattr(tasks,'worker_revision',lambda:'code-1')
    monkeypatch.setattr(tasks,'ensure_private_model',lambda *a:None)
    return base


def test_corrupt_settings_fail_closed_and_model_choice_is_explicit(tmp_path):
    settings.write_settings(tmp_path,'kaggle','Owner','NvidiaTeslaT4',True)
    value=settings.read_settings(tmp_path)
    assert value['username']=='owner' and not value['allow_model_upload'] and not value['pipeline_ready']
    data={**value,'allow_model_upload':'yes'};save_json(tmp_path/'compute-settings.json',data)
    with pytest.raises(RuntimeError,match='blocked'):settings.read_settings(tmp_path)


@pytest.mark.parametrize('text,expected',[("owner/complete-example has status \"queued\"",'queued'),
    ('{"status":"running"}','running'),('Status: KernelWorkerStatus.ERROR','error'),
    ('No status returned for completed-example','returned'),('incomplete','incomplete')])
def test_provider_status_does_not_match_handles(text,expected):assert provider_status(text)==expected


def test_dataset_incomplete_is_not_ready():
    assert not dataset_ready('Dataset status: incomplete')
    assert dataset_ready('Dataset status: ready')


def test_dataset_and_notebook_titles_cannot_collide_in_kaggle_namespace(project,monkeypatch):
    job=jobs.create(project,request(),'owner')
    assert job['dataset_handle'].split('/')[-1]!=job['kernel_handle'].split('/')[-1]


def test_expanded_kaggle_payload_keeps_media_and_code_hash_checks(tmp_path):
    from scripts.kaggle_task_worker import restore_payload
    source=tmp_path/'dataset';expanded=source/'payload';expanded.mkdir(parents=True)
    audio=expanded/'audio.wav';audio.write_bytes(b'owned audio')
    code=expanded/'src/backend/media.py';code.parent.mkdir(parents=True);code.write_text('safe code')
    records=[{'file':str(path.relative_to(expanded)).replace('\\','/'),'size':path.stat().st_size,'sha256':digest(path)} for path in (audio,code)]
    restore_payload(source,'payload.zip',tmp_path/'restored',records,'original-archive-checksum')
    assert (tmp_path/'restored/src/backend/media.py').read_text()=='safe code'
    code.write_text('changed code')
    with pytest.raises(RuntimeError,match='hash|checksum'):restore_payload(source,'payload.zip',tmp_path/'rejected',records,'original-archive-checksum')


def test_cancel_acknowledged_is_terminal_not_unknown(monkeypatch):
    from backend import kaggle_transport
    monkeypatch.setattr(kaggle_transport,'run',lambda *a,**k:'owner/run has status "KernelWorkerStatus.CANCEL_ACKNOWLEDGED"')
    assert kaggle_transport.kernel_status('owner','owner/run')=='cancelled'


def request():return {'schema_version':2,'operation':'fit','username':'owner','model':{},'params':{},'inputs':[],'expected_outputs':['fit.wav']}


def test_one_claim_and_terminal_retry_requires_evidence(project):
    job=jobs.create(project,request(),'owner');jobs.claim_submission(project,job['id'])
    with pytest.raises(RuntimeError):jobs.claim_submission(project,job['id'])
    jobs.update(project,job['id'],'review_required','Model code error')
    with pytest.raises(RuntimeError):jobs.retry_terminal(project,job['id'])
    jobs.update(project,job['id'],'review_required','Remote attempt is terminal. Verified.')
    retry=jobs.retry_terminal(project,job['id'])
    assert retry['kernel_handle'].endswith('-retry-2') and retry['kernel_state']=='not_submitted'
    assert retry['dataset_handle']==job['dataset_handle']


def test_ambiguous_push_is_never_blindly_submitted_again(project,monkeypatch):
    source=project/'audio.wav';source.write_bytes(b'real-input-placeholder')
    calls=[]
    def run(owner,args,**kw):
        calls.append(args[:2])
        if args[:2]==['datasets','status']:return 'Dataset status: ready'
        if args[:2]==['kernels','push']:raise ProviderError('uncertain','Timed out')
        return 'created'
    monkeypatch.setattr(tasks,'run',run)
    monkeypatch.setattr(tasks,'kernel_status',lambda *a:'unknown')
    for _ in range(2):
        with pytest.raises(tasks.RemoteWaiting):tasks.execute(project,'fit',{'target':1},{'audio.wav':source},{'fit.wav':project/'fit.wav'})
    assert calls.count(['datasets','create'])==1 and calls.count(['kernels','push'])==1
    job=jobs.get(project,jobs.list_jobs(project)[0]['id'])
    assert job['kernel_state']=='submitting'
    assert source.read_bytes()==b'real-input-placeholder'


def test_model_pending_parks_parent_without_notebook_push(project,monkeypatch):
    from backend.kaggle_models import ModelPending
    def pending(*a):raise ModelPending('Model processing')
    monkeypatch.setattr(tasks,'ensure_private_model',pending)
    monkeypatch.setattr(tasks,'run',lambda *a,**kw:pytest.fail('must not push'))
    source=project/'audio';source.write_bytes(b'input')
    with pytest.raises(tasks.RemoteWaiting):tasks.execute(project,'fit',{}, {'audio.wav':source},{'fit.wav':project/'out.wav'})
    assert jobs.list_jobs(project)[0]['state']=='waiting'


def output_fixture(base,job,*,filename='fit.wav',status='completed',kind=None):
    root=base/'kaggle'/job['id']/'task-download'/job['kernel_handle'].split('/')[-1]/'task-output'
    root.mkdir(parents=True,exist_ok=True);path=root/'fit.wav';path.write_bytes(b'verified audio bytes')
    receipt={'fingerprint':job['fingerprint'],'operation':'fit','status':status,'failure_kind':kind,
             'outputs':[{'file':filename,'size':path.stat().st_size,'sha256':digest(path)}],'result':{'file':'@output/fit.wav'}}
    save_json(root/'task-receipt.json',receipt);return receipt,path


@pytest.mark.parametrize('filename',['../fit.wav','/fit.wav','C:/fit.wav','unexpected.wav'])
def test_unexpected_output_rejected_before_import(project,monkeypatch,filename):
    job=jobs.create(project,request(),'owner');output_fixture(project,job,filename=filename)
    monkeypatch.setattr(tasks,'run',lambda *a,**kw:'ok')
    with pytest.raises((RuntimeError,ValueError)):tasks._collect(project,job)
    assert not (project/'kaggle'/job['id']/'task-completed/fit.wav').exists()


def test_hash_checked_completion_and_corrupt_cache_rejection(project,monkeypatch):
    source=project/'input.wav';source.write_bytes(b'source')
    task={**request(),'model':{'revision':'pinned'},'params':{'target':1},'accelerator':'NvidiaTeslaT4','worker_revision':'code-1','payload_files':tasks.payload_records({'audio.wav':source}),
          'inputs':[{'file':'audio.wav','sha256':digest(source),'size':source.stat().st_size}]}
    job=jobs.create(project,task,'owner');output_fixture(project,job)
    monkeypatch.setattr(tasks,'run',lambda *a,**kw:'ok')
    receipt,folder=tasks._collect(project,job);out=project/'fitted.wav'
    assert tasks.execute(project,'fit',{'target':1},{'audio.wav':source},{'fit.wav':out})['file']==str(out)
    previous=out.read_bytes();(folder/'fit.wav').write_bytes(b'corrupt')
    with pytest.raises(RuntimeError,match='changed'):tasks.execute(project,'fit',{'target':1},{'audio.wav':source},{'fit.wav':out})
    assert out.read_bytes()==previous


def test_private_bundle_excludes_environment_and_other_media(project,monkeypatch):
    source=project/'audio.wav';source.write_bytes(b'input');(project/'.env').write_text('PRIVATE=do-not-upload')
    (project/'original.mp4').write_bytes(b'unselected original')
    job=jobs.create(project,{**request(),'payload_files':tasks.payload_records({'audio.wav':source})},'owner');calls=[]
    def run(owner,args,**kw):
        calls.append(args);return 'status: ready'
    monkeypatch.setattr(tasks,'run',run)
    folder=tasks._publish_input(project,job,{'audio.wav':source},None)
    with zipfile.ZipFile(folder/'input/payload.zip') as archive:
        names=archive.namelist()
        assert 'audio.wav' in names and 'src/backend/media.py' in names
        assert not any(name.endswith(('.env','.mp4')) or 'runtime/' in name for name in names)
    metadata=json.loads((folder/'kernel/kernel-metadata.json').read_text())
    assert metadata['is_private'] is True and metadata['enable_gpu'] is False


def test_credentials_for_another_account_rejected_and_no_plaintext_fallback(monkeypatch):
    from backend import kaggle_credentials as credentials
    monkeypatch.setattr(credentials,'_stored',lambda:{'username':'other','token':'PRIVATE_TOKEN'})
    with pytest.raises(RuntimeError,match='different'):credentials.subprocess_environment('owner')
    monkeypatch.setenv('OPENDUB_KAGGLE_BRIDGE','1')
    def unavailable():raise RuntimeError('Vault unavailable')
    monkeypatch.setattr(credentials,'_vault',unavailable)
    with pytest.raises(RuntimeError,match='Vault'):credentials.save_credentials('owner','secret')


def test_metadata_secret_guard_and_archive_traversal(tmp_path):
    from backend.kaggle_privacy import check_metadata
    from scripts.kaggle_task_worker import unpack
    with pytest.raises(RuntimeError):check_metadata({'params':{'hf_token':'secret'}})
    archive=tmp_path/'bad.zip'
    with zipfile.ZipFile(archive,'w') as output:output.writestr('../escape','private')
    with pytest.raises(RuntimeError):unpack(archive,tmp_path/'unpack')
    assert not (tmp_path/'escape').exists()


def test_session_retry_retains_completed_and_observes_backoff(project,monkeypatch):
    from backend import kaggle_recovery as recovery
    job=jobs.create(project,request(),'owner');job=jobs.claim_submission(project,job['id'])
    jobs.set_control(project,job['id'],kernel_state='submitted')
    jobs.update(project,job['id'],'running')
    monkeypatch.setattr(recovery,'kernel_status',lambda *a:'failed')
    monkeypatch.setattr(recovery,'wake_parent',lambda *a:None)
    def failure(base,job):
        jobs.update(base,job['id'],'review_required','Remote session failure. Completed units retained.')
        raise tasks.RemoteWaiting('session failed')
    monkeypatch.setattr(recovery,'_collect',failure)
    first=recovery.reconcile(project,job['id']);assert first['state']=='review_required'
    observed=jobs.get(project,job['id'])['terminal_observed_at'];assert observed
    monkeypatch.setattr(recovery.time,'time',lambda:observed+61)
    second=recovery.reconcile(project,job['id'])
    assert second['state']=='prepared' and second['kernel_handle']!=job['kernel_handle']
    assert second['dataset_handle']==job['dataset_handle'] and second['attempts']==1


def test_model_code_failure_does_not_auto_retry(project,monkeypatch):
    from backend import kaggle_recovery as recovery
    job=jobs.create(project,request(),'owner');jobs.claim_submission(project,job['id']);jobs.set_control(project,job['id'],kernel_state='submitted')
    monkeypatch.setattr(recovery,'kernel_status',lambda *a:'failed')
    def failure(base,job):
        jobs.update(base,job['id'],'review_required','Remote processing failure. Completed units retained.')
        raise tasks.RemoteWaiting('review')
    monkeypatch.setattr(recovery,'_collect',failure)
    result=recovery.reconcile(project,job['id'])
    assert result['state']=='review_required' and result['kernel_handle']==job['kernel_handle']


def test_worker_wait_error_survives_wrapping():
    error=tasks.RemoteWaiting('quota waiting')
    try:
        try:raise error
        except tasks.RemoteWaiting as exc:raise RuntimeError('chunk wrapper') from exc
    except RuntimeError as wrapped:assert tasks.waiting_error(wrapped) is error


def test_account_lock_blocks_second_coordinator_and_releases(project):
    from backend.kaggle_lock import account_lock
    with account_lock(project,'owner'):
        with pytest.raises(tasks.RemoteWaiting):
            with account_lock(project,'owner'):pytest.fail('duplicate coordinator entered')
    with account_lock(project,'owner'):pass


def test_pipeline_waits_for_short_account_contention_without_orphaning_parent(project,monkeypatch):
    import threading
    from backend.kaggle_lock import account_lock
    entered=threading.Event();errors=[];result=[]
    monkeypatch.setattr(tasks,'_execute',lambda *a,**kw:entered.set() or {'retained':True})
    def run():
        try:result.append(tasks.execute(project,'probe',{}, {}, {}))
        except Exception as exc:errors.append(exc)
    with account_lock(project,'owner'):
        thread=threading.Thread(target=run);thread.start()
        assert not entered.wait(.15)
    thread.join(3)
    assert not thread.is_alive() and not errors
    assert result==[{'retained':True}]


def test_pipeline_can_cancel_while_waiting_for_account_lock(project,monkeypatch):
    from backend.kaggle_lock import account_lock
    monkeypatch.setattr(tasks,'_execute',lambda *a,**kw:pytest.fail('entered locked account'))
    with account_lock(project,'owner'):
        with pytest.raises(InterruptedError,match='cancelled|paused'):
            tasks.execute(project,'probe',{}, {}, {},cancelled=lambda:True)


def test_synthesis_prefetch_bounds_each_notebook_to_four_lines(project,monkeypatch):
    from backend import kaggle_operations as operations
    reference=project/'reference.wav';reference.write_bytes(b'reviewed reference')
    monkeypatch.setattr(operations,'synthesis_key',lambda base,item:item['text'])
    batches=[]
    monkeypatch.setattr(operations,'execute',lambda base,operation,params,files,outputs,**kw:batches.append((operation,params,outputs)))
    operations.prefetch_synthesis(project,[{'text':str(i),'reference':reference,'ref_text':'exact reference','prosody':{}} for i in range(9)],lambda:False)
    assert [len(batch[1]['lines']) for batch in batches]==[4,4,1]
    assert all(batch[0]=='synthesis_batch' and len(batch[2])==len(batch[1]['lines'])*3 for batch in batches)


def test_nested_portable_output_paths_are_rebound_without_private_host_paths(tmp_path):
    files={'reference.wav':tmp_path/'ref.wav'};outputs={'lines/a/speech.wav':tmp_path/'speech.wav'}
    value={'audio':'@output/lines/a/speech.wav','source':'@input/reference.wav'}
    assert tasks.materialize(value,files,outputs)=={'audio':str(tmp_path/'speech.wav'),'source':str(tmp_path/'ref.wav')}


def test_compute_mutations_reject_cross_site_requests():
    from backend.compute_routes import local_request
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:local_request(SimpleNamespace(headers={'origin':'https://evil.example','host':'127.0.0.1:7861'}))
    assert error.value.status_code==403
    local_request(SimpleNamespace(headers={'origin':'http://127.0.0.1:7861','host':'127.0.0.1:7861'}))


def test_unported_research_tools_never_silently_run_locally(project,monkeypatch):
    from backend import app as studio,kaggle_operations
    from fastapi import HTTPException
    monkeypatch.setattr(studio,'project_dir',lambda _:project)
    monkeypatch.setattr(kaggle_operations,'remote_plan',lambda *a:{'admitted':True,'reasons':[]})
    for operation in ('voice_traits','overlap_recovery'):
        with pytest.raises(HTTPException) as error:studio.create_job('movie',operation,{})
        assert error.value.status_code==409 and 'local' in error.value.detail.lower()


def test_provider_diagnostic_redacts_credentials_and_signed_urls():
    from scripts.kaggle_bridge import safe_diagnostic
    text='401 API failed example-private-token\nAuthorization: Bearer private-header\nhttps://example.org/upload?signature=private-signature\napi_key=private-key\nKGAT_'+('a'*40)
    result=safe_diagnostic(text,{'KAGGLE_API_TOKEN':'example-private-token'})
    assert '401 API failed' in result
    assert not any(value in result for value in ('example-private-token','private-header','private-signature','private-key','KGAT_'))


def test_cli_http_detail_only_copies_structured_error_fields():
    from scripts.kaggle_cli import error_detail
    response=SimpleNamespace(json=lambda:{'code':409,'message':'Title conflict','request':{'authorization':'private'},'headers':{'cookie':'private'}})
    assert json.loads(error_detail(response))=={'code':409,'message':'Title conflict'}


def test_bounded_readonly_log_stream_returns_redacted_progress(monkeypatch):
    import subprocess
    from scripts import kaggle_bridge as bridge
    from backend import kaggle_credentials
    monkeypatch.setattr(kaggle_credentials,'subprocess_environment',lambda username:{'KAGGLE_API_TOKEN':'private-token'})
    def timeout(*a,**kw):raise subprocess.TimeoutExpired('logs',1,output=b'Worker model loading private-token')
    monkeypatch.setattr(bridge.subprocess,'run',timeout)
    result=bridge.main('cli',{'username':'owner','args':['kernels','logs','owner/run','--follow'],'timeout':1})
    assert result['ok'] and result['partial_read'] and 'loading' in result['data'] and 'private-token' not in result['data']


def test_remote_failure_receipt_retains_stack_without_environment_secret(monkeypatch):
    from scripts.kaggle_task_worker import failure_diagnostic
    monkeypatch.setenv('TEST_API_TOKEN','private-worker-token')
    try:raise TypeError('bad argument private-worker-token')
    except TypeError as error:result=failure_diagnostic(error)
    assert result['type']=='TypeError' and result['stack']
    assert 'bad argument' in result['message'] and 'private-worker-token' not in result['message']


def test_remote_asr_pins_the_verified_pyav_decoder_for_both_paths(tmp_path,monkeypatch):
    from scripts import kaggle_task_worker as worker
    calls=[]
    monkeypatch.setattr(worker.subprocess,'run',lambda args,**kw:calls.append(args))
    for operation in ('transcription','synthesis_batch'):worker.install(operation,tmp_path)
    assert len(calls)==2 and all('av==18.1.0' in args and 'faster-whisper==1.2.1' in args for args in calls)


def test_cloud_stem_clock_resamples_before_counting_source_samples(tmp_path):
    import numpy as np
    import soundfile as sf
    from scripts.kaggle_task_worker import clocked_stem
    source=tmp_path/'separator-44100.wav';target=tmp_path/'stem-48000.wav'
    sf.write(source,np.ones((44100,2),dtype='float32')*.1,44100)
    frames=12347
    clocked_stem(source,target,frames)
    info=sf.info(target)
    assert (info.frames,info.samplerate,info.channels,info.subtype)==(frames,48000,2,'FLOAT')


def test_remote_unicode_receipt_is_independent_of_windows_locale(project,monkeypatch):
    job=jobs.create(project,request(),'owner');receipt,path=output_fixture(project,job)
    receipt['result']['text']='हिंदी संवाद · 谢谢'
    save_json(path.parent/'task-receipt.json',receipt)
    original=Path.read_text
    def legacy_locale(path,encoding=None,**kw):return original(path,encoding=encoding or 'cp1252',**kw)
    monkeypatch.setattr(Path,'read_text',legacy_locale)
    monkeypatch.setattr(tasks,'run',lambda *a,**kw:'ok')
    result,_=tasks._collect(project,job)
    assert result['result']['text']==receipt['result']['text']


def test_cancel_wins_over_concurrent_remote_connection_wait(project,monkeypatch):
    from backend import worker,app as studio
    cancelled=[];released=[]
    monkeypatch.setattr(worker,'job_cancel_requested',lambda *a:True)
    monkeypatch.setattr(worker,'mark_job_cancelled',lambda *a:cancelled.append(a))
    monkeypatch.setattr(worker,'release_job',lambda *a:released.append(a))
    def interrupted(*a):raise tasks.RemoteWaiting('Provider connection interrupted')
    monkeypatch.setattr(studio,'execute_full_analysis',interrupted)
    worker.JobWorker(studio.DB_PATH,worker_id='test')._dispatch({'id':'cancelled','project_id':'movie','kind':'full_analysis'})
    assert len(cancelled)==1 and not released


def test_auto_dub_status_honors_cancel_during_provider_wait(project,monkeypatch):
    from backend import app as studio,auto_dub
    from backend.db import now
    with studio.connect(studio.DB_PATH) as conn:
        conn.execute('INSERT INTO projects(id,name,created_at,updated_at) VALUES (?,?,?,?)',('movie','test',now(),now()))
        conn.execute('INSERT INTO jobs(id,project_id,kind,status,created_at,updated_at,cancel_requested) VALUES (?,?,?,?,?,?,?)',('job','movie','auto_dub','claimed',now(),now(),1))
    monkeypatch.setattr(studio,'project_dir',lambda _:project)
    def waiting(*a,**kw):raise tasks.RemoteWaiting('Provider interrupted')
    monkeypatch.setattr(studio,'project_processing_plan',waiting)
    auto_dub.execute_auto_dub('job','movie',{})
    assert auto_dub.read_status(project)['status']=='cancelled'


def test_gpu_runtime_installs_before_importing_torch_numpy(tmp_path,monkeypatch):
    import builtins
    from scripts import kaggle_task_worker as worker
    monkeypatch.setenv('CUDA_VISIBLE_DEVICES','initial')
    installed=[];original=builtins.__import__
    monkeypatch.setattr(worker,'install',lambda *a:installed.append(True))
    fake=SimpleNamespace(version=SimpleNamespace(cuda='12.8'),cuda=SimpleNamespace(
        is_available=lambda:True,device_count=lambda:1,mem_get_info=lambda i:(100,200),
        set_device=lambda i:None,get_device_name=lambda i:'test GPU'))
    def guarded(name,*a,**kw):
        if name=='torch':
            assert installed,'GPU imports must happen after dependency installation'
            return fake
        return original(name,*a,**kw)
    monkeypatch.setattr(builtins,'__import__',guarded)
    assert worker.prepare_runtime('diarization',tmp_path)['name']=='test GPU'


def test_numerical_runtime_is_compatible_with_metrics_and_numba(tmp_path,monkeypatch):
    from scripts import kaggle_task_worker as worker
    calls=[];monkeypatch.setattr(worker.subprocess,'run',lambda args,**kw:calls.append(args))
    for operation in ('diarization','separation','synthesis_batch'):worker.install(operation,tmp_path)
    assert all('numpy==2.2.6' in args for args in calls)


def test_media_batch_preserves_per_line_timing_and_normalization(tmp_path,monkeypatch):
    import numpy as np
    import soundfile as sf
    from scripts import kaggle_task_worker as worker
    monkeypatch.setenv('OPENDUB_REMOTE_EXECUTION','1')
    work=tmp_path/'work';out=tmp_path/'out';work.mkdir();out.mkdir()
    sf.write(work/'speech.wav',np.sin(np.arange(16000)*.13)*.1,16000)
    items=[{'id':'0','operation':'fit','input':'speech.wav','params':{'target':1.2},'normalize':-20},
           {'id':'1','operation':'normalize','input':'speech.wav','params':{'target_lufs':-20}}]
    result=worker.execute({'operation':'audio_batch','params':{'items':items},'model':{}},work,out)
    assert set(result['items'])=={'0','1'}
    assert abs(sf.info(out/'0/fit.wav').duration-1.2)<.03
    assert (out/'0/normalized.wav').is_file() and (out/'1/normalized.wav').is_file()
    assert result['items']['0']['fit']['speech_truncated'] is False


def test_cloud_fit_batch_bounds_sessions_and_keeps_existing_checkpoints(project,monkeypatch):
    from backend import kaggle_operations as operations
    source=project/'speech.wav';source.write_bytes(b'validated speech')
    units=[{'segment_index':i,'duration_sec':1.,'tts':{'audio_path':str(source)}} for i in range(19)]
    calls=[]
    def execute(base,op,params,files,outputs,**kw):
        calls.append(params['items']);return {'items':{str(row['id']):{'fit':{'file':'output'}} for row in params['items']}}
    monkeypatch.setattr(operations,'execute',execute)
    result=operations.fit_batch(project,units,[],1.25,.82,True,-16,False,lambda:False)
    assert [len(rows) for rows in calls]==[16,3] and len(result)==19
    units[0]['timing']={'status':'completed','fit_policy_version':2,'target_duration_sec':1.,'applied_tempo':1.}
    units[0]['loudness']={'status':'completed'}
    (project/'segments').mkdir();(project/'segments/segment_000000_fit.wav').write_bytes(b'fit');(project/'segments/segment_000000_normalized.wav').write_bytes(b'normalized')
    calls.clear();operations.fit_batch(project,units,[],1.25,.82,True,-16,False,lambda:False)
    assert sum(len(rows) for rows in calls)==18


def test_cloud_leveling_batches_preserve_fitted_sources(project,monkeypatch):
    from backend import kaggle_operations as operations
    source=project/'fit.wav';source.write_bytes(b'accepted fitted audio');before=digest(source)
    units=[{'segment_index':i,'timing':{'fit_audio':str(source)}} for i in range(18)]
    calls=[]
    def execute(base,op,params,files,outputs,**kw):
        calls.append(params['items'])
        return {'items':{row['id']:{'normalize':{'file':str(outputs[row['id']+'/normalized.wav'])}} for row in params['items']}}
    monkeypatch.setattr(operations,'execute',execute)
    result=operations.normalize_batch(project,units,-20,lambda:False)
    assert [len(rows) for rows in calls]==[16,2] and len(result)==18 and digest(source)==before
    assert all(row['params']['target_lufs']==-20 for batch in calls for row in batch)
