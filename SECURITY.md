# Security reporting

OpenDub Studio is experimental, intended to bind to localhost, and has no supported stable production release. Do not expose the studio to the Internet without a separate authentication, upload, storage and provider security review.

Do not post credentials, user recordings, private voice references or vulnerable private endpoints in public issues. If GitHub private vulnerability reporting is enabled, use the repository's **Security → Report a vulnerability** flow. If unavailable, first contact the maintainer through a contact method they have explicitly published; no dedicated security mailbox or response-time guarantee is established here. An ordinary issue may ask for a private reporting channel without disclosing the vulnerability.

Include a minimal description, affected revision, reproduction steps and impact in the private report. Use synthetic/non-sensitive fixtures. If a credential has been exposed, its owner should revoke/rotate it; removing a current file does not remove Git history, downloaded copies or caches.

Downloaded models and third-party packages have independent security and license considerations. A passed test suite or pattern scan is not a security certification.
