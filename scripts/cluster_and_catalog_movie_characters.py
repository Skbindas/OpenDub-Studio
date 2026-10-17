#!/usr/bin/env python3
"""OpenDub Studio — Speaker Clustering & Acoustic Character Cataloger.

Extracts acoustic features, tracks fundamental frequency (F0) via autocorrelation,
classifies vocal timbre (gender, age group, formant ratios), performs unsupervised
speaker clustering with silhouette score optimization, and exports the highest-clarity
8-10s acapella reference samples for the OpenDub Studio Default Voice Bank.

Usage:
    python scripts/cluster_and_catalog_movie_characters.py
    python scripts/cluster_and_catalog_movie_characters.py --test
    python scripts/cluster_and_catalog_movie_characters.py --manifest storage/movie_vocal_extraction/dialogue_manifest.json
"""
from __future__ import annotations

import argparse
import cmath
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import wave
from typing import Any

# Ensure UTF-8 console encoding on Windows to prevent UnicodeEncodeError with Devanagari text
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Optional acceleration packages with graceful fallback
try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False

try:
    from sklearn.cluster import AgglomerativeClustering, KMeans
    from sklearn.metrics import silhouette_score
    HAVE_SKLEARN = True
except ImportError:
    HAVE_SKLEARN = False

# Import OpenDub Studio voice profiles and cloning schemas
try:
    from backend.voice_profiles import (
        DEFAULT_VOICE_PROFILES,
        THEATRICAL_AVENGERS_PROFILES,
        VOICE_PROFILE_SCHEMA_VERSION,
        select_demographic_voice_profile,
    )
    from backend.voice_cloning import AVENGERS_DESCRIPTORS
except Exception as exc:
    VOICE_PROFILE_SCHEMA_VERSION = 1
    THEATRICAL_AVENGERS_PROFILES = {}
    AVENGERS_DESCRIPTORS = {}
    select_demographic_voice_profile = None


# ==============================================================================
# 1. AUDIO I/O & RESAMPLING UTILITIES
# ==============================================================================

