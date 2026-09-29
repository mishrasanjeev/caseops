# Workspace Assistant saved answers after access changes, 2026-09-28

Follow-up to PR #496, which keeps Intelligent Review and Draft manifests
fail-closed after any later relevant event. This change applies the owner's
2026-09-28 decision to the other saved-output path, Workspace Assistant
answers.

## What the code did

`PrivateSavedOutputAccess` rows exist only for Workspace Assistant answers:
`assistant_turn_id` is `NOT NULL` with a foreign key to `assistant_turns`. A
session belongs to the member who created it, so the reader of an answer is
always its author.

- `apply_private_projection_event` marked an answer's rows
  `reauthorization_required` for an `access_changed` event and `locked` for
  every other event.
- `_serialize_turns` called `reauthorize_private_saved_outputs` on every read,
  which served a `reauthorization_required` row while the reader still
  resolved its saved source version, and locked it otherwise.
- The turn list committed nothing. The export and a successful citation open
  committed their decision together with their audit events.
- Events reached saved sources only through the projections of the event's own
  generation. Typed IP records (asset, trademark application, proceeding) have
  no projections, so a docket event never reached them. Neither did a document
  the index no longer held.

The commit that pins this contract (`23b5d757`,
`test_20260928_assistant_reauthorization_contract.py`) proved on SQLite and
PostgreSQL, through the real endpoints and registration path:

- An access change that keeps the author's access (a grant) served the
  document-only answer again on every read. The answer that also saved the
  Matter stayed hidden, because the Matter's version carries its access policy
  version. Whether an answer survived depended on which records it happened to
  save.
- A wall hid both answers, and removing it served the document-only answer
  again.
- An export during the wall locked that answer for good, while a turn-list read
  during the same wall left it to return. The outcome depended on which screen
  the author opened.
- A dispose then reopen locked both answers for good.

## Decision

The owner decided on 2026-09-28:

1. Answers lock for good after any relevant event, access included, as Reviews
   and Drafts do.
2. A read never saves a decision.

## Change

- `apply_private_projection_event` locks, in one set-based update, the saved
  outputs of the event's target and of the records under it, found from the
  canonical tables:
  - a Matter's documents;
  - an IP docket's asset, application and proceeding records, and the IP
    documents linked to the docket or to one of its applications, proceedings,
    events or deadlines;
  - the sources of the projections the event tombstoned, as before.

  It does this for every event type, access included. The Company lock is
  still taken first, by the enqueue. The saved-output update then runs where
  the per-row updates used to flush, before the shadow generations are
  locked, so no lock order changes.
- `private_saved_output_turns_to_hide` replaces the read-time reauthorization
  and writes nothing. An answer is served only while every saved source row is
  `accessible` and still resolves for the reader at its saved version. The
  turn list, the export and a citation open reach the same decision.
- Rows already `reauthorization_required` stay hidden. There is no migration,
  and the check constraint still allows the value.

## Boundaries

- A visibility change that emits no projection event is still judged when the
  answer is read. Examples are team membership, a grant or wall reaching its
  start or expiry time, and a Matter's assignee. The answer is hidden while its
  author cannot read a saved source and shown when they can, which is also how
  Reviews and Drafts behave. Locking on these would need them to emit events.
- Production answers already in `reauthorization_required` become hidden when
  this deploys. Their authors ask again.

## Verification

- **Current contract before the change.** On `main` code, the 4 tests of the
  pinning commit pass on SQLite and PostgreSQL.
- **New contract.** It has 7 tests, each on SQLite and on PostgreSQL:
  - a grant that keeps access locks both answers;
  - a wall and its removal leave both locked;
  - no read writes, and a legacy `reauthorization_required` answer stays
    hidden across the turn list, the export and a citation open, with the
    persisted state fields unchanged;
  - a dispose then reopen locks both answers;
  - a document dropped from the index is still reached;
  - an IP docket event reaches its asset, application and proceeding records,
    and documents linked directly or through an application or a proceeding,
    while an unrelated docket, its document and a Matter stay accessible;
  - one event locks 2 or 60 saved answers with the same number of saved-output
    statements (at most 2).
- **Unfixed commit.** On `23b5d757`, in a separate checkout whose imported
  `private_retrieval.py` was recorded as that checkout's file without the
  change, 6 of the 7 fail on SQLite and on PostgreSQL. The dispose-and-reopen
  test passes there as well, because that behaviour did not change.
- **Fix commit.** On `d47f588b` all 7 pass on SQLite and on PostgreSQL.
- **Browser journey.** `tests/e2e/iplf-066b-assistant-access-lock-2026-09-28.spec.ts`
  runs in the app Playwright suite; its dated name is in the resolved app
  inventory. The owner asks about an indexed document in the browser and sees
  the answer and its citation. The owner then adds an ethical wall on the
  Matter, excluding a colleague, and removes it through the real endpoints,
  while still able to read the Matter. The saved answer stays hidden after
  reload, at 360 px, in two turn-list reads, in the export and for a citation
  open (409).
  - On the fix it passes locally with the three existing IPLF-066B journeys,
    on a Next build made as CI makes it.
  - Against the unfixed API, with the imported module checked through
    uvicorn's `--app-dir` path, the page served the saved answer again, with
    its text and citation, instead of the hidden notice.
  - The production journey has not yet been extended. It depends on one
    exact-release fixture that the release pipeline seeds and then disposes.
    Running an access change in production needs a separately seeded
    fixture, so it is left as a release follow-up. Until the exact release
    passes production verification, this is not a deployed fix.
