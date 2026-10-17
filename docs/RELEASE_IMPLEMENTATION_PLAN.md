# Public alpha implementation and continuation plan

Owner requested implementation, 16 October 2026. Source-only private pushes are authorized. Public visibility, history replacement and final release remain separate final steps.

Source-release scope (17 October 2026): experimental source-only alpha, with pending demo/full-model tests stated openly. Source publication does not certify those acceptance tasks.

## Goal

Make a new contributor able to understand, clone, install and operate OpenDub Studio without the developer's private media, accounts or installed models. Publish bounded tested claims, a cleared demo and an auditable prerelease when the remaining release gates close.

## Ordered work

1. **Inventory and metadata — DONE.** Verify private visibility, default/development branches and About description/topics. Fourteen relevant topics are configured. Topics are classification, not a ranking guarantee.
2. **Reproducible onboarding — IMPLEMENTED.** README clone/install commands, Windows and POSIX core instructions, local-model installation/download inventory, translation setup and Kaggle guide are linked. Repository targets/internal links were checked. Optional-model install commands remain recipes requiring full fresh-environment validation; the core UI installation is not a complete model installation.
3. **Community review — IMPLEMENTED.** Contribution invitation, separate Suhaib/AI credits, @Skbindas CODEOWNERS, issue/PR templates and review/merge checklist are present. CI uses read-only contents permission. CODEOWNERS does not itself enforce branch protection; confirm available hosting rules before relying on enforcement.
4. **Source and dependency checks — PARTLY VERIFIED.** Exact source CI passed 467 Python and 14 frontend tests at 4cffd08. New isolated Windows core install and five API/UI endpoints passed without developer site-packages or private voices. Full optional model installation and an owner-recording dub in that environment remain pending. Final edits need their own CI.
5. **History/asset release candidate — PREPARED, NOT APPROVED.** An ignored source-only ZIP excludes media, weights, runtime and Git history. Existing private repository history still contains 50 WAV paths. Keep a private backup and choose a clean-history publication method with final owner authorization. Never force-push/remove old refs as ordinary cleanup.
6. **Component terms — OPEN.** Finish exact separator/checkpoint, binary packaging and selected translation-provider review. Application MIT does not relicense model weights. No model/binary bundling by default.
7. **Before/after — WAITING FOR MATERIAL.** Obtain an owner/permission-cleared scene and voices, then use the actual UI to generate a Hindi pair, review every line, decode and record hashes/captions/permission evidence. Only the cleared pair may become README/release sample links. Do not publish the private movie to fill this gap.
8. **Prerelease — GATED.** Put the approved candidate on the intended public default branch, verify exact-commit CI and final source inventory, then obtain final owner approval for visibility and `v0.1.0-alpha.1`. Publish prerelease notes and only cleared assets. Verify anonymous clone, install, documentation and sample playback.
9. **Public search surface — OPEN.** Select the final site URL, publish the approved content with canonical/social metadata, verify mobile/crawlability/sitemap and use the owner's Search Console. No localhost indexing, fake reviews, bought stars or guaranteed Trending/AI citations.

## Resumability and limits

Read shared usage before expensive milestones. At primary usedPercent >=95 (5% remaining), stop starting new work; save the exact commit, CI/run status, active owned processes, tests, files changed, pending decisions and next command in `runtime/public-alpha/CONTINUATION_HANDOFF.md` and the private implementation checkpoint. Never place tokens or private media in a public handoff. Resume from the recorded state rather than rerunning completed dubbing.

## Verification

For this documentation/community increment: validate internal links and command targets, run core diagnostics in the already isolated core environment, parse YAML/JSON, check `git diff --check`, push source only and inspect exact-commit CI. Keep current movie/audio hashes and running studio untouched.
