# Draft list private-source reauthorization, 2026-09-27

Follow-up to PR #490 (`fix/review-list-latency-20260927`), which added
`private_saved_source_manifests_are_current` and bounded the Intelligent
Review history. This change is bounded-work hardening, not an incident: the
Draft lists are fast today because each Matter or proceeding has few drafts.

## What was unbounded

`services/drafting.py` still reauthorized each version's saved private manifest
separately, through the one-manifest `private_saved_source_manifest_is_current`:

- `list_drafts` (the Matter drafts list) and `list_ip_drafts` (the drafts of
  one IP opposition proceeding) ran the check for every version of every draft.
- `_assert_private_draft_sources_current` ran it for every version of one
  draft. `_load_draft` and `_load_ip_draft` call it, so every read, export,
  comparison, generation, edit, transition and filing of a draft paid it.

Each check issues about seven statements for a version that carries a private
source. Measured on the unfixed commit `a2e3d2f1` (the #490 head), in a
separate checkout whose imported `drafting.py` was verified, for a non-owner
member:

| Path | Smaller set | Larger set |
| --- | --- | --- |
| Matter drafts list | 91 statements, 18 drafts / 23 versions | 493 statements, 54 drafts / 161 versions |
| IP drafts list | 82 statements, 18 drafts / 23 versions | 434 statements, 54 drafts / 161 versions |
| Read of a draft whose edits copy one manifest | 27 statements at 3 versions | 69 statements at 9 versions |

On PostgreSQL, with 10,000 unrelated projections retained in each of two
generations, no manual `ANALYZE`, a 1,500 ms statement budget and hash and
merge joins disabled, the Matter list of 72 drafts / 299 versions took 868
statements and 8.6-10.2 s, and the IP list 760 statements and 5.8-7.4 s.

## A list returned drafts that its read refused

The lists parsed each manifest with `_load_manifest`, which turns any JSON
value other than a list into `[]`, meaning "no private source". The
single-draft read refuses the same draft with 409 because of its
`isinstance(manifest, list)` check. A draft whose manifest was saved as a JSON
object or `null` was therefore listed, body included, although it could not
be opened. On the unfixed commit both lists returned three such drafts.

Every writer stores a JSON list, so only a corrupted row can take this path.
The lists now follow the read's fail-closed decision; the read was not
relaxed. Undecodable text still counts as no saved private source on both
paths, as before.

## Fix

- `_version_source_manifest` parses a version's manifest once, with the read's
  rules. `_private_draft_sources_current` sends the manifests of every version
  of every draft to `private_saved_source_manifests_are_current`. Each version
  keeps its own decision, and a draft is current only when all of its versions
  are.
- Identical manifests, which every edit copies, share one decision. One call
  reauthorizes at most `PRIVATE_MANIFEST_BATCH_SIZE` (100) distinct manifests,
  the review-history page size #490 proved on PostgreSQL. The lists are
  unpaginated, so without this cap a long history of distinct manifests would
  put every saved projection ID into one `IN` predicate and every retired
  source pair into one `OR`. A pull-request review raised this.
- Versions are never merged into one manifest. Edits copy the same projections
  and older versions keep older generations, so a merged manifest would fail a
  readable draft.
- `list_drafts`, `list_ip_drafts` and `_assert_private_draft_sources_current`
  all use it, so a list and a read make the same decision.
- For a non-owner member the Matter list takes 14 statements and the IP list
  13, however many drafts and versions they hold, up to 100 distinct manifests.
  Each further 100 add one statement set of at most 8. A single-draft read
  takes at most 14, whatever its version count.

## Verification

- `apps/api/tests/test_20260927_draft_lists_bounded.py` (SQLite) captures a
  Matter's and an IP docket's manifests through the real capture path. Each
  target has one manifest per state: saved in a generation later retired by an
  unrelated rebuild, saved in the active generation, and either one naming a
  second Matter whose access then changes. Each list holds 18 draft shapes:
  - current: active, retired, retired then active, and edits that copy one
    manifest;
  - no private source: authority entries only, no version yet, and
    undecodable text;
  - revoked: in either generation, and a revoked version between two current
    ones;
  - malformed: retired and active entries merged into one manifest, a JSON
    object, JSON `null`, a current version after a JSON object, an entry
    without a projection ID, a duplicated projection, an unknown generation,
    and a changed hash.
  Each shape's visibility equals its versions' one-manifest decisions and its
  stated expectation. Both lists return the same drafts with the same statement
  count at 18 drafts / 23 versions and at 54 drafts / 161 versions. Every
  single-draft read agrees with the list at a constant cost from 1 to 9
  versions. The HTTP list and detail routes agree too (200 or 409).
- `test_draft_list_reauthorizes_a_long_distinct_history_in_capped_batches`
  saves one Matter's manifest in seven generations. Every manifest names other
  projections and another saved generation. Each draft has two identical
  versions, and the list also holds a revoked draft and one with a changed
  hash. With the batch size set to 3, the list makes three calls of three
  distinct manifests, for 16 versions. It returns exactly the drafts the
  unsplit list and the one-manifest decisions return. Each extra batch adds at
  most 8 statements. On the previous commit, the same list sent all 16 version
  manifests in one call, and this test fails there.
- `apps/api/tests/test_20260927_draft_lists_bounded_postgres.py` runs the same
  journey on PostgreSQL, then again at the retained volume above with 72 drafts
  and 299 versions per list: 14 and 13 statements, 0.22-0.48 s and
  0.18-0.28 s. Both commits were timed on the same workstation under the same
  concurrent load.
- On the unfixed commit the SQLite regression fails in one run. It reports
  the three refused drafts in the Matter list, 91 then 493 statements against
  a bound of 14, and reads that grow with their versions. Both PostgreSQL tests
  fail there the same way.
- The 26 test files that exercise drafts, draft exports, Intelligent Reviews
  and private retrieval passed: 472 tests, reconciled per file against the
  requested inventory.
