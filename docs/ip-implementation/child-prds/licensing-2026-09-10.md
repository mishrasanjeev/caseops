# Licensing Workflow Contract

Version: OTHER-IP-2026-09-10.2. Owner: other-ip-domains.
Parent: PRD_IP_LAW_FIRM_PLATFORM_2026-08-01.md; LIC-01, IP-SCOPE-01..10,
UJ-30, UJ-43-NORMAL, UJ-43-EXC-01..04, UJ-60, UJ-61; IPLF-090A/B.
Supersedes intake-only admission for new writes, not historical evidence versions.

## Source-Reported Workflow

An authorized transactional lawyer versions the source instrument and records
grantor/grantee, grant type, rights, territory, field, term, exclusivity,
sublicensing, control, renewal, termination, notice and financial clauses.
Extraction is not review: ambiguous clauses retain review issues and sources.
Activation requires the IP review capability and resolved issues with rationale.
Financial terms require the confidential-finance capability for complete reads
and writes; a redacted response cannot overwrite the retained contract.

An active reviewed contract can create a supplied-date contractual obligation
with one canonical task and operational deadline, source clause and optional
active same-docket cost reference. No statutory deadline or invoice is inferred.
Creation and performance revalidate the current instrument source set, original
obligation clause and current cost lineage. Notice evidence, completion and
cancellation retain exact source versions and immutable performance history.
Completion/cancellation changes the obligation, task and deadline atomically.
Notice recording alone leaves work open. Replays do not create duplicate children.

Recordal is separate from contract review and registry ownership. Source-reported
acceptance retains its identifier/date. Termination closes the permission period
without deleting earlier terms or reopening the instrument. Surviving obligations
may still be performed while the parent docket remains operational.

## Shared Safety

Membership, capabilities, current grants, lifecycle version and source integrity
are checked under tenant-first locks. Stale commands, foreign-tenant evidence,
retired instruments and inactive cost references fail closed. Closing the parent
neutralizes operational children; explicit reopening does not resurrect them.
History remains permission checked. Any specialist document link denies general
AI, portal, export and notification disclosure. External delivery is not implied
by recording a notice receipt. No paid provider is called by these workflows.

## Acceptance And Open Scope

HTTP tests: test_licence_review_effective_period_obligations_recordal_and_financial_redaction,
test_ip_specialist_performance.py and the specialist source/access/lifecycle suite.
Frontend must show persisted obligations/performance, retain rejected input, and
use canonical source/cost choices. PostgreSQL atomicity/races, migration and
responsive browser execution remain independent acceptance requirements.

Not complete: cross-record affected-right linkage, official recordal automation,
royalty calculation/reconciliation, delivery/reminder failure recovery, portfolio
reporting and the complete parent UJ-43/UJ-60/UJ-61 journeys. Full-domain activation
remains NO-GO; the other seven domain journeys remain intake-only and unfinished.
