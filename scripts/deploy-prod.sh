#!/usr/bin/env bash
# CaseOps prod deploy — single source of truth.
#
# Why this script: previous deploys used ad-hoc `gcloud builds submit` +
# `gcloud run deploy` calls that skipped the migrate-job. With
# CASEOPS_AUTO_MIGRATE=false on the API service (EG-002), schema
# migrations MUST run before the new API revision starts taking
# traffic, otherwise a commit that lands a new migration would deploy
# an API binary that errors on every query.
#
# This script enforces the order:
#   1. build api + web images in parallel
#   2. update + execute caseops-migrate-job (alembic upgrade head)
#   3. refresh scheduled/background jobs with an immutable API image
#   4. deploy caseops-api with the new image
#   5. deploy caseops-web with the new image
#   6. quick post-deploy smoke
#
# Usage:
#   scripts/deploy-prod.sh                 # tag with current git HEAD short SHA
#   scripts/deploy-prod.sh <commit-sha>    # assert this SHA is current HEAD
#
# Pre-reqs: gcloud authenticated, project set to perfect-period-305406,
# region set to asia-south1, and API/web build contexts clean for the
# HEAD you intend to ship. Cloud Build uploads current files, so dirty
# contexts are rejected before any gcloud call.

set -euo pipefail

PROJECT=perfect-period-305406
REGION=asia-south1
REPO=caseops-images
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}"
API_CPU=2
API_MEMORY=4Gi
API_SOURCE_DIR=apps/api
WEB_SOURCE_DIR=apps/web
API_GCLOUDIGNORE_FILE=.gcloudignore
API_GCLOUDIGNORE_PATH="${API_SOURCE_DIR}/${API_GCLOUDIGNORE_FILE}"
WEB_GCLOUDIGNORE_FILE=.gcloudignore
WEB_GCLOUDIGNORE_PATH="${WEB_SOURCE_DIR}/${WEB_GCLOUDIGNORE_FILE}"
# 2026-06-08 incident: a blocking request pinned the single Uvicorn
# event loop and Cloud Run kept routing unrelated API calls to that
# same instance until each hit the 300s service timeout. Keep
# concurrency at 1 so one stuck request cannot take the whole API
# surface down.
API_CONCURRENCY=1
API_TIMEOUT=300s
# P1-2 (2026-05-15 perf review): keep one API instance always warm.
# caseops-api previously had no minScale (scaled to 0), so the first
# login after any idle window paid a 3-8s Python + SQLAlchemy + Cloud
# SQL + clamav-sidecar cold start — the dominant cause of "login is
# slow". One always-on cpu=2/4Gi instance trades ~$35-50/mo for a
# consistently warm auth path. Override with API_MIN_INSTANCES=0 for a
# cost-only deploy.
API_MIN_INSTANCES="${API_MIN_INSTANCES:-1}"
# P1-2b (2026-05-15 perf review): keep one web instance warm too.
# /sign-in is `dynamic = "force-dynamic"` (SSR per request, no CDN
# cache), so with web minScale=0 the first hit after an idle window
# cold-starts the Next.js node server (~1-3s) before the login form is
# even usable — the leading cold-path login latency once the API is
# warm. caseops-web is stateless (no DB / sidecar); one cpu=1/512Mi
# warm instance is ~$10-18/mo. Override with WEB_MIN_INSTANCES=0.
WEB_MIN_INSTANCES="${WEB_MIN_INSTANCES:-1}"

if [[ "$#" -gt 1 ]]; then
  echo "Usage: scripts/deploy-prod.sh [commit-sha]"
  exit 2
fi

HEAD_SHA=$(git rev-parse --verify HEAD)
if [[ "$#" -eq 1 ]]; then
  REQUESTED_REF="$1"
  if [[ ! "${REQUESTED_REF}" =~ ^[0-9a-fA-F]{7,40}$ ]]; then
    echo "ERROR: commit-sha must be 7-40 hexadecimal characters."
    exit 2
  fi
  if ! REQUESTED_SHA=$(git rev-parse --verify "${REQUESTED_REF}^{commit}" 2>/dev/null); then
    echo "ERROR: requested commit ${REQUESTED_REF} cannot be resolved."
    exit 1
  fi
  if [[ "${REQUESTED_SHA}" != "${HEAD_SHA}" ]]; then
    echo "ERROR: requested commit ${REQUESTED_SHA} does not match current HEAD ${HEAD_SHA}."
    echo "Cloud Build uploads the current tree; refusing to mislabel it."
    exit 1
  fi
