from __future__ import annotations

import json
import uuid
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import re
import math

from .voice_profiles import resolve_character_voice
from .atomic_files import replace_with_retry


PIPELINE_STAGES: tuple[dict[str, Any], ...] = (
    {"id": "analysis", "label": "Analysis", "requires": ()},
    {"id": "character_identity", "label": "Character Identity", "requires": ("analysis",)},
    {"id": "translation", "label": "Translation", "requires": ("character_identity",)},
    {"id": "voice_assignment", "label": "Voice Assignment", "requires": ("translation",)},
    {"id": "tts", "label": "TTS", "requires": ("voice_assignment",)},
    {"id": "timing", "label": "Timing", "requires": ("tts",)},
    {"id": "loudness", "label": "Loudness", "requires": ("timing",)},
    {"id": "dialogue_removal", "label": "Dialogue Removal", "requires": ("loudness",)},
    {"id": "background_preservation", "label": "Background Preservation", "requires": ("dialogue_removal",)},
    {"id": "mix", "label": "Mix", "requires": ("background_preservation",)},
    {"id": "render", "label": "Render", "requires": ("mix",)},
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


LANGUAGE_MAP: dict[str, str] = {
    "hindi": "hi", "english": "en", "korean": "ko", "chinese": "zh",
    "japanese": "ja", "spanish": "es", "french": "fr", "german": "de",
}


def normalize_language_code(lang: str | None) -> str:
    """Normalize language names (e.g. 'Hindi') to standard ISO codes ('hi')."""
    cleaned = str(lang or "").strip().lower()
    return LANGUAGE_MAP.get(cleaned, cleaned)


def next_character_display_name(characters: list[dict[str, Any]]) -> str:
    """Return the next stable 1-based generated character label."""
    used = set()
    for character in characters:
        match = re.fullmatch(r"Character\s+(\d+)", str(character.get("display_name") or "").strip(), re.IGNORECASE)
        if match:
            number = int(match.group(1))
            if number >= 1:
                used.add(number)
    number = 1
    while number in used:
        number += 1
    return f"Character {number}"


def normalize_auto_character_display_names(characters: list[dict[str, Any]]) -> bool:
    """Migrate old automatic Speaker/Speaker-ID labels to 1-based Character labels.

    Explicit user-renamed labels are left untouched; only labels that still match
    the old automatic speaker naming convention are migrated.
    """
    changed = False
    for character in characters:
        display = str(character.get("display_name") or "").strip()
        source = str(character.get("source_speaker_id") or "").strip()
        old_auto_names = {source, source.replace("SPEAKER_", "Speaker ").replace("speaker_", "Speaker ")}
        is_old_auto = (
            display == "Character 0"
            or re.fullmatch(r"Speaker\s+\d+", display, re.IGNORECASE) is not None
            or display in old_auto_names
            or display == source
        )
        if not is_old_auto:
            continue
        new_name = next_character_display_name(characters)
        while any(c is not character and str(c.get("display_name") or "").strip() == new_name for c in characters):
            suffix = int(new_name.split()[-1]) + 1
            new_name = f"Character {suffix}"
        if display != new_name:
            character["display_name"] = new_name
            character["auto_display_name"] = True
            changed = True
    return changed


def recover_short_speech_window(rows: list[dict], index: int, turns: list[dict]) -> tuple[float, float]:
    """Recover an isolated short utterance's detected speech edges, never a free gap."""
    row = rows[index]
    start, end = float(row.get('start', 0)), float(row.get('end', 0))
    speaker = row.get('speaker_id')
    if not speaker or not 0 < end-start < .6:
        return start, end
    candidates = [t for t in turns if t.get('speaker_id') == speaker
                  and float(t.get('start', 0)) < end and float(t.get('end', 0)) > start]
    if len(candidates) != 1:
        return start, end
    turn = candidates[0]
    left, right = min(start, float(turn['start'])), max(end, float(turn['end']))
    if start-left > .35 or right-end > .35 or right-left > 1.2:
        return start, end
    neighbors = [r for i,r in enumerate(rows) if i != index] + [t for t in turns if t.get('speaker_id') != speaker]
    for neighbor in neighbors:
        nstart, nend = float(neighbor.get('start', 0)), float(neighbor.get('end', 0))
        if nstart >= right or nend <= left:
            continue
        if neighbor.get('speaker_id') == speaker or (nstart < end and nend > start):
            return start, end
        if nend <= start:
            left = max(left, nend)
        elif nstart >= end:
            right = min(right, nstart)
    return left, right


def stage_definitions() -> list[dict[str, Any]]:
    return [
        {"id": stage["id"], "label": stage["label"], "requires": list(stage["requires"])}
        for stage in PIPELINE_STAGES
    ]


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def build_dialogue_manifest(
    *,
    project_id: str,
    transcript: dict[str, Any],
    scenes: list[dict[str, Any]],
    registry: dict[str, Any] | None = None,
    output_path: Path,
    target_language: str | None = None,
) -> dict[str, Any]:
    """Create the single source-time dialogue unit manifest used by later stages."""
    registry = registry or {}
    speaker_links = registry.get("speaker_links") or {}
    characters = {
        str(row.get("character_id")): row
        for row in (registry.get("characters") or [])
        if row.get("character_id")
    }

    ordered_scenes = sorted(scenes, key=lambda row: float(row.get("start_sec", 0)))
    scene_starts = [float(row.get("start_sec", 0)) for row in ordered_scenes]

    from bisect import bisect_right

    units: list[dict[str, Any]] = []
    for index, segment in enumerate(transcript.get("segments", [])):
        start = float(segment.get("start", 0))
        end = float(segment.get("end", start))
        speaker_id = segment.get("speaker_id")
        character_id = speaker_links.get(str(speaker_id)) if speaker_id else None
        character = characters.get(str(character_id)) if character_id else None
        scene_index = None
        if ordered_scenes:
            pos = bisect_right(scene_starts, start) - 1
            if pos >= 0:
                scene = ordered_scenes[pos]
                scene_end = scene.get("end_sec")
                if scene_end is None or start < float(scene_end):
                    scene_index = scene.get("scene_index")

        units.append({
            "segment_id": f"seg-{index + 1:06d}",
            "segment_index": index,
            "start_sec": round(start, 3),
            "end_sec": round(end, 3),
            "duration_sec": round(max(0.0, end - start), 3),
            "scene_index": scene_index,
            "speaker_id": speaker_id,
            "speaker_confidence": segment.get("speaker_confidence"),
            "speaker_review_required": bool(segment.get("speaker_review_required", speaker_id is None)),
            "character_id": character_id,
            "character_name": (character or {}).get("display_name"),
            "source_text": (segment.get("text") or "").strip(),
            "words": segment.get("words", []),
            "translation": {
                "status": "pending",
                "target_language": target_language,
                "text": None,
                "engine": None,
                "error": None,
            },
            "voice": resolve_character_voice(character),
            "prosody": {
                "schema_version": 1,
                "emotion": None,
                "delivery": None,
                "rate": 1.0,
                "pitch": None,
                "volume": None,
                "review_required": True,
                "provider_support": "not_checked",
            },
            "tts": {
                "status": "pending",
                "audio_path": None,
                "duration_sec": None,
            },
            "timing": {
                "status": "pending",
                "target_duration_sec": round(max(0.0, end - start), 3),
                "fit_audio": None,
            },
            "loudness": {
                "status": "pending",
                "source_lufs": None,
                "target_lufs": None,
                "gain_db": None,
                "normalized_audio": None,
            },
            "audio_replacement": {
                "status": "pending",
                "method": None,
                "duck_db": None,
                "mask_audio": None,
            },
        })

    manifest = {
        "schema_version": 1,
        "project_id": project_id,
        "generated_at": _now(),
        "timebase": "source_media_seconds",
        "source_language": transcript.get("language"),
        "target_language": target_language,
        "segment_count": len(units),
        "units": units,
        "dependency_chain": stage_definitions(),
        "notice": "Dialogue units are source-timeline master records. Later stages must update these units rather than creating a second independent timeline.",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp = output_path.with_suffix(output_path.suffix + ".tmp")
    temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    replace_with_retry(temp, output_path)
    return manifest


def update_timeline_character_identity(*, timeline_path: Path, registry: dict[str, Any]) -> bool:
    """Synchronize character IDs/names into the persisted source-time timeline."""
    if not timeline_path.is_file():
        return False
    try:
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    links = registry.get("speaker_links") or {}
    characters = {
        str(row.get("character_id")): row
        for row in (registry.get("characters") or [])
        if row.get("character_id")
    }
    changed = False
    for segment in timeline.get("segments", []):
        speaker_id = str(segment.get("speaker_id") or "")
        character_id = segment.get("character_id") or links.get(speaker_id)
        character = characters.get(str(character_id)) if character_id else None
        character_name = (character or {}).get("display_name")
        if segment.get("character_id") != character_id:
            segment["character_id"] = character_id
            changed = True
        if segment.get("character_name") != character_name:
            segment["character_name"] = character_name
            changed = True

    if changed:
        temp = timeline_path.with_suffix(timeline_path.suffix + ".tmp")
        temp.write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
        replace_with_retry(temp, timeline_path)
    return changed



def find_dialogue_manifest_unit(manifest: dict[str, Any], segment_index: int) -> dict[str, Any] | None:
    """Resolve a master dialogue unit by its explicit source segment index."""
    units = manifest.get("units")
    if not isinstance(units, list):
        return None
    for unit in units:
        if not isinstance(unit, dict):
            continue
        unit_index = unit.get("segment_index")
        if isinstance(unit_index, int) and not isinstance(unit_index, bool) and unit_index == segment_index:
            return unit
    return None



def _read_manifest_safe(manifest_path: Path, retries: int = 15, delay: float = 0.05) -> dict[str, Any]:
    last_exc = None
    for attempt in range(retries):
        try:
            raw = manifest_path.read_text(encoding="utf-8")
            if raw.strip():
                return json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            last_exc = exc
            time.sleep(delay)
    if last_exc:
        raise RuntimeError(f"Dialogue manifest could not be read: {last_exc}") from last_exc
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _atomic_write_manifest(manifest_path: Path, manifest: dict[str, Any]) -> None:
    temp = manifest_path.with_name(f"{manifest_path.stem}.{uuid.uuid4().hex[:8]}.tmp")
    temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    replace_with_retry(temp, manifest_path)


def update_dialogue_manifest_tts(
    *, manifest_path: Path, segment_index: int, status: str,
    audio_path: str | None = None, duration_sec: float | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Persist synthesis status on the master source-time dialogue unit."""
    if status not in {"completed", "error", "pending", "running", "queued", "cancelled", "needs_review"}:
        raise ValueError("Unsupported TTS status")
    if duration_sec is not None and duration_sec < 0:
        raise ValueError("duration_sec must be non-negative")
    if not manifest_path.is_file():
        raise RuntimeError("Master dialogue manifest is not available.")
    manifest = _read_manifest_safe(manifest_path)
    unit = find_dialogue_manifest_unit(manifest, segment_index)
    if unit is None:
        raise RuntimeError(f"Dialogue manifest unit {segment_index} is not available.")
    unit["tts"] = {
        "status": status,
        "audio_path": audio_path if status == "completed" else None,
        "duration_sec": duration_sec if status == "completed" else None,
        "error": error if status == "error" else None,
        "updated_at": _now(),
    }
    _atomic_write_manifest(manifest_path, manifest)
    return manifest


def timing_fit_matches_policy(unit, max_speedup, max_slowdown):
    """A retained transform must satisfy the currently requested tempo bounds."""
    timing = unit.get('timing') or {}
    try:
        applied = float(timing['applied_tempo'])
        if not math.isfinite(applied) or not max_slowdown - 1e-9 <= applied <= max_speedup + 1e-9:
            return False
        target, duration = float(timing['target_duration_sec']), float(unit['duration_sec'])
        if not math.isfinite(target) or not math.isfinite(duration) or duration <= 0:
            return False
        if timing.get('fit_policy_version') != 2 or abs(target - duration) >= .001:
            return False
        if timing.get('status') == 'needs_review':
            return (abs(float(timing['max_speedup']) - max_speedup) < 1e-9 and
                    abs(float(timing['max_slowdown']) - max_slowdown) < 1e-9)
        return timing.get('status') == 'completed'
    except (KeyError, TypeError, ValueError):
        return False


def update_dialogue_manifest_timing(
    *, manifest_path: Path, segment_index: int, status: str,
    fit_audio: str | None = None, required_tempo: float | None = None,
    applied_tempo: float | None = None, duration_fit_limited: bool = False,
    error: str | None = None,
    fit_policy_version: int | None = None,
    max_speedup: float | None = None, max_slowdown: float | None = None,
) -> dict[str, Any]:
    """Persist timing fit status on the master dialogue unit."""
    if status not in {"completed", "error", "pending", "running", "queued", "cancelled", "needs_review"}:
        raise ValueError("Unsupported timing status")
    if not manifest_path.is_file():
        raise RuntimeError("Master dialogue manifest is not available.")
    manifest = _read_manifest_safe(manifest_path)
    unit = find_dialogue_manifest_unit(manifest, segment_index)
    if unit is None:
        raise RuntimeError(f"Dialogue manifest unit {segment_index} is not available.")
    unit["timing"] = {
        "status": status,
        "target_duration_sec": float(unit.get("duration_sec") or 0.0),
        "fit_audio": fit_audio if status in {"completed", "needs_review"} else None,
        "required_tempo": required_tempo,
        "applied_tempo": applied_tempo,
        "duration_fit_limited": duration_fit_limited,
        "fit_policy_version": fit_policy_version,
        "max_speedup": max_speedup, "max_slowdown": max_slowdown,
        "error": error if status == "error" else None,
        "updated_at": _now(),
    }
    _atomic_write_manifest(manifest_path, manifest)
    return manifest


def update_dialogue_manifest_loudness(
    *, manifest_path: Path, segment_index: int, status: str,
    normalized_audio: str | None = None, target_lufs: float | None = None,
    source_lufs: float | None = None, gain_db: float | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Persist loudness normalization status on the master dialogue unit."""
    if status not in {"completed", "error", "pending", "running", "queued", "cancelled", "needs_review"}:
        raise ValueError("Unsupported loudness status")
    if not manifest_path.is_file():
        raise RuntimeError("Master dialogue manifest is not available.")
    manifest = _read_manifest_safe(manifest_path)
    unit = find_dialogue_manifest_unit(manifest, segment_index)
    if unit is None:
        raise RuntimeError(f"Dialogue manifest unit {segment_index} is not available.")
    unit["loudness"] = {
        "status": status,
        "source_lufs": source_lufs,
        "target_lufs": target_lufs,
        "gain_db": gain_db,
        "normalized_audio": normalized_audio if status == "completed" else None,
        "error": error if status == "error" else None,
        "updated_at": _now(),
    }
    _atomic_write_manifest(manifest_path, manifest)
    return manifest


def update_dialogue_manifest_translation(
    *, manifest_path: Path, translated_result: dict[str, Any]
) -> dict[str, Any]:
    """Write Phase 12 translation results back into the master dialogue units."""
    if not manifest_path.is_file():
        raise RuntimeError("Master dialogue manifest is not available.")
    manifest = _read_manifest_safe(manifest_path)

    rows = translated_result.get("segments") or []
    by_index = {
        int(row.get("segment_index", index)): row
        for index, row in enumerate(rows)
        if isinstance(row, dict)
    }
    completed = 0
    errors = 0
    for unit in manifest.get("units", []):
        row = by_index.get(int(unit.get("segment_index", 0)))
        if row is None:
            continue
        text = (row.get("translated_text") or "").strip()
        error = row.get("translation_error")
        status = "completed" if text and not error else "error" if error else "pending"
        unit["translation"] = {
            "status": status,
            "target_language": translated_result.get("target_language"),
            "text": text,
            "engine": translated_result.get("engine"),
            "error": error,
            "adaptation": {
                "status": "baseline_translation",
                "mode": "source_faithful_dialogue",
                "text": text,
                "note": "Phase 12 stores the baseline target-language dialogue on the master unit without changing source timing or character identity.",
            },
        }
        if status == "completed":
            completed += 1
        elif status == "error":
            errors += 1

    manifest["target_language"] = translated_result.get("target_language")
    manifest["translation"] = {
        "status": "completed" if completed and not errors else "completed_with_errors" if completed else "error",
        "engine": translated_result.get("engine"),
        "translated_units": completed,
        "error_units": errors,
        "updated_at": _now(),
    }
    _atomic_write_manifest(manifest_path, manifest)
    return manifest


def merge_dialogue_manifest_state(
    new_manifest: dict[str, Any],
    previous_manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    """Preserve valid downstream state when identity metadata is refreshed."""
    if not previous_manifest:
        return new_manifest

    old_target = previous_manifest.get("target_language")
    new_target = new_manifest.get("target_language")
    previous_units = {
        str(unit.get("segment_id")): unit
        for unit in (previous_manifest.get("units") or [])
        if unit.get("segment_id")
    }
    for unit in new_manifest.get("units", []):
        old = previous_units.get(str(unit.get("segment_id")))
        if not old or old.get("source_text") != unit.get("source_text"):
            continue

        if normalize_language_code(old_target) == normalize_language_code(new_target) and old.get("translation"):
            unit["translation"] = old["translation"]

        if old.get("character_id") == unit.get("character_id"):
            # Line-level emotion and delivery intent are independent of voice profile changes.
            if old.get("prosody"):
                unit["prosody"] = old["prosody"]

            new_voice = unit.get("voice") or {}
            old_voice = old.get("voice") or {}
            new_is_configured = new_voice.get("status") == "configured"
            old_is_configured = old_voice.get("status") in {"configured", "completed"}

            voice_changed = False
            if new_is_configured:
                if not old_is_configured:
                    voice_changed = True
                else:
                    new_profile = new_voice.get("profile") or {}
                    old_profile = old_voice.get("profile") or {}
                    new_model = new_voice.get("model_path") or new_profile.get("model_path")
                    old_model = old_voice.get("model_path") or old_profile.get("model_path")
                    if (
                        new_model != old_model
                        or new_profile.get("voice_id") != old_profile.get("voice_id")
                        or new_profile.get("provider") != old_profile.get("provider")
                        or new_profile.get("settings") != old_profile.get("settings")
                        or new_profile.get("reference_sha256") != old_profile.get("reference_sha256")
                        or new_profile.get("reference_text_sha256") != old_profile.get("reference_text_sha256")
                    ):
                        voice_changed = True

            if voice_changed:
                # Retain newly configured voice from new_manifest;
                # invalidate downstream audio artifacts for this character per PRD §5.1 & §5.4.
                pass
            elif new_is_configured:
                # Voice profile is configured and unchanged: restore valid downstream audio state
                for key in ("tts", "timing", "loudness", "audio_replacement"):
                    if old.get(key):
                        unit[key] = old[key]
            else:
                # Neither is newly configured (e.g. test fixture or unassigned voice); keep existing state
                for key in ("voice", "tts", "timing", "loudness", "audio_replacement"):
                    if old.get(key):
                        unit[key] = old[key]
    return new_manifest


def suggest_dialogue_adaptation(
    *,
    source_text: str,
    translated_text: str,
    tone: str = "neutral",
    delivery_intent: str = "faithful",
    max_words: int | None = None,
) -> dict[str, Any]:
    """Produce a conservative, reviewable adaptation suggestion.

    This pass is deliberately non-generative: it removes only safe formatting/filler
    noise and never silently invents new semantic content. A future semantic model
    can replace this adapter without changing the master-dialogue contract.
    """
    original = " ".join(str(translated_text or "").split())
    candidate = original
    # Conservative spoken-dialogue cleanup. No semantic substitutions are made.
    filler_prefixes = (
        "um, ", "um ", "uh, ", "uh ", "erm, ", "erm ",
        "अ, ", "अ ", "उम्म, ", "उम्म ",
    )
    lowered = candidate.lower()
    for prefix in filler_prefixes:
        if lowered.startswith(prefix.lower()):
            candidate = candidate[len(prefix):].lstrip()
            break
    # Collapse obvious duplicated adjacent tokens without touching normal phrasing.
    tokens = candidate.split()
    compact_tokens: list[str] = []
    for token in tokens:
        if compact_tokens and token.casefold().strip(".,!?") == compact_tokens[-1].casefold().strip(".,!?"):
            continue
        compact_tokens.append(token)
    candidate = " ".join(compact_tokens).strip()

    budget = evaluate_adaptation_budget(
        source_text=source_text,
        target_text=candidate,
        source_duration_sec=1.0,
        max_words=max_words,
    )
    changes = []
    if candidate != original:
        changes.append("Removed leading filler/repeated adjacent words where safe.")
    if budget["status"] == "over_budget":
        changes.append("Line is still over the requested word budget; semantic shortening requires review or a language model.")
    return {
        "mode": "conservative_assist",
        "status": "suggested",
        "source_text": source_text,
        "original_text": original,
        "suggested_text": candidate,
        "tone": tone,
        "delivery_intent": delivery_intent,
        "budget": budget,
        "changes": changes,
        "requires_review": True,
        "semantic_rewrite": False,
    }


def validate_adaptation_candidate(
    *,
    source_text: str,
    target_text: str,
    expected_character_id: str | None,
    actual_character_id: str | None,
    requested_tone: str,
    recorded_tone: str | None,
    delivery_intent: str,
    recorded_delivery_intent: str | None,
    source_duration_sec: float,
    max_words: int | None = None,
) -> dict[str, Any]:
    """Run deterministic metadata, identity, and timing checks without claiming semantic equivalence."""
    issues: list[str] = []
    if not str(target_text or "").strip():
        issues.append("Candidate dialogue is empty.")
    if expected_character_id and actual_character_id and str(expected_character_id) != str(actual_character_id):
        issues.append("Character identity mismatch between dialogue manifest and synthesis row.")
    if requested_tone and recorded_tone and requested_tone.strip().casefold() != recorded_tone.strip().casefold():
        issues.append("Recorded tone differs from the requested tone.")
    if delivery_intent and recorded_delivery_intent and delivery_intent.strip().casefold() != recorded_delivery_intent.strip().casefold():
        issues.append("Recorded delivery intent differs from the requested intent.")
    budget = evaluate_adaptation_budget(
        source_text=source_text, target_text=target_text,
        source_duration_sec=source_duration_sec, max_words=max_words,
    )
    issues.extend(budget["issues"])
    return {
        "valid": not issues,
        "status": "passed_heuristic_checks" if not issues else "needs_review",
        "checks": {
            "non_empty": bool(str(target_text or "").strip()),
            "character_identity": "passed" if not expected_character_id or not actual_character_id or str(expected_character_id) == str(actual_character_id) else "failed",
            "tone_metadata": "passed" if not requested_tone or not recorded_tone or requested_tone.strip().casefold() == recorded_tone.strip().casefold() else "failed",
            "delivery_intent_metadata": "passed" if not delivery_intent or not recorded_delivery_intent or delivery_intent.strip().casefold() == recorded_delivery_intent.strip().casefold() else "failed",
            "timing_budget": budget["status"],
            "semantic_equivalence": "requires_human_review",
        },
        "issues": issues,
        "timing": budget,
        "warning": "These deterministic checks do not prove semantic equivalence, emotional fidelity, or measured audio duration. Human review and audio audition remain required.",
    }


def evaluate_adaptation_budget(
    *,
    source_text: str,
    target_text: str,
    source_duration_sec: float,
    max_words: int | None = None,
    words_per_second: float = 3.0,
) -> dict[str, Any]:
    """Check whether an adapted line is plausible for its source-time budget."""
    target_words = len(target_text.split())
    duration = max(0.0, float(source_duration_sec))
    estimated_duration = round(target_words / words_per_second, 3) if words_per_second > 0 else None
    duration_word_limit = max(1, int(round(duration * words_per_second)))
    effective_word_limit = min(max_words, duration_word_limit) if max_words is not None else duration_word_limit
    issues = []
    if max_words is not None and target_words > max_words:
        issues.append(f"Target dialogue has {target_words} words; explicit max_words limit is {max_words}.")
    if words_per_second <= 0:
        issues.append("words_per_second must be greater than zero for timing estimation.")
    elif estimated_duration is not None and estimated_duration > duration:
        issues.append(
            f"Estimated speech duration is {estimated_duration}s; source segment duration is {round(duration, 3)}s."
        )
    if target_words > duration_word_limit and not any("Estimated speech duration" in issue for issue in issues):
        issues.append(f"Target dialogue has {target_words} words; duration-based heuristic allows about {duration_word_limit} words.")
    return {
        "source_duration_sec": round(duration, 3),
        "source_word_count": len(source_text.split()),
        "target_word_count": target_words,
        "estimated_duration_sec": estimated_duration,
        "max_words": effective_word_limit,
        "explicit_max_words": max_words,
        "duration_word_limit": duration_word_limit,
        "words_per_second": words_per_second,
        "status": "within_budget" if not issues else "over_budget",
        "issues": issues,
        "note": "Word-count and speech-duration checks are heuristics; human review and audio timing validation remain required.",
    }


def validate_translation_manifest(
    manifest: dict[str, Any],
    translated: dict[str, Any],
) -> dict[str, Any]:
    """Validate translation completeness, identity and source-timebase invariants."""
    units = manifest.get("units") or []
    rows = translated.get("segments") or []
    by_index = {
        int(row.get("segment_index", index)): row
        for index, row in enumerate(rows)
        if isinstance(row, dict)
    }
    issues: list[str] = []
    checked = 0
    target = str(manifest.get("target_language") or translated.get("target_language") or "")
    for unit in units:
        index = int(unit.get("segment_index", -1))
        row = by_index.get(index)
        if row is None:
            issues.append(f"Missing translated segment {index + 1}.")
            continue
        checked += 1
        translated_text = str(row.get("translated_text") or "").strip()
        if not translated_text:
            issues.append(f"Empty target dialogue for segment {index + 1}.")
        row_target = str(row.get("target_language") or translated.get("target_language") or "")
        if target and row_target and normalize_language_code(row_target) != normalize_language_code(target):
            issues.append(f"Target language mismatch on segment {index + 1}.")
        source_text = str(unit.get("source_text") or "").strip()
        row_source = str(row.get("source_text") or row.get("text") or "").strip()
        if source_text != row_source:
            issues.append(f"Source text drift on segment {index + 1}.")
        start = float(unit.get("start_sec", 0))
        end = float(unit.get("end_sec", start))
        row_start = float(row.get("start", start))
        row_end = float(row.get("end", end))
        if abs(start - row_start) > 0.01 or abs(end - row_end) > 0.01:
            issues.append(f"Source-timebase drift on segment {index + 1}.")
        unit_character = unit.get("character_id")
        row_character = row.get("character_id")
        if unit_character and row_character and str(unit_character) != str(row_character):
            issues.append(f"Character identity drift on segment {index + 1}.")
    return {
        "valid": not issues and len(by_index) == len(units),
        "checked_units": checked,
        "unit_count": len(units),
        "translated_row_count": len(rows),
        "target_language": target,
        "issues": issues,
        "status": "passed" if not issues and len(by_index) == len(units) else "needs_review",
    }


def _artifact_status(project_root: Path, relative_path: str) -> bool:
    path = project_root / relative_path
    return path.is_file() and path.stat().st_size > 0


def get_pipeline_state(
    *,
    project_root: Path,
    project_id: str,
    target_language: str | None = None,
) -> dict[str, Any]:
    analysis_dir = project_root / "analysis"
    manifest = _read_json(analysis_dir / "analysis_manifest.json", {})
    transcript = _read_json(analysis_dir / "transcript.json", {})
    dialogue_manifest = _read_json(analysis_dir / "dialogue_manifest.json", {})
    registry = _read_json(project_root / "characters" / "registry.json", {})
    translation = _read_json(analysis_dir / "translated_transcript.json", {})
    mix_path = project_root / "output" / "dubbed_audio_mix.wav"
    rendered = sorted(
        (project_root / "output").glob("*_dubbed.mp4"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    ) if (project_root / "output").is_dir() else []

    statuses: dict[str, dict[str, Any]] = {}

    analysis_ready = (
        manifest.get("status") == "completed"
        and _artifact_status(project_root, "analysis/timeline.json")
        and isinstance(transcript.get("segments"), list)
    )
    statuses["analysis"] = {
        "status": "completed" if analysis_ready else "blocked",
        "ready": bool(analysis_ready),
        "detail": "Persistent source-time analysis is available." if analysis_ready else "Run full movie analysis first.",
    }

    expected_speakers = {
        str(segment.get("speaker_id"))
        for segment in transcript.get("segments", [])
        if segment.get("speaker_id")
    }
    linked_speakers = set((registry.get("speaker_links") or {}).keys())
    identity_ready = analysis_ready and bool(registry.get("characters")) and expected_speakers.issubset(linked_speakers)
    review_required = any(bool(char.get("review_required", False)) for char in registry.get("characters", []))
    statuses["character_identity"] = {
        "status": (
            "review_required" if identity_ready and review_required
            else "completed" if identity_ready
            else "blocked"
        ),
        "ready": bool(identity_ready),
        "review_required": bool(review_required),
        "detail": (
            "Speakers are automatically linked to saved character records; user review remains allowed."
            if identity_ready else "Automatic Character Registry must exist for every detected speaker."
        ),
    }
    diarization=_read_json(analysis_dir/'diarization.json',{})
    if diarization.get('schema_version',0)>=3:
        from .speaker_review import review_state
        foundation=review_state(project_root,registry)
        statuses['character_identity'].update(ready=analysis_ready and foundation['ready_for_dubbing'],
            status='completed' if analysis_ready and foundation['ready_for_dubbing'] else 'review_required' if analysis_ready else 'blocked',
            review_required=not foundation['ready_for_dubbing'],
            detail='Speaker identities and voice choices are reviewed and locked.' if foundation['ready_for_dubbing'] else ' '.join(foundation['blocking']))

    translation_rows = translation.get("segments") if isinstance(translation, dict) else None
    manifest_translation = (dialogue_manifest.get("translation") or {}) if isinstance(dialogue_manifest, dict) else {}
    translation_validation = (
        validate_translation_manifest(dialogue_manifest, translation)
        if isinstance(translation, dict) and isinstance(translation_rows, list)
        else {"valid": False, "issues": ["Translation artifact not available."]}
    )
    units_list = dialogue_manifest.get("units", []) if isinstance(dialogue_manifest, dict) else []
    translated_count = manifest_translation.get("translated_units")
    if translated_count is None:
        translated_count = sum(
            1 for u in units_list
            if isinstance(u.get("translation"), dict) and u["translation"].get("status") == "completed"
        )
    translation_ready = (
        statuses["character_identity"]["ready"]
        and bool(target_language or translation.get("target_language"))
        and bool(units_list)
        and translated_count == len(units_list)
        and translation_validation.get("valid", False)
    )
    statuses["translation"] = {
        "status": (
            "completed" if translation_ready
            else "review_required" if isinstance(translation_rows, list) and translation_rows
            else "not_started"
        ),
        "ready": bool(translation_ready),
        "review_required": not bool(translation_ready) and bool(translation_rows),
        "validation": translation_validation,
        "detail": (
            "Target-language dialogue passed identity/timebase validation."
            if translation_ready else
            "Review translation completeness, Character identity and source timestamps before continuing."
            if translation_rows else
            "Translation stage is next after Character Identity."
        ),
    }

    characters_list = registry.get("characters", []) if isinstance(registry, dict) else []
    configured_voice_count = sum(
        1 for c in characters_list
        if isinstance(c.get("voice_profile"), dict)
        and c["voice_profile"].get("status") == "configured"
        and (bool(c["voice_profile"].get("model_path")) or
             c["voice_profile"].get("provider") in {"cloned", "omnivoice"} and bool(c["voice_profile"].get("voice_id")))
    )
    voice_assignment_completed = (
        translation_ready
        and bool(characters_list)
        and configured_voice_count == len(characters_list)
    )
    statuses["voice_assignment"] = {
        "status": (
            "completed" if voice_assignment_completed
            else "review_required" if (0 < configured_voice_count < len(characters_list))
            else "not_started"
        ),
        "ready": bool(voice_assignment_completed),
        "detail": (
            "All characters have verified target voice profiles assigned."
            if voice_assignment_completed
            else f"{configured_voice_count}/{len(characters_list)} characters have configured voice profiles."
            if characters_list
            else "Assign a stable target voice model to every character before TTS."
        ),
    }

    dialogue_units = dialogue_manifest.get("units", []) if isinstance(dialogue_manifest, dict) else []
    completed_tts_count = sum(
        1 for u in dialogue_units
        if isinstance(u.get("tts"), dict) and u["tts"].get("status") == "completed"
    )
    tts_completed = (
        voice_assignment_completed
        and bool(dialogue_units)
        and completed_tts_count == len(dialogue_units)
    )
    tts_in_progress = bool(dialogue_units) and 0 < completed_tts_count < len(dialogue_units)
    statuses["tts"] = {
        "status": (
            "completed" if tts_completed
            else "in_progress" if tts_in_progress
            else "ready" if voice_assignment_completed
            else "not_started"
        ),
        "ready": bool(tts_completed),
        "detail": (
            "Target-language audio generated for all dialogue units."
            if tts_completed
            else f"{completed_tts_count}/{len(dialogue_units)} dialogue units synthesized."
            if tts_in_progress
            else "Ready to synthesize target voices for dialogue units."
            if voice_assignment_completed
            else "Generate target-language audio per dialogue unit after voice assignment."
        ),
    }
    completed_timing_count = sum(
        1 for u in dialogue_units
        if isinstance(u.get("timing"), dict) and u["timing"].get("status") in {"completed", "needs_review"}
    )
    timing_completed = (
        tts_completed
        and bool(dialogue_units)
        and completed_timing_count == len(dialogue_units)
    )
    timing_in_progress = bool(dialogue_units) and 0 < completed_timing_count < len(dialogue_units)
    statuses["timing"] = {
        "status": (
            "completed" if timing_completed
            else "in_progress" if timing_in_progress
            else "ready" if tts_completed
            else "not_started"
        ),
        "ready": bool(timing_completed),
        "detail": (
            "All dialogue clips fitted to original source timeline windows."
            if timing_completed
            else f"{completed_timing_count}/{len(dialogue_units)} dialogue units fitted."
            if timing_in_progress
            else "Ready to fit dialogue timing after TTS generation."
            if tts_completed
            else "Fit each generated clip to its source dialogue duration."
        ),
    }

    completed_loudness_count = sum(
        1 for u in dialogue_units
        if isinstance(u.get("loudness"), dict) and u["loudness"].get("status") == "completed"
    )
    loudness_completed = (
        timing_completed
        and bool(dialogue_units)
        and completed_loudness_count == len(dialogue_units)
    )
    loudness_in_progress = bool(dialogue_units) and 0 < completed_loudness_count < len(dialogue_units)
    statuses["loudness"] = {
        "status": (
            "completed" if loudness_completed
            else "in_progress" if loudness_in_progress
            else "ready" if timing_completed
            else "not_started"
        ),
        "ready": bool(loudness_completed),
        "detail": (
            "All dialogue clips normalized to target broadcast LUFS and peak ceiling."
            if loudness_completed
            else f"{completed_loudness_count}/{len(dialogue_units)} dialogue units normalized."
            if loudness_in_progress
            else "Ready to normalize dialogue loudness after timing fit."
            if timing_completed
            else "Measure source dialogue loudness and match target speech loudness."
        ),
    }
    bg_preserved_path = project_root / "output" / "background_preserved.wav"
    bg_separated_path = project_root / "analysis" / "separation" / "background.wav"
    bg_ready = bg_preserved_path.is_file() or bg_separated_path.is_file()
    mix_manifest_path = project_root / "output" / "mix_manifest.json"

    dialogue_removal_completed = bool(bg_ready)
    statuses["dialogue_removal"] = {
        "status": (
            "completed" if dialogue_removal_completed
            else "ready" if loudness_completed
            else "not_started"
        ),
        "ready": bool(dialogue_removal_completed),
        "detail": (
            "Source dialogue ducked/attenuated while preserving non-dialogue audio."
            if dialogue_removal_completed
            else "Ready to duck/attenuate source dialogue and preserve background."
            if loudness_completed
            else "Replace or duck source dialogue while preserving non-dialogue audio."
        ),
    }

    background_preservation_completed = bool(bg_ready)
    statuses["background_preservation"] = {
        "status": (
            "completed" if background_preservation_completed
            else "ready" if dialogue_removal_completed
            else "not_started"
        ),
        "ready": bool(background_preservation_completed),
        "detail": (
            "Original background music, SFX and ambience preserved for the dub mix."
            if background_preservation_completed
            else "Ready to preserve background audio track for mixing."
            if dialogue_removal_completed
            else "Carry music, SFX and ambience into the dub mix without flattening the scene."
        ),
    }

    mix_completed = bool(mix_path.is_file())
    statuses["mix"] = {
        "status": (
            "completed" if mix_completed
            else "ready" if background_preservation_completed
            else "not_started"
        ),
        "ready": bool(mix_completed),
        "detail": (
            "Dubbed audio mix is present and balanced with preserved background."
            if mix_completed
            else "Ready to build multi-track production mix."
            if background_preservation_completed
            else "Build the production mix after background preservation."
        ),
    }

    rendered_completed = bool(rendered)
    statuses["render"] = {
        "status": (
            "completed" if rendered_completed
            else "ready" if mix_completed
            else "not_started"
        ),
        "ready": bool(rendered_completed),
        "detail": (
            f"Final dubbed movie rendered ({rendered[0].name})."
            if rendered_completed
            else "Ready to render final movie with video and dubbed audio."
            if mix_completed
            else "Render only after the mix is approved."
        ),
    }

    next_stage = None
    for stage in PIPELINE_STAGES:
        state = statuses[stage["id"]]
        if not state["ready"]:
            next_stage = {
                "id": stage["id"],
                "label": stage["label"],
                "requires": list(stage["requires"]),
                "status": state["status"],
                "detail": state["detail"],
            }
            break

    return {
        "project_id": project_id,
        "target_language": target_language or translation.get("target_language"),
        "stages": [
            {
                "id": stage["id"],
                "label": stage["label"],
                "requires": list(stage["requires"]),
                **statuses[stage["id"]],
            }
            for stage in PIPELINE_STAGES
        ],
        "next_recommended": next_stage,
        "dialogue_manifest": {
            "available": bool(dialogue_manifest.get("units")),
            "path": "analysis/dialogue_manifest.json",
            "segment_count": len(dialogue_manifest.get("units", [])),
        },
    }
