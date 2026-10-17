"""Report source packet integrity without changing the source or project."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.media import verify_media_decode

parser = argparse.ArgumentParser()
parser.add_argument("source", type=Path)
args = parser.parse_args()
try:
    report = verify_media_decode(args.source)
except RuntimeError as exc:
    report = {"status": "failed", "detail": str(exc)}
output = ROOT / "runtime/qa-video/source-decode-integrity.json"
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
sys.exit(0 if report["status"] == "passed" else 1)
