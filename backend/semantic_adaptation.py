"""Theatrical semantic dialogue adaptation and lip-sync synchronization for OpenDub Studio.

This module provides Marvel/Avengers-grade Hindi semantic adaptation:
- Colloquial, punchy, cinematic spoken Hindi idioms (as heard in Marvel movies and top K-Dramas)
- Syllable counting and duration matching to actor's lip flaps (+/- 0.05s tolerance)
- Emotion and attitude tagging ([confident], [intense], [angry], [whisper], [playful], [authoritative])
- Offline local adaptation engine and OpenAI-compatible LLM provider integration
"""
from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class SemanticAdaptationError(RuntimeError):
    """Raised when the optional semantic provider cannot return a safe proposal."""


# The 6 core theatrical attitude tags for cinematic dubbing
CORE_EMOTION_TAGS = (
    "[confident]",
    "[intense]",
    "[angry]",
    "[whisper]",
    "[playful]",
    "[authoritative]",
)

# Canonical mapping for tone/delivery intent to core emotion tags
EMOTION_TAG_MAP: dict[str, str] = {
    # Confident / Heroic
    "confident": "[confident]",
    "heroic": "[confident]",
    "proud": "[confident]",
    "bold": "[confident]",
    "brave": "[confident]",
    "triumphant": "[confident]",
    "hero_playboy": "[confident]",
    "playboy": "[confident]",
    # Intense / Dramatic
    "intense": "[intense]",
    "serious": "[intense]",
    "dramatic": "[intense]",
    "urgent": "[intense]",
    "suspenseful": "[intense]",
    "grim": "[intense]",
    "desperate": "[intense]",
    "sharp": "[intense]",
    "female_detective": "[intense]",
    "detective": "[intense]",
    # Angry / Aggressive
    "angry": "[angry]",
    "furious": "[angry]",
    "hostile": "[angry]",
    "irritated": "[angry]",
    "aggressive": "[angry]",
    "rage": "[angry]",
    "rough": "[angry]",
    "villain": "[angry]",
    "villain_rough": "[angry]",
    # Whisper / Secretive / Emotional
    "whisper": "[whisper]",
    "secretive": "[whisper]",
    "soft": "[whisper]",
    "conspiratorial": "[whisper]",
    "tender": "[whisper]",
    "maternal": "[whisper]",
    "mother": "[whisper]",
    "mother_matron": "[whisper]",
    # Playful / Comic / Spirited
    "playful": "[playful]",
    "comic": "[playful]",
    "witty": "[playful]",
    "sarcastic": "[playful]",
    "ironic": "[playful]",
    "energetic": "[playful]",
    "youthful": "[playful]",
    "young": "[playful]",
    "young_boy": "[playful]",
    "young_woman": "[playful]",
    "surprised": "[playful]",
    # Authoritative / Commanding
    "authoritative": "[authoritative]",
    "commanding": "[authoritative]",
    "chief": "[authoritative]",
    "formal": "[authoritative]",
    "stern": "[authoritative]",
    "senior": "[authoritative]",
    "senior_detective": "[authoritative]",
    "elderly_heavy": "[authoritative]",
    "patriarch": "[authoritative]",
}

