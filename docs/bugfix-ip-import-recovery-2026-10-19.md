# BUG-008 Import Review Recovery

## Scope And Classification

**Overall BUG-008 verdict: Inconclusive pending committed exact-serving proof.**
The candidate source implements the bounded review/recovery UX and has focused
local regression evidence; it is not a released or production-certified fix.
Classification: mixed historical missing-context report (cause unconfirmed) and
confirmed raw-warning UX. Do not describe the original backend failure as
reproduced. This is UJ-02/04/26 under J08/M08, IPLF-030/032/037, including
IPLF-UJ-02-NORMAL and EXC-01/03. No new context schema or legal-data default.
This branch is independent of the C6 release and its held Docker/CI gates.

## Retained Evidence

The one-issue workbook `CaseOps_Bugs(l).xlsx` has SHA256
`6f1f91ba7e59632daa8bcc0f24ec259ffc3caba824c9932abe0785f7ea465894`.
Private source rows, screenshots and authenticated parent receipts remain only
in the primary workspace's `outputs/bugs-l-20261019` (O2), not repository
fixtures. No client upload or image URL was fetched or reimported by this task.

Parent `live-read-01` pins API/web to
`9cf76f2b420fcb38a9aaa4b87ac63270bb3c0535` before/after the read. Workspace v3
has `jurisdictions_json=[IN]`, `offices_json=[IP India]`, updated September 30.
Both saved jobs have source SHA256
`d2388a19a569e32cf2cd05ae8b1435807432179fbf1d776a9c08cb1a64d53a14`,
138 original rows: 135 valid and three invalid blank rows.
`source_incomplete_draft` and `source_reference_only` are warnings, not errors.
Job `3fb4ac16-e4eb-4d44-98a1-16f400ae6d66` is committed with **zero created**,
135 `duplicate_skipped` and three blank rows skipped. Never call 135 valid rows
135 created or imported records.

Parent `ui-diagnostic-01/RESULT.json` passed read-only Playwright at 1280/393 on
that exact P: no jurisdiction/office errors; 138 raw specification notes and
81 raw image notes. Job `f1a48bf5-7a76-49f6-9199-ccf08a90e262` was expired,
Refresh preview was visible and Commit was correctly disabled. No document
overflow, page errors, business mutations, provider calls or retained browser
media/auth state. This diagnostic is not committed regression acceptance.

Parent `history-followup-02/RESULT.json` explicitly requested history limit100
and returned all59 owned jobs. Six match the same source hash/filename across
October15/17/19, all135 valid/three blank invalid with no workspace errors.
Earliest `bd0b933c-693f-4a1d-a60c-36aeffe31a3c` at October15 01:45:22 UTC
committed134 creations, one duplicate skip and three blank skips. Later
committed matches created zero and skipped135 duplicates. A separate October15
preview remains pending; it is not a commit. This proves retained successful
validation/creation at least since October15, not the unidentified screenshot's
cause. Parent changed/revalidated/committed none of these jobs. Its first
followup's `status()` versus Fetch `status` error after one public GET is retained
operator evidence, not a product failure; corrected followup02 exited naturally.

## Confirmed Cause And Patch

`imports/page.tsx` rendered errors and warnings together as raw field/code
strings under Validation. The page hid refresh until expiry, although the
existing revalidation endpoint can reread a nonexpired saved original after
legitimate configuration changes. The patch separates Blocking issues from
Non-blocking notes, explains draft/image/default context without inventing
missing facts, and offers the existing refresh command on nonterminal previews.
Context-blocked saved previews have a permission-aware workspace recovery state.
Upload counts are valid source rows, never promised new records. Retained notes
refer to source data and new imports, not a linked record's current lifecycle or
a subsequently corrected date; blank-row wording also fits committed history.
Refresh uses the saved job ID, not a new upload; new duplicate decisions must
still be reviewed. Expiry, valid-row count, token, permission, pending-operation,
terminal-state and duplicate-decision commit fences remain intact.

## Adjacent Paths

- Bulk `_validate_row` preserves `_source_values`/`raw_json`, prefers explicit
  source jurisdiction/office and derives only missing fields from independently
  single-valued `*_json` configuration. Missing/ambiguous values remain errors.
- `_revalidate_ip_import_job_locked` reads each pending row's original `raw_json`,
  rotates version/token and recalculates duplicates. Terminal jobs are rejected;
  already committed rows are preserved. Commit independently rechecks derived
  context and rejects stale changed defaults before canonical writes.
- Manual `CreateTrademarkCard` supplies explicit, editable jurisdiction/office;
  `ManualTrademarkApplicationCreateRequest` requires both. Its form/schema
  validates filing particulars, unlike a deliberately incomplete imported draft.
  No manual defaults, filing readiness or backend schema were relaxed.
- Source specification omission keeps imported particulars incomplete. Image
  references remain text, not downloaded/attached evidence. Unknown blocking
  codes remain visible; optional-date notes never manufacture a date.

## Focused Verification

Base: `a78992bc3e6b10974b348c8009ee3055648bc22e`, branch
`codex/ip-import-triage-20261019`, with this uncommitted patch in the dedicated T.
Evidence: T `outputs/bug008-import-recovery-20261019-01`.

