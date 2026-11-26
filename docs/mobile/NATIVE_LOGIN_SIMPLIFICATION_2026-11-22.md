# Native login simplification — November 22, 2026

Status: **local browser flow verified; production and native acceptance
Inconclusive; release NO-GO**.

J20 / M22, US-MOB-01/02/08, MOB-WEB native browser handoff and NATIVE-13.
The user reported that the Play-installed app stopped at “Complete MFA in this
browser session before native sign-in,” then explicitly requested simpler login.
The security requirement remains: enrolled users must complete MFA for the exact
current browser session, user and workspace before native authorization.

## Effective interaction contract

This entry supersedes the old verify-only interaction on the native consent page
as of November 22. Historical tests and evidence remain historical. Previously,
successful code verification instructed the user to select Connect app again.
The replacement is one explicit **Verify and continue** submission: verify the
code, reread the current account/workspace, then request one native grant. The
screen must explain that this action connects the displayed account/workspace.
It must not authorize on mount, timer, digit entry or an uncertain previous POST.

The initial connection action still requires user consent. The final **Open
CaseOps** action remains a separate synchronous user gesture because browser
app-link launch cannot depend on an awaited network request. PKCE, state,
redirect allowlists, exact browser-session MFA, identity freshness, grant expiry
and duplicate-interaction guards remain mandatory. Native code does not collect
the web password or bypass MFA. MFA recovery is an ordinary verification step,
with plain-language copy, a focused enabled field and usable phone-sized targets.

## Current measured baseline

Current main was 1b6ba0f6c7f5306c574f2602d784a9ccbb4fa84b. Both production
web and API public build identities matched it on November 22. The Play-installed
OnePlus app is the Play-signed version 1.0.0 (3), with embedded source 9d79b1ab.
This establishes different binary/web ages, not a measured authentication cause.

The unchanged production-built local web client consumed a real loopback HTTP
RFC7807 native_mfa_required response in four browser viewports. On 360×640 the
Verify control was below the viewport (y658–706); all three mobile inputs were
40px high and focus remained on BODY. At 390×844 and 393×851 the measured
controls were in view. A disabled empty-code button is expected, not a defect.
This diagnostic does not prove a real soft keyboard, Safari, production sign-in
or native acceptance. Original RED and setup failures remain separate.

Evidence root: private native-release-20261111-ZzEIol4V, dated
web-native-mfa-viewport-20261122-02/browser-baseline-01. Actual baseline took
15.142 seconds and intentionally exited 1; its worker was reaped. Raw result
SHA-256 starts 1d2a31c1; independent reconciliation starts 98032baa.

An adjacent client audit found that generic 401 recovery could refresh and replay
the cookie-only native authorization POST with a bearer token. This is a
source-based adjacent finding, not the measured cause of the reported 403.
The canonical /api/auth/native/authorize pathname now bypasses generic refresh
and retry, while preserving its normal sign-in recovery and ordinary API refresh.
Trailing-slash aliases are outside this canonical caller contract.

The original behavior was then reproduced on the **actual production web/API**
with the previously created, owned disposable account and real normal UI login.
Both deployed identities remained 1b6ba0f6 before and after. Native authorization
returned the exact reported typed 403; the production code field was 40px high
and unfocused at 393×851. Real step-up and the subsequent identity read returned
200, and the old separate Connect action returned 200. The Open control became
ready but was not clicked; normal browser logout returned 204. This measures the
recoverable but cumbersome current flow, rather than establishing an APK,
network, CORS or MFA-server defect. It does not certify the reporting user's
account or a native callback exchange. Safe route/status/timing evidence, without
bodies, credentials, IDs or queries, is retained in
`production-native-mfa-browser-20261122-01/proof-01.json` (80301f8a). The sole
actual owner exited 0, its group was absent/reaped, and no retry occurred.

## Verification and remaining gates

The complete API-client unit module passes 36 cases, zero failures or skips,
including native 401 single-request, CSRF, cookie and ordinary-refresh guards.
The first invocation used an incorrect doubled config path and failed before
collection; it is not a failed application case. Corrected command ran from
apps/web with the pinned Node 24.15.0 runtime. Reports are retained separately
under resume-20261122-01/client-retry-regression-02.json.

The complete UI/client unit selection now passes **79 cases (43 UI + 36
client)**, zero failures or skips. Five independently identified retained
callback failures were reproduced first (74 passed, five failed) against the
actual page handlers, then the same 79-case inventory passed. Synchronous live
MFA/code state and terminal-attempt guards prevent old callbacks from repeating
consent, replaying a consumed code or continuing after failed identity checks.
The verification lease spans step-up, current identity and grant response.

The current production-built local browser selection passes **all 14 cases**:
seven stable workflows on phone and desktop, with zero skips or retries. The
new real-HTTP cases cover successful MFA continuation, rejected code and expired
session with zero refresh/bearer replay. The phone project has real mobile/touch
configuration; new journeys use 360×640 and prove enabled-field focus, 44px
minimum targets, visible controls and a hittable verification button. Open is
separate and never launched in this browser-only contract. Exact discovery and
native reporter identities match. Complete source snapshots match from build
through execution; all owned processes are absent and reaped. Both full web
component typing and E2E typing pass.

