# Production HTTPS qualification — 2026-11-15

J20/M22, US-MOB-01/02/08, **CX28-LINK-05**. Implementation and native
verification remain **Partially implemented / Inconclusive / NO-GO**.

The existing 83-case platform inventory includes one real signed HTTPS
association case, but its common admission accepts only local QA app IDs and
receipts. The local producer supplies custom-scheme links, and a caller-written
`verifiedAssociation.observed` flag is not OS association proof. Separately,
the submission builder requires the complete native gate before creating the
artifact needed by that case. The November 12 platform-gates note records this
unresolved cycle; it is historical evidence and is not rewritten as acceptance.

This task adds an explicitly non-submittable Android qualification build and a
case-specific signed production-app lease. It preserves all 83 identities,
all 24 client callbacks, local QA app/receipt admission, source and installed
binary fences, original case/serial/cleanup budgets, and all 15 submission gates.
Qualification cannot upload, publish, set a native gate passed, or authorize a
final AAB. Promotion must bind the unchanged qualified artifact and independently
complete current native/source/security evidence.

The production case must independently observe the installed APK identity and
signer, the exact public HTTPS association under default verified TLS, the OS's
verified domain state, and its unforced URL resolver. A package-forced intent is
not positive resolver evidence. Cold and warm opens still require the exact
expected matter readback. The production app uses an independently prepared,
normally authenticated disposable test tenant; its identity must be visible in
native Account. Its credentials, CA and backend are never borrowed from the
isolated local QA fixture. Cleanup restores the local QA app/context even when
the case fails, without replaying a possibly dispatched URL.

First verification uses pure Node/Python negative and composition regressions.
Actual production artifact generation, device execution, full native suites,
signing ownership, independent review, current CI and final promotion remain
required. Earlier source7247 APK/Simulator builds and historical source9d79
qualification artifacts are retained evidence and earn no new-source case credit.

## Implemented source boundaries

`run-android-qualification.mjs --execute` is a separate, explicitly armed local
entry. Its exact 14 shared prerequisite gates cannot contain a fabricated native
pass; the existing final store builder still requires all 15. It derives one
universal APK from the strictly verified signed AAB inside the protected signing
boundary, using the admitted bundletool/aapt2/JDK closure. It transfers verified
ZIP member bytes without reopening their pathname. Qualification results and
embedded source attestations remain non-submittable. No new dependency, licence
exception or attribution is introduced: the existing exact tool/source notices
still apply to a real build and must be retained in its postflight.

The Android-only case lease reads the actual installed APK and independently
checks package/version, embedded source/build policy, actual signer, compiled
strict-transport/autoVerify filter, marked public DAL, current serving revisions,
OS `verified` state, and an unforced default resolver. It issues two package-free
VIEW intents, with cold state and a fresh warm foreground/state witness, and
retains both original exact matter readbacks. Every native action is charged;
late results cannot start the next action. Independent cleanup shares a finite
90-second maximum reserve with the original case/lease deadline, makes at most
three single attempts, and cannot erase a falsy, primitive or frozen original
failure. An expired or lost cleanup acknowledgement stays unverified.

The normal-API producer `android-https-subject.mjs` generates a fresh
`test-native-https-…` workspace and company-domain test identity, persists its
private credentials outside the repository before its single bootstrap request,
and performs normal MFA enrollment/verification, current identity/capability
checks, and exact matter creation/readback. All constructors use the no-paid
marker, strict bundled public TLS roots, finite per-read/whole-operation limits
and no retries. It never edits entitlements, retained roots or the database.
Unknown creation outcomes remain incomplete and must not be adopted by slug.
Its public receipt contains acknowledged routes/statuses and subject IDs, never
passwords, tokens, MFA secrets, QR media or recovery codes. API enrollment is
neither rendered-QR acceptance nor native authentication proof.

`--promote` is a separate all-15-gate operation that performs no build, signing or
upload. It binds the unchanged AAB and derived APK, the actual LINK05 observation,
current source/tool/build/history references, and exact native reports for
23+17+2+24+17=83 cases / 249 phases. It requires each canonical final
summary/result; V1 additionally requires its complete two-stream manifest,
byte hashes, ordering and acknowledged session cleanup/absence. Passing call
rows cannot upgrade failed final evidence closure. Files publishes its result
only after its journal close acknowledges. The promotion explicitly distinguishes
QA suite artifacts from the production LINK05 artifact and cannot transfer a
pass between them. It does not certify the independent physical-device review
or Play-generated APK/signing-key installation path.

## Execution and remaining prerequisites

The preparation, observer, packaging and promotion unit/contract tests exercise
synthetic SDK/API/UI adapters. Their outputs are marked `contractOnly` and cannot
authorize a submission. No production subject, new signed artifact, native case,
store promotion, upload or release was executed by this source task. Fresh
source freeze, current security/CI verdicts, actual builds and both complete
platform suites remain required; prior source7247 results cannot be renamed.

Before Android LINK05, use the producer's new private account for an ordinary
sign-in in the separately installed qualification app, completing its actual
HTTPS callback/PKCE/MFA flow. The local QA browser helper deliberately expects a
custom callback and cannot establish this prerequisite. The observer verifies
the exact principal/workspace through native Account before granting its lease.
Failure of current production capability, policy or authentication admission is
a concrete prerequisite failure; no JSON flag, entitlement patch or retained
production account substitution repairs it.

