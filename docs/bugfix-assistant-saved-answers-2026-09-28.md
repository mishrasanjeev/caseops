# Workspace Assistant saved answers after access changes, 2026-09-28

Follow-up to draft PR #496, which keeps Intelligent Review and Draft manifests
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
