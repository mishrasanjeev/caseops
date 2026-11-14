# Optional telemetry dependency repair — November 14, 2026

QG-SEC-004 / NFT-005, J14/M14. Candidate implemented; production verdict
**Inconclusive** and complete native release **NO-GO** until the updated image,
CI and both native suites are verified. This does not enable telemetry.

The first strict audit of all152 installed Mac API distributions, including
the optional observability extra, found opentelemetry-api1.45.1 affected by
CVE-2026-126360 / GHSA-mf5v-w3w3-f6cg after the separate DNS repair. Preserve
that failed audit. The previous138-package CI installation omitted this extra.

The [maintainer advisory](https://github.com/open-telemetry/opentelemetry-python/security/advisories/GHSA-mf5v-w3w3-f6cg)
and [official release](https://github.com/open-telemetry/opentelemetry-python/releases/tag/v1.45.2)
identify1.45.2 as patched. The traceparent parser rejects values longer than512
characters before regex processing and removes overlapping suffix/whitespace
branches. The reported exposure requires a carrier preserving newlines; no
CaseOps production route accepting that input was established.

Update the six direct optional pins together to the official1.45.2/0.66b2
cohort and regenerate its14 resolved package records. Retain the unrelated
uharfbuzz record byte-equivalently after separately preserving and explaining
the resolver's artifact-list normalization. DNS2.9.2 and the reviewed FastEmbed
override remain intact. No audit exception or production permission is added.

Nine bounded parser regressions retain four failures on the actual1.45.1
runtime and pass on the official1.45.2 wheel. They cover512/513 boundaries,
newline input, future-version suffixes, invalid and absent identities, exact
valid trace context, no second-header fallback and injection. The regex spy is
local to the parser module, not a process-global regex replacement. The installed
parser hash matches the official wheel member. No timing threshold is relaxed.

The installed cohort notice inventory found13 packages carrying their license,
but opentelemetry-util-http0.66b2's official wheel and sdist omit it. Supply the
unmodified Apache license from contrib tagv0.66b2, commit
a34b6fa56948bebb539cfece22adf5d022cc3c19:11357bytes, SHA-256
c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4.
The new vendor provenance binds both official archives, installed METADATA and
runtime module, and tagged license. Add its exact Docker COPY and LF paths.
Preserve all historical notices. Five packaging regressions verify the lock,
installed bytes, image, both API upload contexts and deployment dirty fence.

The Security workflow's installed pip-audit job now explicitly syncs the
observability extra. Its strict OSV audit, dependency check, time budget and
no-exclusion behavior remain unchanged. A regression checks this exact command;
no existing artifact path is changed.

The complete nine-module API dependency, parser, notice and image-contract
selection passes112 cases plus22 subtests with zero failures/errors/skips, in
the actual locked Python3.13.17 Mac API environment with normal API fixtures.
All152 installed distributions pass dependency validation and a fresh strict
OSV audit with no vulnerability findings, skips or waivers. Independent audit
reconciliation requires unique PEP503 canonical names and exact versions for
every installed distribution, including the private FastEmbed metadata. Keep
the first reconciler's pdfminer.six/pdfminer-six naming refusal separately; the
scanner report itself is unchanged. These are Mac source/runtime checks, not
Linux image, production or native app acceptance.

Evidence is retained under the owned native evidence root in
`otel1452-security-20261114-01/`: original failed audit, primary metadata and
artifacts, red/green results, targeted lock proof, complete JUnit report, actual
installed inventory/audit and license inventory/provenance. Fresh committed
source gates, Linux CI/image validation and exact-source Android/iOS native
suites remain required. None of these tests grants credit in either83-case
native suite or proves store approval.
