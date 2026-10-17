"""Replay explicit source-bound manual splits without claiming learned identity."""
import copy
from .diarization import overlap_events


def apply_identity_overrides(diarization,corrections):
    result=copy.deepcopy(diarization)
    if corrections.get('source_sha256')!=result.get('identity_source_sha256'):return result
    for change in corrections.get('overrides',[]):
        left,right=float(change['start']),float(change['end']);old=change['from_speaker'];new=change['speaker_id']
        touched=False
        for key in ('regular_turns','alignment_turns'):
            output=[]
            for row in result.get(key,[]):
                a,b=float(row['start']),float(row['end'])
                if row['speaker_id']!=old or b<=left or a>=right:output.append(row);continue
                touched=True
                if a<left:output.append(dict(row,end=left))
                output.append(dict(row,start=max(a,left),end=min(b,right),speaker_id=new,identity_method='user_time_range_split'))
                if b>right:output.append(dict(row,start=right))
            result[key]=sorted(output,key=lambda r:(r['start'],r['end'],r['speaker_id']))
        if touched and new not in {s['speaker_id'] for s in result.get('speakers',[])}:
            result.setdefault('speakers',[]).append({'speaker_id':new,'display_name':new,'embedding_kind':'unavailable',
                'embedding':[],'identity_method':'user_time_range_split','review_required':True,
                'vocal_profile':{'vocal_type':'unknown','method':'manual_identity_not_measured','exact_gender_inferred':False}})
    result['turns']=result.get('regular_turns',[])
    result['overlap_events']=overlap_events(result['turns'])
    active={r['speaker_id'] for r in result['turns']}
    result['speakers']=[s for s in result.get('speakers',[]) if s['speaker_id'] in active]
    result['speaker_count']=len(result['speakers'])
    return result
