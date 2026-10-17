# Generated voice consistency review

16 October 2026: the real-video reviewer rejected the supporting girl's voice as masculine in some scenes and inconsistent across lines. A later replacement audition sounded feminine but was rejected for unclear speech. Neither a configured voice ID nor an ASR content check establishes an acceptable listening result.

The affected character's dialogue uses one stable reference ID in the saved manifest. The observed problem is therefore generated delivery drift, rather than a demonstrated scene-by-scene ID reassignment. Preserve the previous render for comparison; do not deliver the rejected replacement clips as a correction.

Reference revisions now invalidate TTS, timing and loudness for the affected character when either the reference audio hash or its transcript hash changes. Previously, keeping the same voice ID could reuse stale speech after a reference correction. Other characters' valid clips remain reusable. Regression tests cover both reference changes.

Retest with a clean, exclusive-speaker reference and compare short and long actual dialogue takes. Inspect intelligibility and voice consistency independently of timing, and fit natural speech only within the existing timing bounds. Do not drop words or force an excessively fast take to make a window pass. Human listening rejection takes precedence over an automatic content pass.

Existing optional voice-style research inference was used only as supporting local diagnostic evidence. It is not a production gender-identity classifier or a human listening approval, and its non-commercial model is not enabled as an unrestricted default.

The reviewer accepted the clean-reference replacement sample for clarity and feminine casting. That acceptance applies to the audition; every affected scene still requires validation. Lock the approved reference, regenerate only the affected character and rebuild the mix/render. Retain source timing, the other characters, background gain, previous render and all protected bank media. See the private runtime continuation receipt for exact job and artifact locations.

A natural-duration diagnostic also repeated reference words. The content guard now flags a large excess of detected words and blocks publication even if an advisory ASR status was supplied. Minor phonetic differences remain advisory. Regression after both guards: 433 passed, 2 skipped, 1 feature-length test deselected. The complete replacement still requires scene-by-scene listening acceptance.

The owner retained the complete long sentence and explicitly approved two bounded dialogue-gap windows. The timing guard now accepts those exact reviewed bounds, retains the original ASR clocks, validates all proposed neighboring windows before writing, and checks the newly added regions against other speech. Existing short trailing allowances retain their previous 0.35-second cap. A pre-existing overlap inside an unchanged source window does not invalidate a clear new allowance. Unapproved, stale, out-of-bounds and colliding changes remain blocked.

Re-transcribing the exact selected reference and changing only its conditioning transcript recovered the full shortened dialogue in a controlled generation comparison. This is technical reference evidence, not human bank-identity certification. Retain earlier transcripts and generated takes. A concatenated ASR transcript can disagree with an isolated check of the same accepted clip; do not cut audio or certify intelligibility solely from such cross-clip timestamps.
Validation after the bounded timing change: 441 passed, 2 skipped, 1 feature-length test deselected.
