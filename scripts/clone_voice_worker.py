"""Optional heavy worker. Never replaces missing speech with stock voices or tones."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys
import time
import uuid
import shutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_loaded_model = None
_loaded_device = None


def generation_options(prosody, prompt):
    mode = prosody.get('duration_mode', 'fixed')
    if mode not in {'fixed', 'natural'}:
        raise ValueError('Unsupported speech duration mode')
    from backend.dubbing_languages import target_language
    code, name = target_language(prosody.get('language', 'hi'))
    options = {'language': name, 'voice_clone_prompt': prompt,
               'num_step': max(16, min(128, int(prosody.get('generation_steps', 64)))),
               'speed': max(.9, min(1.1, float(prosody.get('rate', 1))))}
    # A source clock is still enforced by the separate native timing-fit gate.
    # OmniVoice's fixed duration overrides speed and can crush a short utterance.
    if mode == 'fixed' and prosody.get('target_duration_sec', 0) > 0:
        options['duration'] = float(prosody['target_duration_sec'])
    return options


def main(request=None):
    global _loaded_model, _loaded_device
    sys.stdout.reconfigure(encoding="utf-8")
    if request is None:
        request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    import numpy as np
    import soundfile as sf
    import torch
    from omnivoice import OmniVoice, VoiceClonePrompt
    from backend.voice_bank_quality import audio_metrics, fingerprint, write_report
    reference = Path(request["reference"])
    metrics = audio_metrics(reference)
    if not 3 <= metrics["duration_sec"] <= 10.01 or metrics["fixed_tone_suspected"]:
        raise ValueError("Clone reference must contain reviewed speech, 3-10 seconds long")
    digest = fingerprint(reference)
    if digest != request["reference_sha256"]:
        raise ValueError("Reference changed since clone request")
    torch.set_num_threads(4)
    started = time.monotonic()
    device = "cpu"
    if torch.cuda.is_available():
        free, total = torch.cuda.mem_get_info()
        if free >= 3.2 * 1024**3:
            device = "cuda"
    if _loaded_model is None:
        print(f"[Clone] Loading genuine OmniVoice; speech model {device}, audio tokenizer CPU", flush=True)
        dtype=torch.float16 if request.get('dtype')=='float16' or os.getenv('OPENDUB_CLONE_DTYPE')=='float16' else torch.bfloat16
        model = OmniVoice.from_pretrained(request.get('model_source') or "k2-fsa/OmniVoice", device_map="cpu", dtype=dtype,
                                         attn_implementation="sdpa", load_asr=False)
        # Keep the 0.8 GiB tokenizer off a 4 GiB GPU. Move only generation modules.
        if device == "cuda":
            model.llm.to(device)
            model.audio_embeddings.to(device)
            model.audio_heads.to(device)
            model.codebook_layer_offsets = model.codebook_layer_offsets.to(device)
        _loaded_model, _loaded_device = model, device
    else:
        model, device = _loaded_model, _loaded_device
        print(f"[Clone] Reusing genuine OmniVoice on {device}; audio tokenizer CPU",flush=True)
    folder = Path(request["prompt_dir"])
    folder.mkdir(parents=True, exist_ok=True)
    import hashlib
    prompt_key = hashlib.sha256((digest + request["ref_text"] + "omnivoice-0.2.1").encode()).hexdigest()
    prompt_path = folder / f"{prompt_key}.pt"
    if prompt_path.is_file():
        prompt = VoiceClonePrompt.load(str(prompt_path))
    else:
        prompt = model.create_voice_clone_prompt(ref_audio=str(reference), ref_text=request["ref_text"])
        pending_prompt = folder / f"{prompt_key}.{uuid.uuid4().hex}.pending.pt"
        prompt.save(str(pending_prompt))
        pending_prompt.replace(prompt_path)
    prosody = request.get("prosody", {})
    options = generation_options(prosody, prompt)
    steps = options['num_step']
    seed = int(prosody.get("seed", 42))
    torch.manual_seed(seed)
    print("[Clone] Reference encoded; synthesizing requested speech", flush=True)
    completed_steps = 0
    def progress(module, inputs, result):
        nonlocal completed_steps
        completed_steps += 1
        print(f"[Clone] Decoding step {completed_steps}/{steps}", flush=True)
    progress_hook = model.register_forward_hook(progress)
    inference_started = time.monotonic()
    try:
        audio = model.generate(text=request["text"], **options)
    finally:
        progress_hook.remove()
    samples = np.asarray(audio[0])
    if not samples.size or not np.isfinite(samples).all():
        raise RuntimeError("Model returned empty/non-finite speech")
    output = Path(request["output"])
    output.parent.mkdir(parents=True, exist_ok=True)
    pending = output.with_name(f"{output.stem}.{uuid.uuid4().hex}.pending.wav")
    try:
        sf.write(pending, samples, model.sampling_rate, subtype="PCM_16")
        result_metrics = audio_metrics(pending)
        if result_metrics["fixed_tone_suspected"] or result_metrics["rms_dbfs"] < -65:
            raise RuntimeError("Generated output is a tone or silence, not a usable clone")
        if output.is_file():
            history = output.parent / "history" / output.stem
            history.mkdir(parents=True, exist_ok=True)
            prior = fingerprint(output)
            shutil.copy2(output, history / f"{prior}.wav")
            manifest = output.with_suffix(".clone.json")
            if manifest.is_file():
                shutil.copy2(manifest, history / f"{prior}.clone.json")
        pending.replace(output)
    finally:
        pending.unlink(missing_ok=True)
    unsupported = [k for k in ("emotion", "delivery", "pitch_semitones")
                   if prosody.get(k) not in (None, "", "unspecified", "neutral", 0)]
    report = {"status": "completed", "reference_conditioned": True, "engine": "OmniVoice",
              "model": "k2-fsa/OmniVoice", "provider_version": "0.2.1", "device": device,
              "tokenizer_device": "cpu", "requested_duration_sec": prosody.get("target_duration_sec"),
              "language": prosody.get("language", "hi"),
              "generation_duration_mode": prosody.get('duration_mode', 'fixed'),
              "generation_steps": steps, "seed": seed,
              "file": str(output), "output_sha256": fingerprint(output), "reference_sha256": digest,
              "ref_text": request["ref_text"], "text": request["text"], "metrics": result_metrics,
              "duration_sec": result_metrics["duration_sec"], "elapsed_sec": round(time.monotonic()-started, 2),
              "generation_sec": round(time.monotonic()-inference_started, 2),
              "prompt_path": str(prompt_path), "prosody_unsupported": unsupported,
              "identity_status": "listening_review_required", "emotion_status": "reference_delivery_only"}
    write_report(output.with_suffix(".clone.json"), report)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return report


def serve():
    # One model stays warm for a batch; this process owns the physical GPU slot.
    from backend.clone_runtime import clone_worker_slot
    from backend.chunk_execution import save_json
    with clone_worker_slot():
        for line in sys.stdin:
            request_path = Path(line.strip())
            request = json.loads(request_path.read_text(encoding="utf-8"))
            done = request_path.with_name("worker-result.json")
            try:
                result = main(request)
                save_json(done, {"ok": True, "result": result})
            except Exception as exc:
                save_json(done, {"ok": False, "error": str(exc)})


if __name__ == "__main__":
    if "--serve" in sys.argv:
        serve()
    else:
        main()
