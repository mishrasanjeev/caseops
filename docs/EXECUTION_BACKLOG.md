# CaseOps Execution Backlog — single source of truth

**This file is the only queue.** If work is not here, it is not scheduled. Every
other planning document is reference or history and must not be read as a queue.

Living document — no date in the filename, updated in place.

---

## How this works

1. **One queue, one owner per item.** Ownership is exclusive: two agents never
   hold the same item.
2. **Detail lives elsewhere.** Each row points at the document that carries the
   analysis. Do not restate it here.
3. **No new backlog documents.** New findings append a row here and, if they need
   analysis, a section in an existing reference doc. The proliferation this file
   replaces (100 docs, 16 ID namespaces, 369 ids) is what it exists to stop.
4. **Status is one word:** `queued`, `active`, `blocked`, `done`.

### Ownership split

| Owner | Scope | Exclusive paths / collision rule |
|---|---|---|
| **Claude** | Non-IP billing/payments, trust predicates, retrieval, notifications, security and observability | Exact `EH-SGR` path groups below. |
| **Codex** | The IP subsystem end to end, IPLF program slices | `apps/api/src/caseops_api/services/ip_*.py`, `apps/api/src/caseops_api/api/routes/ip_operations.py`, `apps/api/src/caseops_api/schemas/ip_*.py`, `apps/web/app/app/ip/**`, `docs/ip-implementation/**`. |
| **Serialised shared** | Cross-scope persistence and generated artifacts | `apps/api/src/caseops_api/db/models.py`, `apps/api/alembic/versions/**`, shared Matter/form files, and `apps/web/lib/api/{endpoints,openapi-types}.ts`. The active queue row names one claimant before editing; these paths are never edited concurrently. |

**The one hard rule: migrations are serialised.** Only one agent may add an
Alembic revision at a time. Claim it by putting `MIGRATION` in the Owner cell
here before writing the file. A branch deploy carrying an unclaimed migration
broke a peer deploy on 2026-08-14; that is the failure this rule prevents.

Frontend files follow their owning subsystem. Where a change spans both scopes,
the owner of the **backend** side owns the whole item. The ownership rule
coordinates parallel implementation; it is not a review or confirmation gate.

Exact `EH-SGR` collision map:

- **Claude — `EH-SGR-01..04`:**
  `services/matter_billing.py`, `services/matters.py`,
  `services/portal_outside_counsel.py`, `services/pine_labs.py`,
  `api/routes/matter_billing.py`, `api/routes/matters.py`,
  `schemas/matter_billing.py`, `schemas/billing.py`, and the Matter billing UI.
- **Claude — `EH-SGR-05..09`, `EH-SGR-15..16`:**
  `core/rate_limit.py`, `core/csrf.py`, `core/observability.py`,
  `services/inbound_email.py`, `services/citations.py`,
  `services/recommendations.py`, `services/litigation_strategy.py`,
  `services/drafting.py`, `services/source_actions.py`,
  `services/authorities.py`, `services/text_chunking.py`,
  `services/reranker.py`, `services/court_sync_sources.py`,
  `services/hearing_reminders.py`, `services/notification_delivery.py`,
  `services/saas_billing.py`, their corresponding routes/UI, the API image/deploy
  configuration for `EH-SGR-09`, and `apps/web/components/marketing/Security.tsx`.
- **Codex — `EH-SGR-10..14`:** `services/ip_documents.py`,
  `services/ip_records.py`, `services/ip_identifier_rules.py`,
  `services/ip_operations.py`, `services/ip_lifecycle.py`, their IP routes,
  schemas and UI.

All service paths above are relative to
`apps/api/src/caseops_api/`. Shared persistence/generated paths remain subject
to the serialised-shared row in the table; they are not implicitly owned by both
agents.

---

## P0 — defects in production-capable paths

These rows block activation or pilot use of the affected workflow until fixed;
they do not block unrelated repository implementation.

| ID | Work | Owner | Status | Detail |
|---|---|---|---|---|
| `EH-SGR-01` | Intra-state invoices issued with IGST instead of CGST+SGST; place of supply never reaches the tax engine | Claude | queued | gap review §2.1 |
| `EH-SGR-02` | Matter permanently unopenable — OC-portal invoice and refund webhook write a status the read schema rejects; `GET /api/matters/{id}` 500s forever | Claude | queued | gap review §2.2 |
| `EH-SGR-03` | Payments under-credited — multi-attempt invoices credit only the largest attempt; webhook reads amount as 0 from the nested payload | Claude | queued | gap review §2.3 |
| `EH-SGR-04` | Invoice numbering not gapless, not concurrency-safe, not immutable | Claude MIGRATION | queued | gap review §2.4 |
| `EH-SGR-07` + `FMB-01` + `FMB-02` | Trust predicates. **One fix, not three** — citation verifier and source links are the same failure class: green in tests, hollow in production | Claude | queued | gap review §2.7, backlog §3.1 |
| `FMB-03` | Keyword search has no lexical retrieval path; depends on an embedding provider that defaults to mock | Claude | queued | backlog §3.2 |

## P1 — decided, cheap, unblocked

