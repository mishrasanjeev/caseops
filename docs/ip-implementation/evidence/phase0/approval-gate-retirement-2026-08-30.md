# IP execution approval-gate retirement — 30 August 2026

## Result

The active CaseOps IP program is Codex-owned and no longer waits for a general
program signature, pilot signoff, child-domain PRD signoff, architecture review,
release review, or a waived recovery check. Repository completion is determined
by version-controlled contracts, executable validation, exact commit/image/schema
identity, and dated production acceptance.

This change does not manufacture authority for a product action. A named human
decision remains required only when the action itself is legally, financially,
externally, or destructively effectful: authoritative legal rules or conclusions,
filing/draft finalization, payments, client communications, emergency access,
provider licence activation, or an irreversible operation against customer data.
That authority is checked on the exact immutable object immediately before the
effect and cannot block unrelated fail-closed implementation or release.

## Retired execution gates

- M0 is a machine-validated program contract, not a manual signature checkpoint.
- M3/M7 pilot signoff is replaced by versioned fixture and exact-release suites.
- M8-M10 use version-controlled domain contracts and machine-validated
  legal/source packs; missing legal/provider authority disables only the affected
  capability.
- `ready_for_review` and `approved` are not IP release states;
  `ready_for_release` identifies verified work that still needs deployment proof.
- IPLF-027B revision retirement uses a short-lived signed manifest plus exact
  preflight assertions owned and executed by Codex, without a reviewer checkpoint.
- IPLF-028A restore/export evidence cannot be waived into truth; Codex must run the
  sanitized automated rehearsal. Retention-driven customer-data execution remains
  fail-closed until its exact legal/privacy authority exists.
- Ownership-ledger compatibility retirement is controlled by parity, rollback,
  one-writer, and exact-release evidence rather than migration signoff.

## Permanent regression controls

`scripts/ip_program_manifest.py` now rejects:

- reintroduction of the retired program/milestone phrases in PRD execution
  governance;
- top-level manual/human/signoff gate kinds;
- manual checkpoint phrases in active slice blockers, preconditions, next actions,
  or release boundaries; and
- obsolete `ready_for_review` or `approved` release states.

Focused validation after reconciliation:

- IP program manifest: 436 requirements, 50 families, 68 journeys, 317 atomic
  paths; passed.
- Ownership ledger: all Section 11.2 owners and M2/M3 proposals unique; passed.
- ARCH-OPS: 26 controls and versioned event catalogues; passed.
- M2 ownership audit: 26 M2 slices; passed.
- Manifest/ownership/ARCH-OPS/M2 tests: 69 passed.

Historical release evidence retains the facts of its dated candidate, with a
supersession notice making clear that generic human/pilot/program signoffs are no
longer active controls.
