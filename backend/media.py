from __future__ import annotations

import json, shutil, subprocess, re, os
import importlib.util
import tempfile
import time

from pathlib import Path
from typing import Any


def _bin(name: str) -> str:
    value = shutil.which(name)
    if not value:
        raise RuntimeError(f'{name} not found on PATH; install FFmpeg.')
    return value



def probe_media(source: Path, *, verify_decode: bool = False, cancelled=lambda: False) -> dict[str, Any]:
    from .kaggle_tasks import project_for
    if verify_decode and project_for(source):
        from .kaggle_operations import probe
        return probe(source,verify_decode)
    """Validate a movie source and return stable ffprobe metadata for checkpoints."""
    if not source.exists() or not source.is_file():
        raise RuntimeError("Source movie is missing or is not a regular file.")
    size = source.stat().st_size
    if size <= 0:
        raise RuntimeError("Source movie is empty.")
    executable = _bin("ffprobe")
    result = subprocess.run(
        [executable, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(source)],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "FFprobe failed to inspect the source movie.")[-3000:])
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"FFprobe returned invalid JSON: {exc}") from exc
    streams = data.get("streams") or []
    video = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    if not video:
        raise RuntimeError("Source movie has no video stream.")
    if not audio:
        raise RuntimeError("Source movie has no audio stream; dubbing analysis requires source audio.")
    duration_raw = (data.get("format") or {}).get("duration")
    try:
        duration_sec = float(duration_raw) if duration_raw is not None else 0.0
    except (TypeError, ValueError):
        duration_sec = 0.0
    if duration_sec <= 0:
        raise RuntimeError("Source movie duration is missing or invalid.")
    if verify_decode:
        verify_media_decode(source, metadata=data, cancelled=cancelled)
    return {
        "schema_version": 1,
        "file_name": source.name,
        "size_bytes": size,
        "duration_sec": round(duration_sec, 3),
        "format_name": (data.get("format") or {}).get("format_name"),
        "format_long_name": (data.get("format") or {}).get("format_long_name"),
        "bit_rate": (data.get("format") or {}).get("bit_rate"),
        "video_stream_count": len(video),
        "audio_stream_count": len(audio),
        "streams": [
            {
                "index": stream.get("index"),
                "codec_type": stream.get("codec_type"),
                "codec_name": stream.get("codec_name"),
                "width": stream.get("width"),
                "height": stream.get("height"),
                "channels": stream.get("channels"),
                "sample_rate": stream.get("sample_rate"),
                "language": (stream.get("tags") or {}).get("language"),
            }
            for stream in streams
        ],
    }


