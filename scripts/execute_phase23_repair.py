"""Phase 23: Targeted Human-QA Lip-Sync Repair Execution Script."""
import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import soundfile as sf
import numpy as np
import edge_tts

sys.stdout.reconfigure(encoding='utf-8')

PROJ_DIR = Path('runtime/projects/53ba81b5-cc7c-4a68-944e-ff553456a917')
SEGS_DIR = PROJ_DIR / 'segments'
OUT_DIR = PROJ_DIR / 'output'

# Load Phase 22 manifests
with open(PROJ_DIR / 'alignment_report_phase22.json', 'r', encoding='utf-8') as f:
    align_p22 = json.load(f)

with open(PROJ_DIR / 'lipsync_report_phase22.json', 'r', encoding='utf-8') as f:
    lipsync_p22 = json.load(f)

# Repair specifications
REPAIRS = {
    8: {
        "speaker": "SPEAKER_01",
        "voice": "hi-IN-SwaraNeural",
        "pitch": "-4Hz",
        "rate": "+5%",
        "hindi_text": "चल जा!",
        "target_dur": 0.400,
        "visible_mouth_end": 16.55,
        "rationale": "Shortened from 'जा, जल्दी!' to punchy imperative 'चल जा!' (0.40s fitted), ending speech at 16.60s (+50ms after mouth closure at 16.55s) instead of +724ms late."
    },
    14: {
        "speaker": "SPEAKER_02",
        "voice": "hi-IN-SwaraNeural",
        "pitch": "+8Hz",
        "rate": "+6%",
        "hindi_text": "तुम्हारी आँखें खराब हैं, पूरे परिवार की!",
        "target_dur": 2.470,
        "visible_mouth_end": 41.40,
        "rationale": "Shortened from 'तुम्हारी आँखें खराब हैं, तुम्हारे पूरे परिवार की!' to 'तुम्हारी आँखें खराब हैं, पूरे परिवार की!' (2.469s fitted), ending speech at 41.399s (-1ms delta to mouth closure at 41.40s) instead of +592ms late."
    },
    26: {
        "speaker": "SPEAKER_03",
        "voice": "hi-IN-MadhurNeural",
        "pitch": "+0Hz",
        "rate": "+10%",
        "hindi_text": "दौड़ेंगे तो पसीना आएगा!",
        "target_dur": 1.250,
        "visible_mouth_end": 73.16,
        "rationale": "Shortened from 'दौड़ने पर तो पसीना आएगा ही!' to natural jogging line 'दौड़ेंगे तो पसीना आएगा!' (1.250s fitted), ending speech at 73.22s (+60ms delta to mouth closure at 73.16s) instead of +592ms late."
    }
}

