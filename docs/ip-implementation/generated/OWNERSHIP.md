# Ownership view

Generated; do not edit.

| Slice | Class | Component | Canonical writer | Compatibility | Retirement gate |
| --- | --- | --- | --- | --- | --- |
| IPLF-027A | NEW | IPLF-027 canonical scope: Add shared idempotency/outbox/consumer-effect foundations, lifecycle workflow versions/transition commands, OpenAPI, audit/domain-event catalogues, mixed-revision fencing and migration rollback proof. | The existing Section 11.2 owner, extended by the parent epic's typed adapter/service; any new record is owned by the PRD-named neutral or IP bounded context. | Existing Matter/platform routes and records remain canonical; additive adapters delegate to one writer and preserve legacy reads during rollout. | No compatibility path is retired until one-writer reconciliation, mixed-revision proof, rollback evidence, and exact deployed acceptance pass. |
