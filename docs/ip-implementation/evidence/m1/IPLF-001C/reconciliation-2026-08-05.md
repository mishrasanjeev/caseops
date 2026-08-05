# IPLF-001C Scheduler Delivery and Outcome Reconciliation

**Recorded:** 5 August 2026  
**Milestone:** M1 — Trust Recovery GA  
**Implementation revision:** `a8406178791d137c8db40f9664b225bcd4241bdc`  
**Production application revision audited:** `623ca8f5e88a8110c71cc1c6edca9c951eac7e1a`  
**Production API revision:** `caseops-api-00232-lls`  
**Production web revision:** `caseops-web-00212-rh9`  
**Production API/job image:** `asia-south1-docker.pkg.dev/perfect-period-305406/caseops-images/caseops-api@sha256:bb13c057680dec1d0d228306c1e22f4ebb960d5b605369ef30c02bdc4a262fb8`

## Outcome

IPLF-001C closes the repository-controlled scheduler/IAM/canary reconciliation
tail. The six canonical schedulers are enabled, target the intended Cloud Run
jobs, use the dedicated scheduler invoker, have job-scoped `roles/run.invoker`,
and point at the immutable production image. Every scheduler has a recorded
attempt with successful Scheduler-to-Cloud-Run delivery. Five latest workloads
succeeded. The latest authority-metadata workload was correctly invoked and
then stopped fail-closed on its configured daily provider-spend cap; its
immediately preceding natural execution completed successfully.

There is no fixed seven-day or other elapsed-duration release gate. Release
proof is exact-image configuration/IAM validation, a bounded delivery/canary
audit, workload outcome evidence, public health, exact-head CI, and dated
production journeys. Natural executions continue as SLO and incident evidence.

## Canonical ownership and duplicate-work decision

- Classification: `EXTEND`.
- Configuration owner: `infra/cloudrun/scheduler-inventory.json`.
- Reconciliation and audit owner: `scripts/scheduler_inventory.py`.
- Deployment owner: `scripts/deploy-prod.sh` invoking the inventory helper.
- Existing Cloud Run job commands, runtime identity, secrets, resources, data
  owners, provider budgets, notification owner, and application services remain
  unchanged.
- No scheduler, job, credential store, provider-operations dashboard, or
  notification dispatcher was duplicated.
- The legacy midnight case-tracking scheduler remains present and `PAUSED` as a
  recoverable compatibility path.

## Repository change

`scheduler_inventory.py audit` now adds bounded operational evidence to the
existing immutable-image/IAM/configuration verifier:

1. requires every canonical Scheduler resource to have a natural or bounded
   canary attempt;
2. fails when Scheduler delivery itself has a non-zero status;
3. fetches only the latest Cloud Run execution per owned job;
4. classifies the workload separately as `succeeded`, `failed`, `missing`, or
   `running_or_unknown`;
5. does not misrepresent a fail-closed application safety stop as IAM drift or
   as a successful workload.

The command introduces no application API, UI, schema, tenant-data, secret,
provider, or delivery mutation.

## Automated verification

From the exact implementation revision:

```text
uv --directory apps/api run pytest tests/test_scheduler_inventory.py -q
7 passed, 1 dependency deprecation warning

uv --directory apps/api run ruff check ../../scripts/scheduler_inventory.py tests/test_scheduler_inventory.py
All checks passed!

python scripts/scheduler_inventory.py validate
scheduler inventory valid: 6 recurring jobs
```

The tests cover inventory completeness, duplicate/mutable policy rejection,
immutable-image enforcement, Windows gcloud resolution, IAM/image drift,
successful/failed/missing execution classification, and the important split
between Scheduler delivery failure and workload failure.

## Dated production audit

The following read-only command was run against project
`perfect-period-305406` and region `asia-south1`:

```text
python scripts/scheduler_inventory.py audit \
  --project perfect-period-305406 \
  --region asia-south1 \
  --image asia-south1-docker.pkg.dev/perfect-period-305406/caseops-images/caseops-api@sha256:bb13c057680dec1d0d228306c1e22f4ebb960d5b605369ef30c02bdc4a262fb8
```

Result: exit `0`, aggregate `result=pass`, six of six configuration and
Scheduler-delivery checks passed.

