# Test-Legal Manual IP QA Grant

## Scope And Current Status

The owner authorized a non-billable manual-IP entitlement for the existing
`test-legal` QA tenant on October 14, 2026. This is not a paid-plan upgrade,
provider activation, general entitlement-management API or permission to change
GBA. At this checkpoint the grant has not executed in production.

The October 14 readiness read on serving `3dbf364d` found an enabled, configured
manual workspace with no enabled automations, but no IP entitlement. A fresh
local bootstrap had a separate missing-configuration condition. These are
different preconditions, not missing imported records.

The one-shot operator changes only `ip_workspace` in the existing subscription's
entitlement overrides, plus the subscription's normal update timestamp and one
audit receipt. It preserves other override keys, plan, status, billing fields,
provider fields and workspace configuration. It neither creates an account or
subscription nor invokes an external provider. Workspace rollout, source trust,
record access and lifecycle checks remain authoritative.

## Inspect Before Applying

1. Complete the candidate's local service, PostgreSQL, deployment-contract,
   Docker and hosted CI gates. Merge the validated tree to canonical `main`.
   Do not inject an unreviewed script into an older production image.
2. Inspect production through a bounded PostgreSQL `REPEATABLE READ, READ ONLY`
   transaction. Verify the read-only setting and always roll back. Resolve
   the exact existing `test-legal` company and its unique active subscription.
   Keep connection credentials in process memory, outside source and evidence.
3. Require an active company, the exact inspected identifiers and a subscription
   with `externally_billable=false`. Do not change a paid subscription to make
   this guard pass. Ambiguous, missing or changed identities require a new
   investigation, not an automatic repair.
4. Use the candidate-owned application interpreter to invoke
   `caseops_api.scripts.qa_manual_ip_entitlement inspect` with `--company-id`
   and `--subscription-id`. Record its minimal identifiers and `before_sha256`.
   Inspection does not initialize billing or workspace state.
5. Generate one operation UUID and retain it for this authorization. Prepare a
   JSON input outside the release checkout with exactly these fields:

```json
{
  "schema_version": 1,
  "company_id": "<inspected company UUID>",
  "subscription_id": "<inspected subscription UUID>",
  "before_sha256": "<inspected lowercase SHA-256>",
  "operation_id": "<one retained operation UUID>"
}
```

Placeholders are not accepted values. Do not put a password, provider key,
contact details or legal content in this input.

## Apply Through The Guarded Release

1. Set `CASEOPS_TEST_LEGAL_MANUAL_IP_GRANT_INPUT` to the approved input's absolute
   path and `CASEOPS_TEST_LEGAL_MANUAL_IP_GRANT_OUTPUT` to a new evidence-file
   path outside the release checkout. The output's parent must exist and the
   output file must not. Neither variable set means no grant is requested.
2. Run the normal clean, exact-SHA `scripts/deploy-prod.sh` release. Input shape
   is checked before cloud work and its fingerprint is checked again at apply.
   The optional control runs after the exact-image QA canary and before the
   automatic production-verification dispatch. Canonical main is rechecked at
   the mutation boundary.
3. Verify the dedicated job and execution use the exact API digest, release,
   one task, no automatic retries and only the required database/auth secrets.
   The job is not part of the recurring scheduler inventory. A failed or
   uncertain execution is not permission to submit another mutation.
4. Retain the execution-specific grant receipt, operation and audit identifiers,
   input fingerprint, and before/after fingerprints. A separate read-only
   inspection execution must match the recorded after-fingerprint. This is not
   another grant or a mutation retry. Check current workspace
   readiness through the marked `test-legal` login. A successful job alone does
   not certify that a user can open an imported docket.
5. Run the committed October 13 IP and Calendar production journeys at both
   desktop and mobile widths against the exact serving API/web SHA. All
   automated requests retain the no-paid-provider marker. Do not skip a
   readiness failure or weaken a source/lifecycle boundary.
6. Remove the optional input/output variables from subsequent release requests.
   Do not add this grant to a bootstrap, scheduler or default release action.

## Replay And Recovery

The release helper binds its container list as one `--args=...` token, following
the existing scheduler helper. Separate dash-prefixed values are rejected by
the installed SDK parser even when CMD preserves every argument. It uses the
default cloud CLI comma separator only for its
fixed module/flags and validated UUID/hash arguments. Native Windows CMD tests
assert the complete received argv for grant and inspection; a zero exit alone
does not prove argument transport. Do not restore caret/pipe delimiters.

Cloud-command failures retain an allowlisted `cloud_error.stage` and typed
`cloud_error.category` beside the existing constant `error_code`. Raw command
arguments, stdout, stderr and exception messages are not diagnostic evidence.
Use the stage to investigate the retained execution state; do not increase
deadlines or automatically repeat a mutation. The original09d preflight failure
discarded its exact stage, so a separately reproduced transport defect must
not be represented as that historical command's proven cause.

The service inserts the grant and its deterministic audit receipt atomically
under Company-first locking. An identical service replay is a no-op only while
the current state still matches the recorded after-state. A consumed operation
cannot regrant access after revocation or repair later billing/identity drift.

If execution fails or its outcome is uncertain, retain the original evidence
and inspect the existing audit receipt and current subscription read-only.
Do not generate a fresh operation UUID merely to bypass a consumed-operation
rejection. Any later grant requires a separately reviewed authorization and
fresh before-state. A revoked test-legal QA entitlement stays revoked by default.

Full acceptance and production proof are recorded in
`docs/BUGFIX_IP_CALENDAR_2026-10-13.md`. Until that evidence is complete, the
reported IP/Calendar requirements remain partially fixed and the unidentified
historical Matter reopening remains inconclusive.
