"""Unicode-safe supporting evidence for speech content; not a listening verdict."""
from difflib import SequenceMatcher
import unicodedata
import json
from pathlib import Path
import subprocess
import sys
import threading
import tempfile
import os
import time
from contextlib import contextmanager

_content_validation_lock = threading.Lock()


def speech_words(text: str) -> list[str]:
    # Python's \w excludes combining marks, including Hindi vowel signs/virama.
    # Keep letters, marks and numbers; replace punctuation with boundaries.
    normalized = unicodedata.normalize("NFC", text).casefold()
    return "".join(character if unicodedata.category(character)[0] in "LMN" else " "
                   for character in normalized).split()


def content_evidence(expected: str, transcript: str) -> dict:
    expected_words, actual_words = speech_words(expected), speech_words(transcript)
    if not expected_words:
        raise ValueError("Expected dialogue is empty")
    similarity = SequenceMatcher(None, expected_words, actual_words).ratio()
    character_similarity = SequenceMatcher(None, "".join(expected_words), "".join(actual_words)).ratio()
    # Short Hindi words and phonetic spellings are unreliable in small-model ASR.
    # Block substantial omissions, not minor transcript differences in a take
    # that still needs listening review.
    substantial = not actual_words or (len(expected_words) >= 4 and
                  (len(actual_words) < .65 * len(expected_words) or character_similarity < .55))
    # Large reference-text leakage needs review even when the requested words survive.
    addition = len(actual_words) - len(expected_words) > max(3, .5 * len(expected_words))
    return {"word_sequence_similarity":round(similarity,3),
            "character_similarity":round(character_similarity,3),
            "substantial_omission_suspected":substantial,
            "substantial_addition_suspected":addition,
            "expected_word_count":len(expected_words), "detected_word_count":len(actual_words),
            "status":"content_review_required" if similarity < .85 else "asr_supporting_evidence_only",
            "identity":"listening_review_required", "emotion":"not_validated"}


_content_process = None
_content_log = None
_content_warm = False


@contextmanager
def warm_content_batch(enabled=True):
    global _content_warm, _content_process, _content_log
    _content_warm = enabled
    try:
        yield
    finally:
        _content_warm = False
        with _content_validation_lock:
            if _content_process is not None:
                _content_process.stdin.close()
                try:
                    _content_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    _content_process.terminate()
                    _content_process.wait(timeout=10)
                _content_process = None
            if _content_log is not None:
                _content_log.close()
                _content_log = None


def _warm_content_check(root, audio, report):
    global _content_process, _content_log
    if _content_process is None or _content_process.poll() is not None:
        if _content_log:
            _content_log.close()
        _content_log = (root / 'runtime/content-batch.log').open('a', encoding='utf-8')
        _content_process = subprocess.Popen([sys.executable, str(root/'scripts/check_speech_content.py'), '--serve'],
            stdin=subprocess.PIPE, stdout=_content_log, stderr=subprocess.STDOUT, text=True, encoding='utf-8',
            env={**os.environ,'PYTHONIOENCODING':'utf-8','CUDA_VISIBLE_DEVICES':'-1'})
    with tempfile.TemporaryDirectory(prefix='content-request-',dir=audio.parent) as folder:
        request = Path(folder)/'request.json'
        request.write_text(json.dumps({'audio':str(audio.resolve()),'output':str(report.resolve())}),encoding='utf-8')
        _content_process.stdin.write(str(request)+'\n'); _content_process.stdin.flush()
        done = request.with_name('content-worker-result.json')
        deadline = time.monotonic()+240
        while not done.is_file():
            if _content_process.poll() is not None:
                raise RuntimeError('CPU content worker exited; previous speech retained. Inspect runtime/content-batch.log')
            if time.monotonic()>deadline:
                _content_process.terminate(); _content_process.wait(timeout=10)
                raise RuntimeError('CPU content validation timed out; previous speech retained')
            time.sleep(.1)
        result=json.loads(done.read_text(encoding='utf-8'))
        if not result.get('ok'):
            raise RuntimeError(result.get('error') or 'CPU content check failed')


def verify_clone_dialogue(expected: str, audio: Path) -> dict:
    from .kaggle_tasks import project_for
    if project_for(audio):
        from .kaggle_operations import transcribe
        from .chunk_execution import digest,save_json
        cached=audio.with_suffix('.content.json')
        if cached.is_file():
            evidence=json.loads(cached.read_text(encoding='utf-8'))
            if evidence.get('sha256')==digest(audio) and evidence.get('compute_provider')=='kaggle':
                evidence.update(content_evidence(expected,evidence['transcript']));return evidence
        result=transcribe(audio,'small','hi','cuda')
        evidence={'sha256':digest(audio),'transcript':' '.join(row['text'] for row in result['segments']),
            'model':'faster-whisper-small/pinned-kaggle','validator_version':2,'compute_provider':'kaggle'}
        evidence.update(content_evidence(expected,evidence['transcript']));save_json(audio.with_suffix('.content.json'),evidence)
        return evidence
    """Validate in a disposable CPU worker before publishing a project revision."""
    from .voice_bank_quality import fingerprint
    root = Path(__file__).resolve().parents[1]
    report = audio.with_suffix(".content.json")
    log_path = audio.with_suffix(".content.log")
    with _content_validation_lock, log_path.open("w", encoding="utf-8") as log:
        if _content_warm:
            _warm_content_check(root, audio, report)
            returncode = 0
        else:
            result = subprocess.run([sys.executable, str(root / "scripts/check_speech_content.py"),
                                     str(audio), str(report)], stdout=log, stderr=subprocess.STDOUT,
                                    timeout=240)
            returncode = result.returncode
    if returncode or not report.is_file():
        raise RuntimeError(f"Hindi content validation failed; previous audio retained. See {log_path}")
    evidence = json.loads(report.read_text(encoding="utf-8"))
    if evidence.get("sha256") != fingerprint(audio):
        raise RuntimeError("Generated audio changed during content validation")
    evidence.update(content_evidence(expected, evidence["transcript"]))
    return evidence


def require_clone_content(evidence: dict) -> None:
    if evidence.get("substantial_addition_suspected", False) or (
            evidence.get("status") != "asr_supporting_evidence_only" and evidence.get("substantial_omission_suspected", True)):
        raise RuntimeError("Generated Hindi words need review before replacing project audio: "
                           + evidence.get("transcript", "") + ". Previous successful audio retained.")