# Colloquial Hindi cinematic idioms mapping stiff machine translations
# into punchy, natural Bollywood / Marvel Avengers spoken Hindi.
CINEMATIC_HINDI_IDIOMS: list[tuple[re.Pattern, str]] = [
    # Declarative / Heroic punchlines
    (re.compile(r"मैं इसे करने जा रहा हूँ", re.IGNORECASE), "यह मैं संभाल लूँगा"),
    (re.compile(r"मैं यह करने जा रहा हूँ", re.IGNORECASE), "ये तो मैं ही करूँगा"),
    (re.compile(r"मैं इसे करूँगा", re.IGNORECASE), "मैं देख लूँगा इसे"),
    (re.compile(r"हम इसे कर सकते हैं", re.IGNORECASE), "हम ये कर दिखाएंगे!"),
    (re.compile(r"हम जीतेंगे", re.IGNORECASE), "जीत हमारी ही होगी!"),
    (re.compile(r"यह मेरा फैसला है", re.IGNORECASE), "फैसला हो चुका है!"),
    (re.compile(r"मैं वापस आऊंगा", re.IGNORECASE), "लौट के आऊँगा मैं!"),
    # Conversational checks & questions
    (re.compile(r"क्या आप ठीक हैं\??", re.IGNORECASE), "सब ठीक तो है ना?"),
    (re.compile(r"क्या तुम ठीक हो\??", re.IGNORECASE), "होश में तो हो?"),
    (re.compile(r"क्या आप पागल हैं\??", re.IGNORECASE), "दिमाग़ खराब हो गया है क्या?"),
    (re.compile(r"क्या तुम पागल हो\??", re.IGNORECASE), "पागल हो गए हो क्या?"),
    (re.compile(r"क्या आप मुझसे मज़ाक कर रहे हैं\??", re.IGNORECASE), "मज़ाक चल रहा है क्या यहाँ?"),
    (re.compile(r"क्या तुम मज़ाक कर रहे हो\??", re.IGNORECASE), "मज़ाक कर रहे हो क्या?"),
    (re.compile(r"यहाँ क्या हो रहा है\??", re.IGNORECASE), "ये क्या बखेड़ा है यहाँ?"),
    (re.compile(r"तुम्हारा क्या मतलब है\??", re.IGNORECASE), "कहना क्या चाहते हो?"),
    (re.compile(r"तुम क्या सोच रहे हो\??", re.IGNORECASE), "दिमाग़ में क्या खिचड़ी पक रही है?"),
    # Reassurance & Casual expressions
    (re.compile(r"चिंता मत करो", re.IGNORECASE), "फ़िक्र मत करो यार"),
    (re.compile(r"चिंता मत कीजिए", re.IGNORECASE), "बेफ़िक्र रहिए"),
    (re.compile(r"मुझ पर विश्वास करो", re.IGNORECASE), "भरोसा रखो मुझपर!"),
    (re.compile(r"मुझ पर भरोसा करो", re.IGNORECASE), "यकीन रखो यार!"),
    (re.compile(r"कोई बात नहीं", re.IGNORECASE), "कोई चक्कर नहीं यार!"),
    (re.compile(r"शांत हो जाओ", re.IGNORECASE), "ठंडे दिमाग़ से सोचो!"),
    (re.compile(r"सब ठीक हो जाएगा", re.IGNORECASE), "सब संभाल लेंगे हम!"),
    # Exclamations & Drama
    (re.compile(r"क्या बकवास है\??", re.IGNORECASE), "क्या बकवास है ये!"),
    (re.compile(r"यह असंभव है", re.IGNORECASE), "ये तो नामुमकिन है!"),
    (re.compile(r"बिल्कुल नहीं", re.IGNORECASE), "सवाल ही पैदा नहीं होता!"),
    (re.compile(r"मुझे परवाह नहीं है", re.IGNORECASE), "मुझे कोई फर्क नहीं पड़ता!"),
    (re.compile(r"मुझे नहीं पता", re.IGNORECASE), "मुझे क्या मालूम यार!"),
    (re.compile(r"भगवान का शुक्र है", re.IGNORECASE), "शुक्र है ऊपर वाले का!"),
    (re.compile(r"चलो चलते हैं", re.IGNORECASE), "चलो, निकलते हैं यहाँ से!"),
    (re.compile(r"जल्दी करो", re.IGNORECASE), "वक़्त नहीं है, जल्दी!"),
    (re.compile(r"मेरी बात सुनो", re.IGNORECASE), "एक बात कान खोल के सुन लो!"),
    (re.compile(r"ध्यान से सुनो", re.IGNORECASE), "ध्यान से सुन लो!"),
    (re.compile(r"रुको एक मिनट", re.IGNORECASE), "रुको ज़रा..."),
    (re.compile(r"एक मिनट रुको", re.IGNORECASE), "एक सेकंड रुको..."),
]


