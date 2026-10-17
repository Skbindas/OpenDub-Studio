import json
import os
import sys
from pathlib import Path
from PIL import Image
import numpy as np

sys.stdout.reconfigure(encoding='utf-8')

proj = Path('runtime/projects/53ba81b5-cc7c-4a68-944e-ff553456a917')
frames_dir = proj / 'output/qa_comparison/orig_frames_30fps'

with open(proj / 'analysis/transcript.json', 'r', encoding='utf-8') as f:
    transcript = json.load(f)

with open(frames_dir / 'frame_manifest.json', 'r', encoding='utf-8') as f:
    f_manifest = json.load(f)

frames_list = f_manifest['frames']

try:
    import cv2
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    cv2_avail = True
except Exception:
    cv2_avail = False
    face_cascade = None

print(f"CV2 Available: {cv2_avail}")

def analyze_segment_visuals(start_sec, end_sec, speaker_id):
    # Find frames in window
    seg_frames = [f for f in frames_list if start_sec <= f['pts_sec'] <= end_sec]
    if not seg_frames:
        return {'status': 'NO_FRAMES', 'faces_found': 0, 'shot_type': 'unknown'}
    
    face_counts = []
    face_sizes = []
    face_boxes = []
    
    # Sample up to 10 frames evenly across segment
    sample_indices = np.linspace(0, len(seg_frames)-1, min(10, len(seg_frames)), dtype=int)
    for si in sample_indices:
        f_info = seg_frames[si]
        f_path = frames_dir / f_info['file_name']
        if not f_path.is_file(): continue
        
        try:
            with Image.open(f_path) as img:
                w, h = img.size
                if cv2_avail and face_cascade is not None:
                    cv_img = np.array(img)
                    gray = cv2.cvtColor(cv_img, cv2.COLOR_RGB2GRAY)
                    detected = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(30, 30))
                    face_counts.append(len(detected))
                    if len(detected) > 0:
                        for (fx, fy, fw, fh) in detected:
                            face_sizes.append((fw * fh) / (w * h))
                            face_boxes.append((fx/w, fy/h, fw/w, fh/h))
                else:
                    face_counts.append(0)
        except Exception:
            pass
            
    avg_faces = np.mean(face_counts) if face_counts else 0
    max_face_coverage = max(face_sizes) if face_sizes else 0
    
    # Determine visual character condition
    if len(face_sizes) == 0 or max_face_coverage < 0.015:
        if avg_faces < 0.2:
            shot_type = "off-screen / turned away / non-frontal"
        else:
            shot_type = "wide shot / small face"
    elif avg_faces >= 1.5:
        shot_type = "two-shot / multiple characters"
    elif max_face_coverage > 0.08:
        shot_type = "close-up / medium close-up"
    else:
        shot_type = "medium shot"
        
    return {
        'total_frames': len(seg_frames),
        'sampled': len(sample_indices),
        'avg_faces_detected': round(avg_faces, 2),
        'max_face_coverage': round(max_face_coverage, 4),
        'shot_type': shot_type
    }

results = []
for i, s in enumerate(transcript['segments']):
    vis = analyze_segment_visuals(s['start'], s['end'], s['speaker_id'])
    results.append({
        'segment_index': i,
        'speaker_id': s['speaker_id'],
        'start': s['start'],
        'end': s['end'],
        'dur': round(s['end'] - s['start'], 2),
        'text': s['text'],
        **vis
    })
    print(f"Seg {i:02d} ({s['speaker_id']}) [{s['start']:5.2f}-{s['end']:5.2f}s]: Faces={vis['avg_faces_detected']} | Coverage={vis['max_face_coverage']*100:.1f}% | Shot={vis['shot_type']}")

with open(proj / 'output/visual_frame_analysis.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2)
