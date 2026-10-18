import json
import pytest
from scripts.clone_voice_worker import generation_options


def test_english_synthesis_uses_english_instead_of_hindi():
    assert generation_options({'language': 'en'}, object())['language'] == 'English'
    assert generation_options({}, object())['language'] == 'Hindi'


def test_english_translation_has_separate_cache_and_target(tmp_path, monkeypatch):
    from backend import automatic_dialogue as dialogue
    source, target = tmp_path/'source.json', tmp_path/'english.json'
    source.write_text(json.dumps({'segments': [{'start': 0, 'end': 2, 'text': '你好'}]}))
    monkeypatch.setattr(dialogue, 'generate_english_batch', lambda rows, context: {0: 'Hello there.'})
    result = dialogue.translate_natural_english(source, target)
    assert result['target_language'] == 'en'
    assert result['segments'][0]['translated_text'] == 'Hello there.'
    monkeypatch.setattr(dialogue, 'generate_english_batch', lambda *_: pytest.fail('Cache should resume'))
    assert dialogue.translate_natural_english(source, target)['target_language'] == 'en'
    assert not (tmp_path/'natural_hindi_batches').exists()


def test_english_validation_does_not_accept_hindi_or_missing_words():
    from backend.automatic_dialogue import validate_english_batch
    rows = [{'segment_index': 0}]
    assert validate_english_batch({'lines': [{'segment_index': 0, 'text': 'Hello!'}]}, rows) == {0: 'Hello!'}
    with pytest.raises(ValueError):
        validate_english_batch({'lines': [{'segment_index': 0, 'text': 'नमस्ते'}]}, rows)
    with pytest.raises(ValueError):
        validate_english_batch({'lines': []}, rows)


def test_english_content_validation_never_reuses_hindi_asr_cache(tmp_path, monkeypatch):
    from backend import speech_content, kaggle_tasks, kaggle_operations
    from backend.chunk_execution import digest
    audio = tmp_path/'speech.wav'
    audio.write_bytes(b'audio-identity-fixture')
    audio.with_suffix('.content.json').write_text(json.dumps({'sha256':digest(audio), 'language':'hi',
        'compute_provider':'kaggle','transcript':'पुरानी आवाज'}), encoding='utf8')
    monkeypatch.setattr(kaggle_tasks, 'project_for', lambda *_: tmp_path)
    calls=[]
    def transcribe(path, model, language, device):
        calls.append(language)
        return {'segments':[{'text':'Hello there.'}]}
    monkeypatch.setattr(kaggle_operations,'transcribe',transcribe)
    result=speech_content.verify_clone_dialogue('Hello there.',audio,language='en')
    assert calls == ['en']
    assert result['language'] == 'en'
    assert speech_content.verify_clone_dialogue('Hello there.',audio,language='en')['transcript']=='Hello there.'
    assert calls == ['en']


def test_api_accepts_english_display_label_for_natural_translation(tmp_path, monkeypatch):
    from backend import app, automatic_dialogue
    base=tmp_path/'project';(base/'analysis').mkdir(parents=True)
    calls=[]
    monkeypatch.setattr(app,'project_dir',lambda *_: base)
    monkeypatch.setattr(app,'get_pipeline_state',lambda **_: {'stages':[{'id':'character_identity','ready':True}]})
    monkeypatch.setattr(app,'refresh_dialogue_manifest',lambda *_: {})
    monkeypatch.setattr(app,'get_project',lambda *_: {'source_path':'source.mp4'})
    monkeypatch.setattr(automatic_dialogue,'source_subtitle_context',lambda *_: [])
    def translate(source,target,**kwargs):
        calls.append('en')
        result={'target_language':'en','segments':[],'translated_segments':0}
        target.write_text(json.dumps(result),encoding='utf8')
        return result
    monkeypatch.setattr(automatic_dialogue,'translate_natural_english',translate)
    monkeypatch.setattr(app,'update_dialogue_manifest_translation',lambda **_: None)
    result=app.translate_project('sample',app.TranslationRequest(target_language='English',conversational_hindi=True))
    assert calls==['en'] and result['target_language']=='en'
