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
MIGRATION_TASK_TIMEOUT=30m
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
# slow". This must be SERVICE-level minimum capacity (gcloud --min),
# not revision-level --min-instances. Historical tagged revisions inherited
# revision minScale=1 and kept restarting with pinned, obsolete DB secrets.
# One service-level warm instance follows traffic to the current revision.
# Override with API_MIN_INSTANCES=0 for a cost-only deploy.
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
  --image "${API_IMMUTABLE_IMAGE}" \
  --task-timeout "${MIGRATION_TASK_TIMEOUT}" \
  --region "${REGION}" --project "${PROJECT}" --quiet
gcloud run jobs execute caseops-migrate-job \
  --region "${REGION}" --project "${PROJECT}" --wait --quiet
echo "  migrate-job completed."

# Step 3 - converge the complete recurring-job inventory. This repairs image,
# target, cadence, time-zone, OAuth identity, and per-job invoker IAM drift from
# one checked-in source, verifies the canonical configuration, and only then
# pauses superseded scheduler names.
echo "--- 3/6 reconcile recurring-job inventory ---"
python scripts/scheduler_inventory.py reconcile \
  --project "${PROJECT}" \
  --region "${REGION}" \
  --image "${API_IMMUTABLE_IMAGE}"

# Step 3 — deploy API. CASEOPS_AUTO_MIGRATE=false stays in the service
# env from the manifest, so the new pods will NOT try to migrate again.
echo "--- 4/6 deploy caseops-api ---"
CLAMAV_IMAGE=$(gcloud run services describe caseops-api \
  --region "${REGION}" \
  --project "${PROJECT}" \
  --format='value(spec.template.spec.containers[1].image)')
if [[ -z "${CLAMAV_IMAGE}" ]]; then
  echo "EG-003 REGRESSION: cannot resolve the deployed ClamAV image; refusing a partial multi-container deploy."
  exit 1
fi
gcloud run deploy caseops-api \
  --region "${REGION}" \
  --project "${PROJECT}" \
  --quiet \
  --concurrency "${API_CONCURRENCY}" \
  --timeout "${API_TIMEOUT}" \
  --min "${API_MIN_INSTANCES}" \
  --min-instances default \
  --container api \
  --port 8080 \
  --image "${API_IMAGE}" \
  --update-env-vars "CASEOPS_RELEASE_SHA=${HEAD_SHA}" \
  --cpu "${API_CPU}" \
  --memory "${API_MEMORY}" \
  --container clamav \
  --image "${CLAMAV_IMAGE}" \
  --startup-probe "tcpSocket.port=3310,initialDelaySeconds=0,periodSeconds=2,timeoutSeconds=1,failureThreshold=120"
echo "  caseops-api at 100% traffic on ${TAG} (${API_CPU} CPU, ${API_MEMORY}, concurrency ${API_CONCURRENCY}, service-min ${API_MIN_INSTANCES})."

# Step 4 — deploy web.
echo "--- 5/6 deploy caseops-web ---"
gcloud run deploy caseops-web \
  --image "${WEB_IMAGE}" --region "${REGION}" --project "${PROJECT}" --quiet \
  --update-env-vars "CASEOPS_RELEASE_SHA=${HEAD_SHA}" \
  --min "${WEB_MIN_INSTANCES}" \
  --min-instances default
echo "  caseops-web at 100% traffic on ${TAG} (service-min ${WEB_MIN_INSTANCES})."

# Preview tags pin old revisions as externally routable targets. Combined with
# revision-level minScale left by historical deploys, those tags kept obsolete
# API containers alive after DB-secret rotation. They repeatedly failed startup
# and consumed Cloud Run/Cloud SQL capacity. A production release has one
# canonical target, so converge both services to latest-only routing.
gcloud run services update-traffic caseops-api \
  --region "${REGION}" --project "${PROJECT}" --to-latest --clear-tags --quiet
gcloud run services update-traffic caseops-web \
  --region "${REGION}" --project "${PROJECT}" --to-latest --clear-tags --quiet
echo "  stale API/web revision tags cleared; 100% traffic remains on latest."

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
CLAMAV_PROBE_DELAY=$(gcloud run services describe caseops-api --region "${REGION}" --format='value(spec.template.spec.containers[1].startupProbe.initialDelaySeconds)')
CLAMAV_PROBE_PERIOD=$(gcloud run services describe caseops-api --region "${REGION}" --format='value(spec.template.spec.containers[1].startupProbe.periodSeconds)')
# Cloud Run omits zero-valued protobuf fields when serializing a service, so
# an empty initialDelaySeconds is the canonical representation of zero.
CLAMAV_PROBE_DELAY=${CLAMAV_PROBE_DELAY:-0}
if [[ "${CLAMAV_PROBE_DELAY}" != "0" || "${CLAMAV_PROBE_PERIOD}" != "2" ]]; then
  echo "EG-003 REGRESSION: clamav startup probe delay=${CLAMAV_PROBE_DELAY} period=${CLAMAV_PROBE_PERIOD}; expected 0/2 seconds."
  exit 1
fi
echo "  EG-003 clamav sidecar present with immediate two-second startup probing."

echo "=== deploy-prod.sh — DONE ${TAG} ==="
