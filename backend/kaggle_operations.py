"""Adapters preserve native timeline, voice-review and artifact contracts."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from .chunk_execution import digest,save_json
from .kaggle_tasks import project_for,execute


def remote_plan(base,duration=0):
    from .compute_settings import read_settings
    from .kaggle_credentials import credential_status
    settings=read_settings(base);account=credential_status()
    reasons=[]
    if not account.get('cli_installed'):reasons.append('Install the isolated Kaggle SDK using scripts/setup_kaggle.py.')
    if not account.get('configured'):reasons.append('Configure your own Kaggle API credentials in the secure account panel.')
    elif (account.get('username') or '').lower()!=settings['username'].lower():reasons.append('Saved API credentials must be bound to the selected Kaggle username.')
    if not settings.get('allow_media_upload'):reasons.append('Select private audio/code upload for this project.')
    if not settings.get('allow_model_upload'):reasons.append('Select private model-file upload for the gated speaker/separator models; tokens remain local.')
    return {'admitted':not reasons,'reasons':reasons,'compute_provider':'kaggle','heavy_workers':1,
        'cpu_threads_per_worker':2,'asr_device':'cuda','separation_device':'cuda','separation_slots':[{'device':'cuda'}],
        'chunk_seconds':90,'context_seconds':3,'required_available_ram_bytes':256*1024**2,
        'reserved_ram_bytes':256*1024**2,'gpu_eligibility':'unverified','quota_remaining':None,
        'requested_accelerator':settings['accelerator'],'duration_seconds':duration,
        'note':'Local control/input preparation; neural inference on allocated Kaggle CUDA, media tasks on Kaggle CPU. Allocation is not guaranteed.'}


def cancellation(base):
    from .work_progress import current_context
    context=current_context()
    if context:
        from . import app as studio
        return lambda:studio.job_cancel_requested(studio.DB_PATH,context[1])
    return lambda:False


def crop(base,source,start,end,rate,channels):
    identity=hashlib.sha256(f'{digest(source)}:{start}:{end}:{rate}:{channels}'.encode()).hexdigest()
    path=Path(base)/'kaggle/prepared-audio'/(identity+'.wav');path.parent.mkdir(parents=True,exist_ok=True)
    if not path.is_file():
        pending=path.with_suffix('.pending.wav')
        subprocess.run(['ffmpeg','-v','error','-y','-ss',str(start),'-i',str(source),'-t',str(end-start),
            '-ac',str(channels),'-ar',str(rate),'-c:a','pcm_s16le',str(pending)],capture_output=True,check=True)
        pending.replace(path)
    return path


def chunk(spec,folder,cancelled=lambda:False):
    base=project_for(folder)
    if base is None:raise RuntimeError('Cloud chunk has no project compute selection.')
    operation=spec['operation'];start,end=spec['context_start'],spec['context_end']
    if end-start>120:raise RuntimeError('Cloud partition exceeds the bounded 120-second context.')
    source=crop(base,Path(spec['source']),start,end,48000 if operation=='separation' else 16000,2 if operation=='separation' else 1)
    names=['dialogue_candidate.wav','background_candidate.wav'] if operation=='separation' else ['transcript.json']
    outputs={name:Path(folder)/name for name in names}
    params={'model_size':spec.get('model_size','small'),'language':spec.get('language'),
        'model_filename':spec.get('model_filename','vocals_mel_band_roformer.ckpt'),
        'target_frames':round(end*48000)-round(start*48000)}
    result=execute(base,operation,params,{'audio.wav':source},outputs,cancelled=cancelled)
    if operation=='separation':
        import soundfile as sf
        for path in outputs.values():
            info=sf.info(path)
            if info.frames!=params['target_frames'] or info.channels!=2 or info.samplerate!=48000:
                raise RuntimeError('Cloud stem sample clock differs from its source context.')
        payload={key:str(outputs[key+'.wav']) for key in ('dialogue_candidate','background_candidate')}
    else:payload=json.loads(outputs['transcript.json'].read_text(encoding='utf-8'))
    response={'outputs':[str(path) for path in outputs.values()],'payload':payload,'compute_provider':'kaggle'}
    save_json(Path(folder)/'result.json',response);return response


def transcribe(source,model_size,language,device):
    import soundfile as sf
    from .chunked_asr import transcribe_chunked
    base=project_for(source);duration=sf.info(source).duration
    return transcribe_chunked(Path(source),base/'chunks/cloud-asr',duration,remote_plan(base,duration),
        model_size=model_size,language=language,cancelled=cancellation(base))


def diarize(source,output,cancelled,progress):
    import soundfile as sf
    from .diarization import union_intervals,overlap_events
    from .speaker_identity import reconcile_identities
    base=project_for(output);duration=sf.info(source).duration;input_hash=digest(source)
    root=base/'chunks/cloud-diarization'/input_hash;root.mkdir(parents=True,exist_ok=True)
    identity=root/'working-identities.json';identity.unlink(missing_ok=True)
    starts=[];at=0
    while at<duration:
        starts.append(at)
        if at+120>=duration:break
        at+=110
    merged={'regular_turns':[],'alignment_turns':[]};speakers={};windows=[];revision=None
    for index,start in enumerate(starts):
        if cancelled():raise InterruptedError('Speaker coordinator paused; completed remote windows retained.')
        end=min(duration,start+120);audio=crop(base,Path(source),start,end,16000,1);target=root/f'{index:05d}.json'
        result=execute(base,'diarization',{}, {'audio.wav':audio},{'diarization.json':target},cancelled=cancelled)
        data=json.loads(target.read_text(encoding='utf-8'));revision=data['model_revision']
        mapped=reconcile_identities(data,identity,input_hash)
        left=start+(5 if index else 0);right=end-(5 if index<len(starts)-1 else 0)
        for key in merged:
            for row in mapped[key]:
                a=max(left,start+row['start']);b=min(right,start+row['end'])
                if b>a:merged[key].append({**row,'start':round(a,3),'end':round(b,3)})
        for speaker in mapped['speakers']:speakers[speaker['speaker_id']]=speaker
        windows.append({'start':start,'end':end,'owned_start':left,'owned_end':right})
        progress(f'Cloud speaker window {index+1}/{len(starts)}',(index+1)/len(starts))
    for key,rows in merged.items():
        grouped={}
        for row in rows:grouped.setdefault(row['speaker_id'],[]).append((row['start'],row['end']))
        merged[key]=sorted([{'speaker_id':sid,'start':a,'end':b} for sid,values in grouped.items() for a,b in union_intervals(values)],key=lambda r:(r['start'],r['end'],r['speaker_id']))
    active={row['speaker_id'] for row in merged['regular_turns']};profiles=[speakers[sid] for sid in sorted(active)]
    result={'schema_version':3,'engine':'pyannote/speaker-diarization-community-1','model_revision':revision,'device':'kaggle/cuda',
        'timebase':'source_media_seconds','speakers':profiles,'speaker_count':len(profiles),**merged,
        'turns':merged['regular_turns'],'overlap_events':overlap_events(merged['regular_turns']),
        'raw_overlap_available':True,'exclusive_alignment':True,'coverage':{'duration':duration,'windows':windows,'complete':True},
        'notice':'Provisional learned speaker identities; source and casting review remain required.'}
    save_json(output,result);return result


def synthesize(text,reference,ref_text,output,prosody):
    base=project_for(output)
    key=synthesis_key(base,{'text':text,'reference':reference,'ref_text':ref_text,'prosody':prosody or {}})
    cached=base/'kaggle/prepared-synthesis'/key
    if (cached/'speech.clone.json').is_file() and (cached/'speech.wav').is_file():
        report=json.loads((cached/'speech.clone.json').read_text(encoding='utf-8'))
        if report.get('output_sha256')!=digest(cached/'speech.wav') or report.get('reference_sha256')!=digest(reference):raise RuntimeError('Prepared speech checkpoint changed; review required.')
        Path(output).parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(cached/'speech.wav',output)
        report.update(file=str(output),reference_sha256=digest(reference));save_json(Path(output).with_suffix('.clone.json'),report)
        evidence=json.loads((cached/'speech.content.json').read_text(encoding='utf-8'))
        if evidence.get('sha256')!=digest(output):raise RuntimeError('Prepared content evidence is stale.')
        save_json(Path(output).with_suffix('.content.json'),evidence)
        return report
    result=execute(base,'synthesis',{'text':text,'ref_text':ref_text,'reference_sha256':digest(reference),'prosody':prosody or {}},
        {'reference.wav':Path(reference)},{'speech.wav':Path(output),'speech.clone.json':Path(output).with_suffix('.clone.json')},cancelled=cancellation(base))
    result.update(file=str(output),output_sha256=digest(output),reference_sha256=digest(reference))
    save_json(Path(output).with_suffix('.clone.json'),result);return result


def synthesis_key(base,item):
    from .kaggle_models import recipe
    from .kaggle_tasks import worker_revision
    from .compute_settings import read_settings
    binding={k:item[k] for k in ('text','ref_text','prosody')}
    binding.update(reference_sha256=digest(item['reference']),model=recipe(base,'synthesis_batch',{}),
                   worker_revision=worker_revision(),account=read_settings(base)['username'])
    return hashlib.sha256(json.dumps(binding,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def prefetch_synthesis(base,items,cancelled):
    # Four reviewed lines bound each session's replay cost and keep one model warm.
    for at in range(0,len(items),4):
        files={};outputs={};lines=[]
        for item in items[at:at+4]:
            key=synthesis_key(base,item);logical='references/'+digest(item['reference'])+'.wav'
            files[logical]=Path(item['reference'])
            lines.append({'key':key,'reference_file':logical,'reference_sha256':digest(item['reference']),
                          **{k:item[k] for k in ('text','ref_text','prosody')}})
            for name in ('speech.wav','speech.clone.json','speech.content.json'):
                outputs['lines/'+key+'/'+name]=Path(base)/'kaggle/prepared-synthesis'/key/name
        execute(base,'synthesis_batch',{'lines':lines},files,outputs,cancelled=cancelled)


def single_audio(operation,src,out,params):
    base=project_for(out) or project_for(src)
    name='fit.wav' if operation=='fit' else 'normalized.wav'
    return execute(base,operation,params,{'audio.wav':Path(src)},{name:Path(out)},cancelled=cancellation(base))


def fit_batch(base,units,translated_rows,max_speedup,max_slowdown,normalize,target_lufs,force,cancelled):
    """Reuse native per-line QA; amortize remote startup over at most 16 lines."""
    base=Path(base);pending=[];results={}
    rows={int(row.get('segment_index',i)):row for i,row in enumerate(translated_rows)}
    for i,unit in enumerate(units):
        index=int(unit.get('segment_index',i));row=rows.get(index,{})
        source=(unit.get('tts') or {}).get('audio_path') or row.get('dub_audio')
        candidate=base/'segments'/f'segment_{index:06d}_dub.wav'
        if not source and candidate.is_file():source=str(candidate)
        if not source or not Path(source).is_file():continue
        fit=base/'segments'/f'segment_{index:06d}_fit.wav';norm=base/'segments'/f'segment_{index:06d}_normalized.wav'
        timing=unit.get('timing') or {};loudness=unit.get('loudness') or {}
        from .pipeline import timing_fit_matches_policy
        current=timing_fit_matches_policy(unit,max_speedup,max_slowdown)
        if not force and current and timing.get('status') in {'completed','needs_review'} and fit.is_file() and (not normalize or (loudness.get('status')=='completed' and norm.is_file())):continue
        duration=float(unit.get('duration_sec') or 0)
        if duration<=0:duration=max(.01,float(row.get('end',0))-float(row.get('start',0))) if row else 1.
        pending.append((index,Path(source),fit,norm,{'target':duration,'max_speedup':max_speedup,
            'max_slowdown':max_slowdown,'trim_silence':True,'pad_short':True}))
    for at in range(0,len(pending),16):
        if cancelled():raise InterruptedError('Media batch cancelled; completed outputs retained.')
        items=[];files={};outputs={}
        for index,source,fit,norm,params in pending[at:at+16]:
            logical='audio/'+digest(source)+'.wav';files[logical]=source
            items.append({'id':str(index),'operation':'fit','input':logical,'params':params,'normalize':target_lufs if normalize else None})
            outputs[f'{index}/fit.wav']=fit
            if normalize:outputs[f'{index}/normalized.wav']=norm
        identity=hashlib.sha256(json.dumps(items,sort_keys=True).encode()).hexdigest()
        outputs['results.json']=base/'kaggle/media-batches'/(identity+'.json')
        response=execute(base,'audio_batch',{'items':items},files,outputs,cancelled=cancelled)
        results.update({int(key):value for key,value in response['items'].items()})
    return results


def normalize_batch(base,units,target_lufs,cancelled):
    base=Path(base);results={}
    for at in range(0,len(units),16):
        items=[];files={};outputs={}
        for i,unit in enumerate(units[at:at+16],at):
            index=int(unit.get('segment_index',i));source=Path((unit.get('timing') or {}).get('fit_audio') or '')
            if not source.is_absolute():source=base/source
            if not source.is_file():raise RuntimeError('Reviewed fitted audio is required for batch leveling.')
            logical='audio/'+digest(source)+'.wav';files[logical]=source
            items.append({'id':str(index),'operation':'normalize','input':logical,'params':{'target_lufs':target_lufs}})
            outputs[f'{index}/normalized.wav']=base/'segments'/f'segment_{index:06d}_normalized.wav'
        if not items:continue
        identity=hashlib.sha256(json.dumps(items,sort_keys=True).encode()).hexdigest()
        outputs['results.json']=base/'kaggle/media-batches'/(identity+'.json')
        response=execute(base,'audio_batch',{'items':items},files,outputs,cancelled=cancelled)
        results.update({int(key):value['normalize'] for key,value in response['items'].items()})
    return results


def background(source,stem,out,intervals,padding,fade):
    base=project_for(out)
    return execute(base,'background',{'intervals':intervals,'padding':padding,'fade':fade},
        {'source.wav':Path(source),'stem.wav':Path(stem)},{'background.wav':Path(out)},cancelled=cancellation(base))


def mix(project,background,out,params):
    base=project_for(project);manifest=json.loads((Path(project)/'analysis/dialogue_manifest.json').read_text(encoding='utf-8'))
    portable={'units':[]};files={};clips=0
    for unit in manifest.get('units',[]):
        selected=None
        for stage in ('loudness','timing','tts'):
            for key in ('output_path','normalized_audio','fit_audio','audio_path'):
                value=(unit.get(stage) or {}).get(key)
                if value:
                    path=Path(value);path=path if path.is_absolute() else Path(project)/path
                    if path.is_file():selected=path;break
            if selected:break
        if selected:
            logical=f'project/media/{digest(selected)}.wav';files[logical]=selected;clips+=1
            portable['units'].append({k:unit[k] for k in ('segment_index','start_sec','end_sec','duration_sec') if k in unit})
            portable['units'][-1]['loudness']={'output_path':logical.removeprefix('project/')}
    if not clips:raise RuntimeError('No reviewed speech artifacts are available for remote mixing.')
    metadata=Path(project)/'kaggle/prepared-mix-manifest.json';save_json(metadata,portable)
    files['project/analysis/dialogue_manifest.json']=metadata
    resolved=Path(background) if background else Path(project)/'output/background_preserved.wav'
    if not resolved.is_file():raise RuntimeError('Preserved background is required before cloud mixing.')
    files['background.wav']=resolved
    return execute(base,'mix',params,files,{'mix.wav':Path(out),'mix_manifest.json':Path(project)/'output/mix_manifest.json'},cancelled=cancellation(base))


def render(source,mixed,out,codec,cancelled):
    base=project_for(out)
    return execute(base,'render',{'source_suffix':Path(source).suffix,'output_suffix':Path(out).suffix,'video_codec':codec},
        {'source'+Path(source).suffix:Path(source),'mix.wav':Path(mixed)},
        {'rendered'+Path(out).suffix:Path(out)},cancelled=cancelled or cancellation(base))


def probe(source,verify_decode):
    base=project_for(source);out=base/'kaggle/probe-result.json'
    return execute(base,'probe',{'source_suffix':Path(source).suffix},{'source'+Path(source).suffix:Path(source)}, {'probe.json':out},cancelled=cancellation(base))