The corrected explicit-current-checkout native harness selection passes **647
cases with two declared Windows-only skips**, zero failures/cancellations/todos
across all four requested modules. Its strict raw authorization HTTP validator
is unchanged. This is synthetic host harness verification, not 83-case native
app acceptance. Fresh mobile dependency reconciliation proves all 509 selected
installed packages; mobile/CLI security audits and tree-health checks pass.

Evidence root remains private native-release-20261111-ZzEIol4V:

- `s32-mfa-complete-current-verification-04`: complete 79-case green unit report.
- `s32-mfa-live-callback-red-01`: original five retained-callback failures.
- `s32-mfa-complete-current-verification-05`: exact current built-browser 14 pass;
  complete reconciliation SHA-256 starts 12f187b8.
- `20261122-mfa-independent-security-triage-01`: independent live-callback review
  a784c9c5, built-browser review f9f12ec4 and focused harness review 278deab4.
- `native-mfa-harness-20261122-01`: actual current harness attempt05, complete
  649-case reporter inventory, including its two declared skips.
- `s32-mobile-dependency-actual-independent-review-01.json`: current 509-package
  and actual dependency-owner exit/source reconciliation, 20162dc7.

Preserve setup/test failures rather than relabeling them: the first combined
unit runner used browser-fixture environment variables and produced six client
failures; the unchanged complete selection passed with canonical unit settings.
The first 14-case browser run had ten passes and four locator failures because
Next's empty global route announcer also has role alert. Scoping assertions to
the authentication main landmark preserves the intended checks; the complete
replacement 14 passes. The first harness 507 pass ran in the older default
checkout and its incorrect current-source proof is explicitly withdrawn. The
actual current harness first had two stale fixture failures; complete attempt05
passes after updating those exact choreography fixtures. A zero-case screenshot
selection is retained as unexecuted; a distinct one-case phone replay supplies
only the synthetic Open-ready screenshot, not additional release case credit.

Canonical whole-API Ruff lint and all four governance/migration validate and
branch-change preflights pass. Complete current-source gates, CI, deployment and
real Android/iOS acceptance remain outstanding. No new 83-case platform pass,
signed store artifact or production login repair is claimed.
The two intentional nested diagnostic exception handlers also receive their
previously reviewed explanatory comments; no runtime behavior changes there.

Play Console confirms the existing Android production release was published
November 17. Managed publishing was enabled November 22 to hold future updates;
the existing public version was not unpublished. No new build has been uploaded
or released by this checkpoint. The authenticated Apple Developer account
currently says Orchestrum Technologies LLP (Pending), enrollment GZQJ2D9M4N is
being processed. No new sign-in or agreement action was needed. Distribution
signing remains unavailable; the Mac has no local code-signing identity or
provisioning profile at the fresh census. Simulator work can continue separately.

## Live web update and actual production browser proof

The preceding predeployment statements are historical. PR642 merged at
`6cdbe7915e1d1d16522d3d2ec716fa05deb87c0d`. Its immutable web image
`sha256:ee3b235eeb5d4bb3458d52844ee400ae403235c48c753699185374970a852c93`
is serving100% traffic in `caseops-web-login-6cdbe791`. Marked public identity
checks confirm the exact revision. Unrelated web settings and the whole API
service specification are unchanged. The API stays at1b6ba0f6. This is a scoped
web login rollout, not a paired API or native binary release.

The actual production browser journey passed using the existing owned disposable
QA account: login200, account200, native authorization403 with the expected MFA
requirement, one step-up200, fresh account200, automatic authorization200, and
logout204. Open CaseOps became ready without another Connect. Verify and input
targets were48px and visible, and the field was focused. The worker took4.413s
and its owner6.061s; both actual exits were0 and the owned process group was absent.
All35 browser requests carried the no-paid marker; the seven auth journal rows
are not a count of all requests. No credentials, response bodies, MFA media,
screenshots, traces or videos were retained.

Proof is `production-native-mfa-hotfix-20261122-01/proof-01.json`, SHA256
`791d71f81caeb5db991ba612a56e67dff2c4c67a98320b11ee46f6f95600a62d`,
with separate actual-parent and independent-review receipts. The journey did
not open the callback or exchange its token. Reporting-user/physical callback
and complete native acceptance therefore remain **Inconclusive**, not properly
fixed by attribution from a different account or browser surface.

Both hosted web platforms passed; Linux reconciles316 modules and3268 cases,
including web/E2E typing, Next build and Docker builder. Canonical main Security
run45008715739 passed8/8 jobs; CodeQL analyses and the independent alert verdict
also passed. Remaining main API/PostgreSQL CI is still separate and pending at
this checkpoint. Do not claim a completely green release from these subsets.

Fresh signed-in Play Console shows existing CaseOps1.0.0(3) at100% production
rollout, no unpublished changes and an empty ready-to-publish list. The existing
binary consumes the web login update without reinstall. Managed publishing
remains on for future updates. Actual passive device checks verify code3 with
Google Play as installer on the connected OnePlus, whose screen is currently
off and locked; no callback acceptance is inferred. Its existing official Google
SDK33.0.3 server was independently verified against Google's byte-exact archive,
then used with its matching client without a restart or phone changes.

The signed-in Apple account still shows enrollmentGZQJ2D9M4N Pending, with no
additional owner action requested. No iOS distribution archive or submission
exists. Current-source native tooling/builds and independent full83-case platform
suites continue separately from this live web update.
