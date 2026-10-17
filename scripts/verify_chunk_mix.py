"""Real isolated mix helpers, exact sample reference, and checkpoint resume."""
import json
from pathlib import Path
import sys
import time
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.chunked_mix import mix_chunked
from backend.chunk_execution import digest, save_json

project = ROOT / "runtime/qa-video/chunk-mix"
project.mkdir(parents=True, exist_ok=True)
source = ROOT / "runtime/qa-video/chunk-separation/separation/instrumental.wav"
background, rate = sf.read(source, dtype="float32", always_2d=True)
voice = project / "voice.wav"
samples = np.full((rate*5, 2), .02, dtype="float32")
sf.write(voice, samples, rate, subtype="FLOAT")
out = project / "mix.wav"
started = time.monotonic()
mix_chunked(project, source, out, [(6.5, voice)], len(background)/rate, seconds=8, workers=1)
checkpoints = list((project / "chunks/mix").glob("*/mix.wav"))
before = {str(path): (digest(path), path.stat().st_mtime_ns) for path in checkpoints}
mixed, _ = sf.read(out, dtype="int16", always_2d=True)
reference = background.copy()
reference[round(6.5*rate):round(6.5*rate)+len(samples)] += samples
expected = project / "reference.wav"
sf.write(expected, reference, rate, subtype="PCM_16")
expected_samples, _ = sf.read(expected, dtype="int16", always_2d=True)
elapsed = time.monotonic()-started
started = time.monotonic()
mix_chunked(project, source, out, [(6.5, voice)], len(background)/rate, seconds=8, workers=1)
report = {"duration_seconds":len(background)/rate,"chunk_count":len(checkpoints),
          "exact_reference_samples":bool(np.array_equal(mixed,expected_samples)),
          "checkpoints_unchanged":all((digest(Path(path)),Path(path).stat().st_mtime_ns)==value for path,value in before.items()),
          "elapsed_seconds":round(elapsed,3), "resume_seconds":round(time.monotonic()-started,3),
          "scope":"Real separated background with synthetic dialogue crossing a chunk boundary; no perceptual voice quality claim."}
save_json(project / "verification.json",report)
print(json.dumps(report,indent=2))
if not report["exact_reference_samples"] or not report["checkpoints_unchanged"] or report["chunk_count"] != 3:
    raise RuntimeError("Isolated mix verification failed")
