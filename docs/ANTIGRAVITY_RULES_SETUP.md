# AntiGravity rules setup and verification

Prepared 3 October 2026. This package adds engineering constraints; it cannot guarantee that an AI never makes mistakes. Real logs, tests, artifacts and human review are still required.

## Files already saved

- Global rules: <USER_HOME>/.gemini/GEMINI.md. The existing file was empty; no earlier rules were replaced. Applies to all projects on this workstation according to the official rule discovery specification.
- OpenDub workspace rules: .agents/rules/opendub-evidence.md. Contains `trigger: always_on`, required for modular rule files in current documentation.
- Project context and remaining implementation: docs/ANTIGRAVITY_HANDOFF_AND_VERIFICATION_PLAN.md.
- Initial agent prompt: docs/ANTIGRAVITY_START_PROMPT.md.

No dubbing generation, project deletion, default-bank activation or Git push was performed for this handoff package. Saving these files does not prove your installed IDE has loaded them.

## Confirm activation in your installed IDE

1. Open this same OpenDub-Studio folder in AntiGravity, with the existing runtime and storage folders. A fresh Git checkout does not contain private media/models/voice reports.
2. Inspect the IDE's Rules/Customizations interface. Confirm that the global GEMINI.md and workspace rule are discovered and active. Current official docs support these paths; installed versions may expose a different UI.
3. Start a fresh conversation and paste ANTIGRAVITY_START_PROMPT.md. Ask the agent to name the loaded rule paths and summarize the data-preservation and evidence requirements before work. This checks recognition; observed behavior must still be verified.
4. If the workspace rule is missing, use the IDE's Workspace Rules interface to activate the same content in its supported location. Do not create conflicting duplicates. If global rules are missing, use its Global Rules interface and preserve any existing rules.
5. Keep permissions appropriate to the task. Rules are prompt instructions, not an OS sandbox or a guarantee that a command cannot delete data. Do not enable unrestricted automatic deletion/public uploads to compensate for a rule-loading problem.

## What the rules enforce

Read current evidence; plan substantial work; identify root causes; verify real user flows and outputs; retain checkpoints and accepted artifacts; keep review flags honest; protect tokens and private media; inspect diffs; report skipped checks; monitor exact-commit CI; resume without repeating valid completed work.

## Sources checked

- https://www.antigravity.google/docs/rules/ — global and directory locations, frontmatter, activation modes and rule discovery.
- https://codelabs.developers.google.com/getting-started-agy-ide — IDE setup and customization context.

The AntiGravity IDE itself has not been opened or operated in this turn. Its exact installed version, active rule loading and browser capabilities remain to be checked there.
