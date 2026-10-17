import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

p = 'runtime/projects/53ba81b5-cc7c-4a68-944e-ff553456a917/output/qa_comparison/lipsync_report_phase21.json'
with open(p, 'r', encoding='utf-8') as f:
    d = json.load(f)

print('Overall Lip-Sync Status:', d.get('status'))
print(f"Pass: {d.get('pass_count')}, Warn: {d.get('warning_count')}, Fail: {d.get('fail_count')}, Manual: {d.get('manual_review_count')}")

for s in d.get('segments', []):
    idx = s['segment_id']
    cls_status = s.get('status', 'UNKNOWN')
    conf = s.get('confidence', 0.0)
    motion = s.get('motion_detected', False)
    onset_ms = s.get('onset_offset_ms')
    end_ms = s.get('end_offset_ms')
    overlap = s.get('overlap_ratio', 0.0)
    issues = s.get('issues', [])
    print(f"Seg {idx:02d} | {cls_status:13s} | conf={conf:4.2f} | motion={str(motion):5s} | onset={str(onset_ms):6s} | end={str(end_ms):6s} | overlap={overlap:4.2f} | issues={issues}")