def verify_media_decode(source: Path, *, metadata=None, cancelled=lambda: False,
                        checkpoint: Path | None = None) -> dict[str, Any]:
    """Decode all primary video/audio packets; headers alone cannot detect truncation.

    Uses bounded log/progress storage and honours cancellation without publishing a
    success checkpoint. A content hash permits safe reuse on subsequent renders.
    """
    from .chunk_execution import digest, save_json
    from .work_progress import emit
    if cancelled():
        raise InterruptedError("Source validation cancelled; existing files retained")
    fingerprint = digest(source)
    if checkpoint and checkpoint.is_file():
        try:
            saved = json.loads(checkpoint.read_text(encoding="utf-8"))
            if saved.get("sha256") == fingerprint and saved.get("version") == 1 and saved.get("status") == "passed":
                return saved
        except (ValueError, OSError):
            pass
    if metadata is None:
        inspected = subprocess.run([_bin("ffprobe"), "-v", "error", "-show_format", "-show_streams",
                                    "-of", "json", str(source)], capture_output=True, text=True, timeout=120)
        if inspected.returncode:
            raise RuntimeError("Source decode validation failed: " + inspected.stderr[-2000:])
        metadata = json.loads(inspected.stdout or "{}")
    expected = float((metadata.get("format") or {}).get("duration") or 0)
    videos = [s for s in metadata.get("streams", []) if s.get("codec_type") == "video"]
    if not videos:
        raise RuntimeError("Source decode validation requires a video stream")
    def progress_tail(path):
        with path.open("rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell()-4096))
            return handle.read().decode("ascii", errors="replace")
    with tempfile.TemporaryDirectory(prefix="opendub-decode-") as directory:
        progress = Path(directory) / "progress.txt"
        with tempfile.TemporaryFile() as error_log:
            process = subprocess.Popen([_bin("ffmpeg"), "-hide_banner", "-v", "error", "-xerror",
                                        "-threads", "2", "-i", str(source), "-map", "0:v:0", "-map", "0:a:0",
                                        "-progress", str(progress), "-nostats", "-f", "null", "-"],
                                       stdout=subprocess.DEVNULL, stderr=error_log)
            try:
                while process.poll() is None:
                    if cancelled():
                        raise InterruptedError("Source validation cancelled; existing files retained")
                    if progress.exists():
                        tail = progress_tail(progress)
                        times = re.findall(r"out_time_us=(\d+)", tail)
                        if times and expected:
                            emit(min(expected, int(times[-1]) / 1e6), expected)
                    time.sleep(.25)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            error_log.seek(0, 2)
            error_log.seek(max(0, error_log.tell() - 3000))
            errors = error_log.read().decode("utf-8", errors="replace")
            if process.returncode or errors.strip():
                raise RuntimeError("Source is corrupt or incomplete; decode validation failed. " + errors[-2000:])
        tail = progress_tail(progress)
        frames = re.findall(r"frame=(\d+)", tail)
        count = int(frames[-1]) if frames else 0
        declared = videos[0].get("nb_frames")
        if count == 0 or (str(declared).isdigit() and count < int(declared) - 2):
            raise RuntimeError(f"Source is incomplete: decoded {count} video frames, header declares {declared}")
    result = {"version": 1, "status": "passed", "sha256": fingerprint, "decoded_video_frames": count}
    if checkpoint:
        save_json(checkpoint, result)
    return result


def check_asr_runtime(device: str = "auto") -> dict[str, Any]:
    """Validate the local ASR runtime before expensive movie analysis begins."""
    faster_whisper_available = importlib.util.find_spec("faster_whisper") is not None
    if not faster_whisper_available:
        raise RuntimeError(
            "ASR runtime is missing. Install requirements-optional.txt and restart OpenDub Studio."
        )
    selected = device
    cuda_devices = 0
    ctranslate2_available = importlib.util.find_spec("ctranslate2") is not None
    if ctranslate2_available:
        try:
            import ctranslate2
            cuda_devices = int(ctranslate2.get_cuda_device_count())
        except Exception:
            cuda_devices = 0
    if selected == "auto":
        selected = "cuda" if cuda_devices > 0 else "cpu"
    if selected == "cuda" and cuda_devices <= 0:
        selected = "cpu"
    if selected not in {"cpu", "cuda"}:
        raise RuntimeError(f"Unsupported ASR device: {selected}")
    return {
        "status": "ready",
        "engine": "faster-whisper",
        "faster_whisper_available": faster_whisper_available,
        "ctranslate2_available": ctranslate2_available,
        "cuda_devices": cuda_devices,
        "requested_device": device,
        "selected_device": selected,
    }


def extract_audio(source: Path, output: Path) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([_bin('ffmpeg'), '-y', '-i', str(source), '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(output)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError((result.stderr or 'Audio extraction failed')[-2500:])
    return {'file': str(output.name), 'size_bytes': output.stat().st_size, 'sample_rate': 16000, 'channels': 1}


def detect_scenes(source: Path, output: Path, threshold: float = 0.35) -> list[dict[str, Any]]:
    result = subprocess.run([_bin('ffmpeg'), '-hide_banner', '-i', str(source), '-vf', f"select='gt(scene,{threshold})',showinfo", '-an', '-f', 'null', '-'], capture_output=True, text=True)
    if result.returncode not in (0, 1):
        raise RuntimeError((result.stderr or 'Scene detection failed')[-2500:])
    times = sorted(set([0.0] + [round(float(m.group(1)), 3) for line in (result.stderr or '').splitlines() if (m := re.search(r'pts_time:([0-9.]+)', line))]))
    scenes = [{'scene_index': i, 'start_sec': t, 'end_sec': times[i+1] if i+1 < len(times) else None} for i, t in enumerate(times)]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(scenes, indent=2), encoding='utf-8')
    return scenes


def transcribe(audio_path: Path, model_size: str = 'small', language: str | None = None, device: str = 'auto') -> dict[str, Any]:
    from .kaggle_tasks import project_for
    if project_for(audio_path):
        from .kaggle_operations import transcribe as remote_transcribe
        return remote_transcribe(audio_path,model_size,language,device)
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError('Optional ASR is missing. Install requirements-optional.txt first.') from exc
    selected = device
    if selected == 'auto':
        try:
            import ctranslate2
            selected = 'cuda' if ctranslate2.get_cuda_device_count() else 'cpu'
        except Exception:
            selected = 'cpu'
    model = WhisperModel(model_size, device=selected, compute_type='float16' if selected == 'cuda' else 'int8',
                         cpu_threads=max(1, int(os.getenv("OPENDUB_ASR_THREADS", "4"))))
    segments, info = model.transcribe(str(audio_path), language=language, vad_filter=True, word_timestamps=True, beam_size=3)
    rows = []
    from .work_progress import emit
    emit(0, info.duration)
    for seg in segments:
        words = [{'start': w.start, 'end': w.end, 'text': w.word, 'probability': w.probability} for w in (seg.words or [])]
        rows.append({'start': seg.start, 'end': seg.end, 'text': seg.text.strip(), 'words': words, 'no_speech_prob': seg.no_speech_prob})
        emit(min(info.duration,seg.end), info.duration)
        print(f"[OpenDub ASR] {min(info.duration, seg.end):.1f}/{info.duration:.1f} audio seconds processed", flush=True)
    return {'language': info.language, 'language_probability': info.language_probability, 'duration': info.duration, 'model': model_size, 'device': selected, 'segments': rows}



def separate_dialogue_candidate(audio_path: Path, output_dir: Path, model_filename: str | None = None, *args, **kwargs) -> dict[str, Any]:
    """Use the shared separator that generates both vocal and background stems."""
    from .background_preservation import separate_dialogue_candidate as separate_stems
    return separate_stems(audio_path, output_dir, model_filename, *args, **kwargs)


def analyze_audio_profile(audio_path: Path, output: Path) -> dict[str, Any]:
    """Measure source audio loudness/peaks and coarse silence regions via FFmpeg."""
    result = subprocess.run(
        [_bin("ffmpeg"), "-hide_banner", "-i", str(audio_path),
         "-af", "astats=metadata=1:reset=0,silencedetect=noise=-45dB:d=0.35",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    # FFmpeg may return nonzero for unusual codecs despite producing useful diagnostics.
    diagnostics = result.stderr or ""
    if result.returncode not in (0, 1) or "silence_" not in diagnostics and "astats" not in diagnostics:
        raise RuntimeError((diagnostics or "Audio profiling failed")[-2500:])
    import re
    def last_metric(label: str) -> float | None:
        matches = re.findall(re.escape(label) + r":\s*(-?(?:[0-9]+(?:\.[0-9]*)?|inf|nan))", diagnostics, re.I)
        if not matches:
            return None
        try:
            value = float(matches[-1])
            return value if value == value and abs(value) != float("inf") else None
        except ValueError:
            return None
    starts = [float(x) for x in re.findall(r"silence_start:\s*([0-9.]+)", diagnostics)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([0-9.]+)", diagnostics)]
    silences = []
    for i, start in enumerate(starts):
        end = ends[i] if i < len(ends) else None
        silences.append({"start_sec": start, "end_sec": end,
                         "duration_sec": round(end - start, 3) if end is not None else None})
    profile = {
        "schema_version": 1, "source_audio": str(audio_path.name),
        "peak_level_db": last_metric("Peak level dB"),
        "rms_level_db": last_metric("RMS level dB"),
        "silence_threshold_db": -45.0, "minimum_silence_sec": 0.35,
        "silence_regions": silences,
        "notice": "Silence detection is a coarse signal heuristic, not dialogue/music/SFX classification."
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return profile
