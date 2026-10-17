# Pull request review and merge policy

Anyone can propose code, bug fixes, documentation, translations, tests or accessible UI improvements. The maintainer @Skbindas decides what is accepted. No automatic merge is configured by this increment.

Before merging each PR:

1. Understand the reported problem and inspect the complete diff. Check source, scripts, dependency manifests and workflow changes, not just the screenshots or PR summary.
2. Verify scope, regression tests and CI at the **latest PR head**. If code changes after review, review/retest the changed part. Resolve failures rather than bypassing checks to ship.
3. Inspect uploads, paths, command execution, credential/log handling, cloud data transfers and dependencies for privacy/security regressions. Never run untrusted PR code against maintainer credentials or private media. Never add secrets to pull_request_target workflows executing contributor code.
4. Review new code/model/asset licenses and attribution. Keep runtime, weights and private media outside source. Confirm sample publication rights separately from voice audition permission.
5. For media behavior, verify actual generated/decode/playback artifacts and listening where relevant. Unit tests do not certify voice identity, clarity or all GPUs.
6. Check backward compatibility, saved-project/checkpoint recovery, accessible UI and documentation. Keep a clear rollback/revert path. Ask for changes if uncertain.
7. Merge only the reviewed revision, retain author attribution and record meaningful changes in release notes. Avoid unrelated refactoring in a fix.

## Hosting enforcement

CODEOWNERS requests @Skbindas review when supported. It does **not** prevent merging by itself. CI now explicitly requests read-only repository contents. Actual main-branch rules/required checks/review protection have not been configured or certified here; availability depends on the owner's GitHub plan/repository settings. Inspect the available rules before choosing enforcement. A sole maintainer cannot approve their own PR as a second independent reviewer; do not promise an impossible review gate.

Do not enable auto-merge or bypass review for convenience. The public release also requires the separate history/assets/demo checks in RELEASE_READINESS.md.
