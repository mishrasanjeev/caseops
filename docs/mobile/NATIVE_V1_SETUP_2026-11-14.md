# Disposable V1 workspace setup — November 14, 2026

J20/M22, US-MOB-01/02/08, SOURCE-01/03/04/06 and the83-case Android/iOS
inventory. Candidate **Partially implemented**; bug verdict **Inconclusive**;
complete native acceptance **NO-GO** until the normal setup and native suites run.
This change concerns the isolated QA gateway, not production API authorization.

## Observed boundaries

At source4265240f, both fresh native builds passed. Android's actual replacement
installation preserved app data and matched the APK hash; the owned emulator
proved API36, ARM64 and16KB pages. A public QA CA was installed through Settings
only on that dedicated emulator, preserving the prior certificate bytes. Its
one setup session is independently absent. These setup actions earn no native
case credit. The real phone received no commands or QA certificate.

The fresh synthetic-owner attempt stopped at its bootstrap POST with an
unacknowledged transport result. Do not infer the original HTTP status from that
exception or replay its original credential payload. A separately dated invalid
empty-payload probe measured403 on the public gateway's bootstrap route; the
observed allowlist omitted that route. An independent read-only query found zero
Company rows for the exact synthetic slug. Preserve the failed attempt and its
private files. A different invalid empty-payload probe measured501 for the normal
workspace-configuration PUT. The serving gateway has no PUT handler.

The owner preflight independently matched API-side and PostgreSQL-side database,
system identifier and exact server-start microseconds, an internal network, no
published PostgreSQL port, owned fresh volume and API mounts/image. No owner was
created and no entitlement was granted. A prior embedded-Python quoting failure
occurred before its DB connection; retain it separately. The preflight now parses
that exact Python program offline before any live dispatch.

## Narrow repair and adjacent checks

Add PUT handling only for the literal API-origin
`/api/ip/workspace/configuration`, without query aliases. The exact route still
must be explicitly admitted. The web proxy, other PUT paths, missing marker,
unadmitted route and oversized body remain rejected before upstream transport.
Forward the original normal Bearer authority and request bytes once; keep normal
API authentication/MFA, tenant permissions and body bounds. No provider route,
browser cookie authority, producer permit or production policy is expanded.
Update the independently reviewed gateway implementation pin to the actual bytes.

Two unchanged regressions retain seven red assertions against the original
gateway and pass after this repair. The positive executes real loopback TLS and
one upstream HTTP exchange, verifying marker, exact route, Bearer and byte-exact
body. Negative guards cover absent route, marker, another explicitly listed PUT,
query, web origin and first oversized body. The complete local fixture module
passes119 cases, with no skips;11 gateway route/immutable-snapshot/producer
consumers also pass. A first complete module run inherited a broken ambient
Node16 executable and failed three readiness-child assertions. Preserve that
report; the unchanged119-case replacement activates pinned Node24.15.0 and passes.

## Remaining actual execution

The initial Core allowlist remains narrow. Before any fresh V1 owner credential
is used, the owned V1 operator must publish its canonical declared fixed setup
routes, including bootstrap and MFA enrollment. During its separate37-call
normal governance phase, admit only the exact workspace PUT and exact subsequent
calendar/rule activation routes after their normal acknowledged creation. Remove
the temporary setup PUT before native route-authority capture; native route-file
and descriptor grammars remain unchanged. Retain immutable configuration and
allowlist snapshots, rather than binding later validation to a mutable path.

Use the existing canonical single nonbillable entitlement worker with fresh
Company/current owner locks, exact two entitlement keys, independent PostgreSQL
identity, unchanged32-statement/30-second bound, one durable claim and exact
postcommit readback. Never promote roles through SQL, use direct API-port HTTP,
replay an uncertain mutation or extend the original profile expiry.

The source4265240f per-scope rebuild also left a refused mixed API/web candidate.
Retain its failure. The owned replacement staged both source identities before
canonical Compose/build-web/finish, preserved the original CA/profile expiry and
all77 retained containers, and independently reconciled the70 unrelated ones.
The later park preserves all data and advances only unreached cleanup; a completed
emulator kill is not replayed after its controller stopped.

Evidence resides under the owned native evidence root in
`qa-gateway-put-security-20261114-01/`,
`v1-4265240f-bootstrap-route-diagnostic-01/`, the two failed owner directories,
`android-v1-4265240f-coherent-rebind-02/` and the dated park directories. Fresh
committed-source gates, rebuilt native artifacts, normal bootstrap/governance and
all83 actual cases on each platform remain due. Earlier native passes and either
source4265240f build do not certify this newer candidate. Physical hardware and store
signing remain separate acceptance boundaries.


## 2026-11-14 — CI observability audit contract reconciliation

Status: Partially implemented. Release verdict: NO-GO pending complete native execution and remaining CI.

CI run 43535689936, API coverage shard 13/13 (job 132264142381), exposed the older FastEmbed workflow source assertion still requiring the base-only sync command. The security workflow intentionally installs `--extra observability` so the strict physical installed-metadata audit includes the optional telemetry packages. Reproduced against frozen revision 723552ba: 13 passed, one failed in `test_fastembed_pillow_rebuild_20261021.py`; updated only the expected exact sync command. All existing `uv pip check`, strict OSV, installed-site-package and no-ignore/no-fix guards remain intact.

Verification: complete FastEmbed module plus the unchanged explicit hearing-channel module: 48 passed, zero skips/errors (33.40 seconds), retained JUnit `/Users/sanjeevkumar/.cache/caseops-mobile/native-release-20261111-ZzEIol4V/ci723-contract-green-01.xml`. The second module independently verifies the backend's empty-channel contract; this is not a native or deployed-production acceptance claim. Native builds and executions remain bound to the separate clean 723552ba checkout; this test/document-only follow-up does not alter application, dependency, gateway, build or native harness bytes. Current native acceptance is still incomplete; no historical case credit is transferred.


## 2026-11-14 — Native V1 raw matter DTO boundary

Bug verdict: Partially fixed; native verification remains incomplete. The actual source-723552ba V1 producer created its 26 contracts, eight matter parents, three IP families, scoped grants and three confirmed deadlines, then refused its external fixture projection because raw MatterRecord omits the invented `is_disposed` and `restricted_access` keys. Retained failed run: `/Users/sanjeevkumar/.cache/caseops-mobile/native-release-20261111-ZzEIol4V/v1-723552ba-android-producer-01/phases`; it is incomplete, with zero native credit, and must not be resumed or renamed into a passing aggregate. A separate marked member GET returned all three exact deadline rows; that read does not complete the failed phase.

Adjacent canonical viewer and inbox producers also assumed raw `is_disposed`. A shared strict boundary now validates actual company, UUID, lifecycle version, operational status and `is_active` before producing the internal `is_disposed: false` fixture field. Missing/unknown/closed/disposed status, missing/false activity, a foreign tenant or contradictory derived state remain rejected before any child write/worker. The external base plan must derive restriction from the acknowledged access response rather than MatterRecord. Raw API acknowledgements are not rewritten.

Verification: complete 178-case V1 JavaScript module and the independent Python inventory passed at `/Users/sanjeevkumar/.cache/caseops-mobile/native-release-20261111-ZzEIol4V/v1-matter-record-contract-fix-01/`. Existing tests now exercise raw API-shaped matter responses without the derived key; the negative inbox journeys retain zero worker/child dispatch. The first focused attempt exposed an incomplete calendar composition double missing the actual lifecycle field (177 passed, one failed); the double now models the real required field, with original assertions and counts unchanged. Stronger fresh-profile API and native acceptance is still pending.
