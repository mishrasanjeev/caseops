# Android And iOS Acceptance Matrix

Date: 23 October 2026. Scope: proposed J20/M22 native client.
All 40 scenario groups below are **Planned / Not run**. They are requirements,
not existing test identities, passed cases or a release certificate. Expand each
group into executable positive/negative cases before collecting the native suite.

## Execution Contract

- Run each applicable native scenario on **Android and iOS separately**. A
  Pixel browser project, responsive screenshot or Android pass is not iOS proof.
- `N`: actual signed/development native app + Appium; `D`: isolated Docker
  PostgreSQL/API with deterministic providers; `P`: physical devices;
  `W`: existing full browser regression/web continuation; `S`: security review.
- Each receipt must identify source SHA, backend SHA, binary hash/version, OS,
  device, scenario identity, start/end, outcome and environment. Redact secrets,
  private records and tokens from screenshots/logs; retain failures unchanged.
- Pin and reconcile intended versus discovered identities and structured results
  including setup/call/teardown. A misspelled file, interrupted run or skipped
  critical journey is incomplete. No retry may turn an unknown mutation into
  false success. Missing native infrastructure is a gap, never a pass.
- Preserve existing full API/frontend/PostgreSQL/security/Playwright gates for
  shared changes and canonical full local Docker acceptance before deployment.
  All automated app calls carry `X-CaseOps-Automated-Test: no-paid-providers`.
- First run against isolated seeded accounts, never production bootstrapping.
  Production acceptance reuses dedicated QA identities and deployed contracts;
  no GBA writes, entitlement rewrites, paid calls or synthetic production leads.

## Planned Scenario Groups

