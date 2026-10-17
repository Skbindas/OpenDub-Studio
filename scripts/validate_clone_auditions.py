"""Check generated Hindi content; never substitute ASR for an identity audition."""
from pathlib import Path
import json
import sys
import argparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.voice_bank_quality import fingerprint, write_report
from backend.speech_content import content_evidence


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=("small","medium"), default="small")
    parser.add_argument("--include-repairs", action="store_true")
    args = parser.parse_args()
    from faster_whisper import WhisperModel
    model = WhisperModel(args.model, device="cpu", compute_type="int8", cpu_threads=4, local_files_only=True)
    folder = ROOT / "runtime/voice-bank-audit"
    paths = sorted((folder / "records").glob("*.json"))
    if args.include_repairs:
        paths += sorted((folder / "repairs").glob("*/*/repair.json"))
    for path in paths:
        record = json.loads(path.read_text(encoding="utf-8"))
        targets = [item.get("clone", {}) for item in record["repairs"]] if "repairs" in record else [record.get("clone", {})]
        for clone in targets:
            validate(clone, record, path, model, args.model)


def validate(clone, record, path, model, model_name):
    output = Path(clone.get("file", ""))
    if clone.get("status") != "completed" or not output.is_file():
        return
    digest = fingerprint(output)
    if digest != clone.get("output_sha256"):
        raise ValueError("Clone changed; existing validation cannot be reused")
    if (clone.get("content_check", {}).get("sha256") == digest and
        clone["content_check"].get("model") == f"faster-whisper-{model_name}" and
        clone["content_check"].get("validator_version") == 2 and
        "substantial_omission_suspected" in clone["content_check"]):
        return
    segments, info = model.transcribe(str(output), language="hi", vad_filter=True, beam_size=3)
    transcript = " ".join(s.text.strip() for s in segments)
    if clone.get("content_check"):
        clone.setdefault("content_check_history",[]).append(clone["content_check"])
    clone["content_check"] = {"sha256":digest, "model":f"faster-whisper-{model_name}", "transcript":transcript,
        "validator_version":2, **content_evidence(clone["text"],transcript)}
    write_report(path, record)
    print(record["voice_id"], clone["content_check"], flush=True)


if __name__ == "__main__":
    main()
