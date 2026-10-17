from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def mux_movie(
    source: Path,
    mixed_audio: Path,
    output: Path,
    video_codec: str = "copy",
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    from .kaggle_tasks import project_for
    if project_for(output):
        from .kaggle_operations import render
        return render(source,mixed_audio,output,video_codec,cancel_check)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg not found on PATH")
    if not source.is_file():
        raise RuntimeError("Source movie missing")
    if not mixed_audio.is_file():
        raise RuntimeError("Dubbed audio mix missing")
    if cancel_check and cancel_check():
        raise InterruptedError("Render cancelled before source validation; existing files retained")
    from .media import verify_media_decode
    verify_media_decode(source, cancelled=cancel_check or (lambda: False),
                        checkpoint=output.parent / "source_decode_checkpoint.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.stem + ".partial" + output.suffix)
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-y",
        "-i",
        str(source),
        "-i",
        str(mixed_audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-map",
        "0:s?",
        "-c:v",
        video_codec,
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-c:s",
        "mov_text" if output.suffix.lower() == ".mp4" else "copy",
        "-map_metadata",
        "0",
        "-shortest",
        "-movflags",
        "+faststart",
        str(temp),
    ]
    try:
        with tempfile.TemporaryFile(mode="w+b") as stderr_log:
            p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=stderr_log)
            peak_rss_bytes = 0
            while p.poll() is None:
                status_file = Path("/proc") / str(p.pid) / "status"
                try:
                    for line in status_file.read_text(encoding="ascii").splitlines():
                        if line.startswith("VmRSS:"):
                            peak_rss_bytes = max(peak_rss_bytes, int(line.split()[1]) * 1024)
                            break
                except (OSError, ValueError, IndexError):
                    pass
                if cancel_check and cancel_check():
                    p.terminate()
                    try:
                        p.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        p.kill()
                        p.wait()
                    raise InterruptedError("Render cancelled; FFmpeg process stopped and partial output removed.")
                time.sleep(0.25)
            stderr_log.seek(0, 2)
            log_size = stderr_log.tell()
            stderr_log.seek(max(0, log_size - 4000))
            stderr = stderr_log.read().decode("utf-8", errors="replace")
            if p.returncode or not temp.is_file() or temp.stat().st_size == 0:
                raise RuntimeError((stderr or "Mux failed")[-4000:])
        temp.replace(output)
        return {
            "file": str(output),
            "size_bytes": output.stat().st_size,
            "container": output.suffix.lstrip("."),
            "video_codec": video_codec,
            "audio_codec": "aac",
            "status": "completed",
            "peak_process_rss_bytes": peak_rss_bytes,
        }
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def verify_render_qa(
    source: Path,
    output: Path,
    dialogue_manifest_path: Path | None = None,
    mix_manifest_path: Path | None = None,
    tolerance_sec: float = 2.0,
) -> dict[str, Any]:
    """Automated Audio & Video Quality Assurance check for dubbed movies (PRD §9.3)."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe not found on PATH")

    checks: list[dict[str, Any]] = []
    hard_fail = False
    warning = False

    # Check 1: File existence & non-zero size
    if not output.is_file() or output.stat().st_size == 0:
        checks.append({"name": "File existence & size", "status": "fail", "detail": "Render output file is missing or empty."})
        return {
            "status": "FAILED",
            "verified_at": _now(),
            "checks": checks,
            "source_duration_sec": 0.0,
            "render_duration_sec": 0.0,
            "size_bytes": 0,
        }
    size_bytes = output.stat().st_size
    checks.append({"name": "File existence & size", "status": "pass", "detail": f"Output file exists ({size_bytes:,} bytes)."})

    # Check 2: Probe format and streams
    try:
        res = subprocess.run(
            [ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(output)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        data = json.loads(res.stdout or "{}")
        if res.returncode:
            raise RuntimeError(res.stderr or "Invalid output container")
        streams = data.get("streams", [])
        fmt = data.get("format", {})
        render_dur = float(fmt.get("duration", 0.0))
        checks.append({"name": "Container integrity", "status": "pass", "detail": f"Valid {fmt.get('format_name', 'media')} container."})
    except Exception as exc:
        checks.append({"name": "Container integrity", "status": "fail", "detail": f"FFprobe inspect failed: {exc}"})
        return {
            "status": "FAILED",
            "verified_at": _now(),
            "checks": checks,
            "source_duration_sec": 0.0,
            "render_duration_sec": 0.0,
            "size_bytes": size_bytes,
        }

    # Check 3: Stream presence (Video + Audio)
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

    if not video_streams:
        checks.append({"name": "Video stream", "status": "fail", "detail": "Missing video stream in rendered output."})
        hard_fail = True
    else:
        v = video_streams[0]
        checks.append({"name": "Video stream", "status": "pass", "detail": f"Codec {v.get('codec_name')}, {v.get('width')}x{v.get('height')}."})

    if not audio_streams:
        checks.append({"name": "Audio stream", "status": "fail", "detail": "Missing audio stream in rendered output."})
        hard_fail = True
    else:
        a = audio_streams[0]
        sr = int(a.get("sample_rate", 0))
        ch = int(a.get("channels", 0))
        checks.append({"name": "Audio stream", "status": "pass", "detail": f"Codec {a.get('codec_name')}, {sr} Hz, {ch} channel(s)."})

    # Check 4: Duration alignment against source
    source_dur = 0.0
    if source.is_file():
        try:
            s_res = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(source)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            source_dur = float(s_res.stdout.strip())
        except Exception:
            pass

    if source_dur > 0:
        dur_diff = abs(render_dur - source_dur)
        if dur_diff <= tolerance_sec:
            checks.append({"name": "Duration alignment", "status": "pass", "detail": f"Duration matches source ({render_dur:.2f}s vs {source_dur:.2f}s, diff {dur_diff:.2f}s)."})
        elif render_dur >= 0.90 * source_dur:
            checks.append({"name": "Duration alignment", "status": "warning", "detail": f"Duration deviation {dur_diff:.2f}s ({render_dur:.2f}s vs source {source_dur:.2f}s)."})
            warning = True
        else:
            checks.append({"name": "Duration alignment", "status": "fail", "detail": f"Early termination detected: render duration {render_dur:.2f}s vs source {source_dur:.2f}s. Dialogue coverage cannot verify missing video."})
            hard_fail = True

    try:
        from .media import verify_media_decode
        verify_media_decode(output, checkpoint=output.parent / "render_decode_checkpoint.json")
        checks.append({"name": "Full stream decode", "status": "pass", "detail": "All primary video and audio packets decoded without errors."})
    except RuntimeError as exc:
        checks.append({"name": "Full stream decode", "status": "fail", "detail": str(exc)})
        hard_fail = True

    # Check 5: Dialogue units inclusion
    if dialogue_manifest_path and dialogue_manifest_path.is_file():
        try:
            manifest_data = json.loads(dialogue_manifest_path.read_text(encoding="utf-8"))
            unit_count = len(manifest_data.get("units", []))
            mixed_count = 0
            if mix_manifest_path and mix_manifest_path.is_file():
                mix_data = json.loads(mix_manifest_path.read_text(encoding="utf-8"))
                mixed_count = int(mix_data.get("dialogue_segments_mixed", 0))
            if unit_count > 0:
                if mixed_count >= unit_count:
                    checks.append({"name": "Dialogue coverage", "status": "pass", "detail": f"{mixed_count}/{unit_count} dialogue units mixed into output."})
                elif mixed_count > 0:
                    checks.append({"name": "Dialogue coverage", "status": "warning", "detail": f"Partial dialogue: {mixed_count}/{unit_count} units included."})
                    warning = True
                else:
                    checks.append({"name": "Dialogue coverage", "status": "warning", "detail": f"Manifest has {unit_count} dialogue units; verify mix inclusion."})
        except Exception as exc:
            checks.append({"name": "Dialogue coverage", "status": "warning", "detail": f"Could not verify dialogue manifest: {exc}"})

    # Check 6: Check no partial artifact leak
    partial_file = output.with_name(output.stem + ".partial" + output.suffix)
    if partial_file.is_file():
        checks.append({"name": "Cleanup integrity", "status": "warning", "detail": "Unpromoted .partial artifact still exists."})
        warning = True
    else:
        checks.append({"name": "Cleanup integrity", "status": "pass", "detail": "No unpromoted .partial artifacts remain."})

    overall_status = "FAILED" if hard_fail else "WARNING" if warning else "PASSED"
    report = {
        "status": overall_status,
        "verified_at": _now(),
        "source_duration_sec": round(source_dur, 3),
        "render_duration_sec": round(render_dur, 3),
        "size_bytes": size_bytes,
        "checks": checks,
    }

    # Save QA report alongside output
    report_file = output.parent / "render_qa_report.json"
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_file"] = str(report_file)
    return report


def cleanup_intermediates(project: Path) -> dict[str, Any]:
    """Remove regenerable working audio only after verified final render."""
    removed = []
    errors = []
    candidates = [
        project / "analysis" / "source_16k_mono.wav",
        project / "analysis" / "separation",
        project / "segments",
        project / "output" / "source_audio_48k.wav",
    ]
    for path in candidates:
        try:
            if path.is_dir():
                shutil.rmtree(path)
                removed.append(str(path))
            elif path.is_file():
                path.unlink()
                removed.append(str(path))
        except OSError as exc:
            errors.append({"path": str(path), "error": str(exc)})
    return {
        "removed": removed,
        "errors": errors,
        "preserved": [
            "source movie",
            "analysis transcripts/scene metadata",
            "character registry",
            "final render",
            "final audio mix",
            "QA report",
        ],
    }
