# PRD: Bench Mapping + Bench-Specific Drafting

Status: **Draft for review** (2026-04-25, mishra.sanjeev@gmail.com).
Approval gate: this PRD must be accepted before any of the slices below
are implemented. Per the bench-strategy memory, do not start
implementation on speculation.

This is a depth extension to:

- Journey `J06` — Court, judge, bench, and tribunal intelligence
  (`docs/PRD_CLAUDE_CODE_2026-04-23.md` §10.J06).
- Module `MOD-TS-001` — JudgeProfile (currently Implemented; this PRD
  adds career history + bench → judge resolution).
- Module `MOD-TS-001-A` — Appeal Strength Analyzer (this PRD adds
  bench-specific authority injection on top of the existing court-
  scoped context).

---

## 1. Why this PRD exists

The 2026-04-25 user smoke caught a real product gap surfaced when SC +
Delhi HC judges went live: `/app/courts/{id}` shows judge names and
their authored judgments, but the system does not know:

1. **A judge's career history across courts.** The `Judge` model has a
   single `court_id` FK, so when Justice X is elevated from Bombay HC
   to SC the prior court rows are gone. The user asked: "are
   ex-judge benches mapped?" — today, no.

2. **Which Judge rows back a `MatterListing.bench_name`.** The
   cause-list scrape stores bench rosters as free text
   ("Justice A.S. Chandurkar & Justice X.Y.Z."). They are not
   resolved into `Judge` FK rows. So we cannot ask "what has THIS
   bench held in similar matters?"

