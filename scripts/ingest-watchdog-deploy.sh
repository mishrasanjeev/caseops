#!/usr/bin/env bash
# Build + deploy the durable ingest watchdog.
#
# Replaces the ephemeral CronCreate watchdog (which only lived for the
# duration of a Claude session) with a Cloud Scheduler → Cloud Run Job
# pair that runs every 15 minutes regardless of whether anyone is at
# the keyboard.
#
# Usage:  scripts/ingest-watchdog-deploy.sh
set -euo pipefail

PROJECT=perfect-period-305406
REGION=asia-south1
JOB=caseops-ingest-watchdog
SCHEDULER_JOB=caseops-ingest-watchdog-15m
SA=caseops-runtime@${PROJECT}.iam.gserviceaccount.com
VM_NAME=caseops-ingest-vm
VM_ZONE=asia-south1-c
SQL_INSTANCE=${PROJECT}:${REGION}:caseops-db
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/caseops-images/${JOB}:latest"
ENV_VARS="^|^PROJECT=${PROJECT}|ZONE=${VM_ZONE}|INSTANCE=${VM_NAME}|STALE_THRESHOLD_SEC=7200|RESET_COOLDOWN_SEC=1800"

CTX_DIR="$(cd "$(dirname "$0")"/ingest-watchdog && pwd)"

echo "=== build watchdog image ==="
gcloud builds submit "${CTX_DIR}" \
  --tag="${IMAGE}" \
  --project="${PROJECT}" --quiet

echo "=== grant compute.instanceAdmin.v1 on ${VM_NAME} (idempotent) ==="
gcloud compute instances add-iam-policy-binding "${VM_NAME}" \
  --zone="${VM_ZONE}" --project="${PROJECT}" \
  --member="serviceAccount:${SA}" \
  --role="roles/compute.instanceAdmin.v1" \
  --quiet >/dev/null

echo "=== deploy Cloud Run Job ==="
ACTION=$(gcloud run jobs describe "${JOB}" \
  --region="${REGION}" --project="${PROJECT}" >/dev/null 2>&1 \
  && echo update || echo create)

gcloud run jobs $ACTION "${JOB}" \
  --image="${IMAGE}" \
  --region="${REGION}" --project="${PROJECT}" \
  --service-account="${SA}" \
  --set-secrets="CASEOPS_DATABASE_URL=caseops-database-url:latest" \
  --set-cloudsql-instances="${SQL_INSTANCE}" \
  --set-env-vars="${ENV_VARS}" \
  --memory=512Mi --cpu=1 --task-timeout=300s --max-retries=0 --quiet

echo "=== grant scheduler permission to run ${JOB} (idempotent) ==="
gcloud run jobs add-iam-policy-binding "${JOB}" \
  --region="${REGION}" --project="${PROJECT}" \
  --member="serviceAccount:${SA}" \
  --role="roles/run.jobsExecutor" \
  --quiet >/dev/null

echo "=== schedule (every 15 min) ==="
RUN_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${JOB}:run"
ACTION_S=$(gcloud scheduler jobs describe "${SCHEDULER_JOB}" \
  --location="${REGION}" --project="${PROJECT}" >/dev/null 2>&1 \
  && echo update || echo create)

gcloud scheduler jobs $ACTION_S http "${SCHEDULER_JOB}" \
  --location="${REGION}" --project="${PROJECT}" \
  --schedule="*/15 * * * *" \
  --time-zone="UTC" \
  --http-method=POST \
  --uri="${RUN_URI}" \
  --oauth-service-account-email="${SA}" \
  --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform" \
  --quiet

echo "=== first probe run (proves end-to-end) ==="
gcloud run jobs execute "${JOB}" \
  --region="${REGION}" --project="${PROJECT}" --wait --quiet

echo "=== DONE ==="
echo "  Job:        gcloud run jobs describe ${JOB} --region=${REGION}"
echo "  Schedule:   gcloud scheduler jobs describe ${SCHEDULER_JOB} --location=${REGION}"
echo "  Logs:       gcloud logging read 'resource.type=cloud_run_job AND resource.labels.job_name=${JOB}' --limit=20"
