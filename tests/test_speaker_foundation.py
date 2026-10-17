from types import SimpleNamespace
import numpy as np
from backend.diarization import assign_speakers


def test_two_turns_of_same_speaker_have_one_union_candidate():
    row=assign_speakers({'segments':[{'start':0,'end':1,'text':'hello'}]},
                        {'turns':[{'start':0,'end':.6,'speaker_id':'A'},
                                  {'start':.4,'end':1,'speaker_id':'A'}]})['segments'][0]
    assert row['speaker_id']=='A' and row['speaker_confidence']==1
    assert len(row['speaker_candidates'])==1


class Annotation:
    def __init__(self,turns):self.turns=turns
    def itertracks(self,yield_label=True):
        for start,end,speaker in self.turns:yield SimpleNamespace(start=start,end=end),None,speaker
    def labels(self):return sorted({x[2] for x in self.turns})


def test_regular_overlaps_and_learned_embeddings_survive_exclusive_alignment():
    from backend.diarization import serialize_diarization
    output=SimpleNamespace(speaker_diarization=Annotation([(0,2,'A'),(1,3,'B')]),
                           exclusive_speaker_diarization=Annotation([(0,1,'A'),(1,3,'B')]),
                           speaker_embeddings=np.eye(2))
    result=serialize_diarization(output,'cpu')
    assert result['regular_turns']==result['turns']
    assert result['overlap_events']==[{'start':1.0,'end':2.0,'speaker_ids':['A','B']}]
    assert result['alignment_turns'][0]['end']==1
    assert result['speakers'][0]['embedding']==[1.,0.]
    assert result['speakers'][0]['embedding_kind']=='learned'


def test_exclusive_winner_does_not_hide_real_second_voice():
    row=assign_speakers({'segments':[{'start':1,'end':2,'text':'yes'}]},
                       {'regular_turns':[{'start':0,'end':2,'speaker_id':'A'},
                                         {'start':1,'end':3,'speaker_id':'B'}],
                        'turns':[{'start':0,'end':3,'speaker_id':'A'}]})['segments'][0]
    assert row['speaker_id'] is None and row['overlapping_speakers']==['A','B']
    assert row['speaker_review_required']


def test_identity_registry_reuses_neural_identity_when_local_labels_change(tmp_path):
    from backend.speaker_identity import reconcile_identities
    path=tmp_path/'identity.json'
    first={'turns':[{'start':0,'end':2,'speaker_id':'A'},{'start':2,'end':4,'speaker_id':'B'}],
           'speakers':[{'speaker_id':'A','embedding':[1,0],'embedding_kind':'learned'},
                       {'speaker_id':'B','embedding':[0,1],'embedding_kind':'learned'}]}
    a=reconcile_identities(first,path,'same-source')
    second={'turns':[{'start':0,'end':2,'speaker_id':'X'},{'start':2,'end':4,'speaker_id':'Y'}],
            'speakers':[{'speaker_id':'X','embedding':[1,0],'embedding_kind':'learned'},
                        {'speaker_id':'Y','embedding':[0,1],'embedding_kind':'learned'}]}
    b=reconcile_identities(second,path,'same-source')
    assert a['turns']==b['turns']
    assert len(set(x['speaker_id'] for x in b['speakers']))==2
    changed=reconcile_identities(second,path,'different-source')
    assert not set(x['speaker_id'] for x in a['speakers'])&set(x['speaker_id'] for x in changed['speakers'])


def test_short_ambiguous_overlap_stays_review_required_with_dominant_winner():
    row=assign_speakers({'segments':[{'start':0,'end':2,'text':'mixed'}]},
                       {'regular_turns':[{'start':0,'end':2,'speaker_id':'A'},
                                         {'start':1,'end':1.5,'speaker_id':'B'}]})['segments'][0]
    assert row['speaker_review_required'] and row['speaker_review_reason']=='overlapping_speech'


