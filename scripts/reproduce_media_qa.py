import subprocess
import json
import shutil
import re
import sys
import numpy as np

sys.stdout.reconfigure(encoding='utf-8')

ffprobe = shutil.which('ffprobe')
ffmpeg = shutil.which('ffmpeg')

files = {
    'original_source': 'runtime/projects/53ba81b5-cc7c-4a68-944e-ff553456a917/source/original.mp4',
    'pre_phase21_render': 'runtime/projects/53ba81b5-cc7c-4a68-944e-ff553456a917/output/dubbed_hindi_41374123128.mp4',
    'phase21_corrected': 'runtime/projects/53ba81b5-cc7c-4a68-944e-ff553456a917/output/dubbed_hindi_41374123128_phase21_corrected.mp4'
}

def probe_file(path):
    cmd = [
        ffprobe, '-v', 'error',
        '-show_format', '-show_streams', '-count_frames',
        '-of', 'json', path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    data = json.loads(res.stdout)
    fmt = data.get('format', {})
    v_stream = next((s for s in data.get('streams', []) if s['codec_type'] == 'video'), {})
    a_stream = next((s for s in data.get('streams', []) if s['codec_type'] == 'audio'), {})
    
    r_fr = v_stream.get('r_frame_rate', '0/1')
    num, den = r_fr.split('/') if '/' in r_fr else (0, 1)
    fps = float(num) / float(den) if float(den) > 0 else 0.0

    return {
        'format_duration': float(fmt.get('duration', 0)),
        'size_bytes': int(fmt.get('size', 0)),
        'video_codec': v_stream.get('codec_name'),
        'video_profile': v_stream.get('profile'),
        'width': v_stream.get('width'),
        'height': v_stream.get('height'),
        'pix_fmt': v_stream.get('pix_fmt'),
        'fps': fps,
        'video_duration': float(v_stream.get('duration', 0)),
        'nb_read_frames': int(v_stream.get('nb_read_frames', v_stream.get('nb_frames', 0))),
        'audio_codec': a_stream.get('codec_name'),
        'audio_channels': a_stream.get('channels'),
        'audio_sample_rate': int(a_stream.get('sample_rate', 0)),
        'audio_duration': float(a_stream.get('duration', 0))
    }

def decode_check(path):
    # Full video decode check
    cmd_v = [ffmpeg, '-v', 'error', '-i', path, '-map', '0:v:0', '-f', 'null', '-']
    res_v = subprocess.run(cmd_v, capture_output=True, text=True, timeout=180)
    
    # Full audio decode check
    cmd_a = [ffmpeg, '-v', 'error', '-i', path, '-map', '0:a:0', '-f', 'null', '-']
    res_a = subprocess.run(cmd_a, capture_output=True, text=True, timeout=180)
    
    # Final 10 seconds decode check
    # Video duration ~ 84.5s, so last 10s is 74.5 to 84.5
    cmd_last10 = [ffmpeg, '-v', 'error', '-ss', '74.5', '-i', path, '-f', 'null', '-']
    res_last10 = subprocess.run(cmd_last10, capture_output=True, text=True, timeout=60)
    
    return {
        'video_errors': res_v.stderr.strip() if res_v.stderr else 'None',
        'audio_errors': res_a.stderr.strip() if res_a.stderr else 'None',
        'last10_errors': res_last10.stderr.strip() if res_last10.stderr else 'None'
    }

results = {}
for name, p in files.items():
    print(f"Probing and decoding {name} ({p})...")
    info = probe_file(p)
    dec = decode_check(p)
    results[name] = {**info, **dec}
    print(f"  Duration: {info['format_duration']:.3f}s | Frames: {info['nb_read_frames']} @ {info['fps']:.2f}fps")
    print(f"  Video: {info['video_codec']} ({info['width']}x{info['height']}) | Audio: {info['audio_codec']} {info['audio_sample_rate']}Hz {info['audio_channels']}ch")
    print(f"  Decode errors: V={dec['video_errors']} | A={dec['audio_errors']} | Last10={dec['last10_errors']}")

# Compare source vs phase21 corrected video frames
print("\nComparing Video Frames (Source vs Phase 21 Corrected):")
# Compare using psnr / ssim filter via ffmpeg
psnr_cmd = [
    ffmpeg, '-v', 'error',
    '-i', files['phase21_corrected'],
    '-i', files['original_source'],
    '-lavfi', 'psnr',
    '-f', 'null', '-'
]
res_psnr = subprocess.run(psnr_cmd, capture_output=True, text=True, timeout=180)
print(f"  PSNR / Frame comparison: {res_psnr.stderr.strip()}")

# Measure audio loudness and peak of phase21 mix and render
print("\nAudio Loudness Verification (EBU R128):")
for name in ['phase21_corrected', 'pre_phase21_render']:
    p = files[name]
    cmd = [
        ffmpeg, '-v', 'error',
        '-i', p,
        '-af', 'ebur128=framelog=verbose',
        '-f', 'null', '-'
    ]
    res_loud = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    # Parse integrated loudness and true peak from ebur128 summary
    lines = res_loud.stderr.splitlines()
    summary = [line.strip() for line in lines if 'I:' in line or 'Peak:' in line or 'LRA:' in line]
    print(f"  {name} Loudness:")
    for s in summary[-5:]:
        print(f"    {s}")

with open('runtime/projects/53ba81b5-cc7c-4a68-944e-ff553456a917/output/media_qa_verification.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2)
