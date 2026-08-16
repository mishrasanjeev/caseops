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

| Owner | Scope | Exclusive files |
|---|---|---|
| **Claude** | Billing correctness, trust predicates (citation + source links), retrieval, notifications | `services/saas_billing.py`, `services/citations.py`, `services/source_actions.py`, `services/authorities.py`, `services/text_chunking.py`, `services/reranker.py`, `services/hearing_reminders.py`, `services/notification_delivery.py` |
| **Codex** | The IP subsystem end to end, IPLF program slices | `services/ip_*.py`, `api/routes/ip_operations.py`, `schemas/ip_*.py`, `apps/web/app/app/ip/**`, `docs/ip-implementation/**` |
| **Either** | Infra hygiene, observability, abuse controls — claim by setting Owner on the row before starting | `core/observability.py`, `core/rate_limit.py`, `infra/**` |

**The one hard rule: migrations are serialised.** Only one agent may add an
Alembic revision at a time. Claim it by putting `MIGRATION` in the Owner cell
here before writing the file. A branch deploy carrying an unclaimed migration
broke a peer deploy on 2026-08-14; that is the failure this rule prevents.

Frontend files follow their owning subsystem. Where a change spans both scopes,
the owner of the **backend** side owns the whole item.

---

## P0 — live defects, wrong in production now

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
| `EH-SGR-16` | Remove SMS/WhatsApp from every selector; mark `roadmap` | Either | queued | resolutions §6 |
| `EH-SGR-15` | Identifying user-agent, `robots.txt`, per-host interval on ingest | Either | queued | resolutions §9 |
| `EH-SGR-05` | Shared limiter store; extend beyond 3.7% of endpoints | Either | queued | gap review §2.5 |
| `EH-SGR-06` | Close the two fail-open controls; add log redaction | Either | queued | gap review §2.6 |
| `EH-SGR-08` | Withdraw or implement the two sold-but-absent claims | Either | queued | gap review §2.8 |

## P2 — IP foundation and the rest

| ID | Work | Owner | Status | Detail |
|---|---|---|---|---|
| `FMB-08` | Always-linked `matter_id`, backfill, then `NOT NULL` | Codex MIGRATION | queued | backlog §2.3 |
| `FMB-10` | Conditional IP Details section on the New Matter form | Codex | queued | backlog §2.3 |
| `FMB-12` | Matter conflict check becomes IP-aware | Codex | queued | resolutions §5a |
| `FMB-04` | IP document filter/search by type + pagination | Codex | queued | backlog §4 |
| `EH-SGR-10` | `/api/ip/documents` unpaginated with N+1 access check | Codex | queued | ledger |
| `EH-SGR-09` | Observability that actually runs; at least one alert policy | Either | queued | gap review §2.9 |
| `FMB-05` `FMB-06` | Contextual help; structured validation errors | Either | queued | backlog §4 |
| `FMB-07` | Bridge tracked-case hearing changes into calendar | Either | queued | backlog §4 |
| `FMB-09` | Map the 27 QA cases onto the repo test-ID convention | Either | queued | backlog §7 |

## Blocked

| ID | Work | Blocked by |
|---|---|---|
| `FMB-11` | External clearance search across registries | Registry data access — vendor decision parked |
| `T0-4` | Corpus expansion shape | Consequence of the no-publisher-licence decision; needs a separate call |

---

## Gates removed 2026-08-16

Removed because they cost time without catching anything:

1. **Waiting for all CI checks on a docs-only PR.** A markdown change cannot
   affect the 10 pytest shards. Merge on the checks that can actually fail for
   it: ruff, secret scan, the data-governance change gate, OpenAPI drift.
2. ~~The duplicate `API (ruff + pytest)` aggregate job.~~ **Withdrawn — it is not
   a duplicate.** It looks like a redundant gate on the shards, but it is also the
   only place that combines the 10 shard coverage artifacts and runs
   `scripts/coverage_gate.py`. Removing it would silently delete the coverage
   gate. Left in place.
3. **Asking for confirmation on reversible documentation decisions.** Decide,
   record the reasoning, mark it reversible, move on.
4. **Multi-pass verification workflows for small factual questions.** Reserve
   the fan-out-plus-critic pattern for whole-repo audits, not single lookups.
5. **Release sign-off ceremony for docs-only changes.**
6. **The two-step `candidate` → `approved` workflow-definition gate.** Seed
   version 1 already approved, with the named approver snapshot (Sanjeev Kumar,
   2026-08-16), rather than seeding a candidate and requiring a second act. The
   audit record is identical; the extra step was not.

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