def count_hindi_syllables(text: str) -> int:
    """Accurately count phonetic syllables (aksharas) in Hindi/Devanagari text.

    Considers:
    - Independent Devanagari vowels (अ, आ, इ, ई, etc.)
    - Consonants with implicit schwa vowels (क, ख, ग, etc.)
    - Virama (halant ्) which silences the implicit vowel in conjuncts
    - Vowel signs (matras: ा, ि, ी, ु, ू, etc.)
    - Anusvara/visarga which adhere to the syllable
    - Latin words via phonetic vowel-group heuristics
    """
    clean = re.sub(r"\[[a-zA-Z0-9_\-]+\]", "", text).strip()
    if not clean:
        return 0

    syllable_count = 0
    words = clean.split()

    for word in words:
        word_syllables = 0
        i = 0
        wlen = len(word)
        has_devanagari = False

        while i < wlen:
            ch = word[i]
            code = ord(ch)

            # Independent Devanagari vowels: \u0904 - \u0914
            if 0x0904 <= code <= 0x0914:
                word_syllables += 1
                has_devanagari = True
                i += 1
            # Devanagari consonants: \u0915 - \u0939, \u0958 - \u095F
            elif (0x0915 <= code <= 0x0939) or (0x0958 <= code <= 0x095F):
                has_devanagari = True
                # Check if followed by virama (halant \u094D)
                if i + 1 < wlen and ord(word[i + 1]) == 0x094D:
                    # Half consonant (conjunct) does not add a standalone syllable
                    i += 2
                else:
                    word_syllables += 1
                    i += 1
                    # Skip any attached matras, nukta, anusvara (0x093E - 0x094C, 0x0901 - 0x0903)
                    while i < wlen and (
                        0x093E <= ord(word[i]) <= 0x094C
                        or 0x0901 <= ord(word[i]) <= 0x0903
                        or ord(word[i]) == 0x093C
                    ):
                        i += 1
            else:
                i += 1

        # If word was in Latin characters (English/Hinglish), count vowel clusters
        if not has_devanagari:
            latin_word = re.sub(r"[^a-zA-Z]", "", word)
            if latin_word:
                vowel_groups = re.findall(r"[aeiouy]+", latin_word, re.IGNORECASE)
                word_syllables = max(1, len(vowel_groups))

        syllable_count += max(1, word_syllables) if re.search(r"[\w\u0900-\u097F]", word) else 0

    return max(1, syllable_count) if clean else 0


def estimate_hindi_speaking_duration(text: str, speech_rate_syllables_per_sec: float = 4.2) -> float:
    """Estimate natural speaking duration in seconds based on syllables and punctuation pacing."""
    syllables = count_hindi_syllables(text)
    rate = max(1.0, float(speech_rate_syllables_per_sec))
    base_duration = syllables / rate

    # Natural breathing & dramatic pauses from punctuation
    commas = text.count(",") + text.count("，")
    ellipses = text.count("...") + text.count("…")
    stops = text.count("!") + text.count("?") + text.count("।") + text.count(".")

    pause_time = (commas * 0.15) + (ellipses * 0.28) + (stops * 0.08)
    return round(base_duration + pause_time, 3)


def calculate_lip_flap_timing(
    text: str,
    source_duration_sec: float | None,
    speech_rate_syllables_per_sec: float = 4.2,
    tolerance_sec: float = 0.05,
) -> dict[str, Any]:
    """Evaluate whether dialogue syllables fit the actor's lip flaps within +/- 0.05s tolerance."""
    syllables = count_hindi_syllables(text)
    rate = max(1.0, float(speech_rate_syllables_per_sec))

    if source_duration_sec is None or source_duration_sec <= 0:
        est_dur = estimate_hindi_speaking_duration(text, rate)
        return {
            "syllable_count": syllables,
            "target_syllables": syllables,
            "estimated_speaking_duration_sec": est_dur,
            "source_duration_sec": None,
            "duration_delta_sec": 0.0,
            "within_tolerance": True,
            "tolerance_sec": tolerance_sec,
            "status": "lip_sync_unconstrained",
            "pacing_recommendation": "No source duration constraint provided.",
        }

    target_dur = float(source_duration_sec)
    est_dur = estimate_hindi_speaking_duration(text, rate)
    delta_sec = round(est_dur - target_dur, 3)
    within_tolerance = abs(delta_sec) <= tolerance_sec

    ideal_syllables = max(1, int(round(target_dur * rate)))
    min_syllables = max(1, int(round(max(0.1, target_dur - tolerance_sec) * rate)))
    max_syllables = max(1, int(round((target_dur + tolerance_sec) * rate)))
    syllable_delta = syllables - ideal_syllables

    if within_tolerance:
        status = "lip_sync_perfect"
        recommendation = f"Dialogue fits actor lip flap interval (+/- {tolerance_sec:.2f}s)."
    elif delta_sec > tolerance_sec:
        status = "lip_sync_over_budget"
        excess = syllables - max_syllables
        recommendation = f"Dialogue exceeds lip flap interval by {delta_sec:+.2f}s (~{excess} syllables). Shorten or tighten phrasing."
    else:
        status = "lip_sync_under_budget"
        deficit = min_syllables - syllables
        recommendation = f"Dialogue is shorter than lip flap interval by {delta_sec:+.2f}s (~{deficit} syllables). Expand or stretch cadence."

    return {
        "syllable_count": syllables,
        "target_syllables_ideal": ideal_syllables,
        "target_syllables_range": [min_syllables, max_syllables],
        "syllable_delta": syllable_delta,
        "estimated_speaking_duration_sec": est_dur,
        "source_duration_sec": round(target_dur, 3),
        "duration_delta_sec": delta_sec,
        "within_tolerance": within_tolerance,
        "tolerance_sec": tolerance_sec,
        "status": status,
        "pacing_recommendation": recommendation,
    }


