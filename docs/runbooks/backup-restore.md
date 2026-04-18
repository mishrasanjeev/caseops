# Backup and restore runbook

**Owner:** platform oncall · **Last reviewed:** 2026-04-18 · **Maps to:** BG-043

This runbook covers the two things the business actually needs to
survive: recovery from accidental data loss, and proof-to-auditor
that a tenant's data can be retrieved within a defined RPO/RTO.

## Scope

CaseOps persists three classes of data that need protection:

| Store | Contains | RPO target | RTO target |
| --- | --- | --- | --- |
| Cloud SQL (Postgres 17 + pgvector) | Tenant tables, authority corpus, embeddings, audit trail | ≤ 15 min | ≤ 1 hour |
| Cloud Storage (`documents/…`) | Matter attachments, contract attachments, audit export artifacts | ≤ 1 hour | ≤ 2 hours |
| Artifact Registry | Container images | N/A (rebuildable from `git`) | N/A |

Local / founder-stage deployments use `docker-compose` Postgres on host
port `15432` and a local filesystem for documents. The runbook below
applies to both; the prod-only GCP steps are called out explicitly.

## Backups

### Postgres (managed, GCP staging + prod)

- Cloud SQL automated backups: **retained 30 days**, **daily snapshot
  at 02:00 UTC**, **point-in-time recovery enabled** (WAL retention 7
  days). These are configured on the Cloud SQL instance — verify via
  `gcloud sql instances describe caseops-pg-prod --format="value(settings.backupConfiguration)"`.
- WAL / binary logs go to the same instance; PITR window is the full
  retention window.
- Cross-region replica: **one read replica** in a second region. Used
  for analytics offload AND warm standby. Promotion drill runs
  quarterly (see §"Restore drill").

### Postgres (local / founder-stage)

```bash
# From the workstation, with the docker-compose stack up
pg_dump --host 127.0.0.1 --port 15432 --username caseops \
  --format=custom --jobs=4 --file caseops-$(date +%Y%m%d).dump caseops
```

Store the dump **outside** the repo. `.gitignore` already blocks
`apps/api/storage/`; dumps live in `~/caseops-backups/` on the
workstation.

### Cloud Storage documents

Enable on the prod bucket (`caseops-documents-prod`):

- **Object versioning: ON**. Every overwrite keeps the previous
  object, indefinitely, until a lifecycle rule expires it.
- **Lifecycle rule**: soft-delete objects older than 90 days; hard
  delete older than 365 days **unless** the object is on a
  legal-hold bucket prefix (`legal-hold/…`).
- **IAM**: the Cloud Run service account has `storage.objectCreator`
  + `storage.objectViewer`; only the break-glass admin has
  `storage.objectAdmin`. No role outside these two can delete
  objects directly.

## Restore

### Scenario 1: a tenant accidentally deleted a matter

1. Confirm the deletion in the audit trail:
   `SELECT * FROM audit_events WHERE target_type='matter' AND action='matter.archived' AND target_id=:id;`
   (CaseOps uses soft-delete for matters — this should recover via
   `UPDATE matters SET is_active=true WHERE id=:id;` inside a
   transaction. No actual deletion happens without a tenant-purge
   job.)
2. For matters that were genuinely hard-deleted via the tenant-purge
   CLI, restore from the nearest PITR window using Cloud SQL point-
   in-time recovery.

### Scenario 2: a tenant's documents bucket is corrupted

1. List the affected storage prefix:
   `gsutil ls gs://caseops-documents-prod/<company_id>/`
2. Restore object versions one level up via the Console or via:
   `gsutil cp gs://caseops-documents-prod/<company_id>/...#<generation> gs://caseops-documents-prod/<company_id>/...`
3. For the corpus, documents can be re-ingested deterministically
   from the public S3 sources (`indian-high-court-judgments`,
   `indian-supreme-court-judgments`) via the
   `caseops-ingest-corpus` CLI. Ingest is idempotent
   (canonical-key dedup); re-running does not double-insert.

### Scenario 3: Postgres instance is dead

1. Promote the cross-region read replica:
   `gcloud sql instances promote-replica caseops-pg-replica-<region>`.
2. Update the Cloud Run service secret
   `caseops-database-url:latest` to point at the promoted instance.
3. Roll the Cloud Run service — the new task picks up the new URL
   via Secret Manager.
4. Post-incident: create a new replica in the dead region so the
   instance is no longer a single region.

## Restore drill (quarterly)

The drill proves the RTO is actually 1 hour. Run it on the last
Friday of each quarter. Checklist:

1. Pick a **recent** snapshot (< 24 h old) — old snapshots have
   operational risk of matching prod; fresh snapshots prove the
   backup pipeline is live.
2. Restore the snapshot to a **brand-new Cloud SQL instance** named
   `caseops-pg-drill-YYYYMMDD`.
3. Promote the corresponding cross-region replica to a second new
   instance; prove both paths work.
4. Point a throwaway Cloud Run revision at each restored DB. Exercise:
   - `caseops-ingest-corpus` picks up the existing corpus (no duplicates).
   - Bootstrap a new tenant — confirms migrations are current.
   - Create a matter → create a draft → generate → approve.
   - Pull an audit export; verify `audit.exported` row lands.
5. **Measure wall time** from step 2 to a green drill run. That number
   is the true RTO; update the table at the top of this doc if it
   drifts.
6. Delete the drill instances.

## Tenant-scoped export (compliance request)

When a tenant asks for "all my data" — e.g. GDPR Art. 15 access request:

1. Run the audit export:
   `GET /api/admin/audit/export?format=csv` (with `since=0001-01-01`).
2. Run a tenant-scoped DB dump (parametrised by `company_id`):
   ```sql
   \copy (SELECT * FROM matters WHERE company_id = :cid) TO 'matters.csv' CSV HEADER
   \copy (SELECT * FROM drafts WHERE matter_id IN (SELECT id FROM matters WHERE company_id = :cid)) TO 'drafts.csv' CSV HEADER
   -- repeat for draft_versions, matter_attachments, matter_activity, contracts, etc.
   ```
   The `scripts/tenant_export.py` CLI (not yet built — tracked as
   BG-047) will automate this. Until then, operator-driven.
3. Sync the matter attachments:
   `gsutil -m rsync -r gs://caseops-documents-prod/<company_id> /tmp/export/`
4. Bundle into a signed ZIP with a SHA-256 manifest and deliver via
   secure transfer. Record the export in the tenant's audit trail
   (`action=tenant.data_export`).

## Hard delete (tenant-purge)

Tracked as BG-047. **Not yet implemented.** When a tenant invokes
their deletion right:

1. Operator confirms the request via a human approval workflow.
2. `scripts/tenant_purge.py` (not yet built) walks every
   `ON DELETE CASCADE` foreign key rooted at `companies.id`. The
   `audit_events` table does NOT cascade — it retains tombstones
   as the compliance-of-record.
3. Cloud Storage objects under the tenant prefix are deleted with
   object-versioning tombstones retained for the lifecycle window.
4. A final `tenant.purged` audit row lands with the operator
   identity and the request_id.

## Changelog

- 2026-04-18: initial draft alongside Sprint 14 observability shipping.
