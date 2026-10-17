"""Read-only Git release preflight. Prints paths/reasons, never secret values.

This inventories files and current credential patterns, with optional reachable
historical blob scanning. It is not a complete secret/rights certification.
Exit 2 means blocked.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess

MEDIA = {'.wav','.mp3','.mp4','.mkv','.mov','.avi','.flac','.webm'}
WEIGHTS = {'.onnx','.ckpt','.safetensors','.pt','.pth'}
SECRETS = re.compile(r'(?:hf_[A-Za-z0-9]{30,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-[A-Za-z0-9_-]{40,})')


def inspect_path(name):
    path=Path(name)
    if path.as_posix().startswith('storage/default_voice_bank/'):
        return 'private_voice_bank_metadata'
    if path.suffix.lower() in MEDIA:return 'media_requires_distribution_permission'
    if path.suffix.lower() in WEIGHTS:return 'model_requires_separate_license_review'
    if path.name in {'kaggle.json','access_token'} or (path.name.startswith('.env') and path.name!='.env.example'):
        return 'credential_file'
    if any(part in {'runtime','.venv','node_modules'} for part in path.parts):return 'private_runtime_or_dependencies'
    return None


def audit(root, deep_history=False):
    def git(*args):
        return subprocess.check_output(['git','-C',str(root),*args]).decode('utf8',errors='replace')
    tracked=git('ls-files','-z').split('\0')
    findings=[]
    for name in filter(None,tracked):
        reason=inspect_path(name)
        if reason:findings.append({'path':name,'reason':reason})
        path=root/name
        if not reason and path.is_file() and path.stat().st_size<=1_000_000:
            content=path.read_bytes()
            if b'\0' not in content and SECRETS.search(content.decode('utf8',errors='replace')):
                findings.append({'path':name,'reason':'credential_pattern_requires_review'})
    historical=set()
    objects={}
    for row in git('rev-list','--objects','--all').splitlines():
        oid,sep,name=row.partition(' ')
        objects[oid]=name if sep else '(unnamed object)'
        if sep and inspect_path(name):historical.add(name)
    credentials=[]
    scanned=0
    if deep_history and objects:
        # Batch object reads avoid one subprocess per revision. No matched bytes
        # enter the report: it contains object IDs and paths only.
        payload=('\n'.join(objects)+'\n').encode('ascii')
        sizes=subprocess.check_output(['git','-C',str(root),'cat-file',
                                       '--batch-check=%(objectname) %(objecttype)'],input=payload)
        blobs=[row.split()[0] for row in sizes.splitlines() if row.split()[1:]==[b'blob']]
        if blobs:
            output=subprocess.check_output(['git','-C',str(root),'cat-file','--batch'],
                                           input=b'\n'.join(blobs)+b'\n')
            offset=0
            pattern=re.compile(SECRETS.pattern.encode('ascii'))
            while offset<len(output):
                end=output.index(b'\n',offset)
                oid,kind,size=output[offset:end].split()
                length=int(size)
                content=output[end+1:end+1+length]
                scanned+=1
                if pattern.search(content):
                    key=oid.decode('ascii')
                    credentials.append({'object':key,'path':objects[key],
                                        'reason':'credential_pattern_requires_review'})
                offset=end+length+2
    return {'status':'BLOCKED' if findings or historical or credentials else 'MANUAL_REVIEW_REQUIRED',
            'tracked_findings':findings,'historical_sensitive_or_media_paths':sorted(historical),
            'history_content_secret_scan':'COMPLETED_PATTERN_SCAN' if deep_history else 'NOT_PERFORMED',
            'historical_credential_findings':credentials,'historical_blobs_scanned':scanned,
            'scan_scope':'Objects reachable from local Git refs; patterns do not prove absence of every secret.',
            'asset_rights_certified':False,
            'note':'No files were changed. Removing a file from current Git does not clear history.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output',type=Path)
    parser.add_argument('--deep-history',action='store_true',help='Scan reachable historical blobs for known credential patterns; never print values.')
    args=parser.parse_args();report=audit(args.root,deep_history=args.deep_history)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps({'status':report['status'],'tracked_findings':len(report['tracked_findings']),
                      'historical_paths':len(report['historical_sensitive_or_media_paths']),
                      'history_content_secret_scan':report['history_content_secret_scan']}))
    raise SystemExit(2 if report['status']=='BLOCKED' else 0)
