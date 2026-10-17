"""One isolated model task; reports atomically, then exits its helper process."""
import json
import os
from pathlib import Path
import subprocess
import sys
from .chunk_execution import save_json


def run_isolated(spec: dict, folder: Path, *, visible_helpers=False, cancelled=lambda: False) -> dict:
    from .kaggle_tasks import project_for
    if project_for(folder):
        from .kaggle_operations import chunk
        return chunk(spec,folder,cancelled)
    request = folder / "request.json"
    save_json(request, spec)
    env = dict(os.environ)
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "OPENDUB_ASR_THREADS"):
        env[key] = str(spec["threads"])
    env["PYTHONIOENCODING"] = "utf-8"
    if spec.get("device") == "cpu":
        env["CUDA_VISIBLE_DEVICES"] = "-1"
    elif spec.get("cuda_device") is not None:
        env["CUDA_VISIBLE_DEVICES"] = str(spec['cuda_device'])
    flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" and visible_helpers else 0
    python = sys.executable
    if spec.get("operation") == "separation" and spec.get("device") == "cuda":
        configured = os.getenv("OPENDUB_SEPARATION_PYTHON")
        candidate = Path(configured) if configured else Path(__file__).resolve().parents[1] / "runtime/separation-env" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not candidate.is_file():
            raise RuntimeError("CUDA separation runtime missing; configure OPENDUB_SEPARATION_PYTHON. Completed chunks retained.")
        python = str(candidate)
    process = subprocess.Popen([python, "-u", "-m", "backend.chunk_worker", str(request)],
                               cwd=Path(__file__).resolve().parents[1], env=env, creationflags=flags)
    try:
        while True:
            try:
                code = process.wait(timeout=.5)
                break
            except subprocess.TimeoutExpired:
                if cancelled():
                    process.terminate()
                    process.wait(timeout=10)
                    raise InterruptedError("Helper cancelled; completed chunks retained")
        if code:
            raise RuntimeError(f"Helper {spec['id']} exited {code}; inspect {folder / 'worker.log'}")
        return json.loads((folder / "result.json").read_text(encoding="utf-8"))
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


