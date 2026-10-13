# Workspace Production License Gate - 2026-10-10

## Scope And Verdict

QG-SEC-004: workspace-aware enumeration and fail-closed policy enforcement.
The inherited root `license-checker@25.0.1 --production
--excludePrivatePackages` artifact was `{}`, four bytes and zero packages.
The root is private and has no production dependencies; its private
`apps/web` workspace has 28 direct production dependencies. Empty root-only
enumeration is not license certification.

Implementation status: `Implemented` locally; bug closure remains
`Partially fixed` until exact committed hosted gate evidence is reconciled.
License certification: `NO-GO`. The complete current inventory rejects 19
package locations under the unchanged allowlist. This is a policy dependency,
not evidence of a concrete security vulnerability or a legal conclusion.

Only the Security license jobs, the new built-in-Node script and regression
file, and this scoped document change. No dependencies, lockfile, secret-scan
job, application/worker code, production state, global ledger or waiver changes.
The September 7 ledger remains an inherited tooling/policy gap, not a BUG-010
dependency waiver or permission to certify licenses.

## Inventory Contract

`scripts/production-js-license-gate.mjs` consumes both native npm inventories:

```sh
npm ls --package-lock-only --omit=dev --all --long --json --workspaces --include-workspace-root
npm ls --omit=dev --all --long --json --workspaces --include-workspace-root
```

It reconciles every explicit workspace/root manifest, declaration and identity
against lockfile v3, follows npm's production logical closure at physical lock
locations, and compares installed name/version/license metadata. Hoisted and
nested versions, workspace links, peer closure and optional platform packages
are included. Only private first-party roots are exempt; a third-party private
flag does not remove a dependency. Optional packages absent on this platform
remain policy checked as `lock_only_optional`, not verified installations.

Native missing/invalid dependencies, nonzero inventory exits, omitted runtime
entries/workspaces, unlocked or outside-root paths, mismatched metadata and
zero runtime entries fail closed with exit 2. Unsupported workspace globs are
rejected rather than silently omitted. Input sizes and graph traversal are
bounded. The report retains source, script, input and policy hashes and is
written exclusively before exit; a prior report cannot be overwritten.

On this isolated Windows npm install, npm marks six exact lock-backed optional
packages extraneous while exiting zero. Their diagnostics are reconciled to
exact optional/name/version/license/path metadata. Four locked dev-only extras,
absent from the virtual runtime closure, are retained separately rather than
hidden. The two runtime extras remain policy checked. Repeated peer/extra nodes
are classified by physical identity, independent of traversal order. The
runtime-reachable `fsevents@2.3.2` is retained despite its lock `dev` flag.
Unknown extras or diagnostics still fail closed.

The Security job runs the complete committed regression file with native TAP
and JUnit, then the real inventory gate. `if: always()` uploads both inventories,
stderr, report and unit reporters, including failed evidence. No npx/license
checker download or additional runtime dependency is introduced.

## Policy Boundary

The exact existing 14 terms are preserved:

```text
MIT;Apache-2.0;BSD-2-Clause;BSD-3-Clause;ISC;PostgreSQL;Python-2.0;Unlicense;
CC0-1.0;0BSD;BlueOak-1.0.0;CC-BY-4.0;CC-BY-3.0;Apache 2.0
```

Policy hash: `0bc2696e7d5d262964415118de72c6ca5185e5b8d4202b6a06e2b044f580c3b8`.

