# CaseOps — GCP Production Deployment Runbook

**Target**: Single-region prod stack on GCP, region `asia-south1` (Mumbai), in a fresh project (`caseops-prod` or your chosen name). For the "v1 demo" footprint — not the multi-region HA build.

**Audience**: You (sole operator). Every step is gcloud CLI; no Console clicking required.

---

## 0. Prerequisites

- `gcloud` CLI installed + authenticated: `gcloud auth login`
- Billing account ready to attach to the new project
- A working local DB with the corpus already ingested (the whole point of waiting — see `tmp/structured_budget.json` for completion)

---

## 1. Create the project + enable APIs

```bash
export GCP_PROJECT=caseops-prod
export GCP_REGION=asia-south1

# Create + link billing
gcloud projects create $GCP_PROJECT
gcloud billing projects link $GCP_PROJECT \
  --billing-account=$(gcloud billing accounts list --format='value(ACCOUNT_ID)' | head -1)

gcloud config set project $GCP_PROJECT
gcloud config set run/region $GCP_REGION

# APIs
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com \
  compute.googleapis.com
```

---

## 2. Cloud SQL Postgres 17 + pgvector

```bash
export DB_INSTANCE=caseops-db
export DB_NAME=caseops
export DB_USER=caseops
export DB_PASSWORD=$(openssl rand -base64 32)

# db-custom-2-7680: 2 vCPU, 7.68 GB RAM. ~$80/mo committed-use, ~$110/mo on-demand.
gcloud sql instances create $DB_INSTANCE \
  --database-version=POSTGRES_17 \
  --region=$GCP_REGION \
  --tier=db-custom-2-7680 \
  --storage-type=SSD \
  --storage-size=50GB \
  --storage-auto-increase \
  --backup-start-time=03:00 \
  --enable-point-in-time-recovery

# DB + user
gcloud sql databases create $DB_NAME --instance=$DB_INSTANCE
gcloud sql users create $DB_USER --instance=$DB_INSTANCE --password=$DB_PASSWORD

# Stash creds in Secret Manager
echo -n "$DB_PASSWORD" | gcloud secrets create caseops-db-password --data-file=-

# Enable pgvector. Cloud SQL Postgres 17 supports v0.6+ out of the box.
gcloud sql connect $DB_INSTANCE --user=$DB_USER --database=$DB_NAME <<SQL
CREATE EXTENSION IF NOT EXISTS vector;
SELECT extversion FROM pg_extension WHERE extname='vector';
SQL
# Expect: extversion >= 0.6.0
```

---

## 3. Cloud Storage bucket for documents

```bash
export DOC_BUCKET=caseops-prod-documents
gcloud storage buckets create gs://$DOC_BUCKET \
  --location=$GCP_REGION \
  --uniform-bucket-level-access
```

---

## 4. Secret Manager — every credential

```bash
# Anthropic
gcloud secrets create caseops-anthropic-api-key --replication-policy=automatic
echo -n "sk-ant-…YOUR-KEY…" | gcloud secrets versions add caseops-anthropic-api-key --data-file=-

# Voyage
gcloud secrets create caseops-voyage-api-key --replication-policy=automatic
echo -n "pa-…YOUR-VOYAGE-KEY…" | gcloud secrets versions add caseops-voyage-api-key --data-file=-

# Pine Labs (if you'll demo billing)
echo -n "merchant-id-here" | gcloud secrets create caseops-pinelabs-merchant-id --data-file=-
echo -n "api-key-here"     | gcloud secrets create caseops-pinelabs-api-key --data-file=-
echo -n "api-secret-here"  | gcloud secrets create caseops-pinelabs-api-secret --data-file=-
echo -n "webhook-secret"   | gcloud secrets create caseops-pinelabs-webhook-secret --data-file=-

# JWT signing key (32+ bytes — generate fresh; do NOT reuse local one)
echo -n "$(openssl rand -base64 48)" | gcloud secrets create caseops-auth-secret --data-file=-
```

---

## 5. Artifact Registry + image build

```bash
export REPO=caseops-images
gcloud artifacts repositories create $REPO \
  --repository-format=docker \
  --location=$GCP_REGION

gcloud auth configure-docker $GCP_REGION-docker.pkg.dev

# Build + push the API image (built from the apps/api context).
# The repo's .dockerignore keeps the layer slim.
gcloud builds submit apps/api \
  --tag $GCP_REGION-docker.pkg.dev/$GCP_PROJECT/$REPO/caseops-api:v1

# Same for the web image.
gcloud builds submit apps/web \
  --tag $GCP_REGION-docker.pkg.dev/$GCP_PROJECT/$REPO/caseops-web:v1
```

