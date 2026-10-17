"""Resumable single-model bank auditions; never promotes defaults."""
from pathlib import Path
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.clone_runtime import clone_worker_slot
from backend.voice_bank_quality import fingerprint, write_report
from clone_voice_worker import main as generate


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    folder=ROOT/"runtime/voice-bank-audit"
    text="आज हम मिलकर एक नई शुरुआत करेंगे। आपकी बात सुनकर मुझे बहुत खुशी हुई।"
    progress={"completed":[],"retained":[],"requires_reference_repair":[],"failed":[]}
    started=time.monotonic()
    with clone_worker_slot():
        for path in sorted((folder/"records").glob("*.json")):
            record=json.loads(path.read_text(encoding="utf-8"))
            voice_id=record["voice_id"]
            clone=record.get("clone",{})
            output=folder/"clones"/f"{voice_id}.wav"
            existing=Path(clone.get("file",str(output)))
            if (clone.get("status")=="completed" and existing.is_file()
                and fingerprint(existing)==clone.get("output_sha256")
                and clone.get("reference_sha256")==record["sha256"]
                and fingerprint(Path(record["reference_path"]))==record["sha256"]
                and clone.get("ref_text")==record["audit"]["speech_text"]):
                progress["retained"].append(voice_id)
            elif record["audit"]["status"]!="single_speaker_candidate" or not 3<=record["metrics"]["duration_sec"]<=10.01:
                progress["requires_reference_repair"].append(voice_id)
            else:
                print(f"[Bank] Generating {voice_id}; model reused, original retained",flush=True)
                try:
                    result=generate({"reference":record["reference_path"],"reference_sha256":record["sha256"],
                                     "ref_text":record["audit"]["speech_text"],"output":str(output),"text":text,
                                     "prompt_dir":str(folder/"prompts"),
                                     "prosody":{"target_duration_sec":8,"generation_steps":64}})
                    record["clone"]=result
                    record["review"]={}
                    write_report(path,record)
                    progress["completed"].append(voice_id)
                except Exception as exc:
                    record["clone_attempt"]={"status":"failed","error":str(exc)}
                    write_report(path,record)
                    progress["failed"].append({"voice_id":voice_id,"error":str(exc)})
            progress["elapsed_sec"]=round(time.monotonic()-started,2)
            progress["status"]="running"
            write_report(folder/"batch-progress.json",progress)
            print(f"[Bank] {len(progress['completed'])} new, {len(progress['retained'])} retained, "
                  f"{len(progress['requires_reference_repair'])} require reference repair",flush=True)
    progress["status"]="auditions_generated_reference_repairs_pending" if progress["requires_reference_repair"] else "auditions_require_listening_review"
    write_report(folder/"batch-progress.json",progress)


if __name__=="__main__":
    main()
