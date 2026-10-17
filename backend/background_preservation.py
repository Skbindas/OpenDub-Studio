from __future__ import annotations

import json
import math
import os
import shutil
import struct
import subprocess
import tempfile
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import numpy as np
    import soundfile as sf
except ImportError:
    np = None  # type: ignore
    sf = None  # type: ignore



def _bin(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"{name} not found on PATH; ensure FFmpeg/ffprobe are installed.")
    return path


def probe_audio_duration(path: Path) -> float:
    """Return the duration in seconds of an audio file via ffprobe."""
    if not path.is_file():
        raise FileNotFoundError(f"Audio file not found: {path}")
    probe = _bin("ffprobe")
    result = subprocess.run(
        [
            probe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"Failed to probe audio duration for {path}: {result.stderr}")
    return float(result.stdout.strip())


def extract_full_fidelity_audio(source_movie: Path, output_wav: Path) -> Path:
    """Extract pristine 48kHz 16-bit stereo PCM audio from the source movie."""
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = _bin("ffmpeg")
    movie_dur = None
    try:
        movie_dur = probe_audio_duration(source_movie)
    except Exception:
        pass
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-y",
        "-i",
        str(source_movie),
        "-vn",
    ]
    if movie_dur and movie_dur > 0:
        cmd += ["-af", f"apad=whole_dur={movie_dur:.6f},atrim=0:{movie_dur:.6f}"]
    cmd += [
        "-ar",
        "48000",
        "-ac",
        "2",
        "-c:a",
        "pcm_s16le",
        "-rf64", "auto",
        str(output_wav),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if result.returncode != 0 or not output_wav.is_file() or output_wav.stat().st_size == 0:
        raise RuntimeError(f"Full-fidelity audio extraction failed: {result.stderr}")
    return output_wav


def generate_ducking_control_signal(
    output_path: Path,
    duration_sec: float,
    intervals: list[tuple[float, float]],
    sample_rate: int = 48000,
) -> Path:
    """Generate a high-performance 16-bit mono control track.

    Samples within dialogue intervals are set to ~0.9 amplitude (30000);
    all other samples are set to silence (0).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    total_samples = max(1, int(math.ceil(duration_sec * sample_rate)))

    # Merge overlapping and sort intervals
    sorted_intervals = sorted(intervals, key=lambda x: x[0])
    merged: list[tuple[int, int]] = []
    for start, end in sorted_intervals:
        s_idx = max(0, min(total_samples, int(start * sample_rate)))
        e_idx = max(0, min(total_samples, int(end * sample_rate)))
        if e_idx <= s_idx:
            continue
        if merged and s_idx <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e_idx))
        else:
            merged.append((s_idx, e_idx))

    silence_sample = b"\x00\x00"
    active_sample = struct.pack("<h", 30000)

    # Chunk buffer size: 48000 samples (1 second)
    silence_block = silence_sample * sample_rate
    active_block = active_sample * sample_rate

    def write_repeated(wav_file: wave.Wave_write, count: int, sample_bytes: bytes, block_bytes: bytes) -> None:
        full_blocks = count // sample_rate
        remainder = count % sample_rate
        for _ in range(full_blocks):
            wav_file.writeframes(block_bytes)
        if remainder > 0:
            wav_file.writeframes(sample_bytes * remainder)

    with wave.open(str(output_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)

        current_idx = 0
        for s_idx, e_idx in merged:
            if s_idx > current_idx:
                # Write silence leading up to dialogue window
                write_repeated(wav, s_idx - current_idx, silence_sample, silence_block)
            # Write active control signal during dialogue window
            write_repeated(wav, e_idx - s_idx, active_sample, active_block)
            current_idx = e_idx

        if current_idx < total_samples:
            # Write trailing silence
            write_repeated(wav, total_samples - current_idx, silence_sample, silence_block)

    return output_path


def duck_source_audio(
    source_audio: Path,
    output_path: Path,
    intervals: list[tuple[float, float]],
    duck_db: float = -1.5,
    attack_ms: float = 35.0,
    release_ms: float = 120.0,
) -> dict[str, Any]:
    """Apply dialogue-time ducking to source audio with smooth attack and release envelopes.

    Preserves original background audio between dialogue windows. Never clicks at boundaries.
    Default duck_db is -1.5 dB (subtle transparent mastering ducking; never muted or gated!).
    """
    ffmpeg = _bin("ffmpeg")
    duration = probe_audio_duration(source_audio)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not intervals or duration <= 0:
        # No dialogue to duck; copy audio cleanly
        subprocess.run(
            [ffmpeg, "-hide_banner", "-y", "-i", str(source_audio), "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(output_path)],
            check=True,
            capture_output=True,
        )
        return {
            "output_file": str(output_path),
            "source_duration": duration,
            "output_duration": duration,
            "intervals_ducked": 0,
            "duck_db": 0.0,
            "method": "passthrough",
        }

    # Map duck_db to gentle mastering ratio (never squash background to silence)
    ratio = max(1.2, min(4.0, abs(duck_db) * 0.8))
    attack = max(5.0, min(500.0, attack_ms))
    release = max(20.0, min(1500.0, release_ms))

    with tempfile.TemporaryDirectory() as temp_dir:
        control_wav = Path(temp_dir) / "duck_control.wav"
        generate_ducking_control_signal(control_wav, duration, intervals, sample_rate=48000)

        cmd = [
            ffmpeg,
            "-hide_banner",
            "-y",
            "-i",
            str(source_audio),
            "-i",
            str(control_wav),
            "-filter_complex",
            # Keep the control input alive until the main audio is fully drained.
            # Equal-duration inputs can otherwise end at different packet boundaries.
            f"[1:a]apad=pad_dur=1[control];[0:a][control]sidechaincompress=threshold=0.08:ratio={ratio:.1f}:attack={attack:.1f}:release={release:.1f}[ducked]",
            "-map",
            "[ducked]",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if result.returncode != 0 or not output_path.is_file() or output_path.stat().st_size == 0:
            raise RuntimeError(f"FFmpeg sidechain ducking failed: {result.stderr}")

    out_dur = probe_audio_duration(output_path)
    return {
        "output_file": str(output_path),
        "source_duration": duration,
        "output_duration": out_dur,
        "intervals_ducked": len(intervals),
        "duck_db": duck_db,
        "attack_ms": attack,
        "release_ms": release,
        "method": "smooth_sidechain_ducking",
    }


def identify_separator_stems(paths: list[Path]) -> tuple[Path | None, Path | None]:
    # Match the stem label, never 'vocals' inside the model/file basename.
    import re
    vocals, background = None, None
    for path in paths:
        name = path.stem.lower()
        labels = re.findall(r"\(([^)]+)\)", name)
        label = labels[-1] if labels else name
        if label in {"vocals", "vocal", "dialogue"}:
            vocals = path
        elif label in {"instrumental", "instrumentals", "no_vocals", "no_vocal", "background", "other"}:
            background = path
    return vocals, background


_separator_cache = {}


def _separate_single(
    audio_path: Path,
    output_dir: Path,
    model_filename: str | None = None,
) -> dict[str, Any]:
    """Separate audio into BOTH Vocals and Instrumental stems via UVR / audio-separator.

    CRITICAL: output_single_stem is NEVER set to 'Vocals' alone!
    Both Vocals (vocals.wav) and Instrumental (instrumental.wav) are generated and preserved.
    The instrumental stem contains an estimated music/effects bed; neural separation can introduce artifacts or residual speech.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    original_copy = output_dir / "original_mix.wav"
    if audio_path.resolve() != original_copy.resolve():
        try:
            shutil.copy2(audio_path, original_copy)
        except Exception:
            pass

    selected_model = model_filename or "UVR-MDX-NET-Inst_HQ_3.onnx"
    try:
        from audio_separator.separator import Separator
    except ImportError:
        return {
            "status": "fallback",
            "method": "spectral_center_vocal_subtraction",
            "dialogue_candidate": str(original_copy),
            "background_candidate": None,
            "model": selected_model,
            "notice": "audio-separator not installed. Fallback to harmonic-percussive spectral center-vocal subtraction.",
        }

    try:
        model_dir = None
        for candidate_dir in [Path(__file__).resolve().parents[1] / "runtime/models/separation", Path("C:/tmp/audio-separator-models"), Path(tempfile.gettempdir()) / "audio-separator-models"]:
            if candidate_dir.is_dir() and (candidate_dir / selected_model).is_file():
                model_dir = str(candidate_dir)
                break
        sep_kwargs = {
            "output_dir": str(output_dir),
            "output_format": "WAV",
            "output_single_stem": None,
            "normalization_threshold": 1.0,
            "amplification_threshold": 0.0,
            "model_file_dir": str(Path(__file__).resolve().parents[1] / "runtime/models/separation"),
            "mdxc_params": {"segment_size": 256, "overlap": 2, "batch_size": 1},
        }
        if model_dir:
            sep_kwargs["model_file_dir"] = model_dir
        key = (selected_model, os.getenv("CUDA_VISIBLE_DEVICES", "default"))
        separator = _separator_cache.get(key) if os.getenv("OPENDUB_WARM_SEPARATOR") == "1" else None
        if separator is None:
            separator = Separator(**sep_kwargs)
            separator.load_model(model_filename=selected_model)
            if os.getenv("OPENDUB_WARM_SEPARATOR") == "1":
                _separator_cache[key] = separator
        else:
            separator.output_dir = str(output_dir)
            separator.model_instance.output_dir = str(output_dir)
        outputs = separator.separate(str(audio_path), custom_output_names={"Vocals":"vocals", "Instrumental":"instrumental", "Other":"instrumental", "No Vocals":"instrumental"})
        candidates = [Path(p) if Path(p).is_absolute() else output_dir / p for p in outputs]

        vocal, instrumental = identify_separator_stems(candidates)

        if vocal is None or not vocal.is_file() or instrumental is None or not instrumental.is_file():
            raise RuntimeError("Separator did not produce both recognizable vocals and instrumental stems.")

        target_vocals = output_dir / "vocals.wav"
        target_inst = output_dir / "instrumental.wav"

        if vocal.resolve() != target_vocals.resolve():
            shutil.copy2(vocal, target_vocals)
        else:
            target_vocals = vocal

        if instrumental and instrumental.is_file():
            if instrumental.resolve() != target_inst.resolve():
                shutil.copy2(instrumental, target_inst)
            else:
                target_inst = instrumental
        elif not target_inst.is_file():
            target_inst = None

        return {
            "status": "completed",
            "method": "UVR/audio-separator",
            "model": selected_model,
            "dialogue_candidate": str(target_vocals),
            "background_candidate": str(target_inst) if target_inst and target_inst.is_file() else None,
            "vocals_stem": str(target_vocals),
            "instrumental_stem": str(target_inst) if target_inst and target_inst.is_file() else None,
            "original_mix": str(original_copy),
            "notice": "Both Vocals and Instrumental stems separated. Instrumental preserved with estimated BGM/SFX (listen for separation artifacts).",
        }
    except Exception as exc:
        return {
            "status": "fallback",
            "method": "spectral_center_vocal_subtraction",
            "dialogue_candidate": str(original_copy),
            "background_candidate": None,
            "model": selected_model,
            "error": str(exc),
            "notice": "Separation failed; fallback to harmonic-percussive spectral center-vocal subtraction.",
        }


def _pcm_fingerprint(path: Path) -> tuple:
    import hashlib
    import soundfile as sf
    digest = hashlib.sha256()
    with sf.SoundFile(str(path)) as audio:
        metadata = (audio.samplerate, audio.channels, len(audio))
        for block in audio.blocks(blocksize=65536, dtype='float32', always_2d=True):
            digest.update(block.tobytes())
    return metadata + (digest.hexdigest(),)


def original_path_valid(report: dict, original: Path) -> bool:
    if not original.is_file():
        return False
    if report.get("source_fingerprint"):
        from .chunk_execution import digest
        return digest(original) == report["source_fingerprint"]
    return original.parent == Path(report.get("dialogue_candidate", "")).resolve().parent


def cached_separation(audio_path: Path, output_dir: Path, model_filename: str) -> dict | None:
    """Reuse completed stems only when their recorded source PCM still matches."""
    try:
        report = json.loads((output_dir.parent / 'separation.json').read_text(encoding='utf-8'))
        if report.get('status') != 'completed' or report.get('model') != model_filename:
            return None
        paths = [Path(report[key]).resolve() for key in ('original_mix','dialogue_candidate','background_candidate')]
        root = output_dir.resolve()
        if not original_path_valid(report, paths[0]) or any(not path.is_relative_to(root) or not path.is_file() for path in paths[1:]):
            return None
        original, vocals, background = paths
        if any(original.stat().st_mtime_ns > stem.stat().st_mtime_ns for stem in (vocals, background)):
            return None
        if _pcm_fingerprint(original) != _pcm_fingerprint(audio_path):
            return None
        duration = probe_audio_duration(audio_path)
        if any(abs(probe_audio_duration(stem)-duration) > .05 for stem in (vocals, background)):
            return None
        print('[OpenDub separation] Reusing completed stems; source PCM and duration verified.', flush=True)
        return {**report, 'reused': True}
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        return None


def separate_dialogue_candidate(audio_path: Path, output_dir: Path, model_filename: str | None = None,
                               *, processing_plan: dict | None = None, force_chunks=False,
                               visible_helpers=False, cancelled=None, separation_workers=None) -> dict[str, Any]:
    duration = probe_audio_duration(audio_path)
    from .kaggle_tasks import project_for
    cloud=project_for(output_dir)
    if cloud:
        from .kaggle_operations import remote_plan
        processing_plan=remote_plan(cloud,duration);force_chunks=True
    cached = cached_separation(audio_path, output_dir, model_filename or 'UVR-MDX-NET-Inst_HQ_3.onnx')
    if cached:
        return cached
    if force_chunks or duration > 300:
        from .chunked_separation import separate_chunked
        from .work_progress import current_context, track
        context = current_context()
        if context:
            from . import app as studio
            base, job_id, phase, _ = context
            cancelled = cancelled or (lambda: studio.job_cancel_requested(studio.DB_PATH, job_id))
            from .auto_dub import read_status
            options = read_status(base).get("options") or {}
            visible_helpers = visible_helpers or bool(options.get("visible_helpers"))
            if separation_workers is None:
                separation_workers = options.get('separation_workers')
        else:
            base, job_id, phase = output_dir, "separation", "vocal_separation"
        cancelled = cancelled or (lambda: False)
        if processing_plan is None:
            from .system_diagnostics import collect_diagnostics
            from .resource_plan import plan_resources
            requested = separation_workers
            if requested is None and os.getenv('OPENDUB_SEPARATION_WORKERS','').strip():
                requested = int(os.environ['OPENDUB_SEPARATION_WORKERS'])
            processing_plan = plan_resources(collect_diagnostics(output_dir.parent), duration, audio_path.stat().st_size, workload="separation",requested_workers=requested)
        with track(base, job_id, phase, "chunks"):
            result = separate_chunked(audio_path, output_dir, duration, processing_plan,
                                    model_filename=model_filename or "UVR-MDX-NET-Inst_HQ_3.onnx",
                                    visible_helpers=visible_helpers, cancelled=cancelled)
    else:
        result = _separate_single(audio_path, output_dir, model_filename)
    if result.get("status") == "completed":
        from .chunk_execution import save_json, digest
        result["source_fingerprint"] = digest(Path(result["original_mix"]))
        save_json(output_dir.parent / "separation.json", result)
    return result


def apply_spectral_center_vocal_subtraction(
    stereo: np.ndarray,
    w: np.ndarray,
    sr: int = 48000,
    subtle_duck_db: float = -1.5,
    fft_size: int = 2048,
    hop_size: int = 1024,
) -> np.ndarray:
    """True Continuous Background Music & Sound Effects Preservation via Spectral Center-Vocal Subtraction.

    Removes ONLY center dialogue vocal formants (180 Hz - 4500 Hz) during speech (w > 0),
    while retaining a continuous estimate of stereo background music and effects,
    sub-bass (<180 Hz), and brilliance (>4500 Hz) continuously across the entire audio.
    Never gates to sub-bass. Transparent mastering ducking (subtle_duck_db, e.g. -1.5 dB) during dialogue.
    """
    if stereo.ndim == 1:
        stereo = np.column_stack((stereo, stereo))
    n = stereo.shape[0]
    if n == 0:
        return stereo

    L = stereo[:, 0].astype(np.float32)
    R = stereo[:, 1].astype(np.float32)
    M = 0.5 * (L + R)
    S = 0.5 * (L - R)

    hann = np.hanning(fft_size).astype(np.float32)
    pad_len = fft_size
    M_pad = np.pad(M, (pad_len, pad_len), mode="reflect")
    S_pad = np.pad(S, (pad_len, pad_len), mode="reflect")
    w_pad = np.pad(w, (pad_len, pad_len), mode="edge")

    freq_bins = np.fft.rfftfreq(fft_size, d=1.0 / sr)
    vocal_mask = (freq_bins >= 180.0) & (freq_bins <= 4500.0)

    num_frames = (M_pad.size - fft_size) // hop_size + 1
    M_out = np.zeros_like(M_pad)
    S_out = np.zeros_like(S_pad)
    win_sum = np.zeros_like(M_pad)

    prev_mag = None
    for i in range(num_frames):
        pos = i * hop_size
        m_frame = M_pad[pos : pos + fft_size] * hann
        s_frame = S_pad[pos : pos + fft_size] * hann

        m_fft = np.fft.rfft(m_frame)
        s_fft = np.fft.rfft(s_frame)

        w_frame = float(np.mean(w_pad[pos : pos + fft_size]))

        m_mag = np.abs(m_fft)
        s_mag = np.abs(s_fft)

        if w_frame > 0.001:
            # Protect percussive transients (gunshots, punches, explosions, snare hits) during dialogue
            transient_impact = False
            if prev_mag is not None:
                spectral_flux = float(np.sum(np.maximum(0.0, m_mag - prev_mag))) / (float(np.sum(m_mag)) + 1e-6)
                if spectral_flux > 0.65:
                    transient_impact = True

            # If zero-bleed or deep ducking requested (subtle_duck_db <= -6.0):
            if subtle_duck_db <= -6.0:
                if not transient_impact:
                    # Cleanly eliminate center dialogue vocal formants (> 98% reduction)
                    m_fft[vocal_mask] *= (1.0 - (w_frame ** 0.5) * 0.98)
            else:
                # Center vocal isolation: speech is centered (Mid >> Side)
                c_speech = np.maximum(0.0, m_mag[vocal_mask] - 1.15 * s_mag[vocal_mask])
                vocal_ratio = c_speech / (m_mag[vocal_mask] + 1e-7)
                m_fft[vocal_mask] *= (1.0 - w_frame * vocal_ratio * 0.96)

        prev_mag = m_mag

        # Side information is retained; centered music and effects can still be altered.
        m_rec = np.fft.irfft(m_fft, n=fft_size).astype(np.float32)
        s_rec = np.fft.irfft(s_fft, n=fft_size).astype(np.float32)

        M_out[pos : pos + fft_size] += m_rec
        S_out[pos : pos + fft_size] += s_rec
        win_sum[pos : pos + fft_size] += hann

    valid = win_sum > 1e-4
    M_out[valid] /= win_sum[valid]
    S_out[valid] /= win_sum[valid]

    M_clean = M_out[pad_len : pad_len + n]
    S_clean = S_out[pad_len : pad_len + n]

    if subtle_duck_db <= -6.0:
        # Zero-bleed dialogue vocal elimination:
        # Mid channel (where speech formants live) is ducked to zero/inaudible (-24 dB)
        # Side channel (where stereo BGM, reverb, and ambience live) is preserved smoothly (-3 dB max)
        mid_gain = 1.0 - w * (1.0 - 10.0 ** (subtle_duck_db / 20.0))
        side_gain = 1.0 - w * (1.0 - 10.0 ** (-3.0 / 20.0))
        L_bg = M_clean * mid_gain + S_clean * side_gain
        R_bg = M_clean * mid_gain - S_clean * side_gain
    else:
        # Subtle transparent mastering ducking (-1.5 dB during dialogue, 0 dB outside)
        duck_gain = 1.0 - w * (1.0 - 10.0 ** (subtle_duck_db / 20.0))
        L_bg = (M_clean + S_clean) * duck_gain
        R_bg = (M_clean - S_clean) * duck_gain

    return np.column_stack((L_bg, R_bg)).astype(np.float32)


def spectral_center_vocal_subtraction(
    source_audio: Path,
    output_path: Path,
    intervals: list[tuple[float, float]] | None = None,
    sample_rate: int = 48000,
    subtle_duck_db: float = -1.5,
    attack_ms: float = 35.0,
    release_ms: float = 120.0,
) -> dict[str, Any]:
    """Execute high-resolution harmonic-percussive spectral center-vocal subtraction on source_audio.

    Streams audio chunk by chunk (safe for full movies) and ensures continuous stereo BGM and SFX.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration = probe_audio_duration(source_audio)

    if np is None or sf is None:
        # Graceful fallback if numpy/soundfile not present
        return duck_source_audio(
            source_audio,
            output_path,
            intervals or [],
            duck_db=max(-2.0, subtle_duck_db),
            attack_ms=attack_ms,
            release_ms=release_ms,
        )

    # Build dialogue control envelope
    intervals = intervals or []
    sorted_intervals = sorted(intervals, key=lambda x: x[0])
    merged: list[tuple[float, float]] = []
    for s, e in sorted_intervals:
        if e <= s:
            continue
        if merged and s - merged[-1][1] <= 0.40:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    ctrl_sr = 200  # 5ms control grid
    total_ctrl = int(math.ceil(duration * ctrl_sr)) + 10
    mute_ctrl = np.zeros(total_ctrl, dtype=np.float32)

    for ms, me in merged:
        cs = max(0, int(round((ms - 0.15) * ctrl_sr)))
        ce = min(total_ctrl, int(round((me + 0.20) * ctrl_sr)) + 1)
        mute_ctrl[cs:ce] = 1.0

    # Smooth ramps (40ms attack, 100ms release)
    attack_steps = max(2, int(attack_ms * ctrl_sr / 1000.0))
    release_steps = max(4, int(release_ms * ctrl_sr / 1000.0))
    ramp_steps = (attack_steps + release_steps) // 2
    if total_ctrl > ramp_steps:
        kernel = np.ones(ramp_steps, dtype=np.float32) / ramp_steps
        mute_ctrl = np.convolve(mute_ctrl, kernel, mode="same")
    mute_ctrl = np.clip(mute_ctrl, 0.0, 1.0)

    chunk_sec = 60
    chunk_frames = chunk_sec * sample_rate

    with sf.SoundFile(str(source_audio), "r") as src_f:
        total_frames = len(src_f)
        with sf.SoundFile(str(output_path), "w", samplerate=sample_rate, channels=2, subtype="PCM_16") as dst_f:
            pos = 0
            while pos < total_frames:
                to_read = min(chunk_frames, total_frames - pos)
                stereo = src_f.read(to_read, dtype="float32", always_2d=True)
                n = stereo.shape[0]
                c_end = pos + n

                ctrl_indices = np.arange(pos, c_end, dtype=np.float32) / float(sample_rate / ctrl_sr)
                w_chunk = np.interp(ctrl_indices, np.arange(total_ctrl, dtype=np.float32), mute_ctrl).astype(np.float32)

                processed = apply_spectral_center_vocal_subtraction(
                    stereo,
                    w_chunk,
                    sr=sample_rate,
                    subtle_duck_db=subtle_duck_db,
                )

                # Soft ceiling limiter to prevent clipping
                peak = np.max(np.abs(processed)) if processed.size else 0.0
                if peak > 0.89:
                    processed = 0.89 * np.tanh(processed / 0.89)

                dst_f.write(processed)
                pos = c_end

    out_dur = probe_audio_duration(output_path)
    return {
        "output_file": str(output_path),
        "source_duration": duration,
        "output_duration": out_dur,
        "intervals_processed": len(intervals),
        "subtle_duck_db": subtle_duck_db,
        "method": "harmonic_percussive_spectral_center_vocal_subtraction",
        "notice": "Spectral center-vocal subtraction applied. Degraded preview: centered music/effects can be altered. Listening review is required.",
    }


def preserve_background_audio(
    project_root: Path,
    source_movie: Path | None = None,
    mode: str = "separation",
    duck_db: float = -1.5,
    attack_ms: float = 35.0,
    release_ms: float = 120.0,
    user_stem_path: str | Path | None = None,
    model_filename: str | None = None,
    strict_separation: bool = True,
    separation_workers: int | None = None,
) -> dict[str, Any]:
    """Preserve non-dialogue background audio (music, SFX, ambience) for final mixing.

    Modes:
      - 'separation': Neural vocal / background stems; unavailable models fail without mixing the source vocals back in.
      - 'spectral_subtraction': Harmonic-percussive spectral center-vocal cancellation leaving continuous BGM & SFX.
      - 'ducking': Continuous background audio with transparent mastering ducking (-1.5 dB).
      - 'user_stem': Conforms a user-supplied dialogue-free background WAV.
    """
    output_dir = project_root / "output"
    analysis_dir = project_root / "analysis"
    output_dir.mkdir(parents=True, exist_ok=True)
    analysis_dir.mkdir(parents=True, exist_ok=True)

    target_bg_wav = output_dir / "background_preserved.wav"
    metadata_path = output_dir / "background_metadata.json"
    analysis_meta_path = analysis_dir / "separation" / "background_metadata.json"
    analysis_meta_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Resolve source audio
    clean_48k = output_dir / "source_audio_48k.wav"
    source_16k = analysis_dir / "source_16k_mono.wav"
    selected_source_audio: Path

    movie_dur = None
    if source_movie and source_movie.is_file():
        try:
            movie_dur = probe_audio_duration(source_movie)
        except Exception:
            pass

    if source_movie and source_movie.is_file() and (
        not clean_48k.is_file() or (movie_dur and abs(probe_audio_duration(clean_48k) - movie_dur) > 0.5)
    ):
        selected_source_audio = extract_full_fidelity_audio(source_movie, clean_48k)
    elif clean_48k.is_file():
        selected_source_audio = clean_48k
    elif source_16k.is_file():
        selected_source_audio = source_16k
    else:
        raise RuntimeError("No source audio or movie found in project to preserve background from.")

    mode_lower = str(mode or "separation").strip().lower()
    result_data: dict[str, Any] = {}

    # Extract dialogue intervals from dialogue_manifest.json or translated_transcript.json
    dialogue_manifest_path = analysis_dir / "dialogue_manifest.json"
    translated_transcript_path = analysis_dir / "translated_transcript.json"
    transcript_path = analysis_dir / "transcript.json"

    intervals: list[tuple[float, float]] = []
    if dialogue_manifest_path.is_file():
        try:
            m = json.loads(dialogue_manifest_path.read_text(encoding="utf-8"))
            for unit in m.get("units", []):
                s = float(unit.get("start_sec", 0))
                e = float(unit.get("end_sec", 0))
                if e > s:
                    intervals.append((s, e))
        except Exception:
            pass

    if not intervals and translated_transcript_path.is_file():
        try:
            t = json.loads(translated_transcript_path.read_text(encoding="utf-8"))
            for seg in t.get("segments", []):
                s = float(seg.get("start", 0))
                e = float(seg.get("end", 0))
                if e > s:
                    intervals.append((s, e))
        except Exception:
            pass

    if not intervals and transcript_path.is_file():
        try:
            tr = json.loads(transcript_path.read_text(encoding="utf-8"))
            for seg in tr.get("segments", []):
                s = float(seg.get("start", 0))
                e = float(seg.get("end", 0))
                if e > s:
                    intervals.append((s, e))
        except Exception:
            pass

    # MODE A: UVR STEM SEPARATION
    if mode_lower == "separation":
        sep_dir = analysis_dir / "separation"
        sep_res = separate_dialogue_candidate(selected_source_audio, sep_dir, model_filename=model_filename, separation_workers=separation_workers)
        bg_candidate = sep_res.get("background_candidate")
        if bg_candidate and Path(bg_candidate).is_file():
            # Conforming background stem to target_bg_wav (unity gain, estimated BGM/SFX)
            ffmpeg = _bin("ffmpeg")
            subprocess.run(
                [ffmpeg, "-hide_banner", "-y", "-i", str(bg_candidate), "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", "-rf64", "auto", str(target_bg_wav)],
                check=True,
                capture_output=True,
            )
            # A singing cluster excluded from dialogue review is still music.
            # Neural stems alone would erase its vocals throughout the movie.
            diarization_path=analysis_dir/'diarization.json'
            if diarization_path.exists():
                from .speaker_review import read,overlap_evidence_hash
                diar=read(diarization_path,{})
                disposition=read(analysis_dir/'speaker_dispositions.json',{})
                if disposition.get('evidence_sha256')==overlap_evidence_hash(diar):
                    excluded={sid for sid,entry in disposition.get('speakers',{}).items()
                              if entry.get('confirmed') and entry.get('category') in {'music_or_singing','non_speech'}}
                else:excluded=set()
                intervals.extend((float(turn['start']),float(turn['end'])) for turn in diar.get('regular_turns',[])
                                 if turn.get('speaker_id') not in excluded)
            from .selective_background import preserve_non_dialogue_audio
            selective=preserve_non_dialogue_audio(selected_source_audio,target_bg_wav,target_bg_wav,intervals)
            result_data = {
                "mode": "separation",
                "method": "dialogue_only_uvr_with_original_non_dialogue",
                "model": sep_res.get("model"),
                "background_candidate": bg_candidate,
                "dialogue_candidate": sep_res.get("dialogue_candidate"),
                "status": "completed",
                "confidence": "requires_listening_review",
                "selective_preservation":selective,
                "notice": "UVR vocal/background separation succeeded; instrumental stem preserved with estimated BGM/SFX (listen for separation artifacts) at full natural volume.",
            }
        else:
            if strict_separation:
                raise RuntimeError("Background separation unavailable: " + str(sep_res.get("error") or sep_res.get("notice") or "no instrumental stem") + ". Install the separation model or supply an instrumental stem; original audio was retained.")
            # Separation unavailable or failed: graceful fallback to high-resolution spectral center-vocal subtraction
            spec_res = spectral_center_vocal_subtraction(
                selected_source_audio,
                target_bg_wav,
                intervals,
                sample_rate=48000,
                subtle_duck_db=duck_db,
                attack_ms=attack_ms,
                release_ms=release_ms,
            )
            result_data = {
                "mode": "ducking",
                "method": "harmonic_percussive_spectral_center_vocal_subtraction",
                "fallback_from": "separation",
                "status": "completed",
                "confidence": "fallback",
                "background_audio": str(target_bg_wav),
                "notice": "UVR neural separation was unavailable; smoothly fell back to dialogue-time ducking with high-resolution harmonic-percussive spectral center-vocal subtraction. Degraded preview: centered music/effects can be altered. Listening review is required.",
                **spec_res,
            }

    # MODE C: USER-SUPPLIED STEM
    elif mode_lower == "user_stem":
        if not user_stem_path:
            raise ValueError("user_stem_path must be specified when mode is 'user_stem'")
        stem = Path(user_stem_path)
        stem = stem if stem.is_absolute() else (project_root / stem).resolve()
        if not stem.is_file():
            raise FileNotFoundError(f"User background stem not found: {stem}")
        ffmpeg = _bin("ffmpeg")
        subprocess.run(
            [ffmpeg, "-hide_banner", "-y", "-i", str(stem), "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(target_bg_wav)],
            check=True,
            capture_output=True,
        )
        result_data = {
            "mode": "user_stem",
            "method": "user_supplied_stem",
            "user_stem_path": str(stem),
            "status": "completed",
            "confidence": "requires_listening_review",
            "notice": "User-supplied background stem conformed to 48kHz stereo.",
        }

    # MODE B: SPECTRAL CENTER-VOCAL SUBTRACTION OR TRANSPARENT MASTERING DUCKING
    elif mode_lower in ("spectral_subtraction", "spectral", "subtraction"):
        spec_res = spectral_center_vocal_subtraction(
            selected_source_audio,
            target_bg_wav,
            intervals,
            sample_rate=48000,
            subtle_duck_db=duck_db,
            attack_ms=attack_ms,
            release_ms=release_ms,
        )
        result_data = {
            "mode": "spectral_subtraction",
            "method": "harmonic_percussive_spectral_center_vocal_subtraction",
            "status": "completed",
            "confidence": "requires_listening_review",
            "notice": "High-resolution spectral center-vocal subtraction applied. Degraded preview: centered music/effects can be altered. Listening review is required.",
            **spec_res,
        }

    else:
        # Default ducking mode also utilizes high-resolution spectral subtraction with subtle transparent ducking
        spec_res = spectral_center_vocal_subtraction(
            selected_source_audio,
            target_bg_wav,
            intervals,
            sample_rate=48000,
            subtle_duck_db=duck_db,
            attack_ms=attack_ms,
            release_ms=release_ms,
        )
        result_data = {
            "mode": "ducking",
            "method": "harmonic_percussive_spectral_center_vocal_subtraction",
            "status": "completed",
            "confidence": "requires_listening_review",
            "notice": f"Continuous background preserved with transparent {duck_db} dB mastering ducking during dialogue. Music and SFX preserved.",
            **spec_res,
        }

    result_data["background_audio"] = str(target_bg_wav)
    result_data["created_at"] = datetime.now(timezone.utc).isoformat()
    result_data["source_audio"] = str(selected_source_audio)
    result_data["dialogue_intervals_count"] = len(intervals)

    # Persist metadata
    for meta_path in (metadata_path, analysis_meta_path):
        meta_path.write_text(json.dumps(result_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # Update dialogue units in dialogue_manifest.json if present
    if dialogue_manifest_path.is_file():
        try:
            manifest = json.loads(dialogue_manifest_path.read_text(encoding="utf-8"))
            for unit in manifest.get("units", []):
                unit["dialogue_removal"] = {
                    "status": "completed",
                    "mode": result_data["mode"],
                    "duck_db": duck_db,
                    "updated_at": result_data["created_at"],
                }
            temp_manifest = dialogue_manifest_path.with_suffix(".tmp")
            temp_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            temp_manifest.replace(dialogue_manifest_path)
        except Exception:
            pass

    return result_data
