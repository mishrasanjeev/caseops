# Operational Reporting And Delegated Report Administration

Status: Partially implemented. No production certification for this extension.

## Historical Compatibility Gate Correction

Candidate `d8ba7fb0` is not release-admitted. Its required CI run
`39401705619` exposed historical worker/compliance failures before their
intended concurrency boundary. A retained PostgreSQL replay surfaces the
actual exception: the current User mapping selects `sessions_valid_after`
from a genuinely older schema that does not contain that column. This is
fixture dependency drift, not proof that the worker arbitration fence failed.

The replacement keeps the physical old schema and frozen source hashes.
Historical reads omit absent User fields only on that isolated engine and
raise on unexpected access rather than invent a cutoff. Regression coverage
must prove the real absence, normal loading outside the scoped fixture and
all original worker, migration and stale-writer assertions. A missed boundary
now exposes its Future exception, early return or still-pending state without
raising the wait budget. The two non-security CodeQL notes are addressed by
explicit `None` reset returns and the public pytest-marker export; no auth
policy, alert dismissal or security waiver is introduced.

Preserve C19's failed CI and incomplete/superseded Docker attempt separately.
Fresh complete replacement CI and Docker acceptance remain mandatory before
merge, guarded exact-main deployment and production replay. Focused green
results and the earlier local browser journeys are not release certificates.

## Why The Release Gate Reopened

- The new global User revocation field changed historical ORM reads. Focused
  console tests did not exercise every older-schema worker and migration
  fixture. Keep the old schema real and prove each affected dependency path.
- The report client duplicated the existing HTTP deadline boundary. Its
  30-second timer was bounded, but this still violated the shared transport
  contract. Share the complete response-consumer boundary, not a headers-only
  wrapper that loses body cancellation or crosses into tenant refresh.
- The production verification step changed without updating all its ordered
  invocation and branch assertions. Repair those complete inventories and
  preserve exact-release prerequisite checks rather than weakening evidence.
- The audit scanner used a substring, confusing the distinct global
  PlatformReportAuditEvent with the tenant AuditEvent constructor. Exact AST
  calls and imported aliases now distinguish them without permitting a tenant
  audit-write bypass. Console own-auth exceptions are exact reviewed paths,
  never a namespace exemption; matching-CSRF/no-session tests retain denial.
- The parent local wrapper itself merged four PowerShell arguments into one
  invalid base directory. All 165 setup failures remain preserved, not relabelled
  as product defects. The corrected wrapper independently records all eleven
  native arguments and requires nonempty complete collection.

The four complete API contract modules then passed 324 tests and 972 phases,
with zero failures/skips and matching JUnit identities in
`outputs/bugs-l-20261019/c20-parent-ci-contracts-02/PARENT-PROOF.json`.
That scoped result is not a complete candidate or production certificate.
Historical rollback must also distinguish its pinned old revision from
current-head index health; require a real later upgrade for the latter.

## October 20 Local Convergence Checkpoint

At 10:50 UTC the replacement's complete five-module backend selection passed
330 tests/990 phases, with all 14 dependency pins unchanged. Four additional
historical/migration modules plus six helper controls passed 43 tests/129
phases, including both court and document rolling variants, retained specialist
evidence, and actual current-head health after the historical rollback. Their
frozen bodies, original wait budgets, physical schemas and cleanup checks held.
The 324-test contract selection above remains separate; overlapping helper
controls must not be counted twice as unique coverage.

The shared response-consumer now owns the console's unchanged 30-second
deadline through body parsing without adopting tenant refresh. Its 220-case
focused selection retains the earlier 188 identities; fresh whole-web coverage
passes all 1,740 tests in 238 files, with no failures/skips/global errors and
unchanged thresholds. The fresh build is `lHuZjDlTO92Kjw8O6IwHF`.
All are pinned, uncommitted local snapshots, not complete release acceptance.
See `c20-complete-modules-01`, `c20-additional-pg-gate-01` and
`platform-shared-deadline-fix-01` under `outputs/bugs-l-20261019/`.

