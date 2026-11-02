# Mobile development checkpoint — 27 October 2026

Public release remains **NO-GO**. This records an intermediate engineering
checkpoint, not completed Android/iOS acceptance or store approval. Earlier
failures and partial native results remain valid within their recorded scope.

## Source and CI boundary

The published draft [PR #558](https://github.com/mishrasanjeev/caseops/pull/558)
is at `6a562336cf5b6cc2a0bc97cab113987bc7ded981`. A fresh read found all 54
hosted checks completed: 52 successful, with the intended staging deploy and
feedback checks skipped. Successful checks include security, both installed mobile platform dependency graphs,
CodeQL, API, PostgreSQL and browser checks. Those checks certify that older
published source. Current main was independently read as
`b9946c71f7e9912d56b5372f2dcfedd3cf82eea6` and merged locally. Its 47 hosted checks pass. These hosted counts were reread on 27 October at approximately 16:38 UTC.

Newer local source through `9f0caec3614f53197cdb503debe750d03a44e0d7`
adds a paginated Matter-task queue, contract-obligation and counsel read context, receipt-only account-deletion
requests, private-content purging after authority loss, Inbox lookup repairs,
a separately scoped native workflow harness, queue/privacy native harness controls, early iOS cache admission and safe diagnostics, and the fpdf2 2.8.8 parser/security repair. It is not yet published or
certified by those hosted checks. The counsel performance candidate is committed
as a development checkpoint and has a known failed adverse-plan result.

## Completed checks and their limits

| Evidence | Recorded result | Boundary |
| --- | --- | --- |
| Mobile source and compiler | 472/472 cases in 33 modules and full mobile TypeScript pass | Controller/mocked TSX and real offline renderer controls do not establish native UI acceptance. The original compiler failure is retained. |
| Web source, compiler and coverage | Complete 9f replacement passes Next type generation, component-inclusive web TypeScript, E2E TypeScript and all 2,022 tests across 251 files. Coverage lines 66.50%, statements 63.19%, branches 57.84%, functions 49.18% | All 3,496 source files and 407 source directories retain exact bytes/metadata; 158.93s within 900s. Original body passed but generated-cache directory drift made its envelope incomplete; retained separately. No browser acceptance. |
| Scoped gateway and fixture controls | 128/128 pass; nine adjacent route tests and four explicitly selected CI contract checks also pass | Synthetic source/FS/protocol controls; no native or real fixture-worker acceptance. Original reporter-format refusal is retained. |
| Integrated schema preflight | All six changed migrations pass against the main revision above; canonical governance map, compiled projection and change gate pass | Source/schema validation; no substitute for the complete database migration journeys. |
| API type generation | Offline OpenAPI and pinned 7.13.0 client generation pass; 831 routes | All 2,256 generator paths remained stable. The summary's `toolPaths: 2` counts its two manifest containers. Generated types are committed. |
| Inbox repair | Complete 100-case Inbox/role-guard replacement passes, including 30 PostgreSQL cases | Earlier, separately guarded API scope. Full integrated API replacement remains due. |
| Contract obligations | Complete historical-catalog/contract SQLite inventory passes 20 cases; integrated PostgreSQL inventory passes all 15 | Historical catalogs and current-head health retain their separate assertions. |
| Account request intake | Complete 77 common cases and eight PostgreSQL privacy cases pass | Includes one real PostgreSQL migration case and an actual old-service disclosure counterfactual. A received request does not perform deletion. |
| Queue access timing | Two actual clock controls and 31 focused temporal cases pass on SQLite/PostgreSQL | Repairs all four earlier grant/wall timing failures. The full 97-case queue inventory has not passed; its 12 performance failures remain open. |
| Adjacent access policy | Complete eight-module inventory passes 195/195: 119 common and 76 PostgreSQL, all 585 phases | Existing statement observers, actual plans, policy composition and work bounds are unchanged. |
| Mac JavaScript dependencies | Fresh official npm advisory reads report zero vulnerabilities in both locks; actual 305 root and 497 mobile installed identities match | No installation occurred; not fresh Linux/Windows or complete release-security acceptance. |
| PDF dependency security | fpdf2 2.8.8 exact lock and installed Mac identity audits are clear; real old-version parser counterfactual fails 10/12 and patched controls pass 12/12; complete affected 313-case inventory plus 13 subtests passes | Official LGPL-3.0-only source/notices are retained and Docker packaging verified statically. Fresh Linux/Windows inventories, shipping images and full security/alert verdicts remain due. |
| Packed read experiments | Counsel prototype passes eight complete DTO/plan comparisons at 158 default / 224 adverse. Queue prototype passes 24 DTO/plan comparisons, maximum 327/400 | The queue experiment full envelope remains incomplete solely because of `.codex` directory metadata drift. Production refresh, old writers, concurrency and current policy remain separate unproved claims; no limit waiver. |

The first integrated 23-case PostgreSQL run passed 21 and failed two test
oracles. A retained viewer cookie correctly took priority over an owner Bearer
credential on the shared HTTPS client; the test now clears the cookie before
switching principal. PostgreSQL also exposes a unique constraint's backing
index. The test now independently verifies exact ordinary-index, constraint and
backing-index maps while retaining full before/after catalog equality. Production
authentication and indexes were unchanged. The complete replacement 23-case
PostgreSQL run and 77-case common run both pass.

The retained exploratory query inventory contains 126 plans, including 63 adverse
probes; 62 exceed 400. One isolated directory point-lookup helper passes at 82
and does not certify a complete page. The covered source-ID-only counsel query
still charges 852. Packed physical read-page experiments were subsequently measured as recorded above. Production implementations are being developed in separate isolated branches; transaction-end synchronization, own-write fallback, old writers, policy, actual PostgreSQL races and complete plans still require acceptance. The immediate-refresh candidate was rejected after source review identified an added membership/audit locking cycle. Shared commit-time synchronization is not yet proven by native or database execution.

The account request records the authenticated global user's own request exactly
once. It does not delete accounts or tenant records, send email, promise a
completion date, or establish a store-compliant fulfillment process. Its audit
belongs outside tenant-exportable audit history.

## Native acceptance remains incomplete

The retained Android/iOS binaries use historical source `8928c0db` and retain
their own hashes and backend receipts. They are diagnostic artifacts, not the
shipping candidate for the newer source or its security repair.

- A prior iOS Files run passed 13 calls and failed one initial text-readiness call, with three unverified calls; those row-scoped results remain retained. The newer complete 17-case attempt on an owned iPhone17 profile ended at its original 30-minute limit: six passing calls, five failed calls, three dependent calls blocked and cases 15–17 incomplete. There are 43 of 51 phase rows, with eight missing. Four failures occurred at uploaded-source admission and one at native Files marker containment. The fixture omitted `filesCache`; the new runner now rejects that omission before native work, and diagnostics keep fixed labels. Original child stderr and the original failed rectangle response were not retained, so these candidate repairs do not establish the exact historical failure cause. No uncertain upload is replayed. All owned sessions/resources were reconciled and the device shut down.
- The latest retained complete Android core attempt has zero passing calls,
  one Firefox entry-readiness failure and 22 blocked calls. A fresh owned 16 KiB
  Android boot has passed browser trust, installed-artifact, original-provider,
  complete public-root and private-baseline checks. A later actual normal
  consent/MFA/principal/workspace/logout observation passed. Its N1 diagnostic
  never ran before the window closed; owned resources closed safely.
- The earlier owned profile's initial OS Files setup timeout is retained separately from its later successful normal setup/authentication. It is now shut down. A fresh independent 9f cache checkout has healthy private dependencies, exact source fingerprint `691d6e236902d4a907493ccf0767052961476b573ce37770dc367d800edc3910` over 140 inputs, and a verified read-only Docker bind. Its sequential local backend build has started under fresh filesystem/inode checks; no new iOS artifact or native acceptance exists yet.
- Final matching binaries still need the complete 23-case core and 17-case
  Files inventories independently on each platform. The new 17-case workflow
  supplement and the separate queue/account-request native cases also need actual evidence. A static
  collection, JavaScript export or unit test cannot satisfy those requirements.

## Remaining development and release work

The Work tab now implements server-paginated Matter tasks with Mine, other
active-Team member and Unassigned semantics, independent date filters and fresh
page/detail reauthorization. Its performance and native acceptance remain open. Existing IP work,
push, physical-device privacy/accessibility/performance and the broader planned
MOB acceptance groups retain their separate implementation/evidence boundaries.

After source writers close, run the full integrated source/API/PostgreSQL/web
checks, repair every failure, freeze the candidate and build both native apps.
Then execute and reconcile every intended native setup/call/teardown phase.
Signing, actual device acceptance and store distribution follow the applicable
owner-controlled enrollment and release requirements.

Organization-first publication is selected for **Orchestrum Technologies LLP**.
The corporate website has been redesigned and remains a private preview, as
requested. The supplied company name, LLPIN and principal address are included;
tax identifiers are excluded. Organization enrollment, D-U-N-S, paid memberships/console access,
final production identifiers, signing, public policies and reviewed request fulfillment are still
external release dependencies. No production deployment, store upload or PR
merge is authorized by this checkpoint.

## Workstation receipts

Receipts are retained under `/Users/sanjeevkumar/.cache/caseops-mobile/`:

- `mobile472-compiler-replacement-b2yshifo/summary.json`
- `integrated-web-compiler-t1s_yv88/summary.json`
- `v1-gateway128-tap-replacement-ylvn10ei/summary.json`
- `v1-integrated-schema-preflight-m9llaqzj/summary.json`
- `queue-integrated-openapi-7npj70bc/summary.json`
- `v1-inbox-roleguards-complete100-0swopp4g/summary.json`
- `contract-obligation-dated-catalog-sqlite20-nw067r5j/summary.json`
- `privacy-common77-principal-index-replacement-hero7dzz/summary.json`
- `fresh-js-advisories-workspaces-9h8s5rik/summary.json`
- `matter-queue-complete70-mounts-xgyk50oq/summary.json` (failed)
- `matter-queue-complete70-mounts-xgyk50oq/temporal-source/temporal-focused-01/summary.json`
- `matter-queue-complete70-mounts-xgyk50oq/temporal-source/integrated-pg23-0790/summary.json` (failed)
- `matter-queue-complete70-mounts-xgyk50oq/temporal-source/integrated-pg23-9ed/summary.json` (replacement)
- `matter-queue-complete70-mounts-xgyk50oq/temporal-source/affected-ip195-9ed/summary.json`
- `account-privacy-private-audit-source-r4z_l555/source-closure.json`
- `counsel-minmax-study-9l4czquj/new-analysis/review.json`
- `counsel-minmax-study-9l4czquj/new-analysis/current-ci-before-packed-prototype.json`
- `android-mac-setup/android-n1-public-window-j63i8nyf/native-window-handoff.json`
- `fpdf-integrated-common-replacement-znses5fp/run/summary.json` (313 cases plus 13 subtests; original incomplete envelope retained)
- `fpdf-patched-whole-python-audit-kg1vbgs6/summary.json` (whole resolved lock and actual Mac installed identities)
- `ios-files-20261026/fresh-files17-8928-prepared-20261027T124708Z/window2-full17-native-handoff.json` (incomplete 17-case native attempt and closed resources)
- `ios-files-20261026/final-native-replay-readiness-20261027T125344Z/security-fixed-native-candidate-plan/candidate-9f-01/web-gate-02/resource-handoff.json` (complete web replacement)
- `ios-files-20261026/fresh-files17-8928-prepared-20261027T124708Z/readiness/candidate-backend-capacity-wrapper-v4/runs/public-admission-02/summary.json` (public admission only; no native acceptance)

The source-bound receipts, complete inventories and original failed artifacts
take precedence over a case name or an aggregate count in prose.
