"""Local-only bridge. Secrets enter on stdin or the OS vault, never argv."""
import contextlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def safe_diagnostic(text,env):
    for name,value in env.items():
        if value and len(value)>=6 and any(word in name.upper() for word in ('TOKEN','SECRET','PASSWORD','API_KEY','KAGGLE_KEY')):text=text.replace(value,'[REDACTED]')
    text=re.sub(r'(https?://[^\s?]+)\?[^\s]+',r'\1?[REDACTED]',text)
    text=re.sub(r'(?i)(authorization\s*[:=]\s*|bearer\s+)[^\r\n]+',r'\1[REDACTED]',text)
    text=re.sub(r'(?i)((?:api[_ -]?key|token|password|secret)\s*[\"\x27]?\s*[:=]\s*)[^\s,}]+',r'\1[REDACTED]',text)
    text=re.sub(r'(?:KGAT_|hf_|github_pat_|ghp_)[A-Za-z0-9_.-]+','[REDACTED]',text)
    text=re.sub(r'\b[A-Za-z0-9_+/=-]{40,}(?:\.[A-Za-z0-9_+/=-]+)*','[REDACTED]',text)
    return '\n'.join(text.splitlines()[-12:])[-2500:]


def main(action,body):
    from backend.kaggle_credentials import credential_status,save_credentials,subprocess_environment
    if action=='status':return {'ok':True,'data':credential_status()}
    if action=='save':return {'ok':True,'data':save_credentials(body.get('username',''),body.get('token',''),body.get('legacy_key',''))}
    if action=='cli':
        args=body['args']
        if not isinstance(args,list) or len(args)<2 or any(not isinstance(a,str) for a in args):raise ValueError('Invalid CLI request.')
        if (args[0],args[1]) not in {('datasets','list'),('datasets','create'),('datasets','status'),('datasets','files'),('datasets','download'),('kernels','list'),('kernels','push'),('kernels','status'),('kernels','output'),('kernels','logs')}:
            raise ValueError('Unsupported CLI operation.')
        env=subprocess_environment(body['username'])
        try:result=subprocess.run([sys.executable,str(ROOT/'scripts/kaggle_cli.py'),*args],env=env,capture_output=True,text=True,timeout=body.get('timeout',180))
        except subprocess.TimeoutExpired as error:
            if args[:2]==['kernels','logs']:
                partial=error.stdout or ''
                if isinstance(partial,bytes):partial=partial.decode('utf-8',errors='replace')
                return {'ok':True,'data':safe_diagnostic(partial,env),'partial_read':True}
            raise
        text=result.stdout+'\n'+result.stderr
        if result.returncode:
            value=text.lower()
            kind='quota' if 'quota' in value else 'auth' if any(x in value for x in ('401','403','unauthorized','forbidden')) else 'not_found' if any(x in value for x in ('404','not found','does not exist')) else 'provider'
            return {'ok':False,'kind':kind,'message':'Kaggle '+kind+' response.','diagnostic':safe_diagnostic(text,env)}
        for name in ('KAGGLE_API_TOKEN','KAGGLE_KEY','HF_TOKEN','GEMINI_API_KEY'):
            secret=env.get(name)
            if secret:text=text.replace(secret,'[REDACTED]')
        return {'ok':True,'data':text}
    if action=='snapshot':
        from huggingface_hub import HfApi,snapshot_download
        repo=body['repo'];revision=body.get('revision')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):raise ValueError('Invalid model repository.')
        token=os.getenv('HF_TOKEN') or None
        if not revision:revision=HfApi(token=token).model_info(repo).sha
        path=snapshot_download(repo_id=repo,revision=revision,token=token,local_files_only=body.get('local_only',False)) if body.get('download',False) else None
        return {'ok':True,'data':{'repo':repo,'revision':revision,'path':path}}
    raise ValueError('Unknown SDK action.')


if __name__=='__main__':
    os.environ['OPENDUB_KAGGLE_BRIDGE']='1'
    try:
        # Third-party imports/warnings must not corrupt or expose bridge stdout.
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            result=main(sys.argv[1],json.load(sys.stdin))
    except subprocess.TimeoutExpired:
        result={'ok':False,'kind':'uncertain','message':'Request timed out; reconcile before retrying.'}
    except Exception:
        result={'ok':False,'kind':'setup','message':'SDK, credential vault or model access setup is required. Secrets and raw logs were withheld.'}
    print(json.dumps(result))
