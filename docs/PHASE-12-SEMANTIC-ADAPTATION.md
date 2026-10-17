# Phase 12 — Optional Semantic Dialogue Adaptation Provider

## Status: implementation complete (CI verified)\n\nPhase 12 implementation and automated acceptance checks are complete for the scoped provider, review workflow, audit trail, synthesis approval gate, and deterministic metadata/timing validation. This does not claim machine-proven semantic equivalence or replace human review and audio audition.\n\n## Scope

The optional OpenAI-compatible chat-completions provider proposes a natural spoken rewrite for one translated dialogue unit. It is explicitly an assistant-only proposal path.

- The existing `analysis/dialogue_manifest.json` contract is unchanged.
- The provider does not write the manifest or translated transcript.
- Suggestions are returned with `requires_review=true`, `production_ready=false`, and `validation_status=pending`.
- The existing conservative adaptation remains the default and works without an API key.
- Enable the optional provider by setting `OPENDUB_LLM_API_KEY`; configure `OPENDUB_LLM_BASE_URL` and `OPENDUB_LLM_MODEL` for an OpenAI-compatible service.
- Request semantic mode with `adaptation_mode=llm_semantic_assist` on the existing adaptation suggestion endpoint.

## Safety and production gate

The provider prompt asks for faithful meaning preservation and explicitly prohibits inventing facts, plot, relationships, or unsupported emotional intent. The API response is parsed as untrusted JSON and constrained to a non-empty string no longer than 5,000 characters.

**This provider is not production approval.** Character identity, tone, delivery intent, linguistic meaning, word-count and actual source-time fit still require application validation and human review before the candidate is accepted or used for synthesis. A model's own claim of compliance is not validation.

The initial integration carries the unit's character ID as identity context. It does not infer a character biography from that ID. A future enhancement should resolve a reviewed character profile and add deterministic post-generation checks for meaning/identity drift, tone constraints, word limits, and measured speech duration.

## Verified acceptance checks

The API integration and provider tests verify the following safeguards:

- Provider is optional; missing configuration returns HTTP 503 without calling the provider.
- Provider/network failures return a controlled HTTP 502 response.
- Missing project/manifest/segment and blank translated input return controlled 4xx responses.
- Corrupt or malformed character registry metadata falls back to an explicit no-inference identity instruction.
- Provider output is treated as untrusted: route-level response flags are overwritten so every semantic suggestion requires human review and is never production-ready, even if the provider claims approval.
- A successful suggestion leaves the master `dialogue_manifest.json` and existing `translated_transcript.json` unchanged.
- Explicit `POST /api/projects/{project_id}/dialogue/{segment_index}/adaptation/review` supports user approval or rejection: rejection performs no translation write; approval records `human_approved` metadata and updates synthesis input. Every decision is appended to `analysis/adaptation_review_audit.jsonl` with per-dialogue revision, previous text, candidate text, decision, mode, reviewer, timestamp, tone, and delivery intent.
- Translation UI renders the candidate in a separate review panel with Approve/Reject actions; the candidate does not replace the editor before approval. Review calls preserve the actual adaptation mode in saved metadata.
- The synthesis endpoint returns HTTP 409 and does not invoke TTS for an `llm_semantic_assist` transcript row without `adaptation_review.decision=approved`; a human-approved semantic row may proceed to TTS.
- Approval records the human decision but does not claim automatic semantic correctness; deterministic checks cover non-empty text, manifest-vs-row character ID, tone/delivery metadata consistency, and heuristic timing. Semantic equivalence and measured audio duration remain human/audio-review responsibilities.
- Provider output must contain a non-empty string and is bounded to 5,000 characters.
- Frontend JavaScript validation runs even when the Python test step fails, while the overall workflow still fails on a Python test failure.

## Tests

`tests/test_semantic_adaptation.py` covers disabled configuration, review-only output, malformed provider output, response-size limits, and character-context filtering. `tests/test_semantic_adaptation_routes.py` covers API error paths, corrupt-registry fallback, manifest and transcript immutability for suggestions, untrusted provider approval flags, timing over-budget warnings, and explicit approval/rejection persistence. Tests mock the network call and do not require an API key or incur provider charges.

Latest verified CI for Phase 12 completion: 62 unit tests passed; Python compile, durable job queue tests, frontend JavaScript validation, and post-run cleanup all succeeded in GitHub Actions Run #248.
