"""Stable friendly aliases and conservative technical reference admission.

Aliases identify library entries, not actors, identities or licensed voice rights.
Human approval and distribution permission remain separate requirements.
"""
import math
import re

NAMES = ('Kabir', 'Arjun', 'Veer', 'Dev', 'Rohan', 'Kunal', 'Aman', 'Meera',
         'Tara', 'Naina', 'Ishita', 'Reva', 'Niyati', 'Sana', 'Aditi', 'Kavya',
         'Milan', 'Devansh', 'Arya', 'Zain', 'Rishi', 'Noor', 'Yash', 'Aniket',
         'Samar', 'Ishan', 'Nikhil', 'Avinash', 'Rudra', 'Mayank', 'Dhruv', 'Lalit',
         'Vivaan', 'Siddharth', 'Ayaan', 'Rehan', 'Kiara', 'Om', 'Pranav', 'Mihir',
         'Ashwin', 'Shaurya')


def public_voice_name(voice_id: str) -> str:
    match = re.match(r'^char_(\d+)_', voice_id)
    index = int(match[1]) - 1 if match else -1
    return NAMES[index] if 0 <= index < len(NAMES) else 'Voice ' + voice_id


def reference_blockers(record: dict) -> list[str]:
    """Block known-bad evidence; never turn absence of evidence into approval."""
    audit = record.get('audit') or {}
    metrics = record.get('metrics') or {}
    review = record.get('review') or {}
    blockers = []
    if audit.get('status') != 'single_speaker_candidate':
        blockers.append(audit.get('status') or 'not_audited')
    if not str(audit.get('speech_text') or '').strip():
        blockers.append('speech_transcript_missing')
    if (audit.get('speaker_count_detected') or 0) > 1:
        blockers.append('multiple_speakers')
    if audit.get('overlaps'):
        blockers.append('overlapping_speakers')
    for key in ('single_speaker', 'speech_present', 'naturalness_passed', 'dialogue_content_passed', 'clone_identity_passed'):
        if review.get(key) is False:
            blockers.append('review_rejected_' + key)
    try:
        seconds = float(metrics.get('duration_sec', 0))
        level = float(metrics.get('rms_dbfs', 0))
        if not math.isfinite(seconds) or not 3 <= seconds <= 10.01:
            blockers.append('reference_duration_outside_engine_range')
        if not math.isfinite(level) or level < -60:
            blockers.append('silent_or_near_silent')
    except (ValueError, TypeError):
        blockers.append('invalid_audio_metrics')
    if metrics.get('fixed_tone_suspected'):
        blockers.append('non_speech_tone')
    return list(dict.fromkeys(blockers))
