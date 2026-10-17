"""Script to ingest and clone character voices from a reference Hindi dubbed movie into the Default Voice Bank.

Usage:
    python scripts/ingest_hindi_movie_voices.py --movie "C:\\path\\to\\Hindi_Movie.mkv"
    python scripts/ingest_hindi_movie_voices.py --movie "C:\\path\\to\\Hindi_Movie.mkv" --role "hero_male" --name "Tony Stark" --start 120.5 --duration 8.0
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import wave

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.voice_cloning import VoiceCloneRegistry, analyze_vocal_timbre


def extract_audio_segment(
    media_path: Path,
    output_wav: Path,
    start_sec: float | None = None,
    duration_sec: float = 8.0,
    sample_rate: int = 24000,
) -> bool:
    """Extract a clean mono 24kHz WAV snippet from media using ffmpeg."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        win_ffmpeg = Path(r"C:\Users\su936\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin\ffmpeg.exe")
        if win_ffmpeg.is_file():
            ffmpeg = str(win_ffmpeg)
        elif Path("/mnt/c/Users/su936/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-9.0.2-full_build/bin/ffmpeg.exe").is_file():
            ffmpeg = "/mnt/c/Users/su936/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-9.0.2-full_build/bin/ffmpeg.exe"

    if not ffmpeg:
        raise RuntimeError("FFmpeg executable not found. Please ensure FFmpeg is installed.")

    output_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    if start_sec is not None and start_sec > 0:
        cmd += ["-ss", f"{start_sec:.2f}"]
    cmd += ["-i", str(media_path)]
    if duration_sec > 0:
        cmd += ["-t", f"{duration_sec:.2f}"]
    cmd += ["-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le", str(output_wav)]

    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.returncode == 0 and output_wav.is_file() and output_wav.stat().st_size > 1000


def main():
    parser = argparse.ArgumentParser(description="Ingest reference Hindi movie voices into OpenDub Studio Default Voice Bank.")
    parser.add_argument("--movie", "-m", required=True, help="Path to reference Hindi movie / audio file")
    parser.add_argument("--role", "-r", default="", help="Character role tag (e.g. hero_male, lead_female, villain, old_chief)")
    parser.add_argument("--name", "-n", default="", help="Character display name (e.g. Iron Man, Black Widow)")
    parser.add_argument("--start", "-s", type=float, default=None, help="Start timecode in seconds for snippet extraction")
    parser.add_argument("--duration", "-d", type=float, default=8.0, help="Snippet duration in seconds (default: 8.0s)")
    parser.add_argument("--text", "-t", default="", help="Spoken Hindi transcript of the snippet (ref_text)")
    parser.add_argument("--prompt", "-p", default="", help="Natural language instruct style prompt")
    parser.add_argument("--list", action="store_true", help="List all currently registered default voices")

    args = parser.parse_args()
    registry = VoiceCloneRegistry()

    if args.list:
        voices = registry.list_default_voices()
        print(f"\n=== OpenDub Studio Default Voice Bank ({len(voices)} voices registered) ===")
        for v in voices:
            role = v.get("character_role") or v.get("voice_id")
            name = v.get("character_name", role)
            gender = v.get("gender", "unknown")
            age = v.get("age_group", "unknown")
            base = v.get("settings", {}).get("base_voice_id", "none")
            audio = v.get("ref_audio_path", "")
            print(f"  • [{role}] {name} ({gender}, {age}) -> Base: {base} | File: {Path(audio).name}")
        return

    media_path = Path(args.movie).resolve()
    if not media_path.is_file():
        # Try checking Windows path if running in WSL
        wsl_path = Path(f"/mnt/{args.movie[0].lower()}/{args.movie[3:].replace(chr(92), '/')}")
        if wsl_path.is_file():
            media_path = wsl_path
        else:
            print(f"[ERROR] Movie file not found: {args.movie}")
            sys.exit(1)

    print(f"\n[OpenDub Studio] Ingesting voices from Hindi Reference Movie: {media_path.name}")
    bank_dir = registry.get_default_bank_dir()
    temp_wav = bank_dir / f"_temp_extract_{os.getpid()}.wav"

    role = args.role.strip() or f"character_{media_path.stem[:12]}"
    name = args.name.strip() or role.replace("_", " ").title()

    try:
        print(f"  -> Extracting {args.duration}s clean speech snippet...")
        success = extract_audio_segment(media_path, temp_wav, start_sec=args.start, duration_sec=args.duration)
        if not success:
            print(f"[ERROR] Failed to extract audio snippet from {media_path}")
            sys.exit(1)

        print("  -> Analyzing acoustic vocal timbre, F0 pitch, gender, and resonance...")
        timbre = analyze_vocal_timbre(temp_wav, character_id=role)
        print(f"     F0: {timbre.pitch_f0_hz} Hz | Gender: {timbre.gender} | Age: {timbre.age_group} | Semitones: {timbre.pitch_semitones:+.1f}st")
        print(f"     Matched Theatrical Profile: {timbre.matched_base_profile}")

        print(f"  -> Saving to Default Voice Bank as '{role}'...")
        saved = registry.save_default_voice(
            character_role=role,
            audio_path=temp_wav,
            ref_text=args.text,
            character_name=name,
            style_prompt=args.prompt,
            timbre_data=timbre.to_dict(),
        )

        print("\n[SUCCESS] Character voice successfully cloned into Default Voice Bank!")
        print(f"  Voice ID: {saved['voice_id']}")
        print(f"  Role: {saved['character_role']}")
        print(f"  Display Name: {saved['character_name']}")
        print(f"  Audio Snippet: {saved['ref_audio_path']}")
        print(f"  Base Neural Model: {saved['settings']['base_voice_id']}")
        print("  Status: Available permanently as default voice for all future dubs.")
    finally:
        temp_wav.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