class WarmChunkRunner:
    """A sequential separation process; model imports/weights survive between chunks."""
    def __init__(self, root: Path, cancelled=lambda: False, *, visible_helpers=False):
        self.root, self.cancelled = root, cancelled
        self.process, self.log = None, None
        self.visible_helpers = visible_helpers

    def __enter__(self):
        return self

    def __call__(self, spec, folder):
        import time
        request = folder / "request.json"
        save_json(request, spec)
        done = folder / "worker-done.json"
        done.unlink(missing_ok=True)
        if self.process is None:
            env = {**os.environ,"PYTHONIOENCODING":"utf-8","OPENDUB_WARM_SEPARATOR":"1"}
            for key in ("OMP_NUM_THREADS","MKL_NUM_THREADS","OPENBLAS_NUM_THREADS"):
                env[key] = str(spec["threads"])
            if spec["device"] == "cpu":
                env["CUDA_VISIBLE_DEVICES"] = "-1"
            elif spec.get("cuda_device") is not None:
                env["CUDA_VISIBLE_DEVICES"] = str(spec['cuda_device'])
            python = sys.executable
            if spec["device"] == "cuda":
                python = os.getenv("OPENDUB_SEPARATION_PYTHON") or str(Path(__file__).resolve().parents[1] / "runtime/separation-env" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
                if not Path(python).is_file():
                    raise RuntimeError("GPU separation runtime unavailable; completed chunks retained")
            self.log = (self.root / "batch-worker.log").open("a",encoding="utf-8")
            self.process = subprocess.Popen([python,"-u","-m","backend.chunk_worker","--serve"],
                cwd=Path(__file__).resolve().parents[1],env=env,stdin=subprocess.PIPE,
                stdout=None if self.visible_helpers else self.log,
                stderr=None if self.visible_helpers else subprocess.STDOUT,text=True,encoding="utf-8",
                creationflags=subprocess.CREATE_NEW_CONSOLE if os.name=='nt' and self.visible_helpers else 0)
        self.process.stdin.write(str(request.resolve())+"\n"); self.process.stdin.flush()
        deadline=time.monotonic()+2700
        while not done.is_file():
            if self.cancelled():
                raise InterruptedError("Separation cancelled; completed chunks retained")
            if self.process.poll() is not None:
                raise RuntimeError("Separation worker exited; inspect batch-worker.log. Completed chunks retained")
            if time.monotonic()>deadline:
                raise RuntimeError("Separation chunk timed out; completed chunks retained")
            time.sleep(.2)
        status=json.loads(done.read_text(encoding="utf-8"))
        if not status.get("ok"):
            raise RuntimeError(status.get("error") or "Separation chunk failed")
        return json.loads((folder / "result.json").read_text(encoding="utf-8"))

    def __exit__(self, *args):
        if self.process is not None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.terminate(); self.process.wait(timeout=10)
        if self.log:
            self.log.close()


class WarmChunkPool:
    """Each admitted slot owns one warm process, assigned to a physical CUDA card."""
    def __init__(self, root, slots, cancelled=lambda: False, *, visible_helpers=False):
        import queue
        self.slots = slots
        self.available = queue.Queue()
        self.runners = []
        for index, slot in enumerate(slots):
            worker_root = root if index == 0 else root / f'worker-{index:03d}'
            worker_root.mkdir(parents=True,exist_ok=True)
            self.runners.append(WarmChunkRunner(worker_root,cancelled,visible_helpers=visible_helpers))
            self.available.put(index)

    @property
    def resident_count(self):
        return sum(r.process is not None and r.process.poll() is None for r in self.runners)

    def __enter__(self):
        return self

    def __call__(self, spec, folder):
        index = self.available.get()
        try:
            return self.runners[index]({**spec, **self.slots[index]},folder)
        finally:
            self.available.put(index)

    def __exit__(self, *args):
        for runner in self.runners:
            runner.__exit__(*args)


class Tee:
    def __init__(self, stream, log):
        self.stream, self.log = stream, log

    def write(self, text):
        if not self.log.closed:
            self.log.write(text)
            self.log.flush()
        if self.stream:
            self.stream.write(text)
            self.stream.flush()
        return len(text)

    def flush(self):
        if not self.log.closed:
            self.log.flush()
        if self.stream:
            self.stream.flush()

    def close(self):
        # Libraries may retain this per-request proxy until process shutdown.
        self.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


def main(request_path: Path) -> None:
    spec = json.loads(request_path.read_text(encoding="utf-8"))
    folder = request_path.parent
    with (folder / "worker.log").open("a", encoding="utf-8") as log:
        original_out, original_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = Tee(original_out, log), Tee(original_err, log)
        try:
            print(f"[OpenDub helper {spec['id']}] Starting {spec['operation']}; PID {os.getpid()}", flush=True)
            if spec["operation"] == "mix":
                from .chunked_mix import render_mix_window
                result=render_mix_window(spec,folder / "mix.wav")
                save_json(folder / "result.json",result)
                print(f"[OpenDub helper {spec['id']}] Mix window complete; helper exiting.",flush=True)
                return
            clip = folder / "context.wav"
            separation = spec["operation"] == "separation"
            result = subprocess.run([spec["ffmpeg"], "-v", "error", "-y", "-ss", str(spec["context_start"]),
                                     "-i", spec["source"], "-t", str(spec["context_end"] - spec["context_start"]),
                                     "-ac", "2" if separation else "1", "-ar", "48000" if separation else "16000", "-c:a", "pcm_s16le", str(clip)], capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError((result.stderr or "Chunk extraction failed")[-1500:])
            if separation:
                from .background_preservation import _separate_single
                stems = _separate_single(clip, folder / "stems", spec["model_filename"])
                if stems.get("status") != "completed" or not stems.get("background_candidate"):
                    raise RuntimeError(stems.get("error") or "No separated background produced")
                count = spec.get('target_frames',round(spec["context_end"]*48000)-round(spec["context_start"]*48000))
                payload, outputs = {}, []
                for key in ("dialogue_candidate", "background_candidate"):
                    output = folder / f"{key}.wav"
                    subprocess.run([spec["ffmpeg"], "-v", "error", "-y", "-i", stems[key], "-ar", "48000", "-ac", "2",
                                    "-af", f"aresample=48000,apad=whole_len={count},atrim=end_sample={count}",
                                    "-c:a", "pcm_f32le", str(output)], check=True)
                    payload[key] = str(output)
                    outputs.append(str(output))
                save_json(folder / "result.json", {"outputs": outputs, "payload": payload})
                print(f"[OpenDub helper {spec['id']}] Both stems complete; helper exiting.", flush=True)
                return
            if spec["operation"] != "transcription":
                raise ValueError("Unsupported helper operation")
            from .media import transcribe
            from .work_progress import track
            with track(folder, str(os.getpid()), "transcription", "seconds"):
                transcript = transcribe(clip, spec["model_size"], spec.get("language"), spec["device"])
            output = folder / "transcript.json"
            save_json(output, transcript)
            save_json(folder / "result.json", {"outputs": [str(output)], "payload": transcript})
            print(f"[OpenDub helper {spec['id']}] Complete; result saved. Helper exiting.", flush=True)
        finally:
            sys.stdout, sys.stderr = original_out, original_err


if __name__ == "__main__":
    if "--serve" in sys.argv:
        for line in sys.stdin:
            request = Path(line.strip())
            try:
                main(request)
                save_json(request.parent / "worker-done.json", {"ok": True})
            except Exception as exc:
                save_json(request.parent / "worker-done.json", {"ok": False, "error": str(exc)})
    else:
        main(Path(sys.argv[1]))
