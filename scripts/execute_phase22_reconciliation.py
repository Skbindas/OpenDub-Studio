import asyncio
import edge_tts
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

sys.stdout.reconfigure(encoding='utf-8')

PROJ_DIR = Path('runtime/projects/53ba81b5-cc7c-4a68-944e-ff553456a917')
ANALYSIS_DIR = PROJ_DIR / 'analysis'
OUTPUT_DIR = PROJ_DIR / 'output'
SEGMENTS_DIR = PROJ_DIR / 'segments'
QA_DIR = OUTPUT_DIR / 'qa_comparison'
FRAMES_DIR = QA_DIR / 'orig_frames_30fps'

ffmpeg = shutil.which('ffmpeg')
ffprobe = shutil.which('ffprobe')

with open(ANALYSIS_DIR / 'dialogue_manifest_phase22_planned.json', 'r', encoding='utf-8') as f:
    dialogue_specs = json.load(f)

def run_cmd(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed ({' '.join(cmd[:4])}...): {p.stderr}")
    return p

def get_audio_info(p):
    with wave.open(str(p), 'rb') as w:
        frames = w.getnframes()
        sr = w.getframerate()
        ch = w.getnchannels()
        return {'dur': frames / float(sr), 'sr': sr, 'frames': frames, 'ch': ch}

async def synth_stem(spec):
    idx = spec['index']
    text = spec['hindi_text']
    voice = spec['voice']
    pitch = spec['pitch']
    rate = spec['rate']
    
    raw_path = SEGMENTS_DIR / f'segment_{idx:06d}_phase22_raw.wav'
    trim_path = SEGMENTS_DIR / f'segment_{idx:06d}_phase22_trimmed.wav'
    
    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tf:
        tmp_mp3 = tf.name
    try:
        comm = edge_tts.Communicate(text, voice, pitch=pitch, rate=rate)
        await comm.save(tmp_mp3)
        
        # Convert to 48kHz stereo WAV raw
        run_cmd([
            ffmpeg, '-y', '-v', 'error',
            '-i', tmp_mp3,
            '-ar', '48000', '-ac', '2',
            '-c:a', 'pcm_s16le',
            str(raw_path)
        ])
        
        # Robust leading and trailing silence trimming
        # Uses silenceremove forward and reverse
        run_cmd([
            ffmpeg, '-y', '-v', 'error',
            '-i', str(raw_path),
            '-af', 'silenceremove=start_periods=1:start_duration=0.02:start_threshold=-50dB:detection=peak,areverse,silenceremove=start_periods=1:start_duration=0.02:start_threshold=-50dB:detection=peak,areverse',
            '-ar', '48000', '-ac', '2',
            '-c:a', 'pcm_s16le',
            str(trim_path)
        ])
    finally:
        if os.path.exists(tmp_mp3):
            os.unlink(tmp_mp3)

async def synthesize_all():
    print("Synthesizing raw and trimmed stems for all 28 dialogue segments...")
    for spec in dialogue_specs:
        await synth_stem(spec)
        idx = spec['index']
        raw_dur = get_audio_info(SEGMENTS_DIR / f'segment_{idx:06d}_phase22_raw.wav')['dur']
        trim_dur = get_audio_info(SEGMENTS_DIR / f'segment_{idx:06d}_phase22_trimmed.wav')['dur']
        print(f"  Seg {idx:02d}: Raw={raw_dur:.3f}s | Trimmed={trim_dur:.3f}s | '{spec['hindi_text']}'")

def process_fitting_and_normalization():
    print("\nCalculating optimal tempo factors and generating fitted & normalized audio stems...")
    processed = []
    
    for i, spec in enumerate(dialogue_specs):
        idx = spec['index']
        orig_start = spec['orig_start']
        orig_end = spec['orig_end']
        orig_dur = orig_end - orig_start
        
        next_start = dialogue_specs[i+1]['orig_start'] if i < 27 else 84.43
        avail_win = next_start - orig_start
        
        trim_path = SEGMENTS_DIR / f'segment_{idx:06d}_phase22_trimmed.wav'
        fit_path = SEGMENTS_DIR / f'segment_{idx:06d}_phase22_fit.wav'
        norm_path = SEGMENTS_DIR / f'segment_{idx:06d}_phase22_norm.wav'
        
        trim_dur = get_audio_info(trim_path)['dur']
        
        # Calculate optimal tempo T and fitted duration
        # We ensure T is strictly between 0.85 and 1.25 (or up to 1.28 max), and NO SPEECH TRUNCATION.
        # Max duration we can occupy without collision is avail_win - safety_gap
        safety_gap = 0.12 if i < 27 else 0.50
        max_occupy = max(orig_dur, avail_win - safety_gap)
        
        # Desired tempo:
        # If trim_dur / orig_dur <= 1.25, we fit exactly into orig_dur!
        if (trim_dur / orig_dur) <= 1.25:
            tempo = round(trim_dur / orig_dur, 4)
            fitted_dur = orig_dur
        else:
            # Need to extend into available window so tempo is pleasant and <= 1.25x
            # Target tempo between 1.10x and 1.20x
            target_tempo = 1.15
            needed_dur = trim_dur / target_tempo
            if needed_dur <= max_occupy:
                tempo = target_tempo
                fitted_dur = needed_dur
            else:
                # Use max_occupy
                tempo = round(trim_dur / max_occupy, 4)
                # Cap tempo at 1.28x
                tempo = min(1.28, max(0.95, tempo))
                fitted_dur = trim_dur / tempo

        # Apply rubberband time stretch (pitch and formant preserved)
        # Note: Do NOT use atrim so words are never truncated!
        run_cmd([
            ffmpeg, '-y', '-v', 'error',
            '-i', str(trim_path),
            '-af', f'rubberband=tempo={tempo:.6f}:pitch=1.0:formant=preserved',
            '-ar', '48000', '-ac', '2',
            '-c:a', 'pcm_s16le',
            str(fit_path)
        ])
        
        actual_fit_dur = get_audio_info(fit_path)['dur']
        
        # Normalize to EBU R128 (-16 LUFS, true peak -1.5 dBTP)
        run_cmd([
            ffmpeg, '-y', '-v', 'error',
            '-i', str(fit_path),
            '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11',
            '-ar', '48000', '-ac', '2',
            '-c:a', 'pcm_s16le',
            str(norm_path)
        ])
        
        actual_norm_dur = get_audio_info(norm_path)['dur']
        
        audio_start = orig_start
        audio_end = round(audio_start + actual_fit_dur, 3)
        gap_to_next = round(next_start - audio_end, 3)
        
        # Mathematical verification:
        math_fit = trim_dur / tempo
        reconciled = abs(actual_fit_dur - math_fit) < 0.015
        
        print(f"Seg {idx:02d}: Trim={trim_dur:.3f}s | Tempo={tempo:.3f}x | FitDur={actual_fit_dur:.3f}s | Timeline={audio_start:5.2f}-{audio_end:5.2f}s | Next={next_start:5.2f}s (Gap={gap_to_next:5.2f}s) | Reconciled={reconciled}")
        
        processed.append({
            'segment_index': idx,
            'speaker_id': spec['speaker_id'],
            'character_name': spec['character'],
            'source_text': spec['source_zh'],
            'hindi_text': spec['hindi_text'],
            'voice_profile': {'voice': spec['voice'], 'pitch': spec['pitch'], 'rate': spec['rate']},
            'original_start': orig_start,
            'original_end': orig_end,
            'original_duration': round(orig_dur, 3),
            'available_window': round(avail_win, 3),
            'raw_tts_duration': round(get_audio_info(SEGMENTS_DIR / f'segment_{idx:06d}_phase22_raw.wav')['dur'], 3),
            'trimmed_tts_duration': round(trim_dur, 3),
            'fitted_duration': round(actual_fit_dur, 3),
            'actual_speed_factor': round(tempo, 4),
            'audio_start_sec': audio_start,
            'audio_end_sec': audio_end,
            'timing_offset': round(audio_start - orig_start, 3),
            'gap_to_next_dialogue': gap_to_next,
            'math_reconciled': reconciled,
            'truncation_seconds': 0.0,
            'raw_audio_path': str(SEGMENTS_DIR / f'segment_{idx:06d}_phase22_raw.wav'),
            'trimmed_audio_path': str(trim_path),
            'fitted_audio_path': str(fit_path),
            'normalized_audio_path': str(norm_path)
        })
        
    return processed

def mix_and_render(processed_units):
    print("\nMixing dialogue stems with preserved background audio...")
    bg_path = OUTPUT_DIR / 'background_preserved.wav'
    mix_out = OUTPUT_DIR / 'mix_phase22.wav'
    root_mix_out = PROJ_DIR / 'mix_phase22.wav'
    
    # Build FFmpeg complex filtergraph to place each clip at its exact timestamp
    # Input 0: background_preserved.wav
    # Inputs 1..28: segment_XXXXXX_phase22_norm.wav
    cmd = [ffmpeg, '-y', '-v', 'error', '-i', str(bg_path)]
    for u in processed_units:
        cmd.extend(['-i', u['normalized_audio_path']])
        
    filter_chains = []
    # Background gets a slight ducking or stays intact
    filter_chains.append("[0:a]volume=0.85[bg]")
    
    mix_inputs = ["[bg]"]
    for i, u in enumerate(processed_units):
        delay_ms = int(round(u['audio_start_sec'] * 1000))
        # adelay takes delay for each channel: delay_ms|delay_ms
        filter_chains.append(f"[{i+1}:a]adelay={delay_ms}|{delay_ms}[d{i}]")
        mix_inputs.append(f"[d{i}]")
        
    mix_cmd = "".join(mix_inputs) + f"amix=inputs={len(mix_inputs)}:duration=first:dropout_transition=0,volume={len(mix_inputs)}:precision=fixed,loudnorm=I=-16:TP=-1.5:LRA=11[outa]"
    filter_chains.append(mix_cmd)
    
    full_filter = ";".join(filter_chains)
    cmd.extend([
        '-filter_complex', full_filter,
        '-map', '[outa]',
        '-ar', '48000', '-ac', '2',
        '-c:a', 'pcm_s16le',
        str(mix_out)
    ])
    
    run_cmd(cmd)
    shutil.copy2(mix_out, root_mix_out)
    print(f"  Mixed audio saved to: {mix_out} and {root_mix_out}")
    
    # Save mix manifest
    mix_manifest = {
        'schema_version': 2,
        'output_file': str(mix_out),
        'target_lufs': -16.0,
        'true_peak_ceiling': -1.5,
        'dialogue_segments_mixed': len(processed_units),
        'background_used': True,
        'background_path': str(bg_path),
        'created_at': datetime.now(timezone.utc).isoformat(),
        'clips': [
            {
                'segment_index': u['segment_index'],
                'start_sec': u['audio_start_sec'],
                'end_sec': u['audio_end_sec'],
                'duration_sec': u['fitted_duration'],
                'audio_path': u['normalized_audio_path']
            }
            for u in processed_units
        ]
    }
    with open(OUTPUT_DIR / 'mix_manifest_phase22.json', 'w', encoding='utf-8') as f:
        json.dump(mix_manifest, f, indent=2)

    # Render Phase 22 corrected video MP4
    print("\nMuxing Phase 22 video output (dubbed_hindi_41374123128_phase22_corrected.mp4)...")
    source_mp4 = PROJ_DIR / 'source/original.mp4'
    render_out = OUTPUT_DIR / 'dubbed_hindi_41374123128_phase22_corrected.mp4'
    
    run_cmd([
        ffmpeg, '-y', '-v', 'error',
        '-i', str(source_mp4),
        '-i', str(mix_out),
        '-map', '0:v:0',
        '-map', '1:a:0',
        '-c:v', 'copy',
        '-c:a', 'aac', '-b:a', '192k',
        str(render_out)
    ])
    print(f"  Rendered Phase 22 MP4: {render_out} ({render_out.stat().st_size} bytes)")
    return render_out

if __name__ == '__main__':
    asyncio.run(synthesize_all())
    processed = process_fitting_and_normalization()
    render_out = mix_and_render(processed)
    print("\nPhase 22 Synthesis, Fitting, Mixing, and Rendering COMPLETE!")
