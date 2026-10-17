"""Versioned, secret-free character voice profile validation for OpenDub Studio."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

VOICE_PROFILE_SCHEMA_VERSION = 1
SUPPORTED_PROVIDERS = {"piper", "edge-tts", "openai_compatible", "custom", "omnivoice", "cloned"}
_FORBIDDEN_KEYS = {
    "api_key", "apikey", "token", "access_token", "secret", "password",
    "authorization", "hf_token", "credential", "credentials",
}


from dataclasses import dataclass, asdict


@dataclass
class VoiceProfile:
    profile_id: str
    provider: str
    voice_id: str
    gender: str
    style: str
    language: str = "hi"
    default_rate: float = 1.0
    default_pitch_semitones: float = 0.0
    age_group: str = "adult"
    description: str = ""
    instruct_prompt: str = ""
    character_reference: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = {
            "schema_version": VOICE_PROFILE_SCHEMA_VERSION,
            "status": "configured",
            "provider": self.provider,
            "voice_id": self.voice_id,
            "language": self.language,
            "gender": self.gender,
            "style": self.style,
            "settings": {
                "rate": self.default_rate,
                "pitch_semitones": self.default_pitch_semitones,
                "age_group": self.age_group,
                "description": self.description,
            },
        }
        if self.instruct_prompt:
            data["settings"]["instruct_prompt"] = self.instruct_prompt
        if self.character_reference:
            data["settings"]["character_reference"] = self.character_reference
        return data


DEFAULT_VOICE_PROFILES: dict[str, VoiceProfile] = {
    # Baseline compatibility profiles
    "hi_male_1": VoiceProfile(
        profile_id="hi_male_1",
        provider="edge-tts",
        voice_id="hi-IN-MadhurNeural",
        gender="male",
        style="neutral",
        default_rate=1.0,
        default_pitch_semitones=0.0,
        age_group="adult",
        description="Standard Hindi male narrator",
    ),
    "hi_female_1": VoiceProfile(
        profile_id="hi_female_1",
        provider="edge-tts",
        voice_id="hi-IN-SwaraNeural",
        gender="female",
        style="neutral",
        default_rate=1.0,
        default_pitch_semitones=0.0,
        age_group="adult",
        description="Standard Hindi female narrator",
    ),
    # Multi-Character Age, Gender, and Personality Profiles
    "hi_hero_young_male": VoiceProfile(
        profile_id="hi_hero_young_male",
        provider="edge-tts",
        voice_id="hi-IN-MadhurNeural",
        gender="male",
        style="hero_playboy",
        default_rate=1.04,
        default_pitch_semitones=0.5,
        age_group="young_adult",
        description="Young adult male chaebol lead hero (playful, confident)",
    ),
    "hi_detective_female": VoiceProfile(
        profile_id="hi_detective_female",
        provider="edge-tts",
        voice_id="hi-IN-SwaraNeural",
        gender="female",
        style="female_detective",
        default_rate=1.02,
        default_pitch_semitones=0.0,
        age_group="adult",
        description="Adult female detective team leader (sharp, authoritative)",
    ),
    "hi_junior_boy_male": VoiceProfile(
        profile_id="hi_junior_boy_male",
        provider="edge-tts",
        voice_id="ne-NP-SagarNeural",
        gender="male",
        style="young_boy",
        default_rate=1.06,
        default_pitch_semitones=1.8,
        age_group="young",
        description="Energetic young junior detective / boyish voice",
    ),
    "hi_senior_cop_male": VoiceProfile(
        profile_id="hi_senior_cop_male",
        provider="edge-tts",
        voice_id="mr-IN-ManoharNeural",
        gender="male",
        style="senior_detective",
        default_rate=0.98,
        default_pitch_semitones=-1.2,
        age_group="middle_aged",
        description="Serious middle-aged senior detective",
    ),
    "hi_secretary_male": VoiceProfile(
        profile_id="hi_secretary_male",
        provider="edge-tts",
        voice_id="en-US-BrianMultilingualNeural",
        gender="male",
        style="polite_secretary",
        default_rate=0.99,
        default_pitch_semitones=-0.5,
        age_group="middle_aged",
        description="Polite composed corporate secretary / older brother",
    ),
    "hi_elderly_heavy_male": VoiceProfile(
        profile_id="hi_elderly_heavy_male",
        provider="edge-tts",
        voice_id="de-DE-FlorianMultilingualNeural",
        gender="male",
        style="elderly_heavy",
        default_rate=0.92,
        default_pitch_semitones=-3.0,
        age_group="elderly",
        description="Very heavy authoritative elderly chairman / patriarch",
    ),
    "hi_elderly_father_male": VoiceProfile(
        profile_id="hi_elderly_father_male",
        provider="edge-tts",
        voice_id="mr-IN-ManoharNeural",
        gender="male",
        style="elderly_father",
        default_rate=0.93,
        default_pitch_semitones=-2.5,
        age_group="elderly",
        description="Warm veteran elderly retired father",
    ),
    "hi_villain_male": VoiceProfile(
        profile_id="hi_villain_male",
        provider="edge-tts",
        voice_id="ko-KR-HyunsuMultilingualNeural",
        gender="male",
        style="villain_rough",
        default_rate=0.96,
        default_pitch_semitones=-2.0,
        age_group="middle_aged",
        description="Rough raspy male criminal / villain",
    ),
    "hi_reporter_male": VoiceProfile(
        profile_id="hi_reporter_male",
        provider="edge-tts",
        voice_id="fr-FR-RemyMultilingualNeural",
        gender="male",
        style="reporter_fast",
        default_rate=1.08,
        default_pitch_semitones=0.5,
        age_group="adult",
        description="Fast sharp male reporter / journalist",
    ),
    "hi_mother_middle_female": VoiceProfile(
        profile_id="hi_mother_middle_female",
        provider="edge-tts",
        voice_id="mr-IN-AarohiNeural",
        gender="female",
        style="mother_matron",
        default_rate=0.95,
        default_pitch_semitones=-1.5,
        age_group="middle_aged",
        description="Middle-aged mother / maternal figure",
    ),
    "hi_young_girl_female": VoiceProfile(
        profile_id="hi_young_girl_female",
        provider="edge-tts",
        voice_id="ne-NP-HemkalaNeural",
        gender="female",
        style="young_woman",
        default_rate=1.05,
        default_pitch_semitones=1.5,
        age_group="young",
        description="Bright young woman / actress / friend",
    ),
    "hi_child_voice": VoiceProfile(
        profile_id="hi_child_voice",
        provider="edge-tts",
        voice_id="en-US-AvaMultilingualNeural",
        gender="female",
        style="child",
        default_rate=1.06,
        default_pitch_semitones=3.0,
        age_group="child",
        description="Young child boy/girl",
    ),
    "hi_elderly_female": VoiceProfile(
        profile_id="hi_elderly_female",
        provider="edge-tts",
        voice_id="de-DE-SeraphinaMultilingualNeural",
        gender="female",
        style="elderly_female",
        default_rate=0.92,
        default_pitch_semitones=-2.0,
        age_group="elderly",
        description="Elderly grandmother / matron",
    ),
}

# Pre-bundled Theatrical Avengers-Grade Hindi Voice Profiles
THEATRICAL_AVENGERS_PROFILES: dict[str, VoiceProfile] = {
    "hi_avengers_hero_male": VoiceProfile(
        profile_id="hi_avengers_hero_male",
        provider="edge-tts",
        voice_id="hi-IN-MadhurNeural",
        gender="male",
        style="theatrical_hero",
        default_rate=1.02,
        default_pitch_semitones=-0.8,
        age_group="adult",
        description="Deep, confident, charismatic heroic tone (Tony Stark / Jin Isoo style)",
        instruct_prompt="Deep, confident, charismatic heroic male voice with theatrical energy, rich lower mids, commanding presence and clear Hindi articulation.",
        character_reference="Tony Stark / Jin Isoo",
    ),
    "hi_avengers_lead_female": VoiceProfile(
        profile_id="hi_avengers_lead_female",
        provider="edge-tts",
        voice_id="hi-IN-SwaraNeural",
        gender="female",
        style="theatrical_lead_female",
        default_rate=1.02,
        default_pitch_semitones=0.0,
        age_group="adult",
        description="Sharp, commanding, emotive female lead (Black Widow / Detective Ganghyun style)",
        instruct_prompt="Sharp, commanding, emotive theatrical female lead with crisp diction, tactical intensity, and authoritative poise.",
        character_reference="Black Widow / Detective Ganghyun",
    ),
    "hi_avengers_elder_chief": VoiceProfile(
        profile_id="hi_avengers_elder_chief",
        provider="edge-tts",
        voice_id="de-DE-FlorianMultilingualNeural",
        gender="male",
        style="theatrical_elder_chief",
        default_rate=0.90,
        default_pitch_semitones=-3.5,
        age_group="elderly",
        description="Heavy authoritative, deep chest resonance (Nick Fury / Chairman Jin style)",
        instruct_prompt="Heavy authoritative elder leader voice, deep chest resonance, gravitas, measured veteran cadence.",
        character_reference="Nick Fury / Chairman Jin",
    ),
    "hi_avengers_senior_cop": VoiceProfile(
        profile_id="hi_avengers_senior_cop",
        provider="edge-tts",
        voice_id="mr-IN-ManoharNeural",
        gender="male",
        style="theatrical_senior_cop",
        default_rate=0.97,
        default_pitch_semitones=-1.5,
        age_group="middle_aged",
        description="Grounded, gritty, experienced baritone detective (Hawkeye / Junyoung style)",
        instruct_prompt="Grounded, gritty, battle-tested baritone male voice, firm and dry delivery with cinematic realism.",
        character_reference="Hawkeye / Junyoung",
    ),
    "hi_avengers_young_hero": VoiceProfile(
        profile_id="hi_avengers_young_hero",
        provider="edge-tts",
        voice_id="ne-NP-SagarNeural",
        gender="male",
        style="theatrical_young_hero",
        default_rate=1.08,
        default_pitch_semitones=1.6,
        age_group="young",
        description="Youthful, energetic, spirited young boy/cop (Spider-Man / Kyungjin style)",
        instruct_prompt="Youthful, spirited, agile heroic young male voice with bright pacing, expressive warmth, and spirited courage.",
        character_reference="Spider-Man / Kyungjin",
    ),
    "hi_avengers_villain": VoiceProfile(
        profile_id="hi_avengers_villain",
        provider="edge-tts",
        voice_id="ko-KR-HyunsuMultilingualNeural",
        gender="male",
        style="theatrical_villain",
        default_rate=0.92,
        default_pitch_semitones=-2.8,
        age_group="middle_aged",
        description="Dark, raspy, intense villainous tone (Thanos / Criminal Byungsoo style)",
        instruct_prompt="Dark, menacing, raspy theatrical villain voice, brooding cadence, low rumble, formidable vocal weight.",
        character_reference="Thanos / Criminal Byungsoo",
    ),
    "hi_avengers_mother_matron": VoiceProfile(
        profile_id="hi_avengers_mother_matron",
        provider="edge-tts",
        voice_id="mr-IN-AarohiNeural",
        gender="female",
        style="theatrical_maternal",
        default_rate=0.95,
        default_pitch_semitones=-1.2,
        age_group="middle_aged",
        description="Warm, emotional maternal tone",
        instruct_prompt="Warm, deeply emotional, protective maternal female voice with gentle resonant timbre and compassionate inflection.",
        character_reference="Warm Maternal Matron",
    ),
    "hi_avengers_young_actress": VoiceProfile(
        profile_id="hi_avengers_young_actress",
        provider="edge-tts",
        voice_id="ne-NP-HemkalaNeural",
        gender="female",
        style="theatrical_young_actress",
        default_rate=1.05,
        default_pitch_semitones=1.4,
        age_group="young",
        description="Bright, expressive young woman",
        instruct_prompt="Bright, expressive, modern young woman voice with crisp articulation, vibrant melodic flow, and cinematic charm.",
        character_reference="Young Actress Lead",
    ),
}

# Export all new theatrical voice profiles in DEFAULT_VOICE_PROFILES
DEFAULT_VOICE_PROFILES.update(THEATRICAL_AVENGERS_PROFILES)


def select_demographic_voice_profile(
    gender: str = "male",
    age_group: str = "adult",
    role: str = "",
    f0_hz: float | None = None,
    style_preference: str = "",
    cloned_profile: VoiceProfile | dict[str, Any] | None = None,
    character_metadata: dict[str, Any] | None = None,
) -> VoiceProfile:
    """Deterministically select the best demographic or theatrical Hindi voice profile based on character attributes.

    Supports cloned profiles, theatrical Marvel/Avengers-grade acting styles, custom characters,
    and maintains 100% backward compatibility with all demographic queries.
    """
    # 0. Cloned voice profile support
    if cloned_profile is not None:
        if isinstance(cloned_profile, VoiceProfile):
            return cloned_profile
        if isinstance(cloned_profile, dict):
            settings = cloned_profile.get("settings") if isinstance(cloned_profile.get("settings"), dict) else {}
            pid = str(cloned_profile.get("profile_id") or cloned_profile.get("voice_id") or f"clone_{cloned_profile.get('character_id', 'custom')}")
            prov = str(cloned_profile.get("provider") or "cloned")
            vid = str(cloned_profile.get("voice_id") or pid)
            g_c = str(cloned_profile.get("gender") or settings.get("gender") or gender)
            s_c = str(cloned_profile.get("style") or settings.get("style") or "cloned")
            lang = str(cloned_profile.get("language") or "hi")
            rate = float(settings.get("rate", cloned_profile.get("default_rate", 1.0)))
            pitch = float(settings.get("pitch_semitones", cloned_profile.get("default_pitch_semitones", 0.0)))
            ag = str(settings.get("age_group", cloned_profile.get("age_group", age_group)))
            desc = str(settings.get("description", cloned_profile.get("description", "Cloned character voice profile")))
            instruct = str(settings.get("instruct_prompt", cloned_profile.get("instruct_prompt", "")))
            return VoiceProfile(
                profile_id=pid,
                provider=prov,
                voice_id=vid,
                gender=g_c,
                style=s_c,
                language=lang,
                default_rate=rate,
                default_pitch_semitones=pitch,
                age_group=ag,
                description=desc,
                instruct_prompt=instruct,
            )

    # 1. Custom character metadata resolution
    if character_metadata and isinstance(character_metadata, dict):
        if character_metadata.get("cloned_profile"):
            return select_demographic_voice_profile(cloned_profile=character_metadata["cloned_profile"])
        vp = character_metadata.get("voice_profile")
        if isinstance(vp, dict) and vp.get("status") == "configured" and (vp.get("provider") or vp.get("voice_id")):
            settings = vp.get("settings") or {}
            pid = str(vp.get("profile_id") or vp.get("voice_id") or "custom_voice")
            return VoiceProfile(
                profile_id=pid,
                provider=str(vp.get("provider") or "custom"),
                voice_id=str(vp.get("voice_id") or pid),
                gender=str(vp.get("gender") or gender),
                style=str(vp.get("style") or "custom"),
                language=str(vp.get("language") or "hi"),
                default_rate=float(settings.get("rate", 1.0)),
                default_pitch_semitones=float(settings.get("pitch_semitones", 0.0)),
                age_group=str(settings.get("age_group", age_group)),
                description=str(settings.get("description", "Custom character voice")),
            )
        if not role and character_metadata.get("role"):
            role = character_metadata["role"]
        if not style_preference and character_metadata.get("style"):
            style_preference = character_metadata["style"]
        if gender == "male" and character_metadata.get("gender"):
            gender = character_metadata["gender"]
        if age_group == "adult" and character_metadata.get("age_group"):
            age_group = character_metadata["age_group"]

    g = (gender or "male").strip().lower()
    a = (age_group or "adult").strip().lower()
    r = (role or "").strip().lower()
    s = (style_preference or "").strip().lower()

    is_theatrical = s in ("theatrical", "avengers", "marvel", "cinematic", "epic") or any(
        tag in r for tag in ("theatrical", "avengers", "marvel", "cinematic")
    )

    # 2. Direct Marvel / Avengers / Theatrical character style matching
    if any(k in r for k in ("tony", "stark", "iron_man", "iron man", "jin_isoo", "jin isoo", "isoo", "avengers_hero")):
        return DEFAULT_VOICE_PROFILES["hi_avengers_hero_male"]
    if any(k in r for k in ("black_widow", "black widow", "natasha", "ganghyun", "avengers_lead")):
        return DEFAULT_VOICE_PROFILES["hi_avengers_lead_female"]
    if any(k in r for k in ("nick_fury", "nick fury", "fury", "chairman_jin", "chairman jin", "avengers_chief", "elder_chief")):
        return DEFAULT_VOICE_PROFILES["hi_avengers_elder_chief"]
    if any(k in r for k in ("hawkeye", "clint", "junyoung", "avengers_senior_cop")):
        return DEFAULT_VOICE_PROFILES["hi_avengers_senior_cop"]
    if any(k in r for k in ("spider", "spiderman", "spider-man", "peter_parker", "kyungjin", "avengers_young_hero")):
        return DEFAULT_VOICE_PROFILES["hi_avengers_young_hero"]
    if any(k in r for k in ("thanos", "byungsoo", "avengers_villain")):
        return DEFAULT_VOICE_PROFILES["hi_avengers_villain"]
    if any(k in r for k in ("avengers_mother", "avengers_matron", "mother_matron")):
        return DEFAULT_VOICE_PROFILES["hi_avengers_mother_matron"]
    if any(k in r for k in ("avengers_actress", "young_actress")):
        return DEFAULT_VOICE_PROFILES["hi_avengers_young_actress"]

    # 3. Theatrical style preference grid
    if is_theatrical:
        if "villain" in r or "criminal" in r or "antagonist" in r or "rough" in r:
            return DEFAULT_VOICE_PROFILES["hi_avengers_villain"]
        if "senior" in r or "cop" in r or "detective" in r:
            return DEFAULT_VOICE_PROFILES["hi_avengers_senior_cop"] if g == "male" else DEFAULT_VOICE_PROFILES["hi_avengers_lead_female"]
        if "chief" in r or "chairman" in r or "elderly_heavy" in r:
            return DEFAULT_VOICE_PROFILES["hi_avengers_elder_chief"]
        if "mother" in r or "matron" in r:
            return DEFAULT_VOICE_PROFILES["hi_avengers_mother_matron"]
        if "actress" in r or "young_woman" in r or "young_girl" in r:
            return DEFAULT_VOICE_PROFILES["hi_avengers_young_actress"]
        if "junior" in r or "young_hero" in r or "young_cop" in r or "boy" in r:
            return DEFAULT_VOICE_PROFILES["hi_avengers_young_actress"] if g == "female" else DEFAULT_VOICE_PROFILES["hi_avengers_young_hero"]
        if "hero" in r or "lead" in r or "chaebol" in r or "playboy" in r:
            return DEFAULT_VOICE_PROFILES["hi_avengers_lead_female"] if g == "female" else DEFAULT_VOICE_PROFILES["hi_avengers_hero_male"]

        # Demographic theatrical fallbacks
        if g == "female":
            if a in ("young", "young_adult", "child"):
                return DEFAULT_VOICE_PROFILES["hi_avengers_young_actress"]
            elif a in ("middle_aged", "elderly"):
                return DEFAULT_VOICE_PROFILES["hi_avengers_mother_matron"]
            else:
                return DEFAULT_VOICE_PROFILES["hi_avengers_lead_female"]
        else:
            if a in ("child", "young"):
                return DEFAULT_VOICE_PROFILES["hi_avengers_young_hero"]
            elif a in ("middle_aged",):
                return DEFAULT_VOICE_PROFILES["hi_avengers_senior_cop"]
            elif a in ("elderly",):
                return DEFAULT_VOICE_PROFILES["hi_avengers_elder_chief"]
            else:
                return DEFAULT_VOICE_PROFILES["hi_avengers_hero_male"]

    # 4. Standard Role-specific matching (100% backward compatible)
    if "hero" in r or "chaebol" in r or "playboy" in r:
        return DEFAULT_VOICE_PROFILES["hi_hero_young_male"]
    if "detective" in r and g == "female":
        return DEFAULT_VOICE_PROFILES["hi_detective_female"]
    if "senior_detective" in r or "detective" in r and a in ("middle_aged", "adult") and g == "male":
        return DEFAULT_VOICE_PROFILES["hi_senior_cop_male"]
    if "junior" in r or "young_cop" in r:
        return DEFAULT_VOICE_PROFILES["hi_junior_boy_male"]
    if "chairman" in r or "chief" in r or "elderly_heavy" in r:
        return DEFAULT_VOICE_PROFILES["hi_elderly_heavy_male"]
    if "father" in r or "elderly_father" in r:
        return DEFAULT_VOICE_PROFILES["hi_elderly_father_male"]
    if "secretary" in r or "brother" in r or "corporate" in r:
        return DEFAULT_VOICE_PROFILES["hi_secretary_male"]
    if "villain" in r or "criminal" in r or "rough" in r:
        return DEFAULT_VOICE_PROFILES["hi_villain_male"]
    if "reporter" in r or "journalist" in r:
        return DEFAULT_VOICE_PROFILES["hi_reporter_male"]
    if "mother" in r or "matron" in r:
        return DEFAULT_VOICE_PROFILES["hi_mother_middle_female"]
    if "young_woman" in r or "actress" in r:
        return DEFAULT_VOICE_PROFILES["hi_young_girl_female"]
    if "child" in r or "kid" in r or a == "child":
        return DEFAULT_VOICE_PROFILES["hi_child_voice"]

    # 5. Acoustic F0 override if fundamental frequency is known
    if f0_hz is not None and f0_hz > 0:
        if f0_hz < 130 and g == "male":
            return DEFAULT_VOICE_PROFILES["hi_elderly_heavy_male"] if a in ("elderly", "middle_aged") else DEFAULT_VOICE_PROFILES["hi_senior_cop_male"]
        if f0_hz > 240:
            return DEFAULT_VOICE_PROFILES["hi_child_voice"] if f0_hz > 280 else (DEFAULT_VOICE_PROFILES["hi_young_girl_female"] if g == "female" else DEFAULT_VOICE_PROFILES["hi_junior_boy_male"])

    # 6. Demographic grid: (gender, age_group)
    if g == "female":
        if a == "child":
            return DEFAULT_VOICE_PROFILES["hi_child_voice"]
        elif a in ("young", "young_adult"):
            return DEFAULT_VOICE_PROFILES["hi_young_girl_female"]
        elif a == "middle_aged":
            return DEFAULT_VOICE_PROFILES["hi_mother_middle_female"]
        elif a == "elderly":
            return DEFAULT_VOICE_PROFILES["hi_elderly_female"]
        else:
            return DEFAULT_VOICE_PROFILES["hi_detective_female"]
    else:
        if a == "child":
            return DEFAULT_VOICE_PROFILES["hi_child_voice"]
        elif a in ("young",):
            return DEFAULT_VOICE_PROFILES["hi_junior_boy_male"]
        elif a in ("young_adult",):
            return DEFAULT_VOICE_PROFILES["hi_hero_young_male"]
        elif a in ("middle_aged",):
            return DEFAULT_VOICE_PROFILES["hi_senior_cop_male"]
        elif a in ("elderly",):
            return DEFAULT_VOICE_PROFILES["hi_elderly_heavy_male"]
        else:
            return DEFAULT_VOICE_PROFILES["hi_hero_young_male"]


class VoiceProfileError(ValueError):
    """Raised when a character voice profile is invalid or contains credentials."""


def normalize_voice_profile(value: dict[str, Any] | None) -> dict[str, Any]:
    """Validate and normalize a character voice profile without storing credentials.

    Provider configuration is descriptive only; it does not imply that a TTS
    provider is installed or that its synthesis controls are supported.
    """
    if value is None:
        return {
            "schema_version": VOICE_PROFILE_SCHEMA_VERSION,
            "status": "not_configured",
            "provider": None,
            "voice_id": None,
            "model_path": None,
            "language": None,
            "settings": {},
        }
    if not isinstance(value, dict):
        raise VoiceProfileError("voice_profile must be an object")

    def inspect_keys(item: Any, path: str = "voice_profile") -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                normalized = str(key).strip().lower().replace("-", "_")
                if normalized in _FORBIDDEN_KEYS or any(
                    marker in normalized for marker in ("api_key", "access_token", "secret", "password")
                ):
                    raise VoiceProfileError(f"Credentials are not allowed in {path}.{key}; configure secrets in the server environment.")
                inspect_keys(child, f"{path}.{key}")
        elif isinstance(item, list):
            for index, child in enumerate(item):
                inspect_keys(child, f"{path}[{index}]")

    inspect_keys(value)
    provider = value.get("provider", value.get("engine"))
    if provider is not None:
        if not isinstance(provider, str) or provider not in SUPPORTED_PROVIDERS:
            raise VoiceProfileError(f"provider must be one of: {', '.join(sorted(SUPPORTED_PROVIDERS))}")
    voice_id = value.get("voice_id")
    model_path = value.get("model_path")
    language = value.get("language")
    for field, field_value, limit in (
        ("voice_id", voice_id, 180),
        ("model_path", model_path, 1000),
        ("language", language, 40),
    ):
        if field_value is not None and (not isinstance(field_value, str) or len(field_value) > limit):
            raise VoiceProfileError(f"{field} must be a string of at most {limit} characters")
    settings = value.get("settings", {})
    if not isinstance(settings, dict):
        raise VoiceProfileError("settings must be an object")
    if len(settings) > 50:
        raise VoiceProfileError("settings may contain at most 50 entries")
    if "speaker_id" in settings:
        speaker_id = settings["speaker_id"]
        if not isinstance(speaker_id, int) or isinstance(speaker_id, bool) or speaker_id < 0:
            raise VoiceProfileError("settings.speaker_id must be a non-negative integer")
    # Keep legacy voice profiles readable while adding a stable schema.
    result = deepcopy(value)
    result.update({
        "schema_version": VOICE_PROFILE_SCHEMA_VERSION,
        "status": "configured" if (provider or voice_id or model_path) else "not_configured",
        "provider": provider,
        "voice_id": voice_id,
        "model_path": model_path,
        "language": language,
        "settings": deepcopy(settings),
    })
    result.pop("engine", None)
    result.pop("reference_audio", None)
    result.pop("embedding_path", None)
    return result


def resolve_character_voice(character: dict[str, Any] | None) -> dict[str, Any]:
    """Return the profile resolved for a dialogue unit's linked character."""
    if not character:
        return {"status": "pending", "character_id": None, "profile": None}
    profile = normalize_voice_profile(character.get("voice_profile"))
    configured = profile["status"] == "configured"
    return {
        "status": "configured" if configured else "pending",
        "character_id": character.get("character_id"),
        "profile": profile if configured else None,
        # Backward compatibility for existing Piper synthesis consumers.
        "model_path": profile.get("model_path"),
    }
