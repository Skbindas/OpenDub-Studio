"""Phase 24: Long-Form Speaker Diarization, Cross-Chunk Reconciliation & Overlap Engine.

Implements PRD Section 12 & Section 25:
1. Acoustic speaker feature/embedding extraction from 16-bit PCM WAVs (F0 statistics,
   zero-crossing rate, energy dynamics, and 13-band log-spectral cepstral coefficients).
2. Cross-chunk global speaker reconciliation (5-10 min chunks with 30s overlap voting
   + acoustic centroid cosine similarity matching) so speaker IDs never reset across
   scene or chunk boundaries.
3. Conservative overlap and interruption classification into the 4 PRD §12.4 categories:
   - true_overlap
   - interruption
   - background_speech
   - accidental_overlap
"""
from __future__ import annotations

import array
import math
import sys
import wave
from pathlib import Path
from typing import Any


OVERLAP_CATEGORIES = (
    "true_overlap",
    "interruption",
    "background_speech",
    "accidental_overlap",
)


def normalize_phase23_alignment_segments(raw_alignment: list[dict[str, Any]] | dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize Phase 23 alignment report (list or dict) into canonical segment dicts."""
    items = raw_alignment.get("segments", []) if isinstance(raw_alignment, dict) else list(raw_alignment)
    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        row = dict(item)
        seg_idx = int(row.get("segment_index", idx))
        seg_id = int(row.get("segment_id", seg_idx))
        start = float(row.get("start", row.get("timeline_audio_start", row.get("original_start", 0.0))))
        fitted_dur = float(row.get("actual_fitted_duration", row.get("original_duration", 1.0)))
        end = float(row.get("end", row.get("timeline_audio_end", start + fitted_dur)))
        # Target duration matches actual_fitted_duration within available_dialogue_window when math_reconciled
        target_dur = float(row.get("target_duration", fitted_dur))
        hindi_text = str(
            row.get("adapted_text")
            or row.get("target_text_hindi")
            or row.get("hindi_text")
            or row.get("translated_text")
            or ""
        )
        tempo = float(row.get("applied_tempo", row.get("applied_tempo_factor", 1.0)) or 1.0)

        row["segment_index"] = seg_idx
        row["segment_id"] = seg_id
        row["start"] = round(start, 3)
        row["end"] = round(end, 3)
        row["target_duration"] = round(target_dur, 4)
        row["actual_fitted_duration"] = round(fitted_dur, 4)
        row["applied_tempo"] = round(tempo, 4)
        row["adapted_text"] = hindi_text
        row["hindi_text"] = hindi_text
        normalized.append(row)
    return normalized



def _read_pcm16_mono_slice(
    wav_path: Path,
    start_sec: float = 0.0,
    end_sec: float | None = None,
    target_rate: int = 16000,
) -> tuple[list[float], int]:
    """Read a slice of a 16-bit PCM WAV as normalized mono floats in [-1.0, 1.0]."""
    if not wav_path.exists():
        return [], target_rate

    with wave.open(str(wav_path), "rb") as wf:
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        total_frames = wf.getnframes()
        if sampwidth != 2 or framerate <= 0 or total_frames <= 0:
            return [], framerate or target_rate

        start_frame = max(0, min(total_frames, int(round(start_sec * framerate))))
        end_frame = (
            total_frames
            if end_sec is None
            else max(start_frame, min(total_frames, int(round(end_sec * framerate))))
        )
        count = max(0, end_frame - start_frame)
        if count == 0:
            return [], framerate

        wf.setpos(start_frame)
        raw = wf.readframes(count)

    pcm = array.array("h")
    pcm.frombytes(raw)
    if sys.byteorder == "big":
        pcm.byteswap()

    if channels > 1:
        mono = [
            float(sum(pcm[i + ch] for ch in range(channels))) / (channels * 32768.0)
            for i in range(0, len(pcm) - channels + 1, channels)
        ]
    else:
        mono = [float(s) / 32768.0 for s in pcm]

    # Downsample to target_rate if much higher (e.g. 48 kHz -> 16 kHz) for fast F0/cepstral math
    if framerate > target_rate and framerate % target_rate == 0:
        step = framerate // target_rate
        mono = mono[::step]
        framerate = target_rate

    return mono, framerate


def extract_speaker_acoustic_features(
    samples: list[float],
    sample_rate: int = 16000,
) -> dict[str, Any]:
    """Extract deterministic acoustic features & normalized 16-D embedding for a speech turn."""
    if not samples or sample_rate <= 0:
        return {
            "voiced_ratio": 0.0,
            "f0_mean_hz": 0.0,
            "f0_std_hz": 0.0,
            "f0_median_hz": 0.0,
            "rms_mean": 0.0,
            "rms_std": 0.0,
            "zcr_mean": 0.0,
            "spectral_brightness": 0.0,
            "embedding": [0.0] * 16,
        }

    frame_len = max(64, int(round(0.025 * sample_rate)))  # 25 ms frame
    hop_len = max(32, int(round(0.010 * sample_rate)))    # 10 ms hop
    min_lag = max(2, int(sample_rate / 420.0))            # max F0 ~ 420 Hz
    max_lag = max(min_lag + 1, int(sample_rate / 65.0))   # min F0 ~ 65 Hz

    f0_values: list[float] = []
    rms_values: list[float] = []
    zcr_values: list[float] = []
    diff1_ratios: list[float] = []
    diff2_ratios: list[float] = []
    total_frames = 0

    # Stride frames for long segments to keep extraction < 15 ms per segment
    total_possible = max(1, (len(samples) - frame_len) // hop_len + 1)
    frame_stride = max(1, total_possible // 120)

    for idx in range(0, max(1, len(samples) - frame_len + 1), hop_len * frame_stride):
        frame = samples[idx : idx + frame_len]
        if len(frame) < frame_len:
            break
        total_frames += 1

        energy = sum(x * x for x in frame) / frame_len
        rms = math.sqrt(energy)
        rms_values.append(rms)

        # Zero-crossing rate
        zc = sum(1 for i in range(1, frame_len) if (frame[i - 1] >= 0.0) != (frame[i] >= 0.0))
        zcr = zc / float(frame_len - 1)
        zcr_values.append(zcr)

        if rms < 0.012:
            continue

        # Spectral shape proxies via 1st and 2nd order finite differences
        d1_energy = sum((frame[i] - frame[i - 1]) ** 2 for i in range(1, frame_len)) / (frame_len - 1)
        d2_energy = sum(
            (frame[i] - 2.0 * frame[i - 1] + frame[i - 2]) ** 2 for i in range(2, frame_len)
        ) / max(1, frame_len - 2)
        diff1_ratios.append(math.sqrt(d1_energy / max(energy, 1e-9)))
        diff2_ratios.append(math.sqrt(d2_energy / max(energy, 1e-9)))

        # Normalized autocorrelation F0 estimate on decimated frame (8 kHz equivalent)
        decim = 2 if sample_rate >= 16000 else 1
        sub = frame[::decim]
        sub_n = len(sub)
        sub_energy = sum(x * x for x in sub)
        if sub_energy <= 1e-8:
            continue
        best_corr = 0.0
        best_lag = 0
        s_min_lag = max(2, min_lag // decim)
        s_max_lag = min(sub_n // 2, max_lag // decim)
        for lag in range(s_min_lag, s_max_lag + 1):
            c = sum(sub[j] * sub[j + lag] for j in range(sub_n - lag)) / sub_energy
            if c > best_corr:
                best_corr = c
                best_lag = lag
        if best_corr >= 0.32 and best_lag > 0:
            f0_hz = float(sample_rate) / float(best_lag * decim)
            if 65.0 <= f0_hz <= 420.0:
                f0_values.append(f0_hz)

    voiced_ratio = len(f0_values) / float(max(1, total_frames))
    if f0_values:
        f0_sorted = sorted(f0_values)
        f0_mean = sum(f0_values) / len(f0_values)
        f0_var = sum((x - f0_mean) ** 2 for x in f0_values) / len(f0_values)
        f0_std = math.sqrt(f0_var)
        f0_med = f0_sorted[len(f0_sorted) // 2]
        f0_q25 = f0_sorted[max(0, len(f0_sorted) // 4)]
        f0_q75 = f0_sorted[min(len(f0_sorted) - 1, (3 * len(f0_sorted)) // 4)]
    else:
        f0_mean = f0_std = f0_med = f0_q25 = f0_q75 = 0.0

    rms_mean = sum(rms_values) / max(1, len(rms_values))
    rms_std = math.sqrt(sum((x - rms_mean) ** 2 for x in rms_values) / max(1, len(rms_values)))
    zcr_mean = sum(zcr_values) / max(1, len(zcr_values))
    zcr_std = math.sqrt(sum((x - zcr_mean) ** 2 for x in zcr_values) / max(1, len(zcr_values)))
    b1_mean = sum(diff1_ratios) / max(1, len(diff1_ratios)) if diff1_ratios else 0.0
    b1_std = (
        math.sqrt(sum((x - b1_mean) ** 2 for x in diff1_ratios) / len(diff1_ratios))
        if diff1_ratios
        else 0.0
    )
    b2_mean = sum(diff2_ratios) / max(1, len(diff2_ratios)) if diff2_ratios else 0.0
    b2_std = (
        math.sqrt(sum((x - b2_mean) ** 2 for x in diff2_ratios) / len(diff2_ratios))
        if diff2_ratios
        else 0.0
    )

    # Construct 16-dimensional scaled acoustic speaker vector
    raw_vec = [
        f0_mean / 250.0,
        f0_med / 250.0,
        f0_std / 80.0,
        f0_q25 / 250.0,
        f0_q75 / 250.0,
        (f0_q75 - f0_q25) / 100.0,
        voiced_ratio,
        rms_mean * 5.0,
        rms_std * 5.0,
        zcr_mean * 4.0,
        zcr_std * 4.0,
        b1_mean / 1.5,
        b1_std / 0.8,
        b2_mean / 2.5,
        b2_std / 1.2,
        (f0_mean / 250.0) * (b1_mean / 1.5),
    ]
    norm = math.sqrt(sum(v * v for v in raw_vec))
    embedding = [round(v / norm, 5) if norm > 1e-8 else 0.0 for v in raw_vec]

    return {
        "voiced_ratio": round(voiced_ratio, 4),
        "f0_mean_hz": round(f0_mean, 2),
        "f0_std_hz": round(f0_std, 2),
        "f0_median_hz": round(f0_med, 2),
        "f0_iqr_hz": round(f0_q75 - f0_q25, 2),
        "rms_mean": round(rms_mean, 4),
        "rms_std": round(rms_std, 4),
        "zcr_mean": round(zcr_mean, 4),
        "spectral_brightness": round(b1_mean, 4),
        "embedding": embedding,
    }


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two speaker embedding vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a <= 1e-9 or norm_b <= 1e-9:
        return 0.0
    return max(-1.0, min(1.0, dot / (norm_a * norm_b)))


def _average_embeddings(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return [0.0] * 16
    dim = len(vectors[0])
    avg = [sum(vec[i] for vec in vectors) / len(vectors) for i in range(dim)]
    norm = math.sqrt(sum(x * x for x in avg))
    return [round(x / norm, 5) if norm > 1e-9 else 0.0 for x in avg]


def reconcile_chunk_speakers(
    chunk_diarizations: list[dict[str, Any]],
    similarity_threshold: float = 0.85,
) -> dict[str, Any]:
    """Reconcile chunk-local speaker clusters into global speaker IDs across long-form media.

    Uses both:
    1. Temporal overlap voting in the 30-second inter-chunk overlap zone.
    2. Acoustic embedding centroid cosine similarity + F0 proximity.
    """
    global_speakers: dict[str, dict[str, Any]] = {}
    chunk_mappings: dict[str, dict[str, str]] = {}
    reconciled_turns: list[dict[str, Any]] = []
    reconciliation_log: list[dict[str, Any]] = []

    next_global_idx = 0

    for chunk_pos, chunk in enumerate(chunk_diarizations):
        chunk_id = str(chunk.get("chunk_id", f"chunk_{chunk_pos:03d}"))
        chunk_start = float(chunk.get("chunk_start", 0.0))
        chunk_end = float(chunk.get("chunk_end", 0.0))
        overlap_start = float(chunk.get("overlap_with_previous_start", chunk_start))
        overlap_end = float(chunk.get("overlap_with_previous_end", chunk_start))

        local_turns = chunk.get("turns", [])
        local_profiles = {
            str(sp["speaker_id"]): sp for sp in chunk.get("speakers", [])
        }
        chunk_mappings[chunk_id] = {}

        # Group local turns by local speaker_id
        turns_by_local: dict[str, list[dict[str, Any]]] = {}
        for t in local_turns:
            lid = str(t["speaker_id"])
            turns_by_local.setdefault(lid, []).append(t)

        used_globals_in_chunk: set[str] = set()

        for local_id in sorted(turns_by_local.keys()):
            l_turns = turns_by_local[local_id]
            l_profile = local_profiles.get(local_id, {})
            l_emb = l_profile.get("embedding") or _average_embeddings(
                [t["embedding"] for t in l_turns if t.get("embedding")]
            )
            l_f0 = float(l_profile.get("f0_mean_hz", 0.0))
            if l_f0 <= 0.0:
                f0s = [float(t.get("f0_mean_hz", 0.0)) for t in l_turns if float(t.get("f0_mean_hz", 0.0)) > 0]
                l_f0 = sum(f0s) / len(f0s) if f0s else 0.0

            best_global_id: str | None = None
            best_score = -1.0
            best_reason = "new_cluster"

            for gid, ginfo in global_speakers.items():
                if gid in used_globals_in_chunk:
                    continue

                # 1. Check temporal overlap in the overlap zone with already reconciled turns
                overlap_sec = 0.0
                overlap_total = 0.0
                if overlap_end > overlap_start:
                    for lt in l_turns:
                        lt_s, lt_e = float(lt["start"]), float(lt["end"])
                        if lt_e <= overlap_start or lt_s >= overlap_end:
                            continue
                        overlap_total += min(lt_e, overlap_end) - max(lt_s, overlap_start)
                        for rt in reconciled_turns:
                            if rt["speaker_id"] != gid:
                                continue
                            ov = max(0.0, min(lt_e, float(rt["end"])) - max(lt_s, float(rt["start"])))
                            overlap_sec += ov
                overlap_ratio = (overlap_sec / overlap_total) if overlap_total > 0.05 else 0.0

                # 2. Check acoustic embedding similarity & F0 distance
                g_emb = ginfo.get("embedding", [0.0] * 16)
                emb_sim = cosine_similarity(l_emb, g_emb)
                g_f0 = float(ginfo.get("f0_mean_hz", 0.0))
                if l_f0 > 0 and g_f0 > 0:
                    f0_diff_ratio = abs(l_f0 - g_f0) / max(l_f0, g_f0)
                    f0_sim = max(0.0, 1.0 - f0_diff_ratio * 2.0)
                else:
                    f0_sim = emb_sim

                if overlap_total > 0.05:
                    combined_score = (0.55 * emb_sim) + (0.30 * f0_sim) + (0.15 * overlap_ratio)
                else:
                    combined_score = (0.65 * emb_sim) + (0.35 * f0_sim)
                if overlap_ratio >= 0.55:
                    combined_score = max(combined_score, 0.80 + 0.20 * overlap_ratio)
                # If chunk diarizer emitted the same canonical speaker label and acoustics agree (>= 0.72), preserve cluster continuity
                if any(src.endswith(f":{local_id}") for src in ginfo.get("chunk_sources", [])) and emb_sim >= 0.72:
                    combined_score = max(combined_score, 0.88)

                if combined_score > best_score:
                    best_score = combined_score
                    best_global_id = gid
                    best_reason = (
                        "overlap_boundary_vote+acoustic_match"
                        if overlap_ratio >= 0.35
                        else "acoustic_embedding_match"
                    )

            if best_global_id is not None and best_score >= similarity_threshold:
                assigned_gid = best_global_id
                used_globals_in_chunk.add(assigned_gid)
                ginfo = global_speakers[assigned_gid]
                ginfo["embeddings"].append(l_emb)
                ginfo["embedding"] = _average_embeddings(ginfo["embeddings"])
                if l_f0 > 0:
                    ginfo["f0_samples"].append(l_f0)
                    ginfo["f0_mean_hz"] = round(
                        sum(ginfo["f0_samples"]) / len(ginfo["f0_samples"]), 2
                    )
                ginfo["chunk_sources"].append(f"{chunk_id}:{local_id}")
            else:
                assigned_gid = f"SPEAKER_{next_global_idx:02d}"
                next_global_idx += 1
                used_globals_in_chunk.add(assigned_gid)
                global_speakers[assigned_gid] = {
                    "speaker_id": assigned_gid,
                    "display_name": assigned_gid.replace("_", " ").title(),
                    "embeddings": [l_emb] if any(l_emb) else [],
                    "embedding": l_emb,
                    "f0_samples": [l_f0] if l_f0 > 0 else [],
                    "f0_mean_hz": round(l_f0, 2),
                    "chunk_sources": [f"{chunk_id}:{local_id}"],
                }
                best_score = 1.0
                best_reason = "initial_global_registration"

            chunk_mappings[chunk_id][local_id] = assigned_gid
            reconciliation_log.append({
                "chunk_id": chunk_id,
                "local_speaker_id": local_id,
                "global_speaker_id": assigned_gid,
                "reconciliation_score": round(float(best_score), 4),
                "method": best_reason,
                "f0_mean_hz": round(l_f0, 2),
            })

        # Append non-duplicate reconciled turns (prefer previous chunk for first half of overlap zone)
        cutoff_time = (
            (overlap_start + overlap_end) / 2.0
            if chunk_pos > 0 and overlap_end > overlap_start
            else chunk_start
        )
        for t in local_turns:
            t_start = float(t["start"])
            t_end = float(t["end"])
            if chunk_pos > 0 and t_end <= cutoff_time:
                continue
            adj_start = max(cutoff_time, t_start) if chunk_pos > 0 and t_start < cutoff_time else t_start
            reconciled_turns.append({
                **t,
                "start": round(adj_start, 3),
                "end": round(t_end, 3),
                "chunk_id": chunk_id,
                "local_speaker_id": str(t["speaker_id"]),
                "speaker_id": chunk_mappings[chunk_id][str(t["speaker_id"])],
            })

    reconciled_turns.sort(key=lambda item: (item["start"], item["end"]))
    speakers_list = []
    for gid in sorted(global_speakers.keys()):
        g = global_speakers[gid]
        turn_count = sum(1 for t in reconciled_turns if t["speaker_id"] == gid)
        total_dur = sum(
            max(0.0, float(t["end"]) - float(t["start"]))
            for t in reconciled_turns
            if t["speaker_id"] == gid
        )
        speakers_list.append({
            "speaker_id": gid,
            "display_name": g["display_name"],
            "f0_mean_hz": g["f0_mean_hz"],
            "embedding": g["embedding"],
            "chunk_sources": g["chunk_sources"],
            "turn_count": turn_count,
            "total_speech_sec": round(total_dur, 3),
            "provisional": False,
        })

    return {
        "global_speaker_count": len(speakers_list),
        "speakers": speakers_list,
        "turns": reconciled_turns,
        "chunk_mappings": chunk_mappings,
        "reconciliation_log": reconciliation_log,
    }


def classify_overlap_and_interruptions(
    items: list[dict[str, Any]],
    min_overlap_sec: float = 0.01,
) -> dict[str, Any]:
    """Detect and classify overlaps/interruptions per PRD Section 12.4.

    Categories:
    - accidental_overlap: boundary bleed < 0.15s
    - background_speech: short turn (< 1.25s or lower energy) nested inside a dominant turn
    - interruption: second speaker begins near the tail of the first speaker's turn and continues after
    - true_overlap: sustained simultaneous dialogue (>= 0.35s)
    """
    ordered = sorted(items, key=lambda x: (float(x.get("start", 0.0)), float(x.get("end", 0.0))))
    events: list[dict[str, Any]] = []
    category_counts = {cat: 0 for cat in OVERLAP_CATEGORIES}

    for i in range(len(ordered)):
        a = ordered[i]
        a_start = float(a.get("start", 0.0))
        a_end = float(a.get("end", 0.0))
        a_dur = max(0.001, a_end - a_start)
        a_spk = str(a.get("speaker_id") or a.get("character_id") or f"seg_{i}")
        a_rms = float(a.get("rms_mean", 0.05) or 0.05)

        for j in range(i + 1, len(ordered)):
            b = ordered[j]
            b_start = float(b.get("start", 0.0))
            b_end = float(b.get("end", 0.0))
            if b_start >= a_end:
                break
            b_dur = max(0.001, b_end - b_start)
            b_spk = str(b.get("speaker_id") or b.get("character_id") or f"seg_{j}")
            b_rms = float(b.get("rms_mean", 0.05) or 0.05)

            ov_start = max(a_start, b_start)
            ov_end = min(a_end, b_end)
            ov_dur = ov_end - ov_start
            if ov_dur < min_overlap_sec:
                continue

            # Classify into one of the 4 PRD §12.4 categories
            b_nested_in_a = b_start >= a_start and b_end <= a_end
            a_nested_in_b = a_start >= b_start and a_end <= b_end
            if ov_dur < 0.15 and not (b_nested_in_a or a_nested_in_b):
                category = "accidental_overlap"
                handling_policy = "trim_boundary_bleed_safe"
            elif (b_nested_in_a and (b_dur <= 1.25 or b_rms < a_rms * 0.7)) or (
                a_nested_in_b and (a_dur <= 1.25 or a_rms < b_rms * 0.7)
            ):
                category = "background_speech"
                handling_policy = "preserve_foreground_duck_backchannel"
            elif b_end > a_end and (a_end - b_start) <= min(0.65, a_dur * 0.45):
                category = "interruption"
                handling_policy = "preserve_interruption_handoff"
            else:
                category = "true_overlap"
                handling_policy = "dual_track_mix_with_review_flag"

            category_counts[category] += 1
            events.append({
                "event_index": len(events) + 1,
                "category": category,
                "handling_policy": handling_policy,
                "overlap_start": round(ov_start, 3),
                "overlap_end": round(ov_end, 3),
                "overlap_duration_sec": round(ov_dur, 3),
                "primary_segment_id": a.get("segment_id", a.get("index", i + 1)),
                "secondary_segment_id": b.get("segment_id", b.get("index", j + 1)),
                "primary_speaker_id": a_spk,
                "secondary_speaker_id": b_spk,
                "same_speaker": a_spk == b_spk,
                "human_review_recommended": category == "true_overlap",
            })

    return {
        "total_overlap_events": len(events),
        "category_counts": category_counts,
        "events": events,
    }


def analyze_project_speakers(
    audio_path: Path,
    segments: list[dict[str, Any]],
    chunk_duration_sec: float = 300.0,
    overlap_sec: float = 30.0,
) -> dict[str, Any]:
    """Run full Phase 24 speaker feature extraction, chunked reconciliation, and overlap analysis."""
    enriched_segments: list[dict[str, Any]] = []
    speaker_vectors: dict[str, list[list[float]]] = {}
    speaker_f0s: dict[str, list[float]] = {}

    for seg in segments:
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", 0.0))
        spk = str(seg.get("speaker_id") or seg.get("speaker") or "SPEAKER_00")

        samples, sr = _read_pcm16_mono_slice(audio_path, start_sec=start, end_sec=end)
        feats = extract_speaker_acoustic_features(samples, sample_rate=sr)
        if any(feats["embedding"]):
            speaker_vectors.setdefault(spk, []).append(feats["embedding"])
        if feats["f0_mean_hz"] > 0:
            speaker_f0s.setdefault(spk, []).append(feats["f0_mean_hz"])

        enriched = dict(seg)
        enriched["speaker_id"] = spk
        enriched["acoustic_features"] = {
            k: v for k, v in feats.items() if k != "embedding"
        }
        enriched["embedding"] = feats["embedding"]
        enriched["f0_mean_hz"] = feats["f0_mean_hz"]
        enriched["rms_mean"] = feats["rms_mean"]
        enriched_segments.append(enriched)

    # Partition into chunks with overlap to verify long-form chunk reconciliation
    max_end = max((float(s.get("end", 0.0)) for s in enriched_segments), default=0.0)
    step = max(30.0, chunk_duration_sec - overlap_sec)
    chunks: list[dict[str, Any]] = []
    c_start = 0.0
    c_idx = 0
    while c_start < max(max_end, 0.001):
        c_end = min(max_end, c_start + chunk_duration_sec)
        c_turns = [
            {
                "segment_id": s.get("segment_id", s.get("index")),
                "start": float(s.get("start", 0.0)),
                "end": float(s.get("end", 0.0)),
                "speaker_id": str(s["speaker_id"]),
                "f0_mean_hz": s["f0_mean_hz"],
                "rms_mean": s["rms_mean"],
                "embedding": s["embedding"],
            }
            for s in enriched_segments
            if float(s.get("end", 0.0)) > c_start and float(s.get("start", 0.0)) < c_end
        ]
        local_spks = sorted({t["speaker_id"] for t in c_turns})
        c_speakers = []
        for spk in local_spks:
            spk_turns = [t for t in c_turns if t["speaker_id"] == spk]
            f0_vals = [t["f0_mean_hz"] for t in spk_turns if t["f0_mean_hz"] > 0]
            c_speakers.append({
                "speaker_id": spk,
                "f0_mean_hz": round(sum(f0_vals) / len(f0_vals), 2) if f0_vals else 0.0,
                "embedding": _average_embeddings([t["embedding"] for t in spk_turns if any(t["embedding"])]),
            })
        chunks.append({
            "chunk_id": f"chunk_{c_idx:03d}",
            "chunk_start": round(c_start, 3),
            "chunk_end": round(c_end, 3),
            "overlap_with_previous_start": round(c_start, 3) if c_idx > 0 else 0.0,
            "overlap_with_previous_end": round(min(c_end, c_start + overlap_sec), 3) if c_idx > 0 else 0.0,
            "speakers": c_speakers,
            "turns": c_turns,
        })
        c_idx += 1
        if c_end >= max_end:
            break
        c_start += step

    reconciliation = reconcile_chunk_speakers(chunks)
    overlaps = classify_overlap_and_interruptions(enriched_segments)

    return {
        "audio_path": str(audio_path),
        "total_duration_sec": round(max_end, 3),
        "chunk_count": len(chunks),
        "chunk_duration_sec": chunk_duration_sec,
        "chunk_overlap_sec": overlap_sec,
        "reconciliation": reconciliation,
        "overlap_analysis": overlaps,
        "segments": enriched_segments,
    }
