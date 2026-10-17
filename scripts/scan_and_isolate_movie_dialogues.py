"""Scan and isolate human dialogue clips from full-length movie for voice cloning.

Target Movie:
  JR NTR Blockbuster Action Hindi Dubbed Full Movie JANTA GARAGE (Mohanlal, Samantha, Nithya Menen)

Pipeline:
  1. Extract uncompressed 24kHz 16-bit mono master audio track with FFmpeg.
  2. Perform Voice Activity Detection (VAD) and ASR with faster-whisper (WhisperModel).
  3. Filter out non-speech intervals (music, background noise, explosions, pure SFX, hallucinations).
  4. Chain contiguous dialogue utterances into 6.0s - 12.0s speech windows.
  5. Apply acoustic speech conditioning filter:
     - Highpass 85Hz (eliminates sub-bass rumble, mic thumps, low-frequency movie explosions)
     - Lowpass 7500Hz (eliminates high-frequency hiss and synth score bleed)
     - Vocal presence EQ (+1.5 dB @ 2500Hz)
     - EBU R128 Loudness Normalization (-16 LUFS, TP -1.5, LRA 11)
  6. Extract isolated raw dialogue clips into `storage/movie_vocal_extraction/raw_clips/{clip_id}.wav`.
  7. Export `storage/movie_vocal_extraction/dialogue_manifest.json`.

Resumption & Crash Proofing:
  - Checks if master audio is already extracted before re-encoding.
  - Caches raw VAD segments to avoid re-transcribing the full movie.
  - Resumes extraction incrementally; already extracted clips are preserved.
  - Atomically writes manifest to prevent corruption on interruption.
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import wave
from typing import Any

# Optional high-performance audio packages (with graceful fallbacks)
try:
    import numpy as np
except ImportError:
    np = None

try:
    import soundfile as sf
except ImportError:
    sf = None

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None


# Default Paths & Constants
DEFAULT_MOVIE_WIN = (
    r"C:\Users\su936\OneDrive\Desktop\JR NTR Blockbuster Action Hindi Dubbed Full Movie "
    r"JANTA GARAGE  Mohanlal, Samantha, Nithya Menen - Goldmines CineHub (720p, h264).mp4"
)
DEFAULT_FFMPEG_WIN = (
    r"C:\Users\su936\AppData\Local\Microsoft\WinGet\Packages\\"
    r"Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin\ffmpeg.exe"
)
DEFAULT_OUTPUT_DIR = "storage/movie_vocal_extraction"

TARGET_SAMPLE_RATE = 24000
TARGET_CHANNELS = 1

# Duration constraints for voice cloning reference audio
MIN_CLIP_DURATION = 6.0
MAX_CLIP_DURATION = 12.0
MAX_CHAIN_GAP = 1.0  # Max silence gap in seconds to chain contiguous utterances

# Broadcast speech conditioning filter chain
SPEECH_CONDITIONING_FILTER = (
    "highpass=f=85,"
    "lowpass=f=7500,"
    "equalizer=f=2500:width_type=o:width=1.2:g=+1.5,"
    "loudnorm=I=-16:TP=-1.5:LRA=11"
)

# Music / non-speech text pattern tokens
MUSIC_SFX_REGEX = re.compile(
    r"\[.*?\]|\(.*?\)|♪+|♫+|\*+music\*+|\*+applause\*+|[♬♩]|"
    r"\[संगीत\]|\[तालियाँ\]|\[शोर\]|\[हंसी\]",
    re.IGNORECASE,
)


def setup_logger(output_dir: Path | None = None) -> logging.Logger:
    """Configure clean formatted console and file logger."""
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    logger = logging.getLogger("MovieVocalExtractor")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        c_handler = logging.StreamHandler(sys.stdout)
        c_format = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
        c_handler.setFormatter(c_format)
        logger.addHandler(c_handler)

        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            f_handler = logging.FileHandler(output_dir / "vocal_extraction.log", encoding="utf-8")
            f_format = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")
            f_handler.setFormatter(f_format)
            logger.addHandler(f_handler)
    return logger


def resolve_system_path(path_str: str | Path) -> Path:
    """Resolve Windows or WSL filesystem paths cross-platform."""
    raw = str(path_str).strip().strip('"').strip("'")
    p = Path(raw)
    if p.exists():
        return p

    # If running on Linux/WSL and given a Windows drive path (e.g. C:\...)
    if sys.platform != "win32" and re.match(r"^[a-zA-Z]:[\\/]", raw):
        drive = raw[0].lower()
        subpath = raw[3:].replace("\\", "/")
        wsl_candidate = Path(f"/mnt/{drive}/{subpath}")
        if wsl_candidate.exists():
            return wsl_candidate
        return wsl_candidate

    # If running on Windows and given a WSL path (e.g. /mnt/c/...)
    if sys.platform == "win32" and raw.startswith("/mnt/") and len(raw) > 6 and raw[6] == "/":
        drive = raw[5].upper()
        subpath = raw[7:].replace("/", "\\")
        win_candidate = Path(f"{drive}:\\{subpath}")
        if win_candidate.exists():
            return win_candidate
        return win_candidate

    return p


def resolve_ffmpeg(custom_path: str | None = None) -> str:
    """Locate FFmpeg executable across Windows, WSL, and system PATH."""
    if custom_path:
        cand = resolve_system_path(custom_path)
        if cand.is_file():
            return str(cand)
        which_cand = shutil.which(custom_path)
        if which_cand:
            return which_cand

    # Check environment variable
    env_ffmpeg = os.environ.get("FFMPEG_PATH") or os.environ.get("FFMPEG_WIN")
    if env_ffmpeg:
        cand = resolve_system_path(env_ffmpeg)
        if cand.is_file():
            return str(cand)

    # Check system PATH
    sys_ffmpeg = shutil.which("ffmpeg")
    if sys_ffmpeg:
        return sys_ffmpeg

    # Check default Windows Gyan build
    cand_win = resolve_system_path(DEFAULT_FFMPEG_WIN)
    if cand_win.is_file():
        return str(cand_win)

    # Common alternate locations
    standard_paths = [
        Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
        Path(r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"),
        Path("/usr/bin/ffmpeg"),
        Path("/usr/local/bin/ffmpeg"),
        Path("/mnt/c/ffmpeg/bin/ffmpeg.exe"),
    ]
    for sp in standard_paths:
        if sp.is_file():
            return str(sp)

    # Fallback default
    return "ffmpeg"


def format_seconds(seconds: float) -> str:
    """Format seconds into HH:MM:SS.mmm format."""
    td = datetime.timedelta(seconds=max(0.0, seconds))
    total_sec = int(td.total_seconds())
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def extract_master_audio(
    movie_path: Path,
    output_audio: Path,
    ffmpeg_bin: str,
    duration_limit: float | None = None,
    logger: logging.Logger | None = None,
) -> bool:
    """Extract full movie audio to 24kHz 16-bit mono WAV. Supports resumption."""
    log = logger or logging.getLogger("MovieVocalExtractor")

    if output_audio.is_file() and output_audio.stat().st_size > 1024 * 1024:
        log.info(
            f"[Resume] Master audio already exists ({output_audio.stat().st_size / (1024*1024):.2f} MB): {output_audio.name}"
        )
        return True

    output_audio.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output_audio.with_name(f"_tmp_{output_audio.name}")

    cmd = [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-i",
        str(movie_path),
    ]
    if duration_limit and duration_limit > 0:
        cmd.extend(["-t", f"{duration_limit:.2f}"])

    cmd.extend([
        "-vn",
        "-ac",
        str(TARGET_CHANNELS),
        "-ar",
        str(TARGET_SAMPLE_RATE),
        "-c:a",
        "pcm_s16le",
        str(temp_output),
    ])

    log.info(f"Extracting 24kHz master audio from: {movie_path.name}...")
    start_t = time.time()
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            log.error(f"FFmpeg audio extraction failed (code {res.returncode}): {res.stderr[:500]}")
            temp_output.unlink(missing_ok=True)
            return False
    except Exception as exc:
        log.error(f"Exception while executing FFmpeg: {exc}")
        temp_output.unlink(missing_ok=True)
        return False

    if not temp_output.is_file() or temp_output.stat().st_size < 1000:
        log.error("FFmpeg produced empty or invalid master audio file.")
        temp_output.unlink(missing_ok=True)
        return False

    os.replace(temp_output, output_audio)
    elapsed = time.time() - start_t
    size_mb = output_audio.stat().st_size / (1024 * 1024)
    log.info(f"Master audio extracted successfully in {elapsed:.1f}s ({size_mb:.2f} MB).")
    return True


def clean_transcript_text(text: str) -> str:
    """Clean dialogue text, removing music tags, bracketed sfx cues, and extra whitespace."""
    if not text:
        return ""
    cleaned = MUSIC_SFX_REGEX.sub(" ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def is_valid_speech_utterance(
    text: str,
    no_speech_prob: float,
    avg_logprob: float,
    compression_ratio: float = 1.0,
    min_chars: int = 2,
    max_no_speech_prob: float = 0.85,
    min_avg_logprob: float = -2.2,
) -> bool:
    """Filter out pure music, silence, noise, sound effects, and Whisper hallucinations."""
    if no_speech_prob >= max_no_speech_prob:
        return False
    if avg_logprob < min_avg_logprob:
        return False
    if compression_ratio > 2.4:
        # Repetitive hallucination loop
        return False

    cleaned = clean_transcript_text(text)
    # Check if there is actual linguistic content (Hindi characters or Latin characters)
    alphanumeric_count = sum(1 for c in cleaned if c.isalnum())
    if alphanumeric_count < min_chars:
        return False

    # Check for pure music tag remnants
    lower = cleaned.lower()
    if lower in ("music", "applause", "laughter", "cheering", "background music"):
        return False

    return True


def detect_movie_dialogues(
    audio_path: Path,
    cache_path: Path,
    model_size: str = "small",
    device: str = "auto",
    language: str | None = "hi",
    chunk_size_sec: float = 600.0,
    resume: bool = True,
    logger: logging.Logger | None = None,
) -> list[dict[str, Any]]:
    """Detect spoken dialogue segments using faster-whisper with chunked VAD scanning.

    Caches results to disk for instant resumption on subsequent runs.
    """
    log = logger or logging.getLogger("MovieVocalExtractor")

    # Resumption check
    if resume and cache_path.is_file() and cache_path.stat().st_size > 10:
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
            if isinstance(cached_data, list) and len(cached_data) > 0:
                log.info(f"[Resume] Loaded {len(cached_data)} cached dialogue segments from: {cache_path.name}")
                return cached_data
        except Exception as e:
            log.warning(f"Could not read existing cache ({e}), re-running VAD...")

    if WhisperModel is None:
        raise RuntimeError(
            "faster_whisper is not installed. Please install faster-whisper or run in the project environment."
        )

    # Device auto-detection
    selected_device = device
    if selected_device == "auto":
        try:
            import ctranslate2

            if ctranslate2.get_cuda_device_count() > 0:
                selected_device = "cuda"
            else:
                selected_device = "cpu"
        except Exception:
            selected_device = "cpu"

    compute_type = "float16" if selected_device == "cuda" else "int8"
    log.info(
        f"Initializing faster-whisper model='{model_size}' on device='{selected_device}' (compute_type='{compute_type}')..."
    )

    model = WhisperModel(
        model_size_or_path=model_size,
        device=selected_device,
        compute_type=compute_type,
    )

    start_t = time.time()

    # Determine total duration of audio file
    total_audio_sec = None
    sample_rate = TARGET_SAMPLE_RATE
    if sf is not None:
        try:
            info = sf.info(str(audio_path))
            total_audio_sec = info.duration
            sample_rate = info.samplerate
        except Exception as e:
            log.debug(f"soundfile info failed: {e}")

    if total_audio_sec is None:
        try:
            with wave.open(str(audio_path), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate > 0 and frames > 0:
                    total_audio_sec = frames / float(rate)
                    sample_rate = rate
        except Exception:
            pass

    # If duration could not be determined or is shorter than chunk_size_sec, do single pass
    if total_audio_sec is None or total_audio_sec <= chunk_size_sec:
        log.info(f"Scanning movie audio in single pass (language='{language or 'auto'}')...")
        segments_gen, _ = model.transcribe(
            str(audio_path),
            language=language,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=450,
                speech_pad_ms=200,
                threshold=0.5,
            ),
            beam_size=5,
            temperature=0.0,
            word_timestamps=False,
        )
        raw_segments: list[dict[str, Any]] = []
        filtered_speech_segments: list[dict[str, Any]] = []
        for seg in segments_gen:
            item = {
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "duration": round(seg.end - seg.start, 3),
                "text": seg.text.strip(),
                "avg_logprob": round(seg.avg_logprob, 3),
                "no_speech_prob": round(seg.no_speech_prob, 3),
                "compression_ratio": round(seg.compression_ratio, 3),
            }
            raw_segments.append(item)
            if is_valid_speech_utterance(
                text=item["text"],
                no_speech_prob=item["no_speech_prob"],
                avg_logprob=item["avg_logprob"],
                compression_ratio=item["compression_ratio"],
            ):
                item["clean_text"] = clean_transcript_text(item["text"])
                filtered_speech_segments.append(item)
    else:
        # Chunked scan in windows (e.g. 600s / 10 min each)
        num_chunks = math.ceil(total_audio_sec / chunk_size_sec)
        log.info(
            f"Scanning movie audio in {num_chunks} chunked windows of {chunk_size_sec / 60.0:.1f} minutes "
            f"(total: {total_audio_sec / 60.0:.1f} min, language='{language or 'auto'}')..."
        )
        raw_segments = []
        filtered_speech_segments = []
        temp_chunk_wav = audio_path.parent / "_vad_chunk.wav"

        try:
            for chunk_idx in range(num_chunks):
                chunk_start = chunk_idx * chunk_size_sec
                chunk_end = min((chunk_idx + 1) * chunk_size_sec, total_audio_sec)
                chunk_dur = chunk_end - chunk_start
                if chunk_dur <= 0.5:
                    continue

                log.info(
                    f"  Window [{chunk_idx + 1}/{num_chunks}]: "
                    f"{format_seconds(chunk_start)} -> {format_seconds(chunk_end)} ({chunk_dur:.1f}s)..."
                )

                chunk_extracted = False
                if sf is not None:
                    try:
                        with sf.SoundFile(str(audio_path)) as sf_in:
                            sf_in.seek(int(chunk_start * sample_rate))
                            chunk_data = sf_in.read(int(chunk_dur * sample_rate))
                            sf.write(str(temp_chunk_wav), chunk_data, sample_rate)
                            chunk_extracted = True
                    except Exception as err:
                        log.debug(f"soundfile chunk extract failed: {err}")

                if not chunk_extracted:
                    ffmpeg_bin = resolve_ffmpeg()
                    cmd = [
                        ffmpeg_bin, "-y", "-ss", str(chunk_start), "-t", str(chunk_dur),
                        "-i", str(audio_path), "-c", "copy", str(temp_chunk_wav)
                    ]
                    subprocess.run(cmd, capture_output=True, check=True)

                chunk_segs, _ = model.transcribe(
                    str(temp_chunk_wav),
                    language=language,
                    vad_filter=True,
                    vad_parameters=dict(
                        min_silence_duration_ms=450,
                        speech_pad_ms=200,
                        threshold=0.5,
                    ),
                    beam_size=5,
                    temperature=0.0,
                    word_timestamps=False,
                )

                chunk_accepted = 0
                for seg in chunk_segs:
                    abs_start = round(chunk_start + seg.start, 3)
                    abs_end = round(chunk_start + seg.end, 3)
                    item = {
                        "start": abs_start,
                        "end": abs_end,
                        "duration": round(seg.end - seg.start, 3),
                        "text": seg.text.strip(),
                        "avg_logprob": round(seg.avg_logprob, 3),
                        "no_speech_prob": round(seg.no_speech_prob, 3),
                        "compression_ratio": round(seg.compression_ratio, 3),
                    }
                    raw_segments.append(item)

                    if is_valid_speech_utterance(
                        text=item["text"],
                        no_speech_prob=item["no_speech_prob"],
                        avg_logprob=item["avg_logprob"],
                        compression_ratio=item["compression_ratio"],
                    ):
                        item["clean_text"] = clean_transcript_text(item["text"])
                        filtered_speech_segments.append(item)
                        chunk_accepted += 1

                log.info(f"    -> Window [{chunk_idx + 1}/{num_chunks}] extracted {chunk_accepted} dialogue segments.")
        finally:
            if temp_chunk_wav.exists():
                try:
                    temp_chunk_wav.unlink()
                except OSError:
                    pass

    filtered_speech_segments.sort(key=lambda s: s["start"])
    elapsed = time.time() - start_t
    log.info(
        f"VAD & Whisper scan complete in {elapsed:.1f}s: "
        f"detected {len(raw_segments)} raw utterances, {len(filtered_speech_segments)} confirmed spoken dialogue segments."
    )

    # Cache segments atomically
    temp_cache = cache_path.with_name(f"_tmp_{cache_path.name}")
    temp_cache.parent.mkdir(parents=True, exist_ok=True)
    with open(temp_cache, "w", encoding="utf-8") as f:
        json.dump(filtered_speech_segments, f, indent=2, ensure_ascii=False)
    os.replace(temp_cache, cache_path)

    return filtered_speech_segments


def build_dialogue_chains(
    segments: list[dict[str, Any]],
    min_clip_sec: float = MIN_CLIP_DURATION,
    max_clip_sec: float = MAX_CLIP_DURATION,
    max_gap: float = MAX_CHAIN_GAP,
) -> list[dict[str, Any]]:
    """Chain contiguous dialogue utterances into optimal 6.0s - 12.0s vocal clips.

    Algorithms:
      1. If an individual segment duration is in [min_clip_sec, max_clip_sec], keep as clip.
      2. If shorter than min_clip_sec, chain with subsequent contiguous segments if gap <= max_gap.
      3. If a segment exceeds max_clip_sec, split into natural non-overlapping slices within [min_clip_sec, max_clip_sec].
      4. Any isolated segment that cannot reach min_clip_sec is safely excluded.
    """
    if not segments:
        return []

    # Sort segments chronologically
    sorted_segs = sorted(segments, key=lambda s: s["start"])
    chains: list[dict[str, Any]] = []

    current_group: list[dict[str, Any]] = []

    def finalize_group(group: list[dict[str, Any]]) -> None:
        if not group:
            return
        g_start = group[0]["start"]
        g_end = group[-1]["end"]
        dur = round(g_end - g_start, 3)
        combined_text = " ".join(s.get("clean_text") or clean_transcript_text(s["text"]) for s in group).strip()

        if min_clip_sec <= dur <= max_clip_sec:
            chains.append({
                "start_sec": g_start,
                "end_sec": g_end,
                "duration": dur,
                "text": combined_text,
            })
        elif dur > max_clip_sec:
            # Partition prolonged monologue/group into ~8.0s chunks
            sub_start = g_start
            while sub_start + min_clip_sec <= g_end:
                sub_end = min(sub_start + 8.5, g_end)
                if sub_end - sub_start < min_clip_sec and chains:
                    break
                chains.append({
                    "start_sec": round(sub_start, 3),
                    "end_sec": round(sub_end, 3),
                    "duration": round(sub_end - sub_start, 3),
                    "text": combined_text,
                })
                sub_start = sub_end

    for seg in sorted_segs:
        seg_dur = seg["end"] - seg["start"]
        if seg_dur < 0.4:
            continue

        if not current_group:
            current_group.append(seg)
            continue

        gap = seg["start"] - current_group[-1]["end"]
        candidate_dur = seg["end"] - current_group[0]["start"]

        if gap <= max_gap and candidate_dur <= max_clip_sec:
            current_group.append(seg)
        else:
            finalize_group(current_group)
            current_group = [seg]

    if current_group:
        finalize_group(current_group)

    # Filter strictly for [min_clip_sec, max_clip_sec]
    valid_chains = [
        c for c in chains
        if min_clip_sec <= c["duration"] <= (max_clip_sec + 0.1) and len(c["text"]) >= 2
    ]
    return valid_chains


def isolate_dialogue_clip(
    source_audio: Path,
    output_clip: Path,
    start_sec: float,
    duration_sec: float,
    ffmpeg_bin: str,
    logger: logging.Logger | None = None,
) -> bool:
    """Extract and condition speech snippet using highpass, lowpass, vocal presence EQ, and loudnorm."""
    log = logger or logging.getLogger("MovieVocalExtractor")
    output_clip.parent.mkdir(parents=True, exist_ok=True)

    temp_clip = output_clip.with_name(f"_tmp_{output_clip.name}")

    cmd = [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start_sec:.3f}",
        "-i",
        str(source_audio),
        "-t",
        f"{duration_sec:.3f}",
        "-af",
        SPEECH_CONDITIONING_FILTER,
        "-ar",
        str(TARGET_SAMPLE_RATE),
        "-ac",
        str(TARGET_CHANNELS),
        "-c:a",
        "pcm_s16le",
        str(temp_clip),
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            log.warning(f"FFmpeg conditioning failed for clip at {start_sec:.2f}s: {res.stderr[:200]}")
            temp_clip.unlink(missing_ok=True)
            return False
    except Exception as exc:
        log.warning(f"Error extracting clip at {start_sec:.2f}s: {exc}")
        temp_clip.unlink(missing_ok=True)
        return False

    if not temp_clip.is_file() or temp_clip.stat().st_size < 1500:
        temp_clip.unlink(missing_ok=True)
        return False

    os.replace(temp_clip, output_clip)
    return True


def save_manifest_atomic(manifest_path: Path, manifest_data: list[dict[str, Any]]) -> None:
    """Write dialogue manifest JSON atomically to prevent corruption."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_manifest = manifest_path.with_name(f"_tmp_{manifest_path.name}")
    with open(temp_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2, ensure_ascii=False)
    os.replace(temp_manifest, manifest_path)


