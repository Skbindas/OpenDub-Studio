"""Phase 24: Character Identity & Persistent Character Registry v2 Engine.

Implements PRD Section 12.1, 12.3, 12.5 & Section 25:
1. Strict separation between SPEAKER IDENTITY (acoustic cluster SPEAKER_00) and
   CHARACTER IDENTITY (narrative entity CHAR_001).
2. Persistent Character Registry v2 schema with:
   - character_id, display_name, speaker_ids, gender_or_vocal_type,
     voice_profile, emotion_Tendencies, speaking_rate_baseline,
     energy_baseline, pitch_baseline_hz, locked, confidence,
     human_review_required, scenes_present, segment_count, role_classification.
3. Role classification into:
   - primary
   - secondary
   - minor
   - background
4. Explicit HUMAN_REVIEW_REQUIRED flags when confidence < threshold or when
   acoustic ambiguity/overlap occurs.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


CHARACTER_REGISTRY_SCHEMA_VERSION = 2
ROLE_CLASSIFICATIONS = ("primary", "secondary", "minor", "background")


def classify_character_role(
    segment_count: int,
    total_project_segments: int,
    total_speech_sec: float = 0.0,
    total_project_speech_sec: float = 0.0,
    scenes_present_count: int = 1,
    total_scenes_count: int = 1,
) -> str:
    """Classify a character into primary / secondary / minor / background per PRD §12.5."""
    seg_share = segment_count / float(max(1, total_project_segments))
    dur_share = (
        total_speech_sec / float(max(0.001, total_project_speech_sec))
        if total_project_speech_sec > 0
        else seg_share
    )
    combined_share = 0.6 * seg_share + 0.4 * dur_share
    scene_ratio = scenes_present_count / float(max(1, total_scenes_count))

    if segment_count >= 5 and (combined_share >= 0.25 or (combined_share >= 0.18 and scene_ratio >= 0.5)):
        return "primary"
    if segment_count >= 3 or combined_share >= 0.10 or (segment_count >= 2 and scene_ratio >= 0.35):
        return "secondary"
    if segment_count >= 2 or total_speech_sec >= 2.5:
        return "minor"
    return "background"


def infer_vocal_type(f0_mean_hz: float) -> str:
    """Infer vocal register descriptor from measured fundamental frequency F0."""
    if f0_mean_hz <= 0.0:
        return "unclassified_register"
    if f0_mean_hz < 145.0:
        return "low_register_masculine_or_baritone"
    if f0_mean_hz < 185.0:
        return "mid_register_tenor_or_alto"
    return "high_register_feminine_or_soprano"


def detect_scene_boundaries(
    segments: list[dict[str, Any]],
    scene_gap_threshold_sec: float = 3.5,
    max_scene_window_sec: float = 45.0,
) -> list[dict[str, Any]]:
    """Partition a timeline of dialogue segments into coherent narrative scenes."""
    if not segments:
        return []

    ordered = sorted(segments, key=lambda s: (float(s.get("start", 0.0)), float(s.get("end", 0.0))))
    scenes: list[dict[str, Any]] = []
    current_segs: list[dict[str, Any]] = []
    scene_start = float(ordered[0].get("start", 0.0))

    for seg in ordered:
        s_start = float(seg.get("start", 0.0))
        s_end = float(seg.get("end", 0.0))
        if current_segs:
            prev_end = float(current_segs[-1].get("end", 0.0))
            gap = s_start - prev_end
            elapsed = s_end - scene_start
            if gap >= scene_gap_threshold_sec or (gap >= 1.2 and elapsed >= max_scene_window_sec):
                scene_idx = len(scenes) + 1
                scenes.append(_summarize_scene(scene_idx, current_segs))
                current_segs = []
                scene_start = s_start
        current_segs.append(seg)

    if current_segs:
        scene_idx = len(scenes) + 1
        scenes.append(_summarize_scene(scene_idx, current_segs))

    return scenes


def _summarize_scene(scene_idx: int, scene_segments: list[dict[str, Any]]) -> dict[str, Any]:
    scene_id = f"SCENE_{scene_idx:03d}"
    start = round(min(float(s.get("start", 0.0)) for s in scene_segments), 3)
    end = round(max(float(s.get("end", 0.0)) for s in scene_segments), 3)
    speakers = sorted({str(s.get("speaker_id") or s.get("speaker") or "SPEAKER_00") for s in scene_segments})
    seg_ids = [s.get("segment_id", s.get("index", idx + 1)) for idx, s in enumerate(scene_segments)]
    return {
        "scene_id": scene_id,
        "scene_index": scene_idx,
        "start": start,
        "end": end,
        "duration_sec": round(max(0.0, end - start), 3),
        "segment_count": len(scene_segments),
        "segment_ids": seg_ids,
        "speakers_present": speakers,
    }


def build_character_registry(
    segments: list[dict[str, Any]],
    speaker_reconciliation: dict[str, Any] | None = None,
    existing_characters: list[dict[str, Any]] | None = None,
    speaker_to_character_overrides: dict[str, str] | None = None,
    confidence_review_threshold: float = 0.70,
) -> dict[str, Any]:
    """Build Persistent Character Registry v2 separating Speaker IDs from Character IDs.

    Supports:
    - Multiple speaker_ids mapped to one character_id (e.g., normal + phone filter)
    - Explicit human_review_required flags when speaker confidence is low
    - Automatic role classification (primary, secondary, minor, background)
    """
    scenes = detect_scene_boundaries(segments)
    seg_to_scene: dict[Any, str] = {}
    for sc in scenes:
        for sid in sc["segment_ids"]:
            seg_to_scene[sid] = sc["scene_id"]

    existing_by_char: dict[str, dict[str, Any]] = {}
    spk_to_char: dict[str, str] = {}
    if existing_characters:
        for ch in existing_characters:
            cid = str(ch.get("character_id") or "")
            if not cid:
                continue
            existing_by_char[cid] = deepcopy(ch)
            for sid in ch.get("speaker_ids", []):
                spk_to_char[str(sid)] = cid
            if ch.get("speaker_id"):
                spk_to_char[str(ch["speaker_id"])] = cid

    if speaker_to_character_overrides:
        for spk_id, char_id in speaker_to_character_overrides.items():
            spk_to_char[str(spk_id)] = str(char_id)

    # Collect all distinct global speaker IDs in chronological order or sorted order
    all_speakers: list[str] = []
    for seg in segments:
        spk = str(seg.get("speaker_id") or seg.get("speaker") or "SPEAKER_00")
        if spk not in all_speakers:
            all_speakers.append(spk)
    all_speakers.sort()

    next_char_num = 1
    for spk in all_speakers:
        if spk not in spk_to_char:
            while f"CHAR_{next_char_num:03d}" in existing_by_char or f"CHAR_{next_char_num:03d}" in spk_to_char.values():
                next_char_num += 1
            spk_to_char[spk] = f"CHAR_{next_char_num:03d}"
            next_char_num += 1

    # Aggregate segment metrics per character_id
    char_segments: dict[str, list[dict[str, Any]]] = {}
    char_speakers: dict[str, set[str]] = {}
    annotated_segments: list[dict[str, Any]] = []

    for idx, seg in enumerate(segments):
        seg_id = seg.get("segment_id", seg.get("index", idx + 1))
        spk = str(seg.get("speaker_id") or seg.get("speaker") or "SPEAKER_00")
        cid = str(seg.get("character_id") or spk_to_char.get(spk) or "CHAR_001")
        scene_id = seg_to_scene.get(seg_id, "SCENE_001")
        spk_conf = float(seg.get("speaker_confidence", 0.92) or 0.92)
        review_req = bool(seg.get("speaker_review_required", False)) or spk_conf < confidence_review_threshold

        row = dict(seg)
        row["segment_id"] = seg_id
        row["speaker_id"] = spk
        row["character_id"] = cid
        row["scene_id"] = scene_id
        row["speaker_confidence"] = round(spk_conf, 3)
        row["human_review_required"] = review_req
        annotated_segments.append(row)

        char_segments.setdefault(cid, []).append(row)
        char_speakers.setdefault(cid, set()).add(spk)

    total_seg_count = max(1, len(annotated_segments))
    total_speech_sec = sum(
        max(0.0, float(s.get("end", 0.0)) - float(s.get("start", 0.0)))
        for s in annotated_segments
    )
    total_scenes_count = max(1, len(scenes))

    reconciled_speaker_lookup: dict[str, dict[str, Any]] = {}
    if speaker_reconciliation and "speakers" in speaker_reconciliation:
        for sp_entry in speaker_reconciliation["speakers"]:
            reconciled_speaker_lookup[str(sp_entry["speaker_id"])] = sp_entry

    characters: list[dict[str, Any]] = []
    for cid in sorted(char_segments.keys()):
        c_segs = char_segments[cid]
        c_spks = sorted(char_speakers.get(cid, set()))
        prior = existing_by_char.get(cid, {})

        speech_sec = sum(
            max(0.0, float(s.get("end", 0.0)) - float(s.get("start", 0.0)))
            for s in c_segs
        )
        scenes_present = sorted({str(s.get("scene_id", "SCENE_001")) for s in c_segs})

        # Calculate baseline F0, energy, speaking rate
        f0_vals = [float(s.get("f0_mean_hz", 0.0)) for s in c_segs if float(s.get("f0_mean_hz", 0.0)) > 0]
        if not f0_vals:
            for spk in c_spks:
                sp_f0 = float(reconciled_speaker_lookup.get(spk, {}).get("f0_mean_hz", 0.0))
                if sp_f0 > 0:
                    f0_vals.append(sp_f0)
        pitch_baseline = round(sum(f0_vals) / len(f0_vals), 2) if f0_vals else float(prior.get("pitch_baseline_hz", 165.0))

        rms_vals = [float(s.get("rms_mean", 0.0)) for s in c_segs if float(s.get("rms_mean", 0.0)) > 0]
        energy_baseline = round(sum(rms_vals) / len(rms_vals), 4) if rms_vals else float(prior.get("energy_baseline", 0.065))

        char_rates = []
        for s in c_segs:
            dur = max(0.1, float(s.get("end", 0.0)) - float(s.get("start", 0.0)))
            txt = str(s.get("source_text") or s.get("text") or "").strip()
            if txt:
                char_rates.append(len(txt) / dur)
        speaking_rate_baseline = (
            round(sum(char_rates) / len(char_rates), 2)
            if char_rates
            else float(prior.get("speaking_rate_baseline", 4.2))
        )

        confs = [float(s.get("speaker_confidence", 0.92)) for s in c_segs]
        mean_conf = round(sum(confs) / max(1, len(confs)), 3)
        any_seg_review = any(bool(s.get("human_review_required", False)) for s in c_segs)
        human_review_required = (
            bool(prior.get("human_review_required", False))
            or any_seg_review
            or mean_conf < confidence_review_threshold
        )

        role = classify_character_role(
            segment_count=len(c_segs),
            total_project_segments=total_seg_count,
            total_speech_sec=speech_sec,
            total_project_speech_sec=total_speech_sec,
            scenes_present_count=len(scenes_present),
            total_scenes_count=total_scenes_count,
        )

        default_display = prior.get("display_name") or f"Character {cid.split('_')[-1]}"
        voice_profile = prior.get("voice_profile") or {
            "provider": "edge-tts",
            "voice_id": None,
            "rate": "+0%",
            "pitch": "+0Hz",
            "volume": "+0%",
        }
        emotion_tendencies = prior.get("emotion_tendencies") or prior.get("emotion_Tendencies") or [
            "neutral",
            "conversational",
        ]

        characters.append({
            "character_id": cid,
            "display_name": default_display,
            "speaker_ids": c_spks,
            "gender_or_vocal_type": prior.get("gender_or_vocal_type") or infer_vocal_type(pitch_baseline),
            "role_classification": role,
            "voice_profile": voice_profile,
            "emotion_Tendencies": emotion_tendencies,
            "speaking_rate_baseline": speaking_rate_baseline,
            "energy_baseline": energy_baseline,
            "pitch_baseline_hz": pitch_baseline,
            "locked": bool(prior.get("locked", True)),
            "confidence": mean_conf,
            "human_review_required": human_review_required,
            "scenes_present": scenes_present,
            "segment_count": len(c_segs),
            "total_speech_sec": round(speech_sec, 3),
        })

    # Update scenes with characters_present
    for sc in scenes:
        sc_seg_ids = set(sc["segment_ids"])
        sc["characters_present"] = sorted({
            s["character_id"] for s in annotated_segments if s["segment_id"] in sc_seg_ids
        })

    role_summary = {r: 0 for r in ROLE_CLASSIFICATIONS}
    for ch in characters:
        role_summary[ch["role_classification"]] = role_summary.get(ch["role_classification"], 0) + 1

    return {
        "schema_version": CHARACTER_REGISTRY_SCHEMA_VERSION,
        "character_count": len(characters),
        "role_summary": role_summary,
        "human_review_count": sum(1 for c in characters if c["human_review_required"]),
        "characters": characters,
        "scenes": scenes,
        "segments": annotated_segments,
    }
