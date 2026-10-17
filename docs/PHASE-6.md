# Phase 6 — Translation and segment TTS (initial local adapters)

Implemented:
- Local Argos Translate adapter translates each transcript segment independently and preserves original text/timestamps/speaker metadata.
- Translation API and UI action write a project-local translated transcript.
- Piper CLI adapter synthesizes an individual translated segment to WAV using a user-supplied local voice model.
- Synthesize-all UI action runs sequentially to limit memory pressure and stores segment WAVs under the project.
- No model weights are bundled and no network translation/TTS service is called by these adapters.

Setup:
- Install `requirements-translation.txt` in the app environment.
- Install/download Argos language packages for the exact source-target pair separately. Package availability varies.
- Install Piper and a compatible voice model manually; provide the full model path in the UI. Voice model licensing must be checked individually.

Limitations:
- This is baseline offline translation/TTS, not production-quality movie dubbing. No automatic translation package installation, voice cloning, emotion/prosody controls, diarization-based character voice assignment, duration fitting, dialogue ducking, or final mux is implemented yet.
- Synthesis currently makes one WAV per transcript segment; timestamps are retained in metadata but audio is not yet time-aligned/mixed into the movie.
- No local Windows/Python dependency or GPU performance tests have been run.
