"""Durability and bounded admission independent of optional model downloads."""
import json
import threading
import time
import pytest
from backend.chunk_execution import execute_chunks
from backend.chunked_asr import partition, merge_transcripts


def test_context_words_are_owned_once_and_timestamps_stay_on_source_timeline():
    chunks = partition(4, 2, 1)
    words = [{"start": .5, "end": 1, "text": " hello"}, {"start": 1.8, "end": 2.1, "text": " world"}, {"start": 2.2, "end": 2.7, "text": " again"}]
    results = []
    for chunk in chunks:
        offset = chunk["context_start"]
        local = [dict(word, start=word["start"]-offset, end=word["end"]-offset) for word in words
                 if word["start"] >= offset and word["end"] <= chunk["context_end"]]
        results.append({"payload": {"language": "en", "segments": [{"start": 0, "end": 3, "words": local, "text": "context"}]}})
    merged = merge_transcripts(chunks, results, 4)
    retained = [word for row in merged["segments"] for word in row["words"]]
    assert retained == words
    assert any(row["boundary_review_required"] for row in merged["segments"])
    assert merged["duration"] == 4


def test_boundary_without_word_timestamps_is_not_silently_cut():
    chunks = partition(4, 2, 1)
    results = [{"payload": {"segments": [{"start": 1, "end": 2.8, "text": "uncertain boundary"}]}}] * 2
    with pytest.raises(RuntimeError, match="word timestamps"):
        merge_transcripts(chunks, results, 4)


def specs():
    return [{"id": str(i), "start": i * 2, "end": (i + 1) * 2, "source_fingerprint": "same movie"} for i in range(3)]


def test_failure_retains_finished_chunk_and_resume_only_runs_unfinished(tmp_path):
    calls = []
    def run(spec, folder):
        calls.append(spec["id"])
        if spec["id"] == "1":
            raise RuntimeError("internet unavailable")
        output = folder / "result.txt"
        output.write_text("verified content")
        return {"outputs": [str(output)], "payload": {"id": spec["id"]}}
    with pytest.raises(RuntimeError, match="internet"):
        execute_chunks(tmp_path, specs(), run, max_workers=1)
    assert calls == ["0", "1"]
    retained = next(tmp_path.glob("*/result.txt"))
    before = retained.stat().st_mtime_ns
    def resume(spec, folder):
        calls.append(spec["id"])
        output = folder / "result.txt"
        output.write_text("verified content")
        return {"outputs": [str(output)], "payload": {"id": spec["id"]}}
    results = execute_chunks(tmp_path, specs(), resume, max_workers=1)
    assert calls == ["0", "1", "1", "2"]
    assert [r["payload"]["id"] for r in results] == ["0", "1", "2"]
    assert retained.stat().st_mtime_ns == before


def test_out_of_order_workers_are_bounded_and_result_order_is_stable(tmp_path):
    lock = threading.Lock()
    live = peak = 0
    def run(spec, folder):
        nonlocal live, peak
        with lock:
            live += 1
            peak = max(peak, live)
        time.sleep(0.02 if spec["id"] == "0" else 0.001)
        output = folder / "out.txt"
        output.write_text(spec["id"])
        with lock:
            live -= 1
        return {"outputs": [str(output)], "payload": spec["id"]}
    results = execute_chunks(tmp_path, specs(), run, max_workers=2)
    assert peak == 2
    assert [r["payload"] for r in results] == ["0", "1", "2"]


def test_corrupt_output_is_regenerated_and_changed_input_uses_new_checkpoint(tmp_path):
    calls = []
    def run(spec, folder):
        calls.append(spec["source_fingerprint"])
        output = folder / "out.txt"
        output.write_text("valid")
        return {"outputs": [str(output)]}
    execute_chunks(tmp_path, specs()[:1], run)
    next(tmp_path.glob("*/out.txt")).write_text("bad")
    execute_chunks(tmp_path, specs()[:1], run)
    changed = dict(specs()[0], source_fingerprint="new movie")
    execute_chunks(tmp_path, [changed], run)
    assert calls == ["same movie", "same movie", "new movie"]
    assert len(list(tmp_path.glob("*/checkpoint.json"))) == 2


def test_cancel_keeps_completed_outputs_and_capacity_blocks_worker(tmp_path):
    cancelled = False
    def run(spec, folder):
        nonlocal cancelled
        output = folder / "out.txt"
        output.write_text("keep")
        cancelled = True
        return {"outputs": [str(output)]}
    with pytest.raises(InterruptedError):
        execute_chunks(tmp_path, specs(), run, cancelled=lambda: cancelled)
    assert len(list(tmp_path.glob("*/out.txt"))) == 1
    with pytest.raises(RuntimeError, match="capacity"):
        execute_chunks(tmp_path / "blocked", specs(), run, admitted=lambda: False)
    assert not list((tmp_path / "blocked").glob("*/out.txt"))


def test_scheduler_changes_reuse_legacy_completed_chunks_without_rewrite(tmp_path):
    from backend.chunk_execution import save_json,digest
    import hashlib
    old={'id':'sep-0','source_fingerprint':'source-a','model_filename':'model-a','start':0,'end':1,'worker_version':2,'threads':8,'device':'cuda'}
    legacy=tmp_path/hashlib.sha256(json.dumps(old,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    legacy.mkdir(); output=legacy/'stem.wav';output.write_bytes(b'valid completed stem')
    checkpoint=legacy/'checkpoint.json'
    save_json(checkpoint,{'status':'completed','spec':old,'outputs':[{'file':output.name,'size':output.stat().st_size,'sha256':digest(output)}],'result':{'outputs':[str(output)]}})
    before=checkpoint.read_bytes()
    changed={**old,'threads':2,'cuda_device':'GPU-new'}
    result=execute_chunks(tmp_path,[changed],lambda *args: pytest.fail('Completed chunk was regenerated'),max_workers=20)
    assert result[0]['outputs']==[str(output)] and checkpoint.read_bytes()==before


def test_twenty_parallel_chunks_keep_output_order(tmp_path):
    barrier=threading.Barrier(20)
    specs=[{'id':str(i)} for i in range(20)]
    def run(spec,folder):
        barrier.wait(timeout=10)
        output=folder/'result.bin';output.write_text(spec['id'])
        return {'outputs':[str(output)],'index':int(spec['id'])}
    results=execute_chunks(tmp_path,specs,run,max_workers=20)
    assert [r['index'] for r in results]==list(range(20))


def test_separation_cleanup_keeps_verified_outputs_and_failed_scratch(tmp_path):
    from backend.chunk_execution import cleanup_separation_temporaries
    folder=tmp_path/'chunk';folder.mkdir()
    (folder/'stems').mkdir()
    context=folder/'context.wav';context.write_bytes(b'scratch')
    raw=folder/'stems'/'vocals.wav';raw.write_bytes(b'raw')
    assert cleanup_separation_temporaries(folder)==0
    def runner(spec,target):
        output=target/'background_candidate.wav';output.write_bytes(b'verified')
        return {'outputs':[str(output)]}
    execute_chunks(tmp_path/'run',[{'operation':'separation','id':'sep'}],runner)
    completed=next((tmp_path/'run').iterdir())
    scratch=completed/'context.wav';scratch.write_bytes(b'scratch')
    checkpoint=(completed/'checkpoint.json').read_bytes()
    assert cleanup_separation_temporaries(completed)==7
    assert not scratch.exists()
    assert (completed/'background_candidate.wav').read_bytes()==b'verified'
    assert (completed/'checkpoint.json').read_bytes()==checkpoint
    assert context.exists() and raw.exists()