- UI red: four failures/seven passes reproduced missing note/issue groups and
  unavailable nonexpired refresh. All full failure messages retained in JSON.
- UI green: complete page module, 13/13 passed, including skip/link-existing
  source-note truth, admin/nonadmin recovery,
  read-only denial, unknown blocking code, rotated-token commit and expiry fence.
- Native new module: SQLite 2/2 and PostgreSQL 2/2, each six passed phases and
  session completion; absent/ambiguous configuration, unchanged originals,
  explicit-source precedence, draft create/replay, blank skip, duplicate-only
  zero creation. PostgreSQL owns a separate 0.5-CPU PG239 container/database.
- Web and E2E TypeScript checks passed. The initial E2E typecheck caught the
  spec-local missing `errors` type; the type was corrected, not assertions removed.
- Five adjacent native cases/15 phases passed, including expired-preview denial,
  missing-context admission and commit-time rejection of changed derived context.
- Older qualified local `browser-04`: all four original IP13 identities passed, zero skips,
  retries or global errors, at1280/393. Includes actual UI context recovery,
  draft/image notes, create/reload, same-key replay, a fresh duplicate-only commit
  creating zero and persisting after reload, and existing full renewal/batch
  journeys. Start/end byte hashes match for the page, UI/native tests and spec.
  The production-config offline collection remains50 identities/seven files;
  no production test was launched. Configuration mutation is loopback-only.
- Prior browser01 retains all four preauthentication wrapper-origin failures.
  Browser02 retains all four oracle failures: scoped search incorrectly expected
  all application variants; reload text still expected the old warning label.
  It was an intermediate, unsealed source run, not acceptance. Browser03 was
  deliberately stopped before the final human-requested toast correction; it has
  no completion event and remains incomplete. No mutation failure was retried.
- `browser-05` finished naturally with three passed/one failed, stable source,
  no retries/skips/global errors and a complete journal/native report. The mobile
  Refresh assertion reported full-intersection ratio0.987500011920929; it is a
  retained failed run, not the earlier peer's incomplete-at-cutoff observation.
  Its failure preceded rectangle capture. A separate output-only diagnostic on
  identical page bytes reproduced that exact ratio in all three bounded cycles:
  nearest-edge scrolling placed Refresh at y=-0.5 with height40 and an observed
  intersection height39.5 at window scrollY942. Centered scrolling put it at
  y429.5, scrollY512 and ratio1. Ancestor bounds contain its horizontal extent;
  this reproduces fractional viewport-edge positioning, not container clipping.
  The first diagnostic wrapper failed before startup on config-path forwarding;
  its full failed receipt remains alongside the corrected natural-exit0 probe.
- Final `browser-06`: **five passed in two complete files**, four IP13 desktop/
  mobile journeys plus the whole IPLF-030B workflow. Before/after snapshots pin
  ten source/config/helper files; collection and ordered journal start/end IDs
  agree with JSON/XML, with zero retries/skips/global errors and natural exit0.
  Recovery region and controls are explicitly scrolled, retain strict full
  viewport/positive-size/main-area/non-overlap checks, and are captured after
  toast DOM removal without an arbitrary sleep. Deterministic centered framing
  replaces reliance on the browser's nearest-edge scroll placement; pre/post
  control geometry is retained. Region crops now include the actual banner at
  both1280/393. Original screenshot and workflow checks remain.
- The peer P2 oracle is strengthened: exact-number queries before/after repeat
  must equal the first saved docket ID; independent GETs preserve all three
  created dockets, including the optional-C sibling, with identical draft,
  lifecycle/current versions, entire current particulars and original source-row
  IDs. The original source ledger is also reread unchanged after repeat.
  Zero-created/four-duplicate, original-job replay/reload and UI assertions stay.
- Exactly two legacy030B literals change `with warnings` to `with notes`; all
  counts/assertions are unchanged. A fresh all-E2E consumer audit found no other
  stale import summary strings. Its full selected journey passed, not merely
  collection. Production's separate dated inventory remains50/seven files.
- UI module rerun `ui-green-04` passed13/13 after source-context copy clarification;
  frontend and E2E types passed. Nine native results/27 phases are explicitly
  reused from unchanged API-test bytes and unchanged backend owners; no fresh
  native execution/startup hash is claimed. Prior native journals lack embedded
  startup hashes, so this is retained receipt/source correspondence, not a new
  independently pinned native gate. Final peer review remains parent-owned.
- Owned PG239 was stopped/removed after native results. Local Playwright/server
  helpers exited; final closure and patch/source pins are in the evidence receipt.
  Generated `next-env.d.ts` dev-path metadata is excluded from the patch.

Context wording now preserves legitimate multi-jurisdiction/office settings:
only existing unambiguous context can derive missing fields; otherwise correct
values belong in each source row. No configuration collapse is recommended.

No full Docker, cloud, provider, production mutation, workbook edit, push, PR,
main change or deployment is authorized or performed here. New-image full
acceptance and committed exact-release production create/reload/duplicate/notes
proof remain required before any Properly fixed verdict.
