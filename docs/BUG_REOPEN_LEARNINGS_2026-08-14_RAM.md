# Ram 2026-08-14: Bulk Matter Upload — why the 2026-08-11 fix created these bugs

Source workbook: `C:\Users\mishr\Downloads\CaseOps_Bug_list_Ram14Aug2026.xlsx`.
Fix commit: `6db34b64` on `claude/bulk-import-ram-20260814`.

## Verdicts

- **BUG-001 is valid.** Forum hierarchy values outside the alias tables fell
  through to `MatterCreateRequest`, which returned the raw pydantic message
  `forum_level: Input should be 'lower_court', 'high_court', ...` to a legal-ops
  user. The backend enum was the user-facing error text.
- **BUG-002 is valid and is the same defect as BUG-001.** Every catalog
  category introduced on 2026-08-11 was fail-closed, so `DRAT / DRT` and
  `State Commission` rows demanded an exact catalog court string.
- **BUG-003 is valid but was reported one level off.** Duplicates were already
  excluded from creation — `commit_matter_import` only creates `VALID` rows.
  The real defect was classification: duplicates were marked `invalid`, which
  inflated `validation_error_count`, set the job to `completed_with_errors`,
  and told the user to correct a file that needed no correction.
- **BUG-004 is valid in part.** The header aliases accept a bare
  `Matter Owner` / `Responsible Lawyer` column, but resolution was email-only,
  so a valid active user referenced by name was rejected. The team-scoping
  rejection observed alongside it is **not** a bug: `services/matters.py:1376`
  enforces the identical rule on manual creation. Only its message changed.

## The root cause: parity was asserted in one direction only

Manual matter creation (`_resolve_forum_selection`, `services/matters.py:521`)
has a free-text fallback — it accepts `forum_level` plus any `court_name` when
no catalog entry is selected. Bulk import (`_resolve_import_forum`) did not.

Proven on production before any code changed:

| Path                   | `forum_level=tribunal`, `court_name="DRT Delhi"`                      |
| ---------------------- | --------------------------------------------------------------------- |
| `POST /api/matters/`   | **200** — matter `22184487-8059-41d2-b03a-b17b5d652b35` created       |
| Bulk import, same data | **rejected** — "Court is not an active DRAT / DRT catalog selection." |

Two write paths for one business object disagreed, and the stricter one was
the one a client uses to load a hundred matters at once.

## Why this reopened: the previous fix's own rule caused it

`docs/BUG_REOPEN_LEARNINGS_2026-08-11_RAM.md` rule 5 reads:

> Any new hierarchy offered by both manual and bulk creation must have one
> server-owned active master. Persist its ID and derived lineage, revalidate on
> preview and commit, and **reject ambiguous/invented values**. If a historical
> import contract needs a compatibility path, keep it explicit and **narrower
> than the new catalog-backed categories**.

That rule is half right, and the missing half produced this workbook three days
later. It correctly demanded one master. It then specified strictness in one
direction only — bulk must not be _looser_ than the catalog — and said nothing
about bulk not being _stricter_ than the manual path it was supposed to match.
`_LEGACY_CATALOG_OPTIONAL_CATEGORIES` implemented that rule literally: exactly
three historical families fail open, everything else fails closed.

Three compounding facts made it a hard blocker rather than an inconvenience:

1. **The catalog cannot cover India.** Production carries **4** DRAT/DRT
   entries and **3** recovery-forum entries, all Delhi, against 737 consumer
   and 723 district-court entries. A Mumbai DRT matter was unimportable at any
   catalog completeness reachable this year. "Add more catalog data" was never
   a fix.
2. **The product invited the failure.** The XLSX template puts a **dropdown on
   the Forum column** offering all 14 categories, and **no dropdown on the
   Court column**. The user picks `DRAT / DRT` from our own list, types a court,
   and is rejected for not having hand-copied an exact string out of a
   1,499-row reference sheet.
3. **Nothing tested the parity claim.** The 2026-08-11 work added tests that
   catalog values resolve and invented values are rejected. No test asserted
   that the importer accepts what manual creation accepts, or that every Forum
   the template offers is importable.

## Where my own approach failed, specifically

