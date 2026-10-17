import numpy as np
import pytest
import soundfile as sf
from backend.chunked_asr import partition
from backend.chunked_separation import assemble_stem


def predictions(tmp_path, duration=2.37, differing=False):
    specs = partition(duration, 1.03, .3)
    results = []
    for i, spec in enumerate(specs):
        start = round(spec["context_start"] * 48000)
        end = round(spec["context_end"] * 48000)
        times = np.arange(start, end) / 48000
        data = np.stack((.2*np.sin(2*np.pi*220*times), .1*np.cos(2*np.pi*330*times)), axis=1).astype(np.float32)
        if differing:
            data[:] = .2 + i*.1
        output = tmp_path / f"context-{i}.wav"
        sf.write(output, data, 48000, subtype="FLOAT")
        results.append({"payload": {"background_candidate": str(output)}})
    return specs, results


def test_stereo_assembly_preserves_timeline_samples_and_exact_frame_count(tmp_path):
    specs, results = predictions(tmp_path)
    output = tmp_path / "assembled.wav"
    assemble_stem(specs, results, "background_candidate", output, 2.37, blend_seconds=.2)
    data, sr = sf.read(output, dtype="float32", always_2d=True)
    assert sr == 48000
    assert data.shape == (round(2.37*48000), 2)
    times = np.arange(len(data))/48000
    expected = np.stack((.2*np.sin(2*np.pi*220*times), .1*np.cos(2*np.pi*330*times)),axis=1).astype(np.float32)
    assert np.max(np.abs(data-expected)) < 1e-7


def test_context_blending_does_not_create_a_gain_spike_or_boundary_click(tmp_path):
    specs, results = predictions(tmp_path, differing=True)
    output = tmp_path / "blended.wav"
    assemble_stem(specs, results, "background_candidate", output, 2.37, blend_seconds=.2)
    data, _ = sf.read(output, dtype="float32", always_2d=True)
    assert data.min() >= .2-1e-6 and data.max() <= .4+1e-6
    assert np.max(np.abs(np.diff(data[:,0]))) < .0001


def test_missing_prediction_does_not_replace_last_verified_stem(tmp_path):
    specs, results = predictions(tmp_path)
    output = tmp_path / "previous.wav"
    output.write_bytes(b"last verified audio")
    results[1]["payload"]["background_candidate"] = str(tmp_path / "missing.wav")
    with pytest.raises((OSError, RuntimeError)):
        assemble_stem(specs, results, "background_candidate", output, 2.37)
    assert output.read_bytes() == b"last verified audio"


def test_resume_keeps_original_chunk_boundaries_when_capacity_changes(tmp_path):
    from backend.chunked_separation import separation_geometry
    import json
    legacy=tmp_path/'old';legacy.mkdir()
    (legacy/'checkpoint.json').write_text(json.dumps({'status':'completed','spec':{'operation':'separation','source_fingerprint':'source-a','model_filename':'model-a','worker_version':2,'start':0,'end':60,'context_start':0,'context_end':63}}))
    geometry=separation_geometry(tmp_path,180,{'chunk_seconds':120,'context_seconds':3},'source-a','model-a')
    assert geometry['chunk_seconds']==60 and geometry['context_seconds']==3
    assert separation_geometry(tmp_path,180,{'chunk_seconds':120,'context_seconds':3},'source-a','model-a')==geometry
    assert separation_geometry(tmp_path,180,{'chunk_seconds':120,'context_seconds':3},'source-b','model-a')['chunk_seconds']==120


def test_parallel_warm_pool_routes_devices_and_never_shares_a_worker(tmp_path,monkeypatch):
    from backend import chunk_worker
    from concurrent.futures import ThreadPoolExecutor
    import threading,time
    class FakeRunner:
        def __init__(self,root,cancelled,**kwargs):
            self.lock=threading.Lock(); self.process=None
        def __call__(self,spec,folder):
            assert self.lock.acquire(blocking=False),'Worker used concurrently'
            try:
                time.sleep(.02)
                return {'id':spec['id'],'device':spec['device'],'cuda_device':spec['cuda_device']}
            finally:self.lock.release()
        def __exit__(self,*args):pass
    monkeypatch.setattr(chunk_worker,'WarmChunkRunner',FakeRunner)
    slots=[{'device':'cuda','cuda_device':'GPU-one'},{'device':'cuda','cuda_device':'GPU-two'}]
    with chunk_worker.WarmChunkPool(tmp_path,slots) as pool,ThreadPoolExecutor(max_workers=2) as executor:
        results=list(executor.map(lambda i:pool({'id':i,'device':'cpu'},tmp_path),range(8)))
    assert [row['id'] for row in results]==list(range(8))
    assert {row['cuda_device'] for row in results}=={'GPU-one','GPU-two'}
    assert all(row['device']=='cuda' for row in results)


def test_resume_does_not_infer_chunk_size_from_short_final_chunk(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    from backend.chunked_separation import separation_geometry
    checkpoints = []
    for name, start, end, context_start, context_end in (
        ('last', 120, 126, 117, 126), ('full', 0, 60, 0, 63)
    ):
        folder = tmp_path / name
        folder.mkdir()
        checkpoint = folder / 'checkpoint.json'
        checkpoint.write_text(json.dumps({'spec': {
            'operation': 'separation', 'source_fingerprint': 'a',
            'model_filename': 'm', 'worker_version': 2, 'start': start,
            'end': end, 'context_start': context_start, 'context_end': context_end
        }}))
        checkpoints.append(checkpoint)
    original_glob = Path.glob
    monkeypatch.setattr(Path, 'glob', lambda self, pattern:
                        iter(checkpoints) if self == tmp_path else original_glob(self, pattern))
    geometry = separation_geometry(tmp_path, 126, {'chunk_seconds': 120}, 'a', 'm')
    assert geometry['chunk_seconds'] == 60
