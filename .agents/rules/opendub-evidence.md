---
trigger: always_on
description: Preserve OpenDub assets and verify genuine cloned voices, checkpoint recovery, Hindi content and original backgrounds with evidence.
---

# OpenDub Studio project invariants

- Read docs/ANTIGRAVITY_HANDOFF_AND_VERIFICATION_PLAN.md before continuing this handoff. Verify inherited claims against current files and Git state.
- Preserve the accepted char_01_sathyam_mohanlal, char_03_anand_action_ntr and char_09_anu_nithya_menen output hashes. Do not regenerate those takes merely because ASR has phonetic spelling differences.
- 42 catalog IDs are not proof of 42 unique actors. 55 auditions are not 55 verified voices. Use real source identity and listening evidence.
- Keep original movie/media, reference versions, suspect auditions, successful project outputs and legacy defaults. No deletion in routine UI tests.
- Never set review flags to true just to raise the verified count. Apply the seven gates and actual reference/output hashes and transcript matching in backend/voice_bank_quality.py.
- Real reference-conditioned generation only. No stock/tone/passthrough fallback labeled a clone. Keep provider/model/reference provenance.
- Correcting a reference transcript or selecting a different source invalidates that reference's stale clone eligibility; preserve previous revisions and acceptance history.
- Hindi content checks preserve Unicode vowel marks. ASR is supporting evidence; missing speech and minor phonetic spelling differences require different handling. Do not erase words or relax timing/content rules simply to pass.
- Vocals-only auditions are intentional. Movie output must retain the original music/effects timeline; listen for source-separation artifacts and verify mix gains/timing. Do not certify BGM cleanliness from metadata alone.
- Resume from the failed valid checkpoint with completed outputs retained. Test interruption/restart and changed-input invalidation. Never rerun the full movie by default.
- Main terminal stays visible/open. Do not kill the app or close consoles without checking active work and preserving checkpoints. One GPU-heavy clone worker; clone-env and main .venv remain separate.
- White theme with readable Hindi and English, visible status/focus and no decorative GPU-heavy additions. Do not broaden into unrelated UI work during voice review.
- Browser testing must use the user's authorized embedded browser. Codex's in-app browser cannot be assumed available inside AntiGravity; report tool limitations and obtain a user-approved alternative rather than launching external Chrome/Edge.
- Keep runtime, storage media, private paths/logs and credentials local. Commit only intended source/tests/public documentation. Verify exact-commit GitHub workflows after an authorized push.
