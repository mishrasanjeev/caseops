#!/usr/bin/env bash
# Generic HC judges Cloud Run Job runner. Mirrors
# scripts/seed-sci-judges-job.sh but parametrized by court_id so any
# HC with a curated seed_data/<court_id>_sitting_judges.json file can
# be seeded with one command.
#
# Usage:
#   scripts/seed-hc-judges-job.sh <image-tag> <court_id>
# e.g.
#   scripts/seed-hc-judges-job.sh b601e85 delhi-hc
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <image-tag> <court_id>" >&2
  exit 1
fi

PROJECT=perfect-period-305406
REGION=asia-south1
JOB=caseops-seed-hc-judges
IMAGE="asia-south1-docker.pkg.dev/${PROJECT}/caseops-images/caseops-api:$1"
COURT_ID="$2"
SQL_INSTANCE="${PROJECT}:${REGION}:caseops-db"

echo "=== seed-hc-judges-job: image=${IMAGE} court_id=${COURT_ID} ==="

# Always update (or create) so the env / SA / args carry the latest
# court_id. The job name stays the same; the args differ per call.
if gcloud run jobs describe "${JOB}" --region "${REGION}" --project "${PROJECT}" >/dev/null 2>&1; then
  ACTION=update
  echo "--- job exists, updating ---"
else
  ACTION=create
  echo "--- job missing, creating ---"
fi

gcloud run jobs $ACTION "${JOB}" \
  --image="${IMAGE}" \
  --region="${REGION}" --project="${PROJECT}" \
  --command=python \
  --args="^|^-m|caseops_api.scripts.seed_hc_judges|${COURT_ID}" \
  --service-account="caseops-runtime@${PROJECT}.iam.gserviceaccount.com" \
  --set-env-vars "CASEOPS_ENV=cloud,CASEOPS_AUTO_MIGRATE=false" \
  --set-secrets "CASEOPS_DATABASE_URL=caseops-database-url:latest,CASEOPS_AUTH_SECRET=caseops-auth-secret:latest" \
  --set-cloudsql-instances "${SQL_INSTANCE}" \
  --max-retries 1 \
  --quiet

echo "--- executing job (court_id=${COURT_ID}) ---"
gcloud run jobs execute "${JOB}" \
  --region "${REGION}" --project "${PROJECT}" --wait --quiet

echo "=== seed-hc-judges-job: DONE (${COURT_ID}) ==="
