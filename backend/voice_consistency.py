"""Phase 26: Character Voice Consistency & Voice Lock Engine.

Implements PRD Section 14 & Section 27:
1. Deterministic character voice selection & controlled minor/background voice pools.
2. Scene-level voice collision prevention (two characters in the same scene cannot
   share an identical voice+register signature).
3. Cryptographic Voice Lock Schema (PRD §14.3) with SHA-256 configuration_hash.
4. Multi-Engine Voice Lock Guard: prevents mid-character engine fallback (e.g.,
   edge-tts -> piper) or voice drift across segments, scenes, retries, or resume runs
   unless explicitly unlocked.
5. Cross-Scene Voice Consistency QA: measures acoustic embedding similarity and F0
   stability for each character across all scenes in the project.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from backend.speaker_engine import (
    _average_embeddings,
    _read_pcm16_mono_slice,
    cosine_similarity,
    extract_speaker_acoustic_features,
)


class VoiceLockViolationError(RuntimeError):
    """Raised when a locked character voice or TTS engine is mutated mid-project."""


# Deterministic Hindi voice pool with distinct vocal signatures for multi-character projects
HINDI_VOICE_POOL: list[dict[str, str]] = [
    {
        "pool_slot": "primary_masculine_baritone",
        "voice_engine": "edge-tts",
        "voice_id": "hi-IN-MadhurNeural",
        "base_rate": "+0%",
        "base_pitch": "+0Hz",
        "base_volume": "+0%",
        "vocal_register": "low_masculine",
    },
    {
        "pool_slot": "primary_feminine_soprano",
        "voice_engine": "edge-tts",
        "voice_id": "hi-IN-SwaraNeural",
        "base_rate": "+0%",
        "base_pitch": "+0Hz",
        "base_volume": "+0%",
        "vocal_register": "high_feminine",
    },
    {
        "pool_slot": "secondary_masculine_tenor",
        "voice_engine": "edge-tts",
        "voice_id": "hi-IN-MadhurNeural",
        "base_rate": "+3%",
        "base_pitch": "+3Hz",
        "base_volume": "+0%",
        "vocal_register": "mid_tenor",
    },
    {
        "pool_slot": "secondary_feminine_alto",
        "voice_engine": "edge-tts",
        "voice_id": "hi-IN-SwaraNeural",
        "base_rate": "-2%",
        "base_pitch": "-3Hz",
        "base_volume": "+0%",
        "vocal_register": "mid_alto",
    },
    {
        "pool_slot": "minor_masculine_deep",
        "voice_engine": "edge-tts",
        "voice_id": "hi-IN-MadhurNeural",
        "base_rate": "-3%",
        "base_pitch": "-4Hz",
        "base_volume": "+0%",
        "vocal_register": "deep_masculine",
    },
    {
        "pool_slot": "minor_feminine_bright",
        "voice_engine": "edge-tts",
        "voice_id": "hi-IN-SwaraNeural",
        "base_rate": "+4%",
        "base_pitch": "+4Hz",
        "base_volume": "+0%",
        "vocal_register": "bright_feminine",
    },
    {
        "pool_slot": "background_masculine_crisp",
        "voice_engine": "edge-tts",
        "voice_id": "hi-IN-MadhurNeural",
        "base_rate": "+5%",
        "base_pitch": "+2Hz",
        "base_volume": "-2%",
        "vocal_register": "crisp_masculine",
    },
    {
        "pool_slot": "background_feminine_warm",
        "voice_engine": "edge-tts",
        "voice_id": "hi-IN-SwaraNeural",
        "base_rate": "-4%",
        "base_pitch": "-2Hz",
        "base_volume": "-2%",
        "vocal_register": "warm_feminine",
    },
]


def compute_voice_lock_hash(lock_entry: dict[str, Any]) -> str:
    """Compute deterministic SHA-256 configuration_hash per PRD §14.3."""
    canonical = {
        "character_id": str(lock_entry.get("character_id") or ""),
        "voice_engine": str(lock_entry.get("voice_engine") or "edge-tts"),
        "voice_id": str(lock_entry.get("voice_id") or ""),
        "base_rate": str(lock_entry.get("base_rate") or "+0%"),
        "base_pitch": str(lock_entry.get("base_pitch") or "+0Hz"),
        "base_volume": str(lock_entry.get("base_volume") or "+0%"),
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def create_voice_lock_entry(
    character_id: str,
    voice_engine: str = "edge-tts",
    voice_id: str = "hi-IN-MadhurNeural",
    base_rate: str = "+0%",
    base_pitch: str = "+0Hz",
    base_volume: str = "+0%",
    locked: bool = True,
    locked_at_phase: int = 26,
    pool_slot: str | None = None,
) -> dict[str, Any]:
    """Create a normalized PRD §14.3 voice lock entry."""
    entry: dict[str, Any] = {
        "character_id": str(character_id),
        "voice_engine": str(voice_engine),
        "voice_id": str(voice_id),
        "base_rate": str(base_rate),
        "base_pitch": str(base_pitch),
        "base_volume": str(base_volume),
        "locked": bool(locked),
        "locked_at_phase": int(locked_at_phase),
    }
    if pool_slot:
        entry["pool_slot"] = pool_slot
    entry["configuration_hash"] = compute_voice_lock_hash(entry)
    return entry


def assign_and_lock_character_voices(
    characters: list[dict[str, Any]],
    scenes: list[dict[str, Any]] | None = None,
    existing_locks: dict[str, dict[str, Any]] | None = None,
    preferred_engine: str = "edge-tts",
    locked_at_phase: int = 26,
) -> dict[str, Any]:
    """Deterministically assign and lock voices for all characters without scene collisions."""
    locks: dict[str, dict[str, Any]] = {}
    if existing_locks:
        for cid, lock in existing_locks.items():
            if lock.get("locked", True):
                locks[str(cid)] = deepcopy(lock)

    # Build scene co-occurrence adjacency graph
    co_occurring: dict[str, set[str]] = {}
    for sc in scenes or []:
        present = [str(c) for c in sc.get("characters_present", [])]
        for c1 in present:
            co_occurring.setdefault(c1, set()).update(c2 for c2 in present if c2 != c1)

    # Sort characters so primary -> secondary -> minor -> background are assigned first
    role_priority = {"primary": 0, "secondary": 1, "minor": 2, "background": 3}
    ordered_chars = sorted(
        characters,
        key=lambda c: (
            role_priority.get(str(c.get("role_classification", "primary")), 9),
            -int(c.get("segment_count", 0)),
            str(c.get("character_id", "")),
        ),
    )

    used_signatures_global: set[tuple[str, str, str]] = set()
    for cid, lk in locks.items():
        sig = (str(lk.get("voice_id")), str(lk.get("base_pitch")), str(lk.get("base_rate")))
        used_signatures_global.add(sig)

    for idx, ch in enumerate(ordered_chars):
        cid = str(ch["character_id"])
        if cid in locks:
            continue

        # Check if character already has an explicit voice_id configured
        vp = ch.get("voice_profile") or {}
        f0 = float(ch.get("pitch_baseline_hz", 165.0) or 165.0)
        vocal_type = str(ch.get("gender_or_vocal_type") or "").lower()
        prefers_feminine = "feminine" in vocal_type or "soprano" in vocal_type or f0 >= 185.0

        # Filter pool candidates by vocal register preference first
        preferred_pool = [
            slot for slot in HINDI_VOICE_POOL
            if ("feminine" in slot["pool_slot"] or "soprano" in slot["pool_slot"] or "alto" in slot["pool_slot"]) == prefers_feminine
        ] + [
            slot for slot in HINDI_VOICE_POOL
            if ("feminine" in slot["pool_slot"] or "soprano" in slot["pool_slot"] or "alto" in slot["pool_slot"]) != prefers_feminine
        ]

        neighbor_sigs = {
            (
                str(locks[nc]["voice_id"]),
                str(locks[nc]["base_pitch"]),
                str(locks[nc]["base_rate"]),
            )
            for nc in co_occurring.get(cid, set())
            if nc in locks
        }

        chosen_slot: dict[str, str] | None = None
        for cand in preferred_pool:
            sig = (cand["voice_id"], cand["base_pitch"], cand["base_rate"])
            if sig not in neighbor_sigs and sig not in used_signatures_global:
                chosen_slot = cand
                break
        if chosen_slot is None:
            for cand in preferred_pool:
                sig = (cand["voice_id"], cand["base_pitch"], cand["base_rate"])
                if sig not in neighbor_sigs:
                    chosen_slot = cand
                    break
        if chosen_slot is None:
            # Synthesize a unique deterministic micro-offset so no scene collision can happen
            base_voice = "hi-IN-SwaraNeural" if prefers_feminine else "hi-IN-MadhurNeural"
            offset_hz = ((idx % 5) + 1) * (-1 if idx % 2 else 1)
            offset_rate = ((idx % 4) + 1)
            chosen_slot = {
                "pool_slot": f"overflow_slot_{idx:02d}",
                "voice_engine": preferred_engine,
                "voice_id": base_voice,
                "base_rate": f"{offset_rate:+d}%",
                "base_pitch": f"{offset_hz:+d}Hz",
                "base_volume": "+0%",
            }

        voice_id = str(vp.get("voice_id") or chosen_slot["voice_id"])
        base_rate = str(vp.get("rate") or chosen_slot["base_rate"])
        base_pitch = str(vp.get("pitch") or chosen_slot["base_pitch"])
        base_volume = str(vp.get("volume") or chosen_slot["base_volume"])
        sig = (voice_id, base_pitch, base_rate)
        if sig in neighbor_sigs:
            base_pitch = chosen_slot["base_pitch"]
            base_rate = chosen_slot["base_rate"]
            sig = (voice_id, base_pitch, base_rate)

        used_signatures_global.add(sig)
        locks[cid] = create_voice_lock_entry(
            character_id=cid,
            voice_engine=preferred_engine,
            voice_id=voice_id,
            base_rate=base_rate,
            base_pitch=base_pitch,
            base_volume=base_volume,
            locked=True,
            locked_at_phase=locked_at_phase,
            pool_slot=chosen_slot.get("pool_slot"),
        )

    # Check scene collisions
    scene_collisions: list[dict[str, Any]] = []
    for sc in scenes or []:
        present = [str(c) for c in sc.get("characters_present", []) if str(c) in locks]
        seen_in_scene: dict[tuple[str, str, str], str] = {}
        for cid in present:
            lk = locks[cid]
            sig = (lk["voice_id"], lk["base_pitch"], lk["base_rate"])
            if sig in seen_in_scene:
                scene_collisions.append({
                    "scene_id": sc.get("scene_id"),
                    "character_a": seen_in_scene[sig],
                    "character_b": cid,
                    "shared_signature": sig,
                })
            else:
                seen_in_scene[sig] = cid

    return {
        "locked_character_count": len(locks),
        "scene_voice_collision_count": len(scene_collisions),
        "scene_voice_collisions": scene_collisions,
        "voice_locks": [locks[cid] for cid in sorted(locks.keys())],
        "voice_lock_map": locks,
    }


def verify_voice_lock_integrity(
    character_id: str,
    requested_engine: str,
    requested_voice_id: str,
    voice_lock_map: dict[str, dict[str, Any]],
    allow_unlocked_override: bool = False,
    requested_base_rate: str | None = None,
    requested_base_pitch: str | None = None,
    requested_base_volume: str | None = None,
) -> dict[str, Any]:
    """Enforce PRD §14.3 & §14.4 Voice Lock & Multi-Engine Guard.

    Raises VoiceLockViolationError if:
    - A locked character attempts to switch TTS engines (e.g., edge-tts -> piper).
    - A locked character attempts to switch voice_id mid-movie.
    - The stored configuration_hash has been tampered with.
    """
    cid = str(character_id)
    if cid not in voice_lock_map:
        raise VoiceLockViolationError(f"Character {cid} has no registered voice lock.")

    lock = voice_lock_map[cid]
    expected_hash = compute_voice_lock_hash(lock)
    if lock.get("configuration_hash") and lock["configuration_hash"] != expected_hash:
        raise VoiceLockViolationError(
            f"Voice lock configuration_hash mismatch for {cid}: expected {expected_hash}, "
            f"found {lock.get('configuration_hash')}."
        )

    is_locked = bool(lock.get("locked", True))
    if not is_locked and allow_unlocked_override:
        return {
            "character_id": cid,
            "verified": True,
            "locked": False,
            "voice_engine": requested_engine,
            "voice_id": requested_voice_id,
        }

    locked_engine = str(lock.get("voice_engine") or "edge-tts")
    locked_voice = str(lock.get("voice_id") or "")

    if str(requested_engine) != locked_engine:
        raise VoiceLockViolationError(
            f"Multi-Engine Voice Lock Violation for {cid}: locked to engine '{locked_engine}', "
            f"cannot fallback or switch to '{requested_engine}' mid-character."
        )
    if str(requested_voice_id) != locked_voice:
        raise VoiceLockViolationError(
            f"Character Voice Lock Violation for {cid}: locked to voice '{locked_voice}', "
            f"cannot switch to '{requested_voice_id}'."
        )
    if requested_base_rate is not None and str(requested_base_rate) != str(lock.get("base_rate", "+0%")):
        raise VoiceLockViolationError(
            f"Character Base Rate Lock Violation for {cid}: locked to '{lock.get('base_rate')}', "
            f"requested '{requested_base_rate}'."
        )
    if requested_base_pitch is not None and str(requested_base_pitch) != str(lock.get("base_pitch", "+0Hz")):
        raise VoiceLockViolationError(
            f"Character Base Pitch Lock Violation for {cid}: locked to '{lock.get('base_pitch')}', "
            f"requested '{requested_base_pitch}'."
        )
    if requested_base_volume is not None and str(requested_base_volume) != str(lock.get("base_volume", "+0%")):
        raise VoiceLockViolationError(
            f"Character Base Volume Lock Violation for {cid}: locked to '{lock.get('base_volume')}', "
            f"requested '{requested_base_volume}'."
        )

    return {
        "character_id": cid,
        "verified": True,
        "locked": True,
        "voice_engine": locked_engine,
        "voice_id": locked_voice,
        "configuration_hash": expected_hash,
    }


def unlock_and_relock_character_voice(
    character_id: str,
    voice_lock_map: dict[str, dict[str, Any]],
    new_voice_engine: str,
    new_voice_id: str,
    new_base_rate: str = "+0%",
    new_base_pitch: str = "+0Hz",
    new_base_volume: str = "+0%",
    reason: str = "explicit_user_relock",
    phase: int = 26,
) -> dict[str, Any]:
    """Explicitly unlock and re-lock a character voice with audit trail."""
    cid = str(character_id)
    previous = deepcopy(voice_lock_map.get(cid))
    updated = create_voice_lock_entry(
        character_id=cid,
        voice_engine=new_voice_engine,
        voice_id=new_voice_id,
        base_rate=new_base_rate,
        base_pitch=new_base_pitch,
        base_volume=new_base_volume,
        locked=True,
        locked_at_phase=phase,
    )
    updated["relock_reason"] = reason
    updated["previous_configuration_hash"] = (previous or {}).get("configuration_hash")
    voice_lock_map[cid] = updated
    return updated


def evaluate_voice_consistency_qa(
    segments: list[dict[str, Any]],
    voice_lock_map: dict[str, dict[str, Any]],
    scenes: list[dict[str, Any]] | None = None,
    segments_dir: Path | None = None,
    dubbed_mix_audio_path: Path | None = None,
) -> dict[str, Any]:
    """Verify character voice consistency across all segments and scenes (PRD §14.5 & §27)."""
    char_segments: dict[str, list[dict[str, Any]]] = {}
    violations: list[dict[str, Any]] = []

    for idx, seg in enumerate(segments):
        seg_id = seg.get("segment_id", seg.get("index", idx + 1))
        cid = str(seg.get("character_id") or "CHAR_001")
        lk = voice_lock_map.get(cid)
        req_engine = str(seg.get("voice_engine") or (lk or {}).get("voice_engine") or "edge-tts")
        req_voice = str(seg.get("voice_id") or (lk or {}).get("voice_id") or "")

        try:
            verify_voice_lock_integrity(
                character_id=cid,
                requested_engine=req_engine,
                requested_voice_id=req_voice,
                voice_lock_map=voice_lock_map,
            )
        except VoiceLockViolationError as exc:
            violations.append({
                "segment_id": seg_id,
                "character_id": cid,
                "error": str(exc),
            })

        char_segments.setdefault(cid, []).append({**seg, "segment_id": seg_id, "character_id": cid})

    character_reports: list[dict[str, Any]] = []
    for cid in sorted(char_segments.keys()):
        c_segs = char_segments[cid]
        lk = voice_lock_map.get(cid, {})
        scene_embeddings: dict[str, list[list[float]]] = {}
        f0_values: list[float] = []

        for s in c_segs:
            seg_id = int(s["segment_id"])
            sc_id = str(s.get("scene_id") or "SCENE_001")
            dub_start = float(s.get("timeline_audio_start", s.get("start", 0.0)))
            dub_end = float(s.get("timeline_audio_end", s.get("end", dub_start + 1.0)))
            wav_path: Path | None = None
            if s.get("fitted_wav") and Path(str(s["fitted_wav"])).exists():
                wav_path = Path(str(s["fitted_wav"]))
            elif segments_dir is not None:
                p23 = segments_dir / f"seg_{seg_id:02d}_phase23_fitted.wav"
                std = segments_dir / f"seg_{seg_id:02d}_fitted.wav"
                if p23.exists():
                    wav_path = p23
                elif std.exists():
                    wav_path = std

            if wav_path is not None and wav_path.exists():
                samples, sr = _read_pcm16_mono_slice(wav_path)
                feats = extract_speaker_acoustic_features(samples, sample_rate=sr)
                if any(feats["embedding"]):
                    scene_embeddings.setdefault(sc_id, []).append(feats["embedding"])
                if feats["f0_mean_hz"] > 0:
                    f0_values.append(feats["f0_mean_hz"])
            elif dubbed_mix_audio_path is not None and dubbed_mix_audio_path.exists():
                samples, sr = _read_pcm16_mono_slice(dubbed_mix_audio_path, start_sec=dub_start, end_sec=dub_end)
                feats = extract_speaker_acoustic_features(samples, sample_rate=sr)
                if any(feats["embedding"]):
                    scene_embeddings.setdefault(sc_id, []).append(feats["embedding"])
                if feats["f0_mean_hz"] > 0:
                    f0_values.append(feats["f0_mean_hz"])
            elif s.get("embedding"):
                scene_embeddings.setdefault(sc_id, []).append(list(s["embedding"]))
                if float(s.get("f0_mean_hz", 0.0)) > 0:
                    f0_values.append(float(s["f0_mean_hz"]))

        scene_centroids = {
            sc_id: _average_embeddings(vecs)
            for sc_id, vecs in scene_embeddings.items()
            if vecs
        }
        cross_scene_sims: list[float] = []
        sc_keys = sorted(scene_centroids.keys())
        for i in range(len(sc_keys)):
            for j in range(i + 1, len(sc_keys)):
                sim = cosine_similarity(scene_centroids[sc_keys[i]], scene_centroids[sc_keys[j]])
                cross_scene_sims.append(sim)

        mean_sim = round(sum(cross_scene_sims) / len(cross_scene_sims), 4) if cross_scene_sims else 1.0
        f0_mean = round(sum(f0_values) / len(f0_values), 2) if f0_values else 0.0
        f0_std = (
            round(
                (sum((x - f0_mean) ** 2 for x in f0_values) / len(f0_values)) ** 0.5,
                2,
            )
            if f0_values
            else 0.0
        )

        char_violations = [v for v in violations if v["character_id"] == cid]
        status = "PASS" if not char_violations and mean_sim >= 0.75 else ("FAIL" if char_violations else "WARNING")

        character_reports.append({
            "character_id": cid,
            "voice_engine": lk.get("voice_engine"),
            "voice_id": lk.get("voice_id"),
            "base_rate": lk.get("base_rate"),
            "base_pitch": lk.get("base_pitch"),
            "configuration_hash": lk.get("configuration_hash"),
            "locked": bool(lk.get("locked", True)),
            "segment_count": len(c_segs),
            "scenes_evaluated": sc_keys,
            "cross_scene_similarity": mean_sim,
            "dubbed_f0_mean_hz": f0_mean,
            "dubbed_f0_std_hz": f0_std,
            "mid_movie_voice_switches": len(char_violations),
            "status": status,
        })

    overall_status = (
        "FAIL"
        if violations or any(r["status"] == "FAIL" for r in character_reports)
        else ("WARNING" if any(r["status"] == "WARNING" for r in character_reports) else "PASS")
    )

    return {
        "overall_status": overall_status,
        "character_count": len(character_reports),
        "mid_movie_voice_switches": len(violations),
        "violations": violations,
        "character_consistency": character_reports,
    }
