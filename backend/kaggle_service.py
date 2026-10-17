"""Explicit remote submission/reconciliation, independently durable completed units."""
import json
import re
import shutil
from pathlib import Path
from . import kaggle_jobs as jobs
from .compute_settings import read_settings
from .kaggle_bundle import prepare,worker_revision
from .kaggle_transport import run,kernel_status,ProviderError
from .chunk_execution import digest,save_json


def source_fingerprint(base,source):
    source=Path(source).resolve();base=Path(base).resolve()
    if not source.is_relative_to(base):raise ValueError('Source is outside this project.')
    stat=source.stat();key={'file':source.relative_to(base).as_posix(),'bytes':stat.st_size,'mtime_ns':stat.st_mtime_ns,'ctime_ns':stat.st_ctime_ns}
    path=base/'kaggle/source-fingerprint.json'
    try:cached=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):cached={}
    if cached.get('key')!=key:
        cached={'key':key,'sha256':digest(source)};save_json(path,cached)
    return cached['sha256']


def create_request(base, source, operation, start, end, model_size='small', language=None, model_filename='vocals_mel_band_roformer.ckpt'):
    settings=read_settings(base)
    if settings['provider']!='kaggle':raise ValueError('Select Kaggle for this project first.')
    if not settings['allow_media_upload']:raise ValueError('Select private media upload before preparing a remote job.')
    if operation not in {'transcription','separation'} or not 0<=start<end or end-start>120:
        raise ValueError('Select ASR/separation and a valid crop of at most 120 seconds.')
    if not isinstance(model_filename,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,180}',model_filename) or '..' in model_filename:
        raise ValueError('Select a valid separator model filename.')
    request={'operation':operation,'start':start,'end':end,'model_size':model_size,'language':language,
             'model_filename':model_filename,'source_sha256':source_fingerprint(base,source),
             'source_relative':Path(source).resolve().relative_to(Path(base).resolve()).as_posix(),
             'accelerator':settings['accelerator'],'username':settings['username'],
             'worker_revision':worker_revision(),'schema_version':1}
    return jobs.create(base,request,settings['username'])


def prepare_request(base, job_id, source):
    job=jobs.get(base,job_id)
    if job['state']!='prepared':raise RuntimeError('Only an unsubmitted intent can be prepared.')
    prepare(base,job,source)
    return jobs.update(base,job_id,'prepared','Input crop and private worker prepared locally; nothing uploaded yet.')


def submit(base, job_id):
    settings=read_settings(base);job=jobs.get(base,job_id);request=json.loads(job['request'])
    if not settings['allow_media_upload'] or settings['provider']!='kaggle' or settings['username']!=request['username']:
        raise RuntimeError('Project account/upload selection changed; submission is blocked.')
    if source_fingerprint(base,Path(base)/request['source_relative'])!=request['source_sha256']:
        raise RuntimeError('Source changed; stale remote input will not be submitted.')
    folder=Path(base)/'kaggle'/job_id
    if not (folder/'dataset/input.wav').exists():raise RuntimeError('Prepare the bounded input first.')
    metadata=json.loads((folder/'kernel/kernel-metadata.json').read_text(encoding='utf-8'))
    dataset=json.loads((folder/'dataset/dataset-metadata.json').read_text(encoding='utf-8'))
    if metadata.get('is_private') is not True or metadata.get('id')!=job['kernel_handle'] or dataset.get('id')!=job['dataset_handle'] or metadata.get('dataset_sources')!=[job['dataset_handle']]:
        raise RuntimeError('Private account-bound metadata validation failed; nothing was submitted.')
    prepared=json.loads((folder/'dataset/request.json').read_text(encoding='utf-8'))
    if prepared.get('fingerprint')!=job['fingerprint'] or digest(folder/'dataset/input.wav')!=prepared.get('input_sha256') or digest(folder/'dataset/worker-source.zip')!=prepared.get('worker_archive_sha256'):
        raise RuntimeError('Prepared input/source bundle changed; nothing was submitted.')
    job=jobs.claim_submission(base,job_id)
    try:
        # Mark upload intent before the mutation; a timeout must be reconciled too.
        if job['dataset_state']!='created':
            jobs.update(base,job_id,'submitting','Uploading a private bounded input.',dataset_state='uploading')
            run(request['username'],['datasets','create','-p',str(folder/'dataset')],timeout=900)
            jobs.update(base,job_id,'submitting','Private dataset created; submitting notebook.',dataset_state='created')
        run(request['username'],['kernels','push','-p',str(folder/'kernel'),'--timeout','3600','--accelerator',request['accelerator']],timeout=180)
        return jobs.update(base,job_id,'queued','Submitted to Kaggle; requested GPU is not guaranteed until allocated.')
    except ProviderError as exc:
        # Even a quota error can follow a created notebook version. Reconcile first.
        state='waiting' if exc.kind=='quota' else 'submission_uncertain'
        return jobs.update(base,job_id,state,str(exc))
    except Exception:
        jobs.update(base,job_id,'submission_uncertain','Submission interrupted; reconcile remote handles before retrying.')
        raise


