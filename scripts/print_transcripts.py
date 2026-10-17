import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

p = 'runtime/projects/53ba81b5-cc7c-4a68-944e-ff553456a917/analysis/transcript.json'
with open(p, 'r', encoding='utf-8') as f:
    d = json.load(f)
    print('Language:', d.get('language'), 'Prob:', d.get('language_probability'))
    for s in d.get('segments', []):
        dur = s['end'] - s['start']
        print(f"{s['segment_index']:02d} | {s['start']:6.2f}-{s['end']:6.2f} ({dur:4.2f}s) | {s.get('speaker_id')}: {s['text']}")
