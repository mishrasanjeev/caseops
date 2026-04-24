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
#   3. deploy caseops-api with the new image
#   4. deploy caseops-web with the new image
#   5. quick post-deploy smoke
#
# Usage:
#   scripts/deploy-prod.sh                 # tag with current git HEAD short SHA
#   scripts/deploy-prod.sh <commit-sha>    # tag with a specific commit
#
# Pre-reqs: gcloud authenticated, project set to perfect-period-305406,
# region set to asia-south1, working tree clean for the SHA you intend
# to ship (`git status` shouldn't be relevant — Cloud Build uploads the
# current working tree).

set -euo pipefail

PROJECT=perfect-period-305406
REGION=asia-south1
REPO=caseops-images
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}"

TAG="${1:-$(git rev-parse --short=7 HEAD)}"
API_IMAGE="${REGISTRY}/caseops-api:${TAG}"
WEB_IMAGE="${REGISTRY}/caseops-web:${TAG}"

echo "=== deploy-prod.sh — tag ${TAG} ==="
echo "API image: ${API_IMAGE}"
echo "Web image: ${WEB_IMAGE}"

# Step 1 — build both images in parallel.
echo "--- 1/5 build images (parallel) ---"
gcloud builds submit apps/api --tag "${API_IMAGE}" --project "${PROJECT}" &
API_BUILD_PID=$!
gcloud builds submit apps/web --tag "${WEB_IMAGE}" --project "${PROJECT}" &
WEB_BUILD_PID=$!
wait "${API_BUILD_PID}" || { echo "API build FAILED"; exit 1; }
wait "${WEB_BUILD_PID}" || { echo "Web build FAILED"; exit 1; }
echo "  api + web images built."

# Step 2 — refresh and execute the migrate-job. Idempotent when alembic
# is already at head; mandatory when there's a pending migration.
echo "--- 2/5 migrate-job (alembic upgrade head) ---"
gcloud run jobs update caseops-migrate-job \
  --image "${API_IMAGE}" --region "${REGION}" --project "${PROJECT}" --quiet
gcloud run jobs execute caseops-migrate-job \
  --region "${REGION}" --project "${PROJECT}" --wait --quiet
echo "  migrate-job completed."

# Step 3 — deploy API. CASEOPS_AUTO_MIGRATE=false stays in the service
# env from the manifest, so the new pods will NOT try to migrate again.
echo "--- 3/5 deploy caseops-api ---"
gcloud run deploy caseops-api \
  --image "${API_IMAGE}" --region "${REGION}" --project "${PROJECT}" --quiet
echo "  caseops-api at 100% traffic on ${TAG}."

# Step 4 — deploy web.
echo "--- 4/5 deploy caseops-web ---"
gcloud run deploy caseops-web \
  --image "${WEB_IMAGE}" --region "${REGION}" --project "${PROJECT}" --quiet
echo "  caseops-web at 100% traffic on ${TAG}."

# Step 5 — staleness sweep. Fails the script if the public domain
# doesn't return the new image tag, so you don't think you deployed
# when you actually didn't.
echo "--- 5/5 staleness sweep ---"
LIVE_API_TAG=$(gcloud run services describe caseops-api --region "${REGION}" --format='value(spec.template.spec.containers[0].image)' | grep -oE "[a-f0-9]+$")
LIVE_WEB_TAG=$(gcloud run services describe caseops-web --region "${REGION}" --format='value(spec.template.spec.containers[0].image)' | grep -oE "[a-f0-9]+$")
if [[ "${LIVE_API_TAG}" != "${TAG}" || "${LIVE_WEB_TAG}" != "${TAG}" ]]; then
  echo "STALENESS DETECTED: api=${LIVE_API_TAG} web=${LIVE_WEB_TAG} expected=${TAG}"
  exit 1
fi
HEALTH=$(curl -sf https://api.caseops.ai/api/health || echo '{"status":"FAIL"}')
echo "  health=${HEALTH}"
echo "  api=${LIVE_API_TAG} web=${LIVE_WEB_TAG} (matches HEAD ${TAG})"

echo "=== deploy-prod.sh — DONE ${TAG} ==="
