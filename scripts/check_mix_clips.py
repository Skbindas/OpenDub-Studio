import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('runtime/projects/53ba81b5-cc7c-4a68-944e-ff553456a917/output/mix_manifest.json', 'r', encoding='utf-8') as f:
    m = json.load(f)

print(f"Mix Manifest Clips: {len(m['clips'])}")
prev_end = 0.0
collisions = []

for i, c in enumerate(m['clips']):
    idx = c.get('segment_id', c.get('segment_index', i))
    start = c.get('start_sec', 0.0)
    dur = c.get('duration_sec', 0.0)
    end = start + dur
    overlap = max(0.0, prev_end - start) if i > 0 else 0.0
    if overlap > 0.001:
        collisions.append((i, idx, prev_end, start, overlap))
    print(f"Clip {idx:02d} | Start: {start:6.2f}s | Dur: {dur:5.2f}s | End: {end:6.2f}s | OverlapWithPrev: {overlap:5.3f}s")
    prev_end = end

print(f"\nTotal Collisions / Overlaps detected: {len(collisions)}")
for col in collisions:
    print(f"  Collision between clip {col[0]-1} (ended at {col[2]:.2f}s) and clip {col[0]} (starts at {col[3]:.2f}s) -> overlap = {col[4]:.3f}s")
