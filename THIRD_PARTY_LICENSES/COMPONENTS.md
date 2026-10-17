# Component and asset release inventory

Checked 16 October 2026. Our application code is MIT. That does not relicense model weights, reference voices, films, music, or externally supplied files. The source alpha includes no weights, media binaries, movie references or extracted movie catalog. Optional-component redistribution remains subject to exact terms and separate review.

| Component | Project integration | Upstream terms / action |
|---|---|---|
| OmniVoice | `omnivoice==0.2.1`; runtime model revision is pinned locally | [Official model card](https://huggingface.co/k2-fsa/OmniVoice) distinguishes Apache-2.0 code from CC-BY-NC pretrained weights. Current cloning profile must not be advertised as unrestricted commercial use. Check the exact downloaded revision before redistribution. |
| Faster-Whisper small | `faster-whisper==1.2.1`; exact model revision pinned at acquisition | [Converted checkpoint](https://huggingface.co/Systran/faster-whisper-small) declares MIT. Preserve upstream notices; inspect every other selected checkpoint separately. |
| Community-1 | `pyannote.audio==4.0.7`; gated snapshot | [Official model card](https://huggingface.co/pyannote/speaker-diarization-community-1) declares CC-BY-4.0, attribution and user access setup. Do not accept user conditions silently or publish private authorization material. |
| Audio separator and Roformer checkpoint | `audio-separator[gpu]==0.47.0`; checkpoint content hash bound to task | Package code license does not establish checkpoint redistribution rights. Check exact checkpoint origin, training restrictions and notices before bundling. OPEN REVIEW. |
| FFmpeg / codecs / Rubber Band | User's actual executable/build | License depends on enabled libraries and distribution. Review actual build and required notices if shipping binaries. Do not bundle an arbitrary local executable. OPEN REVIEW. |
| Translation | Configured provider or optional local engine | Inventory the provider/model actually selected and its terms. No blanket commercial claim for all optional engines. OPEN REVIEW. |
| Optional voice-style / demographic models | Research tooling | Not an identity certificate or approved production feature. Exact model/data terms need independent review. OPEN REVIEW. |
| Legacy movie reference bank | 50 private WAV files removed from current Git index, 42 catalog entries; historical copies remain | Publication/voice permissions are unverified. Friendly names do not grant rights or certify actor identity. Keep local working assets; exclude from any clean public release unless evidence permits distribution. Git history also needs review. |
| Test movie and corrected dub | Private runtime | Technical QA is separate from public demonstration rights and whole-render listening acceptance. Do not publish as a sample until rights are established. |

## Packaging rules

The public source candidate ships no third-party model weights, FFmpeg/Rubber Band binaries, movie voice bank or extracted movie metadata. The user obtains optional dependencies/models separately under upstream terms. Binary/checkpoint redistribution review is required if a future package bundles them; application MIT alone does not authorize that. Current private operational audits are not sample-pack permissions.

- Keep model files, runtime data and user media outside source distribution by default.
- Model access uses the user's own account; do not bundle keys or share gated access implicitly.
- Reference selection, audition acceptance, default eligibility and distribution permission are separate states.
- A fresh public source distribution needs documented user-supplied/permission-cleared reference setup; the private movie bank must not be its undocumented dependency.
- `python scripts/audit_public_release.py --output runtime/public-alpha/release-audit.json` inventories current tracked files and sensitive/media paths in history. It is not a full historical secret-content scan or legal certification.
