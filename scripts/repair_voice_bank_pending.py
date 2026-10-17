"""Sequential source repairs; explicit unresolved speakers remain review tasks."""
from pathlib import Path
import argparse
import json
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.clone_runtime import clone_worker_slot
from backend.voice_bank_quality import write_report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--movie",type=Path,required=True)
    args=parser.parse_args()
    folder=ROOT/"runtime/voice-bank-audit"
    progress={"repaired":[],"failed":[],"requires_identity_review":[]}
    with clone_worker_slot():
        for path in sorted((folder/"records").glob("*.json")):
            record=json.loads(path.read_text(encoding="utf-8"))
            if record["audit"]["status"]=="single_speaker_candidate" and 3<=record["metrics"]["duration_sec"]<=10.01:
                continue
            voice_id=record["voice_id"]
            context=0 if record["audit"]["status"]=="single_speaker_candidate" else 8
            log_path=folder/f"repair-{voice_id}.log"
            print(f"[Repair bank] {voice_id}: real separation and exclusive speaker crops",flush=True)
            with log_path.open("w",encoding="utf-8") as log:
                result=subprocess.run([sys.executable,str(ROOT/"scripts/repair_voice_reference.py"),
                    voice_id,"--movie",str(args.movie),"--separate","--context",str(context)],
                    stdout=log,stderr=subprocess.STDOUT,timeout=1200)
            if result.returncode:
                progress["failed"].append({"voice_id":voice_id,"log":str(log_path)})
            else:
                progress["repaired"].append(voice_id)
                progress["requires_identity_review"].append(voice_id)
            write_report(folder/"repair-batch-progress.json",progress)
    progress["status"]="source_versions_ready_for_identity_review"
    write_report(folder/"repair-batch-progress.json",progress)


if __name__=="__main__":
    main()
