"""Resumable timeline windows avoid thousands of FFmpeg input arguments."""
import math
import os
from pathlib import Path
import shutil
import numpy as np
import soundfile as sf
from .atomic_files import replace_with_retry
from .chunk_execution import digest, execute_chunks
from .chunked_asr import partition
from .work_progress import emit

RATE = 48000


def protect_dialogue_peaks(background: np.ndarray, dialogue: np.ndarray) -> tuple:
    """Smooth only rare dialogue peaks; never adjust the preserved background."""
    from scipy.ndimage import minimum_filter1d, uniform_filter1d
    ceiling = 1-1/32768
    # Signed PCM16's endpoints are asymmetric: -32768/32768 and +32767/32768.
    if not np.isfinite(background).all() or not np.isfinite(dialogue).all() or np.max(background, initial=0)>ceiling or np.min(background, initial=0)<-1:
        raise RuntimeError('Background peak needs review; background gain retained.')
    bounds = np.ones_like(dialogue)
    np.divide(ceiling-background, dialogue, out=bounds, where=dialogue > 1e-9)
    np.divide(-1-background, dialogue, out=bounds, where=dialogue < -1e-9)
    limit = np.clip(bounds.min(axis=1),0,1)
    # Every averaging neighbor's minimum includes the current safety bound.
    # Thus the 20 ms envelope remains at or below that bound without hard clipping.
    gain = uniform_filter1d(minimum_filter1d(limit,size=1921),size=961)
    gain = np.minimum(gain, limit)
    active = np.max(np.abs(dialogue),axis=1) > .001
    percent = float(np.mean(gain[active] < .99)*100) if active.any() else 0
    strong = float(np.mean(gain[active] < .25)*100) if active.any() else 0
    protected = dialogue * gain[:,None]
    energy = float(np.sum(dialogue.astype('float64')**2))
    protected_energy = float(np.sum(protected.astype('float64')**2))
    delta = 10*math.log10(max(1e-30,protected_energy)/energy) if energy else 0
    if percent > 5 or strong > 1 or delta < -.5:
        raise RuntimeError('Mix would clip without sustained masking; reduce dialogue level. Background gain retained.')
    return background+protected, {'background_gain_db':0, 'attenuated_speech_percent':percent,
                                  'dialogue_rms_change_db':delta, 'speech_active_frames':int(active.sum())}


def render_mix_window(spec: dict, output: Path) -> dict:
    first, last = round(spec["start"]*RATE), round(spec["end"]*RATE)
    requested_first, requested_count = first, last-first
    if spec.get('protect_dialogue_peaks'):
        first = max(0,first-1921)
        last = min(sf.info(spec['background']).frames,last+1921)
    count = last-first
    with sf.SoundFile(spec["background"]) as source:
        if source.samplerate != RATE or source.channels != 2:
            raise RuntimeError("Background must be stereo 48 kHz before mixing")
        source.seek(first)
        data = source.read(count, dtype="float32", always_2d=True)
        if len(data) != count:
            raise RuntimeError("Background does not cover the complete source timeline")
    dialogue = np.zeros_like(data) if spec.get('protect_dialogue_peaks') else None
    for clip in spec["clips"]:
        start = clip["start_frame"]
        a, b = max(first,start), min(last,start+clip["frames"])
        if b <= a:
            continue
        with sf.SoundFile(clip["file"]) as voice:
            if voice.samplerate != RATE or voice.channels != 2:
                raise RuntimeError("Fitted dialogue must be stereo 48 kHz before mixing")
            voice.seek(a-start)
            samples = voice.read(b-a,dtype="float32",always_2d=True)
            if len(samples) != b-a:
                raise RuntimeError("Dialogue checkpoint was truncated")
        (dialogue if dialogue is not None else data)[a-first:b-first] += samples
    protection = None
    if dialogue is not None:
        data, protection = protect_dialogue_peaks(data, dialogue)
        data = data[requested_first-first:requested_first-first+requested_count]
        count = requested_count
    peak = float(np.max(np.abs(data))) if count else 0
    if not np.isfinite(data).all() or peak > 1:
        raise RuntimeError("Mix would clip or contains invalid samples; reduce dialogue level. Background gain retained.")
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary=output.with_suffix(".pending.wav")
    sf.write(temporary,data,RATE,subtype="FLOAT")
    replace_with_retry(temporary,output)
    return {"outputs":[str(output)],"payload":{"mix":str(output),"sample_peak":peak,"frames":count,
                                               'dialogue_peak_protection':protection}}


