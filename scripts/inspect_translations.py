import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

proj = 'runtime/projects/53ba81b5-cc7c-4a68-944e-ff553456a917'

with open(f'{proj}/analysis/transcript.json', 'r', encoding='utf-8') as f:
    t = json.load(f)
with open(f'{proj}/analysis/translated_transcript.json', 'r', encoding='utf-8') as f:
    tt = json.load(f)

for i in range(28):
    s = t['segments'][i]
    tr = tt[i]
    print(f"[{i:02d}] {s['speaker_id']} ({s['start']:5.2f}-{s['end']:5.2f}s, {s['end']-s['start']:4.2f}s):")
    print(f"     Source (ZH): {s['text']}")
    print(f"     Hindi (HI):  {tr['hindi_text']}")
