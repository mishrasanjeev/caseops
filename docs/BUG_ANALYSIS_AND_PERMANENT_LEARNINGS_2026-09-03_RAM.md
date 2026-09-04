# Ram 03 September 2026 workbook — root-cause analysis

## Scope and source reconciliation

`CaseOps_Bugs_Ram03Sep2026.xlsx` contains three populated issue rows:
BUG-004, BUG-005, and BUG-006. Its `Summary` tab says there are four issues and
describes unrelated forum-mapping and duplicate-user defects. That copied
summary is stale and is not evidence for this batch.

The workbook was saved before the same-day eCourts and Indian Kanoon releases.
Those two reports were valid observations at the time, but must be revalidated
against the exact deployed revision rather than treated as proof about the
current system.

## Issue assessment

### BUG-004 — eCourts search and support visibility

- Classification: valid integration/configuration defect at report time.
- Current cause of confusing retests: automated tests deliberately carry the
  `no-paid-providers` marker. The resulting rejection was sometimes read as a
  provider outage even though it proves cost isolation is working.
- Product correction: provider-wide eCourts scope is tenant-visible, exact CNR
  and case-number searches share the same adapter contract, and provider
  readiness is exposed without a human approval gate.
- Acceptance: ordinary regression asserts readiness, support scope, the
  no-paid boundary, and an unchanged CaseOps-recorded budget balance. The
  former automated paid canary was retired on 2026-09-04; paid operation is a
  funded authenticated human workflow.

### BUG-005 — Act and section completeness

- Classification: valid product defect, plus an over-broad requested
  expectation. Users must see the whole catalog, but CaseOps must not permit an
  unverified legal provision to be attached as if it were authoritative.
- Root cause: the prior closure proved only Article 14 and hid every Act with
  zero verified sections. Worse, the browser filtered unverified sections but
  the direct matter-reference API did not enforce the same predicate.
- Product correction: the API returns safe metadata for every active
  catalogued Act and section, reports catalogued versus verified totals, and
  labels each section's selection state. The UI displays pending entries as
  disabled. The write endpoint independently rejects inactive, incomplete, or
  unverified source manifests.
- Data truth: source verification is a separate controlled ingestion task.
  Placeholder or partially sourced text is not promoted merely to make a
  dropdown look complete.

### BUG-006 — Indian Kanoon setup state

- Classification: valid integration/configuration defect at report time.
- Product correction: the adapter reads the configured secret, publishes
  tenant-safe readiness, supports licensed search and attribution, and has no
  manual approval dependency.
- Acceptance: regular regression proves configuration/readiness, exposes the
  CaseOps-recorded workspace budget balance, and blocks paid calls before
  transport. Provider prepaid balance is not inferred where no non-billable
  provider endpoint exists. Real results and attribution remain available to
  authenticated humans on funded live tenants.

## Why issues were reopened

1. A one-row positive fixture was reported as full statute coverage.
2. UI filtering was treated as enforcement; the API bypass was not tested.
3. Source-tree or pre-deployment results were reported without proving the
   exact production revision.
4. A deliberate no-paid test rejection was conflated with a production
   provider outage.
5. The workbook's copied summary was trusted instead of reconciling populated
   issue rows.

The `ReOpen` values in this workbook are issue-tracker states. They do not prove
that a disposed Matter was silently reactivated. Matter lifecycle investigation
must use persisted status and audit events. Generic patches, imports, workers,
and child writes remain unable to reopen a disposed Matter; the only supported
reopen is an explicit, audited `Disposed -> Intake` lifecycle transition.

## Permanent acceptance standard

- Use one server-owned source-verification predicate for read counts, picker
  enablement, and write admission.
- Assert both positive and negative paths: a verified provision attaches; a
  pending provision remains visible but cannot attach through UI or API.
- Keep paid providers out of bulk and regular suites. Use deterministic local
  data and the no-paid request marker.
- Validate Docker before publication, then assert API and web release identity
  against the exact production SHA before repeating the dated tests.
- Do not mark an integration fixed based only on configuration. The bounded
  canary must return usable provider data, while readiness and support metadata
  remain independently testable without charge.
