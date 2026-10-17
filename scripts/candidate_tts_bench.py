import asyncio
import edge_tts
import wave
import subprocess
import os
import tempfile
import sys

sys.stdout.reconfigure(encoding='utf-8')

async def test_tts(text, voice, pitch, rate):
    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
        mp3 = f.name
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        wav = f.name
    try:
        c = edge_tts.Communicate(text, voice, pitch=pitch, rate=rate)
        await c.save(mp3)
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', mp3, '-af', 'silenceremove=start_periods=1:start_duration=0.02:start_threshold=-50dB:detection=peak,areverse,silenceremove=start_periods=1:start_duration=0.02:start_threshold=-50dB:detection=peak,areverse', '-ar', '48000', '-ac', '2', wav], check=True)
        with wave.open(wav, 'rb') as w:
            dur = w.getnframes() / float(w.getframerate())
        return dur
    finally:
        if os.path.exists(mp3): os.unlink(mp3)
        if os.path.exists(wav): os.unlink(wav)

async def main():
    tests = [
        # Seg 02: Priya (-4Hz, -2%) target 0.70s, avail 0.97s
        ('Seg 02', 'कितना आसान है!', 'hi-IN-SwaraNeural', '-4Hz', '-2%'),
        ('Seg 02', 'ये तो बहुत आसान है!', 'hi-IN-SwaraNeural', '-4Hz', '-2%'),
        ('Seg 02', 'ये बहुत आसान है!', 'hi-IN-SwaraNeural', '-4Hz', '-2%'),
        
        # Seg 07: Priya (-4Hz, -2%) target 0.98s, avail 1.53s
        ('Seg 07', 'बस, भरोसा रख!', 'hi-IN-SwaraNeural', '-4Hz', '-2%'),
        
        # Seg 13: Rohan (+0Hz, +0%) target 1.08s, avail 1.41s
        ('Seg 13', 'डॉक्टर के पास चलें?', 'hi-IN-MadhurNeural', '+0Hz', '+0%'),
        ('Seg 13', 'मेडिकल रूम चलें?', 'hi-IN-MadhurNeural', '+0Hz', '+0%'),
        
        # Seg 16: Neha (+8Hz, +4%) target 1.25s, avail 2.16s
        ('Seg 16', 'तेरा तरीका फ्लॉप हो गया, सहेली!', 'hi-IN-SwaraNeural', '+8Hz', '+4%'),
        ('Seg 16', 'तेरा आइडिया बेकार निकला, सहेली!', 'hi-IN-SwaraNeural', '+8Hz', '+4%'),
        
        # Seg 21: Neha (+8Hz, +4%) target 0.84s, avail 1.51s
        ('Seg 21', 'सीधा पोंछ दूँ?', 'hi-IN-SwaraNeural', '+8Hz', '+4%'),
        ('Seg 21', 'मैं खुद पोंछ दूँ?', 'hi-IN-SwaraNeural', '+8Hz', '+4%'),
        
        # Seg 25: Neha (+8Hz, +4%) target 0.96s, avail 1.52s
        ('Seg 25', 'कितना पसीना आ गया!', 'hi-IN-SwaraNeural', '+8Hz', '+4%'),
        ('Seg 25', 'बहुत पसीना आ रहा है!', 'hi-IN-SwaraNeural', '+8Hz', '+4%'),
    ]
    for seg, text, voice, pitch, rate in tests:
        dur = await test_tts(text, voice, pitch, rate)
        print(f"[{seg}] '{text}' ({voice}) -> trimmed: {dur:.3f}s")

if __name__ == '__main__':
    asyncio.run(main())
