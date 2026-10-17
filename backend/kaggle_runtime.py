"""Isolated optional SDK bridge: no SDK imports in the main media environment."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def python_path():
    return Path(os.getenv('OPENDUB_KAGGLE_PYTHON') or ROOT/'runtime/kaggle-env'/('Scripts/python.exe' if os.name=='nt' else 'bin/python'))


def invoke(action,payload=None,timeout=180):
    python=python_path()
    if not python.is_file():raise RuntimeError('Kaggle SDK runtime missing. Run scripts/setup_kaggle.py first.')
    try:
        result=subprocess.run([str(python),str(ROOT/'scripts/kaggle_bridge.py'),action],
            input=json.dumps(payload or {}),capture_output=True,text=True,encoding='utf-8',timeout=timeout,
            env={**os.environ,'OPENDUB_KAGGLE_BRIDGE':'1','PYTHONUTF8':'1'},
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    except subprocess.TimeoutExpired:
        return {'ok':False,'kind':'uncertain','message':'Provider operation timed out. Reconcile its existing handle before retrying.'}
    try:data=json.loads(result.stdout)
    except ValueError:raise RuntimeError('Isolated SDK bridge failed; no secret-bearing logs were returned.') from None
    if not isinstance(data,dict):raise RuntimeError('Invalid SDK bridge response.')
    return data
