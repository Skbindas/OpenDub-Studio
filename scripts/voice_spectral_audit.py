import wave
import numpy as np
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

proj = 'runtime/projects/53ba81b5-cc7c-4a68-944e-ff553456a917'

with open(f'{proj}/analysis/dialogue_manifest_phase21.json', 'r', encoding='utf-8') as f:
    diag = json.load(f)

def analyze_audio(path):
    with wave.open(path, 'rb') as w:
        sr = w.getframerate()
        nframes = w.getnframes()
        frames = w.readframes(nframes)
        samples = np.frombuffer(frames, dtype=np.int16).astype(float)
        if w.getnchannels() == 2:
            samples = samples[0::2]
        
        # Spectral Centroid (brightness / timbre)
        # Use a 2048-point FFT on non-silent window
        magnitude = np.abs(np.fft.rfft(samples[:min(len(samples), sr*2)]))
        freqs = np.fft.rfftfreq(min(len(samples), sr*2), 1.0 / sr)
        centroid = np.sum(freqs * magnitude) / (np.sum(magnitude) + 1e-9)

        # Autocorrelation on downsampled (16kHz) 2048-sample slice
        step = max(1, sr // 16000)
        down = samples[::step]
        slice_len = 2048
        if len(down) > slice_len:
            mid = len(down) // 2
            sub = down[mid : mid + slice_len]
            sub = sub - np.mean(sub)
            r = np.fft.irfft(np.abs(np.fft.rfft(sub, n=4096))**2)
            # 16000 / freq -> for 80-400 Hz: lag is 40 to 200
            search = r[40:200]
            if len(search) > 0 and np.max(search) > 0:
                lag = 40 + np.argmax(search)
                f0 = 16000.0 / lag
            else:
                f0 = 0.0
        else:
            f0 = 0.0

        return f0, centroid

stats = {'SPEAKER_01': [], 'SPEAKER_02': [], 'SPEAKER_03': []}

for u in diag['units']:
    idx = u['segment_index']
    spk = u['speaker_id']
    trim_p = f'{proj}/segments/segment_{idx:06d}_phase21_trimmed.wav'
    f0, sc = analyze_audio(trim_p)
    stats[spk].append((f0, sc))

print("Character Voice Verification (Acoustic Measurements):")
for spk, name in [('SPEAKER_02', 'Neha (hi-IN-SwaraNeural, +8Hz, +4%)'),
                  ('SPEAKER_01', 'Priya (hi-IN-SwaraNeural, -4Hz, -2%)'),
                  ('SPEAKER_03', 'Rohan (hi-IN-MadhurNeural, +0Hz, 1.0x)')]:
    vals = stats[spk]
    f0s = [v[0] for v in vals if v[0] > 0]
    scs = [v[1] for v in vals]
    print(f"  {name}:")
    print(f"    Count: {len(vals)} segments")
    print(f"    Mean Estimated F0: {np.mean(f0s):.1f} Hz (range: {np.min(f0s):.1f} - {np.max(f0s):.1f} Hz)")
    print(f"    Mean Spectral Centroid: {np.mean(scs):.1f} Hz")
