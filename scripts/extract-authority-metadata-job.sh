#!/usr/bin/env bash
# Layer-2 metadata backfill runner — Cloud Run Job invocation of
# `caseops_api.scripts.extract_authority_metadata`. Chews through the
# historical backlog of authority_documents missing structured metadata.
# Backlog size, provider model, and effective token price are runtime facts;
# inspect the target count and configured metadata-purpose model before every
# run instead of relying on a dated estimate in this launcher.
#
# Why a Cloud Run Job instead of a screen on the VM:
# - The VM-side per-bucket Layer-2 path is currently broken for new
#   ingests (0% Layer-2 success on docs ingested 2026-04-29 onwards),
#   and that VM-side fix is a separate task. This job at least gets the
#   backlog (and today's accreting fresh docs) processed in the
#   meantime.
# - The Cloud Run Job lifecycle is durable — survives ingest-VM reboots,
#   logs into Cloud Logging, sub-$3/day actual spend.
#
# Usage:
#   scripts/extract-authority-metadata-job.sh <image-tag> [--concurrency N] [--limit N]
#
# Examples:
#   # smoke test 50 docs
#   scripts/extract-authority-metadata-job.sh 10b0bb2 --limit 50 --concurrency 4
#
#   # full backfill, default concurrency
#   scripts/extract-authority-metadata-job.sh 10b0bb2
set -euo pipefail
if [[ $# -lt 1 ]]; then
  echo "usage: $0 <image-tag> [extra args ...]" >&2
  exit 1
fi
TAG="$1"; shift
EXTRA_ARGS=("$@")

PROJECT=perfect-period-305406
REGION=asia-south1
JOB=caseops-extract-authority-metadata
SA=caseops-runtime@${PROJECT}.iam.gserviceaccount.com
SQL_INSTANCE=${PROJECT}:${REGION}:caseops-db
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/caseops-images/caseops-api:${TAG}"

echo "=== ${JOB}: image=${IMAGE} extra=${EXTRA_ARGS[*]:-(none)} ==="

# Build the args string with the ^|^ delimiter so we can include
# whitespace + flags safely. The script entrypoint is python -m
# caseops_api.scripts.extract_authority_metadata.
ARGS_PARTS=("-m" "caseops_api.scripts.extract_authority_metadata")
# Default --concurrency 8 if the caller didn't pass one. The script's
# argparse default is 6; 8 is a better fit for the Cloud Run Job's
# 2-CPU shape against gpt-5.1's typical 1-2s response time.
HAS_CONCURRENCY=0
for a in "${EXTRA_ARGS[@]}"; do
  if [[ "$a" == "--concurrency" || "$a" == --concurrency=* ]]; then
    HAS_CONCURRENCY=1
  fi
done
if [[ ${HAS_CONCURRENCY} -eq 0 ]]; then
  ARGS_PARTS+=("--concurrency" "8")
fi
for a in "${EXTRA_ARGS[@]}"; do
  ARGS_PARTS+=("$a")
done
JOINED=$(IFS='|'; echo "${ARGS_PARTS[*]}")

ACTION=$(gcloud run jobs describe "${JOB}" --region "${REGION}" --project "${PROJECT}" >/dev/null 2>&1 && echo update || echo create)
echo "--- ${ACTION} job ---"

gcloud run jobs $ACTION "${JOB}" \
  --image="${IMAGE}" \
  --region="${REGION}" --project="${PROJECT}" \
  --command=python \
  --args="^|^${JOINED}" \
  --service-account="${SA}" \
  --set-env-vars="CASEOPS_ENV=cloud,CASEOPS_AUTO_MIGRATE=false,CASEOPS_LLM_PROVIDER=openai,CASEOPS_LLM_MODEL=gpt-5-mini,CASEOPS_LLM_MODEL_METADATA_EXTRACT=gpt-5-mini,CASEOPS_LAYER2_DAILY_USD_CAP=40,CASEOPS_LAYER2_DAILY_CAP_USD=40,CASEOPS_EMBEDDING_PROVIDER=voyage,CASEOPS_EMBEDDING_MODEL=voyage-4-large,CASEOPS_EMBEDDING_DIMENSIONS=1024" \
  --set-secrets="CASEOPS_DATABASE_URL=caseops-database-url:latest,CASEOPS_LLM_API_KEY=caseops-openai-api-key:latest,CASEOPS_OPENAI_API_KEY=caseops-openai-api-key:latest,CASEOPS_EMBEDDING_API_KEY=caseops-voyage-api-key:latest,CASEOPS_AUTH_SECRET=caseops-auth-secret:latest" \
  --set-cloudsql-instances="${SQL_INSTANCE}" \
  --memory=2Gi --cpu=2 \
  --task-timeout=43200s \
  --max-retries=0 --quiet

echo "--- starting execution (no-wait) ---"
gcloud run jobs execute "${JOB}" \
  --region="${REGION}" --project="${PROJECT}" \
  --quiet
echo "=== ${JOB}: started, will run until cap or no rows ==="
echo "  Logs: gcloud logging read 'resource.type=cloud_run_job AND resource.labels.job_name=${JOB}' --limit=20 --freshness=1h"
