# First run

OpenDub Studio is an experimental local application with an optional personal Kaggle worker. Our code is MIT; some selected model weights have non-commercial restrictions. Read [component terms](../THIRD_PARTY_LICENSES/COMPONENTS.md) before choosing your use case.

Start from [clone/install commands and required downloads](INSTALL.md). Then follow [local model setup](LOCAL_SETUP.md) or [your own Kaggle setup](KAGGLE_SETUP.md) before the UI workflow below.

1. Install a supported Python environment and FFmpeg/FFprobe. Follow the existing launcher/environment documentation; do not assume another computer has the developer's optional models, reference bank or GPU setup.
2. Start `start.bat` on Windows or `./start.sh` in a POSIX shell. Keep the terminal open. Follow the localhost URL printed by your launcher; the default is port 7860 and isolated test runs can use another port.
3. Open the system check. Resolve missing dependencies and access before starting a large job. The default Small ASR profile is a starting point, not a guarantee for all hardware/languages. Advanced exposes model and manual-stage choices.
4. Create a project and upload the original video. Select Auto Detect or correct the source language, then choose the target language. Hindi and English dialogue workflows are implemented; validate each source/target pair and voice on your own short scene before longer processing.
5. Choose processing location. Local uses your installed supported backends. Kaggle requires your own account, eligible accelerator/quota and explicit private media/model upload choices. Save credentials yourself in Secure API credentials; never paste a token into an issue, screenshot or chat. Gated models require your own access acceptance.
6. In Voice library, open **Add your own recording** to save a private 3–10 second WAV reference (up to 8 MB). Enter its exact words and confirm permission, one clear speaker and a clean background after listening. This does not generate an audition or approve a public voice pack. Then review detected speakers and proposed voice auditions. Names such as Meera, Tara and Kabir are stable library aliases. They do not establish actor identity, gender, age, quality approval or distribution rights. Silent/mixed and unreviewed references are not automatic defaults. Choose/review an authorized reference rather than expecting a bundled movie voice pack.
7. Continue the dub after locking voices. The monitor shows the current stage/count, provider waiting, and retained checkpoints. Resolve flagged lines and resume the affected work instead of restarting the entire project.
8. Listen to the real original and dubbed previews, including character changes, overlapping speech and background music. Technical checks are not human quality acceptance. Download only when the verified render is available.

Open **Setup & readiness** for a secret-free local prerequisite checklist and recheck. The recommended starting ASR remains Small; advanced choices are preserved. Installed environments/files do not certify loaded models. The current setup assistant guides access and dependency steps; it does not silently accept model agreements or install arbitrary GPU packages.

## Common problems

- **Failed to fetch:** ensure the matching launcher is running and you opened its printed port. Reload after it is ready. An offline empty UI does not mean your saved projects were deleted.
- **Waiting for Kaggle:** inspect Processing location and saved remote jobs. Allocation/setup/download can take time. Avoid duplicate submission; only select local deliberately when its models/hardware are ready.
- **No suitable voice:** review or provide a clean, permission-cleared single-speaker reference. Do not mark missing speech or mixed speakers as approved to continue.
- **Wrong voice or unclear words:** compare the original audition, select a clean reference, correct character mapping and retry only affected dialogue. Automatic pitch measurements do not certify gender/identity.
- **Timing review:** keep complete intelligible speech. Review wording or explicitly allow an available dialogue gap; do not force excessive speed or truncate the last word.

## Data and privacy

Source videos, outputs, credentials and model downloads remain outside ordinary Git source changes. Kaggle mode uploads selected media/references and worker inputs privately to the user's account after their explicit selection. Private cloud storage is still a third-party upload. A public demo requires separately cleared media/voice rights; changing a clip's language does not establish them.
