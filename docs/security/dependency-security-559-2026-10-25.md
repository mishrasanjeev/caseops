# Dependency Security #559 - 25 October 2026

Status: Partially implemented. Release verdict: NO-GO until the acceptance
below is complete. Ownership is existing QG-SEC-001/002/004 and ARCH-OPS-23;
no new product journey, provider policy or legal-source behavior is introduced.

## Root Cause And Scope

The daily Security40180159530 run found newly disclosed vulnerabilities in the
current E3B locked graphs. Existing green release evidence predates that scan.
The gates failed correctly; bypassing them is not the fix. The root Undici
override also requires an actual targeted lock resolution: changing the
manifest alone initially retained7.30.0. Reconcile every nested copy and the
installed graph, not a manifest version string.

| Package | Original Lock | Reviewed Replacement | Primary Evidence |
| --- | --- | --- | --- |
| Filelock | 3.28.0 | 4.2.4 | [Stable package](https://pypi.org/project/filelock/4.2.4/) |
| Undici | 7.30.0 | 7.30.1 | [EventSource advisory](https://github.com/advisories/GHSA-4qv8-2p9j-2685) |
| Zod | 4.4.3 | 4.6.7 | [Collection advisory](https://github.com/advisories/GHSA-mrhx-c7xc-m3w5) |
| Nodemailer | 10.0.13 | 10.2.1 | [Nested-comment advisory](https://github.com/advisories/GHSA-8c8m-p3m8-cjg8) |

Undici8 requires Node22.19+, outside the existing Node22.14 compatibility gate.
Retain the supported patched7 branch for this focused release. Filelock is a
direct security constraint over Hugging Face's transitive cache dependency;
the immutable FastEmbed wheel and all unrelated dependency versions remain.
Nodemailer keeps original MIT-0 bytes; refresh exact metadata/SRI/public notice
and the reviewed-material registry rather than broadening the license allowlist.

## Regression And Acceptance

- `apps/web/lib/dependency-security-20261025.test.ts`: three graph/installed
  identity cases plus actual nested-comment recipient parsing. Initial4/4 RED
  includes the original package selecting the wrong reserved example address.
- `apps/api/tests/test_dependency_security_20261025.py`: manifest/lock/installed
  Filelock identity plus real Hugging Face cross-process exclusion, finite
  timeout and successful reacquisition without model download/provider traffic.
- Existing licence notice byte hashes and production graph gates must pass
  on the newly installed graph, including actual pruned Linux x64 musl copies.
- Fresh canonical `scripts/verify-docker.ps1` with no file filter: all native
  PostgreSQL shards, seeded runtime, desktop shards and mobile browser project.
- Complete web tests/build/typed contracts and hosted full API coverage shards;
  preserve exact collections, phase journals, failures and explicit skips.
- Green current-head CI/Security/CodeQL, protected main merge, identical tested
  tree, canonical guarded deployment and exact-release production verification.
- Recheck API/web identity, job images, warm/latest-only traffic and private
  maintenance's two later clean reports before guarded scheduler resume.

No billable provider probes, synthetic public leads, recipient email delivery,
native app shipping or legal catalogue completion is claimed from this repair.
Production QA uses persistent dedicated tenants and the authoritative no-paid
request marker. Historical Google/provider cleanup/owner-MFA gaps stay open.

Retained execution evidence lives in the primary workspace's
`outputs/security-559-20261025`. Initial API reproduction overlapped candidate
preparation and is mixed-source diagnostic evidence only; do not certify it as
an immutable original or replacement run. Fresh gates must run frozen source.
