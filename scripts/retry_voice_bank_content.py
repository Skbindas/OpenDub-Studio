"""One bounded retry for substantial missing content; preserve accepted takes."""
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.clone_runtime import clone_worker_slot
from backend.voice_bank_quality import write_report, fingerprint
from clone_voice_worker import main as generate


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    folder=ROOT/"runtime/voice-bank-audit"
    with clone_worker_slot():
        for path in sorted((folder/"records").glob("*.json")):
            record=json.loads(path.read_text(encoding="utf-8"))
            clone=record.get("clone",{})
            if not clone.get("content_check",{}).get("substantial_omission_suspected"):
                continue
            if fingerprint(Path(clone["file"])) != clone["output_sha256"]:
                raise ValueError("Audition changed since its content check; validate before retrying")
            if record.get("audition_acceptance",{}).get("output_sha256")==clone.get("output_sha256"):
                print(record["voice_id"],"accepted audition retained",flush=True)
                continue
            if clone.get("seed")==43:
                print(record["voice_id"],"bounded retry already attempted; review required",flush=True)
                continue
            print(record["voice_id"],"one content retry with longer duration",flush=True)
            result=generate({"reference":record["reference_path"],"reference_sha256":record["sha256"],
                "ref_text":record["audit"]["speech_text"],"output":clone["file"],"text":clone["text"],
                "prompt_dir":str(folder/"prompts"),
                "prosody":{"target_duration_sec":10,"generation_steps":64,"seed":43}})
            record.setdefault("clone_history",[]).append(clone)
            record["clone"]=result
            record["review"]={}
            write_report(path,record)


if __name__=="__main__":
    main()