---

## 6. Cloud Run — API service

```bash
export RUNTIME_SA=caseops-runtime
gcloud iam service-accounts create $RUNTIME_SA

# Roles the runtime SA actually needs (least privilege)
for ROLE in \
  roles/cloudsql.client \
  roles/secretmanager.secretAccessor \
  roles/storage.objectAdmin; do
  gcloud projects add-iam-policy-binding $GCP_PROJECT \
    --member="serviceAccount:$RUNTIME_SA@$GCP_PROJECT.iam.gserviceaccount.com" \
    --role=$ROLE
done

# Bucket-scoped grant for the document bucket only
gcloud storage buckets add-iam-policy-binding gs://$DOC_BUCKET \
  --member="serviceAccount:$RUNTIME_SA@$GCP_PROJECT.iam.gserviceaccount.com" \
  --role=roles/storage.objectAdmin

# Deploy. --add-cloudsql-instances enables the Cloud SQL proxy
# socket, which the DATABASE_URL reaches via /cloudsql/<conn-name>.
export SQL_CONN=$GCP_PROJECT:$GCP_REGION:$DB_INSTANCE

gcloud run deploy caseops-api \
  --image=$GCP_REGION-docker.pkg.dev/$GCP_PROJECT/$REPO/caseops-api:v1 \
  --service-account=$RUNTIME_SA@$GCP_PROJECT.iam.gserviceaccount.com \
  --add-cloudsql-instances=$SQL_CONN \
  --allow-unauthenticated \
  --memory=2Gi \
  --cpu=2 \
  --max-instances=10 \
  --min-instances=0 \
  --timeout=300 \
  --set-env-vars=\
"CASEOPS_ENV=production,\
CASEOPS_DATABASE_URL=postgresql+psycopg://$DB_USER:$DB_PASSWORD@/cloudsql/$SQL_CONN/$DB_NAME,\
CASEOPS_DOCUMENT_STORAGE_BACKEND=gcs,\
CASEOPS_DOCUMENT_STORAGE_GCS_BUCKET=$DOC_BUCKET,\
CASEOPS_LLM_PROVIDER=anthropic,\
CASEOPS_LLM_MODEL=claude-haiku-4-5-20251001,\
CASEOPS_LLM_MODEL_DRAFTING=claude-opus-4-7,\
CASEOPS_LLM_MODEL_RECOMMENDATIONS=claude-sonnet-4-6,\
CASEOPS_LLM_MODEL_HEARING_PACK=claude-sonnet-4-6,\
CASEOPS_EMBEDDING_PROVIDER=voyage,\
CASEOPS_EMBEDDING_MODEL=voyage-4-large,\
CASEOPS_EMBEDDING_DIMENSIONS=1024,\
CASEOPS_PUBLIC_APP_URL=https://app.your-domain.example,\
CASEOPS_CORS_ORIGINS=[\"https://app.your-domain.example\"]" \
  --set-secrets=\
"CASEOPS_AUTH_SECRET=caseops-auth-secret:latest,\
CASEOPS_LLM_API_KEY=caseops-anthropic-api-key:latest,\
CASEOPS_EMBEDDING_API_KEY=caseops-voyage-api-key:latest"
```

**Note on `--allow-unauthenticated`**: this is ingress-public + app-level auth (Option B from the design call). CaseOps' own login layer protects every route past `/api/auth/*`.

---

## 7. Cloud Run — web service

```bash
gcloud run deploy caseops-web \
  --image=$GCP_REGION-docker.pkg.dev/$GCP_PROJECT/$REPO/caseops-web:v1 \
  --allow-unauthenticated \
  --memory=512Mi \
  --cpu=1 \
  --max-instances=5 \
  --set-env-vars="NEXT_PUBLIC_API_BASE_URL=https://caseops-api-…asia-south1.run.app"

# After both deploy, capture URLs
gcloud run services describe caseops-api --format='value(status.url)'
gcloud run services describe caseops-web --format='value(status.url)'
```

---

## 8. Migrate the populated local DB → Cloud SQL

This is the step that earns the local-first ingest. Don't re-run extraction in the cloud.