The original C19 result remains NO-GO: all 13 API and 16 native CI shards
reconcile to 9,266 passed/5 failed/3,252 skipped and 3,217 passed/29 failed,
respectively. Hosted web was 1,737 passed, not the earlier 1,722 snapshot.
Docker09 is incomplete with 652 observed passes, one genuine historical
specialist-fixture failure and all 623 browser cases unstarted; its operator
stop is not a replacement result. Fresh committed-candidate CI, complete
Docker10, canonical merge and guarded exact-release production replay are
still mandatory. No production deployment, manager grant or new report batch
is certified by this checkpoint.

## Ownership And Request

Owner request dated October 20, 2026 extends J14/M14, US-040/042 and
FT-060/061. This is operational platform oversight, not a tenant role upgrade
or permission to read client documents, impersonate users, change billing,
invoke paid providers or modify legal records. Existing founder-only platform
administration remains a separate, unchanged authority boundary.

The authorized initial report administrator is `sanjeev@orchestrum.in`.
Only an explicit post-release bootstrap may establish that grant. Never reset
an existing password, fabricate a tenant membership or send a shared password.
There is one unrevoked manager per configured founder root. Invitees are
viewers, not additional managers; enforce this in the database and expose no
arbitrary role/capability input or promotion route.

## Required Outcomes

- PRA-01: Law firms, corporate legal teams and solo lawyers appear exactly
  once in their persisted account category. An unknown category is explicit,
  not silently dropped or relabelled. Account and metric totals reconcile
  across JSON, HTML and plain text, including dormant accounts.
- PRA-02: Dormancy means no evidenced successful human engagement in the
  rolling 30 elapsed days ending at report generation. Use an explicit cutoff
  and timezone in the report. Today counts. Failed requests, automated polling,
  arbitrary row updates and account enablement are not engagement. Unknown or
  future-only evidence must not be labelled inactive. Show those accounts
  expanded with the evidence limitation. Account activation status is separate.
- PRA-03: Dormant accounts remain present in a collapsed, count-labelled group
  in the browser. Email uses progressive markup with complete plain-text and
  markup-stripped fallbacks; do not claim universal email-client collapse.
- PRA-04: A tenant-independent, explicitly delegated report administrator can
  sign in, complete MFA, view the account activity report and existing platform
  financial/usage report types, and inspect bounded account activity summaries.
  No fake company or tenant membership may be used to satisfy authentication.
  The console includes all registered accounts, including QA/internal accounts.
  The existing scheduled email keeps its explicit name-exclusion policy; report
  scope must distinguish these collections rather than misstate either total.
- PRA-05: The initial manager can invite and revoke report-panel users by
  email. Invitees receive reports-only authority, not founder capabilities or
  ordinary tenant access. All reads and administrative changes are audited.
- PRA-06: Expiring, hashed, single-use invitations and password reset links
  support existing and new identities without disclosing account existence.
  Reuse existing password policy, secure credentials and delivery primitives.
  Credential changes and revocation invalidate outstanding access as defined by
  the authoritative session fence. Do not log link tokens or passwords.
- PRA-07: Report sessions have their own token purpose/audience and fresh
  authorization on every request. Tenant, portal and report-admin tokens are
  mutually ineligible for other realms. MFA is required before cross-account
  report access; password reset alone never bypasses MFA.
- PRA-08: Mail delivery claims commit before transport and have bounded crash
  handling. An ambiguous send must not be automatically replayed. No provider
  call may retain a database transaction. Existing four-recipient 07:30 IST
  report settings and zero task retries remain intact.

## Initial Interface Contract

The independent namespace is `/api/platform-console`; browser pages are
`/platform/sign-in`, `/platform/reports`, `/platform/admins`,
`/platform/security`, `/platform/setup` and `/platform/reset-password`.
This contract is being implemented, not a claim that these routes are live.

- `POST /auth/login`: `{email, password}`. Auth responses expose `state`
  (`mfa_enrollment_required`, `mfa_challenge_required`, `authenticated`),
  `expires_at`, and `admin` (`id`, `email`, `full_name`, `role`). Roles are
  `manager` and `viewer`. Secrets/session tokens are not response DTO fields.
- `GET /auth/session`: current auth response. A missing, expired or revoked
  session is 401; an authenticated but insufficient role is 403.
- `POST /auth/mfa/enroll`: limited password-proven session only; returns
  `{secret, otpauth_url}` for initial enrollment, never an existing secret.