fi

DIRTY_BUILD_CONTEXT=$(git status --porcelain --untracked-files=all -- "${API_SOURCE_DIR}" "${WEB_SOURCE_DIR}")
if [[ -n "${DIRTY_BUILD_CONTEXT}" ]]; then
  echo "ERROR: API/web build context is dirty; refusing to label it as ${HEAD_SHA}."
  printf '%s\n' "${DIRTY_BUILD_CONTEXT}"
  exit 1
fi

TAG=$(git rev-parse --short=7 "${HEAD_SHA}")
API_IMAGE="${REGISTRY}/caseops-api:${TAG}"
WEB_IMAGE="${REGISTRY}/caseops-web:${TAG}"

echo "=== deploy-prod.sh — tag ${TAG} ==="
echo "API image: ${API_IMAGE}"
echo "Web image: ${WEB_IMAGE}"

# Step 1 — build both images in parallel.
echo "--- 1/6 build images (parallel) ---"
if [[ ! -f "${API_GCLOUDIGNORE_PATH}" ]]; then
  echo "Missing ${API_GCLOUDIGNORE_PATH}; refusing API build because local secrets/caches may be uploaded."
  exit 1
fi
if [[ ! -f "${WEB_GCLOUDIGNORE_PATH}" ]]; then
  echo "Missing ${WEB_GCLOUDIGNORE_PATH}; refusing web build because local node_modules/.next may be uploaded."
  exit 1
fi

gcloud builds submit "${API_SOURCE_DIR}" --ignore-file "${API_GCLOUDIGNORE_FILE}" --tag "${API_IMAGE}" --project "${PROJECT}" &
API_BUILD_PID=$!
# Explicitly pass the web .gcloudignore. The source directory has local
# node_modules/.next on Windows deploy hosts, and relying on Docker's
# .dockerignore is too late because gcloud creates the upload archive first.
gcloud builds submit "${WEB_SOURCE_DIR}" \
  --ignore-file "${WEB_GCLOUDIGNORE_FILE}" \
  --tag "${WEB_IMAGE}" \
  --project "${PROJECT}" &
WEB_BUILD_PID=$!
wait "${API_BUILD_PID}" || { echo "API build FAILED"; exit 1; }
wait "${WEB_BUILD_PID}" || { echo "Web build FAILED"; exit 1; }
echo "  api + web images built."

# Resolve the API tag while it is known to exist and pin every long-lived job
# to the digest. Artifact Registry cleanup may delete tags; digest references
# keep scheduled jobs runnable and prevent a repeat of the July 2026 report outage.
API_DIGEST=$(gcloud artifacts docker images describe "${API_IMAGE}" \
  --project "${PROJECT}" --format='value(image_summary.digest)')
if [[ ! "${API_DIGEST}" =~ ^sha256:[a-f0-9]{64}$ ]]; then
  echo "ERROR: could not resolve immutable digest for ${API_IMAGE}."
  exit 1
fi
API_IMMUTABLE_IMAGE="${REGISTRY}/caseops-api@${API_DIGEST}"
echo "  immutable api image=${API_IMMUTABLE_IMAGE}"

# Step 2 — refresh and execute the migrate-job. Idempotent when alembic
# is already at head; mandatory when there's a pending migration.
echo "--- 2/6 migrate-job (alembic upgrade head) ---"
gcloud run jobs update caseops-migrate-job \
  --image "${API_IMMUTABLE_IMAGE}" --region "${REGION}" --project "${PROJECT}" --quiet
gcloud run jobs execute caseops-migrate-job \
  --region "${REGION}" --project "${PROJECT}" --wait --quiet
echo "  migrate-job completed."

# Step 3 - refresh recurring jobs. They all execute commands packaged in the API
# image, so every production deploy must advance them with the service release.
echo "--- 3/6 refresh recurring jobs ---"
SCHEDULED_API_JOBS=(
  caseops-document-worker
  caseops-legal-update-sync
  caseops-case-tracking-poll
  caseops-activity-report
  caseops-reminders-job
)
for JOB_NAME in "${SCHEDULED_API_JOBS[@]}"; do
  gcloud run jobs update "${JOB_NAME}" \
    --image "${API_IMMUTABLE_IMAGE}" \
    --region "${REGION}" \
    --project "${PROJECT}" \
    --quiet
  LIVE_JOB_IMAGE=$(gcloud run jobs describe "${JOB_NAME}" \
    --region "${REGION}" \
    --project "${PROJECT}" \
    --format='value(spec.template.spec.template.spec.containers[0].image)')
  if [[ "${LIVE_JOB_IMAGE}" != "${API_IMMUTABLE_IMAGE}" ]]; then
    echo "ERROR: ${JOB_NAME} image=${LIVE_JOB_IMAGE}; expected ${API_IMMUTABLE_IMAGE}."
    exit 1
  fi
  echo "  ${JOB_NAME} pinned to ${API_DIGEST}."
