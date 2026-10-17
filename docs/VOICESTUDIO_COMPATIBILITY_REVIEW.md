# VoiceStudio compatibility review — 3 October 2026

Source: https://github.com/debpalash/VoiceStudio (README, docs/feature-catalog.md,
docs/engines/omnivoice-subprocess.md, docs/audio-quality.md,
backend/services/audio_quality.py, backend/core/job_queue.py).

## Findings

OpenDub already uses the same upstream k2-fsa/OmniVoice model. VoiceStudio has
not been installed or integrated into OpenDub; changing the UI or installing
its entire Electron app is unnecessary for the accepted auditions.

Useful compatibility points:

| Area | OpenDub now | Relevant follow-up |
|---|---|---|
| Reference-conditioned speech | Isolated genuine OmniVoice worker, reference hash/transcript evidence | Preserve the accepted engine; reusable batch worker reduces repeated model loads |
| Worker safety | OS lock, isolated process, timeout, retained assets | Extend resource gating across separation/ASR/TTS and provide cancellation/queue position |
| Voice quality | Silence/tone/clipping checks, Unicode-safe Hindi content evidence, human review | Bounded timestamped advisory warnings; never call them a similarity score |
| Output controls | PCM16 actual engine rate, measured duration | Optional float/24-bit exports only if upstream output contains that precision |
| Model choices | Current accepted OmniVoice configuration | Optional local API adapter after capability discovery, without replacing current project routes |
| Dubbing | Original background stems retained separately from generated vocals | Mix at original timeline; a vocal audition must not contain movie BGM |

The repository distinguishes export precision from synthesis quality and notes
that additional sampling steps do not guarantee better speech. Its isolated
worker design addresses recoverable GPU hangs; its audio checks are advisory.
These are useful design references, not proof that OpenDub voices are verified.

## Integration decision

Keep the accepted direct OmniVoice implementation for the 42-entry work. Do not
add a second Electron UI or large duplicate model downloads. If an external
local provider is needed later, use an optional adapter with saved provider,
voice ID, capabilities and language, and test one real generation first.
VoiceStudio is AGPL-3.0; no repository implementation code was copied into this
change. A direct code/vendor integration would need a separate license decision.

## Current acceptance and remaining work

The user accepted the current char_01, char_03 and char_09 genuine auditions by
listening. Acceptance is saved against their exact generated file hashes.
Original/reference BGM is not evidence of a clean cloning sample. Keep source,
reference and audition separate, preserve the three accepted outputs, and
generate other safe single-speaker candidates in a resumable batch. Mixed,
oversized and uncertain references need versioned repair; they must not be
silently forced into the defaults.
