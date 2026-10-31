# Historical Secret-Scan Review - 2026-10-31

Ownership: existing J08/M08 and J14/M14 security and release-readiness gates.
Status: reviewed candidate change, not production certification. Full replacement
Docker, current CI, canonical main and exact-serving acceptance remain required.
Native app implementation and MacBook acceptance are outside this change.

## Observed Failure

Scheduled Security run `41193137288` on main `b9946c7` selected all refs. Its
history scanner reported 41 findings: 31 matched existing reviewed provenance;
ten did not. The actual terminal cause was `History has unreviewed findings`.
Cleanup was confirmed. This was not a scanner timeout or missing-artifact excuse.

Candidate Security run `41182598760` passed its current tree and 34-commit PR
range. That narrower success cannot certify the scheduled all-refs boundary.
The ten reported commits were absent from its selected PR inventory, and their
paths were absent from both current main and candidate trees. This establishes
scope, not which branch owns a historical commit.

## Source Review

Every original redacted SARIF identity was reconciled to provenance, then its
exact immutable Git blob and one-line span were checked independently. All ten
span hashes match the original report. The machine-readable companion
`history-finding-review-2026-10-31.json` records each exact origin fingerprint,
full blob SHA256 and span SHA256 without credential values.

| Source | Findings | Evidence For Non-Credential Classification |
| --- | ---: | --- |
| `apps/web/lib/vitest-host-pool.ts` | 1 | `reviewedFiles` contains a public file checksum consumed by the byte-level SHA256 comparison in `checkFile`, not authentication. |
| `scripts/mobile/host-platform-trust.py` | 1 | `CERTIFI_BYTES` pins a public CA-bundle file hash; `sha(data) == CERTIFI_BYTES[key]` verifies those bytes. |
| `apps/mobile/e2e/v1-workflows-fixture.mjs` | 1 | Conditional `receipt.kind` labels identify prepared-only synthetic evidence. The same object explicitly records `syntheticDataOnly: true`; the value is not an access token. |
| `scripts/mobile/android-native-proof.test.mjs` | 3 | `SDK37_REPORT` is test-report text. The flagged lines explicitly label public-key SHA256, SHA1 and MD5 digests, not private keys or credentials. |
| `scripts/mobile/build-android-local-acceptance.test.mjs` | 3 | The same three public-key digest report lines appear in a second static test fixture. |
| `scripts/mobile/tooling.test.mjs` | 1 | The literal decodes exactly to the public SHA1 interoperability test seed in RFC6238 Appendix B, and is used only by the TOTP vector assertions. |

The public OTP vector was independently checked against
[RFC6238 Appendix B](https://www.rfc-editor.org/rfc/rfc6238.html#appendix-B).
Android's [apksigner reference](https://developer.android.com/tools/apksigner)
documents signature verification and public signing-certificate information;
the reviewed fixture lines themselves identify the public-key digest algorithms.
No source file in the mobile/MacBook branches was modified or executed.

## Narrow Correction And Regression

Only the ten reviewed `origin:path:rule:line` fingerprints are added to
`.gitleaksignore`. No directory, current-path, value-pattern or rule-wide
exception is added. The provenance gate still checks complete span bytes,
original blame identity and selected history; a new origin, changed value,
changed suffix, mixed origin or new rule remains blocking.

The standard `test_secret_scan_gate.py` inventory now always binds all ten
review rows to the exact ten-entry policy section and hash/type contracts.
Every origin in the current all-refs selection must additionally match its
actual immutable blob, exact span and constrained non-secret use. Checked and
not-selected counts are reported separately. Deleted side branches need not
retain unreachable Git objects forever; those rows remain reviewed metadata,
not a new source-verification claim. Missing selected blobs remain failures.
Separate regressions cover both boundaries. The initial run fails because
the reviewed policy section is absent. Existing real scanner canaries
and changed/new-origin rejection cases must also pass unchanged, followed by a
real all-refs scan. A successful PR-range scan alone cannot close this gap.

## Release Evidence Boundary

Docker37's 76 fixture cases passed, but the workstation rebooted during image
export at 13:55:32 UTC on October31. There is no whole-gate completion record.
That run remains interrupted/incomplete, not green. Both Excel summaries must
retain interim verdicts until the new complete gates and deployed journeys pass.
