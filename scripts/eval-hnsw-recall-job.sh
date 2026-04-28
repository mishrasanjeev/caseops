#!/usr/bin/env bash
# Embedding-quality probe runner — runs caseops-eval-hnsw-recall
# against prod corpus and prints recall@k + MRR + mean_found_rank
# so we can rate the index 0-5 per the user's quality-rating-cadence
# memory.
#
# The probe is read-only (sample N docs, search the index, check
# self-recall). Voyage embedding key is required so the secret ref
# is wired below.
#
# Usage:
#   scripts/eval-hnsw-recall-job.sh <image-tag> <tenant_slug> [sample_size]
set -euo pipefail
if [[ $# -lt 2 ]]; then
  echo "usage: $0 <image-tag> <tenant_slug> [sample_size]" >&2
  exit 1
fi

PROJECT=perfect-period-305406
REGION=asia-south1
JOB=caseops-eval-hnsw-recall
IMAGE="asia-south1-docker.pkg.dev/${PROJECT}/caseops-images/caseops-api:$1"
TENANT="$2"
SAMPLE_SIZE="${3:-30}"
SQL_INSTANCE="${PROJECT}:${REGION}:caseops-db"

echo "=== ${JOB}: image=${IMAGE} tenant=${TENANT} sample=${SAMPLE_SIZE} ==="
ACTION=$(gcloud run jobs describe "${JOB}" --region "${REGION}" --project "${PROJECT}" >/dev/null 2>&1 && echo update || echo create)
echo "--- ${ACTION} job ---"
gcloud run jobs $ACTION "${JOB}" \
  --image="${IMAGE}" \
  --region="${REGION}" --project="${PROJECT}" \
  --command=python \
  --args="^|^-m|caseops_api.scripts.eval_hnsw_recall|--tenant|${TENANT}|--sample-size|${SAMPLE_SIZE}|--k|10|--seed|42" \
  --service-account="caseops-runtime@${PROJECT}.iam.gserviceaccount.com" \
  --set-env-vars "CASEOPS_ENV=cloud,CASEOPS_AUTO_MIGRATE=false,CASEOPS_EMBEDDING_PROVIDER=voyage,CASEOPS_EMBEDDING_MODEL=voyage-4-large,CASEOPS_EMBEDDING_DIMENSIONS=1024,CASEOPS_RERANK_ENABLED=true,CASEOPS_RERANK_BACKEND=fastembed" \
  --set-secrets "CASEOPS_DATABASE_URL=caseops-database-url:latest,CASEOPS_AUTH_SECRET=caseops-auth-secret:latest,CASEOPS_EMBEDDING_API_KEY=caseops-voyage-api-key:latest" \
  --set-cloudsql-instances "${SQL_INSTANCE}" \
  --memory 2Gi --cpu 2 \
  --max-retries 1 --quiet

echo "--- executing job ---"
gcloud run jobs execute "${JOB}" --region "${REGION}" --project "${PROJECT}" --wait --quiet
echo "=== ${JOB}: DONE ==="
