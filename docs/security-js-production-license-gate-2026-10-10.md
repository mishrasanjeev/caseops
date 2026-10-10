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

Only the Security license job, the new built-in-Node script and regression
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

## Local Native Evidence

Fresh isolated install and capture root:
`.tmp/license-gate-20261010-r1` in the owned
`demo-admin-guard-20261010/CaseOps` worktree. It never installs into the root
`node_modules` junction or modifies another checkout.

The historical committed run at `6cb037ab1a8942017c5a614803cd71a26c84c020`,
`unit-2026-10-10T122104998Z`, has 70 passes and zero skips. It verifies the old
implementation, not correct OR semantics: two expected OR rejections were
obsolete. Its report and full native inventory remain immutable.

The corrected provisional full run under
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
