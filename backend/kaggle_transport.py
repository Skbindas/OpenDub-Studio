"""Official CLI transport; credentials live only in the child environment."""
import importlib.util
import subprocess
import sys
import re
from .kaggle_credentials import subprocess_environment


class ProviderError(RuntimeError):
    def __init__(self, kind, message):
        self.kind = kind
        super().__init__(message)


def run(username, args, timeout=180):
    from .kaggle_runtime import invoke
    try:result=invoke('cli',{'username':username,'args':args,'timeout':timeout},timeout=timeout+15)
    except RuntimeError as exc:raise ProviderError('setup',str(exc)) from None
    if not result.get('ok'):
        message=result.get('message','Kaggle request failed.')
        if result.get('diagnostic'):message+=' '+result['diagnostic']
        raise ProviderError(result.get('kind','provider'),message)
    return result['data']


def kernel_status(username, handle):
    value=provider_status(run(username,['kernels','status',handle],timeout=60))
    return {'complete':'completed','completed':'completed','running':'running','queued':'queued',
            'error':'failed','failed':'failed','cancelled':'cancelled','canceled':'cancelled',
            'cancel_acknowledged':'cancelled','cancel_requested':'running','new_script':'queued'}.get(value,'unknown')


def provider_status(text):
    # Match a status field, never a word appearing in an account/handle/warning.
    value=text.strip().lower()
    match=re.search(r'\bstatus\b[\s\"\x27:=]*(?:kernelworkerstatus\.)?([a-z_]+)',value)
    return match.group(1) if match else value if re.fullmatch('[a-z_]+',value) else 'unknown'


def dataset_ready(text):return provider_status(text) in {'ready','complete','completed'}