| ID | Scenario and required invariant | Existing PRD mapping | Required environment |
| --- | --- | --- | --- |
| MOB-01 | Correct workspace login; MFA if required; actual person/workspace visible; no primary-account confusion with provider OAuth | J01/J14, M01/M13/M14, US-001/040/042, FT-002/061 | N,D,P |
| MOB-02 | Invalid/revoked/expired invitation and password-reset recovery; safe messages; single-use handoff expiry, PKCE/state and redirect checks | J01/J14, US-001/002/042, FT-002/003 | N,D,S |
| MOB-03 | OTP paste/recovery, local biometric success/failure/enrollment change and app lock; biometrics do not satisfy server step-up | J01/J14, US-042, SEC-003..006 | N,D,P,S |
| MOB-04 | Suspended app/access expiry; rotating refresh, replay, logout and per-device revocation; no still-valid-access-token requirement masking a broken refresh | J01, US-002, FT-003 | N,D,P,S |
| MOB-05 | Tenant change/shared-device logout clears memory/temp data; mixed cookie/bearer and portal/platform/native credentials cannot select the wrong principal | J01/J14, M13/M14, FT-007/061 | N,D,S |
| MOB-06 | Verified links open cold/warm app; forged ID/tenant/return URL, revoked source and wrong-account link fail closed | J01/J03/J14, FT-007, SEC-003..006 | N,D,P,S |
| MOB-07 | Today scope/counts/continuation match defined per-stream ownership, permitted Team and unassigned semantics; no all-visible-to-Mine relabeling | J03/J08, US-005/023, FT-006/007/042 | N,D |
| MOB-08 | Search supported matter code, case/filing/CNR/temporary identifier; exact record and distinct identities survive reload; no invented cross-domain search | J02/J03, M02, US-004/005, FT-004/006 | N,D |
| MOB-09 | Ethical wall, membership/grant revocation and other-tenant search/detail/attachment probes deny labels and bytes, including a screen held open | J03/J14, M13, FT-007/008 | N,D,S |
| MOB-10 | Dispose -> stale phone note/hearing/upload rejection -> authorized retained reads -> controlled web reopen -> stale replay rejection; no phone command reactivates parent | J03/J08, M02/M08, lifecycle contract | N,D,W |
| MOB-11 | Note save is once, parent/version correct, field errors actionable, acknowledgement precedes success and persisted reload shows the same text | J03/J04, US-005/007, FT-006/011..015 | N,D |
| MOB-12 | Transport loses mutation acknowledgement; exact-operation bounded reconciliation if supported, otherwise honest Unknown; zero automatic duplicate submits/retries | J03/J08, US-005/022, FT-037 | N,D |
| MOB-13 | Supported hearing update validates current fields, canonical court/parent, date, version and permissions; audit/result persist without lifecycle change | J08, US-022/023/057, FT-037/038/080/082 | N,D |
| MOB-14 | Date-only legal dates, appointment timezone, midnight, leap day and DST transitions retain intended date/time; no guessed legal recalculation | J08/J10, FT-042, IPLF-030/032 | N,D |
| MOB-15 | Busy agenda includes every event/continuation; filters, overflow, date selection and return position work; no hidden unreachable hearing | J08, US-023, FT-042 | N,D,P |
| MOB-16 | GC obligation opens exact source contract, date and responsible person; missing integration/source is explicit; no local all-contract scan | J10, M09, US-029/030, FT-050/054 | N,D |
| MOB-17 | Entitled IP renewal/date opens correct source docket; unverified rules/dates stay unverified and no entitlement or calendar engine is invented | J08, IPLF-030/032/037 | N,D |
| MOB-18 | Authorized counsel/budget read-through preserves assignment, currency, exact precision and source context; no new spend approval or budget mutation | J13, M12, US-038/039, FT-055 | N,D |
| MOB-19 | Work includes supported undated items and bounded continuation; same source identities/status as Today; access and ordering remain current | J03/J08, US-005/022/023 | N,D |
| MOB-20 | Current draft/recommendation revision and citations are read-only; neutral note/annotation only on proven endpoint; zero request-changes/approve/finalize/execute calls | J04/J07/J09, US-008/018/028, FT-015/028..030/036 | N,D |
| MOB-21 | Existing hearing pack and file open online; page/source/audited source redirect, zoom, reading and return position work; no generation/unsupported download | J04/J08, US-007/025, FT-013..015/039 | N,D,P |
| MOB-22 | Clean camera/file upload on named parent -> scanner -> available attachment; persist exact bytes/identity where policy allows and reload | J04, M03, FT-009/011/013 | N,D,P |
| MOB-23 | EICAR, scanner outage and post-transport access/lifecycle change reject upload; no unscanned available record or generic success | J04/J14, FT-010/012, SEC-003..006 | N,D,S |
| MOB-24 | Denied camera/media permission, file-picker fallback, unsupported format and configured size limit yield usable recovery; no photo-library/contact harvest | J04, FT-009/010, privacy contract | N,D,P |
| MOB-25 | Upload cancel, unknown response, app kill/restart and staging expiry clean owned temporary bytes without duplicate reupload or false Available | J04, FT-009/010 | N,D,P,S |
| MOB-26 | Viewer cache/HTTP headers, memory purge, access revocation, OS backup, reinstall and app-switcher preview do not silently persist private content; external share unavailable | J04/J14, US-007/042, MASVS storage/privacy | N,D,P,S |
| MOB-27 | Bounded authorized inbox is real, not preferences; read/dismiss never completes source work; no sibling-tenant titles/count leakage | J08, US-024, FT-040/041 | N,D |
| MOB-28 | Generic push foreground/background/killed/locked-screen behavior; open reauthenticates and reauthorizes; zero sensitive legal payload | J08/J14, US-024/042 | N,D,P,S |
| MOB-29 | Device-token rotation, denied notification permission, logout/unregister, provider failure and duplicate delivery keep truthful state; app works without push | J08, US-024, FT-040/041 | N,D,P |
| MOB-30 | Test marker propagates through every native/API path; automated court/LLM/PDF/other billable calls are zero and expected rejection is not provider unavailability | J05/J08/J09/J14, provider-cost contract | N,D,W,S |
| MOB-31 | AI disabled/over-budget/revoked-source states block the complete surface; v1 reads do not trigger generation, paid refresh or an uncapped fallback | J07/J09/J14, M06/M07/M14, US-026..028 | N,D,S |
| MOB-32 | 200% text, VoiceOver/TalkBack order, field names/errors, status contrast, non-color cues and reduced motion remain operable | NFT-013, accessibility contract | N,P |
| MOB-33 | Target dimensions/hit areas, one-handed controls, keyboard, safe area, Android Back and iOS back gesture work without hidden essential gestures | NFT-013, UI contract | N,P |
| MOB-34 | Small/large phones, long names/identifiers and tablet split detail retain readable content, useful inputs and visible controls without overlap | NFT-013, J03/J08 | N,P |
| MOB-35 | Offline, slow and failed reads distinguish Empty/Stale/Unknown/Not permitted; no invented freshness; foreground restoration rechecks authority without paid sync | J03/J08/J10, FT-006/042/080 | N,D,P |
| MOB-36 | Killing app while editing does not claim a durable save or restoration of memory-only text; normal navigation warns about unsaved work | J03/J04, US-005/007 | N,D,P |
| MOB-37 | Current/previous supported app clients through additive backend rollout, forced minimum-version boundary and rollback retain security and safe migration behavior | J14/J15, M14/M15 | N,D,W,S |
| MOB-38 | Named-device cold shell/usable work/loaded-tab budgets, bounded rows/query count/payload and no duplicate request fan-out; interruption does not starve unrelated endpoint | NFT-001/005/013/014, performance contract | N,D,P |
| MOB-39 | Dependency/license/SBOM/signing checks; binary/source/backend identities; store privacy, account deletion request and reviewer fake-data access assessed | J14/J15, US-042, MASVS and store gate | N,D,S |
| MOB-40 | Full canonical local Docker + native inventory + green CI/main + exact-SHA compatible backend replay + signed Android internal/iOS TestFlight beta, with all skips/failures reconciled | J20/M22 and existing release gates | N,D,P,W,S |