- `POST /auth/mfa/verify`: `{code}`; consumes the bounded challenge and returns
  the auth response with a rotated authenticated cookie. A fresh verification
  also establishes the short step-up boundary for administrator changes.
- `POST /auth/logout`: clears this realm only; returns `{status:"signed_out"}`.
- `POST /auth/invitations/complete`: `{token, password, full_name}` accepts the
  one-use invitation. Existing identities must prove their current credential;
  an invitation must not silently replace an existing identity's password.
- `POST /auth/password-reset/start`: `{email}`, always `{status:"accepted"}`
  irrespective of eligibility. `POST /auth/password-reset/complete`:
  `{token, password}`, returns `{status:"complete"}`. Reset never bypasses MFA.
- `POST /auth/invitations/resend`: `{email}`, generic `{status:"accepted"}`,
  explicitly requests a fresh pending setup link after a durable cooldown and
  current root/issuer/target checks. Preserve identity/grant IDs and invalidate
  the old one-use link. Unknown/expired send claims do not cause automatic
  replay; ordinary bootstrap replay still sends nothing. This is not a
  password reset or bypass of initial setup/MFA.
- `GET /admins`: manager-only bounded `{items, next_cursor}` directory.
  `POST /admins/invitations`: `{email, full_name}` creates viewer authority,
  returns `{admin, delivery_status}`. Status distinguishes provider acceptance,
  failure and unknown outcome, never fabricated inbox delivery.
  Repeating an invitation for the same pending viewer returns its existing
  delivery state without sending or replacing the link. Active or revoked
  grants cannot be reset to pending by this creation command. A lost pending
  link uses the explicit cooldown-protected resend route instead.
- `POST /admins/{id}/revoke`: `{reason}`, returns the updated admin record.
  No arbitrary role/capability input, self-revocation or founder mutation.
- `GET /reports/activity`: the canonical activity-report DTO, not raw HTML or
  raw tenant audit payloads. Existing report kinds `overview`, `usage`, `profit`
  and `company-profitability` reuse their canonical read models with bounded
  collection and explicit pagination wherever applicable. A reports-only
  session cannot use the legacy platform-admin routes or tenant routes.

Backend response models and the dedicated frontend validators must implement
the same fields. Authentication uses an independent HttpOnly cookie and a
separate double-submit CSRF pair; browser code must not store bearer tokens or
invoke tenant-session refresh. Setup/reset links carry the token in a fragment;
consume and remove it from browser history without logging or referrer leakage.
Only exact pre-auth routes are CSRF-exempt, never the whole namespace.

## Verification Inventory

Required functional checks: all categories and unknown category, exact totals,
rolling-cutoff boundaries and today's login, missing employee profile,
unknown/future timestamps, dormant expansion, pagination/filtering, all report
tabs, invitation acceptance, reset, login, MFA, revoke and reload.

Required security checks: unauthenticated and wrong-role requests, all token
realm permutations, stale/expired/reused/invalid tokens, concurrent invitation
acceptance and revocation, MFA bypass attempts, enumeration and rate limits,
safe mail failures, audit records, no client-document or paid-provider access,
and preserved founder-only mutations. Verify PostgreSQL constraints and races,
fresh migration upgrade/downgrade and bounded set-based report query work.
Shared HTTP validation must not reflect submitted password/token input or
validator contexts; retain only location, message and error type. This applies
to all RequestValidationError routes, not merely the new console forms.

Required browser checks: committed normally discovered Playwright journeys on
desktop and mobile, including loading, empty, errors, denial, keyboard access,
all actions visible, and fresh page reload. Local Docker uses deterministic
delivery/provider fixtures. Automated production verification must not send
mail, bootstrap accounts, rewrite entitlements or invoke billable providers.
An owner-authorized initial setup email is an operational action, not a
synthetic regression test or proof that its link has been consumed.

## Release And Evidence

The first committed candidate `b239b123` failed its local post-commit migration
change gate before publication or Docker09. Its existing guarded downgrade was
already tested to refuse populated security tables or User revocation cutoffs,
but its annotation did not use the required `restore-forward` policy marker.
The replacement records that exact policy without changing downgrade behavior.
Retain `platform-final-contracts-01` as failed and rerun all 13 contracts on the
replacement commit; a comment correction is not a reused release certificate.

