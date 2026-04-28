#!/usr/bin/env bash
# Provision the GCP-side hourly ingest-VM watchdog.
#
# What this creates (idempotent — re-run is safe):
#   1. Service account caseops-watchdog-runtime
#        - roles/compute.instanceAdmin.v1 (instance get / reset)
#        - roles/iap.tunnelResourceAccessor (gcloud-ssh via IAP)
#        - roles/iam.serviceAccountUser on the VM's runtime SA (so
#          gcloud-ssh can hand over identity)
#        - Secret Manager accessor on caseops-qa-storage-state
#   2. Service account caseops-scheduler-invoker
#        - roles/run.invoker on the watchdog Job
#   3. Secret caseops-qa-storage-state
#        - bytes from tests/e2e/.auth/qa-storage.json (must already be
#          freshly minted via npx playwright test --project=qa-auth-setup)
#   4. Container image
#        - asia-south1-docker.pkg.dev/PROJECT/caseops-images/caseops-ingest-watchdog:HEAD
#        - built from scripts/cron/Dockerfile
#   5. Cloud Run Job caseops-ingest-watchdog
#        - region asia-south1, max-retries 1, 5min timeout
#        - secret-mount /secrets/qa-storage.json
#   6. Cloud Scheduler caseops-ingest-watchdog-trigger
#        - 7 * * * * Asia/Kolkata
#        - target https://run.googleapis.com/v2/.../jobs/.../jobs:run
#        - OAuth as caseops-scheduler-invoker
#
# Usage:
#   scripts/cron/deploy-watchdog.sh              # build at git HEAD short SHA
#   scripts/cron/deploy-watchdog.sh <commit-sha> # specific commit
#
# Re-run cadence: every time the watchdog source changes.
# To rotate the QA cookie file: re-run scripts/qa/refresh-qa-cookies.sh
# (see that script — adds a new secret version), then redeploy is NOT
# needed because the Job pulls "latest" version on each invocation.
#
# Pre-reqs: gcloud authenticated as a project owner (or with iam.admin +
# run.admin + cloudscheduler.admin + secretmanager.admin), tests/e2e/
# .auth/qa-storage.json populated.

set -euo pipefail

PROJECT=perfect-period-305406
REGION=asia-south1
ZONE=asia-south1-c
REPO=caseops-images
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}"
WATCHDOG_SA=caseops-watchdog-runtime
SCHEDULER_SA=caseops-scheduler-invoker
VM_RUNTIME_SA=caseops-runtime          # the SA the ingest-VM runs as
JOB_NAME=caseops-ingest-watchdog
SCHEDULER_NAME=caseops-ingest-watchdog-trigger
SECRET_NAME=caseops-qa-storage-state
QA_STATE_FILE="${QA_STATE_FILE:-tests/e2e/.auth/qa-storage.json}"
TAG="${1:-$(git rev-parse --short=7 HEAD)}"
IMAGE="${REGISTRY}/${JOB_NAME}:${TAG}"

PROJECT_NUMBER=$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')
WATCHDOG_SA_EMAIL="${WATCHDOG_SA}@${PROJECT}.iam.gserviceaccount.com"
SCHEDULER_SA_EMAIL="${SCHEDULER_SA}@${PROJECT}.iam.gserviceaccount.com"
VM_RUNTIME_SA_EMAIL="${VM_RUNTIME_SA}@${PROJECT}.iam.gserviceaccount.com"

echo "=== deploy-watchdog.sh — tag ${TAG} ==="

# ---- 1/6 watchdog SA + roles ----
echo "--- 1/6 watchdog SA + roles ---"
# Use `list | grep` for idempotency — describe needs iam.serviceAccounts.get
# which can be denied even when create+iam-policy work.
if ! gcloud iam service-accounts list --project "${PROJECT}" --format='value(email)' 2>/dev/null | grep -qx "${WATCHDOG_SA_EMAIL}"; then
  gcloud iam service-accounts create "${WATCHDOG_SA}" \
    --display-name="CaseOps ingest-VM watchdog runtime" \
    --project "${PROJECT}" || {
      echo "  WARN create returned non-zero; continuing (likely race)"
    }
fi
# roles/compute.osLogin — required for the SA's SSH probe to be
# accepted by the VM's google_authorized_keys helper. Without it,
# every SSH probe fails with "OS Login user does not have login
# permission" and the watchdog falls into a false-positive reset loop.
for role in roles/compute.instanceAdmin.v1 roles/compute.osLogin roles/iap.tunnelResourceAccessor roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "${PROJECT}" \
    --member="serviceAccount:${WATCHDOG_SA_EMAIL}" \
    --role="${role}" --condition=None --quiet >/dev/null
done
# Allow the watchdog SA to act-as the VM's runtime SA (required for
# gcloud-ssh to attach the watchdog's identity to the SSH session).
gcloud iam service-accounts add-iam-policy-binding "${VM_RUNTIME_SA_EMAIL}" \
  --member="serviceAccount:${WATCHDOG_SA_EMAIL}" \
  --role=roles/iam.serviceAccountUser \
  --project "${PROJECT}" --quiet >/dev/null
