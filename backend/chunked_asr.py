"""Opt-in ASR helpers; global diarization remains responsible for speaker IDs.

Production feature-length mode is deliberately gated until boundary, speaker
identity, separation and final-mix trials have passed.
"""
from pathlib import Path
import shutil
from .chunk_execution import digest, execute_chunks
from .work_progress import emit, read_work


def partition(duration: float, seconds: float, context: float = 3) -> list[dict]:
    if duration <= 0 or seconds <= 0 or context < 0:
        raise ValueError("Positive duration/chunk size and nonnegative context required")
    rows, start = [], 0.0
    while start < duration:
        end = min(duration, start + seconds)
        rows.append({"id": f"asr-{len(rows):06d}", "start": start, "end": end,
                     "context_start": max(0, start-context), "context_end": min(duration, end+context),
                     "is_last": end == duration})
        start = end
    return rows


def merge_transcripts(specs: list[dict], results: list[dict], duration: float) -> dict:
    rows = []
    languages = []
    for spec, result in zip(specs, results):
        payload = result["payload"]
        languages.append(payload.get("language"))
        offset = spec["context_start"]
        for original in payload.get("segments") or []:
            words = []
            for original_word in original.get("words") or []:
                word = dict(original_word, start=original_word["start"]+offset, end=original_word["end"]+offset)
                middle = (word["start"]+word["end"])/2
                if spec["start"] <= middle < spec["end"] or spec["is_last"] and middle == spec["end"]:
                    words.append(word)
            if words:
                row = dict(original, words=words, start=words[0]["start"], end=words[-1]["end"],
                           text="".join(word["text"] for word in words).strip(), chunk_id=spec["id"])
                row["boundary_review_required"] = any(abs(word["start"]-edge) < 1 or abs(word["end"]-edge) < 1
                                                      for word in words for edge in (spec["start"], spec["end"]) if edge not in (0, duration))
                rows.append(row)
            elif not original.get("words"):
                start, end = original["start"]+offset, original["end"]+offset
                if start >= spec["start"] and end <= spec["end"]:
                    rows.append(dict(original, start=start, end=end, chunk_id=spec["id"], boundary_review_required=True))
                elif start < spec["end"] and end > spec["start"]:
                    raise RuntimeError("ASR boundary has no word timestamps; review/retranscribe this chunk before merging")
    rows.sort(key=lambda row: (row["start"], row["end"]))
    detected = [language for language in languages if language]
    language = max(set(detected), key=detected.count) if detected else "unknown"
    return {"language": language, "duration": duration, "segments": rows, "chunk_count": len(specs),
            "engine": "faster-whisper-isolated-chunks", "experimental": True,
            "notice": "Boundary dialogue requires review. Speaker identities are assigned globally after merging."}


def transcribe_chunked(source: Path, output_dir: Path, duration: float, plan: dict, *,
                       model_size="small", language=None, visible_helpers=False, cancelled=lambda: False) -> dict:
    if not plan.get("admitted"):
        raise RuntimeError("Processing capacity unavailable; existing chunks retained")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required for chunk extraction")
    source = source.resolve()
    fingerprint = digest(source)
    specs = [dict(row, source=str(source), source_fingerprint=fingerprint, operation="transcription",
                  model_size=model_size, language=language, device=plan["asr_device"], ffmpeg=ffmpeg,
                  worker_version=1, threads=plan["cpu_threads_per_worker"])
             for row in partition(duration, plan["chunk_seconds"], plan.get("context_seconds", 3))]

    def run(spec, folder):
        from .chunk_worker import run_isolated
        return run_isolated(spec, folder, visible_helpers=visible_helpers, cancelled=cancelled)

    def admitted():
        from .kaggle_tasks import project_for
        if project_for(output_dir):return shutil.disk_usage(output_dir).free>=256*1024**2
        from .system_diagnostics import _memory
        available = _memory().get("available_bytes")
        # Check additional admission without charging already-running models twice.
        ram_needed = plan["required_available_ram_bytes"]
        return available is not None and available >= ram_needed and shutil.disk_usage(output_dir).free >= 5 * 1024**3

    output_dir.mkdir(parents=True, exist_ok=True)
    def partial(folder, spec):
        work = read_work(folder)
        request = folder / "request.json"
        if not request.exists() or work.get("updated_at", 0) < request.stat().st_mtime or not work.get("total"):
            return 0
        return work.get("completed", 0) / work["total"]
    results = execute_chunks(output_dir, specs, run, max_workers=plan["heavy_workers"], cancelled=cancelled,
                             admitted=admitted, on_progress=lambda done, total: emit(done, total), partial_progress=partial)
    return merge_transcripts(specs, results, duration)