At the October 20 09:24 UTC checkpoint, `platform-pw-local-06` completed both
full desktop and Pixel 5 journeys: **2 passed, zero failed/skipped/retried or
global errors**. The API and freshly built web ran locally with deterministic
transport, not production or Docker. Source hashes held through execution;
both retained-fixture cleanup receipts prove revocation and unchanged founder
provenance. The parent proof is
`outputs/bugs-l-20261019/platform-pw-local-06/PARENT-PROOF.json`.

The replay now proves all six report views and reloads, category/dormancy
behavior, independent MFA sessions, invitation idempotence, viewer setup and
denials, password reset, used-recovery-code rejection followed by an explicit
valid retry, administrator revocation and final reload. Prior failures remain
retained: same-path replacement links, UTC wire serialization and duplicate
invitation delivery were genuine defects; the sign-in email ambiguity was a
test-selector defect. The new actual-client/session integration additionally
reproduced and repaired MFA refusal incorrectly clearing a valid challenge.
Financial displays preserve paise with independent literal regressions.

Scoped current backend evidence is 114 tests/342 phases (complete console
module 112 plus two new native invitation races) and the complete hardened
mail-wrapper module 21 tests/63 phases. Current frontend focused evidence is
188 tests across 30 files with no failures/skips. Whole-web coverage05 passed
1,722 tests in all 237 files, but predates the final three-file MFA change;
it is not relabelled as executing that change. Final hosted whole coverage,
fresh full Docker, canonical main merge, guarded deployment and exact-serving
production replay remain required. This checkpoint remains release **NO-GO**.

The 08:34 UTC local checkpoint is **NO-GO**, not a production certificate.
Current frontend coverage (`platform-web-full-03`) passed 1,698 tests in all
236 intended files with zero failures or skips and unchanged thresholds. The
complete desktop/mobile browser replay (`platform-pw-local-03`) passed the
setup/MFA and activity/overview/usage portions but both journeys then failed
at the populated Profit report: SQLite's persisted UTC dates were serialized
without an offset and the strict client correctly rejected the response.
The original failures, native inventories and retained database/WAL/SHM are
preserved. Profit and Revenue date normalization and the unchanged full
journeys require fresh replay; no partial journey counts as a completed test.

The additional 505-case host preflight was deliberately interrupted to finish
the test-mail wrapper's bounded shutdown and atomic cleanup admission before
sealing the candidate. Its retained phase journal is incomplete, not a passing
gate. Complete final-candidate Docker and hosted CI remain the replacement
release gates; earlier scoped results are not silently combined into a whole
suite certificate.

At the October 20 07:43 UTC checkpoint, C17 `560078fc` is not merge-ready:
CI `39375969217` completed with failures in the signed rate-identity time-boundary
case and notification Company-disable/claim race. Full retained failures are
under `outputs/bugs-l-20261019/ci-c17-failures-01`; neither is waived by the new
console feature. The scoped backend run `admin-backend-final-02` completed
297 tests and 891 phases, and `platform-parent-adjacent-02` completed 117 tests
and 351 phases, without failures or skips. These are local scoped evidence,
not a complete Docker, hosted-CI or production certificate. Further source
changes require the corresponding fresh verification.

Freeze one combined candidate after focused regressions and contract generation.
Run fresh complete local Docker and required hosted CI/security/code scanning;
do not carry an earlier candidate's acceptance. Merge through the normal PR to
canonical main, deploy the exact guarded main SHA and replay the release-owned
production inventory. Bootstrap only the named report manager with an audited,
idempotent, separately admitted operation after migration. Record delivered
versus merely accepted email honestly. Keep pending owner MFA/setup, deferred
external Calendar cleanup and genuine legal-source gaps explicit.

Operator rollback limitation: a runtime predating the User-level session
cutoff cannot enforce that new cross-workspace credential-revocation fence.
Do not certify an older-image rollback after a credential change as preserving
the new security contract. Preserve revocation evidence and roll forward to
a compatible runtime; the populated migration's downgrade refusal is not a
proof that an old application image enforces the new policy.

Both older Excel summaries and BUG-008's summary retain their actual row-level
results and failed history. New results need exact source, environment,
Playwright identities and serving API/web SHA; no unexecuted feature may be
marked Properly fixed.
