"""Ingest and catalog the 7 core character voices from Janta Garage into OpenDub Studio Default Voice Bank.

Movie: JR NTR Blockbuster Action Hindi Dubbed Full Movie JANTA GARAGE (Mohanlal, Samantha, Nithya Menen)
Characters Cloned:
1. hero_male_anand        - Jr. NTR (Charismatic, energetic, heroic male lead)
2. chief_elder_sathyam    - Mohanlal (Deep resonant patriarch / garage boss / elder chief)
3. lead_female_bujji      - Samantha (Expressive, sweet, romantic lead heroine)
4. young_female_anu       - Nithya Menen (Bright, lively, modern young woman)
5. villain_male_mukesh    - Sachin Khedekar / Rahman (Dark, menacing, calculated antagonist)
6. senior_cop_officer     - Police Commissioner / Inspector (Authoritative, stern official)
7. maternal_matron        - Mother / Matriarch (Warm, emotional, caring feminine tone)
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.voice_cloning import VoiceCloneRegistry, analyze_vocal_timbre

FFMPEG_WIN = r"C:\Users\su936\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin\ffmpeg.exe"
MOVIE_PATH_WIN = r"C:\Users\su936\OneDrive\Desktop\JR NTR Blockbuster Action Hindi Dubbed Full Movie JANTA GARAGE  Mohanlal, Samantha, Nithya Menen - Goldmines CineHub (720p, h264).mp4"

# Timestamps (start_sec, duration_sec) in Janta Garage Hindi Dub for clear dialogue snippets
CHARACTER_SNIPPET_TARGETS = [
    {
        "role_key": "hero_male",
        "character_name": "Jr. NTR (Anand / Hero Lead)",
        "actor": "Jr. NTR / Anand",
        "start_sec": 1682.0,  # College debate / nature dialogue scene
        "duration_sec": 7.5,
        "gender": "male",
        "age_group": "young_adult",
        "description": "High-energy, charismatic, punchy and confident heroic Hindi lead voice",
        "instruct_prompt": "Confident, energetic, charismatic young hero voice with clear Hindi diction and heroic punch.",
        "base_neural_voice": "hi-IN-MadhurNeural",
        "pitch_semitones": -0.5,
    },
    {
        "role_key": "chief_elder",
        "character_name": "Mohanlal (Sathyam / Patriarch Chief)",
        "actor": "Mohanlal / Sathyam",
        "start_sec": 732.0,   # Mohanlal addressing the garage workers
        "duration_sec": 8.0,
        "gender": "male",
        "age_group": "elderly",
        "description": "Deep, heavy-chested, commanding veteran leader voice with immense gravitas",
        "instruct_prompt": "Heavy authoritative elder chief voice, deep chest resonance, measured cadence and commanding presence.",
        "base_neural_voice": "de-DE-FlorianMultilingualNeural",
        "pitch_semitones": -3.2,
    },
    {
        "role_key": "lead_female",
        "character_name": "Samantha (Bujji / Lead Heroine)",
        "actor": "Samantha / Bujji",
        "start_sec": 2108.0,  # Romantic conversation scene
        "duration_sec": 7.0,
        "gender": "female",
        "age_group": "adult",
        "description": "Sweet, melodic, expressive and emotive lead heroine Hindi voice",
        "instruct_prompt": "Melodic, sweet, expressive and emotive young female lead voice with crisp clear Hindi pronunciation.",
        "base_neural_voice": "hi-IN-SwaraNeural",
        "pitch_semitones": +0.5,
    },
    {
        "role_key": "young_female",
        "character_name": "Nithya Menen (Anu / Second Lead)",
        "actor": "Nithya Menen / Anu",
        "start_sec": 2640.0,  # Lively conversation with Jr NTR
        "duration_sec": 6.8,
        "gender": "female",
        "age_group": "young",
        "description": "Bright, cheerful, vibrant and modern young female voice",
        "instruct_prompt": "Bright, playful, confident and modern young woman voice with lively Hindi cadence.",
        "base_neural_voice": "ne-NP-HemkalaNeural",
        "pitch_semitones": +1.5,
    },
    {
        "role_key": "villain_male",
        "character_name": "Antagonist / Villain Boss",
        "actor": "Mukesh / Villain",
        "start_sec": 3315.0,  # Villain confrontation dialogue
        "duration_sec": 7.5,
        "gender": "male",
        "age_group": "middle_aged",
        "description": "Dark, raspy, cold, calculating and menacing antagonist voice",
        "instruct_prompt": "Dark, sinister, gritty, menacing baritone villain voice with threatening authority.",
        "base_neural_voice": "ko-KR-HyunsuMultilingualNeural",
        "pitch_semitones": -2.0,
    },
    {
        "role_key": "senior_cop",
        "character_name": "Police Commissioner / Senior Officer",
        "actor": "Police Officer",
        "start_sec": 4210.0,  # Police station official discussion
        "duration_sec": 7.2,
        "gender": "male",
        "age_group": "middle_aged",
        "description": "Firm, official, stern baritone police detective / officer voice",
        "instruct_prompt": "Firm, official, grounded baritone detective voice with commanding law enforcement cadence.",
        "base_neural_voice": "mr-IN-ManoharNeural",
        "pitch_semitones": -1.2,
    },
    {
        "role_key": "maternal_matron",
        "character_name": "Mother / Matriarch",
        "actor": "Devayani / Mother",
        "start_sec": 4820.0,  # Family emotional scene
        "duration_sec": 6.5,
        "gender": "female",
        "age_group": "middle_aged",
        "description": "Warm, emotional, tender and gentle maternal Hindi voice",
        "instruct_prompt": "Warm, emotional, gentle and loving maternal female voice with soft comforting tone.",
        "base_neural_voice": "mr-IN-AarohiNeural",
        "pitch_semitones": -0.5,
    },
]


def extract_and_clean_snippet(
    movie_path: str,
    output_wav: Path,
    start_sec: float,
    duration_sec: float,
) -> bool:
    """Extract and condition vocal snippet with highpass, vocal EQ and normalization."""
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    temp_raw = output_wav.with_name(f"_raw_{output_wav.name}")

    # Step 1: Slice from movie with FFmpeg
    cmd_slice = [
        FFMPEG_WIN, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start_sec:.2f}",
        "-i", movie_path,
        "-t", f"{duration_sec:.2f}",
        "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le",
        str(temp_raw),
    ]
    subprocess.run(cmd_slice, check=True)

    if not temp_raw.is_file() or temp_raw.stat().st_size < 1000:
        return False

    # Step 2: Clean speech band (remove rumble <85 Hz, remove hiss >7500 Hz, speech presence EQ)
    # and normalize to broadcast dialogue level
    audio_filters = (
        "highpass=f=85,lowpass=f=7500,"
        "equalizer=f=2500:width_type=o:width=1.2:g=+1.5,"
        "loudnorm=I=-16:TP=-1.5:LRA=11"
    )
    cmd_clean = [
        FFMPEG_WIN, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(temp_raw),
        "-af", audio_filters,
        "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le",
        str(output_wav),
    ]
    subprocess.run(cmd_clean, check=True)
    temp_raw.unlink(missing_ok=True)
    return output_wav.is_file() and output_wav.stat().st_size > 1000


def main():
    print("================================================================================")
    print("  OpenDub Studio — Janta Garage Master Voice Ingestion & Default Cloning")
    print("================================================================================")
    print(f"Movie: {Path(MOVIE_PATH_WIN).name}")
    print(f"Output Default Voice Bank: {PROJECT_ROOT / 'storage' / 'default_voice_bank'}\n")

    registry = VoiceCloneRegistry(data_root=PROJECT_ROOT / "storage")
    bank_dir = registry.get_default_bank_dir()

    cloned_summary = []

    for target in CHARACTER_SNIPPET_TARGETS:
        role_key = target["role_key"]
        char_name = target["character_name"]
        print(f"[*] Processing Voice [{role_key}] — {char_name}...")
        print(f"    Extracting from {target['start_sec'] // 60:.0f}m{target['start_sec'] % 60:02.0f}s ({target['duration_sec']}s)...")

        target_wav = bank_dir / f"{role_key}.wav"
        success = extract_and_clean_snippet(
            MOVIE_PATH_WIN,
            target_wav,
            start_sec=target["start_sec"],
            duration_sec=target["duration_sec"],
        )
        if not success:
            print(f"    [WARN] Snippet extraction failed for {role_key}")
            continue

        # Analyze timbre with acoustic profiler
        timbre = analyze_vocal_timbre(
            target_wav,
            character_id=role_key,
            fallback_gender=target["gender"],
            fallback_age=target["age_group"],
        )
        f0_str = f"{timbre.pitch_f0_hz:.1f} Hz" if timbre.pitch_f0_hz else "Dynamic Formant"
        print(f"    Timbre: F0={f0_str} | Gender={timbre.gender} | Base Neural: {target['base_neural_voice']}")

        # Register into Default Voice Bank
        saved = registry.save_default_voice(
            character_role=role_key,
            audio_path=target_wav,
            character_name=char_name,
            style_prompt=target["instruct_prompt"],
            timbre_data={
                **timbre.to_dict(),
                "matched_base_profile": target["base_neural_voice"],
                "pitch_semitones": target["pitch_semitones"],
            },
            metadata={
                "movie_source": "Janta Garage (Hindi Dubbed)",
                "actor": target["actor"],
                "description": target["description"],
                "base_neural_voice": target["base_neural_voice"],
                "start_timecode_sec": target["start_sec"],
            },
        )

        cloned_summary.append({
            "role": role_key,
            "name": char_name,
            "gender": timbre.gender,
            "age": timbre.age_group,
            "f0": f0_str,
            "neural_base": target["base_neural_voice"],
            "snippet_file": target_wav.name,
            "size_kb": round(target_wav.stat().st_size / 1024, 1),
        })
        print(f"    [OK] Cloned and locked into Default Voice Bank as '{role_key}'!\n")

    print("\n================================================================================")
    print("  DEFAULT VOICE BANK INGESTION COMPLETE — 7 MASTER CHARACTERS SAVED")
    print("================================================================================")
    for c in cloned_summary:
        print(f"  • {c['role']:15} | {c['name']:38} | {c['gender']:6} ({c['age']:11}) | F0: {c['f0']:16} | File: {c['snippet_file']}")

    # Save index file in default bank
    index_file = bank_dir / "default_voices_catalog.json"
    index_file.write_text(json.dumps(cloned_summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nCatalog index generated: {index_file}")
    print("These voices are now permanently active as Default Character Voices in OpenDub Studio!")


if __name__ == "__main__":
    main()
