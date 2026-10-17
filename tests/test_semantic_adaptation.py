import json

import pytest

from backend import semantic_adaptation as provider


def test_character_context_uses_only_saved_descriptive_fields():
    context = provider.format_character_context({
        "characters": [{
            "character_id": "char-1",
            "display_name": "Asha",
            "description": "A cautious village doctor",
            "personality": "measured",
            "voice_profile": {"model_path": "/private/model.pth"},
            "api_key": "should-not-leak",
        }]
    }, "char-1")
    assert "Asha" in context
    assert "cautious village doctor" in context
    assert "private/model" not in context
    assert "should-not-leak" not in context


def test_character_context_does_not_infer_missing_identity():
    context = provider.format_character_context({"characters": []}, "char-missing")
    assert "do not infer identity traits" in context


def test_provider_disabled_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENDUB_LLM_API_KEY", raising=False)
    assert provider.semantic_provider_configured() is False
    with pytest.raises(provider.SemanticAdaptationError, match="not configured"):
        provider.propose_semantic_adaptation(
            source_text="Hello", translated_text="नमस्ते",
            source_language="English", target_language="Hindi",
        )


def test_provider_returns_review_only_suggestion(monkeypatch):
    monkeypatch.setenv("OPENDUB_LLM_API_KEY", "test-key")
    monkeypatch.setenv("OPENDUB_LLM_MODEL", "test-model")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _limit):
            return json.dumps({
                "choices": [{"message": {"content": json.dumps({
                    "suggested_text": "  अरे, तुम यहाँ कैसे आए?  "
                }, ensure_ascii=False)}}]
            }).encode()

    captured = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode())
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(provider, "urlopen", fake_urlopen)
    result = provider.propose_semantic_adaptation(
        source_text="How did you get here?",
        translated_text="तुम यहाँ कैसे आए?",
        source_language="English",
        target_language="Hindi",
        character_identity="Young adult, informal",
        tone="surprised",
        delivery_intent="conversational",
        max_words=7,
        source_duration_sec=2.0,
    )

    assert result["suggested_text"] == "अरे, तुम यहाँ कैसे आए?"
    assert result["requires_review"] is True
    assert result["production_ready"] is False
    assert result["validation_status"] == "pending"
    assert result["semantic_rewrite"] is True
    assert captured["payload"]["model"] == "test-model"
    assert captured["payload"]["temperature"] == 0.2


def test_provider_rejects_malformed_model_response(monkeypatch):
    monkeypatch.setenv("OPENDUB_LLM_API_KEY", "test-key")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _limit):
            return b'{"choices":[{"message":{"content":"not json"}}]}'

    monkeypatch.setattr(provider, "urlopen", lambda *args, **kwargs: FakeResponse())
    with pytest.raises(provider.SemanticAdaptationError, match="malformed JSON"):
        provider.propose_semantic_adaptation(
            source_text="Hello", translated_text="नमस्ते",
            source_language="English", target_language="Hindi",
        )


def test_provider_rejects_oversized_candidate(monkeypatch):
    monkeypatch.setenv("OPENDUB_LLM_API_KEY", "test-key")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _limit):
            text = json.dumps({"suggested_text": "x" * 5001})
            return json.dumps({
                "choices": [{"message": {"content": text}}]
            }).encode()

    monkeypatch.setattr(provider, "urlopen", lambda *args, **kwargs: FakeResponse())
    with pytest.raises(provider.SemanticAdaptationError, match="5000-character"):
        provider.propose_semantic_adaptation(
            source_text="Hello", translated_text="नमस्ते",
            source_language="English", target_language="Hindi",
        )


@pytest.mark.parametrize("registry", [None, [], {"characters": "not-a-list"}])
def test_character_context_handles_malformed_registry(registry):
    context = provider.format_character_context(registry, "char-1")
    assert "do not infer identity traits" in context
