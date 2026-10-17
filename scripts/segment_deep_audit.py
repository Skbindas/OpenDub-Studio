import json
import wave
import sys
from pathlib import Path
from PIL import Image
import numpy as np

sys.stdout.reconfigure(encoding='utf-8')

proj = Path('runtime/projects/53ba81b5-cc7c-4a68-944e-ff553456a917')

with open(proj / 'analysis/transcript.json', 'r', encoding='utf-8') as f:
    transcript = json.load(f)

with open(proj / 'analysis/translated_transcript.json', 'r', encoding='utf-8') as f:
    translated = json.load(f)

with open(proj / 'analysis/alignment_report_phase21.json', 'r', encoding='utf-8') as f:
    alignment_p21 = json.load(f)

with open(proj / 'analysis/dialogue_manifest_phase21.json', 'r', encoding='utf-8') as f:
    diag_p21 = json.load(f)

with open(proj / 'output/qa_comparison/lipsync_report_phase21.json', 'r', encoding='utf-8') as f:
    lipsync_p21 = json.load(f)

def get_wav_dur(p):
    try:
        with wave.open(str(p), 'rb') as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:
        return 0.0

print(f"{'#':2s} | {'Spk':4s} | {'Orig Window':14s} | {'Avail':5s} | {'Raw':5s} | {'Trim':5s} | {'Fit':5s} | {'RepSpd':6s} | {'ActSpd':6s} | {'Trunc':5s} | {'LS Phase21':13s}")
print("-" * 105)

all_seg_data = []

for i in range(28):
    t_seg = transcript['segments'][i]
    tr_seg = translated[i]
    al_seg = alignment_p21[i]
    ls_seg = lipsync_p21['segments'][i]
    
    start = t_seg['start']
    end = t_seg['end']
    dur = end - start
    next_start = transcript['segments'][i+1]['start'] if i < 27 else 84.43
    avail = next_start - start
    
    raw_p = proj / f'segments/segment_{i:06d}_phase21_raw.wav'
    trim_p = proj / f'segments/segment_{i:06d}_phase21_trimmed.wav'
    fit_p = proj / f'segments/segment_{i:06d}_phase21_fit.wav'
    norm_p = proj / f'segments/segment_{i:06d}_phase21_norm.wav'
    
    raw_dur = get_wav_dur(raw_p)
    trim_dur = get_wav_dur(trim_p)
    fit_dur = get_wav_dur(fit_p)
    
    rep_spd = al_seg['speed_ratio']
    # Actual speed would be trim_dur / fit_dur if stretched to fit, BUT if truncated:
    act_stretched_dur = trim_dur / rep_spd
    trunc = max(0.0, act_stretched_dur - fit_dur)
    
    req_spd_orig = trim_dur / dur if dur > 0 else 0
    req_spd_avail = trim_dur / avail if avail > 0 else 0
    
    spk_short = "Neha" if "02" in t_seg['speaker_id'] else "Priya" if "01" in t_seg['speaker_id'] else "Rohan"
    
    print(f"{i:02d} | {spk_short:5s} | {start:5.2f}-{end:5.2f} ({dur:4.2f}s) | {avail:5.2f}s | {raw_dur:5.2f} | {trim_dur:5.2f} | {fit_dur:5.2f} | {rep_spd:6.3f} | {req_spd_orig:6.3f} | {trunc:5.2f} | {ls_seg.get('status'):13s}")
    
    all_seg_data.append({
        'index': i,
        'speaker': spk_short,
        'speaker_id': t_seg['speaker_id'],
        'source_text': t_seg['text'],
        'hindi_text': tr_seg['hindi_text'],
        'start': start,
        'end': end,
        'dur': dur,
        'avail': avail,
        'raw_dur': raw_dur,
        'trim_dur': trim_dur,
        'fit_dur': fit_dur,
        'rep_spd': rep_spd,
        'req_spd_orig': req_spd_orig,
        'req_spd_avail': req_spd_avail,
        'trunc': trunc,
        'ls_status_p21': ls_seg.get('status'),
        'ls_issues_p21': ls_seg.get('issues', [])
    })

with open(proj / 'output/segment_detailed_audit_p21.json', 'w', encoding='utf-8') as f:
    json.dump(all_seg_data, f, indent=2, ensure_ascii=False)
