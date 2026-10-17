"""Explicit small input bundle, never a full runtime/repository upload."""
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from .chunk_execution import digest,save_json

ROOT = Path(__file__).resolve().parents[1]
# Source required for bounded ASR/separation only. Model stages get separate adapters.
SOURCE = sorted(str(path.relative_to(ROOT)).replace('\\','/') for path in (ROOT/'backend').glob('*.py'))


def worker_revision():
    import hashlib
    value=hashlib.sha256()
    for name in SOURCE+['scripts/kaggle_worker.py']:
        value.update(name.encode());value.update((ROOT/name).read_bytes())
    return value.hexdigest()


def prepare(base, job, source):
    request = json.loads(job['request'])
    if request['operation'] not in {'transcription','separation'}:
        raise ValueError('This bounded worker currently supports ASR/separation only.')
    duration = request['end']-request['start']
    if not 0 < duration <= 120: raise ValueError('Each cloud request must be bounded to at most 120 seconds.')
    if digest(Path(source)) != request['source_sha256']:
        raise ValueError('Source changed since the request was prepared.')
    folder = Path(base)/'kaggle'/job['id'];dataset = folder/'dataset';kernel = folder/'kernel'
    dataset.mkdir(parents=True,exist_ok=True);kernel.mkdir(parents=True,exist_ok=True)
    clip = dataset/'input.wav'
    channels,rate = (2,48000) if request['operation']=='separation' else (1,16000)
    pending=dataset/'input.pending.wav'
    subprocess.run(['ffmpeg','-v','error','-y','-ss',str(request['start']),'-i',str(source),'-t',str(duration),
        '-ac',str(channels),'-ar',str(rate),'-c:a','pcm_s16le',str(pending)],capture_output=True,check=True)
    pending.replace(clip)
    with zipfile.ZipFile(dataset/'worker-source.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for name in SOURCE:
            text=(ROOT/name).read_text(encoding='utf-8')
            for pattern in (r'AIza[\w-]{30,}',r'github_pat_[A-Za-z0-9_]{40,}',r'gh[pousr]_[A-Za-z0-9]{30,}',r'hf_[A-Za-z0-9]{25,}',r'KGAT_[A-Za-z0-9_-]{15,}',r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----'):
                if re.search(pattern,text):raise RuntimeError('Credential-like source content detected. Bundle preparation stopped; nothing uploaded.')
            archive.write(ROOT/name,name)
    save_json(dataset/'request.json',{**request,'fingerprint':job['fingerprint'],'input_sha256':digest(clip),
        'worker_archive_sha256':digest(dataset/'worker-source.zip')})
    slug=job['dataset_handle'].split('/')[1]
    save_json(dataset/'dataset-metadata.json',{'id':job['dataset_handle'],'title':slug,
        'licenses':[{'name':'other'}]})
    save_json(kernel/'kernel-metadata.json',{'id':job['kernel_handle'],'title':slug,'code_file':'worker.py',
        'language':'python','kernel_type':'script','is_private':True,'enable_gpu':True,'enable_internet':True,
        'machine_shape':request['accelerator'],'dataset_sources':[job['dataset_handle']],
        'competition_sources':[],'kernel_sources':[],'model_sources':[]})
    shutil.copyfile(ROOT/'scripts/kaggle_worker.py',kernel/'worker.py')
    return folder
