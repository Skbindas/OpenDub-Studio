"""Conservative admission limits, independent of machine-specific detection."""
import math

GIB = 1024**3


def synthesis_worker_limit(available_bytes: int | None, cores: int, *, cloned=False) -> int:
    # Clone generation shares the dedicated GPU and retains its identity cache.
    # A loaded model is not six independent safe workers on a 4 GiB card.
    if cloned or available_bytes is None:
        return 1
    slots = int(max(0, available_bytes - 512 * 1024**2) // (512 * 1024**2))
    return max(1, min(4, max(1, cores - 2), slots))


def plan_resources(report: dict, duration_sec: float = 0, source_bytes: int = 0, model_size: str = "small", *, workload: str = "analysis", bounded_analysis: bool = False, requested_workers: int | None = None) -> dict:
    system, memory, disk = (report.get(key) or {} for key in ("system", "memory", "disk"))
    cores = max(1, int(system.get("logical_cpu_count") or 1))
    available = memory.get("available_bytes")
    free_disk = disk.get("free_bytes")
    reserve_ram = 2 * GIB
    model_ram = {"tiny": 3, "base": 3, "small": 3, "medium": 5, "large-v3": 8}.get(model_size, 8) * GIB
    # Global speaker clustering currently decodes the complete 16 kHz signal.
    # Account for PCM bytes, conversion copies and float tensors before admission.
    diarization_ram = math.ceil(max(0, duration_sec) * 16000 * 12)
    required_ram = reserve_ram + max(model_ram, 3 * GIB + diarization_ram)
    if workload == 'analysis' and bounded_analysis:
        reserve_ram = GIB // 2
        model_ram = {"tiny":2,"base":2,"small":2,"medium":3,"large-v3":5}.get(model_size,5) * GIB
        # PCM is mapped to disk; retain room for global speaker feature tensors.
        required_ram = reserve_ram + model_ram + math.ceil(max(0,duration_sec)*32000)
    if workload == 'speech':
        # Piper runs one line in a subprocess; completed ASR/diarization is reused.
        reserve_ram = GIB
        model_ram = 512 * 1024**2
        required_ram = reserve_ram + model_ram
    elif workload == 'fit':
        # Sequential clip fitting/FFmpeg normalization does not load ASR or TTS.
        # Budget a bounded clip buffer plus OS headroom, not the movie's PCM.
        reserve_ram = GIB
        model_ram = GIB // 2
        required_ram = reserve_ram + model_ram
    elif workload == 'separation':
        # Separation in chunks uses bounded spectral/model slices without ASR/diarization tensors.
        reserve_ram = GIB
        model_ram = GIB
        required_ram = reserve_ram + model_ram
    elif workload != 'analysis':
        raise ValueError('Unknown processing workload')
    usable = max(0, (available or 0) - reserve_ram)
    cpu_budget = max(1, cores - min(2, cores - 1))
    # Keep at least 5 GiB free; include PCM stems, ASR and float mix verification.
    working_bytes = math.ceil(max(0, duration_sec) * 1_200_000 + max(0, source_bytes))
    disk_required = working_bytes + 5 * GIB
    if workload in {'speech', 'fit'}:
        # Analysis/source audio already exists at these resume stages. Budget
        # two full stereo float timelines for clips/fit scratch, plus headroom.
        working_bytes = max(256 * 1024**2, math.ceil(max(0,duration_sec)*768000))
        disk_required = working_bytes + 2 * GIB
    reasons = []
    if available is None or available < required_ram:
        reasons.append(f"About {required_ram/GIB:.1f} GiB of available RAM is required for this model/duration; close other heavy applications or use a shorter preview.")
    if free_disk is None or free_disk < disk_required:
        reasons.append("Insufficient verified workspace disk space for this duration and retained intermediates.")
    accel = report.get("acceleration") or {}
    devices = (report.get("gpu") or {}).get("devices") or []
    # Current model engines select CUDA device 0. Do not aggregate memory from
    # other cards until explicit per-device routing is implemented.
    gpu_slots = max(0, int((float((devices[0] if devices else {}).get("vram_free_mb") or 0) - 512) // 3072))
    cpu_workers = max(1, min(2, int(usable // model_ram), cpu_budget))
    if workload in {'speech', 'fit', 'separation'}:
        cpu_workers = 1
    use_gpu = bool(accel.get("separation_cuda") and gpu_slots)
    workers = min(cpu_workers, max(1, gpu_slots)) if use_gpu else cpu_workers
    separation_slots = []
    if workload == 'separation' and not reasons:
        if requested_workers is not None and (isinstance(requested_workers, bool) or not 1 <= requested_workers <= 256):
            raise ValueError('Requested separation workers must be between 1 and 256')
        # First admitted model is already budgeted; additional processes each
        # reserve 2 GiB of host memory, including import/loading overhead.
        ram_slots = 1 + int(max(0, (available or 0)-required_ram) // (2*GIB))
        cuda_slots = []
        if accel.get('separation_cuda'):
            for index, device in enumerate(devices):
                count = max(0, int((float(device.get('vram_free_mb') or 0)-512)//3072))
                cuda_slots.extend({'device':'cuda','cuda_device':device.get('uuid') or index} for _ in range(count))
        if cuda_slots:
            capacity = min(len(cuda_slots), ram_slots, max(1,cpu_budget//2),256)
            separation_slots = cuda_slots[:min(capacity,requested_workers or capacity)]
            use_gpu = True
        else:
            capacity = min(ram_slots,max(1,cpu_budget//4),256)
            separation_slots = [{'device':'cpu'} for _ in range(min(capacity,requested_workers or capacity))]
            use_gpu = False
        workers = len(separation_slots)
    return {
        "admitted": not reasons, "reasons": reasons,
        "separation_slots": separation_slots, "requested_workers": requested_workers,
        "heavy_workers": workers if not reasons and workload not in {'fit', 'speech'} else 0,
        "speech_workers": (0 if workload in {'fit', 'separation'} else 1 if workload == 'speech' else max(1, min(4, cpu_budget // 2, int(usable // (512 * 1024**2))))) if not reasons else 0,
        "fit_workers": 1 if not reasons and workload == 'fit' else 0,
        "cpu_threads_per_worker": max(1, cpu_budget // workers),
        "reserved_cpu_threads": cores - cpu_budget, "reserved_ram_bytes": reserve_ram,
        "available_ram_bytes": available, "working_storage_bytes": working_bytes,
        "required_available_ram_bytes": required_ram, "model_size": model_size,
        "workload": workload, "bounded_analysis": bounded_analysis,
        "required_free_disk_bytes": disk_required, "free_disk_bytes": free_disk,
        "asr_device": "cuda" if accel.get("asr_cuda") and gpu_slots else "cpu",
        "separation_device": "cuda" if use_gpu else "cpu",
        "chunk_seconds": 120 if usable >= 6 * GIB else 60,
        "context_seconds": 3, "duration_sec": duration_sec,
        "notice": "Worker counts are capacity limits, not speed guarantees. Model workers share device admission; the main terminal stays open.",
    }