Exact identifiers are required: `MIT` does not authorize `MIT-0`. The bounded
expression grammar follows [SPDX Annex D.4.2-D.4.5](https://spdx.github.io/spdx-spec/v2.3.1/SPDX-license-expressions/):
AND requires both operands, OR allows an approved alternative, and AND binds
before OR. Both branches are parsed and bounded before selecting the first
approved alternative. Malformed syntax or an exceeded length/token/depth bound
in an unused branch rejects the whole expression. Valid but unapproved terms
in unused alternatives remain transparent in `unapproved_terms` and
`unused_unapproved_terms`; `selected_terms` records only the chosen obligations.
Unknown standalone/missing metadata, unapproved WITH exceptions and guessed
license-text corrections still fail closed. This is a bounded expression
grammar/policy evaluator, not SPDX-registry, license-text or legal certification.

The draft's former all-OR-terms rule was a tooling false positive, not an owner
approval dependency. `jszip@3.10.2` selects the already-allowlisted MIT branch of
`(MIT OR GPL-3.0-or-later)`; GPL remains unused metadata and is not approved.
The inherited [checker 25.0.1 onlyAllow code](https://github.com/davglass/license-checker/blob/v25.0.1/lib/index.js)
accepted any approved substring, including unsafe AND and `MIT-0` acceptances.
This semantic repair restores correct OR choice without restoring those flaws
or expanding the 14 approved terms.

## Descriptor Read And Original CodeQL Finding

The original draft at `6cb037ab1a8942017c5a614803cd71a26c84c020` received
CodeQL advisory check `114214720606`: FAILED, one HIGH `js/file-system-race`
alert #534 at script line 214. Its exact merge was
`1d349cd8e80fd085013ff07d0f2fb0618df5267c`. The three original SARIFs contain
one JavaScript result and zero Python/actions results. Successful Advanced jobs
did not make the advisory or SARIF green. These original bytes are retained in
`.tmp/license-toctou-20261010-r1/original-2026-10-10T130505759Z`, manifest SHA256
`e47834303ff3c3567bf177434a1c52f0357aab7f67f0aefd236616ab5e71d212`.

The vulnerable filename `statSync` followed by filename `readFileSync` is
replaced by one open descriptor, `fstat` regular-file/size checks, bounded
positioned reads, and descriptor closure in `finally`. POSIX uses O_NOFOLLOW
and O_NONBLOCK. Because Node on Windows exposes neither flag, the opened
descriptor must match the non-symlink leaf's inode metadata; nonzero device
identities must also match. Node 22.14 on Windows reports zero for the path's
device and a volume ID for the descriptor. That native case additionally
requires an unchanged, non-reparse ancestor chain. The post-open identity
check runs everywhere. No pathname is reopened for content.
A nonzero inode identity is required. The buffer is bounded to the initial
size plus one, at most 16MiB plus one byte; reads are at most 64KiB. Growth,
truncation or modification detected by byte count/size/nanosecond metadata
rejects the snapshot. No unbounded `readFileSync(fd)` replaces the path read.

Seventeen added native controls prove one-descriptor ownership, exact-bound
acceptance, oversized rejection before allocation, growth after fstat and
during reads, truncation, same-size rewrite, symlink/leaf identity rejection,
pathname replacement, short reads, invalid JSON, missing/nonregular files and
I/O/stat/close failure handling. POSIX exercises a real symlink; local Windows
exercises the descriptor-bound metadata fallback. No query suppression,
CodeQL workflow/policy change or alert dismissal is added. Fresh exact-head
hosted advisory/SARIF readback is required and retained separately; the old
finding is not retroactively greened.

## Local Native Evidence

Fresh isolated install and capture root:
`.tmp/license-gate-20261010-r1` in the owned
`demo-admin-guard-20261010/CaseOps` worktree. It never installs into the root
`node_modules` junction or modifies another checkout.

The historical committed run at `6cb037ab1a8942017c5a614803cd71a26c84c020`,
`unit-2026-10-10T122104998Z`, has 70 passes and zero skips. It verifies the old
implementation, not correct OR semantics: two expected OR rejections were
obsolete. Its report and full native inventory remain immutable.

The OR-only corrected provisional full run under
`.tmp/license-or-semantics-20261010-r1/unit-2026-10-10T125518976Z` has 123
passes, zero failures/cancellations/skips/todos. It replays the entire original
70-control file, correcting those two OR expectations, plus 53 new controls.
Native TAP and JUnit are retained. Coverage includes the root/private-workspace defect,
all exact terms, compounds, missing/unknown licenses, bounds, omitted
workspaces/runtime, lock drift, missing installed packages, optional platforms,
aliases, nested/multiple-workspace/cycle identities, peer/dev flags, exact
extra diagnostics, traversal order and real CLI report/overwrite behavior.
Additional controls cover both OR orders, nested AND/OR precedence,
deterministic selected obligations, unused terms, missing/malformed syntax on
either branch, valid LicenseRef/DocumentRef syntax, invalid identifier/exception
forms, length/token/depth bounds on both branches, and inventory-level jszip
approval with no GPL-policy failure. The standard Security job selects this
exact full file without a name filter.

After descriptor hardening, the provisional complete run
`unit-2026-10-10T130259214Z` has 140 passes and zero
failures/cancellations/skips/todos: the original 70 controls with two corrected
OR expectations, 53 OR controls and 17 descriptor controls. All run in the
same standard file. The final clean-commit replay and source/blob hashes are
retained in the new ignored evidence root, not substituted for the historical
123- or 70-control inventories.

The historical committed 20-rejection report is
`.tmp/license-gate-20261010-r1/actual-report-2026-10-10T122109487Z/license-report.json`,
SHA256 `04906622dbbb509455b848df475198ab2347de8ae1723cb3e4734f57a759accd`.
It contains the OR false positive and is superseded, not rewritten or greened.

The corrected provisional
`.tmp/license-or-semantics-20261010-r1/actual-2026-10-10T125520285Z/license-report.json` is a complete native
reconciliation: two first-party roots, 200 runtime locations, 166 unique
package/version IDs, 158 installed and 42 lock-only optional, zero inventory
errors, 19 policy rejections. Both native npm inventory exits are zero; the
policy gate exits 1, deliberately not green. Report SHA-256:
`b9f7d3e91ce2289dfbc9b829285485a00f9cadc13f2d0466d4ff6e105ae46f32`.
`jszip@3.10.2` is approved with `selected_terms: ["MIT"]` and
`unused_unapproved_terms: ["GPL-3.0-or-later"]`. The 19 other rejection identities
and expressions remain the same; no license term or dependency version changed.
The descriptor-hardened provisional replay
`actual-2026-10-10T130341187Z/license-report.json` has the same complete inventory
and 19 rejections, SHA256
`3fcdf5f240374e3aaa05af576dbd4cb700413c5f93e3c07c3f499404f90c1026`.

These provisional runs use Node 24.15.0 on Windows, not the hosted Ubuntu/Node
22 environment, and precede the final committed-source replay. The final
ignored receipt/seal must bind that replay to its exact commit and blobs.
There is no claim of hosted CI, Docker, browser or production acceptance here.

Retained earlier evidence is not overwritten: the initial 59-test run had one
fixture-aliasing regression failure (58 pass); fresh replacements pass.
Three initial actual captures were inventory-incomplete (native optional-extra
diagnostics, a runtime peer marked dev, then traversal-dependent extra identity).
Their exit-2 reports remain incomplete; the complete replacement above does not
retroactively certify them.

## Explicit Review Dependencies

Exact current lock IDs outside the allowlist, including compound expressions:

| Package ID | Locked Expression | Local Installation |
| --- | --- | --- |
| `@fontsource/atkinson-hyperlegible@5.2.8` | `OFL-1.1` | installed |
| `@fontsource/jetbrains-mono@5.2.8` | `OFL-1.1` | installed |
| `@fontsource/libre-caslon-text@5.2.7` | `OFL-1.1` | installed |
| `@img/sharp-libvips-darwin-arm64@1.3.4` | `LGPL-3.0-or-later` | lock-only optional |
| `@img/sharp-libvips-darwin-x64@1.3.4` | `LGPL-3.0-or-later` | lock-only optional |
| `@img/sharp-libvips-linux-arm@1.3.4` | `LGPL-3.0-or-later` | lock-only optional |
| `@img/sharp-libvips-linux-arm64@1.3.4` | `LGPL-3.0-or-later` | lock-only optional |
| `@img/sharp-libvips-linux-ppc64@1.3.4` | `LGPL-3.0-or-later` | lock-only optional |
| `@img/sharp-libvips-linux-riscv64@1.3.4` | `LGPL-3.0-or-later` | lock-only optional |
| `@img/sharp-libvips-linux-s390x@1.3.4` | `LGPL-3.0-or-later` | lock-only optional |
| `@img/sharp-libvips-linux-x64@1.3.4` | `LGPL-3.0-or-later` | lock-only optional |
| `@img/sharp-libvips-linuxmusl-arm64@1.3.4` | `LGPL-3.0-or-later` | lock-only optional |
| `@img/sharp-libvips-linuxmusl-x64@1.3.4` | `LGPL-3.0-or-later` | lock-only optional |
| `@img/sharp-wasm32@0.35.5` | `Apache-2.0 AND LGPL-3.0-or-later AND MIT` | installed |
| `@img/sharp-win32-arm64@0.35.5` | `Apache-2.0 AND LGPL-3.0-or-later` | lock-only optional |
| `@img/sharp-win32-ia32@0.35.5` | `Apache-2.0 AND LGPL-3.0-or-later` | lock-only optional |
| `@img/sharp-win32-x64@0.35.5` | `Apache-2.0 AND LGPL-3.0-or-later` | installed |
| `nodemailer@10.0.13` | `MIT-0` | installed |
| `pako@1.0.11` | `(MIT AND Zlib)` | installed |

Review is needed for OFL-1.1, LGPL-3.0-or-later, MIT-0 and Zlib. Selecting the
already-approved MIT alternative does not require GPL approval. No new terms
or obligations have been approved
by this patch. Linux/macOS variants are lock inventory, not a claim of the
exact deployed image contents. Preserve this red result and the inherited gap;
do not close license certification on `{}`, metadata-only inventory, skipped
checks, permissive substrings or a policy edited merely to make CI green.

[Issue #530](https://github.com/mishrasanjeev/caseops/issues/530) and
[draft PR #531](https://github.com/mishrasanjeev/caseops/pull/531) durably publish
the repair and remaining policy dependencies under explicit user approval.
Both remain held/open; the corrected gate is still expected red with 19
rejections. Main owns integration, hosted release gates and policy decisions.
No merge, deployment or license certification occurs in this scoped work.

## Integration Boundary - 2026-10-12

The merged Security workflow retains the Python `license-allowlist` job's
host scan and exact Dockerfile `prod-deps` Linux x64 musl scan. Its required
authoritative verifier receives the checkout as `--review-root`: the host's
`$GITHUB_WORKSPACE`, and a read-only full-checkout mount at `/reviewed-source`
in musl. Raw nonempty scanner reports remain required. The redundant legacy
substring-based `--onlyAllow` invocation is removed, not the verifier.

The separate `license-workspace-lock-policy` job is appended after all existing
jobs, without a sibling success dependency. It retains complete Node TAP/XML,
both native inventories and stderr, and the report under the distinct
`js-license-workspace-lock-report` artifact using `if: always()`. Its eight
independent wiring controls select only this job, test next-job/EOF boundaries,
and reject sibling-marker substitution, missing raw evidence and swallowed
failures. Original 140 native identities and assertions remain, except for
the precise selector in the original workflow wiring test.

Neither gate globally approves OFL, LGPL, MIT-0 or Zlib. The base 14 terms and
their hash above are unchanged. A present `license-policy/reviewed-packages.json`
can authorize only exact name/version/license expression/package-lock integrity
under schema 1 and `managed-saas-only`, with a hashed review document and every
declared material. Node defaults the review root to the inventory root; explicit
`--review-root` permits an independent read-only checkout. Scanner integrity is
not substituted for lock integrity. All physical lock rows remain visible,
including absent platform optionals. Missing review grants no admission;
invalid review evidence fails closed while retaining the native inventory.

The contract permits only `license-policy/**`,
`apps/web/public/third-party-notices/**`, and exact
`docs/security/js-license-compliance-review-2026-10-12.md` material/document
paths. Absolute/traversal/backslash/colon/private dot paths and reparse parents
or leaves are rejected before content reads. A supplied review-root link is
rejected before normalization; parent traversal in that root is forbidden.
The review document must use the exact compliance-document path above, not
merely any permitted material path. Registry bytes are capped at
128KiB, each material at 1MiB, entries at 1-32, materials per entry at 1-32, and
unique referenced paths across the registry at 64, including the review document.
Name/version/license/integrity fields are nonempty and bounded respectively at
214/128/2048/512 Unicode code points, with control characters rejected. Integrity
must be one lowercase `sha512-` SRI with strict standard base64 decoding to exactly
64 bytes and exact re-encoding equality for canonical padding bits; permissive
Node decoding or Python `validate=True` alone does not validate canonicality. All entry,
field, integrity, duplicate and global reference caps precede material content reads.
Unknown fields, duplicate
JSON keys/package IDs/material paths, conflicting or non-lowercase hashes and
changed bytes are rejected. Each file uses one bounded descriptor; only verified
digests are retained and every new reconciliation revalidates the files.

Fake-unit materials explicitly convey no production license approval. This
worker neither authors nor approves the central registry. The historical
19 lock-policy denials above and eight physically shipped denied identities
are different scopes; previous receipts are not new-source acceptance. Actual
material research, complete notices, the managed-SaaS limitation, current hosted
and musl execution, and amended release acceptance remain parent-owned. No
global policy widening, dependency change, license waiver or release approval
is claimed by this integration.

## Native Optional Marker - 2026-10-12

The retained real npm inventory at the pre-freeze HEAD label `031508ae` exits
zero for both native commands, but the previous Node guard exits two with
`unreconciled_extraneous_package`. All six installed WASM-related extras are
exact nonlink lock-backed identities with `optional: true` in the lock; npm's
installed JSON omits their native `optional` property. Requiring that redundant
native property to be explicitly true was an output-shape assumption, not a
licence-policy failure. The original failed output remains retained.

Only an absent native marker is newly accepted, with locked optionality still
mandatory. Explicit false, null, nonboolean and own-undefined native markers
remain rejected. Name/version/license, nonlink targets, exact diagnostics,
declared child edges, duplicate locations and complete physical/logical
membership checks remain unchanged. The four genuinely dev-only extras remain
visible separately; the two virtual runtime extras remain policy checked.

Nineteen added controls cover the realistic six-copy shape, repeated peer
traversal in both orders, marker and locked-optionality corruption, unknown,
unlocked or mismatched targets, links, unexpected nondev copies, undeclared
children and unmatched diagnostics. A positive graph control deliberately
retains an unreviewed MIT-0 policy denial; graph acceptance is not licence
approval. The existing 233 controls, including the original 140 assertions,
are retained unchanged. Fresh complete native tests and real offline npm
inventories are required against exact source-file hashes before local closure.
Dirty HEAD labels do not certify a committed release, and this correction
does not authorize future commercial binary delivery or provider activation.
