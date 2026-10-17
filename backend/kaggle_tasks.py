"""General immutable task contract for the complete remote media pipeline."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import zipfile
from .chunk_execution import digest,save_json
from .compute_settings import read_settings
from . import kaggle_jobs as jobs
from .kaggle_models import recipe,ensure_private_model,ModelPending
from .kaggle_transport import run,ProviderError,kernel_status,dataset_ready

ROOT=Path(__file__).resolve().parents[1]
OPERATIONS={'transcription','separation','diarization','synthesis','synthesis_batch','audio_batch','fit','normalize','background','mix','render','probe'}
GPU_OPERATIONS={'transcription','separation','diarization','synthesis','synthesis_batch'}


class RemoteWaiting(RuntimeError):pass


def raise_if_waiting(error):
    pending=waiting_error(error)
    if pending:raise pending


def waiting_error(error):
    seen=set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error,RemoteWaiting):return error
        error=error.__cause__ or error.__context__
    return None


def project_for(path):
    if os.getenv('OPENDUB_REMOTE_EXECUTION')=='1':return None
    path=Path(path).resolve()
    for base in [path,*path.parents]:
        if (base/'compute-settings.json').is_file():
            return base if read_settings(base)['provider']=='kaggle' else None
    return None


def worker_revision():
    checksum=hashlib.sha256()
    paths=[*(ROOT/'backend').glob('*.py'),ROOT/'scripts/kaggle_task_worker.py',ROOT/'scripts/clone_voice_worker.py']
    for path in sorted(paths):checksum.update(path.name.encode());checksum.update(path.read_bytes())
    return checksum.hexdigest()


def safe_name(name):
    path=Path(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name or not name or path.as_posix() in {'.',''}:
        raise ValueError('Invalid portable artifact name.')
    return path.as_posix()


def payload_sources(files):
    return {**files,**{'src/backend/'+p.name:p for p in (ROOT/'backend').glob('*.py')},
            'src/scripts/clone_voice_worker.py':ROOT/'scripts/clone_voice_worker.py'}


def payload_records(files):
    return [{'file':n,'sha256':digest(p),'size':p.stat().st_size} for n,p in sorted(payload_sources(files).items())]


def _publish_input(base,job,files,model_handle):
    task=json.loads(job['request']);folder=Path(base)/'kaggle'/job['id'];upload=folder/'input';kernel=folder/'kernel'
    upload.mkdir(parents=True,exist_ok=True);kernel.mkdir(exist_ok=True)
    if job['dataset_state']!='created':
        if job['dataset_state']=='prepared':
            from .kaggle_privacy import check_source,check_metadata
            check_metadata(task)
            for path in [*(ROOT/'backend').glob('*.py'),ROOT/'scripts/clone_voice_worker.py',ROOT/'scripts/kaggle_task_worker.py']:check_source(path)
            if payload_records(files)!=task.get('payload_files'):raise RuntimeError('Task input or worker source changed before upload.')
            with zipfile.ZipFile(upload/'payload.zip','w',zipfile.ZIP_STORED,allowZip64=True) as archive:
                for name,path in payload_sources(files).items():archive.write(path,safe_name(name))
            save_json(upload/'task-request.json',{**task,'fingerprint':job['fingerprint'],'payload_sha256':digest(upload/'payload.zip')})
            save_json(upload/'dataset-metadata.json',{'id':job['dataset_handle'],'title':job['dataset_handle'].split('/')[1],'licenses':[{'name':'other'}]})
            jobs.update(base,job['id'],'submitting','Uploading private task input.',dataset_state='uploading')
            try:run(task['username'],['datasets','create','-p',str(upload)],timeout=1800)
            except ProviderError as exc:
                jobs.update(base,job['id'],'waiting' if exc.kind=='quota' else 'submission_uncertain',str(exc))
                raise RemoteWaiting('Task input upload requires reconciliation; completed units retained.') from None
        # For an uncertain upload, only inspect the existing handle; never create again.
        status=run(task['username'],['datasets','status',job['dataset_handle']],timeout=60).lower()
        if not dataset_ready(status):
            raise RemoteWaiting('Private task input is processing on Kaggle; resume later.')
        jobs.update(base,job['id'],'submitting','Private input ready.',dataset_state='created')
    request_gpu=task['operation'] in GPU_OPERATIONS
    metadata={'id':job['kernel_handle'],'title':job['kernel_handle'].split('/')[1],
        'code_file':'worker.py','language':'python','kernel_type':'script','is_private':True,
        'enable_gpu':request_gpu,'enable_internet':True,
        'machine_shape':task['accelerator'] if request_gpu else '',
        'dataset_sources':[job['dataset_handle']]+([model_handle] if model_handle else []),
        'competition_sources':[],'kernel_sources':[],'model_sources':[]}
    save_json(kernel/'kernel-metadata.json',metadata)
    shutil.copyfile(ROOT/'scripts/kaggle_task_worker.py',kernel/'worker.py')
    return folder


def _collect(base,job):
    task=json.loads(job['request']);folder=Path(base)/'kaggle'/job['id'];download=folder/'task-download'/job['kernel_handle'].split('/')[-1]
    jobs.update(base,job['id'],'downloading','Downloading immutable task outputs.')
    run(task['username'],['kernels','output',job['kernel_handle'],'-p',str(download),'--force','--file-pattern',r'(^|/)task-output/.*'],timeout=1800)
    receipts=list(download.rglob('task-receipt.json'))
    if len(receipts)!=1:raise RuntimeError('Remote completion has no unique task receipt.')
    receipt=json.loads(receipts[0].read_text(encoding='utf-8'))
    if receipt.get('fingerprint')!=job['fingerprint'] or receipt.get('operation')!=task['operation']:
        raise RuntimeError('Remote receipt/source/config does not match the current task.')
    if receipt.get('status')!='completed':
        kind=receipt.get('failure_kind','processing')
        jobs.update(base,job['id'],'review_required','Remote '+kind+' failure. Completed units retained.')
        raise RemoteWaiting('Remote task needs '+kind+' review; no automatic clone or source replay.')
    expected=set(task['expected_outputs']);records=receipt.get('outputs') or []
    if {r.get('file') for r in records}!=expected or len(records)!=len(expected):raise RuntimeError('Remote output set is incomplete/unexpected.')
    for record in records:
        name=safe_name(record['file']);path=receipts[0].parent/name
        if path.is_symlink() or not path.resolve().is_relative_to(receipts[0].parent.resolve()) or not path.is_file() or path.stat().st_size!=record['size'] or digest(path)!=record['sha256']:
            raise RuntimeError('Remote task output failed size/hash validation.')
    completed=folder/'task-completed';completed.mkdir(exist_ok=True)
    for record in records:
        name=record['file'];source=receipts[0].parent/name;target=completed/name;target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists() and digest(target)!=record['sha256']:raise RuntimeError('Existing completed artifact differs; it was retained.')
        if not target.exists():
            pending=target.with_name(target.name+'.pending');shutil.copyfile(source,pending);pending.replace(target)
    save_json(completed/'task-receipt.json',receipt)
    jobs.update(base,job['id'],'completed','Remote task downloaded and hash verified.')
    return receipt,completed


def execute(base,operation,params,files,outputs,*,cancelled=lambda:False,progress=None):
    from .kaggle_lock import account_lock
    with account_lock(base,read_settings(base)['username'],wait=True,cancelled=cancelled):
        return _execute(base,operation,params,files,outputs,cancelled=cancelled,progress=progress)


def materialize(value,files,outputs):
    if isinstance(value,dict):return {k:materialize(v,files,outputs) for k,v in value.items()}
    if isinstance(value,list):return [materialize(v,files,outputs) for v in value]
    if isinstance(value,str):
        if value.startswith('@output/') and value[8:] in outputs:return str(outputs[value[8:]])
        if value.startswith('@input/') and value[7:] in files:return str(files[value[7:]])
    return value


def _execute(base,operation,params,files,outputs,*,cancelled=lambda:False,progress=None):
    """One serial, resumable task. Caller owns semantic/media QA and review gates."""
    base=Path(base);settings=read_settings(base)
    if operation not in OPERATIONS or settings['provider']!='kaggle':raise ValueError('Invalid remote task/provider.')
    if not settings.get('allow_media_upload'):raise RuntimeError('Private input upload has not been selected for this project.')
    files={safe_name(n):Path(p).resolve() for n,p in files.items()};outputs={safe_name(n):Path(p) for n,p in outputs.items()}
    records=[{'file':n,'sha256':digest(p),'size':p.stat().st_size} for n,p in sorted(files.items())]
    model=recipe(base,operation,params)
    task={'schema_version':2,'operation':operation,'params':params,'inputs':records,'payload_files':payload_records(files),'model':model,
          'expected_outputs':sorted(outputs),'username':settings['username'],'accelerator':settings['accelerator'],
          'worker_revision':worker_revision()}
    job=jobs.create(base,task,settings['username'])
    from . import app as studio
    with studio.connect(studio.DB_PATH) as conn:
        parent=conn.execute("SELECT id FROM jobs WHERE project_id=? AND status IN ('running','claimed') ORDER BY created_at DESC LIMIT 1",(base.name,)).fetchone()
    if parent:jobs.set_control(base,job['id'],parent_job_id=parent['id'])
    try:
        if job['state']=='completed':
            folder=base/'kaggle'/job['id']/'task-completed';receipt=json.loads((folder/'task-receipt.json').read_text(encoding='utf-8'))
        else:
            # A model dataset is independently reconciled before any notebook push.
            try:model_handle=ensure_private_model(base,settings,operation,model)
            except ModelPending as exc:
                jobs.update(base,job['id'],'waiting',str(exc))
                raise RemoteWaiting(str(exc)) from None
            if job['state']=='prepared':
                try:job=jobs.claim_submission(base,job['id'])
                except RuntimeError as exc:raise RemoteWaiting(str(exc)) from None
            if job['state'] in {'submitting','submission_uncertain','waiting'}:
                if job['dataset_state']!='created':
                    _publish_input(base,job,files,model_handle);job=jobs.get(base,job['id'])
                if job['kernel_state']=='not_submitted':
                    folder=_publish_input(base,job,files,model_handle)
                    # This persistent state precedes push; an ambiguous crash is reconciled.
                    jobs.update(base,job['id'],'submission_uncertain','Notebook submission in progress; reconcile this exact handle.')
                    jobs.set_control(base,job['id'],kernel_state='submitting')
                    args=['kernels','push','-p',str(folder/'kernel'),'--timeout','10800']
                    if operation in GPU_OPERATIONS:args+=['--accelerator',settings['accelerator']]
                    try:run(settings['username'],args,timeout=180)
                    except ProviderError as exc:raise RemoteWaiting('Notebook submission uncertain: '+str(exc)) from None
                    jobs.update(base,job['id'],'queued','Submitted to Kaggle; awaiting actual allocation.')
                    jobs.set_control(base,job['id'],kernel_state='submitted')
            while True:
                if cancelled():raise InterruptedError('Remote coordinator paused. Existing notebook/checkpoints retained; monitor Kaggle for remote usage.')
                current=read_settings(base)
                if current['provider']!='kaggle' or current['username']!=task['username']:raise InterruptedError('Compute/account choice changed; no automatic local fallback.')
                state=kernel_status(task['username'],jobs.get(base,job['id'])['kernel_handle'])
                if state=='completed':receipt,folder=_collect(base,jobs.get(base,job['id']));break
                if state in {'failed','cancelled'}:
                    # Try a failure receipt when execution itself stopped. It can distinguish model/code/OOM.
                    try:receipt,folder=_collect(base,jobs.get(base,job['id']));break
                    except RemoteWaiting:raise
                    except Exception:pass
                    jobs.update(base,job['id'],'review_required','Remote session ended without a valid completed receipt; completed units retained.')
                    raise RemoteWaiting('Remote session ended. Reconcile/retry only this unfinished task.')
                if state not in {'queued','running'}:raise RemoteWaiting('Remote state is unknown; existing handle retained without duplicate submission.')
                jobs.update(base,job['id'],state,'Kaggle task '+state+'; completed tasks retained.')
                if progress:progress(state,job['id'])
                for _ in range(15):
                    if cancelled():raise InterruptedError('Cloud coordinator paused; remote work retained.')
                    time.sleep(1)
        # Revalidate every reused result, and input files immediately before publishing.
        if receipt.get('fingerprint')!=job['fingerprint'] or receipt.get('status')!='completed' or receipt.get('operation')!=operation:raise RuntimeError('Saved task receipt is stale.')
        if {r['file'] for r in receipt['outputs']}!=set(outputs):raise RuntimeError('Cached task output set is incomplete.')
        if any(digest(files[r['file']])!=r['sha256'] for r in records):raise RuntimeError('Task input changed while processing; results retained separately.')
        for record in receipt['outputs']:
            name=safe_name(record['file']);source=folder/name;target=outputs[name]
            if digest(source)!=record['sha256']:raise RuntimeError('Cached task output changed.')
            target.parent.mkdir(parents=True,exist_ok=True)
            data=None
            if source.suffix.lower()=='.json':
                data=json.dumps(materialize(json.loads(source.read_text(encoding='utf-8')),files,outputs),ensure_ascii=False,indent=2).encode('utf-8')
            local_sha=hashlib.sha256(data).hexdigest() if data is not None else record['sha256']
            if target.is_file() and digest(target)==local_sha:continue
            if target.is_file():
                history=target.parent/'history'/target.stem;history.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(target,history/(digest(target)+target.suffix))
            pending=target.with_name(target.name+'.remote-pending')
            if source.suffix.lower()=='.json':pending.write_bytes(data)
            else:shutil.copyfile(source,pending)
            pending.replace(target)
        return materialize(receipt['result'],files,outputs)
    except ProviderError as exc:
        jobs.update(base,job['id'],'waiting' if exc.kind=='quota' else 'submission_uncertain',str(exc))
        raise RemoteWaiting(str(exc)) from None
