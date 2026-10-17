from __future__ import annotations

"""Resumable orchestration for full-movie source analysis.

The pipeline deliberately checkpoints each stage to disk. Heavy inference is
sequential so it does not keep multiple model instances resident on low-VRAM
machines. Diarization and source separation are optional when their runtime
dependencies/credentials are unavailable; their status is explicit in manifest.
"""
import hashlib
import json
import os
import uuid
import time
from datetime import datetime, timezone
from pathlib import Path
from bisect import bisect_right
from typing import Any, Callable

from .media import analyze_audio_profile, check_asr_runtime, detect_scenes, extract_audio, probe_media, transcribe, separate_dialogue_candidate
from .diarization import DiarizationSetupError, assign_speakers, diarize
from .atomic_files import replace_with_retry


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def prepare_vocal_audio(separation: dict, output: Path, duration: float) -> Path:
    import soundfile as sf
    if separation.get('status') != 'completed':
        raise RuntimeError('Neural vocal separation must complete before dialogue transcription')
    stem = Path(separation.get('vocals_stem') or separation.get('dialogue_candidate') or '')
    if not stem.is_file():
        raise RuntimeError('Vocal separation produced no usable vocal stem')
    if abs(sf.info(stem).duration-duration) > .05:
        raise RuntimeError('Vocal stem duration does not match the original source timeline')
    extract_audio(stem, output)
    info = sf.info(output)
    if abs(info.duration-duration) > .05 or info.samplerate != 16000 or info.channels != 1:
        raise RuntimeError('Prepared vocal audio duration/format does not preserve the source timeline')
    return output


def align_word_speakers(transcript: dict, diarization: dict) -> dict:
    """Split dialogue at speaker changes while keeping original word timestamps."""
    segments = []
    for source_index, original in enumerate(transcript.get('segments', [])):
        words = original.get('words') or []
        if not words:
            segments.extend(assign_speakers({'segments':[original]},diarization)['segments'])
            continue
        aligned = assign_speakers({'segments':words},diarization)['segments']
        groups = []
        for word in aligned:
            if not groups or groups[-1][0]['speaker_id'] != word['speaker_id']:
                groups.append([])
            groups[-1].append(word)
        for group in groups:
            row = {**original, 'source_segment_index':source_index,
                   'start':group[0]['start'], 'end':group[-1]['end'],
                   'text':''.join(w['text'] for w in group).strip(), 'words':group}
            # Word ownership is authoritative; retain segment-level confidence
            # fields expected by character assignment and timing consumers.
            speaker = group[0]['speaker_id']
            ownership = assign_speakers({'segments':[row]},diarization)['segments'][0]
            ownership['speaker_id'] = speaker
            ownership['speaker_review_required'] = speaker is None or any(w['speaker_review_required'] for w in group)
            ownership['speaker_confidence'] = min(w['speaker_confidence'] for w in group)
            ownership['speaker_review_reason'] = next((w['speaker_review_reason'] for w in group if w['speaker_review_reason']),None)
            segments.append(ownership)
    return {**transcript,'segments':segments,'speaker_registry':diarization.get('speakers',[]),
            'speaker_alignment':'word_timestamps'}


ANALYSIS_SCHEMA_VERSION = 2
_ENGINE_FILES = (
    Path(__file__),
    Path(__file__).with_name("media.py"),
    Path(__file__).with_name("diarization.py"),
    Path(__file__).with_name("speaker_identity.py"),
    Path(__file__).with_name("chunked_asr.py"),
    Path(__file__).with_name("chunk_worker.py"),
)


def _analysis_engine_fingerprint() -> str:
    digest = hashlib.sha256()
    for path in _ENGINE_FILES:
        digest.update(str(path.name).encode())
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<missing>")
    return digest.hexdigest()


