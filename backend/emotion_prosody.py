"""Phase 25: Emotion & Prosody Preservation Engine.

Implements PRD Section 13 & Section 26:
1. Multimodal emotion & prosody extraction combining:
   - Source Audio Features: F0 mean/range/slope, RMS energy/dBFS contour, speaking rate,
     internal pause distribution, and voice quality indicators (whisper, shout, breathiness, tremor).
   - Dialogue Context: punctuation/discourse markers, neighboring segment context,
     scene emotional arc, and acoustic-vs-lexical discrepancy (e.g., quiet intensity / sarcasm).
2. Structured Prosody Representation per PRD §13.2.
3. Bounded Prosody Transfer Rules per PRD §13.3 (safe rate/pitch/volume controls coordinated
   with segment duration windows so adjustments never cause cartoon pitch shifts or compounding).
4. Source-vs-Dubbed Emotion/Prosody QA per PRD §13.4 (energy delta, speaking rate delta,
   pitch contour compatibility, pause compatibility, and flatness/robotic delivery detection).
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from backend.speaker_engine import _read_pcm16_mono_slice


URGENT_MARKERS = (
    "快", "赶紧", "小心", "马上", "别", "相信我", "求", "救", "跑", "危险",
    "भरोसा", "जल्दी", "रुको", "मत", "बचाओ", "ध्यान", "तुरंत",
    "hurry", "trust me", "wait", "stop", "now", "careful", "run",
)
REASSURING_MARKERS = (
    "相信我", "没事", "放心", "别怕", "有我", "好", "可以",
    "भरोसा", "चिंता", "ठीक", "डरो मत", "शांत",
    "trust", "okay", "fine", "safe", "worry",
)
QUESTION_MARKERS = (
    "吗", "呢", "怎么", "为什么", "谁", "哪", "什么", "真的",
    "क्या", "क्यों", "कैसे", "कौन", "कहाँ", "सच",
    "what", "why", "how", "who", "where", "really",
)
CONFRONTATIONAL_MARKERS = (
    "滚", "闭嘴", "混蛋", "敢", "绝不", "骗", "胡说",
    "चुप", "झूठ", "कभी नहीं", "हिम्मत",
    "shut up", "lie", "never", "dare",
)


def analyze_audio_prosody_features(
    samples: list[float],
    sample_rate: int = 16000,
    duration_sec: float | None = None,
) -> dict[str, Any]:
    """Measure F0 contour (mean, range, slope), energy dynamics, pauses, and voice quality."""
    actual_dur = duration_sec if (duration_sec and duration_sec > 0) else (
        len(samples) / float(max(1, sample_rate))
    )
    if not samples or sample_rate <= 0:
        return {
            "duration_sec": round(actual_dur, 3),
            "f0_mean_hz": 0.0,
            "f0_range_hz": 0.0,
            "f0_slope_hz_per_sec": 0.0,
            "f0_std_hz": 0.0,
            "rms_mean": 0.0,
            "rms_peak": 0.0,
            "rms_db": -60.0,
            "dynamic_range_db": 0.0,
            "pause_ratio": 0.0,
            "internal_pause_count": 0,
            "pause_before_ms": 0,
            "pause_after_ms": 0,
            "voiced_ratio": 0.0,
            "zcr_mean": 0.0,
            "f0_jitter_ratio": 0.0,
            "voice_quality": "neutral_modal",
        }

    frame_len = max(64, int(round(0.025 * sample_rate)))
    hop_len = max(32, int(round(0.010 * sample_rate)))
    min_lag = max(2, int(sample_rate / 420.0))
    max_lag = max(min_lag + 1, int(sample_rate / 65.0))

    total_possible = max(1, (len(samples) - frame_len) // hop_len + 1)
    stride = max(1, total_possible // 120)
    frame_step_sec = (hop_len * stride) / float(sample_rate)

    rms_contour: list[float] = []
    zcr_contour: list[float] = []
    f0_points: list[tuple[float, float]] = []

    for f_idx, start in enumerate(range(0, max(1, len(samples) - frame_len + 1), hop_len * stride)):
        frame = samples[start : start + frame_len]
        if len(frame) < frame_len:
            break
        t_sec = f_idx * frame_step_sec
        energy = sum(x * x for x in frame) / frame_len
        rms = math.sqrt(energy)
        rms_contour.append(rms)

        zc = sum(1 for i in range(1, frame_len) if (frame[i - 1] >= 0.0) != (frame[i] >= 0.0))
        zcr_contour.append(zc / float(frame_len - 1))

        if rms < 0.010:
            continue

        decim = 2 if sample_rate >= 16000 else 1
        sub = frame[::decim]
        sub_n = len(sub)
        sub_e = sum(x * x for x in sub)
        if sub_e <= 1e-8:
            continue
        best_c = 0.0
        best_l = 0
        for lag in range(max(2, min_lag // decim), min(sub_n // 2, max_lag // decim) + 1):
            c = sum(sub[j] * sub[j + lag] for j in range(sub_n - lag)) / sub_e
            if c > best_c:
                best_c = c
                best_l = lag
        if best_c >= 0.30 and best_l > 0:
            f0 = float(sample_rate) / float(best_l * decim)
            if 65.0 <= f0 <= 420.0:
                f0_points.append((t_sec, f0))

    if not rms_contour:
        rms_contour = [0.0]

    rms_mean = sum(rms_contour) / len(rms_contour)
    rms_peak = max(rms_contour)
    rms_db = 20.0 * math.log10(max(rms_mean, 1e-5))
    rms_sorted = sorted(rms_contour)
    p10 = max(1e-5, rms_sorted[max(0, int(0.10 * len(rms_sorted)))])
    p90 = max(1e-5, rms_sorted[min(len(rms_sorted) - 1, int(0.90 * len(rms_sorted)))])
    dynamic_range_db = max(0.0, 20.0 * math.log10(p90 / p10))

    # Measure leading/trailing/internal pauses
    silence_thresh = max(0.008, rms_peak * 0.12)
    active_flags = [r >= silence_thresh for r in rms_contour]
    if any(active_flags):
        first_active = active_flags.index(True)
        last_active = len(active_flags) - 1 - active_flags[::-1].index(True)
        pause_before_ms = int(round(first_active * frame_step_sec * 1000.0))
        pause_after_ms = int(round((len(active_flags) - 1 - last_active) * frame_step_sec * 1000.0))
        interior = active_flags[first_active : last_active + 1]
        silent_frames = sum(1 for flag in interior if not flag)
        pause_ratio = silent_frames / float(max(1, len(interior)))
        # Count contiguous internal silent runs >= 120 ms
        min_run = max(1, int(round(0.12 / max(0.005, frame_step_sec))))
        internal_pause_count = 0
        cur_run = 0
        for flag in interior:
            if not flag:
                cur_run += 1
            else:
                if cur_run >= min_run:
                    internal_pause_count += 1
                cur_run = 0
    else:
        pause_before_ms = 0
        pause_after_ms = 0
        pause_ratio = 1.0
        internal_pause_count = 0

    # F0 contour stats
    voiced_ratio = len(f0_points) / float(max(1, len(rms_contour)))
    if f0_points:
        f0_vals = [p[1] for p in f0_points]
        f0_mean = sum(f0_vals) / len(f0_vals)
        f0_std = math.sqrt(sum((x - f0_mean) ** 2 for x in f0_vals) / len(f0_vals))
        f0_sorted = sorted(f0_vals)
        f0_range = f0_sorted[min(len(f0_sorted) - 1, int(0.90 * len(f0_sorted)))] - f0_sorted[max(0, int(0.10 * len(f0_sorted)))]
        # Linear regression slope over time
        if len(f0_points) >= 2:
            t_mean = sum(p[0] for p in f0_points) / len(f0_points)
            num = sum((p[0] - t_mean) * (p[1] - f0_mean) for p in f0_points)
            den = sum((p[0] - t_mean) ** 2 for p in f0_points)
            f0_slope = num / den if den > 1e-6 else 0.0
            jitter = sum(abs(f0_vals[i] - f0_vals[i - 1]) for i in range(1, len(f0_vals))) / (
                (len(f0_vals) - 1) * max(1.0, f0_mean)
            )
        else:
            f0_slope = 0.0
            jitter = 0.0
    else:
        f0_mean = f0_std = f0_range = f0_slope = jitter = 0.0

    zcr_mean = sum(zcr_contour) / max(1, len(zcr_contour))

    # Voice quality indicator classification
    if rms_mean > 0.14 and f0_range > 55.0:
        voice_quality = "shout_or_projected"
    elif voiced_ratio < 0.28 and zcr_mean > 0.14 and rms_mean > 0.008:
        voice_quality = "whisper_or_breathy"
    elif jitter > 0.12 and f0_std > 28.0:
        voice_quality = "tremor_or_tense"
    elif voiced_ratio < 0.42 and zcr_mean > 0.10:
        voice_quality = "breathy_soft"
    else:
        voice_quality = "modal_clear"

    return {
        "duration_sec": round(actual_dur, 3),
        "f0_mean_hz": round(f0_mean, 2),
        "f0_range_hz": round(f0_range, 2),
        "f0_slope_hz_per_sec": round(f0_slope, 2),
        "f0_std_hz": round(f0_std, 2),
        "rms_mean": round(rms_mean, 4),
        "rms_peak": round(rms_peak, 4),
        "rms_db": round(rms_db, 2),
        "dynamic_range_db": round(dynamic_range_db, 2),
        "pause_ratio": round(pause_ratio, 3),
        "internal_pause_count": internal_pause_count,
        "pause_before_ms": min(400, max(0, pause_before_ms)),
        "pause_after_ms": min(400, max(0, pause_after_ms)),
        "voiced_ratio": round(voiced_ratio, 3),
        "zcr_mean": round(zcr_mean, 4),
        "f0_jitter_ratio": round(jitter, 4),
        "voice_quality": voice_quality,
    }


def _extract_emphasis_tokens(text: str, max_tokens: int = 2) -> list[str]:
    """Identify emphasis tokens from Hindi/English/Chinese text."""
    if not text:
        return []
    cleaned = re.sub(r"[，。！？,.!?\"'“”‘’—…()（）]", " ", text).strip()
    words = [w for w in cleaned.split() if len(w) >= 2]
    if not words:
        # CJK fallback: take 2-character semantic phrases
        cjk = re.sub(r"\s+", "", cleaned)
        if len(cjk) >= 2:
            return [cjk[: min(3, len(cjk))]]
        return [cjk] if cjk else []

    priority = [w for w in words if any(m in w.lower() for m in ("भरोसा", "जल्दी", "रुको", "मत", "बस", "क्या", "क्यों"))]
    if priority:
        return priority[:max_tokens]
    # Otherwise pick longest content token(s)
    ranked = sorted(words, key=lambda w: len(w), reverse=True)
    return ranked[:max_tokens]


def build_segment_prosody_profile(
    segment: dict[str, Any],
    audio_features: dict[str, Any],
    character_baseline: dict[str, Any] | None = None,
    prev_segment: dict[str, Any] | None = None,
    next_segment: dict[str, Any] | None = None,
    scene_emotional_tone: str = "conversational_dramatic",
) -> dict[str, Any]:
    """Build the PRD §13.2 structured prosody representation from audio + dialogue context."""
    seg_id = segment.get("segment_id", segment.get("index", 1))
    char_id = str(segment.get("character_id") or "CHAR_001")
    source_text = str(segment.get("source_text") or segment.get("original_text") or "").strip()
    target_text = str(
        segment.get("adapted_text")
        or segment.get("translated_text")
        or segment.get("text")
        or ""
    ).strip()
    combined_text = f"{source_text} {target_text}".lower()

    dur = max(0.2, float(segment.get("target_duration") or segment.get("end", 1.0) - segment.get("start", 0.0)))
    char_count = max(1, len(re.sub(r"\s+", "", target_text or source_text)))
    chars_per_sec = char_count / dur

    base_f0 = float((character_baseline or {}).get("pitch_baseline_hz", 170.0) or 170.0)
    base_rms = float((character_baseline or {}).get("energy_baseline", 0.065) or 0.065)
    base_rate = float((character_baseline or {}).get("speaking_rate_baseline", 4.5) or 4.5)

    f0_mean = float(audio_features.get("f0_mean_hz", 0.0))
    f0_slope = float(audio_features.get("f0_slope_hz_per_sec", 0.0))
    f0_range = float(audio_features.get("f0_range_hz", 0.0))
    rms_mean = float(audio_features.get("rms_mean", 0.05))
    voice_quality = str(audio_features.get("voice_quality", "modal_clear"))

    # Contextual discourse markers
    has_exclamation = "!" in source_text or "！" in source_text or "!" in target_text
    has_question = "?" in source_text or "？" in source_text or "?" in target_text or any(
        q in combined_text for q in QUESTION_MARKERS
    )
    has_ellipsis = "..." in source_text or "…" in source_text or "..." in target_text
    is_urgent = any(m in combined_text for m in URGENT_MARKERS)
    is_reassuring = any(m in combined_text for m in REASSURING_MARKERS)
    is_confrontational = any(m in combined_text for m in CONFRONTATIONAL_MARKERS)

    # Neighboring dialogue turn reactivity
    neighbor_exclamatory = False
    if prev_segment:
        prev_txt = str(prev_segment.get("source_text") or prev_segment.get("text") or "")
        neighbor_exclamatory = "!" in prev_txt or "！" in prev_txt or "?" in prev_txt or "？" in prev_txt

    # Relative acoustic ratios against character baseline
    energy_ratio = rms_mean / max(0.015, base_rms)
    pitch_ratio = f0_mean / max(80.0, base_f0) if f0_mean > 0 else 1.0
    rate_ratio = chars_per_sec / max(2.0, base_rate)

    # Classify energy_level (prioritize measured acoustic energy over punctuation)
    if energy_ratio >= 1.35 or rms_mean >= 0.12:
        energy_level = "high"
    elif energy_ratio <= 0.65 or voice_quality in ("whisper_or_breathy", "breathy_soft"):
        energy_level = "low_intimate"
    elif energy_ratio >= 1.05 or rms_mean >= 0.065 or has_exclamation:
        energy_level = "medium_high"
    else:
        energy_level = "medium"

    # Classify pitch_contour
    if has_question or f0_slope >= 12.0:
        pitch_contour = "rising_interrogative"
    elif has_exclamation or f0_slope <= -10.0 or is_reassuring:
        pitch_contour = "falling_assertive"
    elif f0_range >= 45.0:
        pitch_contour = "dynamic_expressive"
    elif f0_range <= 14.0 and f0_mean > 0:
        pitch_contour = "sustained_controlled"
    else:
        pitch_contour = "balanced_conversational"

    # Classify speaking_rate
    if chars_per_sec >= 6.2 or rate_ratio >= 1.22 or (dur <= 1.65 and has_exclamation):
        speaking_rate = "compact_fast"
    elif chars_per_sec <= 3.2 or has_ellipsis or audio_features.get("pause_ratio", 0.0) >= 0.30:
        speaking_rate = "measured_deliberate"
    else:
        speaking_rate = "natural_conversational"

    # Multimodal emotion classification (Audio + Context)
    if is_reassuring and (is_urgent or has_exclamation or dur <= 1.8):
        primary_emotion = "reassuring_urgent"
        secondary_emotion = "protective"
    elif is_confrontational and energy_level in ("high", "medium_high"):
        primary_emotion = "confrontational_intense"
        secondary_emotion = "defiant"
    elif is_urgent and energy_level in ("high", "medium_high"):
        primary_emotion = "urgent_alert"
        secondary_emotion = "commanding"
    elif is_urgent and energy_level == "low_intimate":
        # Audio disambiguates whispered urgency from high-volume shouting!
        primary_emotion = "whispered_urgent"
        secondary_emotion = "tense_concealed"
    elif has_exclamation and energy_level == "low_intimate":
        # Quiet intensity or restrained sarcasm detected via low acoustic energy + strong text marker
        primary_emotion = "restrained_intensity"
        secondary_emotion = "guarded_ironic"
    elif has_question and (energy_level in ("high", "medium_high") or neighbor_exclamatory):
        primary_emotion = "probing_urgent"
        secondary_emotion = "concerned"
    elif has_question:
        primary_emotion = "inquisitive"
        secondary_emotion = "attentive"
    elif has_ellipsis or voice_quality in ("whisper_or_breathy", "breathy_soft"):
        primary_emotion = "hesitant_reflective"
        secondary_emotion = "vulnerable"
    elif energy_level in ("high", "medium_high") or has_exclamation:
        primary_emotion = "assertive_engaged"
        secondary_emotion = "resolute"
    else:
        primary_emotion = "composed_conversational"
        secondary_emotion = "steady"

    # Compute bounded intensity in [0.25, 0.96]
    raw_intensity = (
        0.38
        + 0.22 * min(1.5, energy_ratio)
        + 0.15 * min(1.5, f0_range / 45.0)
        + (0.12 if has_exclamation or is_urgent else 0.0)
        + (0.06 if neighbor_exclamatory else 0.0)
    )
    intensity = round(max(0.25, min(0.96, raw_intensity)), 2)

    # Compute safe, bounded TTS controls per PRD §13.3
    # Rate within [-10%, +12%], Pitch within [-4Hz, +4Hz], Volume within [-5%, +8%]
    if speaking_rate == "compact_fast":
        rate_pct = min(10, max(3, int(round((rate_ratio - 1.0) * 20.0)) or 6))
    elif speaking_rate == "measured_deliberate":
        rate_pct = max(-8, min(-2, int(round((rate_ratio - 1.0) * 18.0)) or -4))
    else:
        rate_pct = 0

    if pitch_contour == "rising_interrogative":
        pitch_hz = min(3, max(1, int(round((pitch_ratio - 1.0) * 10.0)) or 2))
    elif pitch_contour == "falling_assertive":
        pitch_hz = 1 if is_urgent else 0
    elif energy_level == "low_intimate":
        pitch_hz = -1
    else:
        pitch_hz = 0

    if energy_level == "high":
        vol_pct = 5
    elif energy_level == "medium_high":
        vol_pct = 3
    elif energy_level == "low_intimate":
        vol_pct = -3
    else:
        vol_pct = 0

    tts_controls = {
        "rate": f"{rate_pct:+d}%",
        "pitch": f"{pitch_hz:+d}Hz",
        "volume": f"{vol_pct:+d}%",
    }

    emphasis_tokens = _extract_emphasis_tokens(target_text or source_text)
    confidence = round(
        min(
            0.96,
            0.72
            + (0.12 if audio_features.get("voiced_ratio", 0.0) >= 0.25 else 0.04)
            + (0.08 if target_text and source_text else 0.0),
        ),
        2,
    )

    return {
        "segment_id": seg_id,
        "character_id": char_id,
        "scene_emotional_tone": scene_emotional_tone,
        "primary_emotion": primary_emotion,
        "secondary_emotion": secondary_emotion,
        "intensity": intensity,
        "energy_level": energy_level,
        "pitch_contour": pitch_contour,
        "speaking_rate": speaking_rate,
        "pause_before_ms": min(120, int(audio_features.get("pause_before_ms", 0))),
        "pause_after_ms": min(120, int(audio_features.get("pause_after_ms", 40) or 40)),
        "emphasis_tokens": emphasis_tokens,
        "tts_controls": tts_controls,
        "confidence": confidence,
        "source_acoustics": audio_features,
    }


def evaluate_prosody_qa(
    source_features: dict[str, Any],
    dubbed_features: dict[str, Any],
    prosody_profile: dict[str, Any],
    target_duration_sec: float | None = None,
) -> dict[str, Any]:
    """Compare source vs. dubbed segment acoustics & prosody per PRD §13.4."""
    src_db = float(source_features.get("rms_db", -24.0))
    dub_db = float(dubbed_features.get("rms_db", -24.0))
    energy_delta_db = round(abs(dub_db - src_db), 2)

    src_dur = max(0.1, float(source_features.get("duration_sec", 1.0)))
    dub_dur = max(0.1, float(dubbed_features.get("duration_sec", src_dur)))
    win_dur = max(0.1, float(target_duration_sec or src_dur))
    speaking_rate_delta_ratio = round(abs(dub_dur - win_dur) / win_dur, 4)

    src_f0_range = float(source_features.get("f0_range_hz", 20.0))
    dub_f0_range = float(dubbed_features.get("f0_range_hz", 20.0))
    dub_dyn_db = float(dubbed_features.get("dynamic_range_db", 8.0))
    dub_voiced = float(dubbed_features.get("voiced_ratio", 0.5))

    # Detect robotic / flat delivery warning
    flatness_warning = bool(
        dub_voiced > 0.20
        and dub_f0_range < 8.0
        and src_f0_range > 28.0
        and dub_dyn_db < 3.5
    )

    pitch_compatible = not flatness_warning and (
        dub_f0_range >= 6.0 or float(dubbed_features.get("f0_mean_hz", 0.0)) > 75.0
    )
    pause_delta_ms = abs(
        int(dubbed_features.get("pause_after_ms", 0)) - int(prosody_profile.get("pause_after_ms", 0))
    )
    pause_compatible = pause_delta_ms <= 280

    if flatness_warning or speaking_rate_delta_ratio > 0.15:
        status = "WARNING"
    else:
        status = "PASS"

    return {
        "segment_id": prosody_profile.get("segment_id"),
        "character_id": prosody_profile.get("character_id"),
        "status": status,
        "energy_delta_db": energy_delta_db,
        "speaking_rate_delta_ratio": speaking_rate_delta_ratio,
        "pitch_contour_compatible": pitch_compatible,
        "pause_boundary_compatible": pause_compatible,
        "flatness_warning": flatness_warning,
        "source_f0_mean_hz": source_features.get("f0_mean_hz", 0.0),
        "dubbed_f0_mean_hz": dubbed_features.get("f0_mean_hz", 0.0),
        "source_rms_db": src_db,
        "dubbed_rms_db": dub_db,
    }


def analyze_project_emotion_prosody(
    source_audio_path: Path,
    segments: list[dict[str, Any]],
    characters: list[dict[str, Any]] | None = None,
    segments_dir: Path | None = None,
    dubbed_mix_audio_path: Path | None = None,
) -> dict[str, Any]:
    """Run full Phase 25 emotion & prosody analysis + source-vs-dubbed QA across a project."""
    char_map = {str(c["character_id"]): c for c in (characters or []) if c.get("character_id")}
    profiles: list[dict[str, Any]] = []
    qa_entries: list[dict[str, Any]] = []

    for idx, seg in enumerate(segments):
        seg_id = seg.get("segment_id", seg.get("index", idx + 1))
        src_start = float(seg.get("original_start", seg.get("start", 0.0)))
        src_end = float(seg.get("original_end", seg.get("end", src_start + float(seg.get("target_duration", 1.0)))))
        dub_start = float(seg.get("timeline_audio_start", seg.get("start", src_start)))
        dub_end = float(seg.get("timeline_audio_end", seg.get("end", src_end)))
        target_dur = float(seg.get("target_duration", max(0.1, dub_end - dub_start)))
        char_id = str(seg.get("character_id") or "CHAR_001")

        src_samples, src_sr = _read_pcm16_mono_slice(source_audio_path, start_sec=src_start, end_sec=src_end)
        src_feats = analyze_audio_prosody_features(src_samples, sample_rate=src_sr, duration_sec=target_dur)

        prev_seg = segments[idx - 1] if idx > 0 else None
        next_seg = segments[idx + 1] if idx + 1 < len(segments) else None

        profile = build_segment_prosody_profile(
            segment={**seg, "segment_id": seg_id, "character_id": char_id, "target_duration": target_dur},
            audio_features=src_feats,
            character_baseline=char_map.get(char_id),
            prev_segment=prev_seg,
            next_segment=next_seg,
        )
        profiles.append(profile)

        # Measure dubbed fitted WAV or slice from master dubbed mix WAV
        dub_wav: Path | None = None
        if seg.get("fitted_wav") and Path(str(seg["fitted_wav"])).exists():
            dub_wav = Path(str(seg["fitted_wav"]))
        elif segments_dir is not None:
            cand_p23 = segments_dir / f"seg_{int(seg_id):02d}_phase23_fitted.wav"
            cand_std = segments_dir / f"seg_{int(seg_id):02d}_fitted.wav"
            if cand_p23.exists():
                dub_wav = cand_p23
            elif cand_std.exists():
                dub_wav = cand_std

        if dub_wav is not None and dub_wav.exists():
            dub_samples, dub_sr = _read_pcm16_mono_slice(dub_wav, start_sec=0.0, end_sec=None)
            dub_feats = analyze_audio_prosody_features(dub_samples, sample_rate=dub_sr)
        elif dubbed_mix_audio_path is not None and dubbed_mix_audio_path.exists():
            dub_samples, dub_sr = _read_pcm16_mono_slice(dubbed_mix_audio_path, start_sec=dub_start, end_sec=dub_end)
            dub_feats = analyze_audio_prosody_features(dub_samples, sample_rate=dub_sr, duration_sec=target_dur)
        else:
            dub_feats = dict(src_feats)

        qa_item = evaluate_prosody_qa(
            source_features=src_feats,
            dubbed_features=dub_feats,
            prosody_profile=profile,
            target_duration_sec=target_dur,
        )
        qa_entries.append(qa_item)

    emotion_counts: dict[str, int] = {}
    for p in profiles:
        em = p["primary_emotion"]
        emotion_counts[em] = emotion_counts.get(em, 0) + 1

    pass_count = sum(1 for q in qa_entries if q["status"] == "PASS")
    warn_count = sum(1 for q in qa_entries if q["status"] == "WARNING")
    flat_count = sum(1 for q in qa_entries if q["flatness_warning"])

    return {
        "segment_count": len(profiles),
        "emotion_distribution": emotion_counts,
        "qa_summary": {
            "pass_count": pass_count,
            "warning_count": warn_count,
            "flatness_warning_count": flat_count,
            "mean_energy_delta_db": round(
                sum(q["energy_delta_db"] for q in qa_entries) / max(1, len(qa_entries)), 2
            ),
        },
        "segments": profiles,
        "prosody_qa": qa_entries,
    }
