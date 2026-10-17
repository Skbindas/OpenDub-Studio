import numpy as np
import pytest
from backend.chunked_mix import protect_dialogue_peaks


def test_guard_preserves_background_and_changes_only_rare_dialogue_transients():
    bg=np.full((96000,2),.2,dtype='float32')
    speech=np.full_like(bg,.1)
    bg[48000]=.96
    mixed,report=protect_dialogue_peaks(bg,speech)
    assert np.max(np.abs(mixed)) <= 1
    assert np.all(bg[48000]==np.float32(.96))
    assert np.allclose(mixed[:46000],bg[:46000]+speech[:46000])
    assert report['background_gain_db']==0
    assert report['dialogue_rms_change_db'] > -.1


def test_guard_rejects_sustained_masking_instead_of_muting_speech():
    with pytest.raises(RuntimeError,match='dialogue level'):
        protect_dialogue_peaks(np.full((48000,2),.95),np.full((48000,2),.3))


def test_peak_envelope_matches_across_chunk_boundary(tmp_path):
    import soundfile as sf
    from backend.chunked_mix import render_mix_window
    background=tmp_path/'bg.wav'; voice=tmp_path/'voice.wav'
    bg=np.full((192000,2),.2,dtype='float32');bg[95970]=.96
    speech=np.full_like(bg,.1)
    sf.write(background,bg,48000,subtype='FLOAT');sf.write(voice,speech,48000,subtype='FLOAT')
    expected,_=protect_dialogue_peaks(bg,speech)
    pieces=[]
    for i in range(2):
        out=tmp_path/f'window-{i}.wav'
        render_mix_window({'start':i*2,'end':(i+1)*2,'background':str(background),
                           'protect_dialogue_peaks':True,
                           'clips':[{'file':str(voice),'start_frame':0,'frames':len(speech)}]},out)
        pieces.append(sf.read(out,dtype='float32',always_2d=True)[0])
    assert np.allclose(np.concatenate(pieces),expected,atol=1e-6)
