"""Private Kaggle bounded worker. No credentials are included in this script."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


def sha(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):value.update(block)
    return value.hexdigest()


def main():
    inputs=list(Path('/kaggle/input').glob('*/request.json'))
    if len(inputs)!=1:raise RuntimeError('Exactly one bound input dataset is required.')
    source=inputs[0].parent;request=json.loads(inputs[0].read_text())
    if request['operation'] not in {'transcription','separation'}:raise ValueError('Unsupported operation.')
    if sha(source/'input.wav')!=request['input_sha256']:raise RuntimeError('Input hash mismatch.')
    if sha(source/'worker-source.zip')!=request['worker_archive_sha256']:raise RuntimeError('Worker source hash mismatch.')
    root=Path('/kaggle/working/opendub');root.mkdir(exist_ok=True)
    with zipfile.ZipFile(source/'worker-source.zip') as archive:
        for item in archive.infolist():
            path=(root/item.filename).resolve()
            if not path.is_relative_to(root.resolve()) or not item.filename.startswith('backend/'):
                raise RuntimeError('Invalid worker archive path.')
        archive.extractall(root)
    sys.path.insert(0,str(root))
    import torch
    if not torch.cuda.is_available():raise RuntimeError('Requested GPU was not allocated; input/checkpoint retained locally.')
    device=max(range(torch.cuda.device_count()),key=lambda i:torch.cuda.mem_get_info(i)[0])
    os.environ['CUDA_VISIBLE_DEVICES']=str(device)
    # Install only operation-specific libraries; use Kaggle's existing CUDA Torch.
    dependencies=['faster-whisper==1.2.1'] if request['operation']=='transcription' else ['audio-separator[gpu]==0.47.0','librosa>=0.10,<1.0','audioread>=3,<4']
    subprocess.run([sys.executable,'-m','pip','install',*dependencies],check=True)
    if request['operation']=='separation':
        import onnxruntime as ort
        if 'CUDAExecutionProvider' not in ort.get_available_providers():raise RuntimeError('Separation CUDA provider is unavailable; no silent CPU fallback.')
    folder=root/'result';folder.mkdir(exist_ok=True)
    from backend.chunk_execution import save_json
    spec={'id':'cloud-unit','operation':request['operation'],'source':str(source/'input.wav'),
          'context_start':0,'context_end':request['end']-request['start'],'start':0,'end':request['end']-request['start'],
          'ffmpeg':shutil.which('ffmpeg'),'threads':2,'device':'cuda','model_size':request['model_size'],
          'language':request.get('language'),'model_filename':request['model_filename']}
    if request['operation']=='separation':spec['target_frames']=round(request['end']*48000)-round(request['start']*48000)
    if not spec['ffmpeg']:raise RuntimeError('FFmpeg is unavailable in this notebook.')
    save_json(folder/'request.json',spec)
    subprocess.run([sys.executable,'-u','-m','backend.chunk_worker',str(folder/'request.json')],cwd=root,check=True)
    result=json.loads((folder/'result.json').read_text())
    records=[]
    for value in result['outputs']:
        path=Path(value).resolve()
        if not path.is_relative_to(folder.resolve()):raise RuntimeError('Output escapes the bounded result folder.')
        records.append({'file':path.name,'size':path.stat().st_size,'sha256':sha(path)})
    import importlib.metadata
    packages={}
    for name in ('torch','faster-whisper','audio-separator','onnxruntime-gpu'):
        try:packages[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:pass
    model_path=root/'runtime/models/separation'/request['model_filename']
    receipt={'schema_version':1,'fingerprint':request['fingerprint'],'source_sha256':request['source_sha256'],
             'source_time_offset':request['start'],'status':'completed','operation':request['operation'],'outputs':records,
             'gpu':{'name':torch.cuda.get_device_name(device),'index':device},'result':result,
             'runtime_packages':packages,'model_sha256':sha(model_path) if model_path.is_file() else None,
             'asr_model_revision':'unverified' if request['operation']=='transcription' else None}
    save_json(folder/'receipt.json',receipt)


if __name__=='__main__':main()
