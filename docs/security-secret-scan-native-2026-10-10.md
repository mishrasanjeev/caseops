# Nonempty Secret-Scan Gate

## October 22 Invitation Fixture Review

PR553's first secret scan found one new generic-key match in an isolated local
invitation-age fixture, not a provider or deployed account credential. The
fixture explicitly selects e2e, an independent SQLite database, loopback-only
mail capture and no real provider. The immutable a4770e87 origin's exact
line426 span was verified against native redacted evidence, SHA256
4382eeddd6ff0a1dc173f26aa0cebd01de6580beac39e976fe1894793f330eea.
Current source uses a repeated low-entropy local placeholder. Only the exact
historical commit/path/rule/line fingerprint is reviewed for changed-history
scanning; modified spans, new origins and real credentials remain blocking.
No test directory, path-wide or rule-wide exclusion and no alert dismissal.
The failed initial scan is retained. A complete native replacement scan and
fresh hosted Security result remain required before release acceptance.

## Scope and Cause

The actual Security run `38034910148`, job `114163220692`, on merged main
`3dbf364d9834316d181d4a52b2e9b4c7bee431b4` reported zero commits and bytes.
The pinned action derived its push range from payload commit-list entries and
combined `--no-merges --first-parent`, excluding the accepted side history and
the merge itself. A green zero-byte scanner result was not secret coverage.

The replacement gate uses the same approved Gitleaks 8.24.3 image, pinned by
digest. It scans immutable tracked Git blobs, including merge-only resolution
content, separately from all-parent `before..after` push history or PR base to
the actual synthetic merge. Scheduled runs retain all-ref history. Merge diff
options affect diffs, not traversal. Empty/malformed inventories, zero scanner
counters, missing reports, partial scans and interrupted execution fail closed.

## Existing Policy

Tracked `.gitleaks.toml` and `.gitleaksignore` remain byte-identical. Directory
scanning cannot interpret existing commit-bound fingerprints. The initial
redacted native findings are retained; a temporary tree-only fingerprint is
derived only when native blame proves the complete finding span is unchanged
from the exact reviewed commit/path/line and immutable original blob. The same
captured tree is then rescanned. New tokens at an old path/line, changed
multiline spans and newly reintroduced literals still fail. Historical findings
use the same complete-span boundary, additionally requiring the reported
immutable commit to belong to the selected history. Only an unchanged span with
one contiguous reviewed blame origin can receive a temporary exact
reported-commit/path/rule/line translation. The same complete history is then
rescanned natively; no report is filtered into a clean result. Both initial and
final native reports, receipts and owned-container cleanup are retained.
No tracked policy exception or alert dismissal is added.

## Scheduled History Origin Drift (2026-10-18)

Scheduled Security run `39113604226` on main
`2b34c5167def1d92c8b5c10896b2e92e7a7ca5a2` actually failed: the immutable tree
passed after 24 existing translations, but full `--all` history returned native
exit 2 with 29 `generic-api-key` findings. These 29 historical reported spans
resolve to 23 already-reviewed origin fingerprints, with complete contiguous
blame and byte-identical immutable spans. The initial scheduled failure remains
retained; this is not an invented runtime regression or a new credential waiver.

Bounded provenance review rejects changed bytes, identical literals introduced
by a new origin, mixed origins, unreviewed rules, malformed locations, missing or
out-of-range commits and unknown blame. Blob, cache, report and finding limits
fail closed. Selected Git commit counts include empty-diff commits and merges;
the pinned scanner counts commits with eligible non-deleted, non-binary diffs.
Retain and reconcile both inventories rather than narrowing traversal to make
the counters equal. Focused and full-schedule candidate evidence belongs under
`outputs/ip-calendar-open-items-20261017/security-history-origin-20261018-01`.
Local candidate proof does not certify a hosted replacement scheduled run or
authorize deployment.

## Native Evidence

The complete selected unittest file has 38 identities and 114 structured
setup/call/teardown phases, with no skips. Native Git fixtures cover push, PR,
non-fast-forward side parents, merge-only and subsequently removed secrets,
empty inventories/real zero-byte scanning, missing binaries, scanner failures,
reviewed fingerprint provenance and actual container interruption cleanup.
Real approved scanner containers run with networking disabled. Reports and
inventory retain hashes and redacted findings, never raw secret values.

Owned ignored evidence is under
`.tmp/security-nonempty-secret-scan-20261010-r1`. Failed initial runs and full
tree findings are retained with complete classifications, not overwritten.
An independent clone of exact `3dbf364d` proved 2,677 tracked blobs / 102,571,442
bytes and 52 selected/scanned commits; native processed bytes were 66,452,603
for the tree and 2,990,222 for history. The 24 directory findings were all exact
existing reviewed fingerprints, with native provenance retained. Scanner
processed bytes differ from tracked bytes because the existing scanner and
policy retain their normal content/size exclusions; this is not all-byte DLP.

## Limits and Ownership

This is a local CI-gate repair, not hosted integration or production closure.
Main owns integration, learning/ledger updates and release certification. No
main push, PR, deployment, production probe or dependency installation is part
of this change. Empty inherited license inventory, consent dependencies and
unsuppressed quality notes remain separate. Production remains NO-GO while
Main and the patent owner investigate their distinct current failures.
