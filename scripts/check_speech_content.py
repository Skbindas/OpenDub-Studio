"""Offline CPU content check. Never downloads models during project synthesis."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


_model = None


def main(audio=None, output=None, language='hi'):
    global _model
    sys.stdout.reconfigure(encoding="utf-8")
    from faster_whisper import WhisperModel
    from backend.voice_bank_quality import fingerprint, write_report, audio_metrics
    audio, output = (Path(audio), Path(output)) if audio is not None else (Path(sys.argv[1]), Path(sys.argv[2]))
    if _model is None:
        _model = WhisperModel("small",device="cpu",compute_type="int8",cpu_threads=2,
                             local_files_only=True)
    model = _model
    segments, _ = model.transcribe(str(audio),language=language,beam_size=5,
                                  vad_filter=audio_metrics(audio)["duration_sec"] > 2)
    text = " ".join(segment.text.strip() for segment in segments)
    write_report(output,{"sha256":fingerprint(audio),"transcript":text,
                         "model":"faster-whisper-small","validator_version":2,"language":language})
    print(text,flush=True)


def serve():
    import json
    from backend.chunk_execution import save_json
    for line in sys.stdin:
        request = Path(line.strip())
        data = json.loads(request.read_text(encoding="utf-8"))
        try:
            main(data["audio"], data["output"], data.get("language", "hi"))
            save_json(request.with_name("content-worker-result.json"), {"ok": True})
        except Exception as exc:
            save_json(request.with_name("content-worker-result.json"), {"ok": False, "error": str(exc)})


if __name__ == "__main__":
    if "--serve" in sys.argv:
        serve()
    else:
        main(language=sys.argv[3] if len(sys.argv)>3 else 'hi')
