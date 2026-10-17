"""Real, fail-closed orchestration of the existing studio pipeline."""
from __future__ import annotations

import json
import time
from pathlib import Path
from .atomic_files import replace_with_retry
from .work_progress import track, emit, read_work
from .kaggle_tasks import RemoteWaiting


class DialogueReviewRequired(RuntimeError):
    """Quality checkpoint requiring edits rather than a broken engine."""


class SpeakerReviewRequired(DialogueReviewRequired):
    """Expected pause after analysis, before translation and voice generation."""


def read_status(base: Path) -> dict:
    try:
        return json.loads((base / "auto_dub_status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_status(base: Path, status: dict) -> None:
    base.mkdir(parents=True, exist_ok=True)
    target = base / "auto_dub_status.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    replace_with_retry(temporary, target)


def verify_dialogue_ready(base: Path, *, strict_duration: bool = True) -> None:
    manifest = json.loads((base / "analysis/dialogue_manifest.json").read_text(encoding="utf-8"))
    units = manifest.get("units") or []
    if not units:
        raise RuntimeError("No dialogue units found. Review transcription before dubbing.")
    for unit in units:
        timing = unit.get("timing") or {}
        tts = unit.get("tts") or {}
        timing_status = timing.get("status")
        tts_status = tts.get("status")
        is_clamped = timing_status == "needs_review" and timing.get("duration_fit_limited")
        if strict_duration:
            if tts_status != "completed" or timing_status != "completed" or timing.get("duration_fit_limited"):
                raise RuntimeError(f"Dialogue {unit.get('segment_index')} needs synthesis or timing review. Adapt the Hindi line and fit again; speech will not be cut or excessively accelerated.")
        else:
            if tts_status != "completed" or (timing_status != "completed" and not is_clamped):
                raise RuntimeError(f"Dialogue {unit.get('segment_index')} needs synthesis or timing review. Adapt the Hindi line and fit again; speech will not be cut or excessively accelerated.")
        for record, keys in ((tts, ("audio_path", "output_path")), (timing, ("fit_audio", "output_path"))):
            value = next((record.get(key) for key in keys if record.get(key)), None)
            path = Path(value) if value else None
            if path and not path.is_absolute():
                path = base / path
            if path is None or not path.is_file() or path.stat().st_size == 0:
                raise RuntimeError(f"Dialogue {unit.get('segment_index')} audio artifact is missing. Regenerate and fit the line before mixing.")


def synthesis_artifacts_ready(base: Path) -> bool:
    """Use the fit-only budget only when every required speech clip is saved."""
    try:
        units = json.loads((base / 'analysis/dialogue_manifest.json').read_text(encoding='utf-8')).get('units') or []
        if not units:
            return False
        for unit in units:
            tts = unit.get('tts') or {}
            value = tts.get('audio_path') or tts.get('output_path')
            if tts.get('status') != 'completed' or not value:
                return False
            path = Path(value)
            if not path.is_absolute():
                path = base / path
            if not path.is_file() or path.stat().st_size == 0:
                return False
        return True
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def build_balanced_mix(studio, project_id: str, base: Path) -> dict:
    """Bounded dialogue-only leveling; background and source speech remain intact."""
    units = json.loads((base / 'analysis/dialogue_manifest.json').read_text(encoding='utf-8')).get('units') or []
    current_level = min((float((u.get('loudness') or {}).get('target_lufs') or -16) for u in units), default=-16)
    attempts = [None] + [level for level in (-20, -22, -24) if level < current_level]
    for level in attempts:
        if level is not None:
            print(f'[OpenDub mix] Balancing dialogue to {level} LUFS; background gain unchanged.', flush=True)
            from .kaggle_tasks import project_for
            if project_for(base):
                from .kaggle_operations import normalize_batch,cancellation
                results=normalize_batch(base,units,level,cancellation(base))
                for index,result in results.items():
                    studio.update_dialogue_manifest_loudness(manifest_path=base/'analysis/dialogue_manifest.json',
                        segment_index=index,status='completed',normalized_audio=result['file'],target_lufs=level)
            else:
                for index, unit in enumerate(units):
                    studio.normalize_segment(project_id, int(unit.get('segment_index', index)), level)
        try:
            return studio.build_mix(project_id, studio.MixRequest(duck_background=False, protect_dialogue_peaks=True))
        except Exception as exc:
            if 'Mix would clip' not in str(getattr(exc, 'detail', exc)):
                raise
            last_error = exc
    raise DialogueReviewRequired('Mix still clips at the dialogue leveling limit. Review dialogue overlap and levels; background and completed files retained.') from last_error


def execute_auto_dub(job_id: str, project_id: str, options: dict) -> None:
    from . import app as studio
    base = studio.project_dir(project_id)
    state = read_status(base)
    # Worker lease recovery can re-enter the same job without another browser
    # POST. Durable completed stages must still be reused in that case.
    if any(stage.get("status") == "completed" for stage in state.get("stages") or []):
        state["resuming"] = True
    # Keep original options even if a stage updates the worker's payload.
    options = state.get("options") or options
    state.update(status="running", job_id=job_id, start_time=time.time(), auto_download_ready=False, error=None)
    stages = state.setdefault("stages", [dict(s, status="pending", percent=0) for s in studio.AUTO_DUB_STAGES])

    def reusable(index: int, *files: str) -> bool:
        return bool(state.get("resuming") and stages[index].get("status") == "completed"
                    and all((base / file).is_file() and (base / file).stat().st_size > 0 for file in files))

    def progress(index: int, percent: float, label: str) -> None:
        if studio.job_cancel_requested(studio.DB_PATH, job_id):
            raise InterruptedError("Auto-dub cancelled. Intermediate files retained.")
        for previous in stages[:index]:
            previous.update(status="completed", percent=100)
        stages[index].update(status="running", percent=0)
        state.update(current_stage=stages[index]["key"], current_stage_label=label, progress_percent=percent,
                     elapsed_seconds=round(time.time() - state["start_time"], 1), eta_seconds=None)
        save_status(base, state)
        with studio.connect(studio.DB_PATH) as conn:
            conn.execute("UPDATE jobs SET status='running', progress=?,message=?,payload=?,updated_at=? WHERE id=?",
                         (percent / 100, label, json.dumps(options), studio.now(), job_id))

    def checked(operation, *args):
        operation(job_id, project_id, *args)
        result = studio.get_job(studio.DB_PATH, job_id) or {}
        if result.get("status") in {"failed", "cancelled"}:
            raise RuntimeError(result.get("message") or "Pipeline stage failed")
        payload = result.get("payload") or {}
        if payload.get("failed_count") or payload.get("failed"):
            raise RuntimeError(result.get("message") or "Dialogue needs review")
        if payload.get("needs_review_count") and not options.get("allow_advisory_review", False):
            raise DialogueReviewRequired(result.get("message") or "Dialogue needs review")

    try:
        analysis_ready = reusable(0, "analysis/transcript.json", "analysis/diarization.json", "analysis/dialogue_manifest.json")
        synthesis_ready = analysis_ready and synthesis_artifacts_ready(base)
        capacity = studio.project_processing_plan(project_id, model_size=options.get("model_size", "small"),
                                                  workload="fit" if synthesis_ready else "speech" if analysis_ready else "analysis", bounded_analysis=True)
        state["processing_plan"] = capacity
        save_status(base, state)
        print(f"[OpenDub capacity] {capacity['heavy_workers']} heavy workers; {capacity['cpu_threads_per_worker']} threads each; ASR {capacity['asr_device']}; {capacity['chunk_seconds']}s chunks", flush=True)
        if not capacity["admitted"]:
            raise RuntimeError("Processing paused: " + " ".join(capacity["reasons"]) + " Completed project files were retained.")
        if not analysis_ready and not studio.os.getenv("HF_TOKEN") and capacity.get('compute_provider')!='kaggle':
            raise RuntimeError("Speaker identification requires Hugging Face Community-1 access. Accept the model conditions and configure HF_TOKEN locally, then rerun. Existing project files were retained.")
        if not reusable(0, "analysis/transcript.json", "analysis/diarization.json", "analysis/dialogue_manifest.json"):
            progress(0, 2, "Analyzing source audio, scenes and dialogue")
            checked(studio.execute_full_analysis, {
                "model_size": options.get("model_size", "small"), "device": capacity["asr_device"],
                "language": None if options.get("source_language", "auto") == "auto" else options["source_language"],
                "experimental_chunk_asr": bool(options.get("experimental_chunk_asr")),
                "visible_helpers": bool(options.get("visible_helpers")), "processing_plan": capacity,
                "audio_only": options.get("audio_only", True),
                "transcribe_vocals": options.get('transcribe_vocals',True),
                "separation_model": options.get('separation_model','vocals_mel_band_roformer.ckpt'),
                "separation_workers": options.get('separation_workers'),
            })
        transcript = json.loads((base / "analysis/transcript.json").read_text(encoding="utf-8"))
        if not transcript.get("segments"):
            raise RuntimeError("No speech detected. Review source audio and ASR settings.")
        state["detected_language"] = transcript.get("language") or "unknown"
        if not reusable(1, "analysis/transcript.json"):
            progress(1, 30, "Transcript ready; reviewing speaker identities")
        if reusable(2, "characters/registry.json"):
            registry = studio.read_character_registry(project_id)
        else:
            progress(2, 38, "Synchronizing detected speakers and voice assignments")
            registry = studio.sync_characters(project_id)
        if not registry.get("characters"):
            raise RuntimeError(registry.get("notice") or "No speaker identities available. Review diarization before translation.")
        diarization_evidence=json.loads((base/'analysis/diarization.json').read_text(encoding='utf-8')) if (base/'analysis/diarization.json').exists() else {}
        if options.get('review_before_dubbing',False) and not synthesis_ready and diarization_evidence.get('schema_version',0)>=3:
            from .speaker_review import review_state
            review=review_state(base,registry)
            state['speaker_review']=review
            if not review['ready_for_dubbing']:
                raise SpeakerReviewRequired('Review speakers and lock Hindi voices: '+' '.join(review['blocking']))
        if not reusable(3, "analysis/translated_transcript.json", "analysis/dialogue_manifest.json"):
            progress(3, 45, "Translating timestamped dialogue into Hindi")
            with track(base, job_id, "translation", "lines"):
                translation_result = studio.translate_project(project_id, studio.TranslationRequest(
                    target_language=options.get("target_language", "hi"), source_language=state["detected_language"],
                    conversational_hindi=options.get("conversational_hindi", True)))
                if translation_result and translation_result.get('errors'):
                    raise DialogueReviewRequired(f"{translation_result['errors']} dialogue translation errors require repair before synthesis. Valid translations and completed project files were retained.")
        from .speaker_review import voice_locked,review_state
        reviewed_cast=bool(diarization_evidence.get('schema_version',0)>=3 and review_state(base,registry)['ready_for_dubbing'])
        if options.get("automatic_voice_selection", False) and not reusable(2, "characters/registry.json") and not reviewed_cast and not all(voice_locked(c) for c in registry['characters']):
            from .automatic_dialogue import assign_automatic_voices
            registry = assign_automatic_voices(base, registry, studio.DATA_ROOT)
            studio.write_character_registry(project_id, registry)
            studio.refresh_dialogue_manifest(project_id)
        speech_ready = False
        if reusable(4, "analysis/dialogue_manifest.json", "analysis/translated_transcript.json"):
            try:
                verify_dialogue_ready(base)
                speech_ready = True
            except RuntimeError:
                pass  # A deliberate line edit invalidates only that line's speech.
        if not speech_ready:
            if not synthesis_ready:
                progress(4, 60, "Resuming missing dialogue clips with assigned voices" if state.get("resuming") else "Synthesizing dialogue with assigned voices")
                checked(studio.execute_batch_synthesis, {"voice_model_path": options.get("voice_model_path")})
            progress(4, 72, "Fitting dialogue without cutting speech")
            checked(studio.execute_batch_fit, {"max_speedup": 1.15, "max_slowdown": 0.9, "normalize": True})
        verify_dialogue_ready(base)
        if analysis_ready:
            from .background_preservation import cached_separation
            stems = cached_separation(base / 'analysis/source_48k_stereo.wav', base / 'analysis/separation',
                                      options.get('separation_model', 'vocals_mel_band_roformer.ckpt'))
            if not stems:
                heavy_capacity = studio.project_processing_plan(project_id, model_size=options.get('model_size', 'small'), workload='separation')
                if not heavy_capacity['admitted']:
                    raise RuntimeError('Background separation paused: ' + ' '.join(heavy_capacity['reasons']) +
                                       ' Completed dialogue and project files were retained.')
        progress(5, 82, "Separating original vocals; retaining background at unity gain")
        with track(base, job_id, "background", "checkpoints"):
            emit(0, 1)
            studio.preserve_background_endpoint(project_id, studio.BackgroundPreservationRequest(mode="separation", duck_db=0.0,
                model_filename=options.get("separation_model", "vocals_mel_band_roformer.ckpt"),
                separation_workers=options.get("separation_workers")))
            emit(1, 1)
        with track(base, job_id, "mix", "checkpoints"):
            emit(0, 1)
            build_balanced_mix(studio, project_id, base)
            emit(1, 1)
        progress(5, 92, "Rendering video and checking output")
        with track(base, job_id, "render", "checkpoints"):
            emit(0, 1)
            checked(studio.execute_full_render, False)
            emit(1, 1)
        qa = json.loads((base / "output/render_qa_report.json").read_text(encoding="utf-8"))
        if qa.get("status") != "PASSED":
            raise RuntimeError("Render quality checks did not pass. Review the QA report.")
        studio.get_final_video(project_id)
        for stage in stages:
            stage.update(status="completed", percent=100)
        state.update(status="completed", progress_percent=100, auto_download_ready=True,
                     current_stage_label="Render verified. Listen and review before delivery.",
                     rendered_video_url=f"/api/projects/{project_id}/final-video")
    except SpeakerReviewRequired as exc:
        state.update(status='awaiting_review',error=None,auto_download_ready=False,
                     current_stage_label=str(exc),current_stage='character_voice_matching',failure_kind='review')
        stages[2].update(status='awaiting_review',percent=0)
    except RemoteWaiting as exc:
        state.update(status='waiting',error=None,auto_download_ready=False,current_stage_label=str(exc),failure_kind='provider_wait',eta_seconds=None)
        for stage in stages:
            if stage['status']=='running':stage['status']='waiting'
    except Exception as exc:
        from .kaggle_tasks import waiting_error
        pending=waiting_error(exc)
        if pending:
            state.update(status='waiting',error=None,auto_download_ready=False,current_stage_label=str(pending),failure_kind='provider_wait',eta_seconds=None)
            for stage in stages:
                if stage['status']=='running':stage['status']='waiting'
            return
        cancelled = isinstance(exc, InterruptedError) or studio.job_cancel_requested(studio.DB_PATH, job_id)
        state.update(status="cancelled" if cancelled else "failed", error=str(getattr(exc, "detail", exc)),
                     auto_download_ready=False, rendered_video_url=None,
                     failure_kind="review" if isinstance(exc, DialogueReviewRequired) else "processing")
        state["current_stage_label"] = state["error"]
        for stage in stages:
            if stage["status"] == "running":
                stage["status"] = state["status"]
        raise
    finally:
        if state['status']=='waiting' and studio.job_cancel_requested(studio.DB_PATH,job_id):
            state.update(status='cancelled',auto_download_ready=False,eta_seconds=None,
                         current_stage_label='Auto-dub cancelled. Remote work and checkpoints retained.')
            for stage in stages:
                if stage['status']=='waiting':stage['status']='cancelled'
        work = read_work(base)
        if work.get("job_id") == job_id:
            state["progress_percent"] = max(state.get("progress_percent", 0), work.get("overall_percent", 0))
        state["elapsed_seconds"] = round(time.time() - state["start_time"], 1)
        save_status(base, state)
        with studio.connect(studio.DB_PATH) as conn:
            conn.execute("UPDATE jobs SET status=?,payload=?,message=?,updated_at=? WHERE id=?",
                         ('completed' if state['status']=='awaiting_review' else state["status"], json.dumps(options), state["current_stage_label"], studio.now(), job_id))
            conn.execute("UPDATE projects SET status=?,updated_at=? WHERE id=?",
                         (state["status"], studio.now(), project_id))
