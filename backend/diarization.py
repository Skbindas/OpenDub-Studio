from __future__ import annotations

import json
import os
import math
import hashlib
from pathlib import Path
from typing import Any


MODEL_NAME = "pyannote/speaker-diarization-community-1"


def union_intervals(intervals):
    merged=[]
    for start,end in sorted(intervals):
        if end<=start:continue
        if merged and start<=merged[-1][1]:merged[-1]=(merged[-1][0],max(end,merged[-1][1]))
        else:merged.append((start,end))
    return merged


def overlap_events(turns):
    by_speaker={}
    for turn in turns:
        by_speaker.setdefault(str(turn['speaker_id']),[]).append((float(turn['start']),float(turn['end'])))
    events={}
    for speaker,intervals in by_speaker.items():
        for start,end in union_intervals(intervals):
            events.setdefault(start,[]).append((speaker,1));events.setdefault(end,[]).append((speaker,-1))
    active=set();previous=None;result=[]
    for at,changes in sorted(events.items()):
        if previous is not None and at>previous and len(active)>1:
            ids=sorted(active)
            if result and result[-1]['end']==previous and result[-1]['speaker_ids']==ids:result[-1]['end']=at
            else:result.append({'start':previous,'end':at,'speaker_ids':ids})
        for speaker,delta in changes:
            if delta<0:active.discard(speaker)
            else:active.add(speaker)
        previous=at
    return result


def serialize_diarization(annotation,device):
    regular=getattr(annotation,'speaker_diarization',annotation)
    exclusive=getattr(annotation,'exclusive_speaker_diarization',None)
    def rows(view):
        if view is None:return []
        result=[]
        for segment,_,label in view.itertracks(yield_label=True):
            start,end=float(segment.start),float(segment.end)
            if math.isfinite(start) and math.isfinite(end) and end>max(0,start):
                result.append({'start':round(max(0,start),3),'end':round(end,3),'speaker_id':str(label)})
        return sorted(result,key=lambda x:(x['start'],x['end'],x['speaker_id']))
    turns=rows(regular);alignment=rows(exclusive) if exclusive is not None else turns
    labels=list(regular.labels()) if hasattr(regular,'labels') else sorted({x['speaker_id'] for x in turns})
    embeddings=getattr(annotation,'speaker_embeddings',None);speakers=[]
    for i,label in enumerate(labels):
        vector=[]
        if embeddings is not None and i<len(embeddings):
            candidate=[float(v) for v in embeddings[i]]
            if all(math.isfinite(v) for v in candidate) and any(candidate):vector=candidate
        speakers.append({'speaker_id':str(label),'display_name':str(label).replace('_',' ').title(),
                         'character_id':None,'review_required':True,'embedding':vector,
                         'embedding_kind':'learned' if vector else 'unavailable',
                         'embedding_model':MODEL_NAME+'::speaker_embeddings'})
    return {'schema_version':3,'engine':MODEL_NAME,'device':device,'timebase':'source_media_seconds',
            'speaker_count':len(speakers),'speakers':speakers,'turns':turns,'regular_turns':turns,
            'alignment_turns':alignment,'overlap_events':overlap_events(turns),
            'raw_overlap_available':True,'exclusive_alignment':exclusive is not None,
            'notice':'Automatic speaking identities are provisional. Review uncertain words and voice choices.'}


