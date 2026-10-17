import pytest
from backend.speech_content import speech_words, content_evidence, require_clone_content


def test_hindi_vowel_signs_and_virama_survive_normalization():
    assert speech_words("नई शुरुआत। खुशी हुई!") == ["नई","शुरुआत","खुशी","हुई"]
    assert speech_words("बात, बाद") == ["बात","बाद"]


def test_missing_sentence_requires_content_review():
    result = content_evidence("आज हम मिलकर एक नई शुरुआत करेंगे। आपकी बात सुनकर मुझे बहुत खुशी हुई।",
                              "आज हम मिलकर एक नई शुरुआत करेंगे।")
    assert result["status"] == "content_review_required"
    assert result["detected_word_count"] < result["expected_word_count"]


def test_asr_match_never_certifies_identity_or_naturalness():
    result = content_evidence("आपकी बात सुनकर मुझे खुशी हुई।", "आपकी बात सुनकर मुझे खुशी हुई!")
    assert result["word_sequence_similarity"] == 1
    assert result["status"] == "asr_supporting_evidence_only"
    assert result["identity"] == "listening_review_required"


def test_empty_expected_dialogue_is_invalid():
    with pytest.raises(ValueError):
        content_evidence("...", "आवाज")


def test_missing_words_block_publication_of_new_clone():
    with pytest.raises(RuntimeError,match="Previous successful audio retained"):
        require_clone_content({"status":"content_review_required","transcript":"आवाज"})
    require_clone_content({"status":"asr_supporting_evidence_only"})


def test_phonetic_asr_differences_are_advisory_not_a_regeneration_loop():
    expected="आज हम मिलकर एक नई शुरुआत करेंगे आपकी बात सुनकर मुझे बहुत खुशी हुई"
    evidence=content_evidence(expected,"आज हम मिलकर एक नहीं शुर्वात करेंगे आपकी बाद सुनकर मुझे बहुत खुशी हूँई")
    assert evidence["status"]=="content_review_required"
    assert not evidence["substantial_omission_suspected"]
    require_clone_content(evidence)
    missing=content_evidence(expected,"आज हम मिलकर एक नई शुरुआत करेंगे")
    assert missing["substantial_omission_suspected"]
    with pytest.raises(RuntimeError):
        require_clone_content(missing)
def test_reference_words_leaking_into_take_block_publication():
    expected='लड़के जल्दी गलत समझते हैं थक जाए तो उसे पानी की बोतल देना'
    actual='पलुशिन में सनसेट दिखता है नहीं मेरी रोमांटिक बात सुनो '+expected
    evidence=content_evidence(expected,actual)
    assert evidence['substantial_addition_suspected']
    with pytest.raises(RuntimeError,match='Previous successful audio retained'):
        require_clone_content(evidence)


def test_large_addition_cannot_hide_behind_an_asr_status_label():
    with pytest.raises(RuntimeError):
        require_clone_content({'status':'asr_supporting_evidence_only','substantial_addition_suspected':True})