def run_pipeline(
    movie_path_str: str = DEFAULT_MOVIE_WIN,
    ffmpeg_path_str: str | None = DEFAULT_FFMPEG_WIN,
    output_dir_str: str = DEFAULT_OUTPUT_DIR,
    model_size: str = "small",
    device: str = "auto",
    language: str | None = "hi",
    min_clip_sec: float = MIN_CLIP_DURATION,
    max_clip_sec: float = MAX_CLIP_DURATION,
    max_clips: int | None = None,
    scan_duration: float | None = None,
    resume: bool = True,
) -> dict[str, Any]:
    """Execute complete movie vocal extraction, VAD scanning, speech conditioning, and manifest generation."""
    output_dir = Path(output_dir_str).resolve()
    raw_clips_dir = output_dir / "raw_clips"
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_clips_dir.mkdir(parents=True, exist_ok=True)

    logger = setup_logger(output_dir)
    logger.info("================================================================================")
    logger.info("  OpenDub Studio — Movie Dialogue VAD Scanner & Speech Isolator")
    logger.info("================================================================================")

    # 1. Resolve Binaries and Files
    ffmpeg_bin = resolve_ffmpeg(ffmpeg_path_str)
    logger.info(f"FFmpeg binary: {ffmpeg_bin}")

    movie_path = resolve_system_path(movie_path_str)
    logger.info(f"Input Movie:   {movie_path}")
    if not movie_path.is_file():
        logger.warning(
            f"Movie file not found directly at {movie_path}. "
            "Please ensure the file exists or pass --movie with valid path."
        )

    master_audio_path = output_dir / "master_audio_24k.wav"
    vad_cache_path = output_dir / "vad_segments_cache.json"
    manifest_path = output_dir / "dialogue_manifest.json"
    summary_path = output_dir / "extraction_summary.json"

    # 2. Extract Master 24kHz Audio
    if movie_path.is_file():
        success = extract_master_audio(
            movie_path=movie_path,
            output_audio=master_audio_path,
            ffmpeg_bin=ffmpeg_bin,
            duration_limit=scan_duration,
            logger=logger,
        )
        if not success:
            raise RuntimeError(f"Failed to extract master audio from movie {movie_path}")
    elif master_audio_path.is_file():
        logger.info(f"Using pre-existing master audio: {master_audio_path}")
    else:
        raise FileNotFoundError(
            f"Neither movie ({movie_path}) nor pre-extracted master audio ({master_audio_path}) was found."
        )

    # 3. Detect Spoken Dialogue via Whisper + VAD
    speech_segments = detect_movie_dialogues(
        audio_path=master_audio_path,
        cache_path=vad_cache_path,
        model_size=model_size,
        device=device,
        language=language,
        resume=resume,
        logger=logger,
    )

    if not speech_segments:
        logger.warning("No speech segments detected in input audio.")
        save_manifest_atomic(manifest_path, [])
        return {"total_clips": 0, "manifest_path": str(manifest_path)}

    # 4. Build 6.0s - 12.0s Dialogue Chains
    dialogue_chains = build_dialogue_chains(
        speech_segments,
        min_clip_sec=min_clip_sec,
        max_clip_sec=max_clip_sec,
        max_gap=MAX_CHAIN_GAP,
    )
    logger.info(f"Constructed {len(dialogue_chains)} target dialogue chains in [{min_clip_sec}s - {max_clip_sec}s] range.")

    if max_clips and max_clips > 0:
        dialogue_chains = dialogue_chains[:max_clips]
        logger.info(f"Limiting to first {max_clips} dialogue clips as requested.")

    # 5. Load Existing Manifest for Resumption
    existing_manifest_by_id: dict[str, dict[str, Any]] = {}
    if resume and manifest_path.is_file():
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, list):
                    for item in loaded:
                        cid = item.get("clip_id")
                        if cid:
                            existing_manifest_by_id[cid] = item
            logger.info(f"[Resume] Found {len(existing_manifest_by_id)} already cataloged clips in manifest.")
        except Exception as e:
            logger.warning(f"Could not parse existing manifest: {e}")

    # 6. Extract Conditioned Audio Clips
    manifest_records: list[dict[str, Any]] = []
    total_speech_sec = 0.0

    for idx, chain in enumerate(dialogue_chains, start=1):
        clip_id = f"dialogue_{idx:04d}"
        clip_filename = f"{clip_id}.wav"
        clip_path = raw_clips_dir / clip_filename
        # Relative path for portable storage
        rel_clip_path = str(clip_path.relative_to(output_dir.parent.parent)).replace("\\", "/")

        start_sec = chain["start_sec"]
        end_sec = chain["end_sec"]
        duration = chain["duration"]
        text = chain["text"]

        # Check if already extracted and valid
        if resume and clip_id in existing_manifest_by_id and clip_path.is_file() and clip_path.stat().st_size > 2000:
            manifest_records.append(existing_manifest_by_id[clip_id])
            total_speech_sec += duration
            continue

        logger.info(
            f"[{idx}/{len(dialogue_chains)}] Isolating {clip_id} "
            f"[{format_seconds(start_sec)} -> {format_seconds(end_sec)} | {duration:.2f}s]: \"{text[:45]}...\""
        )

        ok = isolate_dialogue_clip(
            source_audio=master_audio_path,
            output_clip=clip_path,
            start_sec=start_sec,
            duration_sec=duration,
            ffmpeg_bin=ffmpeg_bin,
            logger=logger,
        )

        if ok:
            record = {
                "clip_id": clip_id,
                "start_sec": start_sec,
                "end_sec": end_sec,
                "duration": duration,
                "text": text,
                "clip_path": rel_clip_path,
            }
            manifest_records.append(record)
            total_speech_sec += duration

            # Periodic atomic manifest flush
            if len(manifest_records) % 5 == 0:
                save_manifest_atomic(manifest_path, manifest_records)
        else:
            logger.warning(f"Failed to isolate clip {clip_id} at {start_sec:.2f}s.")

    # 7. Final Manifest & Summary Export
    save_manifest_atomic(manifest_path, manifest_records)

    summary_data = {
        "status": "success",
        "movie_source": str(movie_path.name),
        "total_dialogues_extracted": len(manifest_records),
        "total_speech_duration_seconds": round(total_speech_sec, 2),
        "total_speech_duration_minutes": round(total_speech_sec / 60.0, 2),
        "min_clip_duration": min_clip_sec,
        "max_clip_duration": max_clip_sec,
        "sample_rate": TARGET_SAMPLE_RATE,
        "channels": TARGET_CHANNELS,
        "conditioning_filter": SPEECH_CONDITIONING_FILTER,
        "manifest_path": str(manifest_path),
        "raw_clips_dir": str(raw_clips_dir),
        "completed_at": datetime.datetime.now().isoformat(),
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2)

    logger.info("================================================================================")
    logger.info(f"  Vocal Extraction Complete!")
    logger.info(f"  Total Clips:    {len(manifest_records)}")
    logger.info(f"  Speech Audio:   {total_speech_sec / 60.0:.2f} minutes")
    logger.info(f"  Manifest:       {manifest_path}")
    logger.info(f"  Clips Dir:      {raw_clips_dir}")
    logger.info("================================================================================")

    return summary_data


