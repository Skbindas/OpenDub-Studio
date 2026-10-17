# Contributing

OpenDub Studio is experimental. Please describe reproducible behavior and distinguish a technical test from real listening acceptance.

**Everyone is welcome to contribute** code, documentation, tests, translations, accessibility fixes, reproducible bug reports and reviewed setup improvements. While the repository is private, access is limited; after publication anyone can fork it and propose a pull request. New contributors can start with a small documentation/bug fix or discuss a larger change in an issue first.

## Fork and propose a change

Fork the public repository in GitHub, then replace YOUR_USERNAME with your actual GitHub username:

```sh
git clone https://github.com/YOUR_USERNAME/OpenDub-Studio.git
cd OpenDub-Studio
git remote add upstream https://github.com/Skbindas/OpenDub-Studio.git
git switch -c fix/describe-the-change
```

Follow [installation](docs/INSTALL.md). Make a focused change and stage only intended source files. Review `git diff` and `git diff --cached` before committing. Commit with your real author identity, then push your branch to your fork and open a PR against the maintainer's designated branch. Do not include local datasets, recordings or credentials in a contribution.

## Verification and review

1. Read README.md, docs/QUICK_START.md and the component terms.
2. Create a focused branch and add a regression test for behavior changes.
3. Run `python -m pytest -q -k "not feature_length"` and `node --test tests/test_studio_frontend.cjs tests/test_public_alpha_frontend.cjs`. Media integration tests need FFmpeg/FFprobe and the relevant test dependencies; see CI for its exact environment.
4. Run `git diff --check` and review staged files. Keep user recordings, exports, voice references, keys, models and local runtime outside Git.
5. In a pull request, explain the trigger, behavior change, verification and remaining limits. Use permission-cleared minimal reproduction data only.

Do not submit third-party code/assets without identifying their license. Do not claim voice identity, human approval or model capability from metadata alone. Report security issues privately using SECURITY.md, not a public issue with secrets or personal media.

Every PR is reviewed under [the maintainer checklist](docs/MAINTAINER_REVIEW.md); changes can be requested or rejected. Passing CI alone is not automatic acceptance. The latest revision must be reviewed before merge. [CODEOWNERS](.github/CODEOWNERS) identifies @Skbindas for review but does not itself enforce branch protection.

By submitting your contribution, you confirm you have the rights to submit it under this project's MIT application-code license, with separate third-party notices where required. No separate CLA is configured. Preserve author attribution; AI assistance may be disclosed in the PR without inventing an author account. See [credits](CONTRIBUTORS.md).
