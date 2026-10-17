import subprocess

from scripts.audit_public_release import audit, inspect_path


def test_private_voice_metadata_requires_release_review_even_without_audio():
    assert inspect_path('storage/default_voice_bank/candidate_voices/voice.json') == 'private_voice_bank_metadata'


def test_deep_scan_finds_removed_secret_without_disclosing_value(tmp_path):
    def git(*args):
        return subprocess.run(['git', '-C', str(tmp_path), *args], check=True, capture_output=True)
    git('init')
    git('config', 'user.email', 'test@example.invalid')
    git('config', 'user.name', 'Release audit test')
    secret = 'hf_' + 'x' * 34
    source = tmp_path / 'old_config.txt'
    source.write_text('token=' + secret)
    git('add', '.')
    git('commit', '-m', 'Historical test fixture')
    source.write_text('token=removed')
    git('add', '.')
    git('commit', '-m', 'Remove fixture')
    result = audit(tmp_path, deep_history=True)
    assert result['status'] == 'BLOCKED'
    assert result['history_content_secret_scan'] == 'COMPLETED_PATTERN_SCAN'
    assert result['historical_credential_findings'][0]['path'] == 'old_config.txt'
    assert secret not in str(result)
    assert source.read_text() == 'token=removed'


def test_deep_scan_clean_repository_still_requires_manual_review(tmp_path):
    subprocess.run(['git', 'init', str(tmp_path)], check=True, capture_output=True)
    (tmp_path / 'README.md').write_text('No credentials or media.')
    subprocess.run(['git', '-C', str(tmp_path), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(tmp_path), '-c', 'user.name=Test',
                    '-c', 'user.email=test@example.invalid', 'commit', '-m', 'Clean'],
                   check=True, capture_output=True)
    result = audit(tmp_path, deep_history=True)
    assert result['status'] == 'MANUAL_REVIEW_REQUIRED'
    assert result['historical_blobs_scanned'] == 1
    assert not result['historical_credential_findings']
    assert result['asset_rights_certified'] is False


def test_removing_current_media_does_not_hide_historical_release_blocker(tmp_path):
    def git(*args):
        subprocess.run(['git','-C',str(tmp_path),*args],check=True,capture_output=True)
    git('init')
    git('config','user.email','test@example.invalid')
    git('config','user.name','Release audit test')
    audio=tmp_path/'private.wav'
    audio.write_bytes(b'private fixture bytes')
    git('add','private.wav')
    git('commit','-m','Private fixture')
    git('rm','--cached','private.wav')
    git('commit','-m','Untrack but preserve audio')
    result=audit(tmp_path)
    assert result['status']=='BLOCKED'
    assert result['tracked_findings']==[]
    assert 'private.wav' in result['historical_sensitive_or_media_paths']
    assert audio.read_bytes()==b'private fixture bytes'
    assert result['history_content_secret_scan']=='NOT_PERFORMED'
