# WTD-5.1c Temporal Operator Runtime Proof

- Date: `2026-05-26`
- Branch: `codex/wtd-5-1c-operator-temporal-proof`
- Base: `origin/main` at `c1b5703b9308e0ca9e5556a80c4f81c2172f6959`
- Verdict: `GO`

## Scope

This pass covers WTD-5.1c only: operator runtime proof for the existing
WTD-5.1a/WTD-5.1b Temporal notification workflow foundation.

The proof target is the existing deterministic no-op notification-intent
workflow/activity. This pass does not add delivery behavior, schedule
reminders, add polling loops, call external providers, run corpus jobs, run OCR
or document-processing jobs, or modify production deploy paths.

## Existing Runtime Surface

- Worker entrypoint: `caseops-notification-workflow-worker`
- Module entrypoint: `caseops_api.workers.notification_workflows`
- Worker mode checked: `--check-config --require-available`
- Existing workflow: `NotificationIntentRuntimeProbeWorkflow`
- Existing activity: `notification_intent_noop_activity`
- Existing activity result remains no-op:
  - `delivered=false`
  - `scheduled=false`
  - `external_calls=0`

## Operator Temporal Backend

- Backend owner: operator-managed CaseOps GCP project.
- Backend resource: `caseops-temporal-proof-vm-mumbai`.
- Region/zone: Mumbai, `asia-south1-c`.
- Machine class: shared-core `e2-micro`, proof-only sizing.
- Temporal gRPC: `tcp:7233`, restricted by firewall to the current operator
  workstation `/32`.
- Temporal Web UI: not exposed.
- Local config source: ignored local operator env snippet, loaded explicitly for
  the proof command.

No raw endpoint values, namespaces, task queue values, tokens, connection
strings, tenant IDs, matter IDs, task IDs, deadline IDs, or payloads are
recorded in this proof report.

## Proof Commands

```text
uv --directory apps/api run python -m caseops_api.workers.notification_workflows --check-config --require-available
```

Result: success.

Redacted worker status summary:

- `delivery_enabled=false`
- `reminder_scheduling_enabled=false`
- `external_provider_calls_enabled=false`
- `status.enabled=true`
- `status.backend=temporal`
- `status.available=true`
- `status.reason=available`
- `status.address_configured=true`
- `status.namespace_configured=true`
- `status.task_queue_configured=true`
- `status.missing_config_names=[]`
- `status.missing_dependencies=[]`

Python Temporal SDK health check:

- `temporal_client_connected=true`
- `workflow_service_health=true`

Verification commands:

```text
uv --directory apps/api run pytest tests/test_durable_workflows.py -q
uv --directory apps/api run ruff check src tests/test_durable_workflows.py
git diff --check
```

Results:

- Durable workflow tests: `11 passed`.
- Ruff: passed.
- Diff whitespace check: passed.

## Side-Effect Check

- Notification delivery: not run.
- Reminder scheduling: not run.
- External provider calls: not run.
- Outlook/Google/provider sync: not run.
- Corpus ingest/backfill/embedding jobs: not run.
- OCR/document-processing jobs: not run.
- Production deploy paths: not modified.
- New workflows: not added.

## Operations Note

The proof backend is intentionally small and should be stopped when no proof or
follow-on WTD-5.3 work is running:

```text
gcloud compute instances stop caseops-temporal-proof-vm-mumbai --project perfect-period-305406 --zone asia-south1-c
```

This backend is sufficient for the WTD-5.1c operator runtime proof. It is not a
production-grade Temporal cluster, and it does not by itself implement
notification delivery, retries, schedulers, provider sync, or ADP-20.

## Decision

`GO`: the existing Temporal runtime foundation is proven against the
operator-owned Mumbai backend using the existing no-op notification worker
configuration path.

WTD-5.3 durable notification delivery/retry foundation is now complete for
internal in-app delivery, bounded retry/dead-letter state, and fail-closed
external channel intents. ADP-20 durable Outlook sync remains blocked until
provider-specific policy, credential, and runbook prerequisites are complete.