done

# Step 3 — deploy API. CASEOPS_AUTO_MIGRATE=false stays in the service
# env from the manifest, so the new pods will NOT try to migrate again.
echo "--- 4/6 deploy caseops-api ---"
gcloud run deploy caseops-api \
  --region "${REGION}" \
  --project "${PROJECT}" \
  --quiet \
  --concurrency "${API_CONCURRENCY}" \
  --timeout "${API_TIMEOUT}" \
  --min-instances "${API_MIN_INSTANCES}" \
  --container api \
  --image "${API_IMAGE}" \
  --cpu "${API_CPU}" \
  --memory "${API_MEMORY}"
echo "  caseops-api at 100% traffic on ${TAG} (${API_CPU} CPU, ${API_MEMORY}, concurrency ${API_CONCURRENCY}, min-instances ${API_MIN_INSTANCES})."

# Step 4 — deploy web.
echo "--- 5/6 deploy caseops-web ---"
gcloud run deploy caseops-web \
  --image "${WEB_IMAGE}" --region "${REGION}" --project "${PROJECT}" --quiet \
  --min-instances "${WEB_MIN_INSTANCES}"
echo "  caseops-web at 100% traffic on ${TAG} (min-instances ${WEB_MIN_INSTANCES})."

# Step 5 — staleness sweep. Fails the script if the public domain
# doesn't return the new image tag, so you don't think you deployed
# when you actually didn't.
echo "--- 6/6 staleness sweep ---"
LIVE_API_TAG=$(gcloud run services describe caseops-api --region "${REGION}" --format='value(spec.template.spec.containers[0].image)' | grep -oE "[a-f0-9]+$")
LIVE_WEB_TAG=$(gcloud run services describe caseops-web --region "${REGION}" --format='value(spec.template.spec.containers[0].image)' | grep -oE "[a-f0-9]+$")
if [[ "${LIVE_API_TAG}" != "${TAG}" || "${LIVE_WEB_TAG}" != "${TAG}" ]]; then
  echo "STALENESS DETECTED: api=${LIVE_API_TAG} web=${LIVE_WEB_TAG} expected=${TAG}"
  exit 1
fi
if ! HEALTH=$(curl -fsS --connect-timeout 10 --max-time 30 https://api.caseops.ai/api/health); then
  echo "API health request failed; refusing to certify this deploy."
  exit 1
fi
if ! python -c 'import json, sys; payload = json.loads(sys.argv[1]); raise SystemExit(0 if isinstance(payload, dict) and payload.get("status") == "ok" else 1)' "${HEALTH}"; then
  echo "API health response is not healthy: ${HEALTH}"
  exit 1
fi
echo "  health=${HEALTH}"
echo "  api=${LIVE_API_TAG} web=${LIVE_WEB_TAG} (matches HEAD ${TAG})"

# EG-003 regression guard. The clamav sidecar was wired via
# scripts/eg003-apply-clamav.sh on 2026-04-25. `gcloud run deploy
# --image` preserves multi-container shape, but a future
# `gcloud run services replace` from a stale YAML or a manual
# `gcloud run services update --remove-env-vars` could silently drop
# it. If the sidecar is missing, fail the deploy script — the operator
# must re-run scripts/eg003-apply-clamav.sh before the deploy is
# considered safe.
SIDECAR_PRESENT=$(gcloud run services describe caseops-api --region "${REGION}" --format='value(spec.template.spec.containers[].name)' | tr ';' '\n' | grep -c '^clamav$' || true)
if [[ "${SIDECAR_PRESENT}" != "1" ]]; then
  echo "EG-003 REGRESSION: clamav sidecar missing from caseops-api. Run scripts/eg003-apply-clamav.sh and redeploy."
  exit 1
fi
echo "  EG-003 clamav sidecar present."

echo "=== deploy-prod.sh — DONE ${TAG} ==="
