# Phase 5 — Source separation (initial adapter)

Implemented:
- Optional audio-separator / UVR model adapter to produce a vocal candidate and, when available, an instrumental/background candidate.
- Original extracted audio is copied into the separation folder before attempting separation, and remains available as a safe fallback.
- API pipeline stage and result endpoint, plus a UI action and result summary.
- Separation is optional and not installed by the default installer.

Limitations and model licensing:
- A vocal stem is not the same as isolated dialogue. Singing, vocal sound effects, and artifacts can remain; music and effects can leak into either stem.
- The model is user-downloaded; check the specific model card and license before commercial use or redistribution. No weights are bundled.
- The current package requirements specify the CPU extra to maximize compatibility; performance and dependency resolution on Windows/RTX 3050 are unverified.
- Full stem audition, quality metrics, and final background remix controls are not yet implemented.
