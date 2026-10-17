"""Recover source timecodes for review without changing existing reference audio."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.voice_bank_quality import fingerprint, write_report, audio_metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--movie", required=True, type=Path)
    args = parser.parse_args()
    movie = args.movie.resolve()
    if not movie.is_file():
        raise FileNotFoundError("Movie not found")
    out = ROOT / "runtime/voice-bank-audit"
    catalog = json.loads((ROOT / "storage/default_voice_bank/candidate_voices/all_extracted_characters_summary.json").read_text(encoding="utf-8"))["characters"]
    for index, meta in enumerate(catalog):
        path = out / "records" / f"{meta['character_id']}.json"
        if not path.exists():
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        destination = out / "sources" / f"{meta['character_id']}.wav"
        destination.parent.mkdir(parents=True, exist_ok=True)
        start, end = float(meta["start_sec"]), float(meta["end_sec"])
        if not destination.exists():
            subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-n", "-ss", str(start), "-i", str(movie),
                            "-t", str(end-start), "-map", "0:a:0", "-ar", "24000", "-ac", "1",
                            "-c:a", "pcm_s16le", str(destination)], check=True)
        record["source"] = {"path":str(destination), "movie":str(movie), "movie_size":movie.stat().st_size,
                            "movie_mtime_ns":movie.stat().st_mtime_ns, "start_sec":start, "end_sec":end,
                            "sha256":fingerprint(destination), "metrics":audio_metrics(destination)}
        record["source_status"] = "excerpt_available_identity_and_background_review_required"
        write_report(path, record)
        print(f"[Voice source] {index+1}/{len(catalog)} {meta['character_id']}", flush=True)


if __name__ == "__main__":
    main()