3. **Bench-specific authority injection on appeal drafting.** BAAD
   currently injects court-scoped context (every authority from the
   matter's court). The user's ask: when an appeal is being drafted
   for a matter whose next listing is before a specific bench, the
   prompt should carry the citations + reasoning patterns of THAT
   bench, not the whole court.

4. **Tolerant judge name matching.** Authority Layer-2 metadata
   (`AuthorityDocument.judges_json`) tags each judgment with a
   judges array. Matching that against `Judge.full_name` is ILIKE
   today, which fails when one source has "Justice A.K. Sikri" and
   the other has "Justice Adarsh Kumar Sikri".

---

## 2. What is explicitly NOT in scope

The bench-aware drafting hard rules from `CLAUDE.md` and the
caseops-prd-execution skill apply. This PRD does **not** introduce:

- Judge favorability scoring, win-rate, or "this bench is friendly to
  bail" claims.
- Win/lose/probability/predict/outcome language anywhere on the
  bench-aware surface.
- Reputation-based judge ranking, sentiment tags, or
  pro-petitioner/pro-respondent labels.
- Wikipedia-sourced data. All judge career history must come from
  sci.gov.in (for SC) or the official HC website (for HC judges).
- Speculative "the bench will likely rule" copy. All bench-specific
  output must be evidence-phrased and citation-backed.

If a slice below appears to violate any of these rules, the slice is
wrong and must be rewritten before merge.

### 2.1 Advocate-bias selection IS in scope (per user memory)

The user has explicitly asserted (memory
`feedback_user_bias_in_recommendations.md`, 2026-04-20, reaffirmed
2026-04-25 during this PRD's review):

> *"We need to favor the users by giving them draft appeal or hearing
> material with citations and proof based on bench/court they are
> going to appear. Without favoring this is not possible to do."*

Reconciliation with §2:

| Pattern | Verdict | Why |
|---|---|---|
| Selecting authorities from the bench that **support** the user's grounds of appeal | ✅ allowed and required | This is what every advocate does. CaseOps is a tool for the user's side, not a neutral encyclopedia. |
| Citing a precedent and explaining how it advances the user's case | ✅ allowed | Evidence-grounded, transparent, verifiable. |
| Skipping authorities that hurt the user's case (no requirement to be balanced like Wikipedia) | ✅ allowed | Per the user-bias memory; the lawyer is responsible for adverse-authority duties to the court, not us. |
| "This bench has held [supporting principle], cite: [judgment]" | ✅ allowed | Evidence-phrased, verifiable. |
| "This bench grants 67% of bail applications" | ❌ forbidden | Favorability statistic — banned by bench-aware drafting rules and PRD §10.6. |
| "This bench tends to be liberal on bail" | ❌ forbidden | Tendency claim without per-judgment citation. |
| "You have a 70% chance of winning" | ❌ forbidden | Outcome prediction. |
| Including the strongest cases from the bench AND quietly omitting the weakest | ✅ allowed | Citation selection is editorial; it's how advocates draft. |
| Suppressing a citation we know goes against the user without a flag | ⚠️ contested | Better behaviour: tag adverse-authority hits as "Adverse — review before cite" rather than silently drop. Slice C MUST surface these so the lawyer makes the duty-to-court call. |

The structural no-favorability test sweep stays in place — it scans
for the forbidden token list (win, lose, favourable, tendency,
probability, predict, outcome). Advocate-bias selection works WITHIN
that constraint by choosing which evidence-phrased citations make it
into the prompt, not by writing favorability copy.

---

## 3. Slices

Four slices, each shippable independently. Slices A and B are the
foundation slices; C and D depend on A and B respectively.

### Slice A — `MOD-TS-001-B` JudgeAppointment career history

**Status:** `Queued`.

**Scope:**

- New `judge_appointments` table:
  - `id` (uuid)
  - `judge_id` (FK `judges.id`)
  - `court_id` (FK `courts.id`)
  - `role` (string: `puisne_judge` | `chief_justice` | `acting_chief_justice` | `additional_judge` | `judge_supreme_court`)
  - `start_date` (date, nullable when source is silent)
  - `end_date` (date, nullable for current appointment)
  - `source_url` (string — sci.gov.in or HC profile page)
  - `source_evidence_text` (text — the exact sentence we parsed,
    e.g. "Elevated as Additional Judge of the Bombay High Court on
    21st June 2013.")
  - `created_at`, `updated_at`
- Backfill from existing seed data:
  - SC sitting judges (31): the `parent_high_court` field already
    captures the prior HC + the `parent_hc_sentence` text. Parse
    those into `judge_appointments` rows for the prior HC AND the
    current SC appointment.
  - Delhi HC sitting judges (32): the current scrape doesn't capture
    prior history. Slice A.1 adds the per-judge profile-page fetch
    on Delhi HC (the names link out to detail pages with appointment
    info — needs reconnaissance).
- New API surface: `GET /api/courts/judges/{judge_id}` already exists
  via `MOD-TS-001`; extend the response with `career` field — array
  of `JudgeAppointmentRecord`.
- New UI surface: `/app/courts/judges/{id}` page gains a "Career"
  section rendered as a vertical timeline (oldest first). Each entry
  shows court name + role + tenure dates + cited evidence sentence
  with a link to the source URL. Displays "Source: sci.gov.in" so
  users know provenance.

**User stories:**

- `US-014C` — As a litigator, I open Justice X's profile and see
  every court they have served on, with tenure dates, so I know
  whether their prior HC reasoning is relevant to my appeal.
- `US-015C` — As an arguing counsel, I can click through from a
  career row to the source page on sci.gov.in or the HC site, so I
  can verify the data myself.

**Tests:**

- `FT-024C-1` — Backfill produces ≥ 1 appointment row per SC judge
  with non-null `parent_high_court`.
- `FT-024C-2` — Sitting judge's current appointment has `end_date`
  IS NULL.
- `FT-024C-3` — Tenant isolation: profile route exposes career
  history but only for active judges (no leak of soft-deleted).
- `FT-024C-4` — Source-URL is rendered as a clickable link in the
  UI; `target="_blank" rel="noopener noreferrer"` on every link.
- `FT-024C-5` — Frontend vitest: empty career array renders the
  "Career history not yet recorded" empty state, not a broken layout.

**Non-functional:**

- Backfill is idempotent; re-running the seed job updates appointment
  rows in place rather than appending duplicates.
- No favorability copy in the career section (structural test sweeps
  the rendered DOM for the forbidden token list).

**Effort estimate:** ~half day (schema + migration + backfill +
profile route extension + UI section + 5 tests).

---

### Slice B — `MOD-TS-001-C` Bench → Judge FK normalisation

**Status:** `Queued`.

**Scope:**

- Add `MatterListing.judges_json` column (text) — JSON array of
  resolved `Judge.id` strings. Nullable when bench could not be
  parsed.
- New service `services/bench_resolver.py`:
  - `parse_bench_name(text: str) -> list[str]` — tokenises
    "Justice A.S. Chandurkar & Justice X.Y.Z." into candidate name
    strings. Handles `&`, `and`, `,`, common bench formats.
  - `resolve_to_judges(session, court_id, candidate_names) -> tuple[list[str], list[str]]`
    — returns `(matched_judge_ids, unmatched_strings)`. Match must
    be tolerant: surname + initial overlap, normalised
    case/punctuation. Court scope is mandatory — never resolve a
    Bombay HC bench against SC judges.
- New job `caseops-resolve-bench-listings` — Cloud Run Job that
  walks all `matter_listings` rows where `judges_json` IS NULL,
  attempts resolution, writes results, and logs the unmatched rate
  for ops visibility.
- New audit signal: `audit_events` row of type `bench_resolved`
  written per resolution with the source bench_name + resolved IDs.

**User stories:**

- `US-014D` — As a litigator, when I view a matter's hearings tab,
  each upcoming listing shows the bench as clickable links to the
  individual judge profiles, not as a free-text string.
- `US-015D` — As ops, I can see the resolution rate dashboard
  (resolved / total) so I know how often the parser is silently
  failing.

**Tests:**

- `FT-024D-1` — `parse_bench_name` happy paths: 1 judge / 2 judges
  with `&` / 3 judges with `,` and `and`.
- `FT-024D-2` — `parse_bench_name` edge: typos, missing dots,
  honorific variants, ALL CAPS input, mixed case.
- `FT-024D-3` — `resolve_to_judges` honours court scope: a Bombay
  HC bench string never resolves to an SC judge, even on perfect
  name match.
- `FT-024D-4` — Tolerant match: "A.K. Sikri" resolves to "Adarsh
  Kumar Sikri" stored as the canonical Judge.full_name.
- `FT-024D-5` — Idempotent: re-resolving a row with a known mapping
  produces no duplicate audit events.
- `FT-024D-6` — Unmatched rate is logged as a numeric metric (not
  just a free-text WARN).

**Non-functional:**

- The resolver MUST NOT silently match on a single common surname.
  "Singh" alone is too ambiguous to be confident — match must
  require either initial + surname OR full name. Below the
  confidence floor, leave unresolved with a structured reason.
- Performance: bulk resolution of 10,000 listings completes in
  under 60s on a single worker (the matcher is in-memory, no LLM).

**Effort estimate:** ~half day (service + tests + Cloud Run Job
runner + UI link rendering on the matter hearings tab).

---

### Slice C — `MOD-TS-001-D` Bench-specific BAAD context

**Status:** `Queued` (depends on A + B).

**Scope:**

- Extend `services/bench_strategy_context.py`:
  - Optional `next_listing_id` argument. When supplied:
    - Look up `MatterListing` for the listing.
    - Use `MatterListing.judges_json` (resolved by Slice B) to
      identify the specific bench.
    - Pull authorities authored by THIS bench in the matter's
      practice area, scoped to the court.
    - Inject as a `BENCH-SPECIFIC HISTORY` block in the prompt,
      DISTINCT from the existing `COURT HISTORY` block.
- Extend `services/drafting.py` for `appeal_memorandum`:
  - When the matter has an upcoming hearing AND that hearing's
    bench resolved successfully, pass `next_listing_id` to
    `build_bench_strategy_context`.
  - When bench did not resolve, fall back to the existing court-
    scoped context with a visible limitation note.
- Update the prompt:
  - Add a positive instruction: "When the BENCH-SPECIFIC HISTORY
    block is non-empty, cite at least one authority from it in the
    appeal memorandum; explain in plain language how that bench's
    prior reasoning supports the present appeal."
  - Keep the enumerated NEVER WRITE list of forbidden phrases —
    bench-specific MUST NOT translate to favorability.
- UI: `BenchContextCard` extended with a "Specific bench (next
  hearing)" section above the existing court-level block. Empty
  state when bench unresolved.

**User stories:**

- `US-014E` — As a senior litigator, when I draft an appeal memo
  for a matter with an upcoming listing, the draft cites the prior
  reasoning of the specific bench scheduled to hear it, not just
  the court at large.
- `US-015E` — As a reviewer, I can verify the bench-specific
  citations are real and from the right judges by clicking through
  to each cited judgment.

**Tests:**

- `FT-024E-1` — `build_bench_strategy_context(next_listing_id=…)`
  returns a non-empty `bench_specific_authorities` array when the
  bench resolved AND has authored ≥ 3 authorities in the practice
  area.
- `FT-024E-2` — Below the 3-authority floor, returns empty array
  AND a `limitation_note` explaining why.
- `FT-024E-3` — Tenant isolation: bench-specific authorities never
  include another tenant's matter data (the corpus is global, but
  this is a defence-in-depth assertion).
- `FT-024E-4` — Generated draft contains ≥ 1 citation from the
  bench-specific block when the block is non-empty (LLM
  instruction-following test).
- `FT-024E-5` — Structural no-favorability sweep at both the prompt
  level AND the rendered draft DOM — same test pattern as MOD-TS-001-A.
- `FT-024E-6` — Bench-resolution-failed fallback path produces a
  draft equivalent to today's court-scoped output, with a
  `bench_resolution_failed` limitation note shown in the UI.

**Non-functional:**

- Bench-specific context MUST be additive, not replacing. The court-
  scoped block stays — bench-specific is on top.
- LLM cost: per-draft cost should not increase by more than ~20%
  (bench-specific block adds at most 5 authorities).

**Effort estimate:** ~1 day (service extension + prompt tweak + UI
extension + 6 tests + structural test sweep).

---

### Slice D — `MOD-TS-001-E` Tolerant judge name matcher

**Status:** `Queued` (cross-cuts A, B, C).

**Scope:**

- New `judge_aliases` table:
  - `id`, `judge_id` (FK), `alias_text`, `source` (one of:
    `sci_gov_in`, `hc_scrape`, `manual`, `auto_extract`),
    `created_at`.
- Replace ILIKE matching in `services/bench_strategy_context.py:
  query_judges_authorities` with FK-based lookup against
  `judge_aliases`.
- Backfill aliases from existing data sources:
  - For each Judge, generate canonical aliases:
    - "Justice {full_name}"
    - "Justice {first_initials} {surname}"
    - "{honorific} {full_name}"
    - "{full_name}"
- Optional: nightly job that walks new `AuthorityDocument.judges_json`
  entries and proposes new aliases via fuzzy match for human review
  (NOT auto-applied).

**User stories:**

- `US-014F` — As ops, I can see which Judge rows have which aliases,
  via an admin page, so I can fix bad matches.

**Tests:**

- `FT-024F-1` — "Justice A.K. Sikri" and "Justice Adarsh Kumar Sikri"
  both resolve to the same Judge.id.
- `FT-024F-2` — Single common surname ("Singh") does NOT match —
  the resolver requires initial + surname or fuller match.
- `FT-024F-3` — Backfill produces ≥ 4 aliases per Judge for the
  current 63 judges (31 SC + 32 Delhi HC).
- `FT-024F-4` — Adding a new alias doesn't break existing resolved
  bench → judge mappings (idempotent re-resolution).

**Non-functional:**

- Alias table writes are auditable.
- Manual aliases require an admin role.

**Effort estimate:** ~half day (schema + backfill + test sweep).

---

## 4. Data source rules

Every fact populated by these slices must have a verifiable source:

| Source | Used for | Notes |
|---|---|---|
| sci.gov.in `/judge/{slug}` | SC judge career history, DOB, appointment date | Already used by `enrich_sci_judges.py`. |
| `delhihighcourt.nic.in/web/CJ_Sitting_Judges` | Delhi HC sitting judges (current) | Already scraped 2026-04-25; per-judge profile pages need separate reconnaissance for career history. |
| HC website per court | HC judge career history | Each HC has its own format; out of scope for this PRD until per-HC scraper lands. |
| `MatterListing` table | Bench rosters per hearing | Free-text source from cause-list scrapes; Slice B normalises. |
| `AuthorityDocument.judges_json` | Layer-2 extracted bench from each judgment | Already populated by the corpus pipeline. |

No Wikipedia. No hand-curated lists without a source URL recorded in
the row. No LLM-generated judge metadata.

---

## 5. Acceptance criteria

This PRD is implemented when:

1. `/app/courts/judges/{id}` shows a Career section for at least
   the SC judges with `parent_high_court` data (≥ 25 of 31 SC
   judges per the 2026-04-25 enrichment run).
2. `/app/matters/{id}/hearings` renders bench rosters as clickable
   per-judge links, not as free text, for at least 80% of upcoming
   listings (the unmatched 20% surfaces in an ops dashboard).
3. An appeal-memorandum draft generated for a matter with a resolved
   next hearing contains at least one citation from a judgment
   authored by the specific bench scheduled to hear it.
4. The structural no-favorability test sweep (existing pattern from
   MOD-TS-001-A) passes against the new prompt + UI surfaces.
5. All 22 functional tests above pass in CI.
6. `docs/PRD_CLAUDE_CODE_2026-04-23.md` §6 module table updated to
   reflect MOD-TS-001-B/C/D/E status post-implementation.

---

## 6. User answers (received 2026-04-25)

1. **Backfill source for HC career history.** **In parallel.** Scrape
   per-judge profile pages on Delhi HC alongside the SC backfill,
   not deferred. Other 5 HCs: when their sitting-judges scraper
   lands, the per-judge enrichment runs in the same job.
2. **Bench-resolution confidence floor.** **High quality.** Better
   to leave a listing unresolved than to mismatch. Resolver requires
   either (a) initial + surname AND court-scope match, or (b) full
   name AND court-scope match. Single surname alone (even
   court-scoped) is insufficient. Unmatched listings surface in an
   ops dashboard, not silently auto-resolved.
3. **Bench-specific cost ceiling.** **Claude's call.** Implementation
   keeps the prompt addition tight (≤ 5 bench-specific authorities,
   each ≤ 800 chars) and measures actual cost vs the court-scoped
   baseline in the first 100 production drafts. If the per-draft
   cost rises >25% over baseline, drop the cap to 3 authorities.
4. **Alias admin surface.** **Same slice.** Slice D ships with both
   the table + backfill AND the admin page (`/app/admin/judge-aliases`).
5. **Rollout order.** **A + B + C + D in parallel.** Per the user's
   "ship them all" intent. Implementation reality: A, B, D have
   independent schemas/services and can land in parallel commits;
   C depends on B (bench resolution) AND D (tolerant matcher), so
   C lands after B + D's PRs merge. Net session sequence: A and D
   in parallel → B → C.

---

## 7. PRD execution skill compliance

Per `.claude/skills/caseops-prd-execution/SKILL.md`:

- **Affected journey IDs:** J06 (Court, judge, bench, tribunal
  intelligence), J07 (Drafting studio — appeal memorandum subset).
- **Affected module IDs:** MOD-TS-001 (extends), MOD-TS-001-A
  (extends), new MOD-TS-001-B/C/D/E.
- **Current repo status:** code shipped for the parent modules; this
  PRD is the depth extension. No code in the repo today implements
  these slices.
- **Required user stories:** US-014C/D/E/F + US-015C/D/E.
- **Required functional tests:** 22 enumerated above (FT-024C-1
  through FT-024F-4).
- **Required non-functional tests:** tenant isolation (per slice),
  no-favorability sweep (Slice C), idempotency (Slices A, B, D),
  performance budget (Slice B), cost ceiling (Slice C).
- **Required security tests:** alias admin route requires admin role
  (Slice D); audit events written per bench resolution (Slice B).

---

## 8. Sign-off

| Reviewer | Date | Decision |
|---|---|---|
| mishra.sanjeev@gmail.com | 2026-04-25 | **Approved** — implementation may proceed per §6 answers (A + D parallel → B → C). Advocate-bias selection per §2.1 is mandatory, not optional. |

Implementation kicks off immediately on Slices A + D. Will update
`docs/PRD_CLAUDE_CODE_2026-04-23.md` §6 module table to add the four
new MOD-TS-001-B/C/D/E rows with `In progress` status as each lands
in main.