echo "  watchdog SA ready: ${WATCHDOG_SA_EMAIL}"

# ---- 2/6 scheduler SA + role ----
echo "--- 2/6 scheduler SA + role ---"
if ! gcloud iam service-accounts list --project "${PROJECT}" --format='value(email)' 2>/dev/null | grep -qx "${SCHEDULER_SA_EMAIL}"; then
  gcloud iam service-accounts create "${SCHEDULER_SA}" \
    --display-name="CaseOps Cloud Scheduler invoker" \
    --project "${PROJECT}" || echo "  WARN create returned non-zero; continuing"
fi
echo "  scheduler SA ready: ${SCHEDULER_SA_EMAIL} (run.invoker bound after Job exists)"

# ---- 3/6 QA cookie secret ----
echo "--- 3/6 QA cookie secret ---"
if [[ ! -f "${QA_STATE_FILE}" ]]; then
  echo "ERROR ${QA_STATE_FILE} missing — generate via npx playwright test --project=qa-auth-setup first"
  exit 1
fi
if ! gcloud secrets list --project "${PROJECT}" --format='value(name)' 2>/dev/null | grep -qx "${SECRET_NAME}"; then
  gcloud secrets create "${SECRET_NAME}" \
    --replication-policy=automatic \
    --project "${PROJECT}" || echo "  WARN create returned non-zero; continuing"
fi
gcloud secrets versions add "${SECRET_NAME}" \
  --data-file="${QA_STATE_FILE}" \
  --project "${PROJECT}" >/dev/null
gcloud secrets add-iam-policy-binding "${SECRET_NAME}" \
  --member="serviceAccount:${WATCHDOG_SA_EMAIL}" \
  --role=roles/secretmanager.secretAccessor \
  --project "${PROJECT}" --quiet >/dev/null
echo "  secret ${SECRET_NAME} (latest) accessible to watchdog SA"

# ---- 4/6 build container image ----
echo "--- 4/6 build watchdog image ${IMAGE} ---"
gcloud builds submit scripts/cron \
  --tag "${IMAGE}" --project "${PROJECT}"

# ---- 5/6 Cloud Run Job ----
echo "--- 5/6 Cloud Run Job ${JOB_NAME} ---"
JOB_ARGS=(
  --image "${IMAGE}"
  --region "${REGION}"
  --project "${PROJECT}"
  --service-account "${WATCHDOG_SA_EMAIL}"
  --max-retries 1
  --task-timeout 10m
  --cpu 1 --memory 512Mi
)
if gcloud run jobs list --region "${REGION}" --project "${PROJECT}" --format='value(name)' 2>/dev/null | grep -qx "${JOB_NAME}"; then
  gcloud run jobs update "${JOB_NAME}" "${JOB_ARGS[@]}" --quiet
else
  gcloud run jobs create "${JOB_NAME}" "${JOB_ARGS[@]}" --quiet
fi
gcloud run jobs add-iam-policy-binding "${JOB_NAME}" \
  --region "${REGION}" --project "${PROJECT}" \
  --member="serviceAccount:${SCHEDULER_SA_EMAIL}" \
  --role=roles/run.invoker --quiet >/dev/null
echo "  Job ${JOB_NAME} on tag ${TAG}, scheduler can invoke"

# ---- 6/6 Cloud Scheduler trigger ----
echo "--- 6/6 Cloud Scheduler ${SCHEDULER_NAME} ---"
RUN_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${JOB_NAME}:run"
SCHED_ARGS=(
  --location "${REGION}"
  --schedule "7 * * * *"
  --time-zone "Asia/Kolkata"
  --uri "${RUN_URI}"
  --http-method POST
  --oauth-service-account-email "${SCHEDULER_SA_EMAIL}"
  --project "${PROJECT}"
)
# Try update first, fall back to create — robust against list-permission
# differences and gcloud format drift.
gcloud scheduler jobs update http "${SCHEDULER_NAME}" "${SCHED_ARGS[@]}" --quiet 2>/tmp/sched.err || {
  if grep -q "NOT_FOUND\|does not exist" /tmp/sched.err; then
    gcloud scheduler jobs create http "${SCHEDULER_NAME}" "${SCHED_ARGS[@]}" --quiet
  else
    cat /tmp/sched.err >&2
    exit 1
  fi
}
echo "  Scheduler ${SCHEDULER_NAME} firing at :07 every hour (Asia/Kolkata)"

echo "=== deploy-watchdog.sh — DONE ${TAG} ==="
echo
echo "Test-fire:"
echo "  gcloud run jobs execute ${JOB_NAME} --region ${REGION} --project ${PROJECT} --wait"
echo
echo "Tail logs:"
echo "  gcloud logging read 'resource.type=cloud_run_job AND resource.labels.job_name=${JOB_NAME}' --project ${PROJECT} --limit 30 --format='value(textPayload)' --freshness=1h"