def stitch_mix(results: list[dict], output: Path, frames: int) -> float:
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary=output.with_suffix(".pending.wav")
    peak=0.0
    with sf.SoundFile(temporary,"w",samplerate=RATE,channels=2,format="RF64",subtype="PCM_16") as target:
        for result in results:
            with sf.SoundFile(result["payload"]["mix"]) as source:
                if source.channels != 2 or source.samplerate != RATE:
                    raise RuntimeError("Mix window format does not match source timeline")
                for data in source.blocks(blocksize=65536,dtype="float32",always_2d=True):
                    value=float(np.max(np.abs(data)))
                    if value > 1 or not np.isfinite(data).all():
                        raise RuntimeError("Cached mix window would clip; previous mix retained")
                    peak=max(peak,value)
                    target.write(data)
        if target.tell() != frames:
            raise RuntimeError("Mix windows do not cover the complete source timeline")
    replace_with_retry(temporary,output)
    return 20*math.log10(peak) if peak else float("-inf")


def mix_chunked(project: Path, background: Path, output: Path, clips: list[tuple[float,Path]],
                duration: float, *, seconds=60, workers=1, visible_helpers=False, cancelled=lambda:False,
                protect_dialogue_peaks=False) -> float:
    from .chunk_worker import run_isolated
    total_frames=round(duration*RATE)
    bg_info=sf.info(background)
    if bg_info.frames < total_frames or bg_info.samplerate != RATE or bg_info.channels != 2:
        raise RuntimeError("Background must cover the original stereo 48 kHz timeline")
    records=[]
    for start,path in clips:
        info=sf.info(path)
        first=round(start*RATE)
        if first+info.frames > total_frames:
            raise RuntimeError("Dialogue exceeds the source timeline; review its timing instead of cutting speech")
        records.append({"file":str(path.resolve()),"start_frame":first,"frames":info.frames,"sha256":digest(path)})
    fingerprint=digest(background)
    specs=[]
    for row in partition(duration,seconds,0):
        first,last=round(row["start"]*RATE),round(row["end"]*RATE)
        margin=1921 if protect_dialogue_peaks else 0
        relevant=[record for record in records if record["start_frame"] < last+margin and record["start_frame"]+record["frames"] > first-margin]
        specs.append(dict(row,id=row["id"].replace("asr-","mix-"),operation="mix",background=str(background.resolve()),
                          background_sha256=fingerprint,clips=relevant,threads=1,worker_version=2,
                          protect_dialogue_peaks=protect_dialogue_peaks))
    root=project / "chunks/mix"
    root.mkdir(parents=True,exist_ok=True)
    def admitted():
        from .system_diagnostics import _memory
        available=_memory().get("available_bytes")
        return available is not None and available >= 1.5*1024**3 and shutil.disk_usage(root).free >= 5*1024**3
    results=execute_chunks(root,specs,lambda spec,folder:run_isolated(spec,folder,visible_helpers=visible_helpers,cancelled=cancelled),
                           max_workers=max(1,min(4,workers,max(1,(os.cpu_count() or 1)-2))),cancelled=cancelled,admitted=admitted,
                           on_progress=lambda done,total:emit(done,total))
    peak=stitch_mix(results,output,total_frames)
    if protect_dialogue_peaks:
        from .chunk_execution import save_json
        save_json(project/'output/dialogue_peak_protection.json',
                  {'background_gain_db':0,'windows':[r['payload'].get('dialogue_peak_protection') for r in results]})
    return peak
