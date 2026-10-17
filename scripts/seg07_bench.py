import asyncio
import edge_tts
import wave
import subprocess
import os
import tempfile
import sys

sys.stdout.reconfigure(encoding='utf-8')

async def test_synth(text, voice='hi-IN-SwaraNeural', pitch='-4Hz', rate='-2%'):
    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
        mp3 = f.name
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        wav = f.name
    try:
        c = edge_tts.Communicate(text, voice, pitch=pitch, rate=rate)
        await c.save(mp3)
        # convert and silence trim
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', mp3, '-af', 'silenceremove=start_periods=1:start_duration=0.02:start_threshold=-50dB:detection=peak,areverse,silenceremove=start_periods=1:start_duration=0.02:start_threshold=-50dB:detection=peak,areverse', '-ar', '48000', '-ac', '2', wav], check=True)
        with wave.open(wav, 'rb') as w:
            dur = w.getnframes() / float(w.getframerate())
        return dur
    finally:
        if os.path.exists(mp3): os.unlink(mp3)
        if os.path.exists(wav): os.unlink(wav)

async def main():
    options = [
        'बस ऐसे, भरोसा रख!',
        'बस, भरोसा रख!',
        'बस, मुझ पर भरोसा रख!',
        'बस यूँ ही, भरोसा रख!',
        'बस यही, भरोसा रख!',
        'मुझ पर भरोसा रख, पक्का काम बन जाएगा!' # Phase 21 baseline
    ]
    for opt in options:
        d = await test_synth(opt)
        spd = d / 0.980
        print(f"{opt:38s} -> trimmed: {d:.3f}s | required speed for 0.98s: {spd:.3f}x")

if __name__ == '__main__':
    asyncio.run(main())
