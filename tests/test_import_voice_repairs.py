import hashlib
import json
from pathlib import Path

import pytest

from scripts.import_voice_repairs import import_repairs


def fixture(tmp_path):
    source, target = tmp_path/'source', tmp_path/'target'
    folder = source/'voice-bank-audit/repairs/char_01_example/version1'
    folder.mkdir(parents=True)
    audio = folder/'reference.wav'
    audio.write_bytes(b'preserved genuine audio fixture')
    digest = hashlib.sha256(audio.read_bytes()).hexdigest()
    report = {'original_sha256':'original', 'repairs':[{'path':str(audio), 'sha256':digest}]}
    (folder/'repair.json').write_text(json.dumps(report))
    records = target/'voice-bank-audit/records'
    records.mkdir(parents=True)
    (records/'char_01_example.json').write_text(json.dumps({'sha256':'original'}))
    return source, target, audio


def test_import_is_non_destructive_hash_checked_and_idempotent(tmp_path):
    source,target,audio = fixture(tmp_path)
    before = audio.read_bytes()
    assert import_repairs(source,target,apply=False)['imported'] == 0
    first = import_repairs(source,target,apply=True)
    assert first['imported'] == 1
    report = next((target/'voice-bank-audit/repairs').glob('*/*/repair.json'))
    row = json.loads(report.read_text())['repairs'][0]
    assert Path(row['path']).is_relative_to(target)
    assert Path(row['path']).read_bytes() == before == audio.read_bytes()
    assert import_repairs(source,target,apply=True)['imported'] == 0


def test_changed_source_audio_is_not_imported(tmp_path):
    source,target,audio = fixture(tmp_path)
    audio.write_bytes(b'tampered')
    with pytest.raises(ValueError, match='hash'):
        import_repairs(source,target,apply=True)