async def synthesize_segment(idx: int, spec: dict):
    raw_wav = SEGS_DIR / f"segment_{idx:06d}_phase23_raw.wav"
    raw_mp3 = SEGS_DIR / f"segment_{idx:06d}_phase23_raw.mp3"
    trimmed_wav = SEGS_DIR / f"segment_{idx:06d}_phase23_trimmed.wav"
    fit_wav = SEGS_DIR / f"segment_{idx:06d}_phase23_fit.wav"
    norm_wav = SEGS_DIR / f"segment_{idx:06d}_phase23_norm.wav"

    print(f"Synthesizing repaired Segment {idx:02d}: '{spec['hindi_text']}'...")
    comm = edge_tts.Communicate(spec['hindi_text'], spec['voice'], pitch=spec['pitch'], rate=spec['rate'])
    await comm.save(str(raw_mp3))

    # Convert mp3 to 48kHz WAV
    subprocess.run(['ffmpeg', '-y', '-i', str(raw_mp3), '-ar', '48000', '-ac', '2', str(raw_wav)], capture_output=True, check=True)
    if raw_mp3.exists():
        raw_mp3.unlink()

    # Trim non-speech silence cleanly
    subprocess.run([
        'ffmpeg', '-y', '-i', str(raw_wav),
        '-af', 'silenceremove=start_periods=1:start_duration=0.01:start_threshold=-40dB:detection=rms,areverse,silenceremove=start_periods=1:start_duration=0.01:start_threshold=-40dB:detection=rms,areverse',
        '-ar', '48000', '-ac', '2', str(trimmed_wav)
    ], capture_output=True, check=True)

    t_data, sr = sf.read(str(trimmed_wav))
    t_dur = len(t_data) / sr

    # Compute tempo to fit target_dur
    target = spec['target_dur']
    tempo = t_dur / target
    # Clamp tempo between 0.85x and 1.25x
    applied_tempo = min(1.25, max(0.85, tempo))

    print(f"  Trimmed duration: {t_dur:.4f}s, Target: {target:.4f}s, Applied Tempo: {applied_tempo:.4f}x")

    # Time-stretch using Rubber Band (pitch and formant preserved)
    subprocess.run([
        'ffmpeg', '-y', '-i', str(trimmed_wav),
        '-af', f'rubberband=tempo={applied_tempo:.6f}:pitch=1.0:formant=preserved',
        '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', str(fit_wav)
    ], capture_output=True, check=True)

    f_data, _ = sf.read(str(fit_wav))
    f_dur = len(f_data) / sr
    print(f"  Fitted duration: {f_dur:.4f}s (Math check: {t_dur/applied_tempo:.4f}s, diff: {abs(f_dur - t_dur/applied_tempo):.6f}s)")

    # Loudnorm
    subprocess.run([
        'ffmpeg', '-y', '-i', str(fit_wav),
        '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11',
        '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', str(norm_wav)
    ], capture_output=True, check=True)

    return {
        "trimmed_dur": t_dur,
        "fitted_dur": f_dur,
        "applied_tempo": applied_tempo,
        "norm_wav": norm_wav
    }