The iOS callback remains fail-closed: this change supplies no iOS qualification
lease. Apple organization documentation is still in review; Orchestrum's own
Team/signing/provisioning and public AASA/application-prefix association must be
available and independently observed before an iOS equivalent can qualify.
MU-ZERO membership or Android association evidence grants no iOS credit.

## Retained source verification

On the uncommitted M26 candidate, the complete nine affected Node modules passed
312/312 with zero failure, skip, cancellation or todo, and the independent Python
client inventory passed9/9. The separately owned complete build-config module
passed98 with its same2 Windows-only skips; all99 previous titles/statuses were
reconciled and only the new source-closure regression was added. The new modules
are explicitly in CI's existing tooling command and independent file inventory.
These counts do not replace the later frozen complete source/CI gates.

Retained failures include the fabricated-association red test, the original
source-closure count mismatch and stale CI literal inventory, incomplete first
qualification/promotion/producer fixture runs, and the output-boundary red test.
The normalized outside-source guard now refuses root/child and alternate path
spellings before private credential creation/publication. A separate deferred
native-dispatch regression prevents budget charging or a queued microtask from
starting a command after its active/cleanup deadline. Constructor failures prove
marked, authenticated, strict-TLS requests without adding a retry.

The later independent promotion review identified a pinned Git runtime gap:
the source reader executes Git twice, while only the first executable read was
verified. Its retained red regression proved that executable replacement during
a source read could still publish a synthetic promotion. The repair rechecks the
same pinned executable with the canonical bounded descriptor reader before and
after both source-reader invocations, using the unchanged 120-second deadline
and declared byte/source limits. A failed post-read check cannot replace an
original source failure, including falsy or frozen throws. Both actual promotion
call positions and counted pre/post descriptor opens are regressed. The complete
replacement affected selection passed314/314 and independent Python9/9; the
snapshot02/312 result remains retained, superseded source evidence, not a current
freeze or native/store result.

A subsequent complete Android wrapper consumer replay found that its isolated
checkout copied the shared build inspector without the newly extracted SDK XML
parser. The original49-case run retained37 passes and12 missing-module failures;
adding the actual parser to the existing fixture copy restored49/49 passes.
Independent review confirmed identical case titles, assertions and deadlines.
This fixture repair adds no native acceptance credit and still requires the
complete frozen source gate before pushing the candidate.

The 1cab4eb4 CodeQL analysis and separate alert verdict succeeded, but the
verdict retained two maintainability warnings for unused fourth arguments in
the association-verifier tests. The isolated follow-up removes only those two
arguments; the APK verifier's required fourth argument remains unchanged. All
23 qualification cases passed with their original titles and assertions. This
test-only correction does not transfer native acceptance: fresh complete source
gates and hosted CodeQL verification remain required for the follow-up revision.


## 2026-11-15 — normal subject capability contract repair

J20/M22, US-MOB-01/02/08, CX28-LINK-05: **Partially fixed / Inconclusive;
release NO-GO**; the actual producer repair is verified separately from
native/store evidence.
The first real producer acknowledged a fresh bootstrap, then stopped before MFA
because it required an invented `matters:read` capability. A separate normal
sign-in/current-identity/list read confirmed the active owner identities,
`matters:create`, absence of `matters:read`, and a successful authorized matter
read. The actual serving API capability catalogue and matter route use creation
capability plus current tenant/per-record read authorization; the API does not
define the extra read capability. The previous synthetic fixture incorrectly
supplied it. No entitlement, API permission or server behavior changes here.

Both bootstrap and fresh `/api/auth/me` checks now require the canonical
`matters:create`. The unchanged single matter create and authenticated exact
GET readback still require status200, the owned tenant, exact created matter ID,
code and active state before publication. Loss of creation capability on the
fresh identity, a403 read, another tenant or another record remains refused,
retains incomplete evidence, and never retries acknowledged mutations.

Using the real create-only capability fixture against the original producer
retains a complete seven-case red result (6passed,1failed at the impossible
capability check). The repaired complete module passes11/11 with zero failures,
skips, cancellations or todo: all seven original test titles/bodies are retained,
with four refusal regressions added. Evidence is retained under
`native-release-20261111-ZzEIol4V/https-subject-14179-repair-01`; production CLI
and native acceptance are separate from these contract tests. The repaired
default CLI then completed a fresh production subject through all nine marked
normal-API acknowledgements (bootstrap, MFA, current identity, exact new matter
create/readback and unchanged final build), exit0, with no injected dependencies
and `contractOnly:false`. Root evidence
`android-https-qualification-14179de8-01/production-subject-02-actual-default-cli-pass.json`
(SHA-256 `b6fac7e942469de05f7a6d68823fb446184f9436eb8c9bd20865cdffa90b15d1`)
binds the stable repaired producer. The original subject01 remains incomplete,
and its bootstrap was not replayed. This proves API enrollment, not rendered QR,
native authentication, a signed artifact or a native case. The earlier
partially created account/failed attempt and original14179 APK remain historical;
no native result is transferred to this changed source. Both83-case inventories,
all fixed deadlines, no-paid/TLS constructors, no-retry behavior and final store
gates remain unchanged. No dependency or licence changes are introduced.
