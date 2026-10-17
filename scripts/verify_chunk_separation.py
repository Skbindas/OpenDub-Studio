"""Real separator trial on a short source excerpt; does not modify a project."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.chunked_separation import separate_chunked
from backend.chunk_execution import digest, save_json
from backend.resource_plan import plan_resources
from backend.system_diagnostics import collect_diagnostics
from backend.work_progress import track
import soundfile as sf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "runtime/qa-video/chunk-separation")
    parser.add_argument("--seconds", type=float, default=24)
    parser.add_argument("--chunk-seconds", type=float, default=12)
    parser.add_argument("--visible-helpers", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source = args.output / "source.wav"
    if not source.exists():
        subprocess.run([shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-y", "-i", str(args.source), "-t", str(args.seconds),
                        "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", str(source)], check=True)
    duration = sf.info(source).duration
    plan = plan_resources(collect_diagnostics(args.output), duration, source.stat().st_size)
    plan["chunk_seconds"] = args.chunk_seconds
    with track(args.output, "separator-trial", "vocal_separation", "chunks"):
        result = separate_chunked(source, args.output / "separation", duration, plan, visible_helpers=args.visible_helpers)
    chunks = args.output / "separation/chunks"
    before = {str(path): (digest(path), path.stat().st_mtime_ns) for path in chunks.glob("*/*candidate.wav")}
    started = time.monotonic()
    repeated = separate_chunked(source, args.output / "separation", duration, plan, visible_helpers=args.visible_helpers)
    unchanged = all((digest(Path(path)), Path(path).stat().st_mtime_ns) == signature for path, signature in before.items())
    stems = {key: {"frames":sf.info(result[key]).frames, "channels":sf.info(result[key]).channels,
                   "sample_rate":sf.info(result[key]).samplerate} for key in ("dialogue_candidate", "background_candidate")}
    report = {"duration":duration, "chunk_count":result["chunk_count"], "stems":stems,
              "completed_chunks_unchanged":unchanged, "resume_seconds":round(time.monotonic()-started,3),
              "source_sha256":digest(source), "scope":"Real UVR chunk execution/frame integrity; listening review still required"}
    save_json(args.output / "verification.json", report)
    print(json.dumps(report,indent=2),flush=True)
    if not unchanged or any(meta["frames"] != round(duration*48000) for meta in stems.values()):
        raise RuntimeError("Chunk separation integrity failed")


if __name__ == "__main__":
    main()
