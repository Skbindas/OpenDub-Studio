from __future__ import annotations

import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
PYTHON = VENV / "Scripts" / "python.exe"

def run(cmd: list[str], retries: int = 3) -> None:
    last_error = None
    for attempt in range(1, retries + 1):
        print(f"> {' '.join(cmd)} (attempt {attempt}/{retries})")
        try:
            subprocess.check_call(cmd, cwd=ROOT)
            return
        except subprocess.CalledProcessError as exc:
            last_error = exc
            if attempt < retries:
                import time
                delay = min(2 ** attempt, 8)
                print(f"Command failed; retrying in {delay}s…")
                time.sleep(delay)
    raise last_error or RuntimeError("Command failed")

def setup_separation_runtime() -> None:
    """Reuse compatible installed GPU Torch and separation packages in isolation."""
    import json
    target = ROOT / "runtime/separation-env"
    clone = ROOT / "runtime/clone-env/Scripts/python.exe"
    if not clone.is_file() or not PYTHON.is_file():
        raise SystemExit("Main and clone runtimes must already be installed; existing environments were retained.")
    probe = "import json,sys,site; print(json.dumps({'version':list(sys.version_info[:2]),'site':site.getsitepackages()}))"
    main_info = json.loads(subprocess.check_output([str(PYTHON),"-c",probe],text=True))
    clone_info = json.loads(subprocess.check_output([str(clone),"-c",probe],text=True))
    if main_info["version"] != clone_info["version"]:
        raise SystemExit("GPU/main Python versions differ; use a dedicated compatible separation environment instead of sharing binary packages.")
    if not target.exists():
        subprocess.check_call([str(PYTHON),"-m","venv",str(target)])
    python = target / "Scripts/python.exe"
    target_info = json.loads(subprocess.check_output([str(python),"-c",probe],text=True))
    if target_info["version"] != main_info["version"]:
        raise SystemExit("Existing separation runtime has a different Python version; retained unchanged.")
    sites = [str(Path(path)) for path in clone_info["site"] + main_info["site"] if Path(path).is_dir() and Path(path).name == "site-packages"]
    location = next(Path(path) for path in target_info["site"] if Path(path).name == "site-packages")
    (location / "opendub_shared_runtime.pth").write_text("\n".join(dict.fromkeys(sites))+"\n",encoding="utf-8")
    subprocess.check_call([str(python),"-c","import torch; from audio_separator.separator import Separator; x=torch.zeros(1,device='cuda'); print('GPU separation runtime ready:',torch.__version__)"])


def main() -> None:
    print("OpenDub Studio — local installer")
    print("-" * 44)

    if sys.version_info < (3, 10):
        raise SystemExit("Python 3.10+ is required.")

    if not VENV.exists():
        print("Creating local Python environment…")
        venv.EnvBuilder(with_pip=True).create(VENV)
    else:
        print("Python environment already exists — skipping.")

    run([str(PYTHON), "-m", "pip", "install", "--upgrade", "pip"])
    run([str(PYTHON), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg and ffprobe:
        print("FFmpeg: found on PATH — skipping install.")
    else:
        print("FFmpeg: NOT FOUND on PATH.")
        print("Install FFmpeg separately or use Windows Package Manager (winget) if available.")
        if shutil.which("winget"):
            choice = input("Try winget install Gyan.FFmpeg now? [Y/n]: ").strip().lower()
            if choice in ("", "y", "yes"):
                run(["winget", "install", "-e", "--id", "Gyan.FFmpeg", "--accept-source-agreements", "--accept-package-agreements"])
        else:
            print("winget not found; continuing. Media analysis/rendering needs FFmpeg.")

    print("\nInstallation complete.")
    print("Run start.bat to launch the local studio.")

if __name__ == "__main__":
    if "--separation-runtime" in sys.argv:
        setup_separation_runtime()
    else:
        main()