def main() -> None:
    """CLI Entry Point."""
    parser = argparse.ArgumentParser(
        description="Scan full-length movie with VAD, isolate human dialogue, and condition speech."
    )
    parser.add_argument("--movie", "-m", default=DEFAULT_MOVIE_WIN, help="Path to input movie file")
    parser.add_argument("--ffmpeg", default=DEFAULT_FFMPEG_WIN, help="Path to FFmpeg executable")
    parser.add_argument("--output-dir", "-o", default=DEFAULT_OUTPUT_DIR, help="Output storage directory")
    parser.add_argument("--model", default="small", choices=["tiny", "base", "small", "medium", "large-v3"])
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--language", default="hi", help="Language code for ASR (default: hi for Hindi)")
    parser.add_argument("--min-clip-sec", type=float, default=MIN_CLIP_DURATION, help="Min dialogue clip length")
    parser.add_argument("--max-clip-sec", type=float, default=MAX_CLIP_DURATION, help="Max dialogue clip length")
    parser.add_argument("--max-clips", type=int, default=None, help="Optional limit on number of clips to extract")
    parser.add_argument("--scan-duration", type=float, default=None, help="Optional limit in seconds of movie to scan")
    parser.add_argument("--no-resume", action="store_true", help="Force re-extraction of all clips")

    args = parser.parse_args()

    run_pipeline(
        movie_path_str=args.movie,
        ffmpeg_path_str=args.ffmpeg,
        output_dir_str=args.output_dir,
        model_size=args.model,
        device=args.device,
        language=args.language,
        min_clip_sec=args.min_clip_sec,
        max_clip_sec=args.max_clip_sec,
        max_clips=args.max_clips,
        scan_duration=args.scan_duration,
        resume=not args.no_resume,
    )


if __name__ == "__main__":
    main()
