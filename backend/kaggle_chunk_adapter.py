"""Stage adapter for bounded cloud ASR/stems; full Auto-Dub remains gated."""
import json
import shutil
import time
from pathlib import Path
from .compute_settings import read_settings
from . import kaggle_service as service
from .chunk_execution import digest,save_json


class CloudPending(RuntimeError):
    """A waiting provider is resumable work, not evidence of a processed chunk."""


def cloud_project(folder):
    for base in Path(folder).resolve().parents:
        if (base/'compute-settings.json').is_file():
            return base if read_settings(base)['provider']=='kaggle' else None
    return None


def run_remote(spec,folder,cancelled=lambda:False):
    """Return the same artifact contract as a native chunk helper."""
    base=cloud_project(folder)
    if base is None:raise RuntimeError('This chunk is not configured for Kaggle.')
    if spec['operation'] not in {'transcription','separation'}:raise RuntimeError('This model stage has no remote adapter yet.')
    start,end=spec['context_start'],spec['context_end']
    if end-start>120:raise RuntimeError('Cloud chunks must be partitioned to at most 120 seconds before execution.')
    job=service.create_request(base,Path(spec['source']),spec['operation'],start,end,
        model_size=spec.get('model_size','small'),language=spec.get('language'),
        model_filename=spec.get('model_filename','vocals_mel_band_roformer.ckpt'))
    if job['state']=='prepared':
        service.prepare_request(base,job['id'],Path(spec['source']))
        job=service.submit(base,job['id'])
    while job['state'] in {'queued','running','downloading','submitting'}:
        if cancelled():raise InterruptedError('Cloud coordinator paused locally; remote attempt and completed units retained. Monitor the notebook on Kaggle.')
        time.sleep(15)
        job=service.reconcile(base,job['id'])
    if job['state']!='completed':
        raise CloudPending(job['message']+' Existing handle retained; no duplicate or CPU fallback was started.')
    completed=base/'kaggle'/job['id']/'completed'
    receipt=json.loads((completed/'receipt.json').read_text(encoding='utf-8'))
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    paths=[]
    for record in receipt['outputs']:
        source=completed/record['file'];target=folder/record['file']
        if digest(source)!=record['sha256']:raise RuntimeError('A saved remote artifact changed; checkpoint cannot be reused.')
        if target.exists() and digest(target)!=record['sha256']:raise RuntimeError('Existing local chunk differs; preserve it for review.')
        if not target.exists():
            pending=target.with_name(target.name+'.pending');shutil.copyfile(source,pending);pending.replace(target)
        paths.append(str(target.resolve()))
    payload=json.loads((folder/'transcript.json').read_text(encoding='utf-8')) if spec['operation']=='transcription' else {
        key:str((folder/(key+'.wav')).resolve()) for key in ('dialogue_candidate','background_candidate')}
    result={'outputs':paths,'payload':payload,'compute_provider':'kaggle','remote_job_id':job['id'],
            'source_time_offset':start,'gpu':receipt['gpu']}
    save_json(folder/'result.json',result)
    return result
