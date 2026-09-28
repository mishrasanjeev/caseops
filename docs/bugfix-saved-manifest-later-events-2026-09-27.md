# Saved private manifests after later events, 2026-09-27

Follow-up to PR #490 (`private_saved_source_manifests_are_current`) and PR #492
(Draft lists), found with scratch probes on the PR #492 branch. This is a
fail-closed defect in the saved-output access check, not a production incident.

## Finding

`enqueue_private_projection_event` records the generation that is active when
an event happens. `apply_private_projection_event` tombstones the affected
projections only in that generation (`_affected_projection_statement` filters
`generation_id == event.generation_id`); only the tenant-wide disposition
neutralizes every generation. `activate_private_generation` retires the old
generation without tombstoning anything.

The saved-manifest check trusted the retired generation's rows. Its docstring
said "projection events tombstone affected rows across generations"; that
sentence arrived with the retired-generation path in `ec732f7f`
(2026-09-03) and was never true. So the decision depended on which generation
was active when the output was saved:

- saved in the generation that was active when the event applied: the saved
  row was tombstoned, and the output stayed locked for good;
- saved one generation earlier: the saved row stayed untombstoned, and the
  next rebuild revived the output whenever the event left the source's
  version and hash unchanged and the viewer still passed the current ACL.

## Event producers

Every producer of an access, source or tombstone event, and whether it changes
the target's `private_source_version` (`access_policy_version:updated_at` for
Matters and IP dockets, `sha256_hex` for Matter documents, `current_version`
for IP documents):

| Producer | Event | Target | Target version changes |
| --- | --- | --- | --- |
| Matter restriction, grant add/remove, ethical wall add/remove (`matter_access.py`) | `access_changed` | Matter | yes, `access_policy_version += 1` |
| IP docket restriction, grants and walls (`apply_ip_access_change`) | `access_changed` | IP docket | yes, `access_policy_version += 1` |
| Matter dispose / reopen (`transition_matter_lifecycle_status`) | `tombstoned` / `reindex` | Matter | yes, `updated_at` moves with status and lifecycle version |
| IP docket terminal / reopen (`ip_lifecycle.py`) | `tombstoned` / `reindex` | IP docket | yes, `updated_at` is set |
| New IP document version | `source_changed` | IP document | yes, new `current_version` |
| IP document links changed (`add_ip_document_links`) | `access_changed` | IP document | **no** |
| IP document state transition | `source_changed` | IP document | **no** |
| IP document bulk metadata update | `source_changed` | IP document | **no** |
| Patent disclosure source linked (`ip_patent_families.py`) | `access_changed` | IP document | no; the disclosure filter then drops it from rebuilds |
| Specialist correction and workflow (`ip_specialist*.py`) | `source_changed` | specialist IP docket | not projected: only trademark dockets are disclosed |
| Matter, IP docket, patent and specialist creation | `source_changed` | the new record | no earlier projection exists |
| Tenant data disposition (`data_disposition.py`) | `tombstoned` | tenant | neutralizes every generation |

An event also reaches every projection that carries its target as a scope.
Matter documents are scoped to their Matter and IP documents to their linked
trademark dockets; their versions never change when the parent's access or
lifecycle does. Matter, IP docket and client projections carry only
themselves as scope.

## Can a real flow revive a saved output?

- **Intelligent Reviews and Drafts:** not today. A review captures only its
  target Matter or trademark IP docket, and a Draft copies the review's
  entries. Every producer that targets those sources changes their version,
  and nothing else reaches them. On the unfixed commit a bare event revives
  them (Probe A).
- **Document sources:** yes. `capture_private_saved_source_manifest` accepts
  `matter_document` and `ip_document` sources. On the unfixed commit an access
  grant on a document's Matter, and a dispose then reopen of that Matter, each
  revived a document proof saved one generation before the event (see
  Verification).
