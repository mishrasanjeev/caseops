# Feedback Merge Backlog — 2026-08-16

**Source:** `CaseOps_Feedback_End_to_End_Product_Requirements_16Aug2026.docx`
(founder-supplied, 16 Aug 2026), covering feedback items F-01…F-16.
**Basis:** repository at `ba869fa2` (origin/main), verified by direct code
inspection.
**Purpose:** map every requirement in that document against (a) the code and
(b) every existing plan, and merge whatever is covered by **neither** into the
pending-work backlog.

> The source document names two commercial products as benchmarking references
> (§16, F-08). Those are captured here as a name-free requirement — benchmark IP
> portfolio structure, docket/deadline handling, trademark identifiers and
> search, document organisation, and reminders/reports/navigation — because this
> repository is public and does not record competitor names.

---

## 1. Bottom line

**128 requirements mapped.** Two independent questions were asked of each: does
it exist in code, and is it in any existing plan.

| | Count |
|---|---|
| Already **implemented** in code | 44 |
| **Partially implemented** | 47 |
| **Missing** | 29 |
| Unverifiable / stale-doc | 8 |
| Already **in an existing plan** | 83 |
| **Partially planned** | 31 |
| **Not in any plan** | 14 |

**Most of this document is already covered.** The IP module is ~22.7k LOC of
production runtime and the backend for Application Number, Opposition Number,
mark capture and identifier search is built and tested. The genuinely new work is
tracked as `FMB-01`…`FMB-10` (§4) — the 14 unplanned requirements consolidated,
plus `FMB-10` split out by the §2.3 resolution — alongside 25 items that are
planned only in part (§5).

Three things matter more than the counts:

1. **An apparent conflict with the plan of record turned out to be narrower than
   it looked, and is resolved in §2.** The two documents disagree about the UI,
   not the system of record; the schema already enforces a tenant-safe
   matter link. Four requirements are unblocked by that resolution.
2. **The two "critical bug" items (F-13, F-14) have identified root causes** that
   are deeper than the symptoms reported (§3). Both are P0.
3. **The document's own QA matrix (27 cases) was the weakest part of this
   mapping** and is recorded as a task rather than claimed as done (§7).

---

## 2. The architecture conflict — resolved

### 2.1 What the conflict was

The feedback document asks (§4.2) that the **New Matter form reveal an IP Details
section** when practice area indicates Trademark/IP — IP capture inside the
matter-native flow.

`docs/PRD_IP_LAW_FIRM_PLATFORM_2026-08-01.md` appears to specify the opposite:
*"The top-level Portfolio switch makes `Matters` versus `IP` explicit"* (`:282`),
with the IP workspace as the first screen (`:280`).

This is the pivot for four requirements: `F04-00-ARCH`, `F-04-1` (in-matter
docket view), `F-04-5` (pleadings in Documents), `F01-06-ROWOPEN` (listing row
opens the matter workspace).

### 2.2 Why it is narrower than it looks

Inspecting the schema rather than the prose shows the two documents disagree
about the **UI**, not about the **system of record**:

- `ip_docket_records.matter_id` is already constrained by a tenant-safe
  composite foreign key — `fk_ip_docket_matter_company` on
  `(matter_id, company_id) → (matters.id, matters.company_id)` with
  `ondelete=RESTRICT` (`db/models.py` `IpDocketRecord.__table_args__`). This
  follows the repository's standard tenant-integrity pattern, so an IP record
  cannot point at a missing or cross-tenant matter.
- The only genuine fork is **nullability**: `matter_id` is
  `String(36), nullable=True` (`:14054`), so an IP record may float free of any
  matter.
- The feedback document itself already asserts the matter-native principle at
  §3 — *"Matter remains the central entity. IP/Trademark information becomes
  practice-area-aware data attached to a Matter"* — and at §1 prefers extending
  existing modules over duplicate workflows.

So the PRD's separate workspace is a presentation decision, and the feedback's
requirement is a data-ownership decision. They only collide because the schema
currently permits an IP record with no matter, which satisfies **neither**
document's stated principle.

### 2.3 Decision of record

**The Matter is the system of record. Both entry points are supported.**

1. **Data.** Every IP docket record links to a Matter. Entering from the IP
   workspace creates and links a Matter in the same transaction rather than
   producing an unlinked record. The composite FK already enforces tenant safety;
   what changes is that the product stops producing `matter_id IS NULL` rows.
   Tighten the column to `NOT NULL` only after a backfill establishes that no
   legacy unlinked rows remain — treat nullable as a migration allowance, not a
   supported state.