| Scheduler | Last attempt UTC | Latest execution | Workload outcome |
| --- | --- | --- | --- |
| `caseops-legal-update-sync-midnight` | `2026-08-04T18:30:00.834119Z` | `caseops-legal-update-sync-xlv2q` | succeeded |
| `caseops-case-tracking-poll-1630-ist` | `2026-08-04T11:00:01.326561Z` | `caseops-case-tracking-poll-bmbk4` | succeeded |
| `caseops-activity-report-0800-ist` | `2026-08-05T02:30:00.729692Z` | `caseops-activity-report-jvxr9` | succeeded |
| `caseops-reminders-cadence` | `2026-08-05T02:30:01.128946Z` | `caseops-reminders-job-28hft` | succeeded |
| `caseops-extract-authority-metadata-daily` | `2026-08-05T00:30:00.729612Z` | `caseops-extract-authority-metadata-jq6zs` | failed after successful delivery; spend safety stop |
| `caseops-db-index-health-weekly` | `2026-08-02T02:30:00.186603Z` | `caseops-db-index-health-cgvj8` | succeeded |

The superseded `caseops-case-tracking-poll-midnight` resource was separately
described and remained `PAUSED`; the canonical 16:30 IST scheduler uses the
dedicated invoker.

## Authority-metadata exception adjudication

`caseops-extract-authority-metadata-jq6zs` was created by the configured
scheduler identity, imported and started the exact pinned container, and exited
non-zero after the application refused additional Layer-2 provider spend. The
log recorded spend of `$40.07` at or above the configured `$40` 24-hour cap.
The cap was not raised and the job was not forced.

The preceding natural execution
`caseops-extract-authority-metadata-bf9kq` completed successfully on
4 August 2026 after 23,358 seconds. Its bounded completion record reported
818,122 processed rows, 10,023 updates, zero missing-text and LLM errors, 137
parse errors, and 11,497 records with nothing to set. These aggregate counts
contain no tenant payload or secret.

This is a workload safety outcome requiring normal cost/SLO monitoring. It is
not an IAM, target, image, Scheduler-delivery, or deployment failure and does
not justify weakening the spend cap.

## Production availability and prior exact release proof

- `https://api.caseops.ai/api/health` returned HTTP `200` on 5 August 2026.
- Exact production workflow run `30965133241` for application revision
  `623ca8f5e88a8110c71cc1c6edca9c951eac7e1a` succeeded.
- The run recorded 54 RAM passes with four intentional environment skips and
  two of two Notice workflow passes.
- API and web served 100 percent intended traffic on the revisions named at
  the top of this record, and all six jobs were pinned to the same API digest.

Health is cited only as availability evidence; the audit and exact workflow are
the behavior/configuration evidence.

## Security and data impact

- Read-only gcloud describe/list/IAM-policy operations were used for this
  reconciliation.
- No scheduler or job was triggered, paused, resumed, deleted, or mutated.
- No external email, notification, filing, payment, legal act, or provider call
  was initiated.
- No tenant payload, client identifier, secret value, or rendered report is in
  this evidence.
- The existing fail-closed provider budget and job-level Invoker boundaries
  remain intact.

## Rollback and incident handling

The audit implementation is repository tooling and does not alter runtime. It
can be reverted independently without changing the live resources. For runtime
regression:

1. pause only the affected canonical scheduler;
2. inspect its bounded delivery result and latest workload outcome;
3. for case tracking only, resume the preserved midnight compatibility
   scheduler if the canonical cadence must be rolled back;
4. retain both resources until rollback has been verified, with no elapsed-time
   deletion rule;
5. rerun immutable-image/IAM verification and a side-effect-safe canary before
   restoring cadence.

## Status and remaining gates

- IPLF-001C implementation: `implemented`.
- IPLF-001C verification: `passed` locally and against production configuration.
- IPLF-001C release: `deployment_verified` for the audited scheduler behavior;
  the repository tooling still follows exact-head CI and normal merge controls.
- IPLF-001C acceptance: `pending` because program-level human acceptance is not
  manufactured by this engineering record.
- The scheduler elapsed-time blocker is closed.
- M1 and the overall program remain incomplete until the other exact-head
  releases and genuine legal/product acceptance gates are resolved.

