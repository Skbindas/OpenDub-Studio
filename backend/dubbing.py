"""Theatrical Dialogue Dubbing & Avengers-Grade Prosody Synthesis for OpenDub Studio.

Features:
- Natural conversational cadence shaping with breath markers and dramatic punctuation pacing
- Expressive theatrical styles:
    * heroic_confident (Tony Stark / Thor)
    * sharp_detective (Black Widow / Sherlock)
    * authoritative_chief (Nick Fury / Police Commissioner)
    * gritty_baritone (Wolverine / Thanos)
    * raspy_villain (Loki / Green Goblin)
    * youthful_spirited (Spider-Man / Peter Parker)
    * maternal_warmth (Aunt May / Caring Matriarch)
- SSML generation and prosody rate, pitch inflection, and formant EQ controls
- Seamless integration with the new voice_cloning.py engine
- Robust Argos Translate pipeline for multi-lingual transcript translation
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

# Dynamic integration with the voice cloning engine
try:
    from . import voice_cloning
except ImportError:
    try:
        from backend import voice_cloning
    except ImportError:
        voice_cloning = None


# ---------------------------------------------------------------------------
# Theatrical Styles & Avengers / Bollywood Character Archetypes
# ---------------------------------------------------------------------------
THEATRICAL_STYLES: dict[str, dict[str, Any]] = {
    "heroic_confident": {
        "name": "Heroic & Confident",
        "description": "Tony Stark / Thor / Hero lead: resonant, powerful, charismatic, steady cadence",
        "rate": 1.02,
        "pitch_semitones": -0.8,
        "noise_scale": 0.72,
        "noise_w": 0.85,
        "sentence_silence": 0.22,
        "eq_bass_boost_db": 1.8,
        "eq_treble_boost_db": 0.5,
        "breath_pause_ms": 220,
        "inflection": "dramatic_punch",
    },
    "sharp_detective": {
        "name": "Sharp Detective",
        "description": "Black Widow / Sherlock: fast, razor-sharp analytical cadence, crisp stops",
        "rate": 1.08,
        "pitch_semitones": 0.6,
        "noise_scale": 0.68,
        "noise_w": 0.82,
        "sentence_silence": 0.18,
        "eq_bass_boost_db": 0.0,
        "eq_treble_boost_db": 2.2,
        "breath_pause_ms": 160,
        "inflection": "sharp_inquisitive",
    },
    "authoritative_chief": {
        "name": "Authoritative Chief",
        "description": "Nick Fury / Police Commissioner: slow, heavy gravity, commanding presence",
        "rate": 0.92,
        "pitch_semitones": -2.2,
        "noise_scale": 0.76,
        "noise_w": 0.90,
        "sentence_silence": 0.35,
        "eq_bass_boost_db": 3.2,
        "eq_treble_boost_db": -0.5,
        "breath_pause_ms": 320,
        "inflection": "commanding_descent",
    },
    "gritty_baritone": {
        "name": "Gritty Baritone",
        "description": "Wolverine / Thanos: heavy baritone, gravel overdrive, deliberate menacing pacing",
        "rate": 0.90,
        "pitch_semitones": -3.2,
        "noise_scale": 0.84,
        "noise_w": 0.94,
        "sentence_silence": 0.32,
        "eq_bass_boost_db": 4.5,
        "eq_treble_boost_db": -1.0,
        "breath_pause_ms": 300,
        "inflection": "gravel_steady",
    },
    "raspy_villain": {
        "name": "Raspy Villain",
        "description": "Loki / Green Goblin: sinuous, chilling, dynamic whisper-to-growl cadence",
        "rate": 0.96,
        "pitch_semitones": -1.4,
        "noise_scale": 0.88,
        "noise_w": 0.95,
        "sentence_silence": 0.28,
        "eq_bass_boost_db": 1.0,
        "eq_treble_boost_db": 2.8,
        "breath_pause_ms": 280,
        "inflection": "sinuous_creep",
    },
    "youthful_spirited": {
        "name": "Youthful Spirited",
        "description": "Spider-Man / Peter Parker / Ms Marvel: energetic, bright, rapid, playful",
        "rate": 1.10,
        "pitch_semitones": 1.8,
        "noise_scale": 0.70,
        "noise_w": 0.88,
        "sentence_silence": 0.16,
        "eq_bass_boost_db": -0.5,
        "eq_treble_boost_db": 1.8,
        "breath_pause_ms": 150,
        "inflection": "playful_uplift",
    },
    "maternal_warmth": {
        "name": "Maternal Warmth",
        "description": "Aunt May / Caring Matriarch: soft, soothing, gentle cadence, warm low-mids",
        "rate": 0.95,
        "pitch_semitones": -0.5,
        "noise_scale": 0.65,
        "noise_w": 0.80,
        "sentence_silence": 0.26,
        "eq_bass_boost_db": 1.5,
        "eq_treble_boost_db": -0.5,
        "breath_pause_ms": 240,
        "inflection": "warm_melodic",
    },
}

# Emotion tag to theatrical style map
EMOTION_TO_STYLE_MAP: dict[str, str] = {
    "[confident]": "heroic_confident",
    "[intense]": "sharp_detective",
    "[angry]": "gritty_baritone",
    "[whisper]": "raspy_villain",
    "[playful]": "youthful_spirited",
    "[authoritative]": "authoritative_chief",
}


# ---------------------------------------------------------------------------
# Conversational Cadence & Punctuation Pacing
# ---------------------------------------------------------------------------
def shape_conversational_cadence(
    text: str,
    requested_style: str = "",
    prosody: dict[str, Any] | None = None,
) -> tuple[str, str, dict[str, Any]]:
    """Transform flat, monotone dialogue into natural human theatrical cadence.

    - Extracts attitude/emotion tags ([confident], [intense], etc.)
    - Selects the matching theatrical style
    - Inserts natural breath pauses after vocatives and discourse markers
    - Shapes punctuation pacing (commas, ellipses for realistic pauses)
    """
    clean_text = text.strip()
    detected_emotion = ""

    # 1. Extract bracketed emotion tag if present
    match = re.search(r"(\[(confident|intense|angry|whisper|playful|authoritative)\])", clean_text, re.IGNORECASE)
    if match:
        detected_emotion = match.group(1).lower()
        clean_text = clean_text[:match.start()] + clean_text[match.end():]
        clean_text = clean_text.strip()

    # 2. Determine effective theatrical style
    style_key = (requested_style or "").strip().lower()
    if not style_key or style_key not in THEATRICAL_STYLES:
        if prosody and prosody.get("style") in THEATRICAL_STYLES:
            style_key = prosody["style"]
        elif detected_emotion in EMOTION_TO_STYLE_MAP:
            style_key = EMOTION_TO_STYLE_MAP[detected_emotion]
        elif prosody and prosody.get("delivery") in THEATRICAL_STYLES:
            style_key = prosody["delivery"]
        else:
            style_key = "heroic_confident"

    style_cfg = THEATRICAL_STYLES.get(style_key, THEATRICAL_STYLES["heroic_confident"])

    # 3. Conversational breath markers & punctuation pacing
    # Hindi discourse markers that naturally require a breath pause
    vocatives = [
        "सुनो", "देखो", "यार", "अरे", "रुको", "सच में", "अच्छा", "हाँ", "नहीं",
        "बात सुनो", "एक मिनट", "ध्यान से",
    ]
    for voc in vocatives:
        # If followed by a word without comma/ellipsis, insert natural pause
        pattern = rf"(^|\s)({re.escape(voc)})(?![\s]*[,!?.…\-])(\s+)"
        clean_text = re.sub(pattern, r"\1\2,\3", clean_text)

    # Conjunctions with pre-clause breath pause
    conjunctions = ["लेकिन", "परंतु", "मगर", "क्योंकि", "वरना"]
    for conj in conjunctions:
        pattern = rf"(\S)\s+({re.escape(conj)})(\s+)"
        clean_text = re.sub(pattern, r"\1, \2\3", clean_text)

    # Ellipses for suspense/whisper or dramatic trailing
    if style_key in ("raspy_villain", "sharp_detective") and clean_text.endswith((".", "।")):
        clean_text = clean_text[:-1] + "..."
    elif style_key in ("heroic_confident", "authoritative_chief", "gritty_baritone") and clean_text.endswith("."):
        clean_text = clean_text[:-1] + "!"

    # Clean double spaces and duplicate punctuation
    clean_text = re.sub(r"\s+", " ", clean_text).strip()
    clean_text = re.sub(r",\s*,+", ", ", clean_text)

    meta = {
        "original_text": text,
        "cadence_text": clean_text,
        "detected_emotion": detected_emotion,
        "theatrical_style": style_key,
        "style_config": style_cfg,
    }
    return clean_text, style_key, meta


# ---------------------------------------------------------------------------
# SSML Generation and Parsing
# ---------------------------------------------------------------------------
def build_theatrical_ssml(
    text: str,
    prosody: dict[str, Any] | None = None,
    style_name: str = "",
) -> str:
    """Generate W3C / Edge-TTS compliant SSML with expressive rate, pitch, and breaks."""
    prosody = prosody or {}
    shaped_text, style_key, meta = shape_conversational_cadence(text, style_name, prosody)
    style_cfg = meta["style_config"]

    # Calculate effective rate and pitch
    user_rate = float(prosody.get("rate", 1.0))
    effective_rate = round(user_rate * style_cfg.get("rate", 1.0), 3)
    user_pitch = float(prosody.get("pitch_semitones", prosody.get("pitch", 0.0)))
    effective_pitch = round(user_pitch + style_cfg.get("pitch_semitones", 0.0), 2)

    rate_str = f"{effective_rate * 100:.0f}%"
    pitch_str = f"{effective_pitch:+.1f}st"
    pause_ms = style_cfg.get("breath_pause_ms", 200)

    # Replace commas with explicit SSML micro-breaks
    ssml_body = shaped_text.replace(", ", f', <break time="{pause_ms // 2}ms"/> ')
    ssml_body = ssml_body.replace("...", f'... <break time="{pause_ms}ms"/> ')

    return (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="hi-IN">\n'
        f'  <prosody rate="{rate_str}" pitch="{pitch_str}">\n'
        f"    {ssml_body}\n"
        "  </prosody>\n"
        "</speak>"
    )


def parse_ssml_text(ssml_string: str) -> tuple[str, dict[str, Any]]:
    """Parse SSML to extract clean text with pauses and extracted prosody values."""
    if not ssml_string.strip().startswith("<speak"):
        return ssml_string, {}
    try:
        root = ET.fromstring(ssml_string)
        text_parts = []
        prosody_info: dict[str, Any] = {}

        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag == "prosody":
                if "rate" in elem.attrib:
                    prosody_info["rate_attr"] = elem.attrib["rate"]
                if "pitch" in elem.attrib:
                    prosody_info["pitch_attr"] = elem.attrib["pitch"]
            elif tag == "break":
                text_parts.append(", ")
            if elem.text:
                text_parts.append(elem.text)
            if elem.tail:
                text_parts.append(elem.tail)

        clean = " ".join("".join(text_parts).split())
        return clean, prosody_info
    except Exception:
        clean = re.sub(r"<[^>]+>", " ", ssml_string)
        return " ".join(clean.split()), {}


# ---------------------------------------------------------------------------
# FFmpeg Prosody Post-Processing (Pitch Inflection & Formant EQ)
# ---------------------------------------------------------------------------
def _get_audio_sample_rate(file_path: Path) -> int:
    """Read WAV sample rate via ffprobe with fallback to 22050 Hz."""
    ffprobe_cmd = shutil.which("ffprobe")
    if ffprobe_cmd and file_path.is_file():
        try:
            res = subprocess.run(
                [
                    ffprobe_cmd, "-v", "error", "-select_streams", "a:0",
                    "-show_entries", "stream=sample_rate",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(file_path),
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode == 0 and res.stdout.strip().isdigit():
                return int(res.stdout.strip())
        except Exception:
            pass
    return 22050


def apply_audio_prosody_shaping(
    audio_path: Path,
    style_key: str = "",
    pitch_semitones: float = 0.0,
    volume_db: float = 0.0,
    pitch_dynamics: bool = True,
) -> bool:
    """Apply pitch shifting, theatrical vocal EQ, and dynamics via FFmpeg."""
    ffmpeg_cmd = shutil.which("ffmpeg")
    if not ffmpeg_cmd or not audio_path.is_file() or audio_path.stat().st_size == 0:
        return False

    style_cfg = THEATRICAL_STYLES.get(style_key, THEATRICAL_STYLES.get("heroic_confident", {}))
    effective_pitch = float(pitch_semitones) + float(style_cfg.get("pitch_semitones", 0.0))
    bass_boost = float(style_cfg.get("eq_bass_boost_db", 0.0))
    treble_boost = float(style_cfg.get("eq_treble_boost_db", 0.0))

    filters = []
    sr = _get_audio_sample_rate(audio_path)

    # 1. Pitch shifting via asetrate + atempo (no duration distortion)
    if abs(effective_pitch) >= 0.1:
        pitch_factor = 2.0 ** (effective_pitch / 12.0)
        shifted_rate = round(sr * pitch_factor)
        atempo = 1.0 / pitch_factor
        filters.append(f"asetrate={shifted_rate},atempo={atempo:.5f},aresample={sr}")

    # 2. Formant & Vocal Texture EQ
    if abs(bass_boost) >= 0.2:
        filters.append(f"equalizer=f=140:width_type=o:width=1.5:g={bass_boost:+.1f}")
    if abs(treble_boost) >= 0.2:
        filters.append(f"equalizer=f=3200:width_type=o:width=1.5:g={treble_boost:+.1f}")

    # 3. Dynamic vibrato / pitch liveliness (avoids robotic monotone flatline)
    if pitch_dynamics and style_key in ("youthful_spirited", "raspy_villain", "heroic_confident"):
        filters.append("vibrato=f=4.0:d=0.15")

    # 4. Volume leveling
    if abs(volume_db) >= 0.2:
        filters.append(f"volume={volume_db:+.1f}dB")

    if not filters:
        return False

    filter_str = ",".join(filters)
    tmp_out = audio_path.with_name(f"{audio_path.stem}.prosody_tmp_{uuid.uuid4().hex[:8]}.wav")

    try:
        proc = subprocess.run(
            [ffmpeg_cmd, "-y", "-i", str(audio_path), "-af", filter_str, str(tmp_out)],
            capture_output=True,
            timeout=30,
        )
        if proc.returncode == 0 and tmp_out.is_file() and tmp_out.stat().st_size > 44:
            tmp_out.replace(audio_path)
            return True
    except Exception:
        pass
    finally:
        tmp_out.unlink(missing_ok=True)
    return False


# ---------------------------------------------------------------------------
# Voice Cloning Engine Integration
# ---------------------------------------------------------------------------
def is_voice_cloning_available() -> bool:
    """Check if the voice_cloning module is available in the environment."""
    return voice_cloning is not None


def synthesize_cloned_segment(
    text: str,
    output_path: Path,
    reference_audio: Path | str,
    prosody: dict[str, Any] | None = None,
    speaker_id: str | None = None,
    style_key: str = "",
) -> dict[str, Any]:
    """Directly synthesize speech using the voice_cloning engine."""
    prosody = prosody or {}
    shaped_text, resolved_style, meta = shape_conversational_cadence(text, style_key, prosody)

    if voice_cloning is None:
        raise RuntimeError(
            "Voice cloning engine (voice_cloning.py) is not installed or available. "
            "Please ensure voice_cloning.py is in backend/."
        )

    ref_path = Path(reference_audio)

    # Inspect available voice cloning synthesis signatures
    cloned_result: dict[str, Any] | None = None

    if hasattr(voice_cloning, "synthesize_cloned_voice"):
        cloned_result = voice_cloning.synthesize_cloned_voice(
            text=shaped_text,
            output_path=output_path,
            reference_audio=ref_path,
            prosody=prosody,
            speaker_id=speaker_id,
        )
    elif hasattr(voice_cloning, "clone_and_synthesize"):
        cloned_result = voice_cloning.clone_and_synthesize(
            text=shaped_text,
            output_path=output_path,
            reference_audio=ref_path,
        )
    elif hasattr(voice_cloning, "synthesize_speech"):
        cloned_result = voice_cloning.synthesize_speech(
            text=shaped_text,
            output_path=output_path,
            reference_audio=ref_path,
            prosody=prosody,
        )
    elif hasattr(voice_cloning, "VoiceCloner"):
        cloner = voice_cloning.VoiceCloner()
        if hasattr(cloner, "synthesize"):
            cloned_result = cloner.synthesize(
                text=shaped_text,
                output_path=output_path,
                reference_audio=ref_path,
            )

    if cloned_result is None or not output_path.is_file():
        raise RuntimeError("Voice cloning engine failed to synthesize audio file.")

    # Apply theatrical prosody post-processing if needed
    apply_audio_prosody_shaping(
        output_path,
        style_key=resolved_style,
        pitch_semitones=float(prosody.get("pitch_semitones", 0.0)),
        volume_db=float(prosody.get("volume_db", 0.0)),
    )

    return {
        "file": str(output_path),
        "size_bytes": output_path.stat().st_size,
        "engine": "VoiceCloning",
        "reference_audio": str(ref_path),
        "theatrical_style": resolved_style,
        "cadence_shaped_text": shaped_text,
        "prosody_applied": {
            "rate": prosody.get("rate", 1.0),
            "style": resolved_style,
            "voice_cloning": True,
        },
        "prosody_unsupported": [],
        "prosody_status": "applied",
    }


# ---------------------------------------------------------------------------
# Dialogue Translation (Argos Translate)
# ---------------------------------------------------------------------------
def translate_transcript(
    transcript_path: Path,
    output_path: Path,
    target_language: str,
    source_language: str | None = None,
) -> dict[str, Any]:
    """Translate each ASR segment with locally installed Argos Translate packages."""
    if not transcript_path.exists():
        raise RuntimeError("Run transcription first.")
    try:
        import argostranslate.translate as argos_translate
    except ImportError as exc:
        raise RuntimeError("Optional translation engine missing. Install requirements-translation.txt.") from exc

    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    target = target_language.strip().lower()
    language_map = {
        "hindi": "hi", "english": "en", "korean": "ko", "chinese": "zh",
        "japanese": "ja", "spanish": "es", "french": "fr", "german": "de",
    }
    target_code = language_map.get(target, target)
    source_code = language_map.get(
        (source_language or transcript.get("language") or "").lower(),
        (source_language or transcript.get("language") or "").lower(),
    )

    installed = {lang.code: lang for lang in argos_translate.get_installed_languages()}

    def resolve_pair(from_code: str, to_code: str):
        source_lang = installed.get(from_code)
        target_lang = installed.get(to_code)
        if source_lang is None or target_lang is None:
            return None
        try:
            return source_lang.get_translation(target_lang)
        except Exception:
            return None

    direct_translation = None
    pivot_translation = None
    if source_code and source_code != target_code:
        direct_translation = resolve_pair(source_code, target_code)
        if direct_translation is None and source_code != "en" and target_code != "en":
            source_to_english = resolve_pair(source_code, "en")
            english_to_target = resolve_pair("en", target_code)
            if source_to_english is not None and english_to_target is not None:
                pivot_translation = (source_to_english, english_to_target)
        if direct_translation is None and pivot_translation is None:
            raise RuntimeError(
                f"Argos cannot translate {source_code}->{target_code}. Install that direct pair, "
                f"or install both {source_code}->en and en->{target_code} pivot packages."
            )

    rows = []
    from .work_progress import emit
    total_rows = len(transcript.get("segments", []))
    emit(0, total_rows)
    for index, segment in enumerate(transcript.get("segments", [])):
        text = (segment.get("text") or "").strip()
        translated = ""
        error = None
        try:
            if not text:
                translated = ""
            elif source_code and source_code != target_code:
                if direct_translation is not None:
                    translated = direct_translation.translate(text)
                elif pivot_translation is not None:
                    intermediate = pivot_translation[0].translate(text)
                    translated = pivot_translation[1].translate(intermediate)
                else:
                    raise RuntimeError(f"No translation route for {source_code}->{target_code}.")
            else:
                translated = text
                if source_code == target_code:
                    error = "Source and target languages are identical; retained original text."
            if text and (not isinstance(translated, str) or not translated.strip()):
                translated = ""
                raise RuntimeError("Translation engine returned empty output for spoken dialogue; repair this line before synthesis.")
        except Exception as exc:
            error = str(exc)
        rows.append({
            **segment,
            "segment_index": index,
            "source_text": text,
            "translated_text": translated,
            "translation_error": error,
            "target_language": target_code,
        })
        emit(index + 1, total_rows)

    result = {
        "target_language": target_code,
        "source_language": source_code or None,
        "engine": "Argos Translate (local)",
        "segments": rows,
        "adaptation": {
            "status": "baseline_translation",
            "mode": "source_faithful_dialogue",
            "note": "Translation preserves source segment boundaries, speaker identity and source timing.",
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp = output_path.with_name(f"{output_path.stem}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        replace_error = None
        for attempt in range(5):
            try:
                temp.replace(output_path)
                replace_error = None
                break
            except PermissionError as exc:
                replace_error = exc
                if attempt < 4:
                    time.sleep(0.2 * (attempt + 1))
        if replace_error is not None:
            raise RuntimeError(
                "Windows could not replace translated_transcript.json because another process "
                "or cloud-sync client is holding the file. Pause sync and retry."
            ) from replace_error
    finally:
        temp.unlink(missing_ok=True)

    error_rows = [row for row in rows if row["translation_error"]]
    error_summary = {}
    for row in error_rows:
        message = str(row["translation_error"])[:300]
        error_summary[message] = error_summary.get(message, 0) + 1
    return {
        "target_language": target_code,
        "source_language": source_code or None,
        "segment_count": len(rows),
        "errors": len(error_rows),
        "error_summary": error_summary,
        "file": str(output_path),
    }


# ---------------------------------------------------------------------------
# Piper Synthesis with Expressive Theatrical Shaping
# ---------------------------------------------------------------------------
def plan_speech_rate(text: str, target_duration_sec: float, rate: float = 1.0) -> dict[str, Any]:
    """Use the source window before TTS; estimates never replace measured fitting."""
    from .semantic_adaptation import estimate_hindi_speaking_duration
    estimate = estimate_hindi_speaking_duration(text)
    required = estimate / target_duration_sec if target_duration_sec > 0 else rate
    chosen = max(rate * .9, min(rate * 1.1, required))
    return {"rate": chosen, "target_duration_sec": target_duration_sec,
            "estimated_duration_sec": estimate, "estimate_only": True,
            "needs_shorter_dialogue": target_duration_sec > 0 and estimate / chosen > target_duration_sec * 1.15}


def synthesize_piper_segment(
    text: str,
    output_path: Path,
    voice_model: Path,
    speaker_id: int | None = None,
    prosody: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Synthesize dialogue with Piper, expressive cadence shaping, and FFmpeg prosody."""
    if not text.strip():
        raise RuntimeError("Cannot synthesize an empty segment.")

    prosody = prosody or {}

    # Delegate to voice cloning if requested
    is_cloning = (
        prosody.get("voice_cloning")
        or prosody.get("engine") == "voice_cloning"
        or prosody.get("provider") == "voice_cloning"
        or prosody.get("reference_audio")
    )
    if is_cloning and is_voice_cloning_available():
        ref_audio = prosody.get("reference_audio") or voice_model
        return synthesize_cloned_segment(
            text=text,
            output_path=output_path,
            reference_audio=ref_audio,
            prosody=prosody,
            speaker_id=str(speaker_id) if speaker_id is not None else None,
        )

    executable = shutil.which("piper")
    if not executable:
        local_piper = Path(__file__).resolve().parents[1] / ".venv" / "Scripts" / (
            "piper.exe" if sys.platform == "win32" else "piper"
        )
        if local_piper.is_file():
            executable = str(local_piper)
    if not executable:
        raise RuntimeError("Piper executable not found on PATH or in .venv. Install Piper separately.")

    voice_model = voice_model.expanduser().resolve()
    if not voice_model.is_file():
        raise RuntimeError(f"Voice model file not found: {voice_model}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    rate = float(prosody.get("rate", 1.0))
    if not 0.5 <= rate <= 2.0:
        raise RuntimeError("Prosody rate must be between 0.5 and 2.0.")
    duration_plan = None
    if float(prosody.get("target_duration_sec") or 0) > 0:
        duration_plan = plan_speech_rate(text, float(prosody["target_duration_sec"]), rate)
        rate = max(.5, min(2.0, duration_plan["rate"]))

    # Piper length_scale is inverse to speaking rate
    length_scale = 1.0 / rate

    command = [
        executable,
        "--model", str(voice_model),
        "--output_file", str(output_path),
        "--length_scale", f"{length_scale:.4f}",
    ]
    if speaker_id is not None:
        command += ["--speaker", str(int(speaker_id))]

    # Check for theatrical cadence request
    theatrical_requested = bool(
        prosody.get("theatrical_shaping")
        or prosody.get("theatrical")
        or prosody.get("style")
    )
    synth_text = text
    resolved_style = "default"
    if theatrical_requested:
        synth_text, resolved_style, _ = shape_conversational_cadence(
            text,
            requested_style=prosody.get("style", ""),
            prosody=prosody,
        )

    piper_env = os.environ.copy()
    piper_env["PYTHONIOENCODING"] = "utf-8"
    piper_env["PYTHONUTF8"] = "1"

    result = subprocess.run(
        command,
        input=synth_text,
        text=True,
        encoding="utf-8",
        env=piper_env,
        capture_output=True,
        timeout=300,
    )
    if result.returncode or not output_path.exists():
        raise RuntimeError((result.stderr or "Piper synthesis failed")[-2000:])

    # Post-processing prosody shaping if theatrical style or pitch was explicitly requested
    if theatrical_requested or prosody.get("pitch_semitones"):
        pitch_semitones = float(prosody.get("pitch_semitones") or prosody.get("pitch") or 0.0)
        volume_db = float(prosody.get("volume_db") or prosody.get("volume") or 0.0)
        apply_audio_prosody_shaping(
            output_path,
            style_key=resolved_style,
            pitch_semitones=pitch_semitones,
            volume_db=volume_db,
        )

    unsupported = [
        key for key in ("emotion", "delivery", "pitch", "volume")
        if prosody.get(key) not in (None, "")
    ]
    prosody_applied: dict[str, Any] = {
        "rate": rate,
        "piper_length_scale": round(length_scale, 4),
        "duration_plan": duration_plan,
    }
    if theatrical_requested:
        prosody_applied["theatrical_style"] = resolved_style
        prosody_applied["cadence_shaped"] = synth_text != text

    return {
        "file": str(output_path),
        "size_bytes": output_path.stat().st_size,
        "engine": "Piper",
        "voice_model": voice_model.name,
        "prosody_applied": prosody_applied,
        "prosody_unsupported": unsupported,
        "prosody_status": "partial" if unsupported else "applied",
    }