def resolve_emotion_tag(
    text: str = "",
    tone: str = "",
    delivery_intent: str = "",
    character_identity: str = "",
) -> str:
    """Resolve one of the 6 core Marvel/Avengers emotion tags from context or text."""
    # 1. Direct tag in text
    tag_match = re.search(r"(\[(confident|intense|angry|whisper|playful|authoritative)\])", text, re.IGNORECASE)
    if tag_match:
        return tag_match.group(1).lower()

    # 2. Tone and intent matching
    for candidate in (tone, delivery_intent, character_identity):
        if candidate:
            norm = candidate.strip().lower()
            if norm in EMOTION_TAG_MAP:
                return EMOTION_TAG_MAP[norm]
            for key, tag in EMOTION_TAG_MAP.items():
                if key in norm:
                    return tag

    # 3. Linguistic sentiment cues in text
    t = text.lower()
    if any(w in t for w in ("बकवास", "पागल", "गुस्सा", "मार", "खत्म", "रुको", "खबरदार")):
        return "[angry]"
    if any(w in t for w in ("संभाल", "जीत", "फैसला", "हमेशा", "तैयार", "दम", "यकीन")):
        return "[confident]"
    if any(w in t for w in ("जल्दी", "खतरा", "वक़्त", "मुसीबत", "बचो", "भागो")):
        return "[intense]"
    if any(w in t for w in ("चुप", "धीरे", "आहिस्ता", "राज़", "छुपा", "सुनो ज़रा")):
        return "[whisper]"
    if any(w in t for w in ("मज़ाक", "यार", "अरे", "चक्कर", "मस्त", "कूल")):
        return "[playful]"
    if any(w in t for w in ("आदेश", "हुक्म", "कानून", "कमिश्नर", "सर", "साहब", "कान खोल")):
        return "[authoritative]"

    return "[confident]"


def apply_cinematic_hindi_idioms(text: str) -> str:
    """Transform stiff machine translations into punchy, colloquial Bollywood / Marvel Avengers Hindi."""
    result = text
    for pattern, replacement in CINEMATIC_HINDI_IDIOMS:
        result = pattern.sub(replacement, result)

    # Clean double spaces or double punctuation
    result = re.sub(r"\s+", " ", result).strip()
    result = re.sub(r"([!?,।])\1+", r"\1", result)
    return result


def tune_dialogue_to_lip_budget(
    text: str,
    target_duration_sec: float | None,
    speech_rate_syllables_per_sec: float = 4.2,
    tolerance_sec: float = 0.05,
) -> str:
    """Fine-tune Hindi dialogue syllables to fit within +/- 0.05s of the actor's lip flaps."""
    if target_duration_sec is None or target_duration_sec <= 0:
        return text

    timing = calculate_lip_flap_timing(text, target_duration_sec, speech_rate_syllables_per_sec, tolerance_sec)
    if timing["within_tolerance"]:
        return text

    delta = timing["duration_delta_sec"]
    words = text.split()

    # If dialogue is too long, tighten phrasing
    if delta > tolerance_sec and len(words) > 3:
        # Prune verbose particles if present
        trimmed = text
        for verbose_phrase, compact_phrase in [
            ("के बारे में", "पर"),
            ("करने के लिए", "करने को"),
            ("इस समय", "अब"),
            ("की वजह से", "से"),
            ("चिंता मत करो यार", "फ़िक्र मत कर"),
            ("कोई चक्कर नहीं यार", "कोई बात नहीं"),
            ("एक बात कान खोल के सुन लो", "सुन लो मेरी बात"),
        ]:
            if verbose_phrase in trimmed:
                trimmed = trimmed.replace(verbose_phrase, compact_phrase, 1)
                new_timing = calculate_lip_flap_timing(trimmed, target_duration_sec, speech_rate_syllables_per_sec, tolerance_sec)
                if new_timing["within_tolerance"] or abs(new_timing["duration_delta_sec"]) < abs(delta):
                    return trimmed

    # If dialogue is too short, naturally pad with conversational vocatives / particles
    elif delta < -tolerance_sec:
        padded = text
        # Add natural colloquial breath padding
        if not padded.startswith(("अरे ", "सुनो, ", "देखो, ", "यार, ")):
            if delta < -0.30:
                padded = "सुनो, " + padded
            elif delta < -0.15:
                padded = "अरे, " + padded
        new_timing = calculate_lip_flap_timing(padded, target_duration_sec, speech_rate_syllables_per_sec, tolerance_sec)
        if new_timing["within_tolerance"] or abs(new_timing["duration_delta_sec"]) < abs(delta):
            return padded

    return text