def run_bounded_diarization(pipeline,waveform,sample_rate,cache_root,input_hash,model_key,
                           chunk_seconds=300,overlap_seconds=30,cancelled=lambda:False,progress=lambda p,v:None):
    from .speaker_identity import reconcile_identities
    from .atomic_files import replace_with_retry
    duration=waveform.shape[-1]/sample_rate
    if not 0<=overlap_seconds<chunk_seconds:raise ValueError('Invalid diarization window overlap')
    key=hashlib.sha256(f'{input_hash}:{model_key}:{chunk_seconds}:{overlap_seconds}:schema3'.encode()).hexdigest()[:24]
    cache_root=Path(cache_root)/key;cache_root.mkdir(parents=True,exist_ok=True)
    # Rebuild the within-run registry from validated cached chunks. Persistent
    # project identity reconciliation happens afterwards, on the complete view.
    identity=cache_root/'working-identities.json';identity.unlink(missing_ok=True)
    starts=[];at=0
    while at<duration:
        starts.append(at)
        if at+chunk_seconds>=duration:break
        at+=chunk_seconds-overlap_seconds
    merged={k:[] for k in ('regular_turns','alignment_turns')};profiles={};coverage=[];decisions=[]
    for index,start in enumerate(starts):
        if cancelled():raise InterruptedError('Speaker analysis cancelled; completed windows retained.')
        end=min(duration,start+chunk_seconds);target=cache_root/f'{index:05d}.json'
        if target.exists():
            chunk=json.loads(target.read_text(encoding='utf-8'))
            if chunk.get('input_sha256')!=input_hash or chunk.get('model_revision')!=model_key:raise RuntimeError('Invalid speaker window cache')
        else:
            def hook(*args,**kwargs):
                if cancelled():raise InterruptedError('Speaker analysis cancelled; completed windows retained.')
                name=str(args[0]) if args else 'inference'
                total=kwargs.get('total',args[3] if len(args)>3 else None)
                completed=kwargs.get('completed',args[4] if len(args)>4 else None)
                portion=max(0,min(1,completed/total)) if total and completed is not None else 0
                # Internal steps have separate totals; report them without
                # treating each individual step as a finished speaker window.
                label=f'Speaker window {index+1}/{len(starts)} · {name}'
                if total:label+=f' {completed or 0}/{total}'
                progress(label,(index+.9*portion)/len(starts))
            annotation=_run_pipeline(pipeline,{'waveform':waveform[:,round(start*sample_rate):round(end*sample_rate)],
                                              'sample_rate':sample_rate},hook=hook)
            chunk=serialize_diarization(annotation,str(getattr(pipeline,'device','cpu')))
            chunk.update(input_sha256=input_hash,model_revision=model_key,window={'start':start,'end':end})
            for sp in chunk['speakers']:sp['embedding_model']=model_key+'::speaker_embeddings'
            temp=target.with_suffix('.tmp');temp.write_text(json.dumps(chunk,ensure_ascii=False),encoding='utf-8');replace_with_retry(temp,target)
        mapped=reconcile_identities(chunk,identity,input_hash)
        left=start+(overlap_seconds/2 if index else 0)
        right=end-(overlap_seconds/2 if index<len(starts)-1 else 0)
        for name in merged:
            for turn in mapped.get(name,mapped.get('turns',[])):
                a=max(left,start+turn['start']);b=min(right,start+turn['end'])
                if b>a:merged[name].append(dict(turn,start=round(a,3),end=round(b,3)))
        for sp in mapped['speakers']:profiles[sp['speaker_id']]=sp
        coverage.append({'start':left,'end':right,'state':'complete'})
        decisions.extend(dict(x,window_index=index) for x in mapped.get('identity_decisions',[]))
        progress(f'Speaker window {index+1}/{len(starts)} verified',(index+1)/len(starts))
    for name,rows in merged.items():
        grouped={}
        for row in rows:grouped.setdefault(row['speaker_id'],[]).append((row['start'],row['end']))
        merged[name]=sorted([{'start':a,'end':b,'speaker_id':sid} for sid,intervals in grouped.items()
                             for a,b in union_intervals(intervals)],key=lambda r:(r['start'],r['end'],r['speaker_id']))
    active={x['speaker_id'] for x in merged['regular_turns']}
    return {'schema_version':3,'engine':MODEL_NAME,'model_revision':model_key,'device':str(getattr(pipeline,'device','cpu')),
            'timebase':'source_media_seconds','raw_overlap_available':True,'exclusive_alignment':True,
            'speakers':[profiles[sid] for sid in sorted(active)],'speaker_count':len(active),
            **merged,'turns':merged['regular_turns'],'overlap_events':overlap_events(merged['regular_turns']),
            'coverage':{'duration':duration,'windows':coverage,'complete':True},'window_identity_decisions':decisions,
            'notice':'Estimated speaking identities; review uncertain turns and casting before voice locking.'}


class DiarizationSetupError(RuntimeError):
    """Recoverable diarization setup/access issue; full analysis may continue."""


