import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from backend.dubbing import translate_transcript


def _argos_module(pair_available, pivot=False):
    module = ModuleType("argostranslate.translate")
    class Lang:
        def __init__(self, code): self.code = code
        def get_translation(self, target):
            if pair_available and ((not pivot and (self.code, target.code) == ("zh", "hi")) or
                                   (pivot and (self.code, target.code) in (("zh", "en"), ("en", "hi")))):
                return type("Translation", (), {"translate": lambda self, text: f"{target.code}:{text}"})()
            return None
    module.get_installed_languages = lambda: [Lang("zh"), Lang("en"), Lang("hi")]
    return module

def test_translation_fails_once_with_actionable_error_when_argos_pair_missing(tmp_path, monkeypatch):
    source = tmp_path / "transcript.json"
    output = tmp_path / "translated.json"
    source.write_text(json.dumps({"language": "zh", "segments": [{"text": "你好"} for _ in range(48)]}), encoding="utf-8")
    argos = ModuleType("argostranslate")
    monkeypatch.setitem(sys.modules, "argostranslate", argos)
    monkeypatch.setitem(sys.modules, "argostranslate.translate", _argos_module(False))

    with pytest.raises(RuntimeError, match="Argos cannot translate zh->hi"):
        translate_transcript(source, output, "Hindi")
    assert not output.exists()


def test_translation_uses_preflighted_argos_pair(tmp_path, monkeypatch):
    source = tmp_path / "transcript.json"
    output = tmp_path / "translated.json"
    source.write_text(json.dumps({"language": "zh", "segments": [{"text": "你好"}]}), encoding="utf-8")
    monkeypatch.setitem(sys.modules, "argostranslate", ModuleType("argostranslate"))
    monkeypatch.setitem(sys.modules, "argostranslate.translate", _argos_module(True))

    result = translate_transcript(source, output, "Hindi")
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert result["errors"] == 0
    assert saved["segments"][0]["translated_text"] == "hi:你好"


def test_translation_uses_installed_language_objects_and_pivot_chain(tmp_path, monkeypatch):
    source = tmp_path / "transcript.json"
    output = tmp_path / "translated.json"
    source.write_text(json.dumps({"language": "zh", "segments": [{"text": "你好"}]}), encoding="utf-8")
    monkeypatch.setitem(sys.modules, "argostranslate", ModuleType("argostranslate"))
    monkeypatch.setitem(sys.modules, "argostranslate.translate", _argos_module(True, pivot=True))
    result = translate_transcript(source, output, "Hindi")
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert result["errors"] == 0
    assert saved["segments"][0]["translated_text"] == "hi:en:你好"


@pytest.mark.parametrize("empty", ["", "   ", None])
def test_empty_provider_output_is_a_line_error_and_valid_rows_survive(tmp_path, monkeypatch, empty):
    source = tmp_path / "transcript.json"
    output = tmp_path / "translated.json"
    source.write_text(json.dumps({"language": "zh", "segments": [{"text": "bad"}, {"text": "good"}]}), encoding="utf-8")
    module = _argos_module(True)
    langs = module.get_installed_languages()
    provider = type("Provider", (), {"translate": lambda self, text: empty if text == "bad" else "valid Hindi"})()
    langs[0].get_translation = lambda target: provider
    module.get_installed_languages = lambda: langs
    monkeypatch.setitem(sys.modules, "argostranslate", ModuleType("argostranslate"))
    monkeypatch.setitem(sys.modules, "argostranslate.translate", module)

    result = translate_transcript(source, output, "Hindi")
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert result["errors"] == 1
    assert "empty" in saved["segments"][0]["translation_error"].lower()
    assert saved["segments"][0]["translated_text"] == ""
    assert saved["segments"][1]["translated_text"] == "valid Hindi"
