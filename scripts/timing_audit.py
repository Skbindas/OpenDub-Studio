import json
import wave
import sys
import numpy as np

sys.stdout.reconfigure(encoding='utf-8')

proj = 'runtime/projects/53ba81b5-cc7c-4a68-944e-ff553456a917'

def wav_info(path):
    try:
        with wave.open(path, 'rb') as w:
            sr = w.getframerate()
            frames = w.getnframes()
            ch = w.getnchannels()
            dur = frames / float(sr)
            return {'dur': dur, 'sr': sr, 'frames': frames, 'ch': ch}
    except Exception as e:
        return {'dur': -1, 'error': str(e)}

with open(f'{proj}/analysis/transcript.json', 'r', encoding='utf-8') as f:
    transcript = json.load(f)
with open(f'{proj}/analysis/translated_transcript.json', 'r', encoding='utf-8') as f:
    trans_t = json.load(f)
with open(f'{proj}/analysis/alignment_report_phase21.json', 'r', encoding='utf-8') as f:
    align_rep = json.load(f)
with open(f'{proj}/analysis/dialogue_manifest_phase21.json', 'r', encoding='utf-8') as f:
    diag_m = json.load(f)
with open(f'{proj}/output/mix_manifest.json', 'r', encoding='utf-8') as f:
    mix_m = json.load(f)

t_segs = transcript['segments']
units = diag_m['units']
clips = mix_m.get('clips', [])

print("="*120)
print(f"{'Seg':3s} | {'Spk':10s} | {'Orig Window':15s} | {'Avail Win':9s} | {'Raw':6s} | {'Trimmed':7s} | {'Fitted':6s} | {'RepSpd':6s} | {'MathFit':7s} | {'Diff':6s} | {'Status'}")
print("="*120)

discrepancies = []

for i in range(28):
    t_s = t_segs[i]
    orig_start = t_s['start']
    orig_end = t_s['end']
    orig_dur = orig_end - orig_start
    
    # Available window before next segment start
    next_start = t_segs[i+1]['start'] if i < 27 else orig_end + 5.0
    avail_win = next_start - orig_start
    
    raw_p = f"{proj}/segments/segment_{i:06d}_phase21_raw.wav"
    trim_p = f"{proj}/segments/segment_{i:06d}_phase21_trimmed.wav"
    fit_p = f"{proj}/segments/segment_{i:06d}_phase21_fit.wav"
    norm_p = f"{proj}/segments/segment_{i:06d}_phase21_norm.wav"
    
    raw_info = wav_info(raw_p)
    trim_info = wav_info(trim_p)
    fit_info = wav_info(fit_p)
    norm_info = wav_info(norm_p)
    
    rep = align_rep[i]
    rep_spd = rep['speed_ratio']
    rep_fit = rep['fitted_duration']
    
    math_fit = trim_info['dur'] / rep_spd
    diff = abs(math_fit - fit_info['dur'])
    
    status = "OK"
    if diff > 0.02:
        status = "MATH_MISMATCH"
        discrepancies.append({
            'seg': i,
            'orig_dur': orig_dur,
            'avail_win': avail_win,
            'trim_dur': trim_info['dur'],
            'fit_dur': fit_info['dur'],
            'rep_spd': rep_spd,
            'math_fit': math_fit,
            'diff': diff,
            'required_speed': trim_info['dur'] / orig_dur,
            'source_text': t_s['text'],
            'hindi_text': trans_t[i]['hindi_text']
        })
    elif rep_spd > 1.30 or (trim_info['dur'] / orig_dur) > 1.30:
        status = "SPEED_LIMIT_EXCEEDED"

    print(f"{i:02d}  | {t_s['speaker_id']:10s} | {orig_start:5.2f}-{orig_end:5.2f} ({orig_dur:4.2f}s) | {avail_win:6.2f}s   | {raw_info['dur']:6.2f} | {trim_info['dur']:7.3f} | {fit_info['dur']:6.3f} | {rep_spd:6.3f} | {math_fit:7.3f} | {diff:6.3f} | {status}")

print("="*120)
print(f"Total Segments with Math Mismatch (trimmed / speed_ratio != fitted_duration): {len(discrepancies)}")
for d in discrepancies:
    print(f"Seg {d['seg']:02d}: Trim={d['trim_dur']:.3f}s, Target={d['orig_dur']:.2f}s, RepSpeed={d['rep_spd']:.3f}x, MathFit={d['math_fit']:.3f}s vs ActFit={d['fit_dur']:.3f}s (Diff={d['diff']:.3f}s). True Required Speed={d['required_speed']:.3f}x")
    print(f"  Chinese: {d['source_text']}")
    print(f"  Hindi:   {d['hindi_text']}")
