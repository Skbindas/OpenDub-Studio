import shutil
import wave
import numpy as np
import pytest
import soundfile as sf
from backend.mixing import fit_audio


def test_short_word_window_uses_exclusive_detected_speech_not_arbitrary_padding():
    from backend.pipeline import recover_short_speech_window
    rows=[{'start':1.,'end':1.32,'speaker_id':'A'}]
    turns=[{'start':.8,'end':1.55,'speaker_id':'A'}]
    assert recover_short_speech_window(rows,0,turns) == (.8,1.55)
    assert recover_short_speech_window(rows,0,[]) == (1.,1.32)
    assert recover_short_speech_window(rows+[{'start':1.4,'end':2.,'speaker_id':'A'}],0,turns) == (1.,1.32)
    assert recover_short_speech_window(rows,0,turns+[{'start':1.2,'end':1.5,'speaker_id':'B'}]) == (1.,1.32)
    assert recover_short_speech_window(rows+[{'start':1.32,'end':2.,'speaker_id':'B'}],0,turns) == (.8,1.32)


def test_initial_timing_budget_limits_rate_without_rewriting_dialogue():
    from backend.dubbing import plan_speech_rate
    long = plan_speech_rate('यह बहुत लंबा संवाद है जिसे सामान्य तरीके से बोलना चाहिए।', .4)
    short = plan_speech_rate('हाँ', 5)
    assert long['rate'] == 1.1
    assert long['needs_shorter_dialogue']
    assert short['rate'] == .9
    assert plan_speech_rate('हाँ', 0)['rate'] == 1


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='FFmpeg required')
def test_large_overrun_is_not_cut_or_accelerated_beyond_limit(tmp_path):
    source, output = tmp_path/'voice.wav', tmp_path/'fit.wav'
    sf.write(source, .2*np.sin(np.arange(96000)*.05), 48000, subtype='PCM_16')
    result = fit_audio(source, output, .5, max_speedup=1.15, pad_short=True)
    assert result['duration_fit_limited']
    assert result['applied_tempo'] == 1.15
    assert sf.info(output).duration > 1.6
    assert not result['speech_truncated']


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='FFmpeg required')
def test_short_speech_keeps_natural_tempo_and_fills_window(tmp_path):
    source, output = tmp_path/'voice.wav', tmp_path/'fit.wav'
    sf.write(source, .2*np.sin(np.arange(48000)*.05), 48000, subtype='PCM_16')
    result = fit_audio(source, output, 3, max_slowdown=.9, pad_short=True)
    assert not result['duration_fit_limited']
    assert result['applied_tempo'] == .9
    assert abs(sf.info(output).duration-3) < .001
    assert result['silence_padding_sec'] > 1.8
    assert not result['speech_truncated']


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='FFmpeg required')
def test_trimmed_silence_does_not_make_a_short_utterance_fail(tmp_path):
    source, output = tmp_path/'voice.wav', tmp_path/'fit.wav'
    tone = .2*np.sin(np.arange(48000)*.05)
    sf.write(source, np.concatenate([np.zeros(24000),tone,np.zeros(24000)]),48000,subtype='PCM_16')
    result=fit_audio(source,output,1.1,trim_silence=True,pad_short=True)
    assert not result['duration_fit_limited']
    assert abs(sf.info(output).duration-1.1) < .03
    assert result['leading_silence_duration'] > .4
    assert not result['speech_truncated']
