"""Copy existing hash-verified repair candidates between local runtimes.

Does not select references, change acceptance, regenerate audio, or delete originals.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.voice_bank_quality import write_report


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def import_repairs(source_root: Path, target_root: Path, *, apply=False):
    source_root, target_root = source_root.resolve(), target_root.resolve()
    if source_root == target_root:
        raise ValueError('Source and destination runtime must differ.')
    source = source_root/'voice-bank-audit/repairs'
    imported, available = 0, 0
    versions = []
    for report_path in sorted(source.glob('*/*/repair.json')):
        voice_id = report_path.parent.parent.name
        record_path = target_root/'voice-bank-audit/records'/(voice_id+'.json')
        if not record_path.is_file():
            continue
        record = json.loads(record_path.read_text(encoding='utf8'))
        report = json.loads(report_path.read_text(encoding='utf8'))
        if report.get('original_sha256') != record.get('catalog_reference_sha256',record.get('sha256')):
            continue
        name = 'imported-'+sha(report_path)[:16]
        destination = target_root/'voice-bank-audit/repairs'/voice_id/name
        if (destination/'repair.json').is_file():
            continue
        mapped, files = {}, []
        # Validate every playable byte before publishing a report.
        for candidate in report.get('repairs', []):
            for path_key, hash_key, obj in [('path','sha256',candidate),('file','output_sha256',candidate.get('clone') or {})]:
                if not obj.get(path_key):
                    continue
                path = Path(obj[path_key]).resolve()
                if not path.is_relative_to(source) or not path.is_file():
                    raise ValueError('Repair audio is missing or outside the source audit folder.')
                digest = sha(path)
                if digest != obj.get(hash_key):
                    raise ValueError('Repair audio hash mismatch; original retained.')
                target = destination/(digest+path.suffix.lower())
                mapped[str(path)] = str(target)
                files.append((path,target,digest))
        if not files:
            continue
        available += 1
        versions.append({'voice_id':voice_id,'version':name})
        if not apply:
            continue
        def relocate(value):
            if isinstance(value,dict):return {k:relocate(v) for k,v in value.items()}
            if isinstance(value,list):return [relocate(v) for v in value]
            return mapped.get(value,value) if isinstance(value,str) else value
        revised = relocate(copy.deepcopy(report))
        revised['local_import'] = {'source_report_sha256':sha(report_path),
                                  'method':'byte-preserving local copy; no review or selection changed'}
        destination.mkdir(parents=True,exist_ok=True)
        for path,target,digest in files:
            if target.exists() and sha(target)!=digest:
                raise ValueError('Existing imported audio hash differs; refusing overwrite.')
            if not target.exists():shutil.copy2(path,target)
        write_report(destination/'repair.json',revised)
        imported += 1
    return {'imported':imported,'available_versions':available,'versions':versions,
            'selected_references_changed':False,'human_approval_changed':False}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--destination-root',type=Path,required=True)
    parser.add_argument('--apply',action='store_true',help='Default only validates and reports.')
    args=parser.parse_args()
    print(json.dumps(import_repairs(args.source_root,args.destination_root,apply=args.apply)))
