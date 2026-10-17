import json
import subprocess
from pathlib import Path
import soundfile as sf
import numpy as np

p23_mp4 = Path('runtime/projects/53ba81b5-cc7c-4a68-944e-ff553456a917/output/dubbed_hindi_41374123128_phase23_corrected.mp4')
orig_mp4 = Path('runtime/projects/53ba81b5-cc7c-4a68-944e-ff553456a917/source/original.mp4')
mix_p23 = Path('runtime/projects/53ba81b5-cc7c-4a68-944e-ff553456a917/output/mix_phase23.wav')

def probe(p):
    cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', str(p)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(res.stdout)

info_p23 = probe(p23_mp4)
info_orig = probe(orig_mp4)

v_stream = next(s for s in info_p23['streams'] if s['codec_type'] == 'video')
a_stream = next(s for s in info_p23['streams'] if s['codec_type'] == 'audio')

orig_v = next(s for s in info_orig['streams'] if s['codec_type'] == 'video')

print("=" * 60)
print("PHASE 23 PRODUCTION MASTER MEDIA QA")
print("=" * 60)
print(f"File: {p23_mp4.name} ({p23_mp4.stat().st_size} bytes)")
print(f"Video Stream Duration: {v_stream['duration']}s (Original: {orig_v['duration']}s)")
print(f"Video Frame Count:     {v_stream['nb_frames']} (Original: {orig_v['nb_frames']})")
print(f"Video FPS:             {v_stream['r_frame_rate']}")
print(f"Video Resolution:      {v_stream['width']}x{v_stream['height']}")
print(f"Audio Stream Duration: {a_stream['duration']}s")
print(f"Audio Sample Rate:     {a_stream['sample_rate']} Hz")
print(f"Audio Channels:        {a_stream['channels']}")
print(f"Container Duration:    {info_p23['format']['duration']}s")
print(f"A/V Offset:            {(float(info_p23['format']['duration']) - float(v_stream['duration']))*1000:.1f} ms")

# Decode tests
print("\nRunning full stream decode test...")
res_dec = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(p23_mp4), '-f', 'null', '-'], capture_output=True, text=True)
print("  Full stream decode errors:", res_dec.stderr.strip() if res_dec.stderr.strip() else "0 errors (CLEAN)")

print("Running final 10s decode test...")
res_10 = subprocess.run(['ffmpeg', '-v', 'error', '-ss', '74.4', '-i', str(p23_mp4), '-f', 'null', '-'], capture_output=True, text=True)
print("  Final 10s decode errors:  ", res_10.stderr.strip() if res_10.stderr.strip() else "0 errors (CLEAN)")

# PSNR test against source
print("\nRunning PSNR video frame integrity check...")
res_psnr = subprocess.run(['ffmpeg', '-i', str(p23_mp4), '-i', str(orig_mp4), '-filter_complex', 'psnr', '-f', 'null', '-'], capture_output=True, text=True)
for line in res_psnr.stderr.splitlines():
    if 'PSNR' in line:
        print(" ", line.strip())

# Volume and Loudness
print("\nMeasuring audio volume and loudness...")
res_vol = subprocess.run(['ffmpeg', '-i', str(p23_mp4), '-af', 'volumedetect', '-f', 'null', '-'], capture_output=True, text=True)
for line in res_vol.stderr.splitlines():
    if 'max_volume' in line or 'mean_volume' in line:
        print(" ", line.strip())

res_loud = subprocess.run(['ffmpeg', '-i', str(p23_mp4), '-af', 'ebur128', '-f', 'null', '-'], capture_output=True, text=True)
lines = res_loud.stderr.splitlines()
for i, line in enumerate(lines):
    if 'Integrated loudness' in line:
        print("\n".join(["  " + l for l in lines[i-1:i+6]]))
        break