| ID | Work | Owner | Status | Detail |
|---|---|---|---|---|
| `FMB-14` | Seed all registries, Indian and foreign | Codex | queued | resolutions §5 |
| `FMB-13` | Duplicate detection keyed on `jurisdiction`, not `office` | Codex | queued | resolutions §5a |
| `EH-SGR-12` | Normalise `office`/`jurisdiction` before duplicate-detection use | Codex | queued | ledger |
| `EH-SGR-13` | One identifier normalisation — derive `primary_identifier` from the ledger row | Codex MIGRATION | queued | resolutions §3 |
| `EH-SGR-14` | One terminal-status constant shared by the IP modules | Codex | queued | ledger |
| `EH-SGR-16` | Remove SMS/WhatsApp from every selector; mark `roadmap` | Claude | queued | resolutions §6 |
| `EH-SGR-15` | Identifying user-agent, `robots.txt`, per-host interval on ingest | Claude | queued | resolutions §9 |
| `EH-SGR-05` | Shared limiter store; extend beyond 3.7% of endpoints | Claude | queued | gap review §2.5 |
| `EH-SGR-06` | Close the two fail-open controls; add log redaction | Claude | queued | gap review §2.6 |
| `EH-SGR-08` | Withdraw or implement the two sold-but-absent claims | Claude | queued | gap review §2.8 |

## P2 — IP foundation and the rest

| ID | Work | Owner | Status | Detail |
|---|---|---|---|---|
| `FMB-08` | Always-linked `matter_id`, backfill, then `NOT NULL` | Codex MIGRATION | queued | backlog §2.3 |
| `FMB-10` | Conditional IP Details section on the New Matter form | Codex | queued | backlog §2.3 |
| `FMB-12` | Matter conflict check becomes IP-aware | Codex | queued | resolutions §5a |
| `FMB-04` | IP document filter/search by type + pagination | Codex | queued | backlog §4 |
| `EH-SGR-10` | `/api/ip/documents` unpaginated with N+1 access check | Codex | queued | ledger |
| `EH-SGR-09` | Observability that actually runs; at least one alert policy | Claude | queued | gap review §2.9 |
| `FMB-05` `FMB-06` | Contextual help; structured validation errors | Claude | queued | backlog §4 |
| `FMB-07` | Bridge tracked-case hearing changes into calendar | Claude | queued | backlog §4 |
| `FMB-09` | Map the 27 QA cases onto the repo test-ID convention | Claude | queued | backlog §7 |

## Blocked

| ID | Work | Blocked by |
|---|---|---|
| `FMB-11` | External clearance search across registries | Registry data access — vendor decision parked |
| `T0-4` | Corpus expansion shape | Consequence of the no-publisher-licence decision; needs a separate call |

---

## Gates reviewed 2026-08-16

Procedural gates were removed where they cost time without protecting product or
data integrity. Enforcement gates that catch real failures remain:

1. **Waiting for unrelated runtime checks on a docs-only PR.** A documentation
   change can affect focused documentation-contract tests (including
   `test_gap_review_factual_contract.py`), links, secret scan and data-governance
   checks, so those still run. It need not wait on unrelated runtime shards when
   repository policy can distinguish them.
2. ~~The duplicate `API (ruff + pytest)` aggregate job.~~ **Withdrawn — it is not
   a duplicate.** It looks like a redundant gate on the shards, but it is also the
   only place that combines the 16 shard coverage artifacts and runs
   `scripts/coverage_gate.py`. Removing it would silently delete the coverage
   gate. Left in place.
3. **Asking for confirmation on reversible documentation decisions.** Decide,
   record the reasoning, mark it reversible, move on.
4. **Multi-pass verification workflows for small factual questions.** Reserve
   the fan-out-plus-critic pattern for whole-repo audits, not single lookups.
5. **Release sign-off ceremony for docs-only changes.**
6. **Workflow-definition approval is retained.** No active workflow definition
   or version is seeded. Version 1 must first be seeded as `candidate`, then a
   real approval must run through the approval path so the approver identity,
   authority and timestamp snapshots are persisted. Naming Sanjeev Kumar in a
   document resolves who may approve; it does not perform that runtime act.

### Kept, deliberately

Four, each because it caught something real this session:

- **Fail-closed product controls** — citation verification, conflict checks,
  terminal lifecycle guards, tenant isolation. Three of these are *already broken*
  and are the P0 work above. Removing them would delete the thing we are fixing.
- **Secret scan and the data-governance change gate** — both caught genuine
  omissions in this branch.
- **Prod verification before marking a bug fixed** — this is the rule that
  stopped the reopen cycle. It is the reason the Ram batch closed.
- **Serialised migrations** — a peer deploy has already been broken once.

---

## Document map

**Queue:** this file, and only this file.

**Reference — analysis, not scheduling:**
`STRATEGIC_GAP_REVIEW_2026-08-16.md` (verified gap analysis),
`FEEDBACK_MERGE_BACKLOG_2026-08-16.md` (feedback mapping),
`OPEN_ITEM_RESOLUTIONS_2026-08-16.md` (decisions of record),
`STRICT_ENTERPRISE_GAP_TASKLIST.md` (`EH-*` evidence ledger),
`PRD_CLAUDE_CODE_2026-04-23.md` and `PRD_IP_LAW_FIRM_PLATFORM_2026-08-01.md`
(product contracts), `ip-implementation/PROGRAM_MANIFEST.yaml` (IPLF slices).

**History — do not schedule from these:** everything else in `docs/`, including
`WORK_TO_BE_DONE.md`, whose corpus and coverage figures are four months stale and
were superseded by the verified gap review.
