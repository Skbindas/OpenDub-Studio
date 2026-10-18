import json

import pytest

from backend.auto_dub import synthesis_artifacts_ready
from backend.pipeline import update_dialogue_manifest_translation


@pytest.mark.parametrize('language,text', [('en', 'Hello'), ('hi', 'Changed line')])
def test_changed_translation_invalidates_audio_and_archives_final_outputs(tmp_path, language, text):
    analysis = tmp_path / 'analysis'
    output = tmp_path / 'output'
    analysis.mkdir()
    output.mkdir()
    speech = tmp_path / 'speech.wav'
    speech.write_bytes(b'old-speech')
    unit = {'segment_index': 0, 'duration_sec': 2, 'character_id': 'character-1',
            'translation': {'target_language': 'hi', 'text': 'Hello'},
            'tts': {'status': 'completed', 'audio_path': str(speech)},
            'timing': {'status': 'completed', 'fit_audio': 'old-fit.wav'},
            'loudness': {'status': 'completed', 'normalized_audio': 'old-level.wav'}}
    path = analysis / 'dialogue_manifest.json'
    path.write_text(json.dumps({'target_language': 'hi', 'units': [unit]}))
    for name in ('dubbed_audio_mix.wav', 'scene_dubbed.mp4', 'mix_manifest.json', 'render_qa_report.json'):
        (output / name).write_bytes(b'old-final')
    (output / 'background_preserved.wav').write_bytes(b'keep-background')
    status_path = tmp_path / 'auto_dub_status.json'
    status_path.write_text(json.dumps({'status': 'completed', 'auto_download_ready': True,
        'rendered_video_url': '/old.mp4', 'stages': [{'key': 'multi_character_tts', 'status': 'completed', 'percent': 100}]}))
    translated = {'target_language': language, 'segments': [{'segment_index': 0, 'translated_text': text,
        'dub_audio': str(speech), 'fitted_audio': 'old-fit.wav', 'normalized_audio': 'old-level.wav'}]}
    (analysis / 'translated_transcript.json').write_text(json.dumps(translated))

    result = update_dialogue_manifest_translation(manifest_path=path, translated_result=translated)

    changed = result['units'][0]
    assert all(changed[stage]['status'] == 'pending' for stage in ('tts', 'timing', 'loudness'))
    assert changed['character_id'] == 'character-1'
    assert not synthesis_artifacts_ready(tmp_path)
    assert not any(key in translated['segments'][0] for key in ('dub_audio', 'fitted_audio', 'normalized_audio'))
    saved = json.loads((analysis / 'translated_transcript.json').read_text())
    assert 'dub_audio' not in saved['segments'][0]
    assert speech.read_bytes() == b'old-speech'
    assert not (output / 'scene_dubbed.mp4').exists()
    assert not (output / 'dubbed_audio_mix.wav').exists()
    assert len(list((output / 'stale_translation').glob('*/*'))) == 4
    assert (output / 'background_preserved.wav').read_bytes() == b'keep-background'
    state = json.loads(status_path.read_text())
    assert not state['auto_download_ready'] and state['rendered_video_url'] is None
    assert state['stages'][0]['status'] == 'pending'


def test_unchanged_language_alias_and_text_preserve_completed_audio(tmp_path):
    path = tmp_path / 'analysis' / 'dialogue_manifest.json'
    path.parent.mkdir()
    audio = {'status': 'completed', 'audio_path': 'speech.wav'}
    path.write_text(json.dumps({'target_language': 'Hindi', 'units': [{
        'segment_index': 0, 'translation': {'target_language': 'Hindi', 'text': 'Hello'}, 'tts': audio}]}))
    result = update_dialogue_manifest_translation(manifest_path=path,
        translated_result={'target_language': 'hi', 'segments': [{'segment_index': 0, 'translated_text': 'Hello'}]})
    assert result['units'][0]['tts'] == audio
    assert not (tmp_path / 'output' / 'stale_translation').exists()


def test_missing_row_after_language_change_cannot_reuse_previous_language(tmp_path):
    path = tmp_path / 'analysis' / 'dialogue_manifest.json'
    path.parent.mkdir()
    path.write_text(json.dumps({'target_language': 'hi', 'units': [{
        'segment_index': 3, 'translation': {'target_language': 'hi', 'text': 'Old line'},
        'tts': {'status': 'completed', 'audio_path': 'old.wav'}}]}))
    result = update_dialogue_manifest_translation(manifest_path=path,
        translated_result={'target_language': 'en', 'segments': []})
    unit = result['units'][0]
    assert unit['tts']['status'] == 'pending'
    assert unit['translation']['status'] == 'pending'
    assert not unit['translation'].get('text')


def test_changed_line_preserves_other_lines_completed_speech(tmp_path):
    path = tmp_path / 'analysis' / 'dialogue_manifest.json'
    path.parent.mkdir()
    units = [{'segment_index': i, 'translation': {'target_language': 'en', 'text': text},
              'tts': {'status': 'completed', 'audio_path': f'{i}.wav'}}
             for i, text in enumerate(('Hello', 'Keep this'))]
    path.write_text(json.dumps({'target_language': 'en', 'units': units}))
    result = update_dialogue_manifest_translation(manifest_path=path,
        translated_result={'target_language': 'en', 'segments': [
            {'segment_index': 0, 'translated_text': 'New greeting'},
            {'segment_index': 1, 'translated_text': 'Keep this'}]})
    assert result['units'][0]['tts']['status'] == 'pending'
    assert result['units'][1]['tts'] == units[1]['tts']


def test_api_refresh_keeps_current_language_for_unchanged_english_retry(tmp_path, monkeypatch):
    from backend import app, automatic_dialogue

    analysis = tmp_path / 'analysis'
    analysis.mkdir()
    (analysis / 'transcript.json').write_text(json.dumps({'segments': [
        {'start': 0, 'end': 2, 'text': 'source'}]}))
    (analysis / 'dialogue_manifest.json').write_text(json.dumps({'target_language': 'en', 'units': [{
        'segment_id': 'seg-000001', 'segment_index': 0, 'source_text': 'source',
        'translation': {'target_language': 'en', 'text': 'Hello'},
        'tts': {'status': 'completed', 'audio_path': 'valid.wav'}}]}))
    monkeypatch.setattr(app, 'project_dir', lambda *_: tmp_path)
    monkeypatch.setattr(app, 'get_project', lambda *_: {'source_path': 'source.mp4', 'target_language': 'hi'})
    monkeypatch.setattr(app, 'read_character_registry', lambda *_: {})
    monkeypatch.setattr(app, 'require_reviewed_new_speaker_foundation', lambda *_: None)
    monkeypatch.setattr(app, 'get_pipeline_state', lambda **_: {'stages': [{'id': 'character_identity', 'ready': True}]})
    monkeypatch.setattr(automatic_dialogue, 'source_subtitle_context', lambda *_: [])

    def translate(source, target, **kwargs):
        result = {'target_language': 'en', 'segments': [{'segment_index': 0, 'translated_text': 'Hello'}]}
        target.write_text(json.dumps(result))
        return result

    monkeypatch.setattr(automatic_dialogue, 'translate_natural_english', translate)
    app.translate_project('example', app.TranslationRequest(target_language='en', conversational_hindi=True))
    saved = json.loads((analysis / 'dialogue_manifest.json').read_text())
    assert saved['target_language'] == 'en'
    assert saved['units'][0]['tts']['status'] == 'completed'
