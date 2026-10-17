"""Fail closed before submitting source or portable task metadata."""
import json
import re

PATTERNS=(r'AIza[\w-]{30,}',r'github_pat_[A-Za-z0-9_]{40,}',r'gh[pousr]_[A-Za-z0-9]{30,}',
          r'hf_[A-Za-z0-9]{25,}',r'KGAT_[A-Za-z0-9_-]{15,}',
          r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----')
SECRET_FIELDS={'hf_token','api_token','api_key','legacy_key','password','authorization','kaggle_key'}


def check_text(text):
    if any(re.search(pattern,text) for pattern in PATTERNS):
        raise RuntimeError('Credential-like content detected. Nothing was uploaded.')


def check_source(path):check_text(path.read_text(encoding='utf-8'))


def check_metadata(value):
    check_text(json.dumps(value,ensure_ascii=False))
    def visit(item):
        if isinstance(item,dict):
            for key,child in item.items():
                if key.lower() in SECRET_FIELDS and child:raise RuntimeError('Secrets are forbidden in remote task metadata.')
                visit(child)
        elif isinstance(item,list):
            for child in item:visit(child)
    visit(value)
