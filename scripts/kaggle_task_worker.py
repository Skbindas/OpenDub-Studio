"""One private immutable OpenDub task, with a source/model-bound result receipt."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback
import zipfile
import re


def sha(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):value.update(block)
    return value.hexdigest()


def failure_diagnostic(error):
    message=str(error)
    for name,value in os.environ.items():
        if value and len(value)>=6 and any(word in name.upper() for word in ('TOKEN','SECRET','PASSWORD','API_KEY')):message=message.replace(value,'[REDACTED]')
    message=re.sub(r'(https?://[^\s?]+)\?[^\s]+',r'\1?[REDACTED]',message)
    message=re.sub(r'(?:KGAT_|hf_|github_pat_)[A-Za-z0-9_.-]+','[REDACTED]',message)
    frames=traceback.extract_tb(error.__traceback__)
    return {'type':type(error).__name__,'message':message[-1800:],
            'stack':[{'file':Path(frame.filename).name,'function':frame.name,'line':frame.lineno} for frame in frames[-8:]]}


def unpack(archive,destination):
    destination=destination.resolve();destination.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        for item in bundle.infolist():
            path=(destination/item.filename).resolve()
            if not path.is_relative_to(destination) or (item.external_attr>>16)&0o170000==0o120000:
                raise RuntimeError('Invalid archive member.')
        bundle.extractall(destination)


def restore_payload(source,name,destination,records,archive_sha256):
    """Kaggle expands uploaded ZIPs; validate every bound file in either layout."""
    archive=source/name;destination.mkdir(parents=True,exist_ok=True)
    if archive.is_file():
        if sha(archive)!=archive_sha256:raise RuntimeError('Payload archive checksum mismatch.')
        unpack(archive,destination)
        root=destination
    else:
        root=source/Path(name).stem
        if not root.is_dir():raise RuntimeError('No archive or expanded payload is available.')
    if not records:raise RuntimeError('Payload file hashes are required for expanded archive validation.')
    seen=set()
    for record in records:
        logical=record['file'];relative=Path(logical)
        if relative.is_absolute() or '..' in relative.parts or '\\' in logical or ':' in logical or logical in seen:raise RuntimeError('Invalid payload member.')
        seen.add(logical);path=root/relative
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):raise RuntimeError('Payload path escapes its input root.')
        if not path.is_file() or path.stat().st_size!=record['size'] or sha(path)!=record['sha256']:raise RuntimeError('Payload file hash mismatch.')
    # Validate the complete set before copying any expanded member.
    if root!=destination:
        for record in records:
            target=destination/record['file'];target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(root/record['file'],target)


def install(operation,work):
    deps={'transcription':['faster-whisper==1.2.1','av==18.1.0'],
          'separation':['audio-separator[gpu]==0.47.0','librosa>=0.10,<1.0','audioread>=3,<4'],
          'diarization':['pyannote.audio==4.0.7'],
          'synthesis':['omnivoice==0.2.1'],
          'synthesis_batch':['omnivoice==0.2.1','faster-whisper==1.2.1','av==18.1.0'],
          'audio_batch':['numpy','soundfile','scipy'],
          'fit':['numpy','soundfile','scipy'],'normalize':['numpy','soundfile','scipy'],
          'background':['numpy','soundfile'],'mix':['numpy','soundfile','scipy'],
          'render':[],'probe':[]}[operation]
    if not deps:return
    # Metrics >=4.1 requires NumPy >=2.2.2; Kaggle's Numba requires <2.3.
    deps=[dependency for dependency in deps if dependency!='numpy']+['numpy==2.2.6']
    constraints=[]
    for name in ('torch','torchaudio','torchvision'):
        try:constraints.append(name+'=='+importlib.metadata.version(name))
        except importlib.metadata.PackageNotFoundError:pass
    path=work/'torch-constraints.txt';path.write_text('\n'.join(constraints))
    subprocess.run([sys.executable,'-m','pip','install','-c',str(path),*deps],check=True)


def prepare_runtime(operation,work):
    # Torch imports NumPy. Never replace loaded extension modules underneath it.
    install(operation,work)
    if operation not in {'transcription','separation','diarization','synthesis','synthesis_batch'}:return None
    import torch
    if not torch.cuda.is_available():raise RuntimeError('No requested CUDA GPU was allocated.')
    selected=max(range(torch.cuda.device_count()),key=lambda i:torch.cuda.mem_get_info(i)[0])
    torch.cuda.set_device(selected);os.environ['CUDA_VISIBLE_DEVICES']=str(selected)
    return {'name':torch.cuda.get_device_name(selected),'index':selected,'cuda':torch.version.cuda}


def portable(value,work,out):
    if isinstance(value,dict):return {k:portable(v,work,out) for k,v in value.items()}
    if isinstance(value,list):return [portable(v,work,out) for v in value]
    if isinstance(value,str):
        if value.startswith(str(out)+'/'):return '@output/'+value[len(str(out))+1:]
        if value.startswith(str(work)+'/'):return '@input/'+value[len(str(work))+1:]
        if value.startswith('/kaggle/') or value.startswith('/root/.cache/'):return '@remote/'+Path(value).name
    return value


def clocked_stem(source,target,frames):
    # Separator WAVs can be 44.1kHz. Count owned samples only after resampling.
    subprocess.run(['ffmpeg','-v','error','-y','-i',str(source),'-ac','2','-ar','48000',
        '-af',f'aresample=48000,apad=whole_len={frames},atrim=end_sample={frames}',
        '-c:a','pcm_f32le',str(target)],check=True)


def execute(request,work,out):
    op=request['operation'];params=request['params'];model=request['model']
    def file(name):return work/name
    if op=='transcription':
        from huggingface_hub import snapshot_download
        from backend.media import transcribe
        snapshot=snapshot_download(repo_id=model['repo'],revision=model['revision'])
        result=transcribe(file('audio.wav'),snapshot,params.get('language'),'cuda')
        result.update(model=params['model_size'],model_revision=model['revision'],compute_provider='kaggle')
        (out/'transcript.json').write_text(json.dumps(result,ensure_ascii=False))
        return result
    if op=='separation':
        from backend.background_preservation import _separate_single
        import onnxruntime as ort
        if 'CUDAExecutionProvider' not in ort.get_available_providers():raise RuntimeError('CUDA separator provider unavailable.')
        destination=work/'src/runtime/models/separation';destination.mkdir(parents=True,exist_ok=True)
        for path in (work/'model').glob('*'):
            if path.is_file():shutil.copyfile(path,destination/path.name)
        weights=destination/model['filename']
        if sha(weights)!=model['sha256']:raise RuntimeError('Separator model checksum mismatch.')
        result=_separate_single(file('audio.wav'),work/'stems',model['filename'])
        if result.get('status')!='completed':raise RuntimeError('Neural separation did not complete.')
        frames=params['target_frames']
        for key in ('dialogue_candidate','background_candidate'):
            clocked_stem(result[key],out/(key+'.wav'),frames)
        return {'status':'completed','model':model,'dialogue_candidate':str(out/'dialogue_candidate.wav'),'background_candidate':str(out/'background_candidate.wav')}
    if op=='diarization':
        import torch
        from pyannote.audio import Pipeline
        from backend.diarization import _load_pcm_wav,_run_pipeline,serialize_diarization
        pipeline=Pipeline.from_pretrained(str(work/'model'));pipeline.to(torch.device('cuda'))
        waveform,rate=_load_pcm_wav(file('audio.wav'))
        result=serialize_diarization(_run_pipeline(pipeline,{'waveform':waveform,'sample_rate':rate}),'cuda')
        result['model_revision']=model['revision']
        for speaker in result['speakers']:speaker['embedding_model']=model['repo']+'@'+model['revision']+'::speaker_embeddings'
        (out/'diarization.json').write_text(json.dumps(result,ensure_ascii=False));return result
    if op=='synthesis':
        from huggingface_hub import snapshot_download
        snapshot=snapshot_download(repo_id=model['repo'],revision=model['revision'])
        request_clone={'text':params['text'],'ref_text':params['ref_text'],'reference':str(file('reference.wav')),
            'reference_sha256':params['reference_sha256'],'output':str(out/'speech.wav'),'prompt_dir':str(work/'prompts'),
            'prosody':params.get('prosody',{}),'model_source':snapshot,'model_revision':model['revision'],'dtype':'float16'}
        path=work/'clone-request.json';path.write_text(json.dumps(request_clone))
        subprocess.run([sys.executable,str(work/'src/scripts/clone_voice_worker.py'),str(path)],check=True,
            env={**os.environ,'OPENDUB_CLONE_DTYPE':'float16'})
        result=json.loads((out/'speech.clone.json').read_text(encoding='utf-8'))
        if result.get('device')!='cuda':raise RuntimeError('Remote genuine synthesis did not use CUDA.')
        return result
    if op=='synthesis_batch':
        from huggingface_hub import snapshot_download
        from scripts import clone_voice_worker as clone
        from backend.speech_content import content_evidence
        import torch
        snapshot=snapshot_download(repo_id=model['repo'],revision=model['revision'])
        lines=params['lines']
        if not 1<=len(lines)<=4:raise RuntimeError('Synthesis batch exceeds the bounded four-line contract.')
        for line in lines:
            destination=out/'lines'/line['key'];destination.mkdir(parents=True,exist_ok=True)
            result=clone.main({'text':line['text'],'ref_text':line['ref_text'],'reference':str(file(line['reference_file'])),
                'reference_sha256':line['reference_sha256'],'output':str(destination/'speech.wav'),'prompt_dir':str(work/'prompts'),
                'prosody':line['prosody'],'model_source':snapshot,'model_revision':model['revision'],'dtype':'float16'})
            if result.get('device')!='cuda':raise RuntimeError('Remote genuine synthesis did not use CUDA.')
        # Release the generator before loading the CUDA validator; never add GPU memory together.
        clone._loaded_model=None;clone._loaded_device=None
        import gc
        gc.collect();torch.cuda.empty_cache()
        from faster_whisper import WhisperModel
        validator=model['validator'];snapshot=snapshot_download(repo_id=validator['repo'],revision=validator['revision'])
        asr=WhisperModel(snapshot,device='cuda',compute_type='float16')
        for line in lines:
            destination=out/'lines'/line['key'];audio=destination/'speech.wav'
            segments,_=asr.transcribe(str(audio),language='hi',beam_size=5)
            transcript=' '.join(segment.text for segment in segments)
            evidence={'sha256':sha(audio),'transcript':transcript,'model':validator,'validator_version':2,'compute_provider':'kaggle'}
            evidence.update(content_evidence(line['text'],transcript))
            (destination/'speech.content.json').write_text(json.dumps(evidence,ensure_ascii=False))
        return {'status':'completed','line_count':len(lines),'compute_provider':'kaggle'}
    if op=='fit':
        from backend.mixing import fit_audio
        return fit_audio(file('audio.wav'),out/'fit.wav',**params)
    if op=='audio_batch':
        from backend.mixing import fit_audio,normalize_audio
        items=params['items'];results={}
        if not 1<=len(items)<=16:raise ValueError('Media batch must contain 1–16 lines.')
        ids=[str(item['id']) for item in items]
        if len(set(ids))!=len(ids) or any(not re.fullmatch(r'[0-9]{1,9}',key) for key in ids):raise ValueError('Invalid media line IDs.')
        for item,key in zip(items,ids):
            source=file(item['input'])
            if not source.resolve().is_relative_to(work.resolve()):raise ValueError('Media input escapes task root.')
            target=out/key;target.mkdir(parents=True,exist_ok=True)
            result={}
            if item['operation']=='fit':
                result['fit']=fit_audio(source,target/'fit.wav',**item['params'])
                if item.get('normalize') is not None:result['normalize']=normalize_audio(target/'fit.wav',target/'normalized.wav',item['normalize'])
            elif item['operation']=='normalize':result['normalize']=normalize_audio(source,target/'normalized.wav',**item['params'])
            else:raise ValueError('Unsupported batch audio operation.')
            results[key]=result
        report={'items':results,'compute_provider':'kaggle'}
        (out/'results.json').write_text(json.dumps(report,ensure_ascii=False),encoding='utf-8')
        return report
    if op=='normalize':
        from backend.mixing import normalize_audio
        return normalize_audio(file('audio.wav'),out/'normalized.wav',**params)
    if op=='background':
        from backend.selective_background import preserve_non_dialogue_audio
        return preserve_non_dialogue_audio(file('source.wav'),file('stem.wav'),out/'background.wav',**params)
    if op=='mix':
        from backend.mixing import mix_project
        project=file('project');(project/'output').mkdir(exist_ok=True)
        result=mix_project(project,file('background.wav'),out/'mix.wav',**params)
        shutil.copyfile(project/'output/mix_manifest.json',out/'mix_manifest.json');result['mix_manifest']=str(out/'mix_manifest.json');return result
    if op=='render':
        from backend.rendering import mux_movie
        result=mux_movie(file('source'+params['source_suffix']),file('mix.wav'),out/('rendered'+params['output_suffix']),video_codec=params.get('video_codec','copy'))
        return result
    if op=='probe':
        from backend.media import probe_media
        result=probe_media(file('source'+params['source_suffix']),verify_decode=True)
        (out/'probe.json').write_text(json.dumps(result));return result
    raise ValueError('Unsupported task operation.')


def main():
    requests=list(Path('/kaggle/input').rglob('task-request.json'))
    if len(requests)!=1:raise RuntimeError('Exactly one task request dataset is required.')
    source=requests[0].parent;request=json.loads(requests[0].read_text(encoding='utf-8'))
    work=Path('/kaggle/working/task-root');out=Path('/kaggle/working/task-output')
    out.mkdir(exist_ok=True);work.mkdir(exist_ok=True)
    receipt={'schema_version':2,'fingerprint':request['fingerprint'],'operation':request['operation'],'status':'failed','failure_kind':'setup','outputs':[]}
    phase='setup'
    try:
        contract={k:v for k,v in request.items() if k not in {'fingerprint','payload_sha256'}}
        if hashlib.sha256(json.dumps(contract,sort_keys=True,separators=(',',':')).encode()).hexdigest()!=request['fingerprint']:raise RuntimeError('Task contract fingerprint mismatch.')
        restore_payload(source,'payload.zip',work,request.get('payload_files',[]),request['payload_sha256'])
        for row in request['inputs']:
            if sha(work/row['file'])!=row['sha256']:raise RuntimeError('Input hash mismatch.')
        for manifest_path in Path('/kaggle/input').rglob('model-manifest.json'):
            manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
            if manifest['model']!=request['model']:continue
            if request['model'].get('files_sha256')!=hashlib.sha256(json.dumps(manifest['files'],sort_keys=True).encode()).hexdigest():raise RuntimeError('Model file manifest is not bound to this task.')
            restore_payload(manifest_path.parent,'model.payload.zip',work/'model',manifest['files'],manifest['payload_sha256'])
            for row in manifest['files']:
                if sha(work/'model'/row['file'])!=row['sha256']:raise RuntimeError('Model file checksum mismatch.')
        sys.path.insert(0,str(work/'src'));os.environ['OPENDUB_REMOTE_EXECUTION']='1';os.environ['PYANNOTE_METRICS_ENABLED']='0'
        os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
        receipt['gpu']=prepare_runtime(request['operation'],work);phase='processing'
        result=execute(request,work,out)
        # Canonical path tokens keep private local/remote paths out of portable metadata.
        for path in out.rglob('*.json'):
            path.write_text(json.dumps(portable(json.loads(path.read_text(encoding='utf-8')),work,out),ensure_ascii=False,indent=2))
        result=portable(result,work,out)
        expected=request['expected_outputs'];records=[]
        for name in expected:
            path=out/name
            if not path.is_file() or path.stat().st_size==0:raise RuntimeError('Expected task artifact is missing/empty.')
            records.append({'file':name,'size':path.stat().st_size,'sha256':sha(path)})
        versions={}
        for name in ('torch','torchaudio','numpy','scipy','av','faster-whisper','pyannote.audio','omnivoice','audio-separator','onnxruntime-gpu'):
            try:versions[name]=importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:pass
        receipt.update(status='completed',failure_kind=None,outputs=records,result=result,model=request['model'],runtime_packages=versions)
    except Exception as exc:
        value=str(exc).lower()
        kind='session' if any(x in value for x in ('device lost','gpu has fallen off','driver shutting down')) else 'capacity' if 'no requested cuda gpu' in value else 'memory' if 'out of memory' in value else 'access' if any(x in value for x in ('401','403','gated','unauthorized')) else phase
        receipt.update(failure_kind=kind,message='Remote '+kind+' failure; no successful output was claimed.',diagnostic=failure_diagnostic(exc))
        # Stack locations are useful; private input/dialogue/credentials are not echoed.
        print('OpenDub task stopped:',type(exc).__name__,kind,flush=True)
        print(json.dumps(receipt['diagnostic'],ensure_ascii=True),flush=True)
    finally:
        (out/'task-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
        shutil.rmtree(work,ignore_errors=True)  # Ephemeral worker input only; never user originals.


if __name__=='__main__':main()