def adapt_cinematic_hindi_dialogue(
    *,
    source_text: str,
    translated_text: str,
    tone: str = "neutral",
    delivery_intent: str = "faithful",
    character_identity: str = "",
    source_duration_sec: float | None = None,
) -> dict[str, Any]:
    """Execute local offline cinematic Hindi adaptation with lip flap alignment and emotion tags."""
    # 1. Apply cinematic idioms
    colloquial_text = apply_cinematic_hindi_idioms(translated_text or source_text)

    # 2. Resolve emotion tag
    emotion_tag = resolve_emotion_tag(colloquial_text, tone, delivery_intent, character_identity)

    # 3. Fine-tune syllables for lip flaps (+/- 0.05s)
    lip_aligned_text = tune_dialogue_to_lip_budget(colloquial_text, source_duration_sec)

    # 4. Compute timing analysis
    timing = calculate_lip_flap_timing(lip_aligned_text, source_duration_sec)

    return {
        "mode": "cinematic_hindi_engine",
        "status": "suggested",
        "source_text": source_text,
        "original_text": translated_text,
        "suggested_text": lip_aligned_text,
        "emotion_tag": emotion_tag,
        "theatrical_line": f"{emotion_tag} {lip_aligned_text}",
        "tone": tone,
        "delivery_intent": delivery_intent,
        "lip_flap_sync": timing,
        "syllable_count": timing["syllable_count"],
        "target_syllables": timing.get("target_syllables_ideal", timing["syllable_count"]),
        "duration_delta_sec": timing["duration_delta_sec"],
        "within_lip_sync_tolerance": timing["within_tolerance"],
        "tolerance_sec": 0.05,
        "requires_review": True,
        "semantic_rewrite": True,
        "production_ready": False,
    }


def format_character_context(registry: dict[str, Any], character_id: str | None) -> str:
    """Return only explicitly saved, human-authored character context for a prompt."""
    if not character_id:
        return "No character linked in the Character Registry; do not infer identity traits."
    if not isinstance(registry, dict):
        return "Character Registry is invalid; do not infer identity traits."
    characters = registry.get("characters") or []
    if not isinstance(characters, list):
        return "Character Registry character list is invalid; do not infer identity traits."
    character = next(
        (row for row in characters if isinstance(row, dict) and str(row.get("character_id") or "") == str(character_id)),
        None,
    )
    if not character:
        return "Character ID is not present in the Character Registry; do not infer identity traits."
    allowed_fields = ("display_name", "description", "identity", "personality", "speaking_style", "traits", "notes")
    context = {key: character[key] for key in allowed_fields if character.get(key) not in (None, "", [], {})}
    if not context:
        return "Registry record has no descriptive identity metadata; do not infer identity traits."
    return json.dumps(context, ensure_ascii=False)


def semantic_provider_configured() -> bool:
    """Check if the external LLM provider API key is set."""
    return bool(os.getenv("OPENDUB_LLM_API_KEY", "").strip())


