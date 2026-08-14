# IPLF-029A M2 one-writer repository audit - 2026-08-13

## Scope and boundary

This repository-only control makes the M2 duplicate-ownership and
reconciliation exit condition reviewable without adding a new data owner,
schema, route, worker, storage adapter, provider operation, or external act.
It validates the canonical program manifest rather than inferring a completed
M2 program.

## Enforced minimum

For every active M2 slice, `scripts/ip_m2_ownership_audit.py` requires:

- a canonical-writer, compatibility-path, and retirement-gate ownership record;
- checked-in implementation and canonical-writer test references;
- a checked-in dated evidence artifact; and
- a named blocker whenever the active slice remains release-blocked.

For a `deployment_verified` slice, the control also requires an existing
evidence artifact. It reports the canonical manifest's status; it does not
inspect a live service or promote any status itself.

## Remaining M2 closure conditions

The audit deliberately retains, rather than conceals, the current incomplete
work: the provider-gated IPLF-026B release, unimplemented IPLF-027B and
IPLF-028B user workflows, policy/recovery and data-operation blockers in
IPLF-028, and all named acceptance. The result is a Definition-of-Ready guard,
not a claim of legal, security, pilot, UAT, production, recovery, or data
operation completion.
