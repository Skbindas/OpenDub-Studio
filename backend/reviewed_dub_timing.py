"""Explicit, bounded audio-only allowances; original ASR clocks are retained."""
import json,math,wave


def apply_reviewed_windows(manifest,rows,review,source_hash,duration,raw_turns):
    if review.get('source_sha256')!=source_hash:raise ValueError('Timing allowance belongs to a different source; review it again.')
    changes=[]
    for entry in review.get('entries',[]):
        index=entry['segment_index'];row=next((r for r in rows if r.get('segment_index')==index),None)
        unit=next((u for u in manifest.get('units',[]) if u.get('segment_index')==index),None)
        if row is None or unit is None:raise ValueError('Reviewed dialogue is missing.')
        start,end=float(entry['start']),float(entry['source_end'])
        original=row.get('source_asr_timing') or row
        if not entry.get('confirmed') or entry.get('confirmed_by')!='user':raise ValueError('A timing allowance requires explicit user review.')
        if entry.get('allowance_type')=='bounded_dialogue_gap':
            left,right=float(entry['window_start']),float(entry['window_end'])
            if not all(math.isfinite(v) for v in (start,end,left,right)) or not 0<=left<=start<end<=right<=duration:
                raise ValueError('Reviewed timing allowance exceeds the bounded source window.')
        else:
            extra=float(entry['extension_sec']);left,right=start,end+extra
            if not all(math.isfinite(v) for v in (start,end,extra)) or not 0<extra<=.35 or not 0<=start<end<right<=duration:
                raise ValueError('Reviewed timing allowance exceeds the bounded source window.')
        if abs(original['start']-start)>.001 or abs(original['end']-end)>.001 or row.get('translated_text')!=entry.get('translated_text') or row.get('speaker_id')!=entry.get('speaker_id'):
            raise ValueError('Dialogue changed since timing review; renew the allowance.')
        if any(change[0] is row for change in changes):raise ValueError('Duplicate reviewed dialogue window.')
        changes.append((row,unit,entry,start,end,left,right))
    # Validate the complete proposed timeline before mutating either document.
    planned={change[0]['segment_index']:(change[-2],change[-1]) for change in changes}
    for row,unit,entry,start,end,left,right in changes:
        neighbors=[planned.get(r.get('segment_index'),(float(r['start']),float(r['end']))) for r in rows if r is not row]
        neighbors += [(float(r['start']),float(r['end'])) for r in raw_turns if r.get('speaker_id')!=row.get('speaker_id')]
        added=[(left,start)] if left<start else []
        if right>end:added.append((end,right))
        if any(other_start<added_end and other_end>added_start
               for added_start,added_end in added for other_start,other_end in neighbors):
            raise ValueError('Timing allowance would overlap another speaking turn.')
    for row,unit,entry,start,end,left,right in changes:
        annotation={'source_asr_timing':{'start':start,'end':end},'timing_window_source':'user_approved_dialogue_gap',
                    'timing_extension_review':dict(entry)}
        row.update(annotation,start=round(left,6),end=round(right,6))
        unit.update(annotation,start_sec=round(left,6),end_sec=round(right,6),duration_sec=round(right-left,6))


def replay_reviewed_windows(base,manifest,rows):
    path=base/'analysis/dub_timing_overrides.json'
    if not path.exists():return
    review=json.loads(path.read_text(encoding='utf-8'))
    diar=json.loads((base/'analysis/diarization.json').read_text(encoding='utf-8'))
    with wave.open(str(base/'analysis/vocals_16k_mono.wav'),'rb') as audio:
        duration=audio.getnframes()/audio.getframerate()
    apply_reviewed_windows(manifest,rows,review,diar.get('identity_source_sha256'),duration,diar.get('regular_turns',[]))
