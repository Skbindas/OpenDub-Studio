"""Project-scoped compute choice. Settings contain no secrets."""
import json
import re
from pathlib import Path
from .chunk_execution import save_json

ACCELERATORS = {'NvidiaTeslaT4','NvidiaL4','NvidiaL4X1','NvidiaTeslaA100','NvidiaH100','NvidiaRtxPro6000'}
DEFAULT = {'provider':'local','username':'','accelerator':'NvidiaTeslaT4','allow_media_upload':False,
           'allow_model_upload':False,'automatic_resume':True,'max_session_retries':2,
           'pipeline_ready':False,'integration_status':'implementation_unverified'}


def read_settings(base):
    path = Path(base)/'compute-settings.json'
    if not path.exists():return dict(DEFAULT)
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value,dict) or value.get('provider') not in {'local','kaggle'} or value.get('accelerator') not in ACCELERATORS:
            raise ValueError('Invalid compute settings.')
        username=value.get('username','')
        if not isinstance(username,str) or (username and not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',username)) or any(not isinstance(value.get(k,DEFAULT[k]),bool) for k in ('allow_media_upload','allow_model_upload','automatic_resume')):
            raise ValueError('Invalid account or upload choice.')
        if type(value.get('max_session_retries',2)) is not int or not 0<=value.get('max_session_retries',2)<=3:raise ValueError('Invalid retry budget.')
        if value['provider']=='kaggle' and not username:raise ValueError('Kaggle account is missing.')
        return {**DEFAULT, **{k:value[k] for k in DEFAULT if k in value},
                'pipeline_ready':False, 'integration_status':'implementation_unverified'}
    except (OSError, ValueError, TypeError):
        raise RuntimeError('Compute settings could not be read. Processing is blocked; no automatic local fallback.') from None


def write_settings(base, provider, username, accelerator, allow_media_upload,allow_model_upload=False):
    if provider not in {'local','kaggle'} or accelerator not in ACCELERATORS:
        raise ValueError('Unsupported compute provider or accelerator request.')
    if username and not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', username):
        raise ValueError('Invalid Kaggle username.')
    if provider == 'kaggle' and not username:
        raise ValueError('A Kaggle username is required.')
    data = {**DEFAULT,'provider':provider,'username':username.lower(),'accelerator':accelerator,
            'allow_media_upload':bool(allow_media_upload),'allow_model_upload':bool(allow_model_upload)}
    save_json(Path(base)/'compute-settings.json',data)
    return data