2. **UI.** Keep the PRD's top-level IP workspace for IP-first users **and** add
   the feedback's conditional IP Details section to the New Matter form for
   matter-first users. Both write the same record through the existing
   `POST /api/ip/dockets` writer, which already accepts `matter_id`
   (`schemas/ip_operations.py:85`).

This unblocks `F-04-1`, `F-04-5` and `F01-06-ROWOPEN` immediately: with the
matter as the system of record, an in-matter docket view and a listing row that
opens the Matter workspace are both well defined.

**Rationale.** Neither document loses. The PRD keeps its workspace; the feedback
gets its matter-native contract. The alternative — resolving in favour of the
PRD alone — would leave IP records that no matter-level permission, audit,
billing or conflict check can reach, which contradicts the repository's own rule
that every persistent business object is tenant- and matter-aware.

**Reversible.** This is a documentation decision, not code. If you prefer the
strict PRD reading (IP as a wholly separate portfolio with optional matter
linkage), say so and §5/§8 re-sequence accordingly — but the `matter_id IS NULL`
state should still be closed either way, because it is unreachable by matter-level
controls.

---

## 3. The two critical bugs — verified root causes

### 3.1 F-13 / F-10 — source links do not open

The reported symptom is that clicking a source does nothing. The root cause is
deeper and has three layers:

- **The trust predicate is unsatisfiable by real data.** The check compares a
  source field against `"official"`, a value the ingest path never writes. The
  test fixture uses that fake value, so **the suite is green while production can
  never satisfy the predicate** (`F13-ROOT-PREDICATE`, `CRITIC-M1`). Fix this
  first; everything else in F-13 is downstream.
- **Ingested judgments carry no resolvable source URL** (`F13-ROOT-INGEST`,
  `CRITIC-M2`). Even a correct predicate has nothing to open.
- **Surfaces disagree on the predicate, and one fails open.** The card fails
  closed while `routes/courts.py:388` derives `verified=bool(row.source_reference)`
  and `:952` uses `bool(row.source_url)` — so an unverified non-official
  reference can pass on the judge profile (`CRITIC-C1`, `F13-PREDICATE-DRIFT`).
  This is security-relevant, not cosmetic.

Resolve as **one** fix: a single helper deriving `verified` from the record, used
by the card, the open endpoint, the judge profile and the recommendations
surface. Then fix the fixture to a value production actually writes.

This is the same failure class as the citation finding in
`docs/STRATEGIC_GAP_REVIEW_2026-08-16.md` §2.7 — a trust signal that is green in
tests and hollow in production. Fix both together.

### 3.2 F-14 — keyword search returns nothing

**There is no embedding-independent lexical retrieval path** (`F-14-7`). Keyword
mode depends on the vector provider, and `embedding_provider` defaults to `mock`
with no checked-in artifact setting it (`STRATEGIC_GAP_REVIEW_2026-08-16.md` §3).
A keyword search therefore has no way to retrieve lexically when the provider is
absent or unconfigured.

**Not in any plan.** Add a Postgres full-text (tsvector + GIN) or trigram index
over authority chunk content and a keyword query builder that uses it, so keyword
mode retrieves candidates lexically rather than silently falling back.

---

## 4. In neither the code nor any plan — new backlog items

These are the answer to "what is in the document that we have not captured
anywhere". Each carries an `FMB-` id for tracking.

| ID | Requirement | Source | Effort |
|---|---|---|---|
| `FMB-01` | Replace the unsatisfiable judgment-source trust predicate with a real signal populated at ingest, and fix the fixture | F-13 | M |
| `FMB-02` | Consolidate all surfaces onto one trust predicate; close the fail-open variant at `courts.py:388` | F-13 | S |
| `FMB-03` | Lexical (FTS/trigram) retrieval path for keyword search, independent of the embedding provider | F-14 | L |
| `FMB-04` | Filter and search IP documents by document type; add pagination and apply filters in SQL before the per-row access check | DOC-IP-03 | M |
| `FMB-05` | Contextual help scoped to the current page/module, with a help affordance in the app shell | F-09 | M |
| `FMB-06` | Structured, machine-readable validation errors carrying field + accepted format, surfaced as plain language | F-09, UX-04 | M |
| `FMB-07` | Bridge tracked-case hearing changes into the calendar surface | F-11 | M |
| `FMB-08` | Enforce Matter as the system of record for IP: always link `matter_id` on create from either entry point, backfill legacy unlinked rows, then tighten to `NOT NULL` (§2.3) | F-04 | M |
| `FMB-10` | Conditional IP Details section on the New Matter form, writing through the existing `POST /api/ip/dockets` writer (§2.3) | F-04 | M |
| `FMB-09` | Map the document's 27 QA cases onto the repo's test-ID convention and close the gaps (see §7) | §21 | M |