def check_model_access(token: str | None = None) -> dict[str, Any]:
    token = token or os.getenv("HF_TOKEN")
    result = {
        "status": "needs_setup",
        "model": MODEL_NAME,
        "model_url": "https://huggingface.co/pyannote/speaker-diarization-community-1",
        "token_configured": bool(token),
        "authorized": False,
        "reason": None,
    }
    if not token:
        result["reason"] = "HF_TOKEN is not configured."
        return result
    try:
        from huggingface_hub import HfApi
        HfApi(token=token).auth_check(MODEL_NAME)
        result.update({"status": "ready", "authorized": True})
    except Exception as exc:
        name, message = type(exc).__name__, str(exc)
        lowered = message.lower()
        if "gated" in lowered or "403" in lowered or "authorized" in lowered or "access" in lowered:
            result["status"] = "authorization_required"
            result["reason"] = "Hugging Face token is configured, but this account is not authorized for the gated Community-1 model. Accept the model conditions and retry."
        elif "401" in lowered or ("invalid" in lowered and "token" in lowered):
            result["status"] = "invalid_token"
            result["reason"] = "HF_TOKEN was rejected by Hugging Face."
        else:
            result["status"] = "unreachable"
            result["reason"] = f"{name}: model access check unavailable; check connectivity and retry."
    return result


def diarization_runtime_status() -> dict[str, Any]:
    """Report whether local pyannote diarization can run without exposing secrets."""
    try:
        import importlib.util
        installed = importlib.util.find_spec("pyannote.audio") is not None
    except Exception:
        installed = False

    token_configured = bool(os.getenv("HF_TOKEN"))
    model_access = check_model_access(os.getenv("HF_TOKEN"))
    torch_available = False
    cuda_available = False
    vram_total_mb = None
    vram_free_mb = None
    try:
        import torch
        torch_available = True
        cuda_available = bool(torch.cuda.is_available())
        if cuda_available:
            free_bytes, total_bytes = torch.cuda.mem_get_info()
            vram_total_mb = round(total_bytes / 1048576)
            vram_free_mb = round(free_bytes / 1048576)
    except Exception:
        pass

    return {
        "status": "ready" if installed and model_access["status"] == "ready" else "needs_setup",
        "engine": "pyannote.audio",
        "model": MODEL_NAME,
        "installed": installed,
        "hf_token_configured": token_configured,
        "torch_available": torch_available,
        "cuda_available": cuda_available,
        "vram_total_mb": vram_total_mb,
        "vram_free_mb": vram_free_mb,
        "device_policy": os.getenv("OPENDUB_DIARIZATION_DEVICE", "auto"),
        "model_access": model_access,
    }


def _is_hf_access_error(exc: BaseException) -> bool:
    status_code = getattr(exc, "response", None)
    status_code = getattr(status_code, "status_code", None)
    text = str(exc).lower()
    return (
        status_code in {401, 403}
        or "403 client error" in text
        or "401 client error" in text
        or "gated repo" in text
        or "gated" in text and "huggingface" in text
        or "not in the authorized list" in text
        or "access to model" in text and "restricted" in text
    )


def _select_device() -> tuple[str, Any | None]:
    """Prefer GPU only when it has enough VRAM for diarization; otherwise use CPU."""
    requested = os.getenv("OPENDUB_DIARIZATION_DEVICE", "auto").strip().lower()
    try:
        import torch
    except ImportError:
        return "cpu", None

    if requested == "cpu":
        return "cpu", torch.device("cpu")

    if requested == "cuda":
        if not torch.cuda.is_available():
            return "cpu", torch.device("cpu")
        return "cuda", torch.device("cuda")

    # RTX 3050-class 4 GB GPUs are intentionally kept on CPU in auto mode.
    if torch.cuda.is_available():
        try:
            _, total_bytes = torch.cuda.mem_get_info()
            if total_bytes >= 6 * 1024**3:
                return "cuda", torch.device("cuda")
        except Exception:
            pass
    return "cpu", torch.device("cpu")


