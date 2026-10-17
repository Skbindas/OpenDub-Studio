import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path
import soundfile as sf
import numpy as np

sys.stdout.reconfigure(encoding='utf-8')

# Ensure edge-tts is available
import edge_tts

async def synthesize(text: str, voice: str, pitch: str, rate: str, out_path: Path):
    communicate = edge_tts.Communicate(text, voice, pitch=pitch, rate=rate)
    await communicate.save(str(out_path))

def trim_silence(in_path: Path, out_path: Path, top_db=30):
    # Use ffmpeg silenceremove
    cmd = [
        'ffmpeg', '-y', '-i', str(in_path),
        '-af', 'silenceremove=start_periods=1:start_duration=0.01:start_threshold=-40dB:detection=rms,areverse,silenceremove=start_periods=1:start_duration=0.01:start_threshold=-40dB:detection=rms,areverse',
        '-ar', '48000', '-ac', '2', str(out_path)
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    data, sr = sf.read(str(out_path))
    return len(data) / sr

async def test_candidates():
    os.makedirs('temp_p23_tests', exist_ok=True)
    
    print("=== TESTING SEGMENT 08 (Priya: hi-IN-SwaraNeural, pitch=-4Hz, rate=-2%) Target: ~0.33s - 0.50s ===")
    priya_voice = "hi-IN-SwaraNeural"
    priya_pitch = "-4Hz"
    priya_rate = "+5%" # Slightly faster rate for urgent command
    
    seg08_candidates = [
        "जा!",
        "चल जा!",
        "जल्दी जा!",
        "जा, जल्दी!",
        "जा अब!",
    ]
    for c in seg08_candidates:
        raw_p = Path(f"temp_p23_tests/seg08_{len(c)}.mp3")
        trim_p = Path(f"temp_p23_tests/seg08_{len(c)}_trim.wav")
        await synthesize(c, priya_voice, priya_pitch, "+4%", raw_p)
        dur = trim_silence(raw_p, trim_p)
        print(f"  '{c}': Trimmed = {dur:.3f}s. Tempo for 0.40s: {dur/0.40:.3f}x. Tempo for 0.50s: {dur/0.50:.3f}x")

    print("\n=== TESTING SEGMENT 14 (Neha: hi-IN-SwaraNeural, pitch=+8Hz, rate=+4%) Target: ~2.47s ===")
    neha_voice = "hi-IN-SwaraNeural"
    neha_pitch = "+8Hz"
    neha_rate = "+6%"
    
    seg14_candidates = [
        "तुम्हारी आँखें खराब हैं, तुम्हारे पूरे परिवार की!",
        "तुम्हारी आँखें खराब हैं, पूरे परिवार की!",
        "तेरी आँखें खराब हैं, तेरे पूरे परिवार की!",
        "तुम्हारी आँखें खराब होंगी, पूरे परिवार की!",
        "तुम्हारी आँखें खराब हैं, पूरे खानदान की!",
        "तेरी आँखें खराब हैं, पूरे परिवार की!",
    ]
    for c in seg14_candidates:
        raw_p = Path(f"temp_p23_tests/seg14_{len(c)}.mp3")
        trim_p = Path(f"temp_p23_tests/seg14_{len(c)}_trim.wav")
        await synthesize(c, neha_voice, neha_pitch, neha_rate, raw_p)
        dur = trim_silence(raw_p, trim_p)
        print(f"  '{c}': Trimmed = {dur:.3f}s. Tempo for 2.47s: {dur/2.47:.3f}x")

    print("\n=== TESTING SEGMENT 26 (Rohan: hi-IN-MadhurNeural, pitch=+0Hz, rate=+0%) Target: ~1.19s ===")
    rohan_voice = "hi-IN-MadhurNeural"
    rohan_pitch = "+0Hz"
    rohan_rate = "+5%"
    
    seg26_candidates = [
        "दौड़ने पर तो पसीना आएगा ही!",
        "दौड़ने से तो पसीना आएगा ही!",
        "दौड़ने पर पसीना आता ही है!",
        "दौड़ने पर पसीना तो आएगा!",
        "दौड़ेंगे तो पसीना आएगा ही!",
        "दौड़ने से पसीना आएगा ही!",
    ]
    for c in seg26_candidates:
        raw_p = Path(f"temp_p23_tests/seg26_{len(c)}.mp3")
        trim_p = Path(f"temp_p23_tests/seg26_{len(c)}_trim.wav")
        await synthesize(c, rohan_voice, rohan_pitch, rohan_rate, raw_p)
        dur = trim_silence(raw_p, trim_p)
        print(f"  '{c}': Trimmed = {dur:.3f}s. Tempo for 1.19s: {dur/1.19:.3f}x. Tempo for 1.30s: {dur/1.30:.3f}x")

if __name__ == '__main__':
    asyncio.run(test_candidates())
