"""OmniVoice & Zero-Shot Voice Cloning Architect for OpenDub Studio.

Integrates with k2-fsa/OmniVoice for zero-shot voice cloning with reference audio + reference text,
and natural language voice design (instruct prompt).
Genuine cloned speech runs in an isolated worker. Missing models fail explicitly;
stock speech and synthetic tones are never reported as successful clones.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import importlib
import importlib.util
import json
import logging
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time
from typing import Any
import uuid
import wave

from .voice_profiles import (
    DEFAULT_VOICE_PROFILES,
    THEATRICAL_AVENGERS_PROFILES,
    VOICE_PROFILE_SCHEMA_VERSION,
    VoiceProfile,
    normalize_voice_profile,
    select_demographic_voice_profile,
)

logger = logging.getLogger("opendub.voice_cloning")

# Pre-bundled Theatrical Avengers-Grade Hindi Voice Profiles metadata
AVENGERS_DESCRIPTORS: dict[str, dict[str, Any]] = {
    "hi_avengers_hero_male": {
        "character_name": "Tony Stark / Jin Isoo style",
        "description": "Deep, confident, charismatic heroic tone",
        "gender": "male",
        "age_group": "adult",
        "style_tags": ["heroic", "charismatic", "deep", "confident", "theatrical"],
        "instruct_prompt": (
            "Deep, confident, charismatic heroic male voice with theatrical energy, "
            "rich lower mids, commanding presence and clear Hindi articulation."
        ),
        "target_f0_hz": 125.0,
        "base_neural_voice": "hi-IN-MadhurNeural",
        "pitch_semitones": -0.8,
        "default_rate": 1.02,
    },
    "hi_avengers_lead_female": {
        "character_name": "Black Widow / Detective Ganghyun style",
        "description": "Sharp, commanding, emotive female lead",
        "gender": "female",
        "age_group": "adult",
        "style_tags": ["commanding", "sharp", "emotive", "tactical", "theatrical"],
        "instruct_prompt": (
            "Sharp, commanding, emotive theatrical female lead with crisp diction, "
            "tactical intensity, and authoritative poise."
        ),
        "target_f0_hz": 210.0,
        "base_neural_voice": "hi-IN-SwaraNeural",
        "pitch_semitones": 0.0,
        "default_rate": 1.02,
    },
    "hi_avengers_elder_chief": {
        "character_name": "Nick Fury / Chairman Jin style",
        "description": "Heavy authoritative, deep chest resonance",
        "gender": "male",
        "age_group": "elderly",
        "style_tags": ["authoritative", "deep_resonance", "heavy", "veteran", "theatrical"],
        "instruct_prompt": (
            "Heavy authoritative elder leader voice, deep chest resonance, "
            "gravitas, measured veteran cadence."
        ),
        "target_f0_hz": 95.0,
        "base_neural_voice": "de-DE-FlorianMultilingualNeural",
        "pitch_semitones": -3.5,
        "default_rate": 0.90,
    },
    "hi_avengers_senior_cop": {
        "character_name": "Hawkeye / Junyoung style",
        "description": "Grounded, gritty, experienced baritone detective",
        "gender": "male",
        "age_group": "middle_aged",
        "style_tags": ["grounded", "gritty", "baritone", "detective", "theatrical"],
        "instruct_prompt": (
            "Grounded, gritty, battle-tested baritone male voice, firm and dry delivery "
            "with cinematic realism."
        ),
        "target_f0_hz": 118.0,
        "base_neural_voice": "mr-IN-ManoharNeural",
        "pitch_semitones": -1.5,
        "default_rate": 0.97,
    },
    "hi_avengers_young_hero": {
        "character_name": "Spider-Man / Kyungjin style",
        "description": "Youthful, energetic, spirited young boy/cop",
        "gender": "male",
        "age_group": "young",
        "style_tags": ["youthful", "energetic", "spirited", "fast", "theatrical"],
        "instruct_prompt": (
            "Youthful, spirited, agile heroic young male voice with bright pacing, "
            "expressive warmth, and spirited courage."
        ),
        "target_f0_hz": 170.0,
        "base_neural_voice": "ne-NP-SagarNeural",
        "pitch_semitones": 1.6,
        "default_rate": 1.08,
    },
    "hi_avengers_villain": {
        "character_name": "Thanos / Criminal Byungsoo style",
        "description": "Dark, raspy, intense villainous tone",
        "gender": "male",
        "age_group": "middle_aged",
        "style_tags": ["villain", "dark", "raspy", "intense", "theatrical"],
        "instruct_prompt": (
            "Dark, menacing, raspy theatrical villain voice, brooding cadence, "
            "low rumble, formidable vocal weight."
        ),
        "target_f0_hz": 105.0,
        "base_neural_voice": "ko-KR-HyunsuMultilingualNeural",
        "pitch_semitones": -2.8,
        "default_rate": 0.92,
    },
    "hi_avengers_mother_matron": {
        "character_name": "Warm Maternal Matron",
        "description": "Warm, emotional maternal tone",
        "gender": "female",
        "age_group": "middle_aged",
        "style_tags": ["warm", "emotional", "maternal", "caring", "theatrical"],
        "instruct_prompt": (
            "Warm, deeply emotional, protective maternal female voice with gentle resonant "
            "timbre and compassionate inflection."
        ),
        "target_f0_hz": 195.0,
        "base_neural_voice": "mr-IN-AarohiNeural",
        "pitch_semitones": -1.2,
        "default_rate": 0.95,
    },
    "hi_avengers_young_actress": {
        "character_name": "Young Actress Lead",
        "description": "Bright, expressive young woman",
        "gender": "female",
        "age_group": "young",
        "style_tags": ["bright", "expressive", "lively", "charm", "theatrical"],
        "instruct_prompt": (
            "Bright, expressive, modern young woman voice with crisp articulation, "
            "vibrant melodic flow, and cinematic charm."
        ),
        "target_f0_hz": 235.0,
        "base_neural_voice": "ne-NP-HemkalaNeural",
        "pitch_semitones": 1.4,
        "default_rate": 1.05,
    },
}


@dataclass
class VocalTimbreProfile:
    """Acoustic timbre representation extracted from reference audio for voice cloning & matching."""
    character_id: str
    pitch_f0_hz: float | None = None
    pitch_semitones: float = 0.0
    tempo_rate: float = 1.0
    gender: str = "male"
    age_group: str = "adult"
    style_tags: list[str] = field(default_factory=list)
    energy_db: float | None = None
    spectral_centroid_hz: float | None = None
    matched_base_profile: str = "hi_avengers_hero_male"

    def to_dict(self) -> dict[str, Any]:
        return {
            "character_id": self.character_id,
            "pitch_f0_hz": self.pitch_f0_hz,
            "pitch_semitones": self.pitch_semitones,
            "tempo_rate": self.tempo_rate,
            "gender": self.gender,
            "age_group": self.age_group,
            "style_tags": list(self.style_tags),
            "energy_db": self.energy_db,
            "spectral_centroid_hz": self.spectral_centroid_hz,
            "matched_base_profile": self.matched_base_profile,
        }


def analyze_vocal_timbre(
    audio_path: str | Path,
    character_id: str = "unknown",
    fallback_gender: str = "male",
    fallback_age: str = "adult",
) -> VocalTimbreProfile:
    """Inspect and extract fundamental acoustic timbre parameters from a reference audio snippet.

    Uses autocorrelation pitch estimation and RMS energy calculation with zero external C-dependencies.
    """
    path = Path(audio_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Reference audio file not found for timbre analysis: {path}")

    f0_hz: float | None = None
    energy_db: float | None = None
    gender = fallback_gender
    age_group = fallback_age
    style_tags: list[str] = []
    pitch_semitones = 0.0
    tempo_rate = 1.0

    try:
        with wave.open(str(path), "rb") as wf:
            channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            n_frames = min(wf.getnframes(), framerate * 10)  # Analyze first 10 seconds

            if sampwidth == 2 and framerate > 0 and n_frames > 0:
                raw_bytes = wf.readframes(n_frames)
                total_samples = len(raw_bytes) // 2
                max_samples = min(total_samples, 120000)
                int_samples = struct.unpack(f"<{max_samples}h", raw_bytes[: max_samples * 2])

                # Downmix stereo to mono if needed
                if channels > 1:
                    mono_samples = int_samples[::channels]
                else:
                    mono_samples = int_samples

                if mono_samples:
                    # 1. Energy Calculation (RMS)
                    sum_sq = sum(s * s for s in mono_samples)
                    rms = math.sqrt(sum_sq / len(mono_samples))
                    energy_db = round(20 * math.log10(max(1.0, rms)), 1)

                    # 2. Normalized Autocorrelation Pitch Estimation
                    min_lag = max(1, framerate // 450)  # ~450 Hz upper human limit
                    max_lag = min(len(mono_samples) // 2, framerate // 60)  # ~60 Hz lower limit

                    window_size = min(2048, len(mono_samples) - max_lag)
                    if window_size > 512 and max_lag > min_lag:
                        ref_win = mono_samples[:window_size]
                        ref_energy = math.sqrt(sum(s * s for s in ref_win))
                        best_corr = -1.0
                        best_lag = 0

                        if ref_energy > 50.0:  # Valid speech presence
                            for lag in range(min_lag, max_lag):
                                comp_win = mono_samples[lag : lag + window_size]
                                comp_energy = math.sqrt(sum(s * s for s in comp_win))
                                if comp_energy > 0:
                                    dot = sum(a * b for a, b in zip(ref_win, comp_win))
                                    norm_corr = dot / (ref_energy * comp_energy)
                                    if norm_corr > best_corr:
                                        best_corr = norm_corr
                                        best_lag = lag

                            if best_corr > 0.32 and best_lag > 0:
                                f0_hz = round(float(framerate) / float(best_lag), 1)
    except Exception as exc:
        logger.debug("Wave timbre inspection fell back to defaults: %s", exc)

    # Classify gender, age, and relative pitch offset from detected F0
    if f0_hz is not None and f0_hz > 50.0:
        if f0_hz > 175.0:
            gender = "female"
            ref_f0 = 210.0
            if f0_hz > 240.0:
                age_group = "young"
                style_tags.extend(["bright", "youthful", "clear"])
            elif f0_hz < 185.0:
                age_group = "middle_aged"
                style_tags.extend(["warm", "maternal", "grounded"])
            else:
                age_group = "adult"
                style_tags.extend(["commanding", "sharp", "theatrical"])
        else:
            gender = "male"
            ref_f0 = 125.0
            if f0_hz < 110.0:
                age_group = "elderly"
                style_tags.extend(["deep", "heavy", "resonant", "authoritative"])
            elif f0_hz < 145.0:
                age_group = "middle_aged"
                style_tags.extend(["baritone", "gritty", "experienced"])
            elif f0_hz > 170.0:
                age_group = "young"
                style_tags.extend(["youthful", "energetic", "spirited"])
            else:
                age_group = "adult"
                style_tags.extend(["charismatic", "heroic", "confident"])

        # Compute pitch shift in semitones relative to neutral reference
        ratio = max(0.5, min(2.0, f0_hz / ref_f0))
        pitch_semitones = round(12.0 * math.log2(ratio), 1)
        pitch_semitones = max(-6.0, min(6.0, pitch_semitones))
    else:
        # Defaults based on fallback inputs
        ref_f0 = 210.0 if fallback_gender == "female" else 125.0
        gender = fallback_gender
        age_group = fallback_age
        style_tags.extend(["theatrical", "balanced", "cinematic"])

    # Match the best base neural theatrical profile
    matched_profile = select_demographic_voice_profile(
        gender=gender,
        age_group=age_group,
        f0_hz=f0_hz,
        style_preference="theatrical",
    )

    return VocalTimbreProfile(
        character_id=character_id,
        pitch_f0_hz=f0_hz,
        pitch_semitones=pitch_semitones,
        tempo_rate=tempo_rate,
        gender=gender,
        age_group=age_group,
        style_tags=style_tags,
        energy_db=energy_db,
        spectral_centroid_hz=round(f0_hz * 2.8, 1) if f0_hz else None,
        matched_base_profile=matched_profile.profile_id,
    )


class VoiceCloneRegistry:
    """Manages character voice clones and reference audio snippets per project.

    Stores reference audio files at: projects/{project_id}/voice_clones/{char_id}.wav
    Stores clone profile metadata at: projects/{project_id}/voice_clones/{char_id}.json
    """

    def __init__(self, data_root: str | Path | None = None) -> None:
        if data_root is not None:
            self.data_root = Path(data_root).resolve()
        else:
            env_dir = os.getenv("OPENDUB_DATA_DIR", "runtime")
            root = Path(__file__).resolve().parents[1]
            self.data_root = (root / env_dir).resolve()
        self.projects_dir = self.data_root / "projects"

    def get_clone_dir(self, project_id: str) -> Path:
        """Return the directory dedicated to voice clones for this project."""
        folder = self.projects_dir / project_id / "voice_clones"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def get_reference_audio_path(self, project_id: str, character_id: str) -> Path:
        """Return canonical snippet path: projects/{id}/voice_clones/{char_id}.wav."""
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in character_id)
        return self.get_clone_dir(project_id) / f"{safe_id}.wav"

    def get_clone_profile_path(self, project_id: str, character_id: str) -> Path:
        """Return canonical metadata path for the cloned voice profile."""
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in character_id)
        return self.get_clone_dir(project_id) / f"{safe_id}.json"

    def save_clone(
        self,
        project_id: str,
        character_id: str,
        audio_path: str | Path,
        ref_text: str = "",
        style_prompt: str = "",
        timbre_data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Save reference audio snippet and persistent cloned voice profile."""
        src = Path(audio_path).resolve()
        if not src.is_file():
            raise FileNotFoundError(f"Reference audio snippet does not exist: {src}")

        dest_audio = self.get_reference_audio_path(project_id, character_id)
        if src != dest_audio:
            shutil.copyfile(src, dest_audio)

        if timbre_data is None:
            timbre = analyze_vocal_timbre(dest_audio, character_id=character_id)
            timbre_dict = timbre.to_dict()
        else:
            timbre_dict = dict(timbre_data)

        # Assemble full persistent profile
        gender = timbre_dict.get("gender", "male")
        age_group = timbre_dict.get("age_group", "adult")
        matched_base = timbre_dict.get("matched_base_profile", "hi_avengers_hero_male")
        pitch_semitones = timbre_dict.get("pitch_semitones", 0.0)
        rate = timbre_dict.get("tempo_rate", 1.0)

        profile_record: dict[str, Any] = {
            "schema_version": VOICE_PROFILE_SCHEMA_VERSION,
            "character_id": character_id,
            "project_id": project_id,
            "status": "configured",
            "provider": "omnivoice",
            "voice_id": f"clone_{character_id}",
            "language": "hi",
            "gender": gender,
            "style": style_prompt or f"cloned_{character_id}",
            "ref_audio_path": str(dest_audio),
            "ref_text": ref_text,
            "style_prompt": style_prompt,
            "timbre": timbre_dict,
            "settings": {
                "character_id": character_id,
                "project_id": project_id,
                "ref_audio_path": str(dest_audio),
                "ref_text": ref_text,
                "instruct_prompt": style_prompt,
                "rate": rate,
                "pitch_semitones": pitch_semitones,
                "age_group": age_group,
                "timbre_tags": timbre_dict.get("style_tags", []),
                "base_voice_id": matched_base,
                "model": "k2-fsa/OmniVoice",
                "description": f"Zero-shot cloned voice for {character_id} (matched to {matched_base})",
            },
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
        }

        # Atomically write profile JSON
        profile_path = self.get_clone_profile_path(project_id, character_id)
        temp_path = profile_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(profile_record, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(profile_path)

        return profile_record

    def load_clone(self, project_id: str, character_id: str) -> dict[str, Any] | None:
        """Load an existing character voice clone profile."""
        profile_path = self.get_clone_profile_path(project_id, character_id)
        if not profile_path.is_file():
            # Check alternative naming
            alt = profile_path.with_name(f"{profile_path.stem}_profile.json")
            if alt.is_file():
                profile_path = alt
            else:
                return None

        try:
            data = json.loads(profile_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                # Ensure snippet path remains valid
                audio_path = self.get_reference_audio_path(project_id, character_id)
                if audio_path.is_file():
                    data["ref_audio_path"] = str(audio_path)
                return data
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to parse clone profile %s: %s", profile_path, exc)
        return None

    def list_clones(self, project_id: str) -> list[dict[str, Any]]:
        """List all cloned voice profiles available in the project."""
        clone_dir = self.get_clone_dir(project_id)
        results: list[dict[str, Any]] = []
        for file in sorted(clone_dir.glob("*.json")):
            if file.name.endswith(".tmp") or file.name == "clones_index.json":
                continue
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("character_id"):
                    results.append(data)
            except Exception:
                continue
        return results

    def get_default_bank_dir(self) -> Path:
        """Return the directory dedicated to default global voice clones across all projects."""
        folder = self.data_root / "default_voice_bank"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def save_default_voice(
        self,
        character_role: str,
        audio_path: str | Path,
        ref_text: str = "",
        character_name: str = "",
        style_prompt: str = "",
        timbre_data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Save a reference vocal snippet to the global Default Voice Bank."""
        src = Path(audio_path).resolve()
        if not src.is_file():
            raise FileNotFoundError(f"Reference audio snippet does not exist: {src}")

        bank_dir = self.get_default_bank_dir()
        safe_key = "".join(c if c.isalnum() or c in "-_" else "_" for c in character_role).lower()
        dest_audio = bank_dir / f"{safe_key}.wav"
        if src != dest_audio:
            shutil.copyfile(src, dest_audio)

        if timbre_data is None:
            timbre = analyze_vocal_timbre(dest_audio, character_id=character_role)
            timbre_dict = timbre.to_dict()
        else:
            timbre_dict = dict(timbre_data)

        meta = dict(metadata or {})
        if character_name:
            meta["character_name"] = character_name

        record: dict[str, Any] = {
            "schema_version": VOICE_PROFILE_SCHEMA_VERSION,
            "character_role": character_role,
            "character_name": character_name or character_role,
            "status": "configured",
            "provider": "omnivoice",
            "voice_id": f"default_bank_{safe_key}",
            "language": "hi",
            "gender": timbre_dict.get("gender", "male"),
            "age_group": timbre_dict.get("age_group", "adult"),
            "style_prompt": style_prompt,
            "ref_audio_path": str(dest_audio),
            "ref_text": ref_text,
            "timbre": timbre_dict,
            "settings": {
                "character_role": character_role,
                "character_name": character_name or character_role,
                "ref_audio_path": str(dest_audio),
                "ref_text": ref_text,
                "instruct_prompt": style_prompt,
                "rate": timbre_dict.get("tempo_rate", 1.0),
                "pitch_semitones": timbre_dict.get("pitch_semitones", 0.0),
                "timbre_tags": timbre_dict.get("style_tags", []),
                "base_voice_id": timbre_dict.get("matched_base_profile", "hi_avengers_hero_male"),
                "model": "k2-fsa/OmniVoice",
            },
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": meta,
        }

        profile_path = bank_dir / f"{safe_key}.json"
        temp_path = profile_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(profile_path)
        return record

    def list_default_voices(self) -> list[dict[str, Any]]:
        """List all voices registered in the global Default Voice Bank."""
        bank_dir = self.get_default_bank_dir()
        results: list[dict[str, Any]] = []
        for file in sorted(bank_dir.glob("*.json")):
            if file.name.endswith(".tmp"):
                continue
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                if isinstance(data, dict) and (data.get("character_role") or data.get("voice_id")):
                    results.append(data)
            except Exception:
                continue
        return results

    def get_default_voice(self, character_role: str) -> dict[str, Any] | None:
        """Lookup a cloned default voice by role or key."""
        safe_key = "".join(c if c.isalnum() or c in "-_" else "_" for c in character_role).lower()
        bank_dir = self.get_default_bank_dir()
        profile_path = bank_dir / f"{safe_key}.json"
        if not profile_path.is_file():
            return None
        try:
            data = json.loads(profile_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                audio_path = bank_dir / f"{safe_key}.wav"
                if audio_path.is_file():
                    data["ref_audio_path"] = str(audio_path)
                return data
        except Exception:
            pass
        return None

    def delete_clone(self, project_id: str, character_id: str) -> bool:
        """Delete cloned voice audio snippet and metadata for a character."""
        audio = self.get_reference_audio_path(project_id, character_id)
        profile = self.get_clone_profile_path(project_id, character_id)
        deleted = False
        if audio.is_file():
            audio.unlink(missing_ok=True)
            deleted = True
        if profile.is_file():
            profile.unlink(missing_ok=True)
            deleted = True
        return deleted


def probe_audio_duration(file_path: Path | str) -> float:
    """Measure duration of a WAV or audio file in seconds."""
    path = Path(file_path)
    if not path.is_file():
        return 0.0

    try:
        with wave.open(str(path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            if rate > 0:
                return round(frames / float(rate), 3)
    except Exception:
        pass

    executable = shutil.which("ffprobe")
    if executable:
        try:
            cmd = [executable, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                data = json.loads(res.stdout or "{}")
                dur = float((data.get("format") or {}).get("duration", 0.0))
                if dur > 0:
                    return round(dur, 3)
        except Exception:
            pass

    return 0.0


def write_synthetic_wav(
    output_path: Path,
    duration_sec: float = 1.0,
    sample_rate: int = 24000,
    f0_hz: float = 130.0,
) -> None:
    """Generate a clean, high-fidelity PCM WAV file with natural vocal harmonic envelope.

    Ensures zero failures and 100% resilient testing when offline or external TTS binaries are missing.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    num_samples = max(2400, int(duration_sec * sample_rate))
    samples: list[int] = []

    for i in range(num_samples):
        t = i / sample_rate
        # Vocal envelope: smooth attack & release
        env = min(1.0, t / 0.04) if t < 0.04 else min(1.0, (duration_sec - t) / 0.04) if t > duration_sec - 0.04 else 1.0
        # Formant-like harmonic structure
        val = (
            0.55 * math.sin(2 * math.pi * f0_hz * t)
            + 0.28 * math.sin(2 * math.pi * (f0_hz * 2) * t)
            + 0.12 * math.sin(2 * math.pi * (f0_hz * 3) * t)
        )
        sample_int = int(max(-32767, min(32767, val * env * 18000)))
        samples.append(sample_int)

    raw_data = struct.pack(f"<{len(samples)}h", *samples)
    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(raw_data)


class OmniVoiceCloner:
    """OmniVoice zero-shot voice cloner & theatrical voice synthesis manager.

    Integrates with `k2-fsa/OmniVoice` supporting:
    - Zero-shot voice cloning with `ref_audio` + `ref_text`
    - Natural language voice design with `instruct` prompts
    - Robust fallback to high-fidelity neural voice cloning & timbre-matching when GPU or model weights are loading.
    """

    def __init__(
        self,
        project_id: str = "default",
        registry: VoiceCloneRegistry | None = None,
        model_id: str = "k2-fsa/OmniVoice",
        device: str = "auto",
    ) -> None:
        self.project_id = project_id
        self.registry = registry or VoiceCloneRegistry()
        self.data_root = self.registry.data_root
        self.model_id = model_id
        self.device = device
        self._model: Any = None
        self._is_loading = False
        self._load_error: str | None = None
        self._init_omnivoice()

    def _init_omnivoice(self) -> None:
        """Heavy models load only inside the isolated worker at synthesis time."""
        from .clone_runtime import runtime_status
        status = runtime_status()
        self._load_error = None if status["environment_available"] else "Isolated clone runtime is not installed."

    @property
    def is_model_available(self) -> bool:
        """Check whether the OmniVoice zero-shot neural model is actively loaded."""
        return self._model is not None

    def clone_character_voice(
        self,
        character_id: str,
        ref_audio_path: str | Path,
        ref_text: str = "",
        style_prompt: str = "",
        project_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create a persistent cloned voice profile from reference audio snippet.

        Analyzes vocal timbre (F0, pitch, rate, energy, style tags) and registers the clone
        in projects/{id}/voice_clones/{char_id}.wav.
        """
        pid = project_id or self.project_id
        src_path = Path(ref_audio_path).resolve()
        if not src_path.is_file():
            raise FileNotFoundError(f"Reference audio snippet for character '{character_id}' does not exist: {src_path}")

        # 1. Acoustic timbre analysis
        timbre = analyze_vocal_timbre(
            audio_path=src_path,
            character_id=character_id,
            fallback_gender=kwargs.get("gender", "male"),
            fallback_age=kwargs.get("age_group", "adult"),
        )

        # 2. Persist in project voice clone registry
        saved_record = self.registry.save_clone(
            project_id=pid,
            character_id=character_id,
            audio_path=src_path,
            ref_text=ref_text,
            style_prompt=style_prompt,
            timbre_data=timbre.to_dict(),
            metadata=kwargs,
        )

        # 3. Build normalized VoiceProfile representation
        vp_dict = {
            "schema_version": VOICE_PROFILE_SCHEMA_VERSION,
            "status": "configured",
            "provider": "omnivoice" if self.is_model_available else "cloned",
            "voice_id": f"clone_{character_id}",
            "language": "hi",
            "gender": timbre.gender,
            "style": style_prompt or f"cloned_{character_id}",
            "settings": {
                "character_id": character_id,
                "project_id": pid,
                "ref_audio_path": saved_record["ref_audio_path"],
                "ref_text": ref_text,
                "instruct_prompt": style_prompt,
                "rate": timbre.tempo_rate,
                "pitch_semitones": timbre.pitch_semitones,
                "age_group": timbre.age_group,
                "timbre_tags": timbre.style_tags,
                "base_voice_id": timbre.matched_base_profile,
                "model": self.model_id,
                "description": f"Zero-shot cloned voice for {character_id} (timbre: {timbre.matched_base_profile})",
            },
        }

        saved_record["voice_profile"] = normalize_voice_profile(vp_dict)
        return saved_record

    def synthesize_cloned_voice(
        self, text_hindi: str, character_id: str, output_path: str | Path,
        prosody: dict[str, Any] | None = None, project_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate a real reference-conditioned clone or fail without replacing audio."""
        from .clone_runtime import synthesize_reference
        pid = project_id or self.project_id
        record = self.registry.load_clone(pid, character_id) or self.registry.get_default_voice(character_id)
        reference = kwargs.get("reference_audio") or (record or {}).get("ref_audio_path")
        transcript = kwargs.get("ref_text") or (record or {}).get("ref_text")
        if not reference or not transcript:
            raise RuntimeError("Cloning requires reviewed reference speech and its exact transcript; stock presets are not clones.")
        return synthesize_reference(text_hindi, Path(reference), transcript, Path(output_path), prosody)

    def _synthesize_neural_fallback(
        self,
        text: str,
        output_path: Path,
        voice_id: str,
        rate: float,
        pitch_semitones: float,
        gender: str,
    ) -> bool:
        """Robust high-fidelity neural voice synthesis fallback with timbre matching."""
        # 1. Attempt Edge-TTS (high quality neural voice with pitch/rate shaping)
        rate_pct = int(round((rate - 1.0) * 100))
        rate_str = f"{rate_pct:+d}%"
        pitch_hz = int(round(pitch_semitones * 8))
        pitch_str = f"{pitch_hz:+d}Hz"

        # Check edge_tts Python library
        try:
            import edge_tts
            communicate = edge_tts.Communicate(text, voice_id, rate=rate_str, pitch=pitch_str)
            try:
                # Try event loop if already running
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(asyncio.run, communicate.save(str(output_path)))
                        future.result(timeout=25)
                else:
                    loop.run_until_complete(communicate.save(str(output_path)))
            except RuntimeError:
                asyncio.run(communicate.save(str(output_path)))

            if output_path.is_file() and output_path.stat().st_size > 200:
                return True
        except Exception as exc:
            logger.debug("Edge-TTS Python module fallback: %s", exc)

        # Check edge-tts CLI tool
        edge_bin = shutil.which("edge-tts")
        if edge_bin:
            try:
                cmd = [
                    edge_bin,
                    "--voice", voice_id,
                    "--text", text,
                    "--write-media", str(output_path),
                    f"--rate={rate_str}",
                    f"--pitch={pitch_str}",
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if res.returncode == 0 and output_path.is_file() and output_path.stat().st_size > 200:
                    return True
            except Exception as exc:
                logger.debug("Edge-TTS CLI tool execution note: %s", exc)

        # 2. Attempt Piper neural TTS fallback if available
        piper_bin = shutil.which("piper")
        if piper_bin:
            models_dir = self.data_root / "models" / "piper"
            available = sorted(models_dir.glob("*.onnx")) if models_dir.is_dir() else []
            if available:
                try:
                    from .dubbing import synthesize_piper_segment
                    res = synthesize_piper_segment(
                        text=text,
                        output_path=output_path,
                        voice_model=available[0],
                        prosody={"rate": rate},
                    )
                    if output_path.is_file() and output_path.stat().st_size > 200:
                        return True
                except Exception as exc:
                    logger.debug("Piper fallback execution note: %s", exc)

        # 3. Pure-Python Synthetic Harmonic Envelope Fallback
        # Guarantees valid, playable PCM WAV audio file with duration aligned to text length
        estimated_duration = max(0.5, round(len(text) * 0.08 / rate, 2))
        base_f0 = 210.0 if gender == "female" else 125.0
        applied_f0 = base_f0 * (2.0 ** (pitch_semitones / 12.0))
        raise RuntimeError("Speech provider unavailable; synthetic tones must never replace speech.")


# Default cloner factory
_GLOBAL_CLONER: OmniVoiceCloner | None = None


def get_cloner(project_id: str = "default") -> OmniVoiceCloner:
    """Return an OmniVoiceCloner instance configured for the specified project."""
    global _GLOBAL_CLONER
    if _GLOBAL_CLONER is None or _GLOBAL_CLONER.project_id != project_id:
        _GLOBAL_CLONER = OmniVoiceCloner(project_id=project_id)
    return _GLOBAL_CLONER


def get_movie_cast_voice_bank() -> list[dict[str, Any]]:
    """Return catalog references; purity and audible identity require an audit."""
    root = Path(__file__).resolve().parents[1]
    bank_dir = root / "storage" / "default_voice_bank" / "candidate_voices"
    data_root = root / os.getenv("OPENDUB_DATA_DIR", "runtime")
    from .voice_catalog import public_voice_name, reference_blockers
    summary_file = bank_dir / "all_extracted_characters_summary.json"
    if summary_file.is_file():
        try:
            with open(summary_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                from .voice_bank_quality import reviewed_eligibility, fingerprint
                rows = []
                for original in data.get("characters", []):
                    row = dict(original)
                    report_path = data_root / "voice-bank-audit/records" / f"{row['character_id']}.json"
                    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
                    row["display_name"] = public_voice_name(row["character_id"])
                    row["selection_blockers"] = reference_blockers(report)
                    row["audit"] = report.get("audit", {"status": "not_audited"})
                    row["sample_available"] = Path(report.get("reference_path") or bank_dir / (row["character_id"] + ".wav")).is_file()
                    row["reference_path"] = report.get("reference_path")
                    row["duration_sec"] = report.get("metrics", {}).get("duration_sec", row.get("duration_sec"))
                    row["review"] = report.get("review", {})
                    row["clone"] = report.get("clone", {"status": "not_tested"})
                    acceptance = report.get("audition_acceptance", {})
                    accepted_output = Path(row["clone"].get("file", ""))
                    row["audition_accepted"] = (acceptance.get("status") == "user_accepted" and
                                                 acceptance.get("output_sha256") == row["clone"].get("output_sha256") and
                                                 accepted_output.is_file() and fingerprint(accepted_output) == acceptance.get("output_sha256"))
                    row["perceived_voice"] = report.get("perceived_voice", {"type": "unknown", "age_band": "unknown"})
                    row["source_audio_url"] = f"/api/voices/{row['character_id']}/source-preview" if report.get("source") else None
                    row["repairs"] = []
                    repair_folder = data_root / "voice-bank-audit/repairs" / row["character_id"]
                    for version in sorted(repair_folder.glob("*/repair.json")):
                        repair_report = json.loads(version.read_text(encoding="utf-8"))
                        if repair_report.get("original_sha256") != report.get("catalog_reference_sha256",report.get("sha256")):
                            continue
                        for index, candidate in enumerate(repair_report.get("repairs", [])):
                            item = dict(candidate)
                            item.update(version=version.parent.name, index=index)
                            if item.get("path"):
                                item["audio_url"] = f"/api/voices/{row['character_id']}/repair-preview/{version.parent.name}/{index}"
                            if item.get("clone",{}).get("status") == "completed":
                                item["clone_audio_url"] = f"/api/voices/{row['character_id']}/repair-clone-preview/{version.parent.name}/{index}"
                            row["repairs"].append(item)
                    row["eligible_for_defaults"] = reviewed_eligibility(report)[0]
                    rows.append(row)
                from .authorized_voices import load_authorized_voices
                return rows + load_authorized_voices(data_root)
        except Exception as exc:
            logger.warning("Error reading voice bank summary: %s", exc)

    # Fallback to scanning individual json files
    voices = []
    if bank_dir.is_dir():
        for jf in sorted(bank_dir.glob("char_*.json")):
            try:
                with open(jf, "r", encoding="utf-8") as f:
                    voices.append(json.load(f))
            except Exception:
                pass
    voices.sort(key=lambda x: x.get("character_index", 0))
    from .authorized_voices import load_authorized_voices
    return voices + load_authorized_voices(data_root)


def assign_movie_cast_voices(
    characters: list[dict[str, Any]],
    manual_overrides: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Dynamically & adaptively assign movie cast voices to characters.

    If video has 2, 5, 8, or 15 characters, this algorithm:
      1. Respects any user manual overrides first.
      2. Matches demographic gender (male/female).
      3. Matches age group (elderly, adult, young_adult).
      4. Matches F0 pitch proximity.
      5. Guarantees distinct voices across characters to prevent confusion.
    """
    bank = get_movie_cast_voice_bank()
    if not bank:
        return characters

    overrides = manual_overrides or {}
    bank_by_id = {v["character_id"]: v for v in bank}
    assigned_voice_ids: set[str] = set()

    result = []
    # First pass: Apply manual overrides
    for char in characters:
        cid = char.get("character_id") or char.get("source_speaker_id") or ""
        override = overrides.get(cid)
        assigned = None
        if override and isinstance(override, dict):
            vid = override.get("voice_id")
            if vid and vid in bank_by_id:
                v = dict(bank_by_id[vid])
                v["applied_rate"] = float(override.get("rate", 1.0))
                v["applied_pitch_semitones"] = float(override.get("pitch_semitones", 0.0))
                assigned = v
                assigned_voice_ids.add(vid)
        elif override and isinstance(override, str) and override in bank_by_id:
            assigned = dict(bank_by_id[override])
            assigned_voice_ids.add(override)

        char_copy = dict(char)
        if assigned:
            char_copy["assigned_voice"] = assigned
        result.append(char_copy)

    # Only reviewed defaults may be recommended automatically. Manual locks are separate.
    automatic_bank = [v for v in bank if v.get("eligible_for_defaults") is True]
    # Second pass: Adaptive matching for remaining unassigned characters
    for char_copy in result:
        if char_copy.get("assigned_voice"):
            continue

        if not automatic_bank:
            char_copy["voice_selection_status"] = "review_required"
            continue
        gender = str(char_copy.get("gender") or "unknown").lower().strip()
        if gender not in ("male", "female"):
            char_copy["voice_selection_status"] = "review_required"
            continue

        age = str(char_copy.get("age_group") or "adult").lower().strip()
        char_f0 = float(char_copy.get("pitch_f0_hz") or (210.0 if gender == "female" else 125.0))

        # Filter available voices by gender
        candidates = [v for v in automatic_bank if v.get("gender") == gender and v["character_id"] not in assigned_voice_ids]
        if not candidates:
            # Relax unique constraint if more characters than voices in that gender
            candidates = [v for v in automatic_bank if v.get("gender") == gender]
        if not candidates:
            char_copy["voice_selection_status"] = "review_required"
            continue

        # Score candidates by age match (weight 40) and pitch proximity (weight 60)
        def score_candidate(cand: dict[str, Any]) -> float:
            c_age = cand.get("age_group", "adult")
            age_penalty = 0.0 if c_age == age else 25.0
            cand_f0 = float(cand.get("pitch_f0_hz") or (210.0 if gender == "female" else 125.0))
            f0_dist = abs(cand_f0 - char_f0)
            return age_penalty + f0_dist

        best = min(candidates, key=score_candidate)
        assigned_voice_ids.add(best["character_id"])
        char_copy["assigned_voice"] = dict(best)

    return result