## User Stories And Traceability

J20/M22 is a native client for existing business journeys, not a new legal domain.
The following namespaced story IDs do not rename existing US/FT identifiers.

- `US-MOB-01`: enter the correct workspace with secure native identity/recovery.
- `US-MOB-02`: see the next authorized work with truthful scope/freshness.
- `US-MOB-03`: find and inspect the exact matter and its retained sources.
- `US-MOB-04`: record one acknowledged update/file against the named parent.
- `US-MOB-05`: inspect calendar, contract/IP dates and counsel context safely.
- `US-MOB-06`: review exact existing evidence without a concealed legal decision.
- `US-MOB-07`: receive optional private alerts and recover honestly from failure.
- `US-MOB-08`: use accessible native Android/iOS controls with testable privacy.

| Stories | Planned scenario groups |
| --- | --- |
| US-MOB-01 | MOB-01..06 |
| US-MOB-02 | MOB-07, MOB-19, MOB-35 |
| US-MOB-03 | MOB-08..10, MOB-21, MOB-26 |
| US-MOB-04 | MOB-11..13, MOB-22..25, MOB-36 |
| US-MOB-05 | MOB-14..18 |
| US-MOB-06 | MOB-20, MOB-30..31 |
| US-MOB-07 | MOB-12, MOB-27..29, MOB-35 |
| US-MOB-08 | MOB-03, MOB-26, MOB-32..34, MOB-37..40 |

## Stop-Ship And Evidence Rules

No release while any critical auth/tenant/lifecycle/upload/cost/privacy scenario
is missing, failed or skipped. An unsupported scope/action must be removed and
explicitly re-scoped, not shown as a working control. Maintain user-visible source
and version restrictions across native and web; do not invent legal fixtures.

Device/app-store access, real push transport, official source data, human OAuth
consent and participant recruitment remain dependencies until actual evidence
exists. Emulators/deterministic transports establish controlled behavior, not
real recipient delivery, native biometrics or a provider's paid operational path.

Validation at plan publication: 40 unique planned groups; **zero executed native
cases claimed**. No Android/iOS build or deployment is certified by this matrix.