```bash
# From the local repo root, dump the populated DB. --no-owner avoids
# role-mismatch errors on restore. --no-acl keeps grants out (Cloud
# SQL manages them differently).
pg_dump \
  --host=127.0.0.1 --port=15432 \
  --username=caseops --dbname=caseops \
  --format=custom \
  --no-owner --no-acl \
  --file=tmp/caseops_local.dump

# Upload to a transfer bucket
gcloud storage cp tmp/caseops_local.dump gs://$DOC_BUCKET/_transfer/caseops_local.dump

# Cloud SQL has a managed import for SQL files but NOT for custom-
# format dumps. Use the Cloud SQL Auth proxy + pg_restore from your
# workstation:
gcloud sql instances describe $DB_INSTANCE --format='value(connectionName)'
# Run the proxy in another terminal:
#   cloud-sql-proxy $SQL_CONN
# Then:
PGPASSWORD=$DB_PASSWORD pg_restore \
  --host=127.0.0.1 --port=5432 \
  --username=$DB_USER --dbname=$DB_NAME \
  --no-owner --no-acl \
  --jobs=4 \
  tmp/caseops_local.dump

# Verify
gcloud sql connect $DB_INSTANCE --user=$DB_USER --database=$DB_NAME <<SQL
SELECT count(*) AS docs FROM authority_documents;
SELECT count(*) AS chunks FROM authority_document_chunks;
SELECT count(*) AS structured FROM authority_documents WHERE structured_version IS NOT NULL;
SELECT extversion FROM pg_extension WHERE extname='vector';
SQL
```

**Critical check**: pgvector indexes don't carry over cleanly through `pg_dump` of `vector` columns in some versions. If retrieval is slow post-restore, drop and rebuild the HNSW index:

```sql
DROP INDEX IF EXISTS idx_authority_chunks_embedding_vector;
CREATE INDEX idx_authority_chunks_embedding_vector
ON authority_document_chunks USING hnsw (embedding_vector vector_cosine_ops);
```

---

## 9. Migrate documents (storage_keys reference local files)

The DB references documents via `storage_key` strings. Local files in `apps/api/storage/documents/` need to land at `gs://$DOC_BUCKET/documents/<storage_key>`.

```bash
gcloud storage rsync -r \
  apps/api/storage/documents/ \
  gs://$DOC_BUCKET/documents/
```

---

## 10. Smoke test

```bash
export API=https://$(gcloud run services describe caseops-api --format='value(status.url)' | sed 's|https://||')

# Bootstrap your demo workspace
curl -sf "$API/api/health" | head
curl -sf -X POST "$API/api/bootstrap/company" \
  -H 'Content-Type: application/json' \
  -d '{"company_name":"Demo Firm","company_slug":"demo","company_type":"law_firm",
       "owner_full_name":"You","owner_email":"you@example.com","owner_password":"…"}'

# Authority search — confirms pgvector is working
TOKEN=…  # from bootstrap response
curl -sf -X POST "$API/api/authorities/search" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"query":"anticipatory bail triple test","limit":5}' | jq '.results | length'
```

If the search returns 5 results in <500ms, pgvector + HNSW are healthy on Cloud SQL.

---

## 11. Cloud Armor (optional belt-and-suspenders)

```bash
# Rate-limit /api/auth/* to mitigate credential-stuffing.
# 60 req / minute / IP; deny excess with 429.
gcloud compute security-policies create caseops-edge-policy
gcloud compute security-policies rules create 1000 \
  --security-policy=caseops-edge-policy \
  --expression="request.path.matches('/api/auth/.*')" \
  --action=rate-based-ban \
  --rate-limit-threshold-count=60 \
  --rate-limit-threshold-interval-sec=60 \
  --conform-action=allow \
  --exceed-action=deny-429 \
  --enforce-on-key=IP \
  --ban-duration-sec=300
# Attach to a Load Balancer in front of Cloud Run if you set one up;
# direct Cloud Run URLs don't go through Cloud Armor.
```

For the v1 demo, **skip this**. Add later when you put a custom domain + LB in front.

---

## Cost expectation (v1, low load)

| Item | Monthly |
|---|---|
| Cloud SQL `db-custom-2-7680` + 50GB SSD + backups | ~$110 |
| Cloud Run API (idle most hours, 2GB / 2vCPU) | ~$15 |
| Cloud Run web (idle most hours, 512MB) | ~$5 |
| Cloud Storage (1-2 GB documents) | <$1 |
| Anthropic + Voyage (demo usage) | ~$10-30 |
| **Total** | **~$140-160/mo** |

Drops by ~$30 if you commit Cloud SQL for 1 year.

---

## Things this runbook deliberately does NOT cover

- Custom domain + SSL — set up via `gcloud run domain-mappings` once you have a domain
- CDN / Cloud Armor LB — not needed for the demo
- Temporal (Sprint I) — durable workflow engine; current FastAPI BackgroundTasks works for demos
- OTel / structured logs (Sprint K) — not customer-visible
- OIDC / SAML SSO (Sprint M) — email/password works for the demo
- Multi-region failover — single Mumbai region is the v1 footprint
