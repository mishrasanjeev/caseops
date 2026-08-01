# Ownership view

Generated; do not edit.

| Slice | Class | Component | Canonical writer | Compatibility | Retirement gate |
| --- | --- | --- | --- | --- | --- |
| IPLF-001B | EXTEND | Cloud Scheduler and Cloud Run recurring-job deployment control | infra/cloudrun/scheduler-inventory.json interpreted by scripts/scheduler_inventory.py and invoked by scripts/deploy-prod.sh | Existing Cloud Run job command, environment, secrets, resources, and runtime service account are preserved while image, scheduler, and invoker IAM drift converge. | The superseded midnight case-tracking scheduler is paused only after the 16:30 replacement passes live configuration verification; rollback is resume-old/pause-new. |
