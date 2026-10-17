"""Small real-media trial, isolated from the user's project/checkpoints."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.chunked_asr import transcribe_chunked
from backend.chunk_execution import digest, save_json
from backend.resource_plan import plan_resources
from backend.system_diagnostics import collect_diagnostics
from backend.work_progress import track


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "runtime/qa-video/chunk-asr")
    parser.add_argument("--seconds", type=float, default=24)
    parser.add_argument("--chunk-seconds", type=float, default=12)
    parser.add_argument("--model", default="small")
    parser.add_argument("--language", default="zh")
    parser.add_argument("--visible-helpers", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    trial = args.output / "trial.wav"
    if not trial.exists():
        subprocess.run([shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-y", "-i", str(args.source),
                        "-t", str(args.seconds), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(trial)], check=True)
    import wave
    with wave.open(str(trial)) as audio:
        duration = audio.getnframes() / audio.getframerate()
    plan = plan_resources(collect_diagnostics(args.output), duration, trial.stat().st_size)
    plan["chunk_seconds"] = args.chunk_seconds
    if not plan["admitted"]:
        raise RuntimeError(" ".join(plan["reasons"]))
    print(f"[OpenDub trial] {plan['heavy_workers']} helpers maximum; ASR {plan['asr_device']}; {duration}s source", flush=True)
    kwargs = dict(model_size=args.model, language=args.language, visible_helpers=args.visible_helpers)
    with track(args.output, "isolated-asr-trial", "transcription", "chunks"):
        transcript = transcribe_chunked(trial, args.output / "chunks", duration, plan, **kwargs)
    save_json(args.output / "merged.json", transcript)
    before = {str(path): (digest(path), path.stat().st_mtime_ns) for path in (args.output / "chunks").glob("*/transcript.json")}
    started = time.monotonic()
    repeated = transcribe_chunked(trial, args.output / "chunks", duration, plan, **kwargs)
    unchanged = all((digest(Path(path)), Path(path).stat().st_mtime_ns) == signature for path, signature in before.items())
    report = {"duration": duration, "chunk_count": transcript["chunk_count"], "segments": len(transcript["segments"]),
              "plan": plan, "resume_seconds": round(time.monotonic()-started, 3), "all_chunk_files_unchanged": unchanged,
              "merged_result_identical": repeated == transcript,
              "boundary_review_required": sum(bool(row.get("boundary_review_required")) for row in transcript["segments"]),
              "scope": "ASR helper isolation/checkpoint trial only; not final dubbing or feature-length certification"}
    save_json(args.output / "verification.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    if not unchanged or repeated != transcript:
        raise RuntimeError("ASR retry changed completed work")


if __name__ == "__main__":
    main()