def propose_semantic_adaptation(
    *,
    source_text: str,
    translated_text: str,
    source_language: str,
    target_language: str,
    character_identity: str = "",
    tone: str = "neutral",
    delivery_intent: str = "faithful",
    max_words: int | None = None,
    source_duration_sec: float | None = None,
    timeout_sec: float = 30.0,
) -> dict[str, Any]:
    """Request a natural rewrite from an OpenAI-compatible chat-completions API.

    Enhanced for Marvel Avengers & K-Drama Hindi theatrical dubbing:
    - Colloquial, punchy, cinematic spoken Hindi
    - Precise syllable count matching actor lip flaps (+/- 0.05s)
    - Emotion and attitude tags ([confident], [intense], [angry], [whisper], [playful], [authoritative])
    """
    api_key = os.getenv("OPENDUB_LLM_API_KEY", "").strip()
    if not api_key:
        raise SemanticAdaptationError("Semantic adaptation provider is not configured.")
    base_url = os.getenv("OPENDUB_LLM_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
    model = os.getenv("OPENDUB_LLM_MODEL", "gpt-4o-mini").strip()
    if not base_url.startswith(("https://", "http://")) or not model:
        raise SemanticAdaptationError("Invalid semantic provider endpoint or model configuration.")

    # Calculate lip-flap target syllables for instruction
    ideal_syllables = (
        max(1, int(round(float(source_duration_sec) * 4.2)))
        if source_duration_sec and source_duration_sec > 0
        else None
    )

    constraints = {
        "source_language": source_language,
        "target_language": target_language,
        "character_identity": character_identity or "Not provided; do not infer identity traits.",
        "tone": tone,
        "delivery_intent": delivery_intent,
        "max_words": max_words,
        "source_duration_sec": source_duration_sec,
        "target_syllables_for_lip_sync": ideal_syllables,
        "lip_sync_tolerance_sec": 0.05,
        "supported_emotion_tags": list(CORE_EMOTION_TAGS),
    }

    system = (
        "You are an elite dialogue adaptation and theatrical dubbing master specializing in Hindi localization "
        "for cinematic blockbusters (Marvel Avengers, top-tier international movies, and Netflix K-Dramas). "
        "Return exactly one JSON object with string field 'suggested_text' and optional field 'emotion_tag'.\n\n"
        "Key dubbing rules:\n"
        "1. CINEMATIC HINDI IDIOM: Translate and rewrite using punchy, charismatic, natural spoken Hindi as heard "
        "in Marvel's Hindi dubs (e.g. Iron Man, Thor, Black Widow, Deadpool). Avoid literal, robotic, or overly formal textbook Hindi.\n"
        "2. LIP FLAP SYNCHRONIZATION: The spoken line MUST match the actor's visual mouth movements and speaking duration "
        "within +/- 0.05 seconds of source_duration_sec. Keep syllable count tightly aligned with the target syllable budget.\n"
        "3. EMOTION & ATTITUDE TAG: Select one of the 6 core theatrical attitude tags: "
        "[confident], [intense], [angry], [whisper], [playful], [authoritative].\n"
        "4. MEANING & CONSTRAINTS: Preserve source facts, relationships, character identity, and core dramatic intent. "
        "Keep within max_words when provided. Output JSON only."
    )

    user = {
        "source_text": source_text,
        "current_translation": translated_text,
        "constraints": constraints,
    }
    payload = {
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
    }
    request = Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=max(1.0, min(float(timeout_sec), 90.0))) as response:
            raw = response.read(1_000_000).decode("utf-8")
        envelope = json.loads(raw)
        content = envelope["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        candidate = parsed.get("suggested_text")
        if not isinstance(candidate, str) or not candidate.strip():
            raise SemanticAdaptationError("Provider returned no usable suggested_text.")
        candidate = " ".join(candidate.split())
        if len(candidate) > 5000:
            raise SemanticAdaptationError("Provider suggestion exceeded the 5000-character safety limit.")
        explicit_emotion = parsed.get("emotion_tag")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise SemanticAdaptationError(f"Semantic adaptation request failed: {exc}") from exc
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SemanticAdaptationError("Provider returned malformed JSON or an unexpected response.") from exc

    # Resolve emotion tag
    emotion_tag = (
        explicit_emotion
        if explicit_emotion in CORE_EMOTION_TAGS
        else resolve_emotion_tag(candidate, tone, delivery_intent, character_identity)
    )

    # Lip-flap timing analysis (+/- 0.05s)
    lip_sync_timing = calculate_lip_flap_timing(candidate, source_duration_sec)

    return {
        "mode": "llm_semantic_assist",
        "status": "suggested",
        "source_text": source_text,
        "original_text": " ".join(str(translated_text or "").split()),
        "suggested_text": candidate,
        "emotion_tag": emotion_tag,
        "lip_flap_sync": lip_sync_timing,
        "syllable_count": lip_sync_timing["syllable_count"],
        "target_syllables": lip_sync_timing.get("target_syllables_ideal", lip_sync_timing["syllable_count"]),
        "duration_delta_sec": lip_sync_timing["duration_delta_sec"],
        "within_lip_sync_tolerance": lip_sync_timing["within_tolerance"],
        "tolerance_sec": 0.05,
        "tone": tone,
        "delivery_intent": delivery_intent,
        "constraints": constraints,
        "requires_review": True,
        "semantic_rewrite": True,
        "production_ready": False,
        "validation_status": "pending",
        "provider": "openai_compatible",
        "model": model,
    }
