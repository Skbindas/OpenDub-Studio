"""Clone versioned exclusive-speaker repairs without asserting actor identity."""
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.clone_runtime import clone_worker_slot
from backend.voice_bank_quality import fingerprint, write_report
from clone_voice_worker import main as generate


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    folder=ROOT/"runtime/voice-bank-audit"
    progress={"completed":[],"retained":[],"failed":[],"unresolved":[]}
    with clone_worker_slot():
        for report_path in sorted((folder/"repairs").glob("*/*/repair.json")):
            report=json.loads(report_path.read_text(encoding="utf-8"))
            original=json.loads((folder/"records"/f"{report['voice_id']}.json").read_text(encoding="utf-8"))
            if report["original_sha256"]!=original.get("catalog_reference_sha256",original["sha256"]):
                continue
            for candidate in report["repairs"]:
                key=f"{report['voice_id']}/{report_path.parent.name}/{candidate['speaker_id']}"
                if candidate.get("audit",{}).get("status")!="single_speaker_candidate":
                    progress["unresolved"].append(key)
                    continue
                reference=Path(candidate["path"])
                output=reference.with_name(reference.stem+"-clone.wav")
                clone=candidate.get("clone",{})
                if (clone.get("status")=="completed" and output.is_file()
                    and fingerprint(output)==clone.get("output_sha256")
                    and clone.get("ref_text")==candidate["audit"]["speech_text"]
                    and fingerprint(reference)==clone.get("reference_sha256")):
                    progress["retained"].append(key)
                    continue
                print(f"[Repair clone] {key}: identity remains unverified",flush=True)
                try:
                    candidate["clone"]=generate({"reference":str(reference),"reference_sha256":candidate["sha256"],
                        "ref_text":candidate["audit"]["speech_text"],"output":str(output),
                        "text":"आज हम मिलकर एक नई शुरुआत करेंगे। आपकी बात सुनकर मुझे बहुत खुशी हुई।",
                        "prompt_dir":str(folder/"prompts"),"prosody":{"target_duration_sec":8,"generation_steps":64}})
                    progress["completed"].append(key)
                except Exception as exc:
                    candidate["clone_attempt"]={"status":"failed","error":str(exc)}
                    progress["failed"].append({"candidate":key,"error":str(exc)})
                write_report(report_path,report)
                write_report(folder/"repaired-clone-progress.json",progress)
    progress["status"]="auditions_ready_identity_and_listening_review_required"
    write_report(folder/"repaired-clone-progress.json",progress)


if __name__=="__main__":
    main()
