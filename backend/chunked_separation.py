"""Bounded UVR helpers and streaming, unity-weight contextual stem assembly."""
from collections import OrderedDict
from pathlib import Path
import shutil
import numpy as np
import soundfile as sf
from .atomic_files import replace_with_retry
from .chunk_execution import digest, execute_chunks
from .chunked_asr import partition
from .work_progress import emit

RATE = 48000


def assemble_stem(specs: list[dict], results: list[dict], key: str, output: Path,
                  duration: float, blend_seconds: float = .25) -> None:
    """Keep source frame ownership exact; blend estimates with weights summing to 1.

    Memory is one stereo block and at most one neighboring prediction block.
    No loudness normalization, gain adjustment or source-timeline truncation.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".pending.wav")
    streams = OrderedDict()
    try:
        for spec, result in zip(specs, results):
            info = sf.info(result["payload"][key])
            expected = round(spec["context_end"]*RATE)-round(spec["context_start"]*RATE)
            if info.samplerate != RATE or info.channels != 2 or info.frames != expected:
                raise RuntimeError("Stem prediction format/frame count does not match its source context")
        total_frames = round(duration*RATE)
        blend_frames = max(0, round(blend_seconds*RATE))
        def read(index, start, count):
            if index not in streams:
                if len(streams) >= 3:
                    _, previous = streams.popitem(last=False)
                    previous.close()
                streams[index] = sf.SoundFile(results[index]["payload"][key])
            streams.move_to_end(index)
            stream = streams[index]
            local = start-round(specs[index]["context_start"]*RATE)
            if local < 0 or local+count > stream.frames:
                raise RuntimeError("Context is too short for the requested boundary blend")
            stream.seek(local)
            data = stream.read(count, dtype="float32", always_2d=True)
            if len(data) != count or not np.isfinite(data).all():
                raise RuntimeError("Incomplete or non-finite stem prediction")
            return data
        with sf.SoundFile(temporary, "w", samplerate=RATE, channels=2, format="RF64", subtype="FLOAT") as target:
            for index, spec in enumerate(specs):
                first, last = round(spec["start"]*RATE), round(spec["end"]*RATE)
                for pos in range(first, last, 65536):
                    count = min(65536, last-pos)
                    data = read(index, pos, count)
                    times = np.arange(pos, pos+count)
                    if blend_frames:
                        for other, boundary, before in ((index-1, first, False), (index+1, last, True)):
                            if not 0 <= other < len(specs):
                                continue
                            mask = times >= boundary-blend_frames if before else times < boundary+blend_frames
                            if not mask.any():
                                continue
                            offset = int(np.flatnonzero(mask)[0])
                            n = int(mask.sum())
                            neighbor = read(other, pos+offset, n)
                            fraction = (times[mask]-(boundary-blend_frames))/(2*blend_frames)
                            weight = fraction if before else 1-fraction
                            data[mask] = data[mask]*(1-weight[:,None]) + neighbor*weight[:,None]
                    target.write(data)
            if target.tell() != total_frames:
                raise RuntimeError("Assembled stem does not cover the complete source timeline")
        replace_with_retry(temporary, output)
    finally:
        for stream in streams.values():
            stream.close()


def separation_geometry(chunks, duration, plan, source_fingerprint, model_filename):
    import json
    from .chunk_execution import save_json
    identity = {'source_fingerprint':source_fingerprint,'model_filename':model_filename,'duration_sec':duration,'worker_version':2}
    path = chunks / 'partition.json'
    if path.is_file():
        try:
            saved = json.loads(path.read_text(encoding='utf-8'))
            if all(saved.get(k)==v for k,v in identity.items()):
                return saved
        except (OSError,ValueError):
            pass
    seconds, context = plan['chunk_seconds'], max(.5,plan.get('context_seconds',3))
    recovered_span = 0
    for checkpoint in chunks.glob('*/checkpoint.json'):
        try:
            row = json.loads(checkpoint.read_text(encoding='utf-8')).get('spec') or {}
            if row.get('operation')=='separation' and row.get('source_fingerprint')==source_fingerprint and row.get('model_filename')==model_filename and row.get('worker_version')==2:
                span = float(row['end'])-float(row['start'])
                margin = max(float(row['start'])-float(row['context_start']),float(row['context_end'])-float(row['end']))
                # The final chunk may be shorter; recover the full partition span.
                if span>recovered_span and margin>0:
                    seconds,context=span,margin
                    recovered_span=span
        except (OSError,ValueError,KeyError,TypeError):
            continue
    saved = {**identity,'chunk_seconds':seconds,'context_seconds':context}
    save_json(path,saved)
    return saved


def separate_chunked(source: Path, output_dir: Path, duration: float, plan: dict, *,
                     model_filename="UVR-MDX-NET-Inst_HQ_3.onnx", visible_helpers=False,
                     cancelled=lambda: False) -> dict:
    from .chunk_worker import run_isolated
    if not plan.get("admitted"):
        raise RuntimeError("Processing capacity unavailable; completed separation chunks retained")
    source = source.resolve()
    fingerprint = digest(source)
    chunks = output_dir / "chunks"
    chunks.mkdir(parents=True, exist_ok=True)
    geometry = separation_geometry(chunks,duration,plan,fingerprint,model_filename)
    specs = [dict(row, id=row["id"].replace("asr-", "sep-"), source=str(source), source_fingerprint=fingerprint,
                  operation="separation", model_filename=model_filename, device=plan["separation_device"],
                  ffmpeg=shutil.which("ffmpeg") or "ffmpeg", worker_version=2, threads=plan["cpu_threads_per_worker"])
             for row in partition(duration, geometry["chunk_seconds"], geometry["context_seconds"])]
    chunks = output_dir / "chunks"
    chunks.mkdir(parents=True, exist_ok=True)
    def admitted():
        from .system_diagnostics import _memory
        available = _memory().get("available_bytes")
        resident = warm.resident_count
        # Resident weights are already reflected in available RAM. Admit room
        # for another model only while there are unloaded worker slots.
        required = plan["reserved_ram_bytes"] + 256*1024**2 if resident >= worker_count else plan["required_available_ram_bytes"]
        return available is not None and available >= required and shutil.disk_usage(chunks).free >= 5*1024**3
    from .chunk_worker import WarmChunkPool
    slots = plan.get('separation_slots') or [{'device':plan['separation_device']}]
    worker_count = min(max(1,int(plan.get('heavy_workers') or 1)),len(slots),len(specs))
    print(f'[OpenDub separation] {worker_count} capacity-admitted warm workers; {len(specs)} resumable chunks',flush=True)
    from .kaggle_tasks import project_for
    if project_for(output_dir):
        results=execute_chunks(chunks,specs,lambda spec,folder:run_isolated(spec,folder,cancelled=cancelled),max_workers=1,
            cancelled=cancelled,admitted=lambda:shutil.disk_usage(chunks).free>=256*1024**2,
            on_progress=lambda done,total:emit(done,total))
    else:
        with WarmChunkPool(chunks,slots[:worker_count],cancelled,visible_helpers=visible_helpers) as warm:
            results = execute_chunks(chunks,specs,warm,max_workers=worker_count,
                                     cancelled=cancelled,admitted=admitted,
                                     on_progress=lambda done,total: emit(done,total))
    vocals, background = output_dir / "vocals.wav", output_dir / "instrumental.wav"
    assemble_stem(specs, results, "dialogue_candidate", vocals, duration)
    assemble_stem(specs, results, "background_candidate", background, duration)
    return {"status":"completed", "method":"UVR/contextual-chunks", "model":model_filename,
            "dialogue_candidate":str(vocals), "background_candidate":str(background),
            "vocals_stem":str(vocals), "instrumental_stem":str(background), "original_mix":str(source),
            "chunk_count":len(specs), "boundary_blend_seconds":.25, "timeline_frames":round(duration*RATE),
            "notice":"Both neural estimates assembled on the original timeline at unity blend weights. Listen for residual speech/separation artifacts."}
