import json
from pathlib import Path

import pytest

from backend.voice_catalog import public_voice_name, reference_blockers


def record(**changes):
    row = {'audit': {'status': 'single_speaker_candidate', 'speech_text': 'नमस्ते।',
                     'speaker_count_detected': 1}, 'review': {},
           'metrics': {'duration_sec': 4, 'rms_dbfs': -20}}
    row.update(changes)
    return row


def test_names_are_stable_unique_aliases_without_actor_claims():
    names = [public_voice_name(f'char_{index:02d}_fixture') for index in range(1, 43)]
    assert len(set(names)) == len(names) == 42
    assert public_voice_name('char_08_bujji_samantha') == 'Meera'
    assert 'samantha' not in public_voice_name('char_08_bujji_samantha').lower()


@pytest.mark.parametrize('change', [
    {'audit': {'status': 'rejected_no_speech', 'speech_text': ''}},
    {'audit': {'status': 'single_speaker_candidate', 'speech_text': 'hi', 'speaker_count_detected': 2}},
    {'audit': {'status': 'overlapping_speakers', 'speech_text': 'hi'}},
    {'review': {'speech_present': False}},
    {'review': {'single_speaker': False}},
    {'metrics': {'duration_sec': 4, 'rms_dbfs': -85}},
])
def test_unsafe_reference_is_blocked_even_with_optimistic_catalog_metadata(change):
    assert reference_blockers(record(**change))


def test_technical_candidate_is_not_a_human_quality_approval():
    assert reference_blockers(record()) == []
    assert reference_blockers(record(audit={'status': 'not_audited'}))


def test_library_uses_selected_runtime_evidence(monkeypatch, tmp_path):
    from backend.voice_cloning import get_movie_cast_voice_bank
    from backend import voice_cloning
    catalog=tmp_path/'storage/default_voice_bank/candidate_voices'
    catalog.mkdir(parents=True)
    (catalog/'all_extracted_characters_summary.json').write_text(json.dumps({
        'characters':[{'character_id':'char_08_bujji_samantha'}]}),encoding='utf8')
    monkeypatch.setattr(voice_cloning,'__file__',str(tmp_path/'backend/voice_cloning.py'))
    monkeypatch.setenv('OPENDUB_DATA_DIR', str(tmp_path))
    folder = tmp_path / 'voice-bank-audit' / 'records'
    folder.mkdir(parents=True)
    (folder / 'char_08_bujji_samantha.json').write_text(json.dumps({
        'audit': {'status': 'rejected_no_speech'},
        'reference_path': str(tmp_path / 'selected.wav'),
    }), encoding='utf8')
    voice = next(v for v in get_movie_cast_voice_bank() if v['character_id'] == 'char_08_bujji_samantha')
    assert voice['audit']['status'] == 'rejected_no_speech'
    assert voice['display_name'] == 'Meera'
    assert voice['selection_blockers']
    assert not voice['eligible_for_defaults']


def test_automatic_assignment_does_not_fall_back_to_unreviewed_or_mixed_voice(monkeypatch):
    from backend import voice_cloning
    monkeypatch.setattr(voice_cloning, 'get_movie_cast_voice_bank', lambda: [
        {'character_id': 'bad', 'gender': 'female', 'eligible_for_defaults': False},
    ])
    result = voice_cloning.assign_movie_cast_voices([{'character_id': 'friend', 'gender': 'female'}])
    assert not result[0].get('assigned_voice')
    assert result[0]['voice_selection_status'] == 'review_required'
