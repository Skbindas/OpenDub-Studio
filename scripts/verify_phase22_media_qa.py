import subprocess
import json

mp4 = 'runtime/projects/53ba81b5-cc7c-4a68-944e-ff553456a917/output/dubbed_hindi_41374123128_phase22_corrected.mp4'
orig = 'runtime/projects/53ba81b5-cc7c-4a68-944e-ff553456a917/source/original.mp4'

def probe(p):
    cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', p]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(res.stdout)

info_p22 = probe(mp4)
info_orig = probe(orig)

print('=== ORIGINAL MP4 ===')
print('Container duration:', info_orig['format']['duration'])
for s in info_orig['streams']:
    print(f"Stream {s['codec_type']}: codec={s['codec_name']}, dur={s.get('duration')}, frames={s.get('nb_frames')}")

print('\n=== PHASE 22 MP4 ===')
print('Container duration:', info_p22['format']['duration'])
for s in info_p22['streams']:
    print(f"Stream {s['codec_type']}: codec={s['codec_name']}, dur={s.get('duration')}, frames={s.get('nb_frames')}, r_frame_rate={s.get('r_frame_rate')}")

# Decode verification
print('\nRunning full stream decode check on Phase 22 MP4...')
dec = subprocess.run(['ffmpeg', '-v', 'error', '-i', mp4, '-f', 'null', '-'], capture_output=True, text=True)
print('Decode errors stdout:', dec.stdout.strip())
print('Decode errors stderr:', dec.stderr.strip() if dec.stderr.strip() else 'None (0 errors)')

print('\nRunning final 10 seconds decode check on Phase 22 MP4...')
dec_10 = subprocess.run(['ffmpeg', '-v', 'error', '-ss', '74.4', '-i', mp4, '-f', 'null', '-'], capture_output=True, text=True)
print('Final 10s stderr:', dec_10.stderr.strip() if dec_10.stderr.strip() else 'None (0 errors)')

# Loudness check
print('\nMeasuring loudness on Phase 22 MP4...')
loud_cmd = ['ffmpeg', '-i', mp4, '-af', 'ebur128=framelog=verbose', '-f', 'null', '-']
loud_res = subprocess.run(loud_cmd, capture_output=True, text=True)
for line in loud_res.stderr.splitlines():
    if 'Integrated loudness:' in line or 'Threshold:' in line or 'Loudness range:' in line or 'True peak:' in line:
        print(' ', line.strip())

# Video frame PSNR check
print('\nComputing PSNR against original video...')
psnr_cmd = ['ffmpeg', '-i', mp4, '-i', orig, '-filter_complex', 'psnr', '-f', 'null', '-']
psnr_res = subprocess.run(psnr_cmd, capture_output=True, text=True)
for line in psnr_res.stderr.splitlines():
    if 'PSNR' in line:
        print(' ', line.strip())
