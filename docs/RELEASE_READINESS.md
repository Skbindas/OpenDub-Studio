# Source alpha release scope and verification

17 October 2026. **Scope: experimental MIT application-source alpha.** Source-code publication is separate from optional-model installation, voice quality and public-demo acceptance. This is not a stable, turnkey movie-dubbing certification.

## Source checks
- Clean initial Git history contains no old private repository refs.
- Private movie recordings and extracted catalogs/audit metadata are excluded. Original private files and history are retained separately.
- Candidate audit found zero flagged tracked paths, zero historical sensitive/media paths and zero known credential-pattern findings. Additional private-key/cloud-token/credential-URL pattern checks found no matches. These bounded checks are not a complete security or legal certification.
- Independently tested source:468 Python tests passed,2 skipped,1 feature-length deselected;14 frontend tests passed. A fresh core Python environment installed requirements and served five UI/API endpoints without copied developer packages or private voices.
- Check the GitHub prerelease for the exact published revision and its CI result.

## Not bundled
No model weights, FFmpeg/Rubber Band binaries, film clips, voice reference pack, private credentials or runtime data. Generated brand images and SVG adaptations have provenance in web/brand/PROVENANCE.json.

Application MIT does not relicense external models, binaries, services, input films or voice performances. Current OmniVoice pretrained weights have non-commercial terms. Users obtain optional components with their own permissions/accounts; see the component inventory.

## Pending acceptance
- Full optional-model installation and real dubbing from a clean environment.
- Owner-supplied permission-cleared before/after recording, captions and whole-pair listening. No public demo/default voice pack is supplied.
- Full movies, other language pairs, overlap quality and real provider GPU-withdrawal/replacement acceptance.
- Listening review of privately retained legacy references, which are not public defaults.
- Public website/domain, canonical/social metadata, sitemap and indexing.

Before bundling weights/binaries or publishing a demo, complete their exact license/permission review. Source alpha availability does not approve those future distributions.

## Reproduce source inventory
~~~shell
python scripts/audit_public_release.py --deep-history --output runtime/public-alpha/release-audit.json
~~~

Exit2 means blocked findings. Exit0 still means manual review required. Reports contain paths/object IDs, never matching credential values. The scan covers objects reachable from local refs; it cannot certify every secret, remote-only object, attachment or LFS store.

Community PRs require maintainer review and current CI. See CONTRIBUTING.md and MAINTAINER_REVIEW.md. CODEOWNERS alone does not enforce branch rules.