async def run_phase23_repair():
    print("=" * 60)
    print("OpenDub Studio — Phase 23 Targeted Lip-Sync Repair Execution")
    print("=" * 60)

    # 1. Produce repaired stems for 08, 14, 26
    repair_results = {}
    for idx, spec in REPAIRS.items():
        repair_results[idx] = await synthesize_segment(idx, spec)

    # 2. Copy/preserve Phase 22 stems for all other segments
    for s in align_p22:
        idx = s['segment_index']
        if idx not in REPAIRS:
            for kind in ['raw', 'trimmed', 'fit', 'norm']:
                src = SEGS_DIR / f"segment_{idx:06d}_phase22_{kind}.wav"
                dst = SEGS_DIR / f"segment_{idx:06d}_phase23_{kind}.wav"
                if src.is_file() and not dst.is_file():
                    shutil.copy2(src, dst)

    # 3. Assemble Phase 23 Timeline and Mix
    print("\nBuilding Phase 23 Audio Mix...")
    timeline_clips = []
    phase23_align = []

    for s in align_p22:
        idx = s['segment_index']
        seg_entry = dict(s)

        if idx in REPAIRS:
            res = repair_results[idx]
            spec = REPAIRS[idx]
            seg_entry['target_text_hindi'] = spec['hindi_text']
            seg_entry['trimmed_tts_duration'] = round(res['trimmed_dur'], 4)
            seg_entry['actual_fitted_duration'] = round(res['fitted_dur'], 4)
            seg_entry['applied_tempo_factor'] = round(res['applied_tempo'], 4)
            seg_entry['timeline_audio_start'] = s['timeline_audio_start']
            seg_entry['timeline_audio_end'] = round(s['timeline_audio_start'] + res['fitted_dur'], 4)
            seg_entry['modification_type'] = "phase23_human_qa_lipsync_repaired"
            seg_entry['math_reconciled'] = bool(abs(res['fitted_dur'] - res['trimmed_dur'] / res['applied_tempo']) < 0.005)
            seg_entry['reconciliation_formula'] = f"{res['trimmed_dur']:.3f}s / {res['applied_tempo']:.3f}x = {res['fitted_dur']:.3f}s"
            seg_entry['visible_mouth_end'] = spec['visible_mouth_end']
            seg_entry['end_of_speech_delta_ms'] = round((seg_entry['timeline_audio_end'] - spec['visible_mouth_end']) * 1000, 1)

            norm_file = SEGS_DIR / f"segment_{idx:06d}_phase23_norm.wav"
        else:
            norm_file = SEGS_DIR / f"segment_{idx:06d}_phase23_norm.wav"
            if not norm_file.exists():
                norm_file = SEGS_DIR / f"segment_{idx:06d}_phase22_norm.wav"

        timeline_clips.append({
            "segment_index": idx,
            "start": seg_entry['timeline_audio_start'],
            "end": seg_entry['timeline_audio_end'],
            "path": norm_file
        })
        phase23_align.append(seg_entry)

    # Recompute gaps and collisions
    for i in range(len(phase23_align) - 1):
        gap = round(phase23_align[i+1]['timeline_audio_start'] - phase23_align[i]['timeline_audio_end'], 4)
        phase23_align[i]['gap_to_next_dialogue'] = gap
        phase23_align[i]['overlap_with_neighbor'] = bool(gap < 0)

    phase23_align[-1]['gap_to_next_dialogue'] = round(84.433 - phase23_align[-1]['timeline_audio_end'], 4)
    phase23_align[-1]['overlap_with_neighbor'] = False

    # 4. Mix with Background
    bg_wav = OUT_DIR / "background_preserved.wav"
    mix_p23_wav = OUT_DIR / "mix_phase23.wav"

    filter_complex = []
    filter_complex.append("[0:a]anull[bg]")

    labels = []
    cmd = ['ffmpeg', '-y', '-i', str(bg_wav)]
    for i, c in enumerate(timeline_clips):
        cmd.extend(['-i', str(c['path'])])
        delay = round(c['start'] * 1000)
        filter_complex.append(f"[{i+1}:a]adelay={delay}|{delay}[d{i}]")
        labels.append(f"[d{i}]")

    filter_complex.append("".join(labels) + f"amix=inputs={len(labels)}:duration=longest:normalize=0[dialogue]")
    # Duck background and loudnorm
    filter_complex.append("[dialogue]asplit=2[dia_sc][dia_mix]")
    filter_complex.append("[dia_sc]apad[dia_sc_pad]")
    filter_complex.append("[bg][dia_sc_pad]sidechaincompress=threshold=0.025:ratio=8:attack=15:release=350[ducked]")
    filter_complex.append("[ducked][dia_mix]amix=inputs=2:duration=longest:normalize=0,loudnorm=I=-16.0:TP=-1.5:LRA=11[mix_loud]")
    filter_complex.append("[mix_loud]apad=whole_dur=84.497415,atrim=0:84.497415[mix_final]")

    cmd.extend([
        '-filter_complex', ";".join(filter_complex),
        '-map', '[mix_final]',
        '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le',
        str(mix_p23_wav)
    ])

    print("Rendering mix_phase23.wav...")
    subprocess.run(cmd, capture_output=True, check=True)
    shutil.copy2(mix_p23_wav, Path('mix_phase23.wav'))
    print("[OK] mix_phase23.wav rendered successfully!")

    # 5. Render Phase 23 Production Master Video
    orig_mp4 = PROJ_DIR / 'source/original.mp4'
    out_p23_mp4 = OUT_DIR / 'dubbed_hindi_41374123128_phase23_corrected.mp4'

    print(f"Muxing Phase 23 production master: {out_p23_mp4.name}...")
    subprocess.run([
        'ffmpeg', '-y',
        '-i', str(orig_mp4),
        '-i', str(mix_p23_wav),
        '-c:v', 'copy',
        '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
        '-map', '0:v:0', '-map', '1:a:0',
        '-shortest',
        str(out_p23_mp4)
    ], capture_output=True, check=True)

    print(f"[OK] {out_p23_mp4.name} created successfully ({out_p23_mp4.stat().st_size} bytes)!")

    # 6. Save alignment_report_phase23.json
    for p in [PROJ_DIR / 'alignment_report_phase23.json', Path('alignment_report_phase23.json')]:
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(phase23_align, f, indent=2, ensure_ascii=False)

    return phase23_align

if __name__ == '__main__':
    asyncio.run(run_phase23_repair())