- **`PrivateSavedOutputAccess`:** these rows exist only for Workspace
  Assistant turns (`assistant_turn_id` is `NOT NULL` with a foreign key to
  `assistant_turns`); Reviews and Drafts have none. An `access_changed` event
  marks a turn's rows `reauthorization_required`. Every read of the session
  (`_serialize_turns` → `reauthorize_private_saved_outputs`) then decides
  again: the answer is shown when the reader still resolves the same source
  version, and the read does not commit, so the rows stay
  `reauthorization_required`. Real flows reach this. In a scratch probe on the
  unfixed commit, a member asked two sessions about one Matter document; the
  owner walled the member off the Matter through
  `POST /api/matters/{id}/access/walls`, then removed the wall. Both events
  marked the answers' rows `reauthorization_required`, yet the member's next
  read showed the tenant-scoped answer, whose only saved source was the
  document, with its citation. The Matter-scoped answer, which also saved the
  Matter, stayed hidden because both wall changes moved the Matter's
  version. No test covered `reauthorization_required`. This change leaves the
  assistant path alone. On 2026-09-28 the owner decided that assistant
  answers lock for good too and that reads never save a decision; PR #500
  implements it and records the evidence in
  `docs/bugfix-assistant-saved-answers-2026-09-28.md`.

## Decision

