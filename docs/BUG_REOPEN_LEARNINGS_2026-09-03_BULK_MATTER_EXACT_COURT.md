# Bulk Matter Exact-Court Mapping — 2026-09-03 assessment and permanent learnings

## Source assessment

`CaseOps_AI_Implementation_Bulk_Matter.docx` contains one populated item. It is
a valid product enhancement, not a defect report: accept a configured Exact
Court or approved alias in the bulk Matter `Forum` field and derive the full
`Forum Hierarchy -> State -> Exact Court` lineage. The document contains no
separate case-reopening incident, affected Matter identifier, timestamp, or
audit evidence. It would be unsafe to invent a reopening root cause from this
source.

## Where the earlier implementation was shallow

The bulk resolver treated `Forum` as a category before it considered the
server-owned court catalog. Consequently, `Tis Hazari`, `ITO`, and
`Dwarka_SWCF` were rejected before catalog resolution could run. Four deeper
contract failures made a parser-only patch insufficient:

1. The shared catalog had no first-class alias configuration. Hard-coding
   `Dwarka_SWCF` in an `if` branch would have hidden the immediate symptom but
   reproduced it for the next client alias.
2. The generated template told users to put only categories in `Forum`, while
   maintained client workbooks already placed Exact Court values there.
3. Preview and commit are separate trust boundaries. A preview-only mapping can
   disappear or change during commit-time revalidation.
4. Earlier tests proved category input and catalog-ID input, but not the inverse
   contract: every unique active Exact Court name/alias offered by the template
   must resolve without an extra hidden ID column.

The systemic mistake was optimizing for the visible validation message instead
of tracing the entire data contract from spreadsheet, through normalization and
preview persistence, through commit revalidation, into the Matter row and its
audit record.

## Correctness boundary

- `ForumCatalogEntry.aliases_json` is the sole alias configuration source.
- The import loads the active catalog once and builds a bounded lookup shared by
  all rows; a 500-row import does not issue or perform a catalog scan per row.
- Normalization is limited to trim/case/punctuation comparison. The stored
  Exact Court name and lineage always come from the active catalog.
- A unique match fills catalog ID, canonical forum level, court, state,
  district, city, and consumer level.
- An unknown, inactive, ambiguous, or context-conflicting value fails at its
  Excel row and CaseOps never guesses or creates a new catalog value.
- Category plus free-text Court remains backward compatible where manual Matter
  creation already permits it.
- The original spreadsheet `Forum` value remains in
  `MatterBulkImportRow.raw_json`; normalized values are stored separately.
- Commit revalidation resolves the persisted catalog ID again and therefore
  cannot bypass inactive/deleted catalog configuration.

## Case-reopening analysis

This enhancement does not write Matter lifecycle fields. Bulk import still
rejects terminal status and creates new Matters only. Existing Matters can be
disposed or reopened only through the dedicated lifecycle endpoint, where
status, `is_active`, lifecycle version, audit events, and operational-child
neutralization are atomic under the parent lock.

A future reopening report must be investigated from the persisted Matter row
and its audit events. An explicit audited `Disposed -> Intake` transition is a
controlled reopen, not automatic resurrection. Generic PATCH, import, worker,
or child writes remain prohibited from reactivating a terminal Matter.

## Permanent regression map

- `test_20260903_bulk_matter_exact_court_forum.py` proves exact names, approved
  alias normalization, complete lineage, raw-input audit preservation,
  preview/commit persistence, alias collisions, conflicting context, inactive
  catalog behavior, unknown values, unrelated owner validation, catalog API
  aliases, and a single catalog query for 500 rows.
- `test_matter_imports.py` proves the downloadable XLSX exposes Exact Court
  values and approved aliases and documents the same contract.
- `test_20260814_matter_import_ram_workbook.py` continues to prove that the new
  exact-court path does not make legacy category/free-text imports stricter than
  manual creation.
- The dated Playwright regression proves user-visible local-Docker and deployed
  behavior without invoking any paid legal-data provider.

Do not mark this item fixed from a source-tree test alone. The same dated
Playwright scenario must pass against a clean local Docker stack and the exact
production revision after it receives 100% traffic.
