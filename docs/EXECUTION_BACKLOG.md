# CaseOps Execution Backlog — single source of truth

**This file is the only queue.** If work is not here, it is not scheduled. Every
other planning document is reference or history and must not be read as a queue.

Living document — no date in the filename, updated in place.

## How this works

1. Codex owns every package and works through the final list below in order.
2. There are no manual project approvals, sign-offs, or confirmation pauses
   between packages. The owner proceeds when the preceding dependency is done.
3. Run the required automated checks once after the implementation batch, then
   run exact-release production verification before marking the batch done.
4. Do not create another backlog. New findings are merged into an existing
   package or appended to this list.
5. Status is one word: `queued`, `active`, or `done`.

### Ownership

Codex is the sole implementation owner across backend, frontend, migrations,
tests, documentation, release evidence, and production verification.

**The one coordination rule:** only one package may add an Alembic migration at
a time to prevent revision collisions.

There is no agent handoff, ownership split, review assignment, or confirmation
gate between packages.

## Final work list

The four completed billing/payment defects (`EH-SGR-01..04`) are closed and are
not repeated in the pending list.

| Order | IDs | Required outcome | Owner | Status |
|---:|---|---|---|---|
| 1 | `EH-SGR-07`, `FMB-01`, `FMB-02` | Make citations and source links use real production trust checks. | Codex | active |
| 2 | `FMB-03` | Add indexed full-text candidate selection so search uses the query, not recency. | Codex MIGRATION | queued |
| 3 | `FMB-14`, `FMB-13`, `EH-SGR-12` | Seed registry catalogs and use one normalized office/jurisdiction value for duplicate detection. | Codex | queued |
| 4 | `EH-SGR-13`, `EH-SGR-14` | Use one primary-identifier rule and one terminal-status definition across IP. | Codex MIGRATION | queued |
| 5 | `EH-SGR-16`, `EH-SGR-15` | Remove unsupported messaging choices and add compliant crawler identity/rate behavior. | Codex | queued |
| 6 | `EH-SGR-05`, `EH-SGR-06`, `EH-SGR-08` | Finish shared rate limiting, fail-closed security controls, log redaction, and product-claim cleanup. | Codex | queued |
| 7 | `FMB-08`, `FMB-10`, `FMB-12` | Link every IP record to a Matter and make Matter creation/conflict checks IP-aware. | Codex MIGRATION | queued |
| 8 | `FMB-04`, `EH-SGR-10` | Add IP document filtering and pagination, with batched access checks and no N+1 loading. | Codex | queued |
| 9 | `EH-SGR-09`, `EH-SGR-17` | Turn on useful observability and enforce legal holds/retention in storage operations. | Codex | queued |
| 10 | `FMB-05`, `FMB-06`, `FMB-07`, `FMB-09` | Finish contextual help, structured errors, hearing-calendar bridging, and QA test mapping. | Codex | queued |
| 11 | `FMB-11` | Build provider-neutral clearance search using available public/licensed registries; vendor adapters are optional extensions. | Codex | queued |
| 12 | `T0-4` | Expand the corpus only from public or already licensed sources; unsupported publishers are skipped. | Codex | queued |

## Execution rules

- No manual project approval or sign-off gates.
- No confirmation pauses for reversible implementation decisions.
- Implement the list in order and run checks/tests once at the end of the batch.
- A batch is done only after automated CI and exact-release production checks pass.
- Machine-enforced runtime controls remain for destructive data operations,
  payments, filings, legal-rule activation, tenant isolation, and terminal Matter
  lifecycle changes. These controls protect live data; they do not pause ordinary
  implementation work.
- The IP manifest records coverage and evidence. It is not a second queue.

## Document map

**Queue:** this file, and only this file.

**Reference — analysis, not scheduling:**
`STRATEGIC_GAP_REVIEW_2026-08-16.md` (verified gap analysis),
`FEEDBACK_MERGE_BACKLOG_2026-08-16.md` (feedback mapping),
`OPEN_ITEM_RESOLUTIONS_2026-08-16.md` (decisions of record),
`STRICT_ENTERPRISE_GAP_TASKLIST.md` (`EH-*` evidence ledger),
`PRD_IP_LAW_FIRM_PLATFORM_2026-08-01.md` (IP product contract), and
`ip-implementation/PROGRAM_MANIFEST.yaml` (IPLF slices).

**History — do not schedule from these:** everything else in `docs/`, including
`WORK_TO_BE_DONE.md`, whose corpus and coverage figures are four months stale and
were superseded by the verified gap review.
