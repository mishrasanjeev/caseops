#!/usr/bin/env bash
# Slice B (MOD-TS-001-C) — backfill matter_cause_list_entries.judges_json
# by resolving every unprocessed bench_name to Judge FK references.
set -euo pipefail
if [[ $# -ne 1 ]]; then echo "usage: $0 <image-tag>" >&2; exit 1; fi

PROJECT=perfect-period-305406
REGION=asia-south1
JOB=caseops-resolve-cause-list-benches
IMAGE="asia-south1-docker.pkg.dev/${PROJECT}/caseops-images/caseops-api:$1"
SQL_INSTANCE="${PROJECT}:${REGION}:caseops-db"

echo "=== resolve-cause-list-benches-job: image=${IMAGE} ==="
ACTION=$(gcloud run jobs describe "${JOB}" --region "${REGION}" --project "${PROJECT}" >/dev/null 2>&1 && echo update || echo create)
echo "--- ${ACTION} job ---"
gcloud run jobs $ACTION "${JOB}" \
  --image="${IMAGE}" \
  --region="${REGION}" --project="${PROJECT}" \
  --command=python \
  --args="^|^-m|caseops_api.scripts.resolve_cause_list_benches" \
  --service-account="caseops-runtime@${PROJECT}.iam.gserviceaccount.com" \
  --set-env-vars "CASEOPS_ENV=cloud,CASEOPS_AUTO_MIGRATE=false" \
  --set-secrets "CASEOPS_DATABASE_URL=caseops-database-url:latest,CASEOPS_AUTH_SECRET=caseops-auth-secret:latest" \
  --set-cloudsql-instances "${SQL_INSTANCE}" \
  --max-retries 1 --quiet

echo "--- executing job ---"
gcloud run jobs execute "${JOB}" --region "${REGION}" --project "${PROJECT}" --wait --quiet
echo "=== resolve-cause-list-benches-job: DONE ==="