Two adjacent defects were found while mapping and are escalated separately
rather than folded in:

- `GET /api/ip/documents` returns **every tenant document unpaginated** with an
  N+1 access check per row. Recorded as an enterprise-hardening gap.
- The IP identifier uniqueness rule is currently **two different rules on two
  fields**: `ip_identifiers` flags duplicates for review, while
  `docket.primary_identifier` is hard-unique per company (`uq_ip_docket_company_identifier`,
  `models.py:14012-14016`) returning 409. The document lists the uniqueness rule
  as TBC — this needs one answer, not two behaviours.

---

## 5. Partially planned — scope extension needed (25 items)

Already in a plan, but the plan does not cover the specific requirement. These
need a scope note on the existing slice, not a new project.

**IP:** registry/jurisdiction as a controlled master (`F04-04-REGISTRY`), a
dedicated trademark view or saved filter (`F01-01-VIEW`), listing filters
(`F01-05-FILTERS`), row-opens-matter (`F01-06-ROWOPEN`), in-matter docket
view/timeline (`F-04-1`, `F-04-3`), IP document type options and metadata
(`DOC-IP-01`, `DOC-IP-02`).

**Hearings:** recipients actually receive the reminder (`F-03-02`) and a delivery
failure never appears successful (`F-03-06`). Both turn on
`hearing_reminders_enabled` and `notification_external_delivery_enabled`, which
default `False` — this is the likely root cause of the reported symptom.

**Statutes:** clickable, source-backed statute references inside **drafting**
output (`BA-DRAFT`) and inside **recommendations/strategy** output (`BA-RECO`) —
distinct from the statutes browser, which is further along.

**UX:** consistent terminology (`UX-01`), useful empty states (`UX-03`),
field-level validation errors (`UX-04`), role-aware onboarding (`UX-05`).

**Knowledge graph:** judgment→court edge (`F-15-3`), matter→entity references
(`F-15-5`).

**Masters and errors:** Document Type as a real master (`MD-04`), Research Source
as a real master (`MD-06`), invalid IP identifier format handling (`E-01`).

---

## 6. Planned but not yet built (16 items)

No action needed beyond sequencing — these already sit in a plan.

Product-guide chatbot (`F-09-01` … `F-09-06`, covered by AI-GUIDE-01..12 /
IPLF-061); Intelligence Review judgment sources (`F10-JUDGMENT-SOURCES`, covered
by AI-REV-01..10 / IPLF-063); advocate/lawyer entity (`F-15-4`) and first-class
knowledge-graph node/edge types (`F-15-8`); opponent field linking to an existing
opposing party (`F04-07-OPPONENT`); statute section-level source seed
(`BA-DATA-SEED`) and the matter Statutes tab source contract (`BA-02-MATTERTAB`);
approved non-government provider hosts (`F13-PROVIDER-HOSTS`); the copy claim
about source coverage (`F13-COPY-CLAIM`); chatbot data-access boundary (`P-05`).

---

## 7. QA matrix — honest status

The document specifies **27 QA cases** (§21: `QA-IP-001..006`, `QA-HR-001..004`,
`QA-RS-001..004`, `QA-BA-001`, `QA-IR-001..003`, `QA-EC-001..003`,
`QA-JP-001..002`, `QA-UX-001..002`, `QA-SEC-001`, `QA-AUD-001`).

**None of them were mapped to existing tests in this pass.** A mechanical
checklist over every identifier in the source document caught this — it was the
one real gap in the mapping, and it is recorded rather than glossed.

Relevant coverage does exist to build on: `test_ip_record_workflow.py`,
`test_ip_prd_slices.py`, two hearing-reminder suites, `test_source_access.py`,
four citation suites, four judge suites, `test_case_tracking.py`, six audit
suites, plus e2e specs including `matter-hearings.spec.ts` and the IPLF series.

