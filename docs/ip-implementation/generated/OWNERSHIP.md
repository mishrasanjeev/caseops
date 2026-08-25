# Ownership view

Generated; do not edit.

| Slice | Class | Component | Canonical writer | Compatibility | Retirement gate |
| --- | --- | --- | --- | --- | --- |
| IPLF-057B | NEW | IPLF-057 canonical scope: Madrid international registration/designation and WIPO reconciliation. | TrademarkInternationalRegistration owns type-specific IR/designation facts; existing ip_docket_records, ip_relationships, ip_docket_events and Section 11.2 shared services retain access, lifecycle, links, sourced events and operational state. | Existing Matter/platform routes and records remain canonical; additive adapters delegate to one writer and preserve legacy reads during rollout. | No compatibility path is retired until one-writer reconciliation, mixed-revision proof, rollback evidence, and exact deployed acceptance pass. |
