# Renewal Response Integrity

Status: Inconclusive; release NO-GO until fresh complete gates and production
replay. Scope: UJ-02/04/26, IPLF-037 and their existing source-date/notification
contracts. No legal source, entitlement, provider or lifecycle policy changes.

## Evidence

- R21 `f4fa6dcd7182bf18276a30cca0faffc280681c1e`, main CI39465871860:
  605 browser passes, 17 explicit skips, one failure, no retries. The failure
  is `ram-2026-10-13-ip-portfolio.spec.ts`, the 393px source-tolerant import
  journey, renewal-date correction assertion754.
- Its originating database exception was not retained. Local original-source
  diagnostics05 reproduced after_commit, after_begin, SQLite SQLITE_ERROR1
  and circular/reference evidence. The safe SQL graph repeats anonymous
  `anon_4` declarations at four nested depths. This is not SQLITE_BUSY and
  does not justify an automatic mutation retry.
- Diagnostic06 only hoisted anonymous stages and returned500; it is failed
  evidence, not an accepted fix. Diagnostic07 assigned five explicit stage
  names, retained all nesting/materialization/predicates and completed all
  three date corrections with HTTP200. Its complete journey then failed at
  assertion798: the notification's offsetless SQLite timestamp was interpreted
  in the Windows client's timezone, producing the wrong alert-day expectation.
- All original artifacts remain under
  `outputs/bugs-l-20261019/r21-renewal-sqlite-diagnostic-01`; external AST
  diagnostics are not canonical acceptance or evidence for production.

## Correction And Regression Scope

Give the scoped, provenance, raw-date, validated-date and stopped-source CTEs
distinct stable identities. Keep the existing nested scope, PostgreSQL
MATERIALIZED prefix, tenant/ACL boundaries, exact current-version joins,
malformed-date protection and source eligibility. Exercise warm tracker,
portfolio list/count/category queries and the complete dated browser journey.
Do not merely remove the legacy writer's unused tracker response.

Normalize known UTC notification persistence fields at the response boundary,
including reminders, delivery intents and suppression receipts. Require
explicit offsets, preserve nulls and the exact instant for non-UTC aware
values, and test alert dates around local midnight. Keep the existing exact
browser assertion; do not make it accept either date.

The unrelated CodeQL595 mixed-return note is addressed only by annotating the
unconditional HTTP400 helper as NoReturn, with direct MIME/extension controls.
Its body is unchanged; a fresh hosted scan must establish resolution.

## Scoped Local Results

- `test_ip_tracker_cte_identity_20261021.py` deterministically reuses the
  anonymous CTE seed: the original source failed four calls, including three
  HTTP503s. The replacement and all three adjacent modules pass 63 cases and
  189 phases, without skips or retries. All 21 PostgreSQL-marked cases were
  deselected, not executed; the three new native cases are discoverable and
  still require the Docker gate. Repeated tracker/portfolio queries retain real
  compiled-cache hits and independent all-row versus 90-day category counts.
- The first replacement run's 61 passes/two failures remain retained. Its new
  test incorrectly counted a May16 fixture inside the Jan1-to-Mar31 horizon;
  the corrected independent expectation leaves the product horizon unchanged.
- `test_notification_response_utc_20261021.py` plus the existing notification
  self-test pass 18 cases/54 phases. The original response boundary failed 11
  explicit-offset assertions, including real SQLite reload-to-HTTP output.
  All 11 persisted timestamp fields are covered; three DTO JSON Schemas are
  byte-equivalent as structured documents before and after the correction.
- `test_matter_import_mime_contract.py` and `test_matter_imports.py` pass
  52 cases/156 phases. The original annotation failed its dedicated contract;
  all prior rejection behavior remains unchanged.

Retained local proof roots are `r21-renewal-503-diagnosis-01`,
`notification-dto-utc-01` and `codeql595-noreturn-01` beneath the existing
BUG008 output directory. These scoped results are not summed into a distinct
whole-suite count and are not Docker, hosted CI or production certification.

## Release Boundary

C22 `30d9ba70b3212df60b72416fca149ba6294a9eae` completed a fresh standard-config
build and all four dated IP portfolio browser cases at 1280px/393px, with zero
skips, retries or global errors. Native collection, JSON, JUnit, progress and
all 3,058 source hashes reconcile. This is focused C22 proof, not acceptance
for a later dependency revision or the whole release.