Events stay fail-closed in every generation. `AGENTS.md` requires it ("relevant
source, access, or tombstone events remain fail-closed"), the check's own
docstring promised it, and the common case already behaved that way. Before
`ec732f7f` every rebuild or event locked a saved output; that commit relaxed
only the benign rebuild.

The check reads the event ledger instead of tombstoning retired generations:

- It covers events that production has already applied. A write-side change
  would reach only future events and would need a production backfill.
- It adds no writes. Production retains every generation (9,820 eligible
  projections per generation on 2026-09-01), so tombstoning every retained
  copy would multiply each event's writes by the number of retained
  generations, inside interactive access and lifecycle transactions that
  hold the Company lock.
- It keeps `AGENTS.md`'s rule that an ordinary event mutates only its active
  generation, with tenant disposition the only exception, and takes no new
  lock, so the Company-then-generation lock order is unchanged.
- It adds no statement to the Review history or the Draft lists.

## Fix

- `_later_event_reaches_projection` is a SQL predicate: an event exists with a
  higher access or tombstone epoch than the saved row's, for the tenant, the
  row's source, or one of the row's saved scopes. Epochs only grow, and the
  shadow fence rejects any rebuild an event overlaps, so a higher epoch means
  the event came after the row was built. Pending and failed events count.
  Each branch uses the event target index.
- `private_saved_source_manifests_are_current` loads each saved row with that
  predicate in the statement that already loads it, and a manifest with any
  reached row is not current, in whichever generation it was saved. An
  unrelated event or rebuild still leaves an unchanged source current.
- The docstring, a comment on `_affected_projection_statement`, and the
  `AGENTS.md` rule now describe the ledger check.

## Verification

- `apps/api/tests/test_20260927_saved_manifest_later_events.py` (SQLite, plus
  a PostgreSQL wrapper) captures one-source manifests through the capture path
  and saves each twice: in a generation retired by an unrelated rebuild, and in
  the generation active when the events apply. The sources are an unchanged
  Matter; a Matter given a bare `access_changed` event; a Matter given a bare
  `reindex` event; a Matter restricted through the HTTP endpoint (the member
  loses access); a Matter restricted and then granted to the member (the
  member keeps access); and three Matter documents whose Matter gets a bare
  access event, an HTTP grant to the member, or an HTTP dispose then reopen. A
  non-owner member of an unrestricted tenant checks every manifest before and
  after a later rebuild, and each one-manifest decision must equal the batched
  one. Only the unchanged Matter stays current: its retired-generation copy
  throughout, and its copy from the event's generation once the later rebuild
  lifts the active generation's epoch fence. A fresh capture after the
  rebuild is current wherever the member can still read the source.
- On the unfixed commit `6dce1014`, in a separate checkout holding the
  committed test files and whose imported `private_retrieval.py` was recorded
  as that checkout's file without the ledger check, the matrix fails in five
  cells on SQLite and on PostgreSQL,
  all "after a later rebuild, saved before an unrelated rebuild": the bare
  access event, the bare reindex event, the bare access event on a document's
  Matter, the member grant on a document's Matter, and the document's Matter
  disposed and reopened. The two restriction cases hold there too, as Probe B
  found, because the Matter's version changed.
- `test_20260927_review_history_bounded.py` and
  `test_20260927_draft_lists_bounded.py` gain a variant that retires every
  saved generation with a later rebuild before listing. On the unfixed commit
  both fail on SQLite and PostgreSQL: "retired generation, source later
  revoked" is current. A scratch HTTP probe there showed
  `GET /api/research/reviews` listing that review with its detail answering
  200, and both Draft lists listing that draft with reads answering 200. With
  the fix both variants pass, and the history, Matter list and IP list keep
  12, 14 and 13 statements.
- The PostgreSQL volume tests now also retain 10,000 unrelated ledger events
  per generation beside 10,000 unrelated projections, without a manual
  `ANALYZE`, inside the 1,500 ms statement budget with hash and merge joins
  disabled. All seven tests of the three PostgreSQL modules pass on the fix.
- With 30,003 ledger events and 30,024 projections in four generations,
  `EXPLAIN (ANALYZE, BUFFERS)` of the saved-projection statement for a
  100-review page shows each branch of the ledger check as an index scan on
  `ix_private_projection_event_company_target` (the scope branch first reads
  the saved row's scopes by `uq_private_projection_scope_target`): 1.1 ms for
  the whole statement, the ledger subplans included. On that dataset, in one
  process under the adverse statement budget, the member's page alternated
  ten times with the ledger check and ten times with the predicate replaced
  by a constant `false`: medians 0.165 s and 0.196 s, 12 statements each. The
  constant `false` also listed 96 reviews instead of 95, the extra one being
  the retired proof of the revoked Matter.
- The final PostgreSQL run, on a detached checkout of the fix commit whose
  imported module path was recorded, ran those seven tests with the two
  private-authority lock tests, the nine legal-hold tests and the 11
  private-index tests of `test_postgres_validation.py`: 28 of 29 passed. The
  exception was the wall-clock bound (`elapsed < 60`) of
  `test_private_rebuild_ten_thousand_projection_query_budget_and_concurrency_on_postgres`,
  at 89.5 s while its statement bound passed. The rebuild module and that
  test are byte-identical on both commits, and the rebuild never calls the
  changed function. Timed alone, alternating commits while a separate Docker
  acceptance run shared the workstation, it took 53.2 s (unfixed), 48.8 s
  (fixed), 54.3 s (unfixed) and 15.6 s (fixed), all passing; an earlier
  solo fixed run took 65.2 s and failed the same bound. The failure is
  workstation load, not this change.
- The 43 test files that exercise private retrieval, Intelligent Reviews,
  Drafts, the Workspace Assistant, disposition and their migrations hold 820
  tests. The first four-worker SQLite run on the fix reported 678 passed,
  135 skipped and 7 failed. Six were `TimeoutExpired` from Git Bash running
  `deploy-prod.sh` in `test_deploy_prod_hardening.py`, and one was a SQLite
  `disk I/O error` in a migration round trip, all under the load above. All
  seven then passed when run alone. A second complete run with three workers
  on the fix commit's checkout was clean: 685 passed and 135 skipped, 134
  for want of `CASEOPS_TEST_POSTGRES_URL` and one POSIX-only, with 820
  collected and 820 reported one-to-one.
- All CI governance validators, including both `check-change` gates, and
  `ruff check src tests` pass.