- **Broad SQLite run.** The 42 test files that exercise private retrieval,
  the Workspace Assistant, Intelligent Reviews, Drafts and disposition hold 823
  tests. On the fix, three workers gave 688 passed and 135 skipped, 134 for
  want of `CASEOPS_TEST_POSTGRES_URL` and one POSIX-only, with 823 collected
  and 823 reported one-to-one.
- **Related PostgreSQL suites.** With the 7 new tests, the private-authority
  lock tests, the legal-hold tests and the 11 private-index tests of
  `test_postgres_validation.py`, including the lifecycle-event lock-order and
  rebuild-race tests, all 29 pass.
- All CI governance validators, including both `check-change` gates, and
  `ruff check src tests` pass.

## Scoped hidden-controls follow-up, 2026-09-29

This follow-up maps to M6, UJ-23/UJ-66 and IPLF-062/IPLF-066. It starts on
`5556e6295bac21b2cd6a19bc5ef26f14357035d4`, directly after the separate
#500 production-proof patch. No private-retrieval/drafting implementation,
shared governance files, cloud resources or remote branches were changed.

The saved-answer decision hid content and citations but still returned the
manifest's `suggested_searches` and `proposed_actions`. Those can contain
private filenames, target labels, URLs and write instructions. Action preview
and confirmation read that manifest directly, and confirmed replay returned
the stored preview without checking the answer. An unchanged writable target
therefore did not prevent a write based on a permanently locked answer.

- `_serialize_turns` now returns both control arrays empty for every hidden
  answer, including legacy reauthorization-required and redacted rows and a
  citation-version mismatch. Visible controls and model metadata are unchanged.
- Proposal lookup uses that same serializer decision. Preview checks both
  before and after the existing tenant/actor locks; confirmation checks after
  those locks and before the confirmed-replay return as well as execution.
  Rejection is a generic 409 `assistant_action_answer_hidden`, without private
  labels or links. No new lock or persisted visibility decision is introduced.
- Turn-list, ask response, export and citation-open all use the shared
  serializer. Citation-open still rejects hidden citations with 409. Source
  manifests, content/hash, citations, saved-access rows and model audit fields
  remain stored unchanged; rejected actions do not change previews or tasks.
- The older changed-target action assertion now expects the earlier hidden
  answer rejection and positively checks its hidden turn and empty proposals.
  Current visible write/confirmation/idempotent-replay behavior stays covered.

Focused regression inventory:

- `test_20260929_assistant_hidden_controls.py`: four hidden-control states,
  with real document navigation plus a retained private-label suggestion,
  visible controls before the change, repeated list/export reads, citation
  rejection and identical retained row fields after reads.
- Its two action cases cache a real task preview, lock only the saved document
  through the real projection-event service while leaving the target unchanged,
  and reject pending execution, a new preview and already-confirmed replay.
  Preview/task/audit state is unchanged after rejection. Visible confirmation
  and replay first succeed in the confirmed case.
- `test_20260929_assistant_hidden_controls_postgres.py` discovers the same six
  cases with the independently isolated PostgreSQL fixture. Execution belongs
  to the parent's combined gate, not this local proof.

Evidence is retained outside the checkout in
`C:/Users/mishr/.codex/worktrees/assistant-access-prod-proof/access-proof-evidence/`:

- `hidden-controls-baseline-20260929.jsonl` and `.xml`: first attempt, six
  fixture assertion failures because the extractive Matter-scoped answer cited
  the Matter rather than the document. This is incomplete reproduction, not
  product evidence; it is preserved, not overwritten.
- `hidden-controls-baseline2-20260929.jsonl` and `.xml`: corrected fixtures,
  six product failures on unchanged `5556e629` code. Hidden filename
  suggestions remained, pending confirmation returned 200 and created a task,
  and confirmed replay returned 200 with private labels and a result link.
- `hidden-controls-baseline-imports-20260929.json` records both imported
  service paths in this checkout before the fix, not the parent's dirty tree.
- `hidden-controls-fixed-20260929.jsonl` and `.xml`: first candidate run,
  20 passed and one old exact-error assertion failed. The full failure was
  inspected and the stricter assertion updated; this is not a green gate.
- `hidden-controls-fixed2-20260929.jsonl` and `.xml`: complete replacement
  selection, 21 passed, zero failed/skipped, in 109.39 seconds. All 63
  setup/call/teardown reports passed and agree one-to-one with the canonical
  collection and JUnit. `hidden-controls-reconciliation-20260929.json` retains
  that comparison and the corrected baseline's six failures. Only existing
  Starlette/httpx and SQLite datetime deprecation warnings were emitted.
- `hidden-controls-fixed-imports-20260929.json` records the candidate's
  service import paths in this same isolated checkout.
- `hidden-controls-collection-20260929.jsonl`: canonical 21-test selection
  across the six new cases, all six existing action cases, seven saved-answer
  contract cases and two original QA/export/permission cases.
- `hidden-controls-postgres-collection-20260929.jsonl`: all six new PostgreSQL
  identities collected, not executed and not certified as passed.

The production follow-up above is historical: `5556e629` already extends the
existing release-owned production journey before disposal, using its seeded
fixture and extractive no-model path. It checks hidden controls after access
change/restore, reload and mobile while retaining terminal reruns. It needs no
new release seed or production company bootstrap. Neither that journey nor
the combined Docker/PostgreSQL gate has been executed by this follow-up.
Deployed verification remains **Inconclusive**, not a deployed-fix claim.
