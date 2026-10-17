"""Pinned model contracts; gated snapshots travel privately, never their token."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import zipfile
from .chunk_execution import digest,save_json
from .kaggle_runtime import invoke
from .kaggle_transport import run,ProviderError,dataset_ready

COMMUNITY='pyannote/speaker-diarization-community-1'


def model_pin(base,repo,download=False):
    from . import app as studio
    cache=studio.DATA_ROOT/'kaggle-models'/repo.replace('/','--');cache.mkdir(parents=True,exist_ok=True)
    marker=cache/'pin.json'
    pin=json.loads(marker.read_text(encoding='utf-8')) if marker.is_file() else None
    if not pin:
        # Prefer already acquired gated weights and their immutable HF snapshot.
        hub=Path(os.getenv('HF_HUB_CACHE') or Path(os.getenv('HF_HOME') or Path.home()/'.cache/huggingface')/'hub')
        folder=hub/('models--'+repo.replace('/','--'));ref=folder/'refs/main'
        if ref.is_file():
            revision=ref.read_text(encoding='utf-8').strip();snapshot=folder/'snapshots'/revision
            pin={'repo':repo,'revision':revision,'path':str(snapshot) if snapshot.is_dir() else None}
        else:
            result=invoke('snapshot',{'repo':repo,'download':download},timeout=1800)
            if not result.get('ok'):raise RuntimeError('Model access/download setup required; no credentials were sent to Kaggle.')
            pin=result['data']
        if not pin.get('revision'):raise RuntimeError('Model revision could not be pinned.')
        save_json(marker,pin)
    if download and not pin.get('path'):
        result=invoke('snapshot',{'repo':repo,'revision':pin['revision'],'download':True},timeout=1800)
        if not result.get('ok'):raise RuntimeError('Gated model snapshot is not locally available; accept its conditions using your own HF account.')
        pin=result['data'];save_json(marker,pin)
    return pin


class ModelPending(RuntimeError):pass


def recipe(base,operation,params):
    if operation=='transcription':
        size=params.get('model_size','small')
        repo={'large-v3':'Systran/faster-whisper-large-v3'}.get(size,'Systran/faster-whisper-'+size)
        pin=model_pin(base,repo)
        return {'repo':pin['repo'],'revision':pin['revision'],'library':'faster-whisper==1.2.1','decoder':'av==18.1.0'}
    if operation in {'synthesis','synthesis_batch'}:
        pin=model_pin(base,'k2-fsa/OmniVoice')
        model={'repo':pin['repo'],'revision':pin['revision'],'library':'omnivoice==0.2.1'}
        if operation=='synthesis_batch':
            validator=model_pin(base,'Systran/faster-whisper-small')
            model['validator']={'repo':validator['repo'],'revision':validator['revision'],'library':'faster-whisper==1.2.1','decoder':'av==18.1.0'}
        return model
    if operation=='diarization':
        pin=model_pin(base,COMMUNITY,download=True)
        return bind_files(base,operation,{'repo':pin['repo'],'revision':pin['revision'],'library':'pyannote.audio==4.0.7','private_snapshot':True})
    if operation=='separation':
        name=params.get('model_filename','vocals_mel_band_roformer.ckpt')
        root=Path(__file__).resolve().parents[1]/'runtime/models/separation'
        path=root/name
        if not path.is_file():raise RuntimeError('Acquire the selected separation model locally first, so its exact checksum can bind the remote request.')
        return bind_files(base,operation,{'filename':name,'sha256':digest(path),'library':'audio-separator[gpu]==0.47.0','private_snapshot':True})
    return {}


def bind_files(base,operation,model):
    files=model_files(base,operation,model)
    records=[{'file':name,'sha256':digest(path),'size':path.stat().st_size} for name,path in sorted(files.items())]
    return {**model,'files_sha256':hashlib.sha256(json.dumps(records,sort_keys=True).encode()).hexdigest()}


def model_files(base,operation,model):
    if operation=='separation':
        path=Path(__file__).resolve().parents[1]/'runtime/models/separation'/model['filename']
        paths={model['filename']:path}
        yaml=path.with_suffix('.yaml')
        if yaml.is_file():paths[yaml.name]=yaml
        return paths
    pin=model_pin(base,model['repo'],download=True);root=Path(pin['path'])
    required=['config.yaml','segmentation/pytorch_model.bin','embedding/pytorch_model.bin','plda/plda.npz','plda/xvec_transform.npz']
    paths={name:root/name for name in required}
    if any(not p.is_file() for p in paths.values()):raise RuntimeError('Offline Community-1 snapshot is incomplete.')
    for name in ('README.md','LICENSE','LICENSE.md'):
        if (root/name).is_file():paths[name]=root/name
    return paths


def ensure_private_model(base,settings,operation,model):
    if not model.get('private_snapshot'):return None
    if not settings.get('allow_model_upload'):raise RuntimeError('Enable private model-file upload for this project; HF/API tokens will stay local.')
    from . import app as studio
    files=model_files(base,operation,model)
    records=[{'file':name,'sha256':digest(path),'size':path.stat().st_size} for name,path in sorted(files.items())]
    key=hashlib.sha256(json.dumps({'model':model,'files':records},sort_keys=True).encode()).hexdigest()[:24]
    handle=settings['username']+'/opendub-model-'+key
    folder=studio.DATA_ROOT/'kaggle-models'/'datasets'/settings['username']/key;folder.mkdir(parents=True,exist_ok=True)
    upload=folder/'upload';upload.mkdir(exist_ok=True)
    state_path=folder/'state.json'
    state=json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {'state':'prepared','handle':handle}
    if state['state']!='ready':
        if state['state']=='prepared':
            with zipfile.ZipFile(upload/'model.payload.zip','w',zipfile.ZIP_STORED,allowZip64=True) as archive:
                for name,path in files.items():archive.write(path,name)
            save_json(upload/'model-manifest.json',{'model':model,'files':records,'payload_sha256':digest(upload/'model.payload.zip')})
            save_json(upload/'dataset-metadata.json',{'id':handle,'title':handle.split('/')[1],
                'licenses':[{'name':'CC-BY-4.0' if operation=='diarization' else 'other'}]})
            save_json(state_path,{**state,'state':'uploading'})
            try:run(settings['username'],['datasets','create','-p',str(upload)],timeout=1800)
            except ProviderError:
                save_json(state_path,{**state,'state':'uncertain'})
                raise ModelPending('Private model upload needs reconciliation; it will not be blindly uploaded again.') from None
        status=run(settings['username'],['datasets','status',handle],timeout=60).lower()
        if not dataset_ready(status):raise ModelPending('Private model dataset is still processing. Wait and resume; no notebook was submitted.')
        # Runtime also verifies manifest/model hashes before loading any weights.
        save_json(state_path,{'state':'ready','handle':handle})
    return handle
