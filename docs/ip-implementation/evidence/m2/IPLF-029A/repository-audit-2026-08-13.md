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

The audit implementation at exact revision
`76d23c8d81509f936eb4dd1c4c94e19f3b228c08` passed pull-request CI
`31760287600`, Security `31760287635`, and CodeQL `31760287570` before PR #220
merged. Those checks included the negative generated-view regression and the
full API, PostgreSQL, web, and Playwright gates. This is immutable evidence that
the bounded repository audit control works. It does not prove the canonical
slice's separate requirement to close every M2 row, so IPLF-029A remains
`in_progress / not_run / blocked / pending` while the unresolved rows listed
below remain open.

## Remaining M2 closure conditions

The audit deliberately retains, rather than conceals, the current incomplete
work: the provider-gated IPLF-026B release; the remaining IPLF-027 and
IPLF-028B user workflows; the six-class IPLF-028A runtime registry boundary;
the policy/recovery and data-operation blockers in IPLF-028; and all named
acceptance. IPLF-028C now supplies only the repository inventory and
Definition-of-Ready facets of `DATA-GOV-01` and `DATA-GOV-03`; it does not
satisfy `DATA-GOV-02` or any runtime/recovery facet. The result is a
Definition-of-Ready guard, not a claim of legal, security, pilot, UAT,
production, recovery, or data-operation completion.
