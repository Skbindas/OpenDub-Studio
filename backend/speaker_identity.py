"""Persistent local identities from learned embeddings; never infer demographics."""
import copy
import hashlib
import json
import math
from pathlib import Path
from .atomic_files import replace_with_retry


def similarity(a,b):
    if not a or not b or len(a)!=len(b):return -1
    na=sum(x*x for x in a)**.5;nb=sum(x*x for x in b)**.5
    return sum(x*y for x,y in zip(a,b))/(na*nb) if na and nb else -1


def reconcile_identities(diarization,path,source_hash,threshold=.78,margin=.08):
    path=Path(path);result=copy.deepcopy(diarization)
    previous=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    same_source=previous.get('source_sha256')==source_hash
    records=copy.deepcopy(previous.get('speakers',[])) if same_source else []
    next_id=int(previous.get('next_id',1));used=set();mapping={};decisions=[]
    for speaker in result.get('speakers',[]):
        local=speaker['speaker_id'];vector=speaker.get('embedding',[])
        learned=speaker.get('embedding_kind')=='learned' and bool(vector)
        choices=sorted([(similarity(vector,p.get('embedding',[])),p) for p in records
                        if p['speaker_id'] not in used and learned and p.get('embedding_model')==speaker.get('embedding_model')],
                       key=lambda x:(-x[0],x[1]['speaker_id']))
        score=choices[0][0] if choices else None
        separation=(score-choices[1][0]) if len(choices)>1 else 1
        if choices and score>=threshold and separation>=margin:
            record=choices[0][1];method='learned_embedding_match'
        else:
            record={'speaker_id':f'SPK_{next_id:04d}','embedding':vector,
                    'embedding_model':speaker.get('embedding_model'),'first_source_speaker_id':local}
            next_id+=1;records.append(record);method='new_provisional_identity'
        stable=record['speaker_id'];used.add(stable);mapping[local]=stable
        speaker.update(speaker_id=stable,source_cluster_id=local,identity_method=method,
                       identity_similarity=round(score,4) if score is not None else None,
                       identity_confidence_kind='uncalibrated_cosine_similarity',review_required=True)
        decisions.append({'source_cluster_id':local,'speaker_id':stable,'method':method})
    for key in ('turns','regular_turns','alignment_turns'):
        for turn in result.get(key,[]):turn['speaker_id']=mapping.get(turn['speaker_id'],turn['speaker_id'])
    for event in result.get('overlap_events',[]):event['speaker_ids']=sorted(mapping.get(x,x) for x in event['speaker_ids'])
    state={'schema_version':1,'source_sha256':source_hash,'next_id':next_id,'speakers':records,
           'threshold':threshold,'margin':margin,'calibration_status':'requires_real_source_evaluation'}
    path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8');replace_with_retry(temporary,path)
    result.update(identity_schema_version=1,identity_mapping=mapping,identity_decisions=decisions,
                  identity_source_sha256=source_hash)
    return result
