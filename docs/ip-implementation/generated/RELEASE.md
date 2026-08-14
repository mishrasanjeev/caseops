# Release view

Generated; do not edit.

| Slice | Release | Acceptance | Blockers | Next actions |
| --- | --- | --- | --- | --- |
| IPLF-028A | blocked | not_required | The repository registry covers only the six new IPLF-028A governance tables; it is not the complete SQL/object/index/cache/queue/log/export/provider/backup data map required by DATA-GOV-01 through DATA-GOV-03.; No approved retention schedule, legal-hold activation/release workflow, step-up/four-eyes decision, or tenant-facing review contract has been supplied for a real data operation.; No current database-plus-object application-cutover restore rehearsal or tenant-export dry run has been performed against an approved environment. | Keep the new records-governance tables unseeded and the service dry-run-only; no route, worker, scheduler, storage adapter, provider adapter, or execute mode is authorized in IPLF-028A.; Expand the registry to every in-scope data class and enforce the data-map update gate before marking foundation implementation complete.; Obtain explicit legal/privacy/security approval for policy, holds, step-up, four-eyes, and user workflow before designing any real data-operation command.; After independent CI and approved non-live resilience preparation, run the required database-plus-object cutover restore and tenant-export dry run with named operators and reviewers. |
