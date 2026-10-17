import pytest
from scripts import clone_voice_worker as worker


def test_natural_speech_mode_keeps_source_window_out_of_fixed_model_duration():
    options = worker.generation_options(
        {'target_duration_sec': .64, 'duration_mode': 'natural', 'rate': .95}, 'reviewed-prompt')
    assert 'duration' not in options
    assert options['speed'] == .95
    assert options['voice_clone_prompt'] == 'reviewed-prompt'


def test_existing_fixed_duration_and_invalid_mode_remain_explicit():
    assert worker.generation_options({'target_duration_sec': 3.2}, None)['duration'] == 3.2
    with pytest.raises(ValueError, match='duration mode'):
        worker.generation_options({'duration_mode': 'unrecognized'}, None)
