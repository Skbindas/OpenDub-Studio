"""Generate real auditions for audited references. Does not promote defaults."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.clone_runtime import synthesize_reference
from backend.voice_bank_quality import fingerprint, write_report, bank_summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--voice-id", action="append")
    parser.add_argument("--text", default="आज हम मिलकर एक नई शुरुआत करेंगे। आपकी बात सुनकर मुझे बहुत खुशी हुई।")
    parser.add_argument("--duration", type=float, default=8)
    parser.add_argument("--steps", type=int, default=64)
    parser.add_argument("--ref-text", help="Corrected reference words; requires exactly one voice ID")
    args = parser.parse_args()
    if args.ref_text and (not args.voice_id or len(args.voice_id) != 1):
        parser.error("--ref-text requires exactly one --voice-id")
    folder = ROOT / "runtime/voice-bank-audit"
    timings = []
    for path in sorted((folder / "records").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        voice_id = record["voice_id"]
        if args.voice_id and voice_id not in args.voice_id:
            continue
        if record["audit"]["status"] != "single_speaker_candidate" or not 3 <= record["metrics"]["duration_sec"] <= 10.01:
            print(f"[Clone bank] Skipped {voice_id}: reference needs repair/review", flush=True)
            continue
        reference = Path(record["reference_path"])
        if args.ref_text:
            record["audit"].setdefault("speech_text_asr", record["audit"]["speech_text"])
            record["audit"]["speech_text"] = args.ref_text.strip()
            record["transcript_review"] = {"status":"corrected_words_require_listening_confirmation"}
            record["review"] = {}
            write_report(path, record)
        if fingerprint(reference) != record["sha256"]:
            raise RuntimeError("Reference changed; audit again before cloning")
        output = folder / "clones" / f"{voice_id}.wav"
        previous = record.get("clone", {})
        if (previous and output.is_file() and previous.get("reference_conditioned") and previous.get("reference_sha256") == record["sha256"]
            and previous.get("text") == args.text and previous.get("ref_text") == record["audit"]["speech_text"]
            and previous.get("generation_steps") == args.steps and previous.get("requested_duration_sec") == args.duration
            and previous.get("output_sha256") == fingerprint(output)):
            print(f"[Clone bank] Reused {voice_id}", flush=True)
            timings.append(previous["elapsed_sec"])
            continue
        print(f"[Clone bank] Genuine audition {voice_id}. Source identity and background still need review.", flush=True)
        try:
            result = synthesize_reference(args.text, reference, record["audit"]["speech_text"], output,
                                          {"target_duration_sec":args.duration,"generation_steps":args.steps})
            record["clone"] = result
            timings.append(result["elapsed_sec"])
        except Exception as exc:
            record["clone_attempt"] = {"status":"failed", "error":str(exc)}
            write_report(path, record)
            raise
        write_report(path, record)
        if timings:
            write_report(folder / "clone-time-estimate.json", {"measured_voices":len(timings),
                "median_cold_worker_seconds":statistics.median(timings),
                "estimated_42_auditions_seconds":statistics.median(timings)*42,
                "excludes":"downloads, reference repairs, source and human listening review, expressive variants",
                "default_promotion":"not_performed"})
        print(f"[Clone bank] Completed {voice_id}: {result['elapsed_sec']}s, listening review required", flush=True)


if __name__ == "__main__":
    main()
