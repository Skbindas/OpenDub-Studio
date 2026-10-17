# Phase 4 — Global character registry (initial)

Implemented:
- Project-local `characters/registry.json` with stable UUID character IDs.
- Sync diarization speaker labels into a character registry.
- Edit display name and character type (unknown, adult, child, animal, creature, narrator, other), plus notes and review status through the API.
- Link additional acoustic speaker clusters to a single global character; transcript segments receive the linked character_id.
- Voice profile metadata placeholders for future engine, reference audio, embedding path, and settings.

Limitations:
- Speaker linking is manual; no visual face/character recognition or automatic cross-scene voice clustering yet.
- Voice profiles are metadata only; no voice cloning, embeddings, or TTS is implemented in this phase.
- The code was committed through GitHub. It has not been executed or tested on the user's Windows/RTX 3050 machine.
