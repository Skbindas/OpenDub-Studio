"""Local interval scoring with global label assignment and overlap included."""
from scipy.optimize import linear_sum_assignment
import numpy as np


def evaluate(prediction,reference):
    refids=sorted({r['speaker_id'] for r in reference});hypids=sorted({r['speaker_id'] for r in prediction})
    edges=sorted({float(r[k]) for rows in (prediction,reference) for r in rows for k in ('start','end')})
    spans=[];matrix=np.zeros((len(refids),len(hypids)))
    for a,b in zip(edges,edges[1:]):
        mid=(a+b)/2
        ref={r['speaker_id'] for r in reference if r['start']<=mid<r['end']}
        hyp={r['speaker_id'] for r in prediction if r['start']<=mid<r['end']}
        spans.append((b-a,ref,hyp))
        for r in ref:
            for h in hyp:matrix[refids.index(r),hypids.index(h)]+=b-a
    ri,hi=linear_sum_assignment(-matrix);mapping={hypids[h]:refids[r] for r,h in zip(ri,hi)}
    missed=false=confused=total=ref_overlap=pred_overlap=overlap_hit=0.
    for seconds,ref,hyp in spans:
        correct=len(ref&{mapping.get(h) for h in hyp})
        missed+=seconds*max(0,len(ref)-len(hyp));false+=seconds*max(0,len(hyp)-len(ref))
        confused+=seconds*(min(len(ref),len(hyp))-correct);total+=seconds*len(ref)
        if len(ref)>1:ref_overlap+=seconds
        if len(hyp)>1:pred_overlap+=seconds
        if len(ref)>1 and len(hyp)>1:overlap_hit+=seconds
    return {'der':(missed+false+confused)/total if total else None,'missed_speaker_seconds':missed,
            'false_alarm_seconds':false,'confusion_seconds':confused,'reference_speaker_seconds':total,
            'speaker_count_error':len(hypids)-len(refids),'overlap_recall':overlap_hit/ref_overlap if ref_overlap else None,
            'overlap_precision':overlap_hit/pred_overlap if pred_overlap else None,'label_mapping':mapping,
            'scoring':'global label assignment; zero collar; overlaps included'}
