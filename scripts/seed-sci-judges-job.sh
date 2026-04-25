#!/usr/bin/env bash
# Create + execute the Cloud Run Job that loads SC sitting judges from
# apps/api/src/caseops_api/scripts/seed_data/sci_sitting_judges.json
# into the prod judges table.
#
# Idempotent at every layer:
#   - jobs create / update is conditional on whether the job exists
#   - the seed script itself is idempotent (uq_judges_court_name)
#
# Usage:
#   scripts/seed-sci-judges-job.sh <image-tag>
#
# image-tag: short SHA tag of caseops-api in Artifact Registry that
# includes apps/api/src/caseops_api/scripts/seed_sci_judges.py.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <image-tag>" >&2
  exit 1
fi

PROJECT=perfect-period-305406
REGION=asia-south1
JOB=caseops-seed-sci-judges
IMAGE="asia-south1-docker.pkg.dev/${PROJECT}/caseops-images/caseops-api:$1"
SQL_INSTANCE="${PROJECT}:${REGION}:caseops-db"

echo "=== seed-sci-judges-job: image=${IMAGE} ==="

if gcloud run jobs describe "${JOB}" --region "${REGION}" --project "${PROJECT}" >/dev/null 2>&1; then
  echo "--- job exists, updating image + env to ${IMAGE} ---"
  # Update sets the same env + secrets + SA + cloudsql every time so
  # drift from a prior misconfigured create can't linger.
  gcloud run jobs update "${JOB}" \
    --image="${IMAGE}" \
    --region="${REGION}" --project="${PROJECT}" \
    --command=python \
    --args="^|^-m|caseops_api.scripts.seed_sci_judges" \
    --service-account="caseops-runtime@${PROJECT}.iam.gserviceaccount.com" \
    --set-env-vars "CASEOPS_ENV=cloud,CASEOPS_AUTO_MIGRATE=false" \
    --set-secrets "CASEOPS_DATABASE_URL=caseops-database-url:latest,CASEOPS_AUTH_SECRET=caseops-auth-secret:latest" \
    --set-cloudsql-instances "${SQL_INSTANCE}" \
    --max-retries 1 \
    --quiet
else
  echo "--- job missing, creating ---"
  # gcloud --args takes ONE argument; repeat the flag (or use the
  # ^||^ delimiter trick) to pass multiple. Repeating is clearer.
  # gcloud's flag parser strips a leading '-' from --args values; use
  # the ^DELIM^ trick so the literal '-m' survives as the first token
  # of the args list.
  # caseops-runtime SA has Secret Manager Accessor on the relevant
  # secrets (caseops-database-url, caseops-auth-secret); the default
  # Compute SA does not. Reuse the same SA the migrate-job uses.
  gcloud run jobs create "${JOB}" \
    --image="${IMAGE}" \
    --region="${REGION}" --project="${PROJECT}" \
    --command=python \
    --args="^|^-m|caseops_api.scripts.seed_sci_judges" \
    --service-account="caseops-runtime@${PROJECT}.iam.gserviceaccount.com" \
    --set-env-vars "CASEOPS_ENV=cloud,CASEOPS_AUTO_MIGRATE=false" \
    --set-secrets "CASEOPS_DATABASE_URL=caseops-database-url:latest,CASEOPS_AUTH_SECRET=caseops-auth-secret:latest" \
    --set-cloudsql-instances "${SQL_INSTANCE}" \
    --max-retries 1 \
    --quiet
fi

echo "--- executing job ---"
gcloud run jobs execute "${JOB}" \
  --region "${REGION}" --project "${PROJECT}" --wait --quiet

echo "=== seed-sci-judges-job: DONE ==="