def _analysis_options_fingerprint(options: dict[str, Any]) -> str:
    relevant = {
        "model_size": options.get("model_size", "small"),
        "device": options.get("device", "auto"),
        "language": options.get("language"),
        "scene_threshold": float(options.get("scene_threshold", 0.35)),
        "separation_model": options.get("separation_model"),
        "experimental_chunk_asr": bool(options.get("experimental_chunk_asr")),
        "audio_only": bool(options.get("audio_only")),
        "transcribe_vocals": bool(options.get("transcribe_vocals")),
    }
    return hashlib.sha256(
        json.dumps(relevant, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def invalidate_downstream_artifacts(project_root: Path, *, preserve_characters: bool = True) -> None:
    """Archive stale artifacts before clearing active paths; never discard work."""
    root = project_root.resolve()
    archive = root / ".history" / str(uuid.uuid4())
    for name in ("analysis", "segments", "output"):
        path = project_root / name
        if path.exists():
            for child in list(path.iterdir()):
                if preserve_characters and name == "analysis" and child.name == "characters":
                    continue
                target = archive / name / child.name
                if not child.resolve().is_relative_to(root) or not target.resolve().is_relative_to(root):
                    raise RuntimeError("Checkpoint archive path escapes project workspace")
                target.parent.mkdir(parents=True, exist_ok=True)
                replace_with_retry(child, target)
        else:
            path.mkdir(parents=True, exist_ok=True)
    if preserve_characters:
        (project_root / "characters").mkdir(parents=True, exist_ok=True)


def _atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    replace_with_retry(temp, path)


def _job_update(db_path: Path, job_id: str, progress: float, message: str,
                payload: dict[str, Any] | None = None) -> None:
    from .db import connect
    with connect(db_path) as conn:
        if payload is None:
            conn.execute("UPDATE jobs SET progress=?,message=?,updated_at=? WHERE id=?",
                         (progress, message, _now(), job_id))
        else:
            conn.execute("UPDATE jobs SET progress=?,message=?,payload=?,updated_at=? WHERE id=?",
                         (progress, message, json.dumps(payload, ensure_ascii=False), _now(), job_id))
        conn.commit()


def run_full_analysis(*, db_path: Path, project_id: str, job_id: str,
                      project_root: Path, source: Path, options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run or resume deterministic analysis stages, reusing validated artifacts."""
    options = options or {}
    from .kaggle_tasks import project_for
    cloud=project_for(project_root)
    if cloud:
        from .kaggle_operations import remote_plan
        options={**options,'experimental_chunk_asr':True,'processing_plan':remote_plan(project_root),
                 'device':'cuda','compute_provider':'kaggle'}
    analysis = project_root / "analysis"
    analysis.mkdir(parents=True, exist_ok=True)
    manifest_path = analysis / "analysis_manifest.json"
    source_stat = source.stat()
    # Cheap stable fingerprint: metadata plus bounded samples from both ends.
    digest = hashlib.sha256()
    digest.update(f"{source.name}:{source_stat.st_size}:{source_stat.st_mtime_ns}".encode())
    with source.open("rb") as handle:
        digest.update(handle.read(1024 * 1024))
        if source_stat.st_size > 1024 * 1024:
            handle.seek(max(0, source_stat.st_size - 1024 * 1024))
            digest.update(handle.read(1024 * 1024))
    source_fingerprint = digest.hexdigest()
    engine_fingerprint = _analysis_engine_fingerprint()
    options_fingerprint = _analysis_options_fingerprint(options)
    manifest = None
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # A torn/corrupt manifest must not prevent recovery; artifacts are rebuilt.
            manifest = None
    cache_signature_matches = (
        isinstance(manifest, dict)
        and manifest.get("schema_version") == ANALYSIS_SCHEMA_VERSION
        and manifest.get("source_fingerprint") == source_fingerprint
        and manifest.get("engine_fingerprint") == engine_fingerprint
        and manifest.get("options_fingerprint") == options_fingerprint
    )
    if not cache_signature_matches:
        invalidate_downstream_artifacts(project_root, preserve_characters=True)
        analysis.mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema_version": ANALYSIS_SCHEMA_VERSION,
            "project_id": project_id,
            "source": str(source.name),
            "source_fingerprint": source_fingerprint,
            "engine_fingerprint": engine_fingerprint,
            "options_fingerprint": options_fingerprint,
            "created_at": _now(),
            "updated_at": _now(),
            "stages": {},
            "status": "running",
            "recovery_note": "Analysis cache invalidated because source, analysis engine, options, or manifest schema changed.",
        }
    stages: list[tuple[str, float, Callable[[], Any], Path | None]] = []

    source_media_path = analysis / "source_media.json"
    preflight_path = analysis / "analysis_preflight.json"
    audio_path = analysis / "source_16k_mono.wav"
    scenes_path = analysis / "scenes.json"
    audio_profile_path = analysis / "audio_profile.json"
    transcript_path = analysis / "transcript.json"
    diarization_path = analysis / "diarization.json"
    separation_dir = analysis / "separation"
    separation_path = analysis / "separation.json"
    vocals_required = bool(options.get('transcribe_vocals'))
    dialogue_audio_path = analysis / 'vocals_16k_mono.wav' if vocals_required else audio_path

    def cached(name: str, artifact: Path | None) -> bool:
        if not artifact or not artifact.is_file() or artifact.stat().st_size <= 0:
            return False
        record = manifest.get("stages", {}).get(name, {})
        if record.get("status") != "completed":
            return False
        # JSON artifacts are parsed before reuse to reject truncated checkpoints.
        if artifact.suffix.lower() == ".json":
            try:
                json.loads(artifact.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return False
        return True

    def stage(name: str, progress: float, fn: Callable[[], Any], artifact: Path | None = None,
              optional: bool = False, setup_exceptions: tuple[type[BaseException], ...] = ()) -> None:
        if cached(name, artifact):
            _job_update(db_path, job_id, progress, f"Reusing checkpoint: {name.replace('_',' ')}")
            from .work_progress import record_work
            record_work(project_root, name, 1, 1, job_id=job_id, unit="checkpoints")
            return
        _job_update(db_path, job_id, progress, f"Analyzing: {name.replace('_',' ')}")
        record = {"status": "running", "started_at": _now(), "artifact": str(artifact.relative_to(project_root)) if artifact else None}
        manifest["stages"][name] = record
        _atomic_json(manifest_path, manifest)
        try:
            from .work_progress import track, emit
            with track(project_root, job_id, name, "seconds" if name == "transcription" else "checkpoints"):
                emit(0, 1)
                result = fn()
                emit(1, 1)
            record.update({"status": "completed", "completed_at": _now()})
            if isinstance(result, dict):
                record["summary"] = {k: v for k, v in result.items() if k not in {"segments", "words"}}
            elif isinstance(result, list):
                record["item_count"] = len(result)
            _atomic_json(manifest_path, manifest)
        except Exception as exc:
            from .kaggle_tasks import waiting_error
            if waiting_error(exc):
                record.update(status='waiting',error=str(waiting_error(exc)))
                _atomic_json(manifest_path,manifest)
                raise
            recoverable_setup = isinstance(exc, setup_exceptions)
            record.update({"status": "skipped" if optional or recoverable_setup else "failed",
                           "completed_at": _now(), "error": str(exc)})
            _atomic_json(manifest_path, manifest)
            if not optional:
                raise


    scene_context_path = analysis / "scene_context.json"

    def build_scene_context() -> dict[str, Any]:
        scene_rows = json.loads(scenes_path.read_text(encoding="utf-8"))
        transcript_data = json.loads(transcript_path.read_text(encoding="utf-8"))
        profile_data = json.loads(audio_profile_path.read_text(encoding="utf-8")) if audio_profile_path.is_file() else {}
        result = _build_scene_context(transcript_data, scene_rows, profile_data)
        _atomic_json(scene_context_path, result)
        return result

    def validate_source() -> dict[str, Any]:
        from .db import job_cancel_requested
        metadata = probe_media(source, verify_decode=True,
                               cancelled=lambda: job_cancel_requested(db_path, job_id))
        metadata["source_fingerprint"] = source_fingerprint
        _atomic_json(source_media_path, metadata)
        return metadata

    stage("source_media_validate", 0.04, validate_source, source_media_path)

    def validate_asr_runtime() -> dict[str, Any]:
        result = {'provider':'kaggle','status':'deferred_to_remote_worker','runtime_verified':False} if cloud else check_asr_runtime(str(options.get("device", "auto")))
        result["model_size"] = str(options.get("model_size", "small"))
        _atomic_json(preflight_path, result)
        return result

    stage("analysis_preflight", 0.07, validate_asr_runtime, preflight_path)
    stage("audio_extract", 0.12, lambda: extract_audio(source, audio_path), audio_path)
    stage("audio_profile", 0.18, lambda: analyze_audio_profile(audio_path, audio_profile_path), audio_profile_path)
    def source_scenes():
        if not options.get("audio_only"):
            return detect_scenes(source, scenes_path, float(options.get("scene_threshold", 0.35)))
        duration = json.loads(source_media_path.read_text(encoding="utf-8"))["duration_sec"]
        data = [{"scene_index": 0, "start_sec": 0, "end_sec": duration, "method": "audio_only_timeline"}]
        _atomic_json(scenes_path, data)
        return data
    stage("scene_detect", 0.26, source_scenes, scenes_path)

    def do_separation() -> dict[str, Any]:
        from .background_preservation import extract_full_fidelity_audio
        stereo = extract_full_fidelity_audio(source, analysis / "source_48k_stereo.wav")
        result = separate_dialogue_candidate(stereo, separation_dir, options.get("separation_model"),
                                             force_chunks=vocals_required,
                                             visible_helpers=bool(options.get('visible_helpers')),
                                             separation_workers=options.get('separation_workers'))
        if vocals_required and result.get('status') != 'completed':
            raise RuntimeError(result.get('error') or 'Neural vocal separation failed; mixed soundtrack transcription disabled')
        _atomic_json(separation_path, result)
        return result

    if vocals_required:
        stage('vocal_separation', .30, do_separation, separation_path)
        stage('vocal_audio_prepare', .34,
              lambda: prepare_vocal_audio(json.loads(separation_path.read_text(encoding='utf-8')),
                                          dialogue_audio_path, json.loads(source_media_path.read_text(encoding='utf-8'))['duration_sec']),
              dialogue_audio_path)

    def do_transcription():
        if options.get("experimental_chunk_asr"):
            from .chunked_asr import transcribe_chunked
            from .work_progress import track
            from .db import job_cancel_requested
            plan = options.get("processing_plan") or {}
            duration = json.loads(source_media_path.read_text(encoding="utf-8"))["duration_sec"]
            with track(project_root, job_id, "transcription", "chunks"):
                result = transcribe_chunked(dialogue_audio_path, project_root / "chunks/asr", duration, plan,
                                           model_size=str(options.get("model_size", "small")), language=options.get("language"),
                                           visible_helpers=bool(options.get("visible_helpers")),
                                           cancelled=lambda: job_cancel_requested(db_path, job_id))
        else:
            result = transcribe(dialogue_audio_path, str(options.get("model_size", "small")), options.get("language"), str(options.get("device", "auto")))
        result.update(audio_source='separated_vocals' if vocals_required else 'original_mix',
                      timebase='source_media_seconds', audio_path=str(dialogue_audio_path),
                      timing_method='asr_word_timestamps')
        return _write_transcript(result, transcript_path)
    stage("transcription", 0.48, do_transcription, transcript_path)

    hf_token = options.get("hf_token") or os.getenv("HF_TOKEN")
    if cloud:hf_token='offline-owner-authorized-snapshot'
    def do_diarize() -> dict[str, Any]:
        from .db import job_cancel_requested
        latest=[0.]
        def speaker_progress(phase,value):
            if time.monotonic()-latest[0]>.5:
                latest[0]=time.monotonic();_job_update(db_path,job_id,.68+.17*value,phase)
                from .work_progress import emit
                emit(value,1)
        result = diarize(dialogue_audio_path, diarization_path, hf_token,
                         cancelled=lambda:job_cancel_requested(db_path,job_id),progress=speaker_progress)
        if result.get('schema_version',0)>=3:
            from .speaker_identity import reconcile_identities
            from .chunk_execution import digest
            result=reconcile_identities(result,project_root/'characters'/'speaker_identity.json',digest(source))
            from .speaker_corrections import apply_identity_overrides
            corrections=project_root/'characters/speaker_overrides.json'
            if corrections.exists():result=apply_identity_overrides(result,json.loads(corrections.read_text(encoding='utf-8')))
            from .voice_bank_quality import safe_reference_windows
            from .automatic_dialogue import measure_vocal_type
            for speaker in result['speakers']:
                windows=safe_reference_windows(result,speaker['speaker_id'],minimum=.8,maximum=4)[:3]
                if windows:
                    speaker['vocal_profile']=measure_vocal_type(dialogue_audio_path,[(w['start'],w['end']) for w in windows])
                else:speaker['vocal_profile']={'vocal_type':'unknown','method':'no_clean_source_windows','exact_gender_inferred':False}
            _atomic_json(diarization_path,result)
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
        aligned = align_word_speakers(transcript, result)
        _atomic_json(transcript_path, aligned)
        return result
    stage("speaker_diarization", 0.68, do_diarize, diarization_path,
          optional=not bool(hf_token), setup_exceptions=(DiarizationSetupError,))

    if not vocals_required:
        stage("vocal_separation", 0.81, do_separation, separation_path, optional=True)
    stage("scene_context", 0.88, build_scene_context, scene_context_path)

    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    scenes = json.loads(scenes_path.read_text(encoding="utf-8"))
    timeline = _build_timeline(transcript, scenes, separation_path)
    if preflight_path.is_file():
        try:
            timeline["analysis_preflight"] = json.loads(preflight_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            timeline["analysis_preflight"] = {"status": "unavailable"}
    if source_media_path.is_file():
        try:
            timeline["source_media"] = json.loads(source_media_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            timeline["source_media"] = {"status": "unavailable"}
    if scene_context_path.is_file():
        try:
            timeline["scene_context"] = json.loads(scene_context_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            timeline["scene_context"] = {"status": "unavailable"}
    if audio_profile_path.is_file():
        try:
            timeline["audio_profile"] = json.loads(audio_profile_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            timeline["audio_profile"] = {"status": "unavailable"}
    timeline_path = analysis / "timeline.json"
    if diarization_path.exists():
        evidence=json.loads(diarization_path.read_text(encoding='utf-8'))
        timeline['speaker_evidence']={k:evidence.get(k) for k in ('schema_version','raw_overlap_available','overlap_events','coverage','identity_source_sha256')}
    _atomic_json(timeline_path, timeline)
    skipped = [name for name, record in manifest["stages"].items() if record.get("status") == "skipped"]
    manifest.update({
        "updated_at": _now(),
        "status": "completed",
        "optional_stages_skipped": skipped,
        "timeline": str(timeline_path.relative_to(project_root)),
        "segment_count": len(timeline["segments"]),
        "scene_count": len(scenes),
        "detected_language": transcript.get("language"),
        "engine_fingerprint": engine_fingerprint,
        "options_fingerprint": options_fingerprint,
    })
    _atomic_json(manifest_path, manifest)
    notice = ("Analysis complete; optional stages skipped: " + ", ".join(skipped)) if skipped else "Full movie analysis complete; timeline persisted."
    _job_update(db_path, job_id, 0.98, notice)
    return {"manifest": str(manifest_path), "timeline": str(timeline_path),
            "segments": len(timeline["segments"]), "scenes": len(scenes),
            "language": transcript.get("language"), "stage_status": {k:v["status"] for k,v in manifest["stages"].items()}}


def _write_transcript(result: dict[str, Any], path: Path) -> dict[str, Any]:
    _atomic_json(path, result)
    return result


def _build_scene_context(transcript_data: dict[str, Any], scene_rows: list[dict[str, Any]],
                         profile_data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build deterministic transcript/silence context aligned to source-time scenes."""
    profile_data = profile_data or {}
    speech = transcript_data.get("segments", [])
    contexts = []
    for scene in scene_rows:
        start = float(scene.get("start_sec", 0))
        end_value = scene.get("end_sec")
        end = float(end_value) if end_value is not None else float(transcript_data.get("duration") or start)
        dialogue = [(idx, seg) for idx, seg in enumerate(speech)
                    if float(seg.get("start", 0)) < end and float(seg.get("end", 0)) > start]
        silences = []
        for silence in profile_data.get("silence_regions", []):
            ss = float(silence.get("start_sec", 0))
            se = float(silence.get("end_sec")) if silence.get("end_sec") is not None else ss
            overlap = max(0.0, min(end, se) - max(start, ss))
            if overlap:
                silences.append({"start_sec": max(start, ss), "end_sec": min(end, se),
                                 "overlap_sec": round(overlap, 3)})
        contexts.append({
            "scene_index": scene.get("scene_index"), "start_sec": start, "end_sec": end_value,
            "duration_sec": round(max(0.0, end-start), 3),
            "dialogue_segment_count": len(dialogue),
            "dialogue_segment_ids": [f"seg-{idx+1:06d}" for idx, _ in dialogue],
            "speaker_ids": sorted({seg.get("speaker_id") for _, seg in dialogue if seg.get("speaker_id")}),
            "silence_overlap_sec": round(sum(x["overlap_sec"] for x in silences), 3),
            "silence_regions": silences, "context_status": "signal_and_transcript_summary",
            "notice": "Visual narrative understanding and dialogue intent analysis are not yet performed."
        })
    return {"schema_version": 1, "method": "scene_transcript_signal_alignment",
            "scene_count": len(contexts), "scenes": contexts}


def _build_timeline(transcript: dict[str, Any], scenes: list[dict[str, Any]],
                    separation_path: Path) -> dict[str, Any]:
    rows = []
    ordered_scenes = sorted(scenes, key=lambda item: float(item.get("start_sec", 0)))
    scene_starts = [float(item.get("start_sec", 0)) for item in ordered_scenes]
    for idx, segment in enumerate(transcript.get("segments", [])):
        start, end = float(segment.get("start", 0)), float(segment.get("end", 0))
        scene_pos = bisect_right(scene_starts, start) - 1
        scene = ordered_scenes[scene_pos] if scene_pos >= 0 else None
        if scene and scene.get("end_sec") is not None and start >= float(scene["end_sec"]):
            scene = None
        rows.append({
            "segment_id": f"seg-{idx+1:06d}", "start_sec": start, "end_sec": end,
            "text": segment.get("text", ""), "words": segment.get("words", []),
            "speaker_id": segment.get("speaker_id"), "character_id": segment.get("character_id"),
            "confidence": segment.get("confidence"),
            "speaker_confidence": segment.get("speaker_confidence"),
            "no_speech_prob": segment.get("no_speech_prob"),
            "scene_index": scene.get("scene_index") if scene else None,
            "emotion": None, "emotion_status": "not_analyzed",
            "audio_class": "speech_candidate", "review_required": segment.get("speaker_id") is None
        })
    separation = json.loads(separation_path.read_text(encoding="utf-8")) if separation_path.exists() else {}
    return {"schema_version": 2, "generated_at": _now(), "timebase": "source_media_seconds",
            "audio_source": transcript.get('audio_source'),
            "timing_method": transcript.get('timing_method'),
            "speaker_alignment": transcript.get('speaker_alignment'),
            "language": transcript.get("language"), "segments": rows, "scenes": scenes,
            "audio_assets": {"dialogue_candidate": separation.get("dialogue_candidate"),
                             "background_candidate": separation.get("background_candidate"),
                             "original_mix": separation.get("original_mix")},
            "analysis_gaps": ["emotion/prosody inference pending Phase 13",
                              "dialogue-vs-music/SFX classification pending Phase 14"]}
