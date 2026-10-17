"""Evidence-based reference auditing. Metadata is never a purity certificate."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid

import numpy as np
import soundfile as sf

SCHEMA_VERSION = 1
AGE_BANDS = {"unknown", "toddler", "child", "adolescent", "young_adult", "adult", "middle_aged", "older"}
VOICE_TYPES = {"unknown", "masculine", "feminine", "androgynous"}


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    pending.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    pending.replace(path)


def fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audio_metrics(path: Path) -> dict:
    audio, rate = sf.read(path, always_2d=True, dtype="float32")
    if not len(audio) or rate <= 0 or not np.isfinite(audio).all():
        raise ValueError("Reference contains no finite audio samples")
    mono = audio.mean(axis=1)
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
    peak = float(np.max(np.abs(audio)))
    # Fixed tones are not speech. This flag is conservative, not a speaker detector.
    n = min(len(mono), rate * 2)
    powers = np.abs(np.fft.rfft(mono[:n] * np.hanning(n))) ** 2
    total = float(powers.sum())
    tone_ratio = float(np.sort(powers)[-12:].sum() / total) if total else 0.0
    return {"duration_sec": round(len(audio) / rate, 4), "sample_rate": rate,
            "channels": audio.shape[1], "rms_dbfs": round(20 * np.log10(max(rms, 1e-12)), 2),
            "peak_dbfs": round(20 * np.log10(max(peak, 1e-12)), 2),
            "clipped_fraction": float(np.mean(np.abs(audio) >= 0.999)),
            "fixed_tone_suspected": tone_ratio > 0.97,
            "tone_power_fraction": round(tone_ratio, 4)}


def classify_reference(metrics: dict, asr: dict | None, diarization: dict | None) -> dict:
    """Keep automatic findings provisional until source/isolation/listening review."""
    reasons = []
    status = "needs_review"
    segments = (asr or {}).get("segments", [])
    reliable = [s for s in segments if s.get("text", "").strip()
                and s.get("no_speech_prob", 0) < 0.6 and s.get("avg_logprob", 0) > -1.2]
    turns = (diarization or {}).get("turns", [])
    labels = {t["speaker_id"] for t in turns if t["end"] - t["start"] >= 0.15}
    overlaps = []
    for index, left in enumerate(turns):
        for right in turns[index + 1:]:
            if left["speaker_id"] == right["speaker_id"]:
                continue
            start, end = max(left["start"], right["start"]), min(left["end"], right["end"])
            if end - start > 0.05:
                overlaps.append({"start": start, "end": end})
    if metrics.get("rms_dbfs", 0) < -65:
        status = "rejected_no_speech"
        reasons.append("silent_or_near_silent")
    elif metrics.get("fixed_tone_suspected"):
        status = "rejected_non_speech"
        reasons.append("fixed_tone_not_a_clone")
    elif asr is not None and not reliable:
        status = "rejected_no_speech" if diarization is not None and not turns else "needs_review"
        reasons.append("no_reliable_words_detected")
    elif overlaps:
        status = "overlapping_speakers"
        reasons.append("simultaneous_speakers_require_alternative_or_verified_separation")
    elif len(labels) > 1:
        status = "multiple_speakers"
        reasons.append("sequential_turns_can_be_split")
    elif reliable and len(labels) == 1:
        status = "single_speaker_candidate"
        reasons.append("automatic_single_speaker_requires_source_and_background_review")
    else:
        reasons.append("speech_or_speaker_evidence_incomplete")
    if metrics.get("clipped_fraction", 0) > 0.001:
        reasons.append("clipping_requires_repair")
    duration = metrics.get("duration_sec", 0)
    if not 3 <= duration <= 10:
        reasons.append("outside_omnivoice_reference_range_3_to_10_seconds")
    return {"status": status, "reasons": reasons, "speaker_count_detected": len(labels),
            "overlaps": overlaps, "speech_text": " ".join(s["text"].strip() for s in reliable),
            "background_status": "unverified", "identity_status": "unverified",
            "clone_status": "not_tested", "eligible_for_defaults": False}


def exclusive_windows(turns: list[dict], speaker: str, minimum: float = 3, maximum: float = 10) -> list[dict]:
    """Return same-speaker intervals minus all competing voices, never mixed crops."""
    spans = sorted((t["start"], t["end"]) for t in turns if t["speaker_id"] == speaker)
    merged = []
    for start, end in spans:
        # Natural pauses belong to the same voice reference. Competing turns
        # are still subtracted below, including turns inside those pauses.
        if merged and start <= merged[-1][1] + 1.5:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    for other in turns:
        if other["speaker_id"] == speaker:
            continue
        pieces = []
        for start, end in merged:
            if other["end"] <= start or other["start"] >= end:
                pieces.append((start, end))
            else:
                if other["start"] > start:
                    pieces.append((start, other["start"]))
                if other["end"] < end:
                    pieces.append((other["end"], end))
        merged = pieces
    return [{"start": round(s, 4), "end": round(min(e, s + maximum), 4), "speaker_id": speaker}
            for s, e in sorted(merged, key=lambda pair: pair[1] - pair[0], reverse=True) if e - s >= minimum]


def safe_reference_windows(diarization: dict,speaker: str,minimum=3,maximum=10) -> list[dict]:
    if not diarization.get('raw_overlap_available') and 'regular_turns' not in diarization:return []
    return exclusive_windows(diarization.get('regular_turns',diarization.get('turns',[])),speaker,minimum,maximum)


def reviewed_eligibility(record: dict) -> tuple[bool, list[str]]:
    review = record.get("review", {})
    required = ("single_speaker", "speech_present", "background_clean", "identity_confirmed", "clone_identity_passed", "naturalness_passed", "dialogue_content_passed")
    missing = [name for name in required if review.get(name) is not True]
    clone = record.get("clone", {})
    if not clone.get("reference_conditioned") or clone.get("status") != "completed":
        missing.append("genuine_clone_output")
    if clone.get("reference_sha256") != record.get("sha256"):
        missing.append("clone_reference_hash_mismatch")
    if clone.get("ref_text") != record.get("audit", {}).get("speech_text"):
        missing.append("clone_reference_transcript_mismatch")
    reference = Path(record.get("reference_path", ""))
    output = Path(clone.get("file", ""))
    if not reference.is_file() or fingerprint(reference) != record.get("sha256"):
        missing.append("reference_missing_or_changed")
    if not output.is_file() or fingerprint(output) != clone.get("output_sha256"):
        missing.append("clone_missing_or_changed")
    status = record.get("audit", {}).get("status", "")
    if status != "single_speaker_candidate":
        missing.append("reference_requires_single_speaker_reaudit")
    metrics = record.get("metrics", {})
    if not 3 <= metrics.get("duration_sec", 0) <= 10.01:
        missing.append("reference_duration_outside_engine_range")
    if metrics.get("fixed_tone_suspected") or metrics.get("clipped_fraction", 0) > 0.001:
        missing.append("reference_audio_quality_requires_repair")
    return not missing, missing


def select_repaired_reference(record: dict, candidate: dict) -> dict:
    """Retain original references when a human selects a repaired speaker."""
    import copy
    clone = candidate.get("clone", {})
    reference, output = Path(candidate.get("path", "")), Path(clone.get("file", ""))
    if (candidate.get("audit", {}).get("status") != "single_speaker_candidate" or
        not 3 <= candidate.get("metrics", {}).get("duration_sec", 0) <= 10.01 or
        not reference.is_file() or fingerprint(reference) != candidate.get("sha256") or
        clone.get("status") != "completed" or not clone.get("reference_conditioned") or
        clone.get("reference_sha256") != candidate.get("sha256") or
        clone.get("ref_text") != candidate.get("audit", {}).get("speech_text") or
        not output.is_file() or fingerprint(output) != clone.get("output_sha256")):
        raise ValueError("Repair reference/audition is missing, changed or requires further analysis")
    updated = copy.deepcopy(record)
    updated.setdefault("catalog_reference_sha256", record["sha256"])
    updated.setdefault("reference_history", []).append({key:copy.deepcopy(record.get(key))
        for key in ("reference_path","sha256","audit","metrics","clone","review")})
    updated.update(reference_path=str(reference), sha256=candidate["sha256"],
                   audit=copy.deepcopy(candidate["audit"]), metrics=copy.deepcopy(candidate["metrics"]),
                   clone=copy.deepcopy(clone), review={}, audition_acceptance={})
    return updated


def promote_defaults(records: list[dict], catalog_ids: set[str], destination: Path) -> dict:
    """Activation is all-or-nothing; legacy files retained until all target reviews pass."""
    by_id = {record["voice_id"]: record for record in records}
    blockers = {voice_id: reviewed_eligibility(by_id.get(voice_id, {}))[1] for voice_id in catalog_ids}
    blockers = {key: value for key, value in blockers.items() if value}
    if blockers:
        raise ValueError(f"Default promotion blocked: {len(blockers)}/{len(catalog_ids)} voices need review")
    active = {"schema_version":1, "voice_ids":sorted(catalog_ids),
              "legacy_defaults_active":False, "activated_at":datetime.now(timezone.utc).isoformat(),
              "records":[by_id[key] for key in sorted(catalog_ids)]}
    write_report(destination, active)
    return active


def bank_summary(records: list[dict]) -> dict:
    return {"total": len(records), "statuses": dict(Counter(r.get("audit", {}).get("status", "not_audited") for r in records)),
            "ready_for_defaults": sum(reviewed_eligibility(r)[0] for r in records),
            "measured_at": datetime.now(timezone.utc).isoformat()}
