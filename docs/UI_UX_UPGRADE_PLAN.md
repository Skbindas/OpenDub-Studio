# OpenDub Studio audit and implementation plan

## Goal
Make the local Hindi dubbing workspace professional, readable on white surfaces, and honest about processing and audio quality. Replace original dialogue with timing-fitted Hindi while retaining the separated background at its original level.

## Context and audit (2026-10-02)
- FastAPI, SQLite durable workers, vanilla HTML/CSS/JavaScript. Preserve this stack and existing project data.
- The supplied test video is 159.103 seconds, 1280x548, stereo AAC at 44.1 kHz. Keep media and model assets local and out of Git.
- Critical: auto-dub currently marks translation, synthesis and render successful after sleeps; extraction/transcription failures are swallowed.
- Critical: default mixing sidechains background and loudness-normalizes the combined soundtrack, changing BGM levels. Separation silently substitutes destructive spectral processing.
- UI contains synthetic waveforms, simulated stem playback, simulated cloning success, invented match scores, hardcoded completed stages and unsupported Dolby/zero-bleed claims.
- Upload and real editing tools appear below several large decorative panels; duplicate character-sync IDs, inaccessible modal behavior and excessive motion need correction.
- Optional speaker diarization is installed but lacks model authorization. Hardware: RTX 3050 4 GB. Model quality and source separation cannot be guaranteed lossless from a mixed soundtrack.

## Decisions
Evolve the existing application instead of introducing a new framework. Design variance 4/10, motion 2/10, density 5/10. White workspace, restrained blue/teal/amber semantic accents, bilingual readable fonts, shallow depth. Replace decorative 3D telemetry with measured audio preview and truthful pipeline progress. Preserve advanced editing tools.

## Steps
1. **Regression coverage:** prove false-success and background gain bugs with focused tests; record baseline suite results.
2. **Real orchestration:** execute existing analysis, translation, synthesis, fit, separation, mix and render operations; propagate failure, validate artifacts and render QA before download readiness. Respect selected model/language. Verify failure and successful sequence tests.
3. **Background integrity:** make separation and unity-gain mixing the defaults; require successful separation for automatic output, label optional degraded approaches accurately. Gate timing problems rather than clipping speech. Verify PCM background gain, duration, fitting and render tests.
4. **Workspace redesign:** put project/upload first, concise workflow navigation, remove invented data and unsupported claims, expose actual previews, fix duplicate controls and project switching. Verify browser clicks and empty/loading/error states.
5. **Accessibility and visual QA:** light-only palette, readable Hindi, responsive layouts, focus, keyboard dialogs, reduced motion. Verify browser snapshots and desktop/mobile dimensions.
6. **Sample pipeline:** import the supplied video into a separate audit project, run real available stages and inspect timing/background/render artifacts. Report missing model access or provider failures honestly; do not call unverified output production quality.
7. **Delivery:** run Python and JavaScript checks, review diff, commit and push the authorized changes. Monitor every workflow triggered by that commit and fix failures.
8. **Persistent terminal (user follow-up):** keep the launcher in the foreground with live local logs. Ctrl+C requests shutdown and requires yes in an interactive terminal. Reopening the launcher follows the existing instance's saved log rather than exiting. Verify declined and confirmed shutdown and add a POSIX start.sh entry point.

## Non-goals
No claim of bit-perfect separation of vocals from arbitrary mixed audio or guaranteed perceptual/lip-sync perfection. No fabricated voice cloning or quality certification. No replacement of the original video or deletion of existing user projects.

## Risks and fallback
Speaker models may require user authorization; external translation/TTS may be unavailable. Failed prerequisites must produce an actionable error, never a fake completed render. Keep source, intermediate stems and QA artifacts for review. A supplied instrumental stem remains the highest-fidelity option. CPU inference may be slow.

## Verification
Focused regression tests, full existing non-feature-length suite, JavaScript syntax, browser interactions, real sample stage outputs, FFprobe duration/stream checks, render QA and GitHub Actions. Document measured results and outstanding subjective listening review separately.

The user explicitly authorized analysis, writing this plan, then implementation, dependency fixes, verification and GitHub push in the same request.
