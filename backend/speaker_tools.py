"""Bounded optional speaker tools; predictions never certify personal identity."""
import copy,hashlib,json,math,os,subprocess,sys,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def tool_python(task):
    if task=='overlap_recovery':
        candidate=Path(os.getenv('OPENDUB_SPEAKER_TOOLS_PYTHON') or ROOT/'runtime/separation-env'/('Scripts/python.exe' if os.name=='nt' else 'bin/python'))
        if candidate.is_file():return str(candidate)
    return sys.executable


def trait_prediction(age,logits):
    if len(logits)!=3 or not all(math.isfinite(v) for v in logits):
        raise ValueError('Trait model returned invalid logits.')
    weights=[math.exp(v-max(logits)) for v in logits]
    return {'age':float(age),'probabilities':[v/sum(weights) for v in weights]}


def tool_context(base):
    """Cheap revision check for polling; inference separately records audio SHA."""
    base=Path(base);digest=hashlib.sha256()
    for name in ('analysis/diarization.json','analysis/transcript.json','characters/registry.json'):
        path=base/name;digest.update(name.encode());digest.update(path.read_bytes() if path.is_file() else b'')
    audio=base/'analysis/vocals_16k_mono.wav'
    if audio.is_file():
        stat=audio.stat();digest.update(f'{stat.st_size}:{stat.st_mtime_ns}'.encode())
    return digest.hexdigest()


def current_tool_result(base,result):
    return result if result.get('context_sha256')==tool_context(base) else {}


def valid_overlap_cache(paths,frames):
    import soundfile as sf
    try:
        return all(p.is_file() and sf.info(p).frames==frames and sf.info(p).samplerate==16000
                   and sf.info(p).channels==1 for p in paths)
    except (OSError,RuntimeError):return False


def summarize_traits(predictions):
    valid=[p for p in predictions if math.isfinite(p['age']) and 0<=p['age']<=1 and len(p['probabilities'])==3
           and all(math.isfinite(v) and 0<=v<=1 for v in p['probabilities'])
           and abs(sum(p['probabilities'])-1)<.001]
    result={'gender_identity':'unknown','exact_age_inferred':False,'voice_style_suggestion':'unknown',
            'age_band_suggestion':'unknown','confidence_kind':'uncalibrated_model_probabilities','review_required':True}
    if not valid:return result
    winners=[max(range(3),key=lambda i:p['probabilities'][i]) for p in valid]
    confidence=min(max(p['probabilities']) for p in valid)
    ages=[max(0,min(100,p['age']*100)) for p in valid]
    result.update(model_confidence=round(confidence,3),sample_count=len(valid))
    if len(set(winners))==1 and confidence>=.8:
        result['voice_style_suggestion']=['feminine','masculine','childlike'][winners[0]]
    if len(valid)>=2 and max(ages)-min(ages)<=12:
        age=sum(ages)/len(ages)
        result['age_band_suggestion']='childlike' if age<18 else 'young' if age<35 else 'adult' if age<60 else 'mature'
    return result


def validate_overlap_request(event,duration):
    start,end=float(event['start']),float(event['end'])
    if len(set(event['speaker_ids']))!=2:raise ValueError('This recovery model supports exactly two simultaneous speakers; crowd speech requires review.')
    if not 0<=start<end<=duration+.01 or end-start>8:raise ValueError('Recovery requires a valid source-time crop of at most eight seconds.')
    return start,end


def join_reviewed_turns(rows,max_gap=.35,max_duration=10):
    result=[]
    for row in rows:
        row=copy.deepcopy(row)
        can_join=bool(result and row.get('speaker_id') and row.get('speaker_id')==result[-1].get('speaker_id')
            and 0<=row['start']-result[-1]['end']<=max_gap and row['end']-result[-1]['start']<=max_duration
            and not row.get('speaker_review_required') and not result[-1].get('speaker_review_required'))
        if can_join:
            previous=result[-1];previous.update(end=row['end'],text=previous['text'].rstrip()+' '+row['text'].lstrip())
            previous.setdefault('words',[]).extend(row.get('words',[]))
            previous.setdefault('source_segment_indices',[previous.get('source_segment_index')]).extend(row.get('source_segment_indices',[row.get('source_segment_index')]))
        else:result.append(row)
    return result


def execute_speaker_tool(job_id,project_id,payload):
    from . import app as studio
    from .analysis_pipeline import _atomic_json
    base=studio.project_dir(project_id);directory=base/'analysis/speaker-tools';directory.mkdir(exist_ok=True)
    request=directory/(job_id+'.request.json');output=directory/(job_id+'.result.json')
    context=tool_context(base)
    with studio.connect(studio.DB_PATH) as conn:
        conn.execute("UPDATE jobs SET status='running',progress=0.1,message=?,updated_at=? WHERE id=?",('Local speaker inference running; original media and locked voices retained.',studio.now(),job_id))
    _atomic_json(request,{'project':str(base.resolve()),'task':payload['task'],'event_index':payload.get('event_index'),
                          'research_mode':payload.get('research_mode',False),'output':str(output.resolve())})
    try:
        # Keep optional model frameworks in a subprocess and one bounded worker.
        from .clone_runtime import clone_worker_slot
        with clone_worker_slot(), (directory/(job_id+'.log')).open('w',encoding='utf-8') as log:
            process=subprocess.Popen([tool_python(payload['task']),str(ROOT/'scripts/speaker_tools_worker.py'),str(request)],stdout=log,stderr=subprocess.STDOUT)
            while process.poll() is None:
                if studio.job_cancel_requested(studio.DB_PATH,job_id):
                    process.terminate();process.wait(timeout=15)
                    raise InterruptedError('Speaker tool cancelled; source and completed candidates retained.')
                time.sleep(.5)
        if process.returncode or not output.exists():raise RuntimeError('Speaker tool failed; inspect its local log. Existing source/voices were retained.')
        result=json.loads(output.read_text(encoding='utf-8'))
        if result.get('status')!='completed':raise RuntimeError(result.get('message','Model/runtime setup is required.'))
        if context!=tool_context(base):raise RuntimeError('Source or identity review changed during inference; rerun this tool on the current revision.')
        result['context_sha256']=context
        target=base/'analysis'/('voice_traits.json' if payload['task']=='voice_traits' else 'overlap_candidates.json')
        if payload['task']=='overlap_recovery' and target.exists():
            previous=current_tool_result(base,json.loads(target.read_text(encoding='utf-8')))
            if previous:previous.setdefault('events',{}).update(result.get('events',{}));result=previous
        _atomic_json(target,result)
        status='completed';message='Casting suggestions ready; review them before changing a locked voice.' if payload['task']=='voice_traits' else 'Separated overlap candidates ready; listen and review both transcripts before applying.'
    except Exception as exc:
        status='cancelled' if isinstance(exc,InterruptedError) else 'failed';message=str(exc)
    with studio.connect(studio.DB_PATH) as conn:
        conn.execute("UPDATE jobs SET status=?,progress=?,message=?,updated_at=? WHERE id=?",(status,1 if status=='completed' else 0,message,studio.now(),job_id))
        conn.execute("UPDATE projects SET status='awaiting_review',updated_at=? WHERE id=?",(studio.now(),project_id))
