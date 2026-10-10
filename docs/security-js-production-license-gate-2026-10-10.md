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
License certification: `NO-GO`. The complete current inventory rejects 20
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
expression grammar accepts parentheses and AND/OR, but requires every explicit
term already be approved for both operators. It does not silently elect the
MIT alternative of an expression containing an unlisted GPL alternative.
WITH exceptions, unknown/missing metadata, malformed expressions and guessed
license-text corrections fail closed. This conservative OR treatment is an
explicit review dependency, not a claim that SPDX OR means AND. Any reviewed
alternative-election rule or new license approval needs a separately authorized
policy change and tests. The script does not certify license-text accuracy,
distribution compliance or third-party obligations.

## Local Native Evidence

Fresh isolated install and capture root:
`.tmp/license-gate-20261010-r1` in the owned
`demo-admin-guard-20261010/CaseOps` worktree. It never installs into the root
`node_modules` junction or modifies another checkout.

The provisional full unit run `unit-2026-10-10T121822779Z` has 70 tests,
70 pass, zero failures/cancellations/skips/todos; native TAP and JUnit are
retained. Coverage includes the original root-only/private-workspace defect,
all exact terms, compounds, missing/unknown licenses, bounds, omitted
workspaces/runtime, lock drift, missing installed packages, optional platforms,
aliases, nested/multiple-workspace/cycle identities, peer/dev flags, exact
extra diagnostics, traversal order and real CLI report/overwrite behavior.
The standard Security job selects this exact file without a name filter.

`actual-report-2026-10-10T121608234Z/license-report.json` is a complete native
reconciliation: two first-party roots, 200 runtime locations, 166 unique
package/version IDs, 158 installed and 42 lock-only optional, zero inventory
errors, 20 policy rejections. Both native npm inventory exits are zero; the
policy gate exits 1, deliberately not green. Report SHA-256:
`932858b776d58ad939d55c7f21595e4ee44389a27aea5b03a8697a46bc117df7`.

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
| `jszip@3.10.2` | `(MIT OR GPL-3.0-or-later)` | installed |
| `nodemailer@10.0.13` | `MIT-0` | installed |
| `pako@1.0.11` | `(MIT AND Zlib)` | installed |

Review is needed for OFL-1.1, LGPL-3.0-or-later, MIT-0 and Zlib and for any
authorized OR-alternative election. No terms or obligations have been approved
by this patch. Linux/macOS variants are lock inventory, not a claim of the
exact deployed image contents. Preserve this red result and the inherited gap;
do not close license certification on `{}`, metadata-only inventory, skipped
checks, permissive substrings or a policy edited merely to make CI green.

No PR is created while the actual focused policy gate remains red under the
user's all-focused-proof-green condition. Main owns subsequent integration,
hosted release gates and any policy decision; no merge or deployment occurs.
