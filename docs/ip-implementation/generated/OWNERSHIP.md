# Ownership view

Generated; do not edit.

| Slice | Class | Component | Canonical writer | Compatibility | Retirement gate |
| --- | --- | --- | --- | --- | --- |
| IPLF-025B | EXTEND | IPLF-025 canonical scope: Expand/backfill/switch existing task, hearing, next-hearing provenance, operational deadline, calendar and notification owners to IP targets in separate migrations; old Matter routes remain adapters and one-writer reconciliation is release-blocking. | The existing Section 11.2 owner, extended by the parent epic's typed adapter/service; any new record is owned by the PRD-named neutral or IP bounded context. | Existing Matter/platform routes and records remain canonical; additive adapters delegate to one writer and preserve legacy reads during rollout. | No compatibility path is retired until one-writer reconciliation, mixed-revision proof, rollback evidence, and exact deployed acceptance pass. |