def retry(base,job_id):
    current=jobs.get(base,job_id)
    state=kernel_status(json.loads(current['request'])['username'],current['kernel_handle'])
    if state not in {'failed','cancelled'}:raise RuntimeError('The old remote attempt is not terminal; retry blocked.')
    job=jobs.retry_terminal(base,job_id)
    root=Path(base)/'kaggle'/job_id
    metadata=json.loads((root/'kernel/kernel-metadata.json').read_text(encoding='utf-8'))
    metadata.update(id=job['kernel_handle'],title=job['kernel_handle'].split('/')[1])
    save_json(root/'kernel/kernel-metadata.json',metadata)
    return submit(base,job_id)


def reconcile(base, job_id):
    job=jobs.get(base,job_id);username=json.loads(job['request'])['username']
    if job['state']=='completed':return job
    try:
        state=kernel_status(username,job['kernel_handle'])
    except ProviderError as exc:
        # Absence can be eventual consistency, a dataset-only upload, or auth failure.
        return jobs.update(base,job_id,'submission_uncertain',str(exc)+' No automatic duplicate was submitted.')
    if state=='completed':return download(base,job_id)
    if state in {'failed','cancelled'}:
        return jobs.update(base,job_id,'review_required','Remote attempt is terminal. Completed local chunks remain; inspect the cause before a new attempt.')
    if state in {'queued','running'}:return jobs.update(base,job_id,state,'Actual Kaggle notebook status: '+state)
    return jobs.update(base,job_id,'submission_uncertain','Provider status is unknown; no automatic duplicate was submitted.')


def download(base, job_id):
    job=jobs.get(base,job_id);root=Path(base)/'kaggle'/job_id;destination=root/'download'
    jobs.update(base,job_id,'downloading','Retrieving output and verifying the bound result receipt.')
    run(json.loads(job['request'])['username'],['kernels','output',job['kernel_handle'],'-p',str(destination),
        '--file-pattern',r'(^|/)result/(receipt\.json|transcript\.json|dialogue_candidate\.wav|background_candidate\.wav|result\.json)$'],timeout=900)
    receipts=list(destination.rglob('receipt.json'))
    if len(receipts)!=1:raise RuntimeError('A unique completed receipt is missing; output was not imported.')
    receipt=json.loads(receipts[0].read_text(encoding='utf-8'));request=json.loads(job['request'])
    if receipt.get('status')!='completed' or receipt.get('fingerprint')!=job['fingerprint'] or receipt.get('source_sha256')!=request['source_sha256']:
        raise RuntimeError('Output receipt does not match this source/config request.')
    if receipt.get('operation')!=request['operation'] or not receipt.get('outputs'):
        raise RuntimeError('Output operation or artifact list is invalid.')
    if source_fingerprint(base,Path(base)/request['source_relative'])!=request['source_sha256']:
        raise RuntimeError('Project source changed; old remote results are retained but will not be applied.')
    allowed={'transcription':{'transcript.json'},'separation':{'dialogue_candidate.wav','background_candidate.wav'}}[request['operation']]
    seen=set();validated=[]
    for record in receipt['outputs']:
        name=record['file']
        if name not in allowed or name in seen:raise RuntimeError('Unexpected output filename.')
        seen.add(name);path=receipts[0].parent/name
        if not path.is_file() or path.stat().st_size!=record['size'] or digest(path)!=record['sha256']:
            raise RuntimeError('Output hash/size mismatch; existing checkpoints retained.')
        if request['operation']=='separation':
            import soundfile as sf
            info=sf.info(path);expected=round(request['end']*48000)-round(request['start']*48000)
            if info.samplerate!=48000 or info.channels!=2 or info.frames!=expected:raise RuntimeError('Remote stem format/duration does not match the crop.')
        else:
            data=json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(data.get('segments'),list):raise RuntimeError('Transcript schema is invalid.')
        validated.append((path,name))
    if seen!=allowed:raise RuntimeError('Required remote artifacts are incomplete.')
    imported=root/'completed';imported.mkdir(exist_ok=True)
    for path,name in validated:
        target=imported/name
        if target.exists() and digest(target)!=digest(path):raise RuntimeError('A completed artifact already exists with different content.')
        if not target.exists():shutil.copyfile(path,target.with_suffix(target.suffix+'.pending'));target.with_suffix(target.suffix+'.pending').replace(target)
    save_json(imported/'receipt.json',receipt)
    return jobs.update(base,job_id,'completed','Bounded remote artifacts downloaded and hash-verified; pipeline application is a separate step.')
