"""Create new reviewable single-speaker references; never overwrite candidates."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.voice_bank_quality import fingerprint, exclusive_windows, write_report, audio_metrics, classify_reference


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("voice_id")
    parser.add_argument("--movie", type=Path, required=True)
    parser.add_argument("--separate", action="store_true", help="Use real UVR model; fallback is rejected")
    parser.add_argument("--context", type=float, default=0, help="Extra seconds around original part for longer same-scene turns")
    args = parser.parse_args()
    bank = ROOT / "storage/default_voice_bank/candidate_voices"
    catalog = json.loads((bank / "all_extracted_characters_summary.json").read_text(encoding="utf-8"))["characters"]
    metadata = next((v for v in catalog if v["character_id"] == args.voice_id), None)
    if metadata is None:
        raise ValueError("Voice ID is not in the catalog")
    audit = ROOT / "runtime/voice-bank-audit/records" / f"{args.voice_id}.json"
    record = json.loads(audit.read_text(encoding="utf-8"))
    if not args.movie.is_file():
        raise FileNotFoundError("Source movie not found")
    context = max(0, min(30, args.context))
    start = max(0, float(metadata["start_sec"]) - context)
    duration = float(metadata["end_sec"]) + context - start
    if duration <= 0:
        raise ValueError("Invalid recorded source timecode")
    # File hash keeps repair versions stable and allows restarting expensive separation.
    key = record["sha256"][:12] + f"-context-{context:g}"
    folder = ROOT / "runtime/voice-bank-audit/repairs" / args.voice_id / key
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / "source.wav"
    if not source.is_file():
        subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-n", "-ss", str(start),
                        "-i", str(args.movie.resolve()), "-t", str(duration), "-map", "0:a:0",
                        "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(source)], check=True)
    selected = source
    separation = None
    if args.separate:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
        from backend.background_preservation import separate_dialogue_candidate
        saved = folder / "separation.json"
        separation = json.loads(saved.read_text(encoding="utf-8")) if saved.exists() else None
        if not separation or separation.get("status") != "completed" or not Path(separation.get("dialogue_candidate", "")).is_file():
            separation = separate_dialogue_candidate(source, folder / "stems")
            write_report(saved, separation)
        if separation.get("status") != "completed":
            raise RuntimeError("Real separation unavailable; original mix must not be labeled clean vocals")
        selected = Path(separation["dialogue_candidate"])
    # Re-diarize original source, rather than trusting a possibly cropped/altered candidate.
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
    from backend.diarization import diarize
    saved_turns = folder / "source-speakers.json"
    if saved_turns.exists():
        turns = json.loads(saved_turns.read_text(encoding="utf-8"))["turns"]
    else:
        analysis = folder / "source-16k.wav"
        subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-y", "-i", str(source),
                        "-ar", "16000", "-ac", "1", str(analysis)], check=True)
        # Use non-exclusive annotation for overlap detection in the shared audit runner.
        from pyannote.audio import Pipeline
        import torch
        from backend.diarization import MODEL_NAME, _load_pcm_wav, _run_pipeline
        import os
        torch.set_num_threads(4)
        pipeline = Pipeline.from_pretrained(MODEL_NAME, token=os.getenv("HF_TOKEN"))
        pipeline.to(torch.device("cpu"))
        waveform, rate = _load_pcm_wav(analysis)
        result = _run_pipeline(pipeline, {"waveform":waveform, "sample_rate":rate})
        annotation = getattr(result, "speaker_diarization", result)
        turns = [{"start":float(s.start), "end":float(s.end), "speaker_id":str(label)}
                 for s, _, label in annotation.itertracks(yield_label=True)]
        write_report(saved_turns, {"turns":turns})
    import soundfile as sf
    audio, rate = sf.read(selected, always_2d=True)
    repairs = []
    from faster_whisper import WhisperModel
    asr_model = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=4, num_workers=1)
    for speaker in sorted({t["speaker_id"] for t in turns}):
        windows = exclusive_windows(turns, speaker, minimum=3, maximum=10)
        if not windows:
            repairs.append({"speaker_id":speaker, "status":"alternative_source_required",
                            "reason":"No exclusive 3-second speech window; do not force mixed voices apart"})
            continue
        window = windows[0]
        output = folder / f"{speaker}-reference-{round(window['start']*1000)}-{round(window['end']*1000)}.wav"
        if not output.is_file():
            sf.write(output, audio[int(window["start"]*rate):int(window["end"]*rate)].mean(axis=1), rate, subtype="PCM_16")
        segments, info = asr_model.transcribe(str(output), language="hi", vad_filter=True, beam_size=3)
        asr = {"model":"small", "segments":[{"start":float(s.start), "end":float(s.end),
                   "text":s.text, "avg_logprob":float(s.avg_logprob), "no_speech_prob":float(s.no_speech_prob)} for s in segments]}
        metrics = audio_metrics(output)
        isolated_turns = {"turns":[{"start":0,"end":metrics["duration_sec"],"speaker_id":speaker}]}
        repairs.append({"speaker_id":speaker, "path":str(output), "sha256":fingerprint(output),
                        "source_start_sec":start+window["start"], "source_end_sec":start+window["end"],
                        "metrics":metrics, "asr":asr, "audit":classify_reference(metrics,asr,isolated_turns),
                        "status":"candidate_requires_identity_and_listening",
                        "background_status":"separated_requires_listening" if separation else "not_separated"})
    prior_report = folder / "repair.json"
    if prior_report.is_file():
        history = folder / "repair-history"
        history.mkdir(exist_ok=True)
        shutil.copy2(prior_report, history / f"{fingerprint(prior_report)}.json")
    write_report(prior_report, {"voice_id":args.voice_id, "original_sha256":record["sha256"],
                                           "source_movie":str(args.movie.resolve()), "repairs":repairs})
    print(json.dumps(repairs, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
