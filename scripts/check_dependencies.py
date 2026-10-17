"""Deterministic environment and dependency validator for OpenDub Studio."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def check_tool(name: str) -> str | None:
    return shutil.which(name)


def check_ffmpeg_rubberband(ffmpeg_path: str) -> bool:
    try:
        p = subprocess.run([ffmpeg_path, "-filters"], capture_output=True, text=True, timeout=5, errors="replace")
        return "rubberband" in (p.stdout or "")
    except Exception:
        return False


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 60)
    print("OpenDub Studio — Dependency & Environment Diagnostics")
    print("=" * 60)

    # 1. Python version
    print(f"Python: {sys.version.split()[0]} ({sys.executable})")

    # 2. FFmpeg & FFprobe
    ffmpeg = check_tool("ffmpeg")
    ffprobe = check_tool("ffprobe")

    if not ffmpeg:
        print("[ERROR] ffmpeg is NOT found on PATH!")
        return 1
    print(f"[OK] ffmpeg found: {ffmpeg}")

    if not ffprobe:
        print("[ERROR] ffprobe is NOT found on PATH!")
        return 1
    print(f"[OK] ffprobe found: {ffprobe}")

    # Check ffmpeg version line
    res = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, timeout=5)
    v_line = res.stdout.splitlines()[0] if res.stdout else "unknown"
    print(f"     Version: {v_line}")

    # 3. Rubber Band filter check
    has_rb = check_ffmpeg_rubberband(ffmpeg)
    if has_rb:
        print("[OK] FFmpeg librubberband filter is available.")
    else:
        print("[WARNING] FFmpeg librubberband filter not detected. Safe atempo fallback will be used.")

    # 4. Core Python modules (from requirements.txt)
    core_modules = ["fastapi", "uvicorn", "pydantic", "httpx", "dotenv", "numpy", "soundfile", "scipy"]
    missing = []
    for mod in core_modules:
        try:
            __import__(mod)
            print(f"[OK] Python module '{mod}' is installed.")
        except ImportError:
            print(f"[ERROR] Python module '{mod}' is MISSING.")
            missing.append(mod)

    # 5. Optional Python modules (for local development / specialized synthesis)
    optional_modules = ["edge_tts"]
    for mod in optional_modules:
        try:
            __import__(mod)
            print(f"[OK] Optional Python module '{mod}' is available.")
        except ImportError:
            print(f"[INFO] Optional Python module '{mod}' is not installed (optional).")

    if missing:
        print(f"\nMissing core Python modules: {', '.join(missing)}")
        print("Run: pip install -r requirements.txt")
        return 1

    print("\n[ALL CORE DEPENDENCIES SATISFIED]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