`FMB-09` covers mapping each QA case onto the repo's `FT-` / `QG-` / `SEC-`
convention and closing whatever is genuinely uncovered. Do not treat the QA
matrix as satisfied until that mapping exists.

---

## 8. Merged sequencing

The document proposes P0–P5. Reconciled against
`docs/STRATEGIC_GAP_REVIEW_2026-08-16.md`, whose stop-ship billing and citation
findings outrank everything here:

**P0 — correctness, before any pilot.** The gap review's billing defects
(`EH-SGR-01..04`) and citation verifier (`EH-SGR-07`) come first. Then, from this
document: `FMB-01`, `FMB-02` (source-link root cause — same failure class as the
citation finding, fix together), `FMB-03` (keyword search), and the hearing
notification flags (`F-03-02`, `F-03-06`).

**P1 — IP foundation.** Unblocked by §2.3. Order: `FMB-08` (always-linked
matter, then backfill), registry master, identifier UI (IPLF-031B), `FMB-10`
(New Matter IP section), trademark view and identifier search.

**P2 — IP docketing.** Blocked on the approved docket stages and approved
trademark document names, which the document states were not supplied.

**P3 — research and intelligence.** `BA-DRAFT`, `BA-RECO`, `BA-DATA-SEED`,
`F10-JUDGMENT-SOURCES`, `FMB-04`.

**P4 — external integration.** eCourts / research-source integration, blocked on
credentials, licensing and rate limits per the document's own constraint.

**P5 — intelligence and UX.** Knowledge graph edges, `FMB-05`, `FMB-06`, UX
items, advocate identity.

---

## 9. Open items — all resolved

**All ten open requirements are resolved in
`docs/OPEN_ITEM_RESOLUTIONS_2026-08-16.md`, and the three that needed a
commercial decision were decided on 2026-08-16. Nothing here is blocked.**

47 sub-questions were examined against the code; 44 were resolvable without any
external input. Most were not open questions at all — the repository had already
answered 19 of them and constrained a further 26; the answers were simply
undocumented.

**Founder decisions taken 2026-08-16:**

| Item | Decision | Effect |
|---|---|---|
| SMS / WhatsApp | **Deferred for the pilot** | `IN_APP` + `EMAIL` only; both channels removed from every selector and marked `roadmap`. `T1-9` moves out of the pilot window and its fix becomes *removal*, not *implement delivery*. |
| Licensed source display | **No publisher licence** | Allow-list stays official-only; commercial sources deep-link out with the `unverified` badge. The `permitted_uses` in-app path is not built. `destination_class` has two live values, not three. |
| Court-data vendor | **Engineering posture accepted** | Build to the frozen adapter contract; vendor choice stays a configuration change. P0–P3 do not wait on it. |

**Sign-off:** the workflow definition version 1 approver is named — **Sanjeev
Kumar**, 2026-08-16. The approval act itself is a runtime action against a seeded
version 1, applied through the existing approval path so the approver snapshot is
persisted; naming the approver in a document does not by itself produce an
approved workflow version. One scope call remains open and blocks nothing: non-Indian
registries.

**One consequence flagged, not assumed:** the licence decision answers *display
of licensed content*, not *corpus acquisition*. If no publisher licence is taken
at all, `T0-4` corpus expansion runs on official and open sources only — which
changes the shape of that gap rather than closing it.

Resolving these also surfaced **five defects**, now `EH-SGR-12`…`EH-SGR-16`:
duplicate detection that silently under-detects, two disagreeing identifier
normalisations, terminal-status constants that are correct only by luck, an
ingest fetcher sending a spoofed browser user-agent, and notification channels
that are selectable while structurally undeliverable.

## 10. Cross-references

- `docs/STRATEGIC_GAP_REVIEW_2026-08-16.md` — verified gap review; its P0 items
  outrank this document's P0
- `docs/STRICT_ENTERPRISE_GAP_TASKLIST.md` — `EH-SGR-*`, plus the IP documents
  pagination gap recorded by this pass
- `docs/PRD_IP_LAW_FIRM_PLATFORM_2026-08-01.md` — plan of record for IP; §2 is a
  conflict with it
- `docs/ip-implementation/PROGRAM_MANIFEST.yaml` — IPLF-031A/031B, IPLF-061,
  IPLF-063 delivery slices
- `docs/PRD_CLAUDE_CODE_2026-04-23.md` §6.1 — the reconciliation precedent this
  mapping follows
