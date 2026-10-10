# Nonempty Secret-Scan Gate

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
multiline spans and newly reintroduced literals still fail. History uses the
original policy unchanged. No new reviewed exception or alert dismissal exists.

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
