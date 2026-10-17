import pytest
from pydantic import ValidationError

from backend.app import SynthesisRequest


@pytest.mark.parametrize("value", [-1, True, False, "2", 1.5])
def test_synthesis_request_rejects_invalid_speaker_id(value):
    with pytest.raises(ValidationError):
        SynthesisRequest(speaker_id=value)


def test_synthesis_request_accepts_non_negative_integer_speaker_id():
    assert SynthesisRequest(speaker_id=0).speaker_id == 0
    assert SynthesisRequest(speaker_id=3).speaker_id == 3
