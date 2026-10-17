from __future__ import annotations

import array
import json
import math
import re
import shutil
import subprocess
import tempfile
import wave
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .atomic_files import publish_audio_revision

from .background_preservation import (
    duck_source_audio,
    preserve_background_audio,
    probe_audio_duration,
)


def run_ffmpeg(args: list[str], timeout: int = 7200) -> None:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("FFmpeg not found on PATH")
    p = subprocess.run([exe, "-hide_banner", "-y", *args], capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError((p.stderr or "FFmpeg failed")[-3000:])


def atempo_chain(rate: float) -> str:
    rate = max(0.25, min(4.0, rate))
    parts = []
    while rate < 0.5:
        parts.append("atempo=0.5")
        rate /= 0.5
    while rate > 2.0:
        parts.append("atempo=2.0")
        rate /= 2.0
    parts.append(f"atempo={rate:.6f}")
    return ",".join(parts)


def is_rubberband_available() -> bool:
    exe = shutil.which("ffmpeg")
    if not exe:
        return False
    try:
        p = subprocess.run([exe, "-filters"], capture_output=True, text=True, timeout=5, errors="replace")
        return "rubberband" in (p.stdout or "")
    except Exception:
        return False


def _probe_wav_stdlib(path: Path) -> tuple[float, int, int, int]:
    """Return (duration_sec, sample_rate, channels, frame_count) for a PCM WAV using standard library."""
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        ch = wf.getnchannels()
        nframes = wf.getnframes()
        if sr <= 0:
            raise ValueError("Invalid WAV sample rate")
        return nframes / float(sr), sr, ch, nframes


def measure_and_trim_wav_silence(
    src: Path,
    out: Path | None = None,
    threshold_db: float = -42.0,
    window_ms: float = 10.0,
    pad_ms: float = 15.0,
) -> dict[str, Any]:
    """Measure genuine leading/trailing silence in a 16-bit PCM WAV and optionally write trimmed WAV.

    Never clips spoken syllables: preserves a configurable safety pad around first/last active window.
    """
    with wave.open(str(src), "rb") as wf:
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        sr = wf.getframerate()
        nframes = wf.getnframes()
        raw = wf.readframes(nframes)

    if sw != 2 or sr <= 0 or nframes <= 0:
        dur = nframes / float(sr) if sr > 0 else 0.0
        if out and out != src:
            shutil.copy2(src, out)
        return {
            "source_duration": dur,
            "trimmed_duration": dur,
            "leading_silence_duration": 0.0,
            "trailing_silence_duration": 0.0,
        }

    samples = array.array("h")
    samples.frombytes(raw)
    win_frames = max(1, int(sr * (window_ms / 1000.0)))
    thresh_amp = 32768.0 * (10.0 ** (threshold_db / 20.0))

    first_active_frame = 0
    last_active_frame = nframes
    found_speech = False

    total_windows = max(1, (nframes + win_frames - 1) // win_frames)
    for w_idx in range(total_windows):
        f_start = w_idx * win_frames
        f_end = min(nframes, f_start + win_frames)
        s_start = f_start * ch
        s_end = f_end * ch
        window_slice = samples[s_start:s_end]
        if not window_slice:
            continue
        rms = math.sqrt(sum(float(x) * float(x) for x in window_slice) / len(window_slice))
        if rms >= thresh_amp:
            if not found_speech:
                first_active_frame = f_start
                found_speech = True
            last_active_frame = f_end

    if not found_speech:
        dur = nframes / float(sr)
        if out and out != src:
            shutil.copy2(src, out)
        return {
            "source_duration": dur,
            "trimmed_duration": dur,
            "leading_silence_duration": 0.0,
            "trailing_silence_duration": 0.0,
        }

    pad_frames = int(sr * (pad_ms / 1000.0))
    trim_start = max(0, first_active_frame - pad_frames)
    trim_end = min(nframes, last_active_frame + pad_frames)
    if trim_end <= trim_start:
        trim_start, trim_end = 0, nframes

    lead_sec = trim_start / float(sr)
    trail_sec = (nframes - trim_end) / float(sr)
    trimmed_sec = (trim_end - trim_start) / float(sr)

    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        trimmed_samples = samples[trim_start * ch : trim_end * ch]
        with wave.open(str(out), "wb") as wf_out:
            wf_out.setnchannels(ch)
            wf_out.setsampwidth(2)
            wf_out.setframerate(sr)
            wf_out.writeframes(trimmed_samples.tobytes())

    return {
        "source_duration": nframes / float(sr),
        "trimmed_duration": trimmed_sec,
        "leading_silence_duration": lead_sec,
        "trailing_silence_duration": trail_sec,
    }


def _timestretch_wav_stdlib(src: Path, out: Path, tempo: float, target_sr: int = 48000) -> dict[str, Any]:
    """Pure-Python WSOLA-style overlap-add time-stretching fallback for 16-bit PCM WAV files.

    Preserves pitch and spoken content without any speech truncation (`atrim`), outputting
    48 kHz stereo 16-bit PCM WAV when FFmpeg is unavailable in a sandboxed environment.
    """
    with wave.open(str(src), "rb") as wf:
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        sr = wf.getframerate()
        nframes = wf.getnframes()
        raw = wf.readframes(nframes)

    if sw != 2 or nframes == 0:
        raise RuntimeError("Pure-Python time-stretch requires 16-bit PCM WAV input.")

    samples = array.array("h")
    samples.frombytes(raw)
    # Convert to mono float array for clean overlap-add, then write stereo 48kHz
    if ch > 1:
        mono = [float(samples[i * ch]) for i in range(nframes)]
    else:
        mono = [float(x) for x in samples]

    # Resample to target_sr first if needed
    if sr != target_sr and sr > 0:
        new_len = max(1, int(round(len(mono) * target_sr / float(sr))))
        resampled = []
        ratio = (len(mono) - 1) / float(max(1, new_len - 1))
        for i in range(new_len):
            pos = i * ratio
            idx = int(pos)
            frac = pos - idx
            nxt = min(len(mono) - 1, idx + 1)
            resampled.append(mono[idx] * (1.0 - frac) + mono[nxt] * frac)
        mono = resampled

    in_len = len(mono)
    out_len = max(1, int(round(in_len / float(tempo))))
    win_size = int(0.030 * target_sr)  # 30ms Hann window
    hop_syn = win_size // 2
    hop_ana = hop_syn * tempo

    out_buf = [0.0] * (out_len + win_size)
    norm_buf = [0.0] * (out_len + win_size)
    hann = [0.5 * (1.0 - math.cos(2.0 * math.pi * i / float(win_size - 1))) for i in range(win_size)]

    syn_pos = 0
    ana_pos = 0.0
    while syn_pos + win_size <= out_len + win_size // 2:
        a_idx = int(round(ana_pos))
        if a_idx >= in_len:
            break
        for i in range(win_size):
            src_i = a_idx + i
            val = mono[src_i] if src_i < in_len else 0.0
            w = hann[i]
            out_buf[syn_pos + i] += val * w
            norm_buf[syn_pos + i] += w
        syn_pos += hop_syn
        ana_pos += hop_ana

    stereo_pcm = array.array("h")
    for i in range(out_len):
        val = out_buf[i] / norm_buf[i] if norm_buf[i] > 1e-6 else 0.0
        clamped = max(-32767, min(32767, int(round(val))))
        stereo_pcm.append(clamped)
        stereo_pcm.append(clamped)

    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as wf_out:
        wf_out.setnchannels(2)
        wf_out.setsampwidth(2)
        wf_out.setframerate(target_sr)
        wf_out.writeframes(stereo_pcm.tobytes())

    return {
        "actual_fitted_duration": out_len / float(target_sr),
        "sample_rate": target_sr,
        "sample_count": out_len,
    }


def fit_audio(
    src: Path,
    out: Path,
    target: float,
    max_speedup: float = 1.25,
    max_slowdown: float = 0.82,
    use_rubberband: bool = True,
    trim_silence: bool = False,
    pad_short: bool = False,
) -> dict[str, Any]:
    from .kaggle_tasks import project_for
    if project_for(out):
        from .kaggle_operations import single_audio
        return single_audio('fit',src,out,{'target':target,'max_speedup':max_speedup,'max_slowdown':max_slowdown,
            'use_rubberband':use_rubberband,'trim_silence':trim_silence,'pad_short':pad_short})
    """Fit synthesized speech into a target window without destructive clipping (PRD §12 & §23).

    Priority order:
      1. Remove genuine leading silence (when trim_silence=True)
      2. Remove genuine trailing silence (when trim_silence=True)
      3. Calculate speech duration
      4. Use controlled time-stretch (Rubber Band -> FFmpeg atempo -> stdlib WSOLA)
      5. Flag semantic_compression_recommended if duration_fit_limited
      6. Never cut actual spoken words (`atrim` is strictly prohibited).
    """
    if target <= 0:
        raise ValueError("Durations must be positive")
    published = out
    out = out.with_name(f"{out.stem}.{uuid.uuid4().hex}.pending{out.suffix}")

    probe = shutil.which("ffprobe")
    ffmpeg_exe = shutil.which("ffmpeg")

    # Measure silence and optionally pre-trim
    silence_info = {
        "source_duration": 0.0,
        "trimmed_duration": 0.0,
        "leading_silence_duration": 0.0,
        "trailing_silence_duration": 0.0,
    }
    working_src = src
    temp_dir_obj = None

    try:
        if src.is_file() and src.suffix.lower() == ".wav":
            try:
                if trim_silence:
                    temp_dir_obj = tempfile.TemporaryDirectory()
                    trimmed_wav = Path(temp_dir_obj.name) / "trimmed.wav"
                    silence_info = measure_and_trim_wav_silence(src, out=trimmed_wav)
                    working_src = trimmed_wav
                else:
                    silence_info = measure_and_trim_wav_silence(src, out=None)
            except Exception:
                pass

        dur = 0.0
        if probe:
            p = subprocess.run(
                [probe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(working_src)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if p.returncode == 0 and p.stdout.strip():
                dur = float(p.stdout.strip())
        if dur <= 0:
            try:
                dur, _, _, _ = _probe_wav_stdlib(working_src)
            except Exception as exc:
                raise RuntimeError("Cannot probe segment duration") from exc

        if dur <= 0:
            raise ValueError("Durations must be positive")

        orig_dur = silence_info["source_duration"] if silence_info["source_duration"] > 0 else dur
        trimmed_dur = dur if trim_silence else orig_dur

        required = trimmed_dur / target
        applied = max(max_slowdown, min(max_speedup, required))
        duration_fit_limited = bool(required > applied + 0.005 or
                                    (not pad_short and required < applied - 0.005))

        out.parent.mkdir(parents=True, exist_ok=True)

        can_rubberband = bool(ffmpeg_exe) and use_rubberband and is_rubberband_available()
        if ffmpeg_exe:
            if can_rubberband:
                af_filter = f"rubberband=tempo={applied:.6f}:pitch=1.0:formant=preserved"
                engine = "rubberband"
            else:
                af_filter = atempo_chain(applied)
                engine = "atempo"

            # Audio fitting must NEVER use destructive atrim to chop speech content.
            run_ffmpeg(
                ["-i", str(working_src), "-af", af_filter, "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(out)],
                600,
            )
        else:
            engine = "stdlib_wsola"
            _timestretch_wav_stdlib(working_src, out, applied, target_sr=48000)

        actual_fitted_dur = trimmed_dur / applied
        sample_rate = 48000
        sample_count = int(round(actual_fitted_dur * sample_rate))
        if out.is_file() and out.suffix.lower() == ".wav":
            try:
                actual_fitted_dur, sample_rate, _, sample_count = _probe_wav_stdlib(out)
            except Exception:
                pass
        elif probe:
            p_out = subprocess.run(
                [probe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(out)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if p_out.returncode == 0 and p_out.stdout.strip():
                actual_fitted_dur = float(p_out.stdout.strip())
                sample_count = int(round(actual_fitted_dur * sample_rate))

        expected_fitted = trimmed_dur / applied
        math_reconciled = bool(abs(actual_fitted_dur - expected_fitted) <= 0.025)
        speech_content_duration = actual_fitted_dur
        silence_padding_sec = 0.0
        if pad_short and not duration_fit_limited and actual_fitted_dur < target:
            # Keep natural delivery; fill the remaining window without adding words.
            with wave.open(str(out), "rb") as reader:
                params = reader.getparams()
                audio = reader.readframes(reader.getnframes())
            target_frames = round(target * params.framerate)
            extra = max(0, target_frames - params.nframes)
            with wave.open(str(out), "wb") as writer:
                writer.setparams(params)
                writer.writeframes(audio)
                writer.writeframes(b"\0" * (extra * params.nchannels * params.sampwidth))
            silence_padding_sec = extra / params.framerate
            sample_count = params.nframes + extra
            actual_fitted_dur = sample_count / params.framerate
        if pad_short and actual_fitted_dur > target + 0.025:
            duration_fit_limited = True

        publish_audio_revision(out, published)
        return {
            "file": str(published),
            "source_duration": round(orig_dur, 6),
            "trimmed_duration": round(trimmed_dur, 6),
            "leading_silence_duration": round(silence_info.get("leading_silence_duration", 0.0), 6),
            "trailing_silence_duration": round(silence_info.get("trailing_silence_duration", 0.0), 6),
            "target_duration": target,
            "requested_tempo": required,
            "required_tempo": required,
            "applied_tempo": applied,
            "actual_fitted_duration": actual_fitted_dur,
            "speech_content_duration": speech_content_duration,
            "silence_padding_sec": silence_padding_sec,
            "sample_rate": sample_rate,
            "sample_count": sample_count,
            "math_reconciled": math_reconciled,
            "duration_fit_limited": duration_fit_limited,
            "semantic_compression_recommended": duration_fit_limited,
            "speech_truncated": False,
            "time_stretch_engine": engine,
        }
    finally:
        out.unlink(missing_ok=True)
        if temp_dir_obj is not None:
            temp_dir_obj.cleanup()


def normalize_audio(src: Path, out: Path, target_lufs: float = -16) -> dict[str, Any]:
    from .kaggle_tasks import project_for
    if project_for(out):
        from .kaggle_operations import single_audio
        return single_audio('normalize',src,out,{'target_lufs':target_lufs})
    temporary = out.with_name(f"{out.stem}.{uuid.uuid4().hex}.pending{out.suffix}")
    try:
        result = _normalize_audio(src, temporary, target_lufs)
        publish_audio_revision(temporary, out)
        result["file"] = str(out)
        return result
    finally:
        temporary.unlink(missing_ok=True)


def _normalize_audio(src: Path, out: Path, target_lufs: float = -16) -> dict[str, Any]:
    out.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("ffmpeg"):
        run_ffmpeg(
            ["-i", str(src), "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(out)],
            600,
        )
    elif src.is_file() and src.suffix.lower() == ".wav":
        # Pure-Python RMS loudness normalization fallback when FFmpeg is absent in sandbox
        with wave.open(str(src), "rb") as wf:
            ch = wf.getnchannels()
            sr = wf.getframerate()
            nframes = wf.getnframes()
            raw = wf.readframes(nframes)
        samples = array.array("h")
        samples.frombytes(raw)
        if samples:
            rms = math.sqrt(sum(float(x) * float(x) for x in samples) / len(samples))
            current_lufs = 20.0 * math.log10(max(1.0, rms) / 32768.0) - 0.691
            gain_db = max(-20.0, min(20.0, target_lufs - current_lufs))
            gain_lin = 10.0 ** (gain_db / 20.0)
            ceiling = int(32767 * (10.0 ** (-1.5 / 20.0)))
            norm_samples = array.array(
                "h",
                (max(-ceiling, min(ceiling, int(round(x * gain_lin)))) for x in samples),
            )
        else:
            norm_samples = samples
        with wave.open(str(out), "wb") as wf_out:
            wf_out.setnchannels(ch)
            wf_out.setsampwidth(2)
            wf_out.setframerate(sr)
            wf_out.writeframes(norm_samples.tobytes())
    else:
        run_ffmpeg(
            ["-i", str(src), "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(out)],
            600,
        )
    return {"file": str(out), "target_lufs": target_lufs}


def mix_project(
    project: Path,
    background: Path | None,
    out: Path,
    target_lufs: float = -16,
    duck_background: bool = False,
    protect_dialogue_peaks: bool = False,
) -> dict[str, Any]:
    from .kaggle_tasks import project_for
    if project_for(project):
        from .kaggle_operations import mix
        return mix(project,background,out,{'target_lufs':target_lufs,'duck_background':duck_background,'protect_dialogue_peaks':protect_dialogue_peaks})
    """Mix dubbed dialogue segments and preserved background into a unified soundtrack.

    If background is None, automatically checks for output/background_preserved.wav
    or analysis/separation/background.wav.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    t = project / "analysis" / "translated_transcript.json"
    manifest_path = project / "analysis" / "dialogue_manifest.json"

    # Auto-resolve background if not provided
    resolved_bg = background
    if resolved_bg is None or not resolved_bg.is_file():
        preserved_bg = project / "output" / "background_preserved.wav"
        separated_bg = project / "analysis" / "separation" / "background.wav"
        if preserved_bg.is_file():
            resolved_bg = preserved_bg
        elif separated_bg.is_file():
            resolved_bg = separated_bg

    clips: list[tuple[float, Path]] = []
    clip_details: list[dict[str, Any]] = []

    # Priority 1: Check dialogue_manifest.json units
    if manifest_path.is_file():
        try:
            m_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            for unit in m_data.get("units", []):
                val = (
                    (unit.get("loudness") or {}).get("output_path")
                    or (unit.get("loudness") or {}).get("normalized_audio")
                    or (unit.get("timing") or {}).get("output_path")
                    or (unit.get("timing") or {}).get("fit_audio")
                    or (unit.get("tts") or {}).get("output_path")
                    or (unit.get("tts") or {}).get("audio_path")
                )
                if val:
                    f = Path(val)
                    f = f if f.is_absolute() else project / f
                    if f.is_file():
                        start_time = max(0.0, float(unit.get("start_sec", 0.0)))
                        clips.append((start_time, f))
                        clip_details.append({
                            "segment_index": unit.get("segment_index"),
                            "start_sec": start_time,
                            "audio_path": str(f),
                        })
        except Exception:
            pass

    # Priority 2: Fall back to translated_transcript.json if no clips found from manifest
    if not clips and t.is_file():
        try:
            t_data = json.loads(t.read_text(encoding="utf-8"))
            rows = t_data.get("segments", [])
            for row in rows:
                value = row.get("normalized_audio") or row.get("fitted_audio") or row.get("dub_audio")
                if value:
                    f = Path(value)
                    f = f if f.is_absolute() else project / f
                    if f.is_file():
                        start_time = max(0.0, float(row.get("start", 0.0)))
                        clips.append((start_time, f))
                        clip_details.append({
                            "segment_index": row.get("segment_index"),
                            "start_sec": start_time,
                            "audio_path": str(f),
                        })
        except Exception:
            pass

    if not clips:
        raise RuntimeError("No synthesized clips; synthesize and fit segments first")

    # Sort clips by timeline start
    clips.sort(key=lambda x: x[0])
    clip_details.sort(key=lambda x: x["start_sec"])

    args: list[str] = []
    filters: list[str] = []
    labels: list[str] = []
    has_bg = bool(resolved_bg and resolved_bg.is_file())

    if has_bg:
        args += ["-i", str(resolved_bg)]
        filters.append("[0:a]anull[bg]")
        base = 1
    else:
        base = 0

    for i, (start, path) in enumerate(clips):
        args += ["-i", str(path)]
        delay = round(start * 1000)
        filters.append(f"[{base+i}:a]adelay={delay}|{delay}[d{i}]")
        labels.append(f"[d{i}]")

    filters.append("".join(labels) + f"amix=inputs={len(labels)}:duration=longest:normalize=0[dialogue]")

    if has_bg:
        if duck_background:
            filters.append("[dialogue]asplit=2[dia_sc][dia_mix]")
            filters.append("[dia_sc]apad[dia_sc_pad]")
            filters.append("[bg][dia_sc_pad]sidechaincompress=threshold=0.08:ratio=2.8:attack=35:release=450[ducked]")
            filters.append(f"[ducked][dia_mix]amix=inputs=2:duration=longest:normalize=0,loudnorm=I={target_lufs}:TP=-1.5:LRA=11[mix]")
        else:
            # Dialogue is normalized before mixing. Changing master gain here
            # would also change the original music and effects.
            filters.append("[bg][dialogue]amix=inputs=2:duration=longest:normalize=0[mix]")
    else:
        filters.append(f"[dialogue]loudnorm=I={target_lufs}:TP=-1.5:LRA=11[mix]")

    movie_dur = None
    source_dir = project / "source"
    if source_dir.is_dir():
        for p in source_dir.glob("original.*"):
            if p.is_file():
                try:
                    probe_cmd = subprocess.run(
                        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(p)],
                        capture_output=True, text=True, timeout=30
                    )
                    if probe_cmd.returncode == 0 and probe_cmd.stdout.strip():
                        movie_dur = float(probe_cmd.stdout.strip())
                        break
                except Exception:
                    pass

    final_map = "[mix]"
    if movie_dur and movie_dur > 0:
        filters.append(f"[mix]apad=whole_dur={movie_dur:.6f},atrim=0:{movie_dur:.6f}[out_aligned]")
        final_map = "[out_aligned]"

    # Inspect floating-point samples before PCM conversion can hide clipping.
    # Publish only a verified mix, preserving the last valid artifact on failure.
    if has_bg and not duck_background and (protect_dialogue_peaks or len(clips) > 32 or (movie_dur or 0) > 600):
        from .chunked_mix import mix_chunked
        from .work_progress import current_context, track
        context=current_context()
        if context:
            from . import app as studio
            base,job_id,phase,_=context
            cancel=lambda:studio.job_cancel_requested(studio.DB_PATH,job_id)
            from .auto_dub import read_status
            visible_helpers=bool((read_status(base).get("options") or {}).get("visible_helpers"))
        else:
            base,job_id,phase,cancel=project,"manual-mix","mix",lambda:False
            visible_helpers=False
        from .system_diagnostics import _memory
        available=_memory().get("available_bytes") or 0
        workers=max(1,min(4,int(max(0,available-2*1024**3)//(512*1024**2))))
        duration=movie_dur or __import__("soundfile").info(resolved_bg).duration
        with track(base,job_id,phase,"chunks"):
            peak_db=mix_chunked(project,resolved_bg,out,clips,duration,workers=workers,
                                visible_helpers=visible_helpers,cancelled=cancel,
                                protect_dialogue_peaks=protect_dialogue_peaks)
    else:
        with tempfile.TemporaryDirectory(prefix="mix-check-", dir=out.parent) as temporary:
            pending = Path(temporary) / "mix_float.wav"
            run_ffmpeg(args + ["-filter_complex", ";".join(filters), "-map", final_map,
                               "-ar", "48000", "-c:a", "pcm_f32le", "-rf64", "auto", str(pending)])
            peak_check = subprocess.run(
                [shutil.which("ffmpeg"), "-hide_banner", "-i", str(pending),
                 "-af", "astats=metadata=1:reset=0", "-f", "null", "-"],
                capture_output=True, text=True, timeout=7200,
            )
            peaks = re.findall(r"Peak level dB:\s*(-?(?:\d+(?:\.\d+)?|inf))", peak_check.stderr)
            if peak_check.returncode or not peaks:
                raise RuntimeError("Mix peak verification failed. Previous mix retained.")
            peak_db = max(float(value) for value in peaks)
            if peak_db > 0:
                raise RuntimeError(f"Mix would clip ({peak_db:.2f} dBFS). Lower dubbed dialogue loudness and mix again; background gain was retained.")
            verified = Path(temporary) / "mix.wav"
            run_ffmpeg(["-i", str(pending), "-c:a", "pcm_s16le", "-rf64", "auto", str(verified)])
            verified.replace(out)

    # Write mix manifest
    mix_manifest = {
        "schema_version": 1,
        "output_file": str(out),
        "target_lufs": target_lufs,
        "true_peak_ceiling": -1.5 if duck_background or not has_bg else None,
        "background_gain_db": 0.0 if has_bg and not duck_background else None,
        "dialogue_peak_protection": protect_dialogue_peaks,
        "master_normalization": bool(duck_background or not has_bg),
        "measured_sample_peak_dbfs": peak_db if math.isfinite(peak_db) else None,
        "dialogue_segments_mixed": len(clips),
        "background_used": has_bg,
        "background_path": str(resolved_bg) if has_bg else None,
        "duck_background": bool(has_bg and duck_background),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "clips": clip_details,
    }
    manifest_out = project / "output" / "mix_manifest.json"
    manifest_out.write_text(json.dumps(mix_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "file": str(out),
        "dialogue_segments_mixed": len(clips),
        "background_used": has_bg,
        "background_path": str(resolved_bg) if has_bg else None,
        "target_lufs": target_lufs,
        "mix_manifest": str(manifest_out),
    }