1. **I wrote a prevention rule from the fix's perspective, not the user's
   workflow.** Rule 5 describes what the _validator_ should do. It never states
   the user-visible invariant: _a matter a lawyer can create by hand must be
   loadable in bulk._ A rule phrased as a validation policy cannot be checked
   against a workflow.
2. **I treated "one source of truth" as "one strictness level".** Sharing a
   master does not mean sharing a rejection policy. The catalog is an
   enrichment source; making it a gate on the bulk path only was an unforced
   choice that no requirement asked for.
3. **I let a fail-closed default stand where the data could not support it.**
   The bug-fixing skill already says catalog-backed selectors need a fail-open
   path when catalog completeness can block workflow completion. The 4-of-India
   DRT count was visible in the 2026-08-11 migration I wrote. I did not check
   coverage against the categories I was gating.
4. **I did not test the tool the user is handed.** The template is generated by
   the same service as the validator. Nothing asserted the two agree, so the
   product shipped a dropdown of values its own importer refused.
5. **I nearly repeated the pattern while fixing it.** Marking every duplicate
   row `duplicate` would have dropped _both_ copies of an in-file duplicate,
   because the existing detector flags all occurrences — silent data loss worse
   than the reported bug. Caught only by writing the "the original still
   imports" assertion before trusting the change. Likewise
   `failed_count = total - created` would have kept showing "2 rows failed"
   after duplicates were skipped, leaving the user's experience unchanged while
   the internals looked fixed.

## Supersession

Rule 5 of `docs/BUG_REOPEN_LEARNINGS_2026-08-11_RAM.md` is **superseded** by
rule 1 below as of 2026-08-14. The 2026-08-11 document remains accurate history
for the defect it addressed; its acceptance evidence is not rewritten.

## Permanent prevention rules

1. **Parity between two write paths is a two-way property, and must be tested
   as one.** When two entry points create the same business object, the one
   used for bulk or migration work must accept everything the interactive path
   accepts. Assert it directly, not by inspection. Enforced by
   `test_bulk_import_is_never_stricter_than_manual_creation`.
2. **A picker must never offer a value its own validator rejects.** Any
   generated template, dropdown, or reference sheet shares a single exported
   constant with the validator, and a test iterates that constant end to end.
   Enforced by `test_every_forum_the_template_offers_can_actually_be_imported`
   against `MATTER_IMPORT_TEMPLATE_FORUMS`.
3. **Before gating a workflow on a reference catalog, measure the catalog.**
   Record per-category row counts against real-world scope. If a category
   cannot cover the tenants who will file under it, enrich on match and fail
   open on miss. Failing open must not become guessing: an ambiguous match
   keeps the user's text and drops the lineage rather than picking a row.
4. **Never let a backend enum reach a user.** Any path that hands a value to a
   pydantic `Literal` validates it first and emits a message naming the
   accepted values in product vocabulary. Assert the absence of the leaked
   string (`"Input should be"`) in the regression, not just the presence of a
   nicer one.
5. **"Excluded" means the good row survives.** When changing a blocking
   condition into a skip, prove the non-offending sibling still lands. For
   in-file duplicates that means first-occurrence-wins with an explicit test
   that the original is created.
6. **A status change is not done until the counters and copy follow it.** A new
   row state must be threaded through job counters, terminal job status,
   notification text, downloadable reports, and the page — otherwise the user
   still reads "failed" while the internals say "skipped".
7. **Classify the report before fixing it.** BUG-003 as written ("duplicates are
   not removed") was already true in the create path; only the classification
   was wrong. Reproduce first and state which layer actually misbehaves, or the
   fix lands in the wrong place.
8. **Prevention rules get phrased as user-visible invariants.** A rule that
   describes validator behaviour cannot be falsified by a workflow test. Write
   the sentence a tester would write, then point at the test that proves it.
9. **A persistent production QA fixture must be unique on every business
   identity predicate, not only its primary code.** On the 2026-08-14 rerun,
   the importer correctly treated the first run's fixed title/client pairs as
   existing Matters even though its matter codes were fresh. Each production
   upload now derives both its code and client fixture from the run identifier,
   while the in-file duplicate scenario deliberately keeps its two rows on the
   same unique client. This preserves the duplicate assertion without turning
   a valid earlier run into a false production regression.