def test_bounded_diarization_reuses_completed_chunks_after_interruption(tmp_path):
    from backend.diarization import run_bounded_diarization
    calls=[]
    class Pipeline:
        device='cpu'
        def __call__(self,data,**kwargs):
            calls.append(data['waveform'].shape[-1])
            return SimpleNamespace(speaker_diarization=Annotation([(0,1,'A'),(1,2,'B')]),
                                   exclusive_speaker_diarization=Annotation([(0,1,'A'),(1,2,'B')]),
                                   speaker_embeddings=np.eye(2))
    waveform=np.zeros((1,30))
    try:run_bounded_diarization(Pipeline(),waveform,10,tmp_path,'source','model',
                               chunk_seconds=2,overlap_seconds=1,cancelled=lambda:len(calls)==1)
    except InterruptedError:pass
    assert len(calls)==1
    result=run_bounded_diarization(Pipeline(),waveform,10,tmp_path,'source','model',chunk_seconds=2,overlap_seconds=1)
    assert len(calls)==2 and result['coverage']['duration']==3
    assert result['speaker_count']==2
    assert all(x['end']<=3 for x in result['turns'])


def test_clean_reference_windows_use_raw_overlaps_not_exclusive_winner():
    from backend.voice_bank_quality import safe_reference_windows
    raw=[{'start':0,'end':4,'speaker_id':'A'},{'start':1,'end':3,'speaker_id':'B'}]
    data={'regular_turns':raw,'raw_overlap_available':True,'exclusive_alignment':True,
          'turns':[{'start':0,'end':4,'speaker_id':'A'}]}
    windows=safe_reference_windows(data,'A',minimum=.5,maximum=4)
    assert [(w['start'],w['end']) for w in windows]==[(0,1),(3,4)]
    assert safe_reference_windows({'turns':data['turns'],'exclusive_alignment':True},'A')==[]


def test_identity_evaluation_penalizes_erased_overlap_and_mid_video_swap():
    from backend.speaker_evaluation import evaluate
    reference=[{'start':0,'end':2,'speaker_id':'A'},{'start':1,'end':3,'speaker_id':'B'}]
    good=evaluate(reference,reference)
    assert good['der']==0 and good['overlap_recall']==1
    bad=evaluate([{'start':0,'end':3,'speaker_id':'A'}],reference)
    assert bad['missed_speaker_seconds']>0 and bad['overlap_recall']==0
    reference=[{'start':0,'end':1,'speaker_id':'A'},{'start':1,'end':2,'speaker_id':'B'},
               {'start':2,'end':3,'speaker_id':'A'},{'start':3,'end':4,'speaker_id':'B'}]
    swapped=[dict(x,speaker_id=('B' if x['speaker_id']=='A' else 'A') if x['start']>=2 else x['speaker_id']) for x in reference]
    assert evaluate(swapped,reference)['confusion_seconds']>0
def test_manual_speaker_split_preserves_unselected_time_and_replays_only_same_source():
    from backend.speaker_corrections import apply_identity_overrides
    raw=[{'start':0,'end':5,'speaker_id':'S'}]
    diar={'identity_source_sha256':'source','speakers':[{'speaker_id':'S','embedding_kind':'learned'}],
          'regular_turns':raw,'turns':raw,'alignment_turns':raw}
    changes={'source_sha256':'source','overrides':[{'start':1,'end':2,'from_speaker':'S','speaker_id':'MANUAL_1'}]}
    result=apply_identity_overrides(diar,changes)
    assert [(r['start'],r['end'],r['speaker_id']) for r in result['regular_turns']]==[(0,1,'S'),(1,2,'MANUAL_1'),(2,5,'S')]
    assert diar['regular_turns']==raw and len(diar['speakers'])==1
    assert result['speakers'][1]['embedding_kind']=='unavailable'
    changes['source_sha256']='other'
    assert apply_identity_overrides(diar,changes)==diar
