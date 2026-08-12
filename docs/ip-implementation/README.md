# IP implementation control plane

`PROGRAM_MANIFEST.yaml` is the only manually maintained program-status and
traceability source. It uses JSON syntax, which is a valid YAML subset, so the
validator has no dependency outside the Python standard library.

Schema version 2 records PRD-explicit and derived suffix slices, reciprocal
requirement/path allocation, stable planned or executable test references,
ownership and release boundaries, evidence metadata, milestone gates, and
child-derived status. Parent epic, milestone, requirement, journey, path, and
program status must not be edited optimistically; validation recomputes it.

The Markdown files under `generated/` are projections. Do not edit them.

From the repository root:

```powershell
python scripts/ip_program_manifest.py validate
python scripts/ip_ownership_ledger.py validate
python scripts/ip_arch_ops_contract.py validate
python scripts/ip_data_class_registry.py validate
python scripts/ip_program_manifest.py generate
```

`OWNERSHIP_LEDGER.yaml` is the binding PRD Section 11.2 one-writer registry for
all M2/M3 proposals. `ARCH_OPS_CONTRACT.yaml` publishes the exact
ARCH-OPS-01..26 control mapping, and `IP_EVENT_CATALOG.yaml` publishes stable
versioned audit-action and domain-event schemas. Their validators are required
CI gates. `IPLF_027A_DATA_CLASS_REGISTRY.yaml` is the narrower pre-schema
admission for the five IPLF-027A foundation tables; its fail-closed dispositions
do not claim the runtime retention/hold/export/purge/restore work allocated to
IPLF-028. These controls authorize no early nullable schema and do not replace the
behavior-level journeys, mixed-revision proof, deployment evidence, or human
approval allocated to later slices.

`IP_CAPABILITY_MODEL.md` documents the IPLF-020A extension of the existing
backend/frontend capability catalogues. Server capability, billing entitlement,
and safety rollout are independent fail-closed gates; frontend visibility is
never authorization. All IP flags default off and optional pilot expiries fail
closed, so deploying the catalogue alone exposes no operational IP feature.

`IP_DOCUMENT_FOUNDATION.md` documents the IPLF-024A one-writer decisions,
additive schema, shared storage/processing boundary, tenant taxonomy and alias
contracts, and the dependent IPLF-024B upload, duplicate-reuse, processing,
review/approval, policy, bulk, and alias workflow. IPLF-024A is
`deployment_verified` at canonical release `65f7c5cd...`; exact build, image,
migration, scheduler, and production-browser evidence is retained in
`evidence/m2/IPLF-024A/release-2026-08-09.md`. IPLF-024B is also
`deployment_verified` at canonical release `64f6360b...`; its exact CI, build,
image, migration, scheduler, and successful dated production evidence is
retained in `evidence/m2/IPLF-024B/release-2026-08-10.md`. Evidence-head release
`18a199bf...` subsequently remediated the integrations cold-start request burst
and reconfirmed the full production suite; its exact evidence is retained in
`evidence/m2/IPLF-024B/cold-start-remediation-2026-08-10.md`.

`SHARED_WORK_FOUNDATION.md` documents the IPLF-025A expansion of the existing
task, hearing, next-hearing, operational-deadline, calendar, reminder, and
durable-notification owners to tenant-correlated IP docket targets. It records
the three-step expand/backfill/switch migration, forbidden duplicate tables,
release-blocking reconciliation, legal-deadline one-writer boundary, and
rollback contract used by IPLF-025B. IPLF-025A is `deployment_verified` at
canonical release `2f27f044...`; exact CI, image, migration, scheduler,
reconciliation, and production-browser evidence is retained in
`evidence/m2/IPLF-025A/release-2026-08-10.md`.

`CALENDAR_REMINDER_WORKFLOW.md` documents the IPLF-025B hearing, reminder, and
external-calendar behavior over those shared owners. IPLF-025B is
`deployment_verified` at canonical release `88ef0b99...`; exact CI, immutable
images, migration, scheduler, isolated entitled-canary, PostgreSQL repair, and
two successful production-browser workflows are retained in
`evidence/m2/IPLF-025B/release-2026-08-11.md`.

`bootstrap` is a one-time mechanical extraction command and refuses to replace
an existing manifest unless `--force` is supplied. Do not use `--force` on an
actively maintained program manifest.

`scripts/reconcile_ip_program_manifest_phase0.py` records the reviewed 2 August
2026 Phase 0 allocation. It is retained as a reproducible audit/migration tool,
not as a completion generator: it preserves `not_started` future scope and does
not infer implementation, verification, release, or human acceptance.

Evidence belongs under `evidence/<milestone>/<slice>/`. Evidence must name the
command, environment, revision, fixture/data scope, assertions, and result.
Generated prose or an empty file is not acceptance evidence.
