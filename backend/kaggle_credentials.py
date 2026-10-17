"""Write-only OS vault credentials; never use a plaintext fallback."""
import importlib.util
import json
import os
import re

SERVICE = 'OpenDub Studio Kaggle'
ACCOUNT = 'credentials-v1'


def _vault():
    try:
        import keyring
        backend = keyring.get_keyring()
        # keyrings.alt file stores are not suitable for API credentials.
        trusted=('keyring.backends.Windows','keyring.backends.macOS','keyring.backends.SecretService','keyring.backends.kwallet','keyring.backends.libsecret')
        if type(backend).__module__.startswith('keyring.backends.chainer'):
            choices=[item for item in backend.backends if item.priority>0 and type(item).__module__.startswith(trusted)]
            if not choices:raise RuntimeError('A secure OS credential vault is unavailable.')
            backend=choices[0];keyring.set_keyring(backend)
        if backend.priority <= 0 or not type(backend).__module__.startswith(trusted):
            raise RuntimeError('A secure OS credential vault is unavailable.')
        return keyring
    except ImportError:
        raise RuntimeError('Install requirements-kaggle.txt before saving credentials.') from None


def save_credentials(username, token, legacy_key=''):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', username):
        raise ValueError('Enter the Kaggle account username, not an email or URL.')
    if bool(token) == bool(legacy_key):
        raise ValueError('Supply an API token or legacy key, not both.')
    if len(token or legacy_key)>16384:raise ValueError('Credential is too long.')
    if any(c in (token or legacy_key) for c in '\r\n\0'):
        raise ValueError('Credential contains invalid characters.')
    if os.getenv('OPENDUB_KAGGLE_BRIDGE')!='1':
        from .kaggle_runtime import invoke
        result=invoke('save',{'username':username,'token':token,'legacy_key':legacy_key})
        if not result.get('ok'):raise RuntimeError(result.get('message','Credential vault unavailable.'))
        return result['data']
    _vault().set_password(SERVICE, ACCOUNT, json.dumps({'username':username.lower(), 'token':token, 'key':legacy_key}))
    return {'saved':True, 'storage':'operating-system credential vault'}


def _stored():
    try:
        value = _vault().get_password(SERVICE, ACCOUNT)
        data=json.loads(value) if value else {}
        return data if isinstance(data,dict) and isinstance(data.get('username',''),str) else {}
    except Exception:
        return {}


def credential_status():
    if os.getenv('OPENDUB_KAGGLE_BRIDGE')!='1':
        from .kaggle_runtime import invoke,python_path
        if python_path().is_file():
            try:
                result=invoke('status',timeout=20)
                if result.get('ok'):return result['data']
            except RuntimeError:pass
        return {'cli_installed':False,'vault_installed':False,'configured':False,'username':None,
                'authentication':'unverified','gpu_eligibility':'unverified','quota_remaining':None,'secret_returned':False}
    stored = _stored()
    env_ready = bool(os.getenv('KAGGLE_API_TOKEN') or (os.getenv('KAGGLE_USERNAME') and os.getenv('KAGGLE_KEY')))
    return {'cli_installed':importlib.util.find_spec('kaggle') is not None,
            'vault_installed':importlib.util.find_spec('keyring') is not None,
            'configured':bool(stored or env_ready),
            'username':stored.get('username') or os.getenv('KAGGLE_USERNAME') or None,
            'authentication':'unverified', 'gpu_eligibility':'unverified', 'quota_remaining':None,
            'secret_returned':False}


def subprocess_environment(username):
    """Bind each submission to the selected account; do not inherit another account."""
    env = dict(os.environ)
    stored = _stored()
    if stored:
        if stored.get('username','').lower() != username.lower():
            raise RuntimeError('Stored credentials belong to a different Kaggle account.')
        for key in ('KAGGLE_API_TOKEN','KAGGLE_USERNAME','KAGGLE_KEY'):
            env.pop(key, None)
        if stored.get('token'):
            env['KAGGLE_API_TOKEN'] = stored['token']
        else:
            env.update(KAGGLE_USERNAME=username, KAGGLE_KEY=stored['key'])
    elif os.getenv('KAGGLE_USERNAME','').lower() != username.lower():
        # A bare token's owner has to be supplied explicitly with KAGGLE_USERNAME.
        raise RuntimeError('Configure credentials for this account before submission.')
    if not env.get('KAGGLE_API_TOKEN') and not env.get('KAGGLE_KEY'):
        raise RuntimeError('Kaggle credentials are not configured.')
    return env