C22 Security39490391664 subsequently failed on critical
[GHSA-6q48-6c7w-9gw2](https://github.com/advisories/GHSA-6q48-6c7w-9gw2),
published October20. Its frozen certifi2026.2.25 includes the affected trust
root; the first patched release is
[2026.10.19](https://pypi.org/project/certifi/2026.10.19/).
Patch that dependency and rebuild images without disabling TLS verification
or changing the audit policy. Preserve the original scan and require fresh
complete gates on the actual replacement commit.

The local follow-up updates only certifi's lock entry and official artifacts;
both hashes match PyPI. All 137 other installed third-party versions remain
unchanged, and the normal 139-distribution environment includes the restored
editable application. Two offline trust-bundle regressions pass six phases:
the compromised G3 root is absent and certificate/hostname verification remains
required. The hash-pinned old bundle fails the root exclusion control without
downgrading the active environment. Strict OSV audit passes for the same 138
non-editable dependencies selected by the canonical CI workflow. This is
scoped local security evidence, not replacement hosted or image acceptance.

Docker12 stopped before application tests because the operator selected
Windows PowerShell5 rather than Docker11's actual accepted bundled PowerShell7
host. An isolated control reproduces stderr from a native exit0 becoming
NativeCommandError on5, while7 accepts exit0 and rejects exit17 explicitly.
Docker13 used the accepted host, but was deliberately superseded after the
critical dependency finding. Its owned native child was stopped, canonical
cleanup ran and its parent was reaped. Neither run provides native PostgreSQL
or browser acceptance; retain both and start the replacement from fresh images.

C21's accepted Docker11 and candidate CI do not override R21's failed main
replay and cannot certify changed source. Require fresh combined Docker/CI,
normal main merge, exact-tree confirmation, current-main release guards and
the exact-serving production journey. Production remains `9cf76f2b` at this
checkpoint. Preserve independent legal-source, Calendar cleanup, unknown
historical incident and initial manager setup qualifications in all workbooks.

## Independent TLS Stores

The C23 adjacent audit found the compromised root in both pinned Node22.14.0
and the API image's system SSL store. Reachable web demo/readiness requests
use default HTTPS fetch; the optional demo SMTP sender used default Python
SSL. Updating certifi alone therefore did not close these paths. This is
candidate-image evidence, not evidence of exploitation or a serving-image
inspection. Docker14 was deliberately superseded: 1,221 native cases finished,
271 more calls passed before interruption, and all 623 browser cases remained
unstarted. Its partial journals and clean resource/source closure are retained.

The replacement web base generates a hash-pinned 148-root bundle from exactly
the existing 149 roots, excluding only the compromised G3 fingerprint. It uses
OpenSSL's explicit file and empty directory before npm/build and at runtime.
An explicit startup preload rejects missing/tampered data and additive or
competing CA settings; verification is never disabled. The Web CI runtime is
pinned to the same shipping Node version. See the exact-version
[CA selection contract](https://nodejs.org/download/release/v22.14.0/docs/api/cli.html#--use-bundled-ca---use-openssl-ca).

`apps/web/lib/node-trust.test.ts` is discovered by the standard Vitest config.
It and the two adjacent client/demo modules pass 40 cases without skips.
Network-disabled Linux-image controls prove default fetch and HTTPS accept a
local trusted fixture and reject an untrusted fixture and wrong hostname.
Synthetic TLS selection and immutable production-bundle exclusion are separate
proofs; the tests do not possess the compromised authority's private key.

The SMTP sender now explicitly selects certifi's reviewed bundle. The original
code fails both 465/587 trust assertions; the three complete related modules
pass 93 cases/279 phases, including PostgreSQL. Socket guards prevent external
delivery. S3 is unchanged: the inspected botocore active and fallback stores
already exclude the affected root. Sender approval/live delivery stays open.

The newly published moderate
[Vite/launch-editor advisory](https://github.com/advisories/GHSA-698v-4r3x-3vcv)
is also patched at Vite8.1.6. Its 24 changed lock entries are all existing
MIT-licensed Vite dependencies; 356 entries remain unchanged, with no added
packages. Full npm audit reports zero findings and the dependency contracts
pass 252 cases. These are scoped preflight results, not complete replacement
Docker/hosted/main or production acceptance. Preserve incomplete diagnostic
launches and require fresh gates on the combined commit.

## Complete Dependency Closure

C24 `4e541acf` failed Security39506605978 on nine Pillow12.3.0 entries,
first patched in [Pillow13.0.0](https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html).
Their OSV publication times followed both C23 clean audits; the failure was
not explained by a Linux/Windows package omission. Docker15 was stopped,
retained and cleaned before any native acceptance or browser execution.
Its successful build/startup is not a complete Docker result.

FastEmbed0.8.0 and the current upstream0.9.0 constrain Pillow below13. A native
uv0.13.4 scoped override can resolve/export/install, but still fails ordinary
installed-dependency validation. That path was rejected. The CaseOps
`1caseops1` wheel instead explicitly rebuilds only the reviewed0.8.0 metadata
for Pillow13, with a distinct build tag, upstream/rebuilt digests and complete
member provenance. Runtime files and upstream LICENSE/NOTICE are unchanged.
This is CaseOps compatibility maintenance, not an upstream support claim or a
change to production Voyage/reranking policy. Keep positive regeneration from
the exact official input, tamper/refusal controls, actual offline inference,
image/OCR paths and ordinary installed-set checks in the regression scope.

The installed-image audit also finds vulnerable uv outside `uv.lock`; the
[maintainer's CA advisory](https://github.com/astral-sh/uv/security/advisories/GHSA-hq85-5cpj-mr62)
requires0.13.4. The replacement image pins that version, disables only the
known G3 Debian anchor and verifies the full before/after root set. Pip
uses the reviewed OS bundle without its additive legacy vendored CA store;
certificate and hostname checks remain enabled. The removal also accepts an
already-secured upstream image. Current offline controls prove150-to149 and
149-to149; the19-case module passes without skips. A separately hash-verified
Windows uv0.13.4 cache is required for subsequent local/release operations;
the existing Winget installation is not overwritten.

The parent also completed all five adjacent deployment/image/rate/license
modules:352 collected identities,351 passed and one explicit Windows skip
for POSIX mount execution policy. JUnit and all1,055 incremental phases match
case-sensitively, with zero failed phases. The first malformed native-argument
launch remains retained as exit4 with no coverage. These are focused C24
contract results, not acceptance for the later dependency revision. Require
fresh complete candidate/main gates and exact-serving production replay.

The final dependency preflight reconciles five complete installed-set OSV
audits with zero findings or omissions: Windows/OCR147, Linux CI137, Linux
production139, and two isolated audit-tool environments of28 each. Native
dependency checks pass. The six complete compatibility modules pass82/82 on
Linux and81/82 on Windows; the one Windows skip is the older opt-in reranker
integration, not an image/Pillow failure. Asset-full controls prove unchanged
2x384 embeddings, both reranking scores and native OCR text/confidence against
the original Pillow12 baseline. Asset-dependent skips outside asset-full
verification are not relabelled positive inference. The existing image prewarm
now executes real two-document reranking; a full precommit API build, offline
final-image inference and all21 image/TLS/tool contract cases pass. This
dirty-snapshot preflight is not a released commit or full Docker acceptance.

Technical compliance review remains within the existing managed-SaaS-only
scope. Pillow's native LICENSE/SBOM materials remain installed; the identified
families include MIT-CMU, MIT, FTL, BSD/X11, IJG/libpng/libtiff and Zlib terms.
Debian's system FriBiDi retains its LGPL-2.1+ copyright and complete licence;
optional GPL libimagequant is disabled. The public FastEmbed rebuild and its
official test fixture retain Apache LICENSE/NOTICE and mark the modifications.
No broader licence-policy waiver or customer binary/container redistribution
approval is implied. Detailed material hashes and review
`CASEOPS-PILLOW13-FASTEMBED08-COMPLIANCE-20261021-02` are retained with the
dependency evidence. Fresh candidate/main and production gates remain pending.

## Final Scanner Findings

C25 `f87d19d6` passed seven Security jobs but failed the secret scanner on two
public wheel-member SHA256 values. They are the exact `token_embeddings.py`
and `tokenizer.py` digests retained from the official FastEmbed wheel, not
credentials. Review only their immutable originating commit/path/rule/line
fingerprints; no path-wide or rule-wide exclusion is authorized. The local
full-scan attempt stopped with a Windows PermissionError before scanning the
tree and remains incomplete. Required hosted Linux scanning must still pass.

The separate CodeQL result found a check-then-read race in the Node trust
guard, despite all three analysis jobs completing successfully. The guard now
opens once, validates the descriptor and current identity, reads through that
descriptor and closes it in `finally`. All 14 trust cases pass, including
replacement and open/stat/read failure controls. Hosted CodeQL resolution is
still required; a successful analysis job alone cannot close its alert.

C25 CI and Docker16 were deliberately superseded. Docker16 retains two
completed native cases, no complete native group and 623 unstarted browser
cases. Its parent and observer were reaped, resources removed and all 3,070
source files preserved. None of that partial execution supplies acceptance
for the next candidate or a deployed-fix claim.

C26 `2210e729` subsequently failed one API call phase: the first-party deadline
inventory found the native default-client TLS probe embedded in a web unit-test
string. The aggregate API failure follows that shard failure; it is not a
second product defect. The correction moves the real probe to a repository
test fixture with a five-second deadline and explicit loopback-only admission.
The application deadline guard and runtime/dependency inputs are unchanged.
All 14 trust cases, 17 adjacent web cases and 23 backend cases pass, including
the unchanged two-case deadline inventory. The first incorrect Vitest launcher
path remains retained as an uncollected setup failure. These focused results
do not replace fresh full gates; old mixed-revision preparation is not current
release admission. Isolated frontend snapshots must also carry the new fixture.

## R22 Production Build Rejection

PR549 merged normally as `d2fd4d00378fd01e51a4538b14b111774fc9f6a3`,
with the exact C27 tree. Fresh main passed 35 CI, 8 Security and 3 CodeQL jobs.
Local Docker18 completed all 3,255 PostgreSQL cases and 623 browser identities:
613 passed, 10 explicit capability skips, zero retries/errors. Both desktop/mobile
PRA-01..08 journeys passed; they do not prove real-owner production MFA.

The first operational launcher failed locally before creating a release
process because a regex overwrote a `$matches` proof array. A fresh local
wrapper renames only that array; all 26 positive/negative controls pass, with
the original failure retained. The canonical deployment script is unchanged.

The actual R22 release stopped in image build, before migration, scheduler
reconciliation or traffic changes. API Cloud Build
`0125c489-c3b8-4002-8d59-3e39158d2692` failed at Dockerfile line31:
`unknown instruction: IMPORT`. The production builder used its legacy parser,
which interpreted the Python heredoc body as Dockerfile instructions. The web
build `4e79c945-3607-4220-821d-d4c44fa6e0cc` succeeded but was not routed.
The deployment parent exited 1 and was reaped. Production remains on 9cf76f2b;
R22 is not a deployed fix or production acceptance certificate.

The correction copies the unchanged CA-removal Python body into a temporary
build script and invokes/removes it with legacy-compatible Docker instructions.
The existing builder, certificate identity checks, unrelated-root equality,
hostname verification and frozen dependencies remain unchanged. A new
two-production-Dockerfile heredoc contract reproduced 1 failure/1 pass before
the correction. Upload-context coverage checks the added build script.
The corrected runtime-base image builds with `DOCKER_BUILDKIT=0`; an offline,
read-only container confirms 148 roots, the denied root absent, TLS/hostname
verification enabled, uv0.13.4 and removal of the temporary script. The moved
policy's Python AST is identical to R22. Actual gcloud upload inventory includes
the script while excluding the local environment and `.venv`. The complete
TLS module plus both new upload checks pass 23 cases/69 phases. The CodeQL
terminal-raise module passes 12 cases/36 phases after its static red case.
Fresh corrected-candidate local Docker, hosted gates, canonical merge/release
and exact-serving browser verification are still required. Open CodeQL NOTE595
on R22 is not a fixed finding; its explicit terminal-raise correction requires
fresh analysis before any resolution claim.
