## Goal

Dubbing analysis separates vocals before recognition, retains the original movie clock including silent scenes, and assigns speakers at word boundaries before Hindi translation, voice selection and duration fitting.

## Steps

1. Stop and remove test 2 from the app. Permanent cleanup is limited to that project and its identified generated backups/pilots; preserve the Downloads original and shared voice models. Tool policy currently blocks permanent recursive removal.
2. Enable vocal-first analysis for automatic dubbing. Require successful neural stems, verify the vocal stem covers the source duration, then convert it to 16 kHz PCM without trimming silence. Failed separation must not silently transcribe the mixed soundtrack.
3. Recognize timestamped words from this vocal audio and diarize the same audio. Split ASR segments at confidently identified speaker changes, preserving word times and unresolved identities.
4. Retain audio-source/timebase metadata in transcript and timeline, and continue existing natural Hindi translation, stable reference voice assignment and bounded fitting. Transcript text alone does not establish gender, actor identity or exact mouth motion.
5. Verify ordering, missing/short stem rejection, speaker changes and original word times with regression tests. Do not start another movie job after the user requested deletion.

## Limits

Audio timestamps support dialogue synchronization, not guaranteed visual lip synchronization. Gender/reference matching remains measured or user-confirmed; uncertain or overlapping speech is not assigned a fabricated identity. Neural separation can retain music vocals or introduce artifacts.
