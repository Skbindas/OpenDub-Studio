# OpenDub Studio FAQ

## What is OpenDub Studio?

An experimental local-first application for transcribing, translating, reviewing speakers and rendering dubbed video. Its application code is MIT; model weights and input assets have separate terms.

## How do I start?

Follow [Quick start](QUICK_START.md), launch the local studio and check **Setup & readiness**. Upload a video, choose source/target languages, review voices, generate a preview and listen before exporting. Optional model setup and access are still required.

## Is Hindi dubbing tested?

A real short-video Chinese-to-Hindi path has technical render/timing/decode evidence. That does not certify every line, all speakers, full-length movies or other language pairs. See the current [demo status](DEMO.md).

## Will it always pick the right character voice automatically?

No. Speaker changes, overlap, similar voices and noisy audio can need correction. Review character mapping and audition each voice. Voice register does not prove a person's gender, age or identity. Lock reviewed mappings before continuing.

## Does it include a free public movie voice pack?

No. Legacy movie references are private working assets. Import a clean single-speaker WAV you own or have permission to use, supply its exact transcript and review a generated audition. Private use permission does not automatically include public redistribution.

## Is commercial use unrestricted?

The application code is MIT. The current OmniVoice pretrained weights have non-commercial terms; other selected models, media and binaries have their own licenses. Read the [component inventory](../THIRD_PARTY_LICENSES/COMPONENTS.md) for the exact components you use.

## Are videos uploaded to a server?

Local mode processes through the user's local backend and configured services. Optional Kaggle mode uploads selected worker inputs to the user's own Kaggle account. Translation/other configured providers may also receive selected content. Review processing choices before submitting private media. Git source pushes should not contain recordings or exports.

## Is free Kaggle GPU availability guaranteed?

No. A user's account access, accelerator availability, session limits and quota determine execution. The UI exposes waiting and resumable jobs. Recovery after every kind of provider/GPU withdrawal has not been fully validated; local execution is an explicit alternative when ready.

## How long will a two-and-a-half-hour movie take?

No reliable full-movie benchmark is available. Hardware, models, speaker count, separation, translation, synthesis, timing repairs and human review all change the duration. A short test's timing must not be presented as a guaranteed movie completion time.

## Can I deploy the whole application as a static website?

No. A static page can describe the product; media processing requires the Python backend, storage, model access and suitable compute. Do not expose the local studio publicly without a separate deployment/security review.

## Where is the before/after sample?

The Chinese original and Hindi dub are available in the [GitHub README preview](../README.md#before-and-after-chinese--hindi--english). English dubbing is still in progress. The private voice-reference bank is not a public download.
