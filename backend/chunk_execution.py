"""Bounded coordinator with content-validated, independently durable chunks.

The runner may start an isolated model process. Only the coordinator writes
checkpoints; previously completed files are never deleted on retry.
"""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import hashlib
import json
from pathlib import Path
from .atomic_files import replace_with_retry


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    replace_with_retry(temporary, path)


def _validated(folder: Path) -> dict | None:
    try:
        checkpoint = json.loads((folder / "checkpoint.json").read_text(encoding="utf-8"))
        if checkpoint.get("status") != "completed" or not checkpoint.get("outputs"):
            return None
        for record in checkpoint["outputs"]:
            path = (folder / record["file"]).resolve()
            if not path.is_relative_to(folder.resolve()) or not path.is_file():
                return None
            if path.stat().st_size != record["size"] or digest(path) != record["sha256"]:
                return None
        return checkpoint["result"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def cleanup_separation_temporaries(folder: Path) -> int:
    """Remove regenerable scratch only after durable outputs pass validation."""
    result = _validated(folder)
    if result is None:
        return 0
    checkpoint = json.loads((folder / 'checkpoint.json').read_text(encoding='utf-8'))
    if checkpoint.get('spec', {}).get('operation') != 'separation':
        return 0
    root = folder.resolve()
    protected = {(root / row['file']).resolve() for row in checkpoint.get('outputs', [])}
    removed = 0
    for name in ('context.wav','stems/original_mix.wav','stems/vocals.wav','stems/instrumental.wav'):
        candidate = (root / name).resolve()
        if not candidate.is_relative_to(root) or candidate in protected:
            continue
        try:
            size = candidate.stat().st_size
            candidate.unlink()
            removed += size
        except OSError:
            pass
    return removed


def chunk_identity(spec: dict) -> str:
    # Scheduling placement is not audio content. Model/source/window/version
    # still participate, so changed audio or algorithms cannot reuse stale stems.
    semantic = {k:v for k,v in spec.items() if k not in {'threads','device','cuda_device'}}
    return hashlib.sha256(json.dumps(semantic,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def execute_chunks(root: Path, specs: list[dict], runner, *, max_workers=1,
                   cancelled=lambda: False, admitted=lambda: True, on_progress=lambda done, total: None,
                   partial_progress=lambda folder, spec: 0) -> list[dict]:
    if not 1 <= max_workers <= 256:
        raise ValueError("Worker count must be bounded between 1 and 256")
    root.mkdir(parents=True, exist_ok=True)
    results = [None] * len(specs)
    folders = []
    legacy = {}
    for checkpoint in root.glob('*/checkpoint.json'):
        try:
            data = json.loads(checkpoint.read_text(encoding='utf-8'))
            if data.get('status') == 'completed' and isinstance(data.get('spec'),dict):
                legacy.setdefault(chunk_identity(data['spec']),checkpoint.parent)
        except (OSError,ValueError,TypeError):
            continue
    for spec in specs:
        fingerprint = chunk_identity(spec)
        folder = legacy.get(fingerprint, root / fingerprint)
        folder.mkdir(exist_ok=True)
        folders.append(folder)
    pending = []
    for index, folder in enumerate(folders):
        results[index] = _validated(folder)
        if results[index] is not None:
            cleanup_separation_temporaries(folder)
        if results[index] is None:
            pending.append(index)
    on_progress(sum(item is not None for item in results), len(specs))
    error = None
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        active = {}
        while pending or active:
            while pending and len(active) < max_workers and error is None:
                if cancelled():
                    error = InterruptedError("Chunk processing cancelled; completed chunks retained")
                    break
                if not admitted():
                    error = RuntimeError("Worker capacity unavailable; completed chunks retained")
                    break
                index = pending.pop(0)
                save_json(folders[index] / "checkpoint.json", {"status": "running", "spec": specs[index]})
                active[pool.submit(runner, specs[index], folders[index])] = index
            if not active:
                break
            finished, _ = wait(active, timeout=0.5, return_when=FIRST_COMPLETED)
            processed = sum(item is not None for item in results)
            processed += sum(max(0, min(0.99, partial_progress(folders[index], specs[index]))) for index in active.values())
            on_progress(processed, len(specs))
            for future in finished:
                index = active.pop(future)
                folder = folders[index]
                try:
                    result = future.result()
                    outputs = []
                    for value in result.get("outputs") or []:
                        path = Path(value).resolve()
                        if not path.is_relative_to(folder.resolve()) or not path.is_file() or not path.stat().st_size:
                            raise RuntimeError("Worker returned missing, empty or out-of-chunk output")
                        outputs.append({"file": str(path.relative_to(folder.resolve())), "size": path.stat().st_size, "sha256": digest(path)})
                    if not outputs:
                        raise RuntimeError("Worker returned no verifiable output")
                    save_json(folder / "checkpoint.json", {"status": "completed", "spec": specs[index], "outputs": outputs, "result": result})
                    cleanup_separation_temporaries(folder)
                    results[index] = result
                    print(f"[OpenDub chunks] {specs[index].get('id', index)} completed; {sum(item is not None for item in results)}/{len(specs)} retained", flush=True)
                except Exception as exc:
                    save_json(folder / "checkpoint.json", {"status": "failed", "spec": specs[index], "error": str(exc)})
                    error = error or exc
                on_progress(sum(item is not None for item in results), len(specs))
        # In-flight workers finish and checkpoint before the coordinator exits.
    if error:
        raise error
    return results