def _load_pcm_wav(audio_path: Path) -> tuple[Any, int]:
    """Load our extracted 16-bit PCM WAV directly into a torch waveform.

    OpenDub extracts diarization audio as mono 16 kHz PCM-S16LE. Passing an
    in-memory waveform to pyannote avoids its torchcodec/FFmpeg file decoder,
    while retaining TorchCodec as an installed optional dependency.
    """
    import wave

    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("PyTorch is required for speaker diarization.") from exc

    with wave.open(str(audio_path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frame_count = wav.getnframes()
        if channels < 1:
            raise RuntimeError("Diarization WAV has no audio channels.")
        if sample_width != 2:
            raise RuntimeError(
                f"Diarization WAV must use 16-bit PCM; found sample width {sample_width} bytes."
            )
        if sample_rate <= 0 or frame_count <= 0:
            raise RuntimeError("Diarization WAV has invalid sample rate or frame count.")
        # A disk-backed float tensor avoids simultaneous raw/bytearray/float copies
        # of a multi-hour soundtrack. Decode and normalize bounded blocks only.
        import numpy as np
        import tempfile
        backing = tempfile.NamedTemporaryFile(prefix="diarization-", suffix=".f32", dir=audio_path.parent, delete=False)
        backing_path = Path(backing.name)
        backing.close()
        mapped = np.memmap(backing_path, dtype="float32", mode="w+", shape=(frame_count, channels))
        try:
            for first in range(0, frame_count, 65536):
                raw = wav.readframes(min(65536, frame_count-first))
                block = np.frombuffer(raw, dtype="<i2").reshape(-1, channels)
                if len(block) != min(65536, frame_count-first):
                    raise RuntimeError("Diarization PCM is truncated")
                mapped[first:first+len(block)] = block.astype("float32") / 32768.0
            mapped.flush()
            waveform = torch.from_numpy(mapped).transpose(0, 1)
            # Keep the mapping alive and release/delete it when the tensor dies.
            import weakref
            def cleanup():
                mapped._mmap.close()
                backing_path.unlink(missing_ok=True)
            weakref.finalize(waveform, cleanup)
            return waveform, int(sample_rate)
        except Exception:
            mapped._mmap.close()
            backing_path.unlink(missing_ok=True)
            raise


def _run_pipeline(pipeline: Any, pipeline_input: Any,hook=None) -> Any:
    try:
        return pipeline(pipeline_input,**({'hook':hook} if hook is not None else {}))
    except RuntimeError as exc:
        message = str(exc).lower()
        if "out of memory" not in message and "cuda" not in message:
            raise
        # Retry safely on CPU for low-VRAM systems.
        try:
            import torch
            pipeline.to(torch.device("cpu"))
            return pipeline(pipeline_input,**({'hook':hook} if hook is not None else {}))
        except Exception:
            raise exc


def diarize(audio_path: Path, output_path: Path, hf_token: str | None = None,*,cancelled=lambda:False,progress=lambda p,v:None) -> dict[str, Any]:
    from .kaggle_tasks import project_for
    if project_for(output_path):
        from .kaggle_operations import diarize as remote_diarize
        return remote_diarize(audio_path,output_path,cancelled,progress)
    """Run local pyannote Community-1 diarization and persist speaker turns."""
    runtime = diarization_runtime_status()
    if not runtime["installed"]:
        raise RuntimeError(
            "Speaker diarization runtime is missing. Install requirements-diarization.txt and restart OpenDub Studio."
        )

    token = hf_token or os.getenv("HF_TOKEN")
    access = check_model_access(token)
    if access["status"] != "ready":
        raise DiarizationSetupError(access["reason"] + " Open: " + access["model_url"])

    try:
        from pyannote.audio import Pipeline
    except ImportError as exc:
        raise RuntimeError(
            "pyannote.audio could not be imported. Reinstall requirements-diarization.txt."
        ) from exc

    device_name, device = _select_device()
    try:
        pipeline = Pipeline.from_pretrained(MODEL_NAME, token=token)
        if device is not None:
            pipeline.to(device)
        waveform, sample_rate = _load_pcm_wav(audio_path)
        from huggingface_hub import try_to_load_from_cache
        config=try_to_load_from_cache(MODEL_NAME,'config.yaml')
        revision=Path(config).parent.name if isinstance(config,str) else 'unresolved_revision'
        from .chunk_execution import digest
        result=run_bounded_diarization(pipeline,waveform,sample_rate,output_path.parent.parent/'chunks'/'diarization',
                                      digest(audio_path),MODEL_NAME+'@'+revision,cancelled=cancelled,progress=progress)
    except DiarizationSetupError:
        raise
    except InterruptedError:
        raise
    except Exception as exc:
        if _is_hf_access_error(exc):
            raise DiarizationSetupError(
                "Hugging Face denied access to the gated Community-1 model. "
                "Accept the model conditions on the Hugging Face account used by HF_TOKEN, "
                "then retry. Open: " + runtime["model_access"].get("model_url", "https://huggingface.co/pyannote/speaker-diarization-community-1")
            ) from exc
        raise RuntimeError(
            "Speaker diarization failed. Verify HF model access, HF_TOKEN, "
            f"audio/model compatibility, and available memory. Details: {exc}"
        ) from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def assign_speakers(transcript: dict[str, Any], diarization: dict[str, Any]) -> dict[str, Any]:
    """Assign speakers conservatively using overlap ratio and ambiguity checks."""
    turns = diarization.get("regular_turns",diarization.get("turns", []))
    segments = []
    minimum_overlap_ratio = 0.25
    ambiguity_margin = 0.10
    for original in transcript.get("segments", []):
        start, end = float(original.get("start", 0)), float(original.get("end", 0))
        duration = max(end - start, 0.001)
        windows={}
        for turn in turns:
            overlap = max(0.0, min(end, float(turn["end"])) - max(start, float(turn["start"])))
            if overlap > 0:
                windows.setdefault(str(turn['speaker_id']),[]).append((max(start,float(turn['start'])),min(end,float(turn['end']))))
        candidates=[(sum(b-a for a,b in union_intervals(parts)),speaker) for speaker,parts in windows.items()]
        candidates.sort(key=lambda item: (-item[0], item[1]))
        best_overlap = candidates[0][0] if candidates else 0.0
        best_speaker = candidates[0][1] if candidates else None
        second_overlap = candidates[1][0] if len(candidates) > 1 else 0.0
        confidence = best_overlap / duration if best_speaker else 0.0
        margin = (best_overlap - second_overlap) / duration if best_speaker else 0.0

        review_reason = None
        if not best_speaker:
            review_reason = "no_temporal_overlap"
        elif confidence < minimum_overlap_ratio:
            review_reason = "low_overlap"
            best_speaker = None
        elif len(candidates) > 1 and margin < ambiguity_margin:
            review_reason = "ambiguous_overlap"
            best_speaker = None

        row = dict(original)
        row["speaker_id"] = best_speaker
        row["speaker_confidence"] = round(confidence, 3)
        row["speaker_margin"] = round(margin, 3)
        row["speaker_review_required"] = best_speaker is None
        row["speaker_review_reason"] = review_reason
        row['speaker_confidence_kind']='temporal_overlap_ratio'
        row['overlapping_speakers']=sorted({sid for event in overlap_events([
            {'start':a,'end':b,'speaker_id':sid} for sid,parts in windows.items() for a,b in parts])
            if event['end']-event['start']>=.03 for sid in event['speaker_ids']})
        if row['overlapping_speakers']:
            row['speaker_review_required']=True
            row['speaker_review_reason']=review_reason or 'overlapping_speech'
            row['speaker_id']=None
        row["speaker_candidates"] = [
            {"speaker_id": speaker, "overlap_sec": round(overlap, 3),
             "overlap_ratio": round(overlap / duration, 3)}
            for overlap, speaker in candidates[:3]
        ]
        segments.append(row)

    return {**transcript, "segments": segments, "speaker_registry": diarization.get("speakers", [])}


def reconcile_longform_diarization(
    chunk_diarizations: list[dict[str, Any]],
    similarity_threshold: float = 0.85,
) -> dict[str, Any]:
    """Phase 24 entrypoint: reconcile chunk-local speaker IDs into global speaker IDs."""
    from backend.speaker_engine import reconcile_chunk_speakers

    return reconcile_chunk_speakers(
        chunk_diarizations=chunk_diarizations,
        similarity_threshold=similarity_threshold,
    )


def classify_turn_overlaps(
    items: list[dict[str, Any]],
    min_overlap_sec: float = 0.01,
) -> dict[str, Any]:
    """Phase 24 entrypoint: classify overlaps into true_overlap, interruption, background_speech, accidental_overlap."""
    from backend.speaker_engine import classify_overlap_and_interruptions

    return classify_overlap_and_interruptions(items=items, min_overlap_sec=min_overlap_sec)
