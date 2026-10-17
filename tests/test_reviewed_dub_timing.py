import copy,pytest


def test_explicit_gap_allowance_preserves_source_clock():
    from backend.reviewed_dub_timing import apply_reviewed_windows
    rows=[{'segment_index':9,'start':23.83,'end':24.15,'translated_text':'शुक्रिया।','speaker_id':'A'},
          {'segment_index':10,'start':34.6,'end':35.24,'translated_text':'अरे!','speaker_id':'A'}]
    manifest={'units':[{'segment_index':9,'speaker_id':'A','source_text':'谢谢','start_sec':23.83,'end_sec':24.15}]}
    source=copy.deepcopy(rows)
    review={'source_sha256':'source','entries':[{'segment_index':9,'start':23.83,'source_end':24.15,
        'extension_sec':.27,'confirmed_by':'user','confirmed':True,'translated_text':'शुक्रिया।','speaker_id':'A'}]}
    apply_reviewed_windows(manifest,rows,review,'source',84,[])
    assert rows[0]['start']==source[0]['start'] and rows[0]['end']==pytest.approx(24.42)
    assert rows[0]['source_asr_timing']=={'start':23.83,'end':24.15}
    assert manifest['units'][0]['duration_sec']==pytest.approx(.59)
    apply_reviewed_windows(manifest,rows,review,'source',84,[])
    assert rows[0]['end']==pytest.approx(24.42) # resume must not accumulate the allowance


def test_unapproved_or_colliding_gap_cannot_bypass_timing():
    from backend.reviewed_dub_timing import apply_reviewed_windows
    row={'segment_index':0,'start':1,'end':1.32,'translated_text':'शुक्रिया।','speaker_id':'A'}
    entry={'segment_index':0,'start':1,'source_end':1.32,'extension_sec':.27,
           'confirmed_by':'user','confirmed':False,'translated_text':'शुक्रिया।','speaker_id':'A'}
    for confirmed,other in [(False,[]),(True,[{'start':1.5,'end':2,'speaker_id':'B'}])]:
        entry['confirmed']=confirmed
        with pytest.raises(ValueError):
            apply_reviewed_windows({'units':[{'segment_index':0}]},[copy.deepcopy(row)],
                {'source_sha256':'s','entries':[entry]},'s',10,other)


def bounded_review():
    rows=[{'segment_index':15,'start':52.12,'end':52.76,'translated_text':'मिल गया आइडिया।','speaker_id':'A'},
          {'segment_index':16,'start':55.75,'end':60.15,'translated_text':'पूरी मूल line','speaker_id':'A'},
          {'segment_index':17,'start':61.13,'end':62.87,'translated_text':'अगली line','speaker_id':'B'}]
    entries=[{'segment_index':r['segment_index'],'start':r['start'],'source_end':r['end'],
              'allowance_type':'bounded_dialogue_gap','window_start':left,'window_end':right,
              'confirmed':True,'confirmed_by':'user','translated_text':r['translated_text'],
              'speaker_id':r['speaker_id']} for r,left,right in [(rows[0],52.12,53.4),(rows[1],53.6,61.1)]]
    return rows,{'source_sha256':'s','entries':entries}


def test_reviewed_bounded_gaps_keep_words_neighbors_and_original_clocks_on_resume():
    from backend.reviewed_dub_timing import apply_reviewed_windows
    rows,review=bounded_review();original=copy.deepcopy(rows)
    manifest={'units':[{'segment_index':r['segment_index']} for r in rows]}
    for _ in range(2):
        apply_reviewed_windows(manifest,rows,review,'s',84,[])
        assert [(r['start'],r['end']) for r in rows[:2]]==[(52.12,53.4),(53.6,61.1)]
        assert rows[2]==original[2]
        for row,source in zip(rows[:2],original):
            assert row['translated_text']==source['translated_text']
            assert row['source_asr_timing']=={'start':source['start'],'end':source['end']}


@pytest.mark.parametrize('change',[{'confirmed':False},{'window_start':56.0},
    {'window_end':float('nan')},{'window_end':85},{'translated_text':'changed'}])
def test_invalid_bounded_review_is_rejected_atomically(change):
    from backend.reviewed_dub_timing import apply_reviewed_windows
    rows,review=bounded_review();review['entries'][1].update(change);before=copy.deepcopy(rows)
    with pytest.raises(ValueError):
        apply_reviewed_windows({'units':[{'segment_index':r['segment_index']} for r in rows]},rows,review,'s',84,[])
    assert rows==before


def test_bounded_gaps_cannot_overlap_each_other_or_untranscribed_speech():
    from backend.reviewed_dub_timing import apply_reviewed_windows
    for collision in ('reviewed','raw'):
        rows,review=bounded_review();before=copy.deepcopy(rows)
        raw=[{'start':54,'end':54.2,'speaker_id':'B'}] if collision=='raw' else []
        if collision=='reviewed':review['entries'][0]['window_end']=54
        with pytest.raises(ValueError):
            apply_reviewed_windows({'units':[{'segment_index':r['segment_index']} for r in rows]},rows,review,'s',84,raw)
        assert rows==before


def test_existing_source_overlap_does_not_invalidate_a_clear_reviewed_extension():
    from backend.reviewed_dub_timing import apply_reviewed_windows
    rows=[{'segment_index':0,'start':1,'end':1.32,'translated_text':'शुक्रिया।','speaker_id':'A'}]
    entry={'segment_index':0,'start':1,'source_end':1.32,'extension_sec':.27,
           'confirmed_by':'user','confirmed':True,'translated_text':'शुक्रिया।','speaker_id':'A'}
    apply_reviewed_windows({'units':[{'segment_index':0}]},rows,{'source_sha256':'s','entries':[entry]},
                           's',10,[{'start':1.1,'end':1.117,'speaker_id':'B'}])
    assert rows[0]['end']==pytest.approx(1.59)
