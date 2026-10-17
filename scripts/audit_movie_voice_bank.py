"""Resume-safe audit of existing candidates, with real ASR and unconstrained speakers."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from backend.voice_bank_quality import (SCHEMA_VERSION, audio_metrics, fingerprint,
                                       classify_reference, exclusive_windows, write_report, bank_summary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="small")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--metrics-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=False)
    bank = ROOT / "storage/default_voice_bank/candidate_voices"
    out = ROOT / "runtime/voice-bank-audit"
    catalog = json.loads((bank / "all_extracted_characters_summary.json").read_text(encoding="utf-8"))["characters"]
    asr_model = pipeline = None
    if not args.metrics_only:
        from faster_whisper import WhisperModel
        import torch
        from pyannote.audio import Pipeline
        from backend.diarization import MODEL_NAME
        torch.set_num_threads(4)
        print("[Voice audit] Loading CPU ASR and speaker models. Existing app remains running.", flush=True)
        asr_model = WhisperModel(args.model, device="cpu", compute_type="int8", cpu_threads=4)
        pipeline = Pipeline.from_pretrained(MODEL_NAME, token=os.getenv("HF_TOKEN"))
        pipeline.to(torch.device("cpu"))
    records = []
    for index, meta in enumerate(catalog[:args.limit] if args.limit else catalog):
        cid = meta["character_id"]
        wav = bank / f"{cid}.wav"
        report_path = out / "records" / f"{cid}.json"
        digest = fingerprint(wav)
        existing = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
        if (not args.force and existing.get("sha256") == digest
            and existing.get("audit_version") == SCHEMA_VERSION
            and (args.metrics_only or existing.get("asr") is not None and existing.get("diarization") is not None)):
            records.append(existing)
            print(f"[Voice audit] {index+1}/{len(catalog)} reused {cid}", flush=True)
            continue
        started = time.monotonic()
        record = {"voice_id": cid, "metadata": meta, "reference_path": str(wav.resolve()),
                  "sha256": digest, "audit_version": SCHEMA_VERSION,
                  "source_status": "timecode_not_yet_compared", "review": {},
                  "perceived_voice": {"type": "unknown", "age_band": "unknown", "confidence": None,
                                      "note": "Audio cannot establish exact age; catalog demographics are unverified hints."}}
        if existing.get("sha256") == digest:
            for key in ("review", "clone", "source", "source_status", "perceived_voice", "delivery_variants"):
                if key in existing:
                    record[key] = existing[key]
        try:
            record["metrics"] = metrics = audio_metrics(wav)
            record["asr"] = record["diarization"] = None
            if asr_model is not None:
                segments, info = asr_model.transcribe(str(wav), language="hi", vad_filter=True,
                    word_timestamps=True, beam_size=3, condition_on_previous_text=False)
                record["asr"] = {"model": args.model, "language": info.language,
                    "segments": [{"start": s.start, "end": s.end, "text": s.text,
                                  "avg_logprob": s.avg_logprob, "no_speech_prob": s.no_speech_prob}
                                 for s in segments]}
                import soundfile as sf
                import torch
                from backend.diarization import _run_pipeline
                audio, rate = sf.read(wav, always_2d=True, dtype="float32")
                result = _run_pipeline(pipeline, {"waveform": torch.from_numpy(audio.T.copy()), "sample_rate": rate})
                annotation = getattr(result, "speaker_diarization", result)
                turns = [{"start": float(s.start), "end": float(s.end), "speaker_id": str(label)}
                         for s, _, label in annotation.itertracks(yield_label=True)]
                record["diarization"] = {"model": "pyannote/community-1", "turns": turns}
                record["repair_windows"] = [window for label in sorted({t["speaker_id"] for t in turns})
                                            for window in exclusive_windows(turns, label)]
            record["audit"] = classify_reference(metrics, record["asr"], record["diarization"])
        except Exception as exc:
            record["audit"] = {"status": "audit_failed", "error": f"{type(exc).__name__}: {exc}", "eligible_for_defaults": False}
        record["elapsed_sec"] = round(time.monotonic() - started, 2)
        write_report(report_path, record)
        records.append(record)
        write_report(out / "report.json", {"schema_version": SCHEMA_VERSION, "summary": bank_summary(records), "records": records,
                                           "complete": len(records) == len(catalog)})
        print(f"[Voice audit] {index+1}/{len(catalog)} {cid}: {record['audit']['status']} ({record['elapsed_sec']}s)", flush=True)
    # Include retained records on limited/restarted runs without losing earlier work.
    by_id = {r["voice_id"]: r for r in records}
    for meta in catalog:
        path = out / "records" / f"{meta['character_id']}.json"
        if meta["character_id"] not in by_id and path.exists():
            by_id[meta["character_id"]] = json.loads(path.read_text(encoding="utf-8"))
    records = list(by_id.values())
    write_report(out / "report.json", {"schema_version": SCHEMA_VERSION, "summary": bank_summary(records),
                                       "records": records, "complete": len(records) == len(catalog)})
    print(json.dumps(bank_summary(records)), flush=True)


if __name__ == "__main__":
    main()
