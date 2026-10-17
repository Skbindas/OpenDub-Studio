# Phase 3 — Dialogue intelligence (initial implementation)

Implemented:
- Optional pyannote.audio diarization adapter using the community-1 pretrained pipeline.
- Speaker turns are persisted as project analysis JSON with start/end timestamps and provisional speaker IDs.
- ASR segments are aligned to diarization turns by maximum temporal overlap, with a coverage-based confidence value.
- API endpoints to start diarization, retrieve diarization, and retrieve the speaker-assigned transcript.
- UI controls to run diarization and view speaker labels/confidence in transcript rows.

Important limitations:
- pyannote is an optional dependency; it is not installed by the default installer and model weights are not bundled.
- The pretrained model may be gated. Users must accept the applicable Hugging Face model terms and supply their own HF_TOKEN through the environment. OpenDub does not store or transmit a token to a third party beyond the model-loading request.
- Speaker IDs are local acoustic clusters, not global character identities. Humans, animals, voice changes, overlapping speech, music, and scene cuts can cause errors. Review is required.
- The implementation has not been run against a full movie in this repository environment. Validate dependency compatibility, model access, VRAM/RAM use, and accuracy on the target machine.