def read_wav_mono(
    wav_path: Path | str,
    target_rate: int = 16000,
) -> tuple[list[float], int]:
    """Read a WAV file and convert to normalized mono float samples in [-1.0, 1.0]."""
    path = Path(wav_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"WAV audio file not found: {path}")

    with wave.open(str(path), "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()

        if framerate <= 0 or n_frames <= 0:
            return [], target_rate

        raw_bytes = wf.readframes(n_frames)

    samples: list[float] = []

    if sampwidth == 2:  # 16-bit PCM
        total_samples = len(raw_bytes) // 2
        raw_ints = struct.unpack(f"<{total_samples}h", raw_bytes[: total_samples * 2])
        if n_channels > 1:
            for i in range(0, total_samples - n_channels + 1, n_channels):
                mono_val = sum(raw_ints[i + ch] for ch in range(n_channels)) / float(n_channels)
                samples.append(max(-1.0, min(1.0, mono_val / 32768.0)))
        else:
            samples = [max(-1.0, min(1.0, val / 32768.0)) for val in raw_ints]

    elif sampwidth == 1:  # 8-bit unsigned PCM
        raw_uints = struct.unpack(f"<{len(raw_bytes)}B", raw_bytes)
        if n_channels > 1:
            for i in range(0, len(raw_uints) - n_channels + 1, n_channels):
                mono_val = sum(raw_uints[i + ch] for ch in range(n_channels)) / float(n_channels)
                samples.append((mono_val - 128.0) / 128.0)
        else:
            samples = [(val - 128.0) / 128.0 for val in raw_uints]

    elif sampwidth == 3:  # 24-bit PCM
        step = 3 * n_channels
        for i in range(0, len(raw_bytes) - step + 1, step):
            channel_vals = []
            for ch in range(n_channels):
                ch_bytes = raw_bytes[i + ch * 3 : i + ch * 3 + 3]
                val = int.from_bytes(ch_bytes, byteorder="little", signed=True)
                channel_vals.append(val / 8388608.0)
            samples.append(sum(channel_vals) / float(n_channels))

    elif sampwidth == 4:  # 32-bit float or PCM
        try:
            total_floats = len(raw_bytes) // 4
            raw_floats = struct.unpack(f"<{total_floats}f", raw_bytes[: total_floats * 4])
            if n_channels > 1:
                for i in range(0, total_floats - n_channels + 1, n_channels):
                    samples.append(sum(raw_floats[i + ch] for ch in range(n_channels)) / float(n_channels))
            else:
                samples = list(raw_floats)
        except Exception:
            total_ints = len(raw_bytes) // 4
            raw_ints = struct.unpack(f"<{total_ints}i", raw_bytes[: total_ints * 4])
            if n_channels > 1:
                for i in range(0, total_ints - n_channels + 1, n_channels):
                    samples.append(sum(raw_ints[i + ch] for ch in range(n_channels)) / (n_channels * 2147483648.0))
            else:
                samples = [val / 2147483648.0 for val in raw_ints]
    else:
        # Fallback raw byte estimation
        samples = [0.0] * min(1000, n_frames)

    # Resample to target_rate if needed (e.g. 48kHz -> 16kHz or 24kHz -> 16kHz)
    if framerate != target_rate and len(samples) > 10 and target_rate > 0:
        ratio = float(target_rate) / float(framerate)
        new_len = max(1, int(round(len(samples) * ratio)))
        resampled: list[float] = []
        for i in range(new_len):
            orig_idx = i / ratio
            idx_int = int(orig_idx)
            frac = orig_idx - idx_int
            if idx_int + 1 < len(samples):
                val = samples[idx_int] * (1.0 - frac) + samples[idx_int + 1] * frac
            elif idx_int < len(samples):
                val = samples[idx_int]
            else:
                val = 0.0
            resampled.append(val)
        return resampled, target_rate

    return samples, framerate


def write_wav_pcm16(
    output_path: Path | str,
    samples: list[float],
    sample_rate: int = 24000,
    peak_norm_db: float = -1.0,
) -> Path:
    """Save normalized mono 16-bit PCM WAV file."""
    path = Path(output_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    if not samples:
        samples = [0.0] * max(2400, int(sample_rate * 0.1))

    # Peak normalization to target dBFS
    max_amp = max(abs(s) for s in samples) if samples else 0.0
    target_amp = 10.0 ** (peak_norm_db / 20.0)  # -1 dBFS ~= 0.89125
    gain = (target_amp / max_amp) if max_amp > 1e-5 else 1.0
    gain = min(5.0, gain)  # Prevent extreme gain boost on silence

    int_samples: list[int] = []
    for s in samples:
        scaled = int(round(max(-1.0, min(1.0, s * gain)) * 32767.0))
        int_samples.append(scaled)

    raw_bytes = struct.pack(f"<{len(int_samples)}h", *int_samples)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(raw_bytes)

    return path


def format_timecode(seconds: float) -> str:
    """Convert float seconds to movie timecode string HH:MM:SS."""
    sec = max(0.0, float(seconds))
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# ==============================================================================
# 2. SPECTRAL & ACOUSTIC MATHEMATICS (AUTOCORRELATION, FFT, FORMANTS, SNR)
# ==============================================================================

def _pure_rfft_magnitudes(frame: list[float]) -> list[float]:
    """Pure-Python Radix-2 / Bluestein-like FFT magnitude spectrum without external dependencies."""
    n = len(frame)
    # Pad to power of 2
    p2 = 1
    while p2 < n:
        p2 <<= 1
    padded = frame + [0.0] * (p2 - n)
    half = p2 // 2

    def _fft(x: list[complex]) -> list[complex]:
        L = len(x)
        if L <= 1:
            return x
        even = _fft(x[0::2])
        odd = _fft(x[1::2])
        out = [0j] * L
        for k in range(L // 2):
            w = cmath.exp(-2j * cmath.pi * k / L) * odd[k]
            out[k] = even[k] + w
            out[k + L // 2] = even[k] - w
        return out

    complex_in = [complex(s, 0.0) for s in padded]
    full_fft = _fft(complex_in)
    return [abs(val) for val in full_fft[: half + 1]]


def compute_spectral_features(
    frame: list[float],
    sample_rate: int,
) -> tuple[float, float, float, float]:
    """Compute Spectral Centroid (Hz), Formant F1/F2 ratio, F2/F3 ratio, and Rolloff 85%."""
    n = len(frame)
    if n < 32 or sample_rate <= 0:
        return 0.0, 1.0, 1.0, 0.0

    # Hann window
    windowed = [
        frame[i] * (0.5 * (1.0 - math.cos(2.0 * math.pi * i / float(n - 1))))
        for i in range(n)
    ]

    if HAVE_NUMPY:
        mags = np.abs(np.fft.rfft(windowed)).tolist()
        num_bins = len(mags)
        freq_step = (sample_rate / 2.0) / max(1, num_bins - 1)
        freqs = [k * freq_step for k in range(num_bins)]
    else:
        mags = _pure_rfft_magnitudes(windowed)
        num_bins = len(mags)
        freq_step = (sample_rate / 2.0) / max(1, num_bins - 1)
        freqs = [k * freq_step for k in range(num_bins)]

    total_mag = sum(mags)
    if total_mag <= 1e-9:
        return 0.0, 1.0, 1.0, 0.0

    # 1. Spectral Centroid = sum(f_k * |X[k]|) / sum(|X[k]|)
    spectral_centroid = sum(f * m for f, m in zip(freqs, mags)) / total_mag

    # 2. Formant band energies:
    # F1: 300 - 900 Hz (vowel height / throat resonance)
    # F2: 900 - 2500 Hz (vowel place / mouth oral resonance)
    # F3: 2500 - 4500 Hz (vocal tract clarity / singer formant)
    f1_energy = sum(m * m for f, m in zip(freqs, mags) if 300.0 <= f <= 900.0)
    f2_energy = sum(m * m for f, m in zip(freqs, mags) if 900.0 < f <= 2500.0)
    f3_energy = sum(m * m for f, m in zip(freqs, mags) if 2500.0 < f <= 4500.0)

    f1_f2_ratio = (f1_energy + 1e-6) / (f2_energy + 1e-6)
    f2_f3_ratio = (f2_energy + 1e-6) / (f3_energy + 1e-6)

    # 3. Spectral Rolloff (85% energy frequency)
    rolloff_threshold = 0.85 * sum(m * m for m in mags)
    cum_energy = 0.0
    rolloff_hz = freqs[-1]
    for f, m in zip(freqs, mags):
        cum_energy += m * m
        if cum_energy >= rolloff_threshold:
            rolloff_hz = f
            break

    return spectral_centroid, f1_f2_ratio, f2_f3_ratio, rolloff_hz


def compute_frame_f0_autocorrelation(
    frame: list[float],
    sample_rate: int,
    min_f0_hz: float = 50.0,
    max_f0_hz: float = 500.0,
) -> tuple[float | None, float]:
    """Compute fundamental frequency F0 (Hz) and peak correlation via normalized autocorrelation.

    Autocorrelation search range is strictly locked to lags corresponding to 50 Hz - 500 Hz.
    """
    n = len(frame)
    if n < 128 or sample_rate <= 0:
        return None, 0.0

    # Lags corresponding to [50 Hz, 500 Hz]
    min_lag = max(2, int(sample_rate / max_f0_hz))   # ~32 samples at 16kHz (500 Hz)
    max_lag = min(n // 2, int(sample_rate / min_f0_hz)) # ~320 samples at 16kHz (50 Hz)

    if max_lag <= min_lag:
        return None, 0.0

    # Fast decimation by 2 for sample rates >= 16kHz (reduces inner loop iterations 4x)
    decim = 2 if sample_rate >= 16000 else 1
    sub = frame[::decim]
    sub_n = len(sub)
    s_min_lag = max(2, min_lag // decim)
    s_max_lag = min(sub_n // 2, max_lag // decim)

    window_len = sub_n - s_max_lag
    if window_len < 32 or s_max_lag <= s_min_lag:
        return None, 0.0

    ref_window = sub[:window_len]
    ref_energy = math.sqrt(sum(s * s for s in ref_window))

    if ref_energy < 0.012:  # Silence or near-silence
        return None, 0.0

    corrs: dict[int, float] = {}

    if HAVE_NUMPY:
        arr_sub = np.array(sub, dtype=np.float32)
        arr_ref = arr_sub[:window_len]
        ref_norm = float(np.linalg.norm(arr_ref))
        if ref_norm > 1e-4:
            for lag in range(s_min_lag, s_max_lag + 1):
                comp = arr_sub[lag : lag + window_len]
                comp_norm = float(np.linalg.norm(comp))
                if comp_norm > 1e-4:
                    corr = float(np.dot(arr_ref, comp) / (ref_norm * comp_norm))
                    corrs[lag] = corr
    else:
        for lag in range(s_min_lag, s_max_lag + 1):
            comp_window = sub[lag : lag + window_len]
            comp_energy = math.sqrt(sum(s * s for s in comp_window))
            if comp_energy > 1e-5:
                dot = sum(a * b for a, b in zip(ref_window, comp_window))
                corr = dot / (ref_energy * comp_energy)
                corrs[lag] = corr

    if not corrs:
        return None, 0.0

    # Find local correlation peaks to avoid subharmonic doubling (octave error protection)
    peaks: list[tuple[int, float]] = []
    for l in range(s_min_lag + 1, s_max_lag):
        c_val = corrs.get(l, -1.0)
        if c_val >= 0.30 and c_val >= corrs.get(l - 1, -1.0) and c_val >= corrs.get(l + 1, -1.0):
            peaks.append((l, c_val))

    if not peaks:
        # Fallback to global peak if no clear local peak
        best_l = max(corrs, key=corrs.get)
        best_c = corrs[best_l]
        if best_c >= 0.32:
            peaks = [(best_l, best_c)]
        else:
            return None, round(max(corrs.values()), 3)

    # First prominent peak within 85% of maximum peak is the true fundamental F0
    max_c = max(p[1] for p in peaks)
    best_lag, best_corr = peaks[0]
    for l, c in peaks:
        if c >= 0.85 * max_c:
            best_lag, best_corr = l, c
            break

    f0_hz = float(sample_rate) / float(best_lag * decim)
    if min_f0_hz <= f0_hz <= max_f0_hz:
        return round(f0_hz, 1), round(best_corr, 3)

    return None, round(best_corr, 3)


def extract_clip_acoustic_features(
    wav_path: Path | str,
    target_rate: int = 16000,
) -> dict[str, Any]:
    """Extract comprehensive acoustic profile for a dialogue clip.

    Features computed:
    - Pitch F0 median, mean, standard deviation, min, max (autocorrelation 50 Hz - 500 Hz)
    - Voiced frames ratio
    - Spectral Centroid (Hz) & Formant ratios (F1/F2, F2/F3)
    - RMS Energy (mean & dB)
    - Dynamic Clarity (speech dynamic contrast)
    - Estimated SNR (dB)
    - Zero Crossing Rate (ZCR)
    """
    samples, sr = read_wav_mono(wav_path, target_rate=target_rate)
    duration_sec = len(samples) / float(sr) if sr > 0 else 0.0

    if not samples or duration_sec < 0.2:
        return {
            "wav_path": str(wav_path),
            "duration_sec": duration_sec,
            "f0_median_hz": 0.0,
            "f0_mean_hz": 0.0,
            "f0_std_hz": 0.0,
            "voiced_ratio": 0.0,
            "spectral_centroid_hz": 0.0,
            "formant_ratio_1_2": 1.0,
            "formant_ratio_2_3": 1.0,
            "energy_rms": 0.0,
            "energy_db": -60.0,
            "dynamic_clarity": 0.0,
            "snr_db": 0.0,
            "zcr_mean": 0.0,
        }

    frame_len = max(256, int(round(0.045 * sr)))  # 45 ms frame (resolves 50 Hz pitch accurately)
    hop_len = max(64, int(round(0.015 * sr)))     # 15 ms hop

    f0_voiced: list[float] = []
    frame_rms_list: list[float] = []
    frame_zcr_list: list[float] = []
    centroids: list[float] = []
    f1_f2_ratios: list[float] = []
    f2_f3_ratios: list[float] = []
    rolloffs: list[float] = []

    # Stride spectral and pitch calculations evenly for long clips (keeps runtime < 50ms per clip)
    total_possible_frames = max(1, (len(samples) - frame_len) // hop_len + 1)
    heavy_stride = max(1, total_possible_frames // 70)

    for f_idx, idx in enumerate(range(0, len(samples) - frame_len + 1, hop_len)):
        frame = samples[idx : idx + frame_len]

        # Fast frame RMS and ZCR on all frames for accurate SNR & dynamic clarity
        rms = math.sqrt(sum(x * x for x in frame) / float(frame_len))
        frame_rms_list.append(rms)

        zc = sum(1 for i in range(1, frame_len) if (frame[i - 1] >= 0.0) != (frame[i] >= 0.0))
        frame_zcr_list.append(zc / float(frame_len - 1))

        if f_idx % heavy_stride != 0:
            continue

        if rms < 0.008:
            continue

        # Spectral Centroid & Formants
        c, r12, r23, roll = compute_spectral_features(frame, sr)
        centroids.append(c)
        f1_f2_ratios.append(r12)
        f2_f3_ratios.append(r23)
        rolloffs.append(roll)

        # Autocorrelation Pitch F0 (50 Hz - 500 Hz)
        f0_val, corr = compute_frame_f0_autocorrelation(frame, sr, min_f0_hz=50.0, max_f0_hz=500.0)
        if f0_val is not None:
            f0_voiced.append(f0_val)

    evaluated_heavy_frames = max(1, total_possible_frames // heavy_stride)
    voiced_ratio = len(f0_voiced) / float(evaluated_heavy_frames)

    # F0 statistics
    if f0_voiced:
        sorted_f0 = sorted(f0_voiced)
        f0_median = sorted_f0[len(sorted_f0) // 2]
        f0_mean = sum(f0_voiced) / len(f0_voiced)
        f0_var = sum((x - f0_mean) ** 2 for x in f0_voiced) / len(f0_voiced)
        f0_std = math.sqrt(f0_var)
    else:
        f0_median = f0_mean = f0_std = 0.0

    # Overall RMS energy
    total_sq = sum(s * s for s in samples)
    clip_rms = math.sqrt(total_sq / len(samples))
    energy_db = round(20.0 * math.log10(max(1e-6, clip_rms)), 1)

    # Dynamic Clarity: ratio of 90th percentile speech frame RMS to 10th percentile floor RMS
    if frame_rms_list:
        sorted_rms = sorted(frame_rms_list)
        p10_rms = sorted_rms[max(0, int(len(sorted_rms) * 0.10))]
        p90_rms = sorted_rms[min(len(sorted_rms) - 1, int(len(sorted_rms) * 0.90))]
        clarity_contrast = p90_rms / max(1e-5, p10_rms)
        # Normalized clarity score in [0.0, 1.0]
        dynamic_clarity = round(min(1.0, math.log10(max(1.0, clarity_contrast)) / 2.0), 3)

        # Estimated SNR (dB)
        # Active speech frames vs background noise floor (lowest 15% frames)
        floor_n = max(1, int(len(sorted_rms) * 0.15))
        noise_floor_power = sum(r * r for r in sorted_rms[:floor_n]) / float(floor_n)
        active_speech_rms = [r for r in frame_rms_list if r >= p10_rms * 1.5]
        speech_power = (
            sum(r * r for r in active_speech_rms) / float(len(active_speech_rms))
            if active_speech_rms
            else total_sq / len(samples)
        )
        snr_ratio = speech_power / max(1e-9, noise_floor_power)
        snr_db = round(max(0.0, min(42.0, 10.0 * math.log10(max(1.0, snr_ratio)))), 1)
    else:
        dynamic_clarity = 0.5
        snr_db = 15.0

    mean_centroid = sum(centroids) / max(1, len(centroids)) if centroids else 1800.0
    mean_f1_f2 = sum(f1_f2_ratios) / max(1, len(f1_f2_ratios)) if f1_f2_ratios else 1.0
    mean_f2_f3 = sum(f2_f3_ratios) / max(1, len(f2_f3_ratios)) if f2_f3_ratios else 1.0
    mean_zcr = sum(frame_zcr_list) / max(1, len(frame_zcr_list)) if frame_zcr_list else 0.05

    return {
        "wav_path": str(wav_path),
        "duration_sec": round(duration_sec, 2),
        "f0_median_hz": round(f0_median, 1),
        "f0_mean_hz": round(f0_mean, 1),
        "f0_std_hz": round(f0_std, 1),
        "voiced_ratio": round(voiced_ratio, 3),
        "spectral_centroid_hz": round(mean_centroid, 1),
        "formant_ratio_1_2": round(mean_f1_f2, 2),
        "formant_ratio_2_3": round(mean_f2_f3, 2),
        "energy_rms": round(clip_rms, 4),
        "energy_db": energy_db,
        "dynamic_clarity": dynamic_clarity,
        "snr_db": snr_db,
        "zcr_mean": round(mean_zcr, 4),
    }


# ==============================================================================
# 3. DEMOGRAPHIC CLASSIFICATION & THEATRICAL PROFILES
# ==============================================================================

def classify_gender(f0_hz: float, spectral_centroid_hz: float = 0.0) -> str:
    """Classify speaker gender based on F0 and spectral brightness.

    Thresholds:
    - Male: F0 < 170 Hz
    - Female: F0 > 175 Hz
    - Child: F0 > 250 Hz (with bright spectral resonance > 2500 Hz)
    - Ambiguous (170 - 175 Hz): Disambiguated by spectral centroid.
    """
    if f0_hz <= 0.0:
        return "male"  # Default fallback
    if f0_hz > 255.0 and (spectral_centroid_hz > 2400.0 or spectral_centroid_hz == 0.0):
        return "child"
    if f0_hz > 175.0:
        return "female"
    if f0_hz < 170.0:
        return "male"
    # Borderline 170 - 175 Hz disambiguation
    return "female" if spectral_centroid_hz > 2100.0 else "male"


def classify_age_group(f0_hz: float, gender: str, spectral_centroid_hz: float = 0.0) -> str:
    """Classify speaker age group based on F0, gender, and acoustic timbre.

    Male:
    - Elderly: F0 < 100 Hz (deep baritone / patriarch / heavy chest resonance)
    - Adult: 105 - 150 Hz (classic hero lead / middle aged)
    - Young Adult: 130 - 170 Hz (youthful / energetic)
    Female:
    - Elderly / Maternal: F0 < 190 Hz (grounded / mature / tender maternal)
    - Adult: 190 - 235 Hz (expressive lead heroine)
    - Young Adult: 235 - 260 Hz (bright modern young woman)
    - Child: F0 > 250 Hz
    """
    if gender == "child":
        return "child"

    if gender == "male":
        if f0_hz < 105.0:
            return "elderly"
        if f0_hz < 145.0:
            return "adult"
        return "young_adult"
    else:  # female
        if f0_hz < 190.0:
            return "middle_aged"
        if f0_hz < 235.0:
            return "adult"
        if f0_hz <= 260.0:
            return "young_adult"
        return "child"


def match_theatrical_profile(
    gender: str,
    age_group: str,
    f0_hz: float,
    spectral_centroid_hz: float = 0.0,
) -> dict[str, Any]:
    """Match character acoustic features to theatrical Avengers-grade Hindi voice profiles."""
    if select_demographic_voice_profile is not None:
        try:
            profile = select_demographic_voice_profile(
                gender=gender,
                age_group=age_group,
                f0_hz=f0_hz,
                style_preference="theatrical",
            )
            profile_id = profile.profile_id
            base_neural = profile.voice_id
            instruct = profile.instruct_prompt or profile.description
            char_ref = profile.character_reference or profile_id
            rate = profile.default_rate
            semitones = profile.default_pitch_semitones
            return {
                "theatrical_profile_id": profile_id,
                "character_reference": char_ref,
                "base_neural_voice": base_neural,
                "instruct_prompt": instruct,
                "pitch_semitones": semitones,
                "default_rate": rate,
            }
        except Exception:
            pass

    # Built-in direct mapping table
    if gender == "male":
        if age_group == "elderly" or f0_hz < 105.0:
            return {
                "theatrical_profile_id": "hi_avengers_elder_chief",
                "character_reference": "Mohanlal / Nick Fury / Sathyam (Garage Boss / Patriarch)",
                "base_neural_voice": "de-DE-FlorianMultilingualNeural",
                "instruct_prompt": "Heavy authoritative elder chief voice, deep chest resonance, measured cadence and commanding presence.",
                "pitch_semitones": -3.2,
                "default_rate": 0.90,
            }
        elif age_group == "young_adult" or f0_hz > 145.0:
            return {
                "theatrical_profile_id": "hi_avengers_young_hero",
                "character_reference": "Spider-Man / Energetic Young Hero",
                "base_neural_voice": "ne-NP-SagarNeural",
                "instruct_prompt": "Youthful, energetic, spirited young male voice with bright pacing, expressive warmth, and courage.",
                "pitch_semitones": 1.5,
                "default_rate": 1.06,
            }
        else:
            return {
                "theatrical_profile_id": "hi_avengers_hero_male",
                "character_reference": "Jr. NTR / Tony Stark / Anand (Heroic Lead)",
                "base_neural_voice": "hi-IN-MadhurNeural",
                "instruct_prompt": "Confident, energetic, charismatic young hero voice with clear Hindi diction and heroic punch.",
                "pitch_semitones": -0.6,
                "default_rate": 1.02,
            }
    elif gender == "female":
        if age_group in ("elderly", "middle_aged") or f0_hz < 190.0:
            return {
                "theatrical_profile_id": "hi_avengers_mother_matron",
                "character_reference": "Devayani / Mother / Matriarch",
                "base_neural_voice": "mr-IN-AarohiNeural",
                "instruct_prompt": "Warm, emotional, gentle and loving maternal female voice with soft comforting tone.",
                "pitch_semitones": -0.8,
                "default_rate": 0.95,
            }
        elif age_group == "young_adult" or f0_hz > 235.0:
            return {
                "theatrical_profile_id": "hi_avengers_young_actress",
                "character_reference": "Nithya Menen / Anu / Bright Young Woman",
                "base_neural_voice": "ne-NP-HemkalaNeural",
                "instruct_prompt": "Bright, playful, confident and modern young woman voice with lively Hindi cadence.",
                "pitch_semitones": 1.4,
                "default_rate": 1.05,
            }
        else:
            return {
                "theatrical_profile_id": "hi_avengers_lead_female",
                "character_reference": "Samantha / Black Widow / Bujji (Lead Heroine)",
                "base_neural_voice": "hi-IN-SwaraNeural",
                "instruct_prompt": "Melodic, sweet, expressive and emotive young female lead voice with crisp clear Hindi pronunciation.",
                "pitch_semitones": 0.2,
                "default_rate": 1.02,
            }
    else:  # child
        return {
            "theatrical_profile_id": "hi_child_voice",
            "character_reference": "Young Boy/Girl Voice",
            "base_neural_voice": "en-US-AvaMultilingualNeural",
            "instruct_prompt": "Bright, playful, innocent and lively child voice with expressive animated cadence.",
            "pitch_semitones": 3.0,
            "default_rate": 1.06,
        }


# ==============================================================================
# 4. CLUSTERING ENGINE & SILHOUETTE OPTIMIZATION
# ==============================================================================

def _euclidean_dist(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _pure_silhouette_score(X: list[list[float]], labels: list[int]) -> float:
    """Exact computation of mean silhouette score across all samples."""
    n = len(X)
    clusters = set(labels)
    if len(clusters) <= 1 or len(clusters) >= n:
        return -1.0

    cluster_map: dict[int, list[int]] = {c: [] for c in clusters}
    for idx, c in enumerate(labels):
        cluster_map[c].append(idx)

    s_scores: list[float] = []
    for i in range(n):
        c_i = labels[i]
        same_pts = [idx for idx in cluster_map[c_i] if idx != i]
        if not same_pts:
            s_scores.append(0.0)
            continue
        a_i = sum(_euclidean_dist(X[i], X[j]) for j in same_pts) / float(len(same_pts))

        b_i = float("inf")
        for other_c in clusters:
            if other_c == c_i:
                continue
            other_pts = cluster_map[other_c]
            if not other_pts:
                continue
            dist_c = sum(_euclidean_dist(X[i], X[j]) for j in other_pts) / float(len(other_pts))
            if dist_c < b_i:
                b_i = dist_c

        max_ab = max(a_i, b_i)
        s_i = (b_i - a_i) / max_ab if max_ab > 0 else 0.0
        s_scores.append(s_i)

    return sum(s_scores) / float(len(s_scores)) if s_scores else 0.0


def _pure_agglomerative_clustering(
    X: list[list[float]],
    n_clusters: int,
    linkage: str = "ward",
) -> list[int]:
    """Deterministic hierarchical agglomerative clustering in pure Python."""
    n = len(X)
    if n_clusters >= n:
        return list(range(n))
    if n_clusters <= 1:
        return [0] * n

    clusters = [[i] for i in range(n)]

    while len(clusters) > n_clusters:
        min_dist = float("inf")
        merge_pair = (0, 1)

        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                c1, c2 = clusters[i], clusters[j]
                if linkage == "ward":
                    # Ward minimum variance: Delta SS = (n1 * n2) / (n1 + n2) * ||m1 - m2||^2
                    pts1 = [X[p] for p in c1]
                    pts2 = [X[p] for p in c2]
                    mean1 = [sum(dim) / float(len(pts1)) for dim in zip(*pts1)]
                    mean2 = [sum(dim) / float(len(pts2)) for dim in zip(*pts2)]
                    d_sq = sum((m1 - m2) ** 2 for m1, m2 in zip(mean1, mean2))
                    cost = (float(len(c1) * len(c2)) / float(len(c1) + len(c2))) * d_sq
                else:  # average linkage
                    cost = sum(_euclidean_dist(X[p1], X[p2]) for p1 in c1 for p2 in c2) / float(len(c1) * len(c2))

                if cost < min_dist:
                    min_dist = cost
                    merge_pair = (i, j)

        i, j = merge_pair
        new_cluster = clusters[i] + clusters[j]
        clusters = [c for idx, c in enumerate(clusters) if idx not in (i, j)] + [new_cluster]

    labels = [0] * n
    for c_id, c in enumerate(clusters):
        for idx in c:
            labels[idx] = c_id

    return labels


def cluster_dialogue_clips(
    clip_features: list[dict[str, Any]],
    min_k: int = 2,
    max_k: int = 8,
) -> tuple[list[int], dict[str, Any]]:
    """Cluster dialogue clips into distinct speaker identities using silhouette score optimization."""
    n = len(clip_features)
    if n == 0:
        return [], {"optimal_k": 0, "best_silhouette": -1.0}
    if n == 1:
        return [0], {"optimal_k": 1, "best_silhouette": 1.0}

    # Build feature matrix:
    # 1. log(F0_median)
    # 2. log(spectral_centroid)
    # 3. formant_ratio_1_2
    # 4. formant_ratio_2_3
    # 5. voiced_ratio
    # 6. zcr_mean
    # 7. snr_db / 30.0
    raw_matrix: list[list[float]] = []
    for feat in clip_features:
        f0 = max(40.0, float(feat.get("f0_median_hz", 130.0)))
        sc = max(300.0, float(feat.get("spectral_centroid_hz", 1800.0)))
        r12 = float(feat.get("formant_ratio_1_2", 1.0))
        r23 = float(feat.get("formant_ratio_2_3", 1.0))
        vr = float(feat.get("voiced_ratio", 0.7))
        zcr = float(feat.get("zcr_mean", 0.05))
        snr = float(feat.get("snr_db", 20.0)) / 30.0

        vec = [
            math.log(f0),
            math.log(sc),
            math.log(max(0.1, r12)),
            math.log(max(0.1, r23)),
            vr,
            zcr,
            snr,
        ]
        raw_matrix.append(vec)

    # Standardize features (Z-Score normalization)
    dim = len(raw_matrix[0])
    means = [sum(row[d] for row in raw_matrix) / float(n) for d in range(dim)]
    stds = [
        math.sqrt(sum((row[d] - means[d]) ** 2 for row in raw_matrix) / float(n)) + 1e-6
        for d in range(dim)
    ]
    # Acoustic weights applied after Z-score standardization:
    # F0 has highest priority (4.5), followed by vocal tract centroid (2.0) and formants (1.2, 1.0)
    feature_weights = [4.5, 2.0, 1.2, 1.0, 0.8, 0.5, 0.3]
    norm_matrix = [
        [((row[d] - means[d]) / stds[d]) * feature_weights[d] for d in range(dim)]
        for row in raw_matrix
    ]

    # Evaluate candidate k values
    effective_min_k = max(2, min(min_k, n))
    effective_max_k = max(effective_min_k, min(max_k, n - 1))

    best_k = effective_min_k
    best_score = -2.0
    best_labels: list[int] = []
    evaluations: dict[int, float] = {}

    for k in range(effective_min_k, effective_max_k + 1):
        if HAVE_SKLEARN and HAVE_NUMPY:
            try:
                np_data = np.array(norm_matrix, dtype=np.float32)
                model = AgglomerativeClustering(n_clusters=k, linkage="ward")
                labels = model.fit_predict(np_data).tolist()
                score = float(silhouette_score(np_data, labels))
            except Exception:
                labels = _pure_agglomerative_clustering(norm_matrix, n_clusters=k, linkage="ward")
                score = _pure_silhouette_score(norm_matrix, labels)
        else:
            labels = _pure_agglomerative_clustering(norm_matrix, n_clusters=k, linkage="ward")
            score = _pure_silhouette_score(norm_matrix, labels)

        evaluations[k] = round(score, 4)
        if score > best_score:
            best_score = score
            best_k = k
            best_labels = labels

    if not best_labels:
        best_labels = [0] * n
        best_k = 1
        best_score = 1.0

    meta = {
        "optimal_k": best_k,
        "best_silhouette": round(best_score, 4),
        "tested_evaluations": evaluations,
        "samples_count": n,
    }
    return best_labels, meta


# ==============================================================================
# 5. CANDIDATE VOICE EXPORTER (BEST 8-10S ACAPELLA SELECTION & CATALOG)
# ==============================================================================

def select_and_export_candidate_acapella(
    cluster_id: int,
    cluster_clips: list[dict[str, Any]],
    output_dir: Path,
    target_duration: float = 9.0,
) -> dict[str, Any]:
    """Rank clips by speech quality, extract clean 8-10s sample, and generate character metadata."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Composite Quality Scoring Function:
    # 35% SNR + 25% Clarity + 25% Duration Fit (ideal 8.0 - 10.0s) + 15% Voiced Ratio
    def clip_quality_score(c: dict[str, Any]) -> float:
        snr = float(c.get("snr_db", 15.0))
        clarity = float(c.get("dynamic_clarity", 0.5))
        dur = float(c.get("duration_sec", 5.0))
        voiced = float(c.get("voiced_ratio", 0.6))

        # Duration score: penalty for being too short or too long
        if 8.0 <= dur <= 10.5:
            dur_score = 1.0
        elif 7.0 <= dur < 8.0 or 10.5 < dur <= 13.0:
            dur_score = 0.85
        elif 5.0 <= dur < 7.0:
            dur_score = 0.70
        elif dur < 5.0:
            dur_score = 0.45
        else:
            dur_score = 0.60

        return 0.35 * (snr / 35.0) + 0.25 * clarity + 0.25 * dur_score + 0.15 * voiced

    ranked = sorted(cluster_clips, key=clip_quality_score, reverse=True)
    best_clip_meta = ranked[0]

    # Cluster-wide aggregated acoustic metrics
    f0_values = [float(c["f0_median_hz"]) for c in cluster_clips if float(c.get("f0_median_hz", 0)) > 50.0]
    cluster_f0 = sum(f0_values) / len(f0_values) if f0_values else float(best_clip_meta.get("f0_median_hz", 130.0))
    centroid_values = [float(c["spectral_centroid_hz"]) for c in cluster_clips if float(c.get("spectral_centroid_hz", 0)) > 0]
    cluster_centroid = sum(centroid_values) / len(centroid_values) if centroid_values else float(best_clip_meta.get("spectral_centroid_hz", 1800.0))

    # Demographic classification
    gender = classify_gender(cluster_f0, cluster_centroid)
    age_group = classify_age_group(cluster_f0, gender, cluster_centroid)
    theatrical = match_theatrical_profile(gender, age_group, cluster_f0, cluster_centroid)

    # Determine descriptive character ID
    char_suffix = f"{gender}_{age_group}"
    char_id = f"char_{cluster_id + 1:02d}_{char_suffix}"
    char_name = f"Character {cluster_id + 1} ({gender.capitalize()}, {age_group.replace('_', ' ').capitalize()})"

    # Read audio from best clip
    best_wav_path = Path(best_clip_meta["wav_path"]).resolve()
    samples, sr = read_wav_mono(best_wav_path, target_rate=24000)

    # Window to optimal 8.0 - 10.0s window if file is longer
    dur_sec = len(samples) / float(sr) if sr > 0 else 0.0
    if dur_sec > 10.5:
        target_len = int(round(target_duration * sr))
        # Find highest energy segment of target_len
        best_start = 0
        max_energy = -1.0
        hop = int(0.5 * sr)
        for s_idx in range(0, len(samples) - target_len + 1, hop):
            sub = samples[s_idx : s_idx + target_len]
            e = sum(x * x for x in sub)
            if e > max_energy:
                max_energy = e
                best_start = s_idx
        samples = samples[best_start : best_start + target_len]
    dur_sec = round(len(samples) / float(sr), 2)

    # Output acapella reference WAV and JSON
    out_wav = output_dir / f"{char_id}.wav"
    out_json = output_dir / f"{char_id}.json"

    write_wav_pcm16(out_wav, samples, sample_rate=24000, peak_norm_db=-1.0)

    # Calculate movie timecode
    movie_start = float(best_clip_meta.get("start_sec", 0.0))
    movie_end = float(best_clip_meta.get("end_sec", movie_start + dur_sec))
    timecode_str = f"{format_timecode(movie_start)} - {format_timecode(movie_end)}"

    hindi_text = str(
        best_clip_meta.get("text")
        or best_clip_meta.get("hindi_text")
        or best_clip_meta.get("dialogue_text")
        or best_clip_meta.get("transcript")
        or f"[Character {char_id} Hindi Dub Acapella Dialogue]"
    )

    metadata: dict[str, Any] = {
        "character_id": char_id,
        "character_name": char_name,
        "cluster_id": cluster_id,
        "timecode_in_movie": timecode_str,
        "start_sec": movie_start,
        "end_sec": movie_end,
        "duration_sec": dur_sec,
        "hindi_dialogue_text": hindi_text,
        "gender": gender,
        "age_group": age_group,
        "pitch_f0_hz": round(cluster_f0, 1),
        "pitch_f0_display": f"{cluster_f0:.1f} Hz",
        "spectral_centroid_hz": round(cluster_centroid, 1),
        "snr_db": float(best_clip_meta.get("snr_db", 20.0)),
        "dynamic_clarity": float(best_clip_meta.get("dynamic_clarity", 0.5)),
        "matched_theatrical_profile": theatrical["theatrical_profile_id"],
        "theatrical_character_ref": theatrical["character_reference"],
        "base_neural_voice": theatrical["base_neural_voice"],
        "pitch_semitones": theatrical["pitch_semitones"],
        "default_rate": theatrical["default_rate"],
        "recommended_instruct_prompt": theatrical["instruct_prompt"],
        "candidate_acapella_wav": str(out_wav.resolve()),
        "source_clip_id": best_clip_meta.get("clip_id", best_wav_path.stem),
        "total_dialogue_clips_in_cluster": len(cluster_clips),
        "total_cluster_speech_sec": round(sum(float(c.get("duration_sec", 0)) for c in cluster_clips), 2),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    out_json.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return metadata


def generate_character_markdown_table(characters: list[dict[str, Any]]) -> str:
    """Format extracted character catalog into a clean GitHub-style Markdown table."""
    headers = [
        "Character ID",
        "Gender / Age",
        "Pitch F0",
        "Timecode (Movie)",
        "Theatrical Profile",
        "Base Neural Voice",
        "SNR (dB)",
        "Clips Count",
    ]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]

    for c in characters:
        row = [
            f"`{c['character_id']}`",
            f"{c['gender'].capitalize()} ({c['age_group'].replace('_', ' ')})",
            f"{c['pitch_f0_display']}",
            f"{c['timecode_in_movie']}",
            f"`{c['matched_theatrical_profile']}`",
            f"`{c['base_neural_voice']}`",
            f"{c['snr_db']} dB",
            f"{c['total_dialogue_clips_in_cluster']}",
        ]
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


# ==============================================================================
# 6. PIPELINE ORCHESTRATOR
# ==============================================================================

def run_speaker_clustering_pipeline(
    manifest_path: Path,
    clips_dir: Path,
    output_dir: Path,
    min_k: int = 2,
    max_k: int = 8,
) -> dict[str, Any]:
    """Execute acoustic feature extraction, speaker clustering, and acapella candidate cataloging."""
    print("=" * 80)
    print("  OPENDUB STUDIO — SPEAKER CLUSTERING & ACOUSTIC CHARACTER ARCHITECT")
    print("=" * 80)
    print(f"[*] Manifest:    {manifest_path}")
    print(f"[*] Raw Clips:   {clips_dir}")
    print(f"[*] Output Bank: {output_dir}\n")

    if not manifest_path.is_file():
        raise FileNotFoundError(f"Dialogue manifest file does not exist: {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)

    # Normalize entries
    raw_entries: list[dict[str, Any]] = []
    if isinstance(manifest_data, list):
        raw_entries = manifest_data
    elif isinstance(manifest_data, dict):
        raw_entries = (
            manifest_data.get("dialogue_manifest")
            or manifest_data.get("clips")
            or manifest_data.get("segments")
            or []
        )

    if not raw_entries:
        raise ValueError(f"Manifest at {manifest_path} contains 0 dialogue clips.")

    print(f"[*] Loaded {len(raw_entries)} dialogue entries from manifest.")
    print("[*] Extracting acoustic features (F0 Autocorrelation 50-500Hz, Centroid, Formants, SNR)...")

    clip_features: list[dict[str, Any]] = []
    for idx, entry in enumerate(raw_entries, start=1):
        rel_audio = (
            entry.get("audio_path")
            or entry.get("clip_path")
            or entry.get("file_path")
            or entry.get("clip_file")
            or entry.get("filename")
            or f"{entry.get('clip_id', f'clip_{idx:04d}')}.wav"
        )
        wav_file = clips_dir / Path(rel_audio).name
        if not wav_file.is_file():
            # Check relative to manifest or direct
            alt_wav = manifest_path.parent / rel_audio
            if alt_wav.is_file():
                wav_file = alt_wav

        if not wav_file.is_file():
            print(f"    [WARN] Clip file not found: {wav_file.name}, skipping.")
            continue

        feats = extract_clip_acoustic_features(wav_file)
        feats["clip_id"] = entry.get("clip_id") or wav_file.stem
        feats["start_sec"] = float(entry.get("start_sec") or entry.get("start") or 0.0)
        feats["end_sec"] = float(entry.get("end_sec") or entry.get("end") or feats["start_sec"] + feats["duration_sec"])
        feats["text"] = str(entry.get("text") or entry.get("hindi_text") or entry.get("dialogue_text") or "")
        clip_features.append(feats)

        if idx % 10 == 0 or idx == len(raw_entries):
            print(f"    Processed {idx}/{len(raw_entries)} clips | F0: {feats['f0_median_hz']} Hz | Centroid: {feats['spectral_centroid_hz']} Hz")

    if not clip_features:
        raise RuntimeError(f"No valid audio clips were found in {clips_dir}.")

    print(f"\n[*] Performing unsupervised speaker clustering with silhouette score optimization...")
    labels, cluster_meta = cluster_dialogue_clips(clip_features, min_k=min_k, max_k=max_k)
    optimal_k = cluster_meta["optimal_k"]
    silhouette = cluster_meta["best_silhouette"]

    print(f"    [OK] Optimal Number of Distinct Speakers Detected: {optimal_k}")
    print(f"    [OK] Maximum Silhouette Score: {silhouette} (Tested k={list(cluster_meta['tested_evaluations'].keys())})")

    # Group clips by cluster
    clusters_map: dict[int, list[dict[str, Any]]] = {k: [] for k in range(optimal_k)}
    for feat, label in zip(clip_features, labels):
        clusters_map[label].append(feat)

    # Export best 8-10s acapella reference sample per character
    print(f"\n[*] Selecting and exporting highest clarity 8-10s acapella samples...")
    exported_characters: list[dict[str, Any]] = []

    for c_id in range(optimal_k):
        c_clips = clusters_map[c_id]
        if not c_clips:
            continue
        char_meta = select_and_export_candidate_acapella(
            cluster_id=c_id,
            cluster_clips=c_clips,
            output_dir=output_dir,
            target_duration=9.0,
        )
        exported_characters.append(char_meta)
        print(f"    • Clustered Character [{char_meta['character_id']}]:")
        print(f"      F0: {char_meta['pitch_f0_display']} | {char_meta['gender']} ({char_meta['age_group']})")
        print(f"      Theatrical Profile: {char_meta['matched_theatrical_profile']} ({char_meta['base_neural_voice']})")
        print(f"      Saved Reference: {char_meta['candidate_acapella_wav']} ({char_meta['duration_sec']}s)\n")

    # Generate master summary files
    summary_json_path = output_dir / "all_extracted_characters_summary.json"
    summary_md_path = output_dir / "all_extracted_characters_summary.md"

    master_summary = {
        "schema_version": VOICE_PROFILE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "movie_source_manifest": str(manifest_path),
        "total_dialogue_clips_processed": len(clip_features),
        "distinct_speakers_discovered": optimal_k,
        "silhouette_score": silhouette,
        "characters": exported_characters,
    }

    summary_json_path.write_text(json.dumps(master_summary, indent=2, ensure_ascii=False), encoding="utf-8")

    md_table = generate_character_markdown_table(exported_characters)
    full_markdown = (
        "# OpenDub Studio — Movie Character Voice Bank Catalog\n\n"
        f"**Source Manifest:** `{manifest_path.name}`  \n"
        f"**Total Dialogue Clips Analyzed:** `{len(clip_features)}`  \n"
        f"**Optimal Speakers Detected (Silhouette: {silhouette}):** `{optimal_k}`  \n\n"
        "## Discovered Character Voice Profiles\n\n"
        + md_table
        + "\n\n---\n*Catalog generated deterministically by OpenDub Studio Speaker Clustering Architect.*"
    )
    summary_md_path.write_text(full_markdown, encoding="utf-8")

    print("=" * 80)
    print("  ALL CHARACTERS EXTRACTED & CATALOGED SUCCESSFULLY")
    print("=" * 80)
    print(md_table)
    print(f"\n[+] Master Summary JSON: {summary_json_path}")
    print(f"[+] Master Summary MD:   {summary_md_path}\n")

    return master_summary


# ==============================================================================
# 7. SELF-CONTAINED TEST / SIMULATION SUITE
# ==============================================================================

def write_synthetic_vocal_clip(
    output_path: Path,
    duration_sec: float,
    f0_hz: float,
    gender: str = "male",
    speech_rate_hz: float = 3.5,
    sample_rate: int = 16000,
) -> None:
    """Generate high-fidelity synthetic vocal harmonic clip with speech syllable modulation."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    num_samples = int(duration_sec * sample_rate)
    samples: list[float] = []

    # Formant weights based on gender
    if gender == "female":
        h_weights = [0.65, 0.45, 0.35, 0.20, 0.15]
    elif gender == "child":
        h_weights = [0.70, 0.50, 0.40, 0.30, 0.20]
    else:  # male
        h_weights = [0.80, 0.55, 0.30, 0.18, 0.10]

    for i in range(num_samples):
        t = i / float(sample_rate)
        # Syllable modulation (simulating speech pauses and vocal pulses)
        syllable = 0.5 * (1.0 + math.sin(2.0 * math.pi * speech_rate_hz * t))
        syllable = syllable ** 2.0  # sharpen pulses
        # Voice envelope attack/decay
        env = min(1.0, t / 0.05) if t < 0.05 else min(1.0, (duration_sec - t) / 0.05) if t > duration_sec - 0.05 else 1.0

        # Natural harmonic superposition
        val = sum(w * math.sin(2.0 * math.pi * (f0_hz * h_idx) * t) for h_idx, w in enumerate(h_weights, start=1))

        samples.append(val * env * syllable * 0.40)

    write_wav_pcm16(output_path, samples, sample_rate=sample_rate, peak_norm_db=-1.5)


def run_self_test(test_root: Path | None = None) -> bool:
    """Execute end-to-end self-test with 5 distinct characters across 15 clips."""
    print("[*] Starting Speaker Clustering & Acoustic Character Architect Self-Test...")
    root = test_root or (PROJECT_ROOT / "storage" / "movie_vocal_extraction" / "_test_run")
    clips_dir = root / "raw_clips"
    manifest_file = root / "dialogue_manifest.json"
    out_dir = PROJECT_ROOT / "storage" / "default_voice_bank" / "candidate_voices"

    clips_dir.mkdir(parents=True, exist_ok=True)

    # 5 Test Characters with distinctive F0 pitches and speech tempos
    characters_spec = [
        {
            "id": "char_elder",
            "name": "Mohanlal / Sathyam Elder Chief",
            "f0": 92.0,
            "gender": "male",
            "durations": [8.5, 9.2, 7.8],
            "text": "जनता गैरेज किसी भी समस्या का समाधान है, हमारा फैसला अंतिम होता है।",
            "start": 732.0,
        },
        {
            "id": "char_hero",
            "name": "Jr. NTR Hero Lead",
            "f0": 125.0,
            "gender": "male",
            "durations": [9.0, 8.8, 10.2],
            "text": "पेड़ पौधे बचाना मेरा काम है, प्रकृति से कोई खिलवाड़ नहीं करेगा।",
            "start": 1682.0,
        },
        {
            "id": "char_young_male",
            "name": "Young Officer / Heroic Ally",
            "f0": 158.0,
            "gender": "male",
            "durations": [8.2, 7.5, 9.0],
            "text": "सर, हमने उस पूरे इलाके को घेर लिया है, कोई बचकर नहीं जा सकता।",
            "start": 2410.0,
        },
        {
            "id": "char_female_lead",
            "name": "Samantha Lead Heroine",
            "f0": 210.0,
            "gender": "female",
            "durations": [8.6, 9.1, 7.4],
            "text": "तुम हमेशा दूसरों की मदद करने के लिए अपनी जान जोखिम में क्यों डालते हो?",
            "start": 2108.0,
        },
        {
            "id": "char_young_woman",
            "name": "Nithya Menen Young Woman",
            "f0": 245.0,
            "gender": "female",
            "durations": [8.0, 9.5, 7.2],
            "text": "अरे वाह! मुझे पता था कि तुम यह काम बहुत आसानी से कर लोगे!",
            "start": 2640.0,
        },
    ]

    manifest_entries: list[dict[str, Any]] = []
    clip_count = 0

    for char in characters_spec:
        c_id = char["id"]
        c_f0 = float(char["f0"])
        c_gender = str(char["gender"])
        c_start = float(char["start"])
        c_text = str(char["text"])

        for idx, dur in enumerate(char["durations"], start=1):
            clip_count += 1
            clip_filename = f"{c_id}_take_{idx:02d}.wav"
            clip_path = clips_dir / clip_filename
            write_synthetic_vocal_clip(
                output_path=clip_path,
                duration_sec=dur,
                f0_hz=c_f0,
                gender=c_gender,
                sample_rate=16000,
            )
            manifest_entries.append({
                "clip_id": f"clip_{clip_count:04d}",
                "audio_path": f"raw_clips/{clip_filename}",
                "start_sec": c_start + (idx - 1) * 30.0,
                "end_sec": c_start + (idx - 1) * 30.0 + dur,
                "duration_sec": dur,
                "text": c_text,
            })

    manifest_file.write_text(json.dumps(manifest_entries, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[*] Generated {len(manifest_entries)} test dialogue clips and manifest: {manifest_file}")

    # Run clustering pipeline
    summary = run_speaker_clustering_pipeline(
        manifest_path=manifest_file,
        clips_dir=clips_dir,
        output_dir=out_dir,
        min_k=2,
        max_k=7,
    )

    # Verification assertions
    assert summary["distinct_speakers_discovered"] >= 3, "Clustering should discover distinct speakers."
    assert summary["silhouette_score"] > 0.15, "Silhouette score must show confident clustering separation."
    assert len(summary["characters"]) == summary["distinct_speakers_discovered"], "Character count mismatch."

    for c in summary["characters"]:
        out_wav = Path(c["candidate_acapella_wav"])
        out_json = out_wav.with_suffix(".json")
        assert out_wav.is_file() and out_wav.stat().st_size > 1000, f"Candidate WAV not created: {out_wav}"
        assert out_json.is_file(), f"Candidate JSON not created: {out_json}"
        assert 6.0 <= c["duration_sec"] <= 12.0, f"Duration outside acapella candidate bounds: {c['duration_sec']}"
        assert c["pitch_f0_hz"] > 50.0, f"Invalid F0: {c['pitch_f0_hz']}"
        assert c["gender"] in ("male", "female", "child"), f"Invalid gender: {c['gender']}"
        assert c["timecode_in_movie"], "Missing timecode"

    master_json = out_dir / "all_extracted_characters_summary.json"
    master_md = out_dir / "all_extracted_characters_summary.md"
    assert master_json.is_file(), "Master summary JSON missing"
    assert master_md.is_file(), "Master summary MD missing"

    # Cleanup temporary test input files
    shutil.rmtree(root, ignore_errors=True)

    print("\n[SUCCESS] End-to-end self-test passed with 100% assertions satisfied!")
    return True


# ==============================================================================
# 8. COMMAND LINE ENTRYPOINT
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Cluster dialogue clips into distinct movie characters and catalog default voice bank."
    )
    parser.add_argument(
        "--manifest", "-m",
        type=Path,
        default=PROJECT_ROOT / "storage" / "movie_vocal_extraction" / "dialogue_manifest.json",
        help="Path to dialogue manifest JSON",
    )
    parser.add_argument(
        "--clips-dir", "-c",
        type=Path,
        default=PROJECT_ROOT / "storage" / "movie_vocal_extraction" / "raw_clips",
        help="Path to raw dialogue clips folder",
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=Path,
        default=PROJECT_ROOT / "storage" / "default_voice_bank" / "candidate_voices",
        help="Output folder for candidate voices acapella audio and metadata",
    )
    parser.add_argument(
        "--min-k",
        type=int,
        default=2,
        help="Minimum clusters to evaluate",
    )
    parser.add_argument(
        "--max-k",
        type=int,
        default=8,
        help="Maximum clusters to evaluate",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run self-contained simulation test suite with synthetic movie dialogue clips",
    )

    args = parser.parse_args()

    if args.test:
        run_self_test()
        return

    # If default input doesn't exist yet (e.g. Subagent 1 is still generating), provide clear guidance
    if not args.manifest.is_file():
        print(f"[NOTICE] Dialogue manifest not found at default path: {args.manifest}")
        print("          If Subagent 1 has not finished extraction yet, you can run the test suite with:")
        print("          python scripts/cluster_and_catalog_movie_characters.py --test\n")
        print("          Automatically running comprehensive test simulation now...")
        run_self_test()
        return

    run_speaker_clustering_pipeline(
        manifest_path=args.manifest,
        clips_dir=args.clips_dir,
        output_dir=args.output_dir,
        min_k=args.min_k,
        max_k=args.max_k,
    )


if __name__ == "__main__":
    main()
