"""Optional local inference. No source media is sent to an external service."""
import gc,hashlib,json,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.speaker_tools import summarize_traits,validate_overlap_request,trait_prediction,valid_overlap_cache

SEPFORMER_REVISION='21a5b500c6f52fddc387c5d9e5fb13ffd6f039c5'


def file_hash(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def traits(base,research_mode):
    if not research_mode:raise ValueError('This optional model has a non-commercial research license; research mode must be explicit.')
    import numpy as np,soundfile as sf,onnxruntime as ort
    model_root=ROOT/'runtime/speaker-tools/models/voice-traits-research'
    models=list(model_root.rglob('*.onnx'))
    if not models:raise RuntimeError('Voice-trait research model is not downloaded yet; existing casting remains unchanged.')
    from backend.speaker_review import review_state,read
    cards=review_state(base,read(base/'characters/registry.json',{}))['cards']
    options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
    session=ort.InferenceSession(str(models[0]),sess_options=options,providers=['CPUExecutionProvider'])
    audio=base/'analysis/vocals_16k_mono.wav';results={}
    with sf.SoundFile(audio) as stream:
        for card in cards:
            predictions=[]
            for window in card['source_windows'][:3]:
                start,end=window['start'],min(window['end'],window['start']+4)
                if end-start<1:continue
                stream.seek(round(start*stream.samplerate));samples=stream.read(round((end-start)*stream.samplerate),dtype='float32')
                if stream.samplerate!=16000:raise ValueError('Traits require the validated 16k vocal stem.')
                # The official ONNX exporter accepts raw 16k PCM; model.yaml has no transform.
                inputs=session.get_inputs()
                if len(inputs)!=1:raise RuntimeError('Unsupported trait ONNX input schema; inspect the exporter metadata.')
                values=session.run(None,{inputs[0].name:samples.reshape(1,-1) if len(inputs[0].shape)==2 else samples})
                vectors=[np.asarray(v).reshape(-1) for v in values]
                age=next((v for v in vectors if v.size==1),None);gender=next((v for v in vectors if v.size==3),None)
                if age is None or gender is None:raise RuntimeError('Unsupported trait ONNX output schema.')
                predictions.append(trait_prediction(float(age[0]),gender.tolist()))
            results[card['character_id']]={**summarize_traits(predictions),'source_windows':card['source_windows'][:3]}
    return {'status':'completed','characters':results,'model':'audEERING wav2vec2 robust 6-layer age/gender',
            'model_sha256':file_hash(models[0]),'audio_sha256':file_hash(audio),'mode':'research_noncommercial',
            'license':'CC-BY-NC-SA-4.0','source':'https://doi.org/10.5281/zenodo.7761387','device':'cpu'}


def overlap(base,index):
    sys.path.insert(0,str(ROOT/'runtime/speaker-tools/packages-v1'))
    import numpy as np,soundfile as sf,torch
    from speechbrain.inference.separation import SepformerSeparation
    from speechbrain.utils.fetching import LocalStrategy,FetchConfig
    diar=json.loads((base/'analysis/diarization.json').read_text(encoding='utf-8'))
    if not 0<=index<len(diar.get('overlap_events',[])):raise ValueError('No detected overlap exists at this index.')
    audio=base/'analysis/vocals_16k_mono.wav';info=sf.info(audio);event=diar['overlap_events'][index]
    start,end=validate_overlap_request(event,info.duration)
    if info.samplerate!=16000 or info.channels!=1:raise ValueError('Overlap recovery requires mono 16k vocal audio.')
    with sf.SoundFile(audio) as stream:
        stream.seek(round(start*16000));samples=stream.read(round((end-start)*16000),dtype='float32')
    audio_digest=file_hash(audio)
    key=hashlib.sha256((audio_digest+SEPFORMER_REVISION+json.dumps(event,sort_keys=True)).encode()).hexdigest()[:24]
    directory=base/'analysis/speaker-tools/overlap'/key;directory.mkdir(parents=True,exist_ok=True)
    paths=[directory/'channel-0.wav',directory/'channel-1.wav']
    metadata=directory/'separation.json'
    cached=json.loads(metadata.read_text()) if metadata.exists() else {}
    device='cuda' if torch.cuda.is_available() else 'cpu';torch.set_num_threads(2)
    cache_valid=valid_overlap_cache(paths,len(samples)) and cached.get('channel_sha256')==[file_hash(p) for p in paths]
    if not cache_valid:
        model=SepformerSeparation.from_hparams(source='speechbrain/sepformer-whamr16k',
            savedir=str(ROOT/'runtime/speaker-tools/models'/('sepformer-'+SEPFORMER_REVISION)),run_opts={'device':'cuda:0' if device=='cuda' else 'cpu'},local_strategy=LocalStrategy.COPY,
            fetch_config=FetchConfig(revision=SEPFORMER_REVISION))
        try:
            with torch.inference_mode():sources=model.separate_batch(torch.from_numpy(samples).reshape(1,-1))[0].cpu().numpy()
        except torch.cuda.OutOfMemoryError:
            model.to('cpu');model.device=torch.device('cpu');torch.cuda.empty_cache();device='cpu'
            with torch.inference_mode():sources=model.separate_batch(torch.from_numpy(samples).reshape(1,-1))[0].cpu().numpy()
        del model;gc.collect()
        if torch.cuda.is_available():torch.cuda.empty_cache()
        if sources.shape!=(len(samples),2):raise RuntimeError('Separated crop failed duration/channel validation.')
        if any(np.sqrt(np.mean(sources[:,i]**2))<.0001 for i in range(2)):raise RuntimeError('An overlap channel has no usable recovered speech.')
        if abs(np.corrcoef(sources.T)[0,1])>.95:raise RuntimeError('Overlap channels are nearly identical; recovery is not independently usable.')
        for i,path in enumerate(paths):
            temporary=path.with_name(path.stem+'.'+uuid.uuid4().hex+'.pending.wav')
            try:sf.write(temporary,sources[:,i],16000,subtype='PCM_16');temporary.replace(path)
            finally:temporary.unlink(missing_ok=True)
        cached={'device':device,'model_revision':SEPFORMER_REVISION,'audio_sha256':audio_digest,'channel_sha256':[file_hash(p) for p in paths]}
        from backend.analysis_pipeline import _atomic_json
        _atomic_json(metadata,cached)
    from faster_whisper import WhisperModel
    model=WhisperModel('small',device=device,compute_type='float16' if device=='cuda' else 'int8',cpu_threads=2)
    language=json.loads((base/'analysis/transcript.json').read_text(encoding='utf-8')).get('language')
    channels=[]
    for path in paths:
        segments,_=model.transcribe(str(path),language=language,word_timestamps=True,vad_filter=True,beam_size=5)
        rows=[{'start':s.start+start,'end':s.end+start,'text':s.text.strip(),'no_speech_prob':s.no_speech_prob} for s in segments]
        channels.append({'audio':str(path),'segments':rows,'speaker_id':None,'review_required':True})
    return {'status':'completed','model':'speechbrain/sepformer-whamr16k','model_revision':SEPFORMER_REVISION,
            'audio_sha256':audio_digest,'license':'Apache-2.0','device':device,
            'separation_device':cached['device'],'asr_device':device,'separation_cache_reused':cache_valid,
            'events':{str(index):{'source_event':event,'channels':channels,'review_required':True,
                                'notice':'Channel order is not speaker identity; review ownership and missing words before applying.'}}}


if __name__=='__main__':
    request=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'));base=Path(request['project'])
    try:
        result=traits(base,request.get('research_mode',False)) if request['task']=='voice_traits' else overlap(base,int(request['event_index']))
    except Exception as exc:
        result={'status':'blocked','message':str(exc)}
        print(type(exc).__name__+': '+str(exc),flush=True)
    Path(request['output']).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
