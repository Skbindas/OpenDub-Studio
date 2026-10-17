import numpy as np,soundfile as sf


def test_original_song_audio_outside_dialogue_is_retained(tmp_path):
    from backend.selective_background import preserve_non_dialogue_audio
    sample_rate=48000
    source=np.random.default_rng(7).integers(-12000,12000,(sample_rate*3,2),dtype=np.int16)
    instrumental=source//4
    sf.write(tmp_path/'source.wav',source,sample_rate,subtype='PCM_16')
    sf.write(tmp_path/'stem.wav',instrumental,sample_rate,subtype='PCM_16')
    result=preserve_non_dialogue_audio(tmp_path/'source.wav',tmp_path/'stem.wav',tmp_path/'out.wav',[(1,2)])
    output,_=sf.read(tmp_path/'out.wav',dtype='int16')
    assert np.array_equal(output[:int(.8*sample_rate)],source[:int(.8*sample_rate)])
    assert np.array_equal(output[int(2.2*sample_rate):],source[int(2.2*sample_rate):])
    assert np.array_equal(output[int(1.2*sample_rate):int(1.8*sample_rate)],instrumental[int(1.2*sample_rate):int(1.8*sample_rate)])
    assert result['original_outside_dialogue_retained'] and result['gain_db']==0


def test_unmatched_stem_cannot_be_used_as_preserved_background(tmp_path):
    import pytest
    from backend.selective_background import preserve_non_dialogue_audio
    sf.write(tmp_path/'source.wav',np.zeros((48000,2)),48000)
    sf.write(tmp_path/'stem.wav',np.zeros((24000,2)),48000)
    with pytest.raises(ValueError):preserve_non_dialogue_audio(tmp_path/'source.wav',tmp_path/'stem.wav',tmp_path/'out.wav',[(0,1)])
    assert not (tmp_path/'out.wav').exists()


def test_valid_signed_pcm_negative_endpoint_is_preserved_without_gain():
    from backend.chunked_mix import protect_dialogue_peaks
    background=np.array([[-1.,0.],[32767/32768,0.]],dtype=np.float32)
    result,report=protect_dialogue_peaks(background,np.zeros_like(background))
    assert np.array_equal(result,background) and report['background_gain_db']==0


def test_floating_background_overflow_still_blocks_the_mix():
    import pytest
    from backend.chunked_mix import protect_dialogue_peaks
    for sample in [-1.001,1.0]:
        with pytest.raises(RuntimeError):protect_dialogue_peaks(np.array([[sample,0.]],dtype=np.float32),np.zeros((1,2),dtype=np.float32))
