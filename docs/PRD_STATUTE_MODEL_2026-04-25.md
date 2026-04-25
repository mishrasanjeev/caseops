# PRD: Statute + Bare Acts Model

Status: **Draft for review** (2026-04-25, mishra.sanjeev@gmail.com).
Implementation begins on user approval.

This is PRD §16.2 line 1 ("statutes and bare acts"), corresponding to
backlog item `WTD-7.4` (currently `Missing` in
`docs/STRICT_ENTERPRISE_GAP_TASKLIST.md`).

---

## 1. Why this PRD exists

Today the appeal-draft / hearing-pack / authority-search pipeline
references statute provisions as **free-text strings**:

- `Matter.statutes_referenced` (free text)
- `AuthorityDocument.sections_cited_json` (Layer-2 extracted strings
  like `"BNSS Section 483"`, `"CrPC §439"`)
- The drafting prompt's `_DOCTRINE_PATTERNS` regex matches doctrines
  by phrase

This works for prose but blocks four things the user has explicitly
asked for:

1. **Citation-grounded appeal grounds** — when a draft says "the
   trial court erred under Section 482 BNSS", we cannot link the
   reader to the actual statutory text. The user's 2026-04-25 ask
   ("citations and proof based on bench/court they are going to
   appear") needs structured statute references.
2. **BNSS vs BNS confusion** — section numbers overlap across the
   2023 codes (Section 483 BNSS = bail; Section 483 BNS = kidnap).
   Free-text strings `"Section 483"` are ambiguous; structured
   `(act_id="bnss-2023", section_number="483")` is not.
3. **Practice-area inference** — "Section 138 NI Act" is unambiguously
   a cheque-bounce matter. With structured statute refs we can derive
   practice area instead of asking the user.
4. **Authority retrieval rerank** — "show me every SC decision
   interpreting Section 482 BNSS" needs an FK, not an ILIKE.

---

## 2. Scope

**In scope (v1):**

- New `statutes` master table (one row per Act, e.g. BNSS 2023, BNS
  2023, CrPC 1973, Constitution of India, NI Act 1881, etc.).
- New `statute_sections` table (one row per Section / Article /
  Order-Rule under each Act).
- Migration that seeds the master + section tables for the first 6
  acts a litigator will hit daily (BNSS, BNS, BSA, CrPC, IPC,
  Constitution).
- New `matter_statute_references` table linking Matter → StatuteSection
  with a `relevance` enum ('cited', 'opposing', 'context').
- New `authority_statute_references` table linking AuthorityDocument
  → StatuteSection (populated by a backfill job that parses
  `sections_cited_json`).
- Read API:
  - `GET /api/statutes` — list all acts
  - `GET /api/statutes/{act_id}/sections` — list sections under an act
  - `GET /api/statutes/{act_id}/sections/{section_number}` — section
    detail incl. text
  - `GET /api/matters/{id}/statute-references` — refs for one matter
- UI:
  - `/app/statutes` — bare-acts browser (Act → Section tree, click
    through to section text).
  - Section detail page shows the bare text + cross-references + a
    "Recent decisions interpreting this section" feed (joins
    `authority_statute_references`).
  - Matter cockpit gains a "Statutes" sub-tab showing referenced
    sections with one-click jump to bare text.
- Drafting prompt extension: when statute refs are populated, the
  appeal-memorandum prompt receives the bare text of each cited
  section so the LLM can quote it verbatim instead of paraphrasing.

**Explicitly NOT in scope (v1):**

- Statute amendment history / version tracking. v1 stores the latest
  enacted text only; future revisions tracked separately.
- Cross-act mapping (e.g. "this CrPC section is now BNSS section
  X"). High-value but big scope; tracked as a v2 PRD.
- LLM-based statute-relevance scoring per matter. v1 is user-asserted
  (lawyer ticks the relevant sections); LLM auto-suggest is a v2.
- State-specific Acts (only the 6 central acts in v1).
- Repealed sections. Deferred to v2.
- Full-text search across sections. v1 has filter by Act + section
  number; full-text search is a v2.

---

## 3. Data model

```
statutes
  id            text PK   e.g. 'bnss-2023', 'crpc-1973', 'constitution-india'
  short_name    text      e.g. 'BNSS', 'CrPC', 'Constitution'
  long_name     text      e.g. 'Bharatiya Nagarik Suraksha Sanhita, 2023'
  enacted_year  int       2023
  jurisdiction  text      'india' (v1: central acts only)
  source_url    text      gazette / India Code URL
  is_active     bool
  created_at, updated_at

statute_sections
  id              uuid PK
  statute_id      FK → statutes.id ON DELETE CASCADE
  section_number  text      '482', '13(1)(a)', 'Article 226' — string for variants
  section_label   text      'Quashing of FIR' — short title
  section_text    text      bare text (CC0 / public domain via India Code)
  section_url     text      direct link to indiacode.nic.in
  parent_section_id uuid|null  for sub-sections
  ordinal         int       sort order within the act
  is_active       bool
  created_at, updated_at
  UNIQUE (statute_id, section_number)

matter_statute_references
  id           uuid PK
  matter_id    FK → matters.id ON DELETE CASCADE
  section_id   FK → statute_sections.id ON DELETE RESTRICT
  relevance    text  'cited' | 'opposing' | 'context'  — who relies on it
  added_by_membership_id  FK → company_memberships.id ON DELETE SET NULL
  notes        text
  created_at, updated_at
  UNIQUE (matter_id, section_id, relevance)

authority_statute_references
  id              uuid PK
  authority_id    FK → authority_documents.id ON DELETE CASCADE
  section_id      FK → statute_sections.id ON DELETE RESTRICT
  occurrence_count int  — how many times the section is cited in the judgment
  source          text 'layer2_extract' | 'manual'
  created_at, updated_at
  UNIQUE (authority_id, section_id)
```

---

## 4. Slices

### Slice S1 — Schema + seed for 6 central acts

- Migration adds 4 tables.
- Seed data for: BNSS 2023, BNS 2023, BSA 2023 (the new 3-Sanhita
  trio), CrPC 1973, IPC 1860, Constitution of India.
- Each Act seed includes ALL sections (numbers + labels + bare
  text) — sourced from indiacode.nic.in (CC0). Enrichment script
  `enrich_statute_sections.py` fetches per-section text.
- Cloud Run Job `caseops-seed-statutes` runs the loader.
- 5 backend tests: schema migration, seed inserts, FK cascade,
  unique constraint, idempotent re-seed.

**Effort:** ~1 day.

### Slice S2 — Read API + bare-acts browser UI

- 4 read routes (list acts / list sections / section detail / matter
  refs).
- `/app/statutes` browser page — Act tiles → Section list → Section
  text view.
- `/app/matters/{id}` matter cockpit gets a "Statutes" sub-tab.
- 4 backend route tests + 3 vitest cases.

**Effort:** ~half-day.

### Slice S3 — Authority statute backfill from Layer 2

- New service `services/statute_resolver.py`:
  - `parse_section_string(text)` — "BNSS Section 483" →
    `(act_id="bnss-2023", section_number="483")`. Tolerant: handles
    "S. 483 BNSS", "§483", "section 483 of the BNSS", etc.
  - `resolve_authority_sections(authority_id)` — reads
    `AuthorityDocument.sections_cited_json`, parses each entry,
    inserts `authority_statute_references` rows.
- Cloud Run Job `caseops-resolve-authority-statutes` runs nightly.
- 6 backend tests covering happy parses + edge cases (BNSS vs BNS
  ambiguity → both inserted with `source='layer2_extract'`; user
  can manually correct via S4 admin).

**Effort:** ~half-day.

### Slice S4 — Matter statute reference UI + drafting prompt extension

- "Add statute reference" dialog on the matter cockpit Statutes
  tab; user picks Act → Section → relevance.
- `services/drafting.py`: when a matter has `matter_statute_references`,
  the appeal-memorandum prompt receives the bare text of each cited
  section. Format: `=== STATUTORY TEXT ===` block with section
  number + label + verbatim text. Instructs the LLM to quote
  verbatim (not paraphrase) when relying on a section.
- 4 backend tests + structural no-favorability sweep + 2 vitest.
- Bench-aware drafting hard rules unchanged: statute references
  are evidence, not favorability.

**Effort:** ~half-day.

---

## 5. User stories

| ID | Story |
|---|---|
| `US-046A` | As a litigator drafting an appeal, the draft prompt receives the bare text of every statute section the matter cites, so the LLM quotes verbatim instead of paraphrasing. |
| `US-046B` | As an arguing counsel preparing for hearing, I can browse `/app/statutes` to look up Section 482 CrPC bare text without leaving CaseOps. |
| `US-046C` | As a junior associate, I can attach statute references to a matter (Act → Section → relevance) so the senior reviewing the draft sees them surfaced. |
| `US-046D` | As an authority-search user, when I open a judgment I see which statute sections it interprets, with click-through to bare text. |

---

## 6. Tests

22 functional tests enumerated in slice descriptions above (S1: 5,
S2: 7, S3: 6, S4: 4). Plus structural no-favorability sweep on the
new prompt block (Slice S4).

---

## 7. Data sources + provenance

- **India Code** (https://www.indiacode.nic.in) — Government of
  India's official Acts repository. CC0 / public domain. v1 source
  for ALL section text.
- **Per-section URL** stored in `statute_sections.section_url` so
  every UI render can link back to the official source.
- **Layer-2 extraction** (existing `AuthorityDocument.sections_cited_json`)
  — input to Slice S3's resolver. No new LLM extraction in v1.

No Wikipedia. No third-party copyrighted compilations. All section
text is verifiable at the cited URL.

---

## 8. User answers (received 2026-04-25)

1. **Act priority order.** Confirmed BNSS → BNS → BSA → CrPC → IPC →
   Constitution. **NI Act 1881 added to v1** because cheque-bounce
   notices are already a shipped drafting template (`MOD-TS-012`)
   and Section 138 NI Act citations dominate that flow. **7 acts in v1.**
2. **State acts.** Confirmed out of v1 — central acts only.
3. **Bare-text source.** Confirmed indiacode.nic.in (Government of
   India's official Acts repository, CC0). No third-party
   compilations.
4. **Drafting prompt cost.** Cap per-section bare-text at **600
   chars** (truncate with ellipsis + section_url for the lawyer to
   click through). Keeps the prompt addition under ~10% of the
   court-scoped baseline.
5. **Rollout order.** Confirmed S1 → S2 → S3 → S4. Foundation-up so
   each downstream slice has real DB rows to read.

---

## 9. Sign-off

| Reviewer | Date | Decision |
|---|---|---|
| mishra.sanjeev@gmail.com | 2026-04-25 | **Approved** — implementation kicks off immediately on Slice S1 (schema + 7 act seed). |
