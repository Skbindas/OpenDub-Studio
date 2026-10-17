"""Render a single already-fitted Hindi line from the valid source portion.

This isolates mux/QA from the corrupt tail and unreviewed remaining dialogue.
It never modifies the original source or the fresh project's checkpoints.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.chunked_mix import mix_chunked
from backend.rendering import mux_movie, verify_render_qa
from backend.chunk_execution import save_json

project = ROOT / "runtime/qa-video/hindi-excerpt"
project.mkdir(parents=True, exist_ok=True)
original = Path(r"C:\Users\su936\Downloads\41597079496-1-192.mp4")
source = project / "source.mp4"
subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-y", "-ss", "1.31", "-i", str(original),
                "-t", "1.62", "-c:v", "libx264", "-threads", "2", "-c:a", "aac", str(source)], check=True)
stem = ROOT / "runtime/qa-video/chunk-separation/separation/instrumental.wav"
with sf.SoundFile(stem) as sound:
    sound.seek(round(1.31*48000))
    background = sound.read(round(1.62*48000), dtype="float32", always_2d=True)
bg = project / "background.wav"
sf.write(bg, background, 48000, subtype="FLOAT")
fresh = ROOT / "runtime/projects/81edba32-84c0-4668-a7b3-5612678d3e28"
voice = fresh / "segments/segment_000000_normalized.wav"
mix = project / "hindi.wav"
mix_chunked(project, bg, mix, [(0, voice)], 1.62, seconds=1, workers=1)
output = project / "hindi-preview.mp4"
mux_movie(source, mix, output)
report = verify_render_qa(source, output)
report["scope"] = "One real fitted Hindi line, 1.31–2.93s of the source. Whole source remains corrupt; other 40 dialogue windows need review. Voice/perceptual fidelity not certified."
save_json(project / "verification.json", report)
print(json.dumps(report, indent=2))
if report["status"] != "PASSED":
    raise RuntimeError("Excerpt render QA failed")
