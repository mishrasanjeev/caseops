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
WEB_SOURCE_DIR=.
API_GCLOUDIGNORE_FILE=.gcloudignore
API_GCLOUDIGNORE_PATH="${API_SOURCE_DIR}/${API_GCLOUDIGNORE_FILE}"
API_CLOUD_BUILD_CONFIG=apps/api/cloudbuild.yaml
WEB_GCLOUDIGNORE_FILE=.gcloudignore
WEB_GCLOUDIGNORE_PATH=.gcloudignore
WEB_CLOUD_BUILD_CONFIG=apps/web/cloudbuild.yaml
MIGRATION_TASK_TIMEOUT=30m
# 2026-06-08 incident: a blocking request pinned the single Uvicorn
# event loop and Cloud Run kept routing unrelated API calls to that
# same instance until each hit the 300s service timeout. Keep
# concurrency at 1 so one stuck request cannot take the whole API
# surface down.
API_CONCURRENCY=1
API_TIMEOUT=120s
# Keep a headroom ceiling above the historical ten single-request containers.
# A production browser page can issue several ordinary API reads in parallel;
# when all ten single-concurrency instances were busy, Cloud Run returned 429
# before application code ran. This does not increase the warm baseline.
# Cloud Run has both a mutable service-wide ceiling (--max) and an immutable
# per-revision ceiling (--max-instances). Set both: the service ceiling alone
# cannot raise a historical revision cap.
# Override only for a deliberate incident/cost response.
API_MAX_INSTANCES="${API_MAX_INSTANCES:-20}"
# Keep four API instances warm because each instance deliberately accepts one
# request and the ClamAV sidecar makes burst scale-out take tens of seconds.
# Production telemetry on 2026-08-28 measured a 49.758s queued request when a
# third supporting read triggered an autoscaled instance. Four warm slots cover
# the bounded foreign-associate workspace load and leave capacity for an
# unrelated interactive request.
# caseops-api previously had no minScale (scaled to 0), so the first
# login after any idle window paid a 3-8s Python + SQLAlchemy + Cloud
# SQL + clamav-sidecar cold start — the dominant cause of "login is
# slow". This must be SERVICE-level minimum capacity (gcloud --min),
# not revision-level --min-instances. Historical tagged revisions inherited
# revision minScale=1 and kept restarting with pinned, obsolete DB secrets.
# Four service-level warm instances leave headroom while another request is
# stalled. The Matter cockpit also sequences its supporting reads.
API_MIN_INSTANCES=4
# P1-2b (2026-05-15 perf review): keep one web instance warm too.
# /sign-in is `dynamic = "force-dynamic"` (SSR per request, no CDN
# cache), so with web minScale=0 the first hit after an idle window
# cold-starts the Next.js node server (~1-3s) before the login form is
# even usable — the leading cold-path login latency once the API is
# warm. caseops-web is stateless (no DB / sidecar); one cpu=1/512Mi
# warm instance is ~$10-18/mo. Override with WEB_MIN_INSTANCES=0.
WEB_MIN_INSTANCES="${WEB_MIN_INSTANCES:-1}"
# IPLF-027B A0 only: opt in to a fail-closed governance fingerprint at the
# final pre-route boundary, after migration and job reconciliation. Ordinary
# releases preserve the historical path exactly.
A0_CAPTURE_RULE_GOVERNANCE_BASELINE="${CASEOPS_A0_CAPTURE_RULE_GOVERNANCE_BASELINE:-false}"
A0_RULE_GOVERNANCE_BASELINE_OUTPUT="${CASEOPS_A0_RULE_GOVERNANCE_BASELINE_OUTPUT:-}"

if [[ "${A0_CAPTURE_RULE_GOVERNANCE_BASELINE}" != "true" && "${A0_CAPTURE_RULE_GOVERNANCE_BASELINE}" != "false" ]]; then
  echo "ERROR: CASEOPS_A0_CAPTURE_RULE_GOVERNANCE_BASELINE must be true or false."
  exit 2
fi
if [[ "${A0_CAPTURE_RULE_GOVERNANCE_BASELINE}" == "true" ]]; then
  if [[ -z "${A0_RULE_GOVERNANCE_BASELINE_OUTPUT}" ]]; then
    echo "ERROR: CASEOPS_A0_RULE_GOVERNANCE_BASELINE_OUTPUT is required for A0 capture."
    exit 2
  fi
  if [[ -e "${A0_RULE_GOVERNANCE_BASELINE_OUTPUT}" ]]; then
    echo "ERROR: refusing to overwrite existing A0 fingerprint evidence ${A0_RULE_GOVERNANCE_BASELINE_OUTPUT}."
    exit 2
  fi
  if [[ ! -d "$(dirname "${A0_RULE_GOVERNANCE_BASELINE_OUTPUT}")" ]]; then
    echo "ERROR: A0 fingerprint evidence directory does not exist."
    exit 2
  fi
fi

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

DIRTY_BUILD_CONTEXT=$(git status --porcelain --untracked-files=all -- \
  "${API_SOURCE_DIR}" "apps/web" package.json package-lock.json \
  .dockerignore .gcloudignore)
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

gcloud builds submit "${API_SOURCE_DIR}" \
  --ignore-file "${API_GCLOUDIGNORE_FILE}" \
  --config "${API_CLOUD_BUILD_CONFIG}" \
  --substitutions "_API_IMAGE=${API_IMAGE},_RELEASE_SHA=${HEAD_SHA}" \
  --project "${PROJECT}" &
API_BUILD_PID=$!
# Submit a narrowly filtered repository-root context so the web Dockerfile can
# install from the committed workspace lockfile. The Cloud Build config names
# the nested Dockerfile and immutable output image explicitly.
gcloud builds submit "${WEB_SOURCE_DIR}" \
  --ignore-file "${WEB_GCLOUDIGNORE_FILE}" \
  --config "${WEB_CLOUD_BUILD_CONFIG}" \
  --substitutions "_WEB_IMAGE=${WEB_IMAGE},_RELEASE_SHA=${HEAD_SHA}" \
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
# target, cadence, time-zone, desired scheduler state, inventory-owned task
# timeout, OAuth identity, and per-job invoker IAM drift from one checked-in
# source, verifies the canonical configuration, and only then pauses
# superseded scheduler names.
echo "--- 3/6 reconcile recurring-job inventory ---"
python scripts/scheduler_inventory.py reconcile \
  --project "${PROJECT}" \
  --region "${REGION}" \
  --image "${API_IMMUTABLE_IMAGE}"

# Index coverage is a release invariant. Execute the just-reconciled job from
# the immutable candidate image and abort before routing traffic on any schema,
# definition, validity, readiness, or foreign-key coverage failure.
echo "--- database index health pre-route gate ---"
gcloud run jobs execute caseops-db-index-health \
  --region "${REGION}" --project "${PROJECT}" --wait --quiet
echo "  database index health completed."

if [[ "${A0_CAPTURE_RULE_GOVERNANCE_BASELINE}" == "true" ]]; then
  echo "--- IPLF-027B A0 final pre-route quiescence baseline ---"
  # This manually invokable writer-era job is not part of recurring inventory.
  # Pin it without execution before establishing the no-writer baseline.
  A0_QA_JOB_BEFORE=""
  A0_QA_JOB_AFTER=""
  A0_BASELINE_TEMP=""
  cleanup_a0_control_files() {
    [[ -z "${A0_QA_JOB_BEFORE}" ]] || rm -f -- "${A0_QA_JOB_BEFORE}"
    [[ -z "${A0_QA_JOB_AFTER}" ]] || rm -f -- "${A0_QA_JOB_AFTER}"
    [[ -z "${A0_BASELINE_TEMP}" ]] || rm -f -- "${A0_BASELINE_TEMP}"
  }
  trap cleanup_a0_control_files EXIT
  A0_QA_JOB_BEFORE=$(mktemp)
  A0_QA_JOB_AFTER=$(mktemp)
  gcloud run jobs describe caseops-ip-qa-bootstrap \
    --region "${REGION}" \
    --project "${PROJECT}" \
    --format=json > "${A0_QA_JOB_BEFORE}"
  gcloud run jobs update caseops-ip-qa-bootstrap \
    --image "${API_IMMUTABLE_IMAGE}" \
    --region "${REGION}" \
    --project "${PROJECT}" \
    --quiet
  gcloud run jobs describe caseops-ip-qa-bootstrap \
    --region "${REGION}" \
    --project "${PROJECT}" \
    --format=json > "${A0_QA_JOB_AFTER}"
  if ! python - "${A0_QA_JOB_BEFORE}" "${A0_QA_JOB_AFTER}" \
    "${API_IMMUTABLE_IMAGE}" "caseops-runtime@${PROJECT}.iam.gserviceaccount.com" \
    "${PROJECT}:${REGION}:caseops-db" <<'PY'
import json
from copy import deepcopy
import sys

before_path, after_path, image, service_account, cloud_sql = sys.argv[1:]
before = json.load(open(before_path, encoding="utf-8"))
after = json.load(open(after_path, encoding="utf-8"))
metadata = after.get("metadata", {})
status = after.get("status", {})
before_template = before.get("spec", {}).get("template", {})
before_job_spec = before_template.get("spec", {})
before_task_spec = before_job_spec.get("template", {}).get("spec", {})
before_container = (before_task_spec.get("containers") or [{}])[0]
after_template = after.get("spec", {}).get("template", {})
job_spec = after_template.get("spec", {})
task_spec = job_spec.get("template", {}).get("spec", {})
container = (task_spec.get("containers") or [{}])[0]
before_annotations = before_template.get("metadata", {}).get("annotations", {})
annotations = after_template.get("metadata", {}).get("annotations", {})
errors = []
if str(metadata.get("generation")) != str(status.get("observedGeneration")):
    errors.append("generation")
if not any(
    item.get("type") == "Ready" and str(item.get("status")).lower() == "true"
    for item in status.get("conditions", [])
):
    errors.append("ready")
if container.get("image") != image:
    errors.append("image")
if container.get("command") != ["caseops-bootstrap-ip-production-qa"]:
    errors.append("command")
if before_container.get("args") != container.get("args"):
    errors.append("args_changed")
if container.get("args") not in (None, []):
    errors.append("args")
env = {item.get("name"): item.get("value") for item in container.get("env", [])}
if env.get("CASEOPS_AUTO_MIGRATE") != "false":
    errors.append("auto_migrate")
if task_spec.get("serviceAccountName") != service_account:
    errors.append("service_account")
if annotations.get("run.googleapis.com/cloudsql-instances") != cloud_sql:
    errors.append("cloud_sql")
if job_spec.get("taskCount") != 1:
    errors.append("task_count")
if job_spec.get("parallelism") not in (None, 1):
    errors.append("parallelism")
if task_spec.get("maxRetries") != 0:
    errors.append("max_retries")
if task_spec.get("timeoutSeconds") not in (600, "600", "600s"):
    errors.append("timeout")
for field in ("taskCount", "parallelism"):
    if before_job_spec.get(field) != job_spec.get(field):
        errors.append(f"{field}_changed")
for field in ("maxRetries", "timeoutSeconds"):
    if before_task_spec.get(field) != task_spec.get(field):
        errors.append(f"{field}_changed")
normalized_before_task_spec = deepcopy(before_task_spec)
normalized_containers = normalized_before_task_spec.get("containers", [])
if normalized_containers:
    normalized_containers[0]["image"] = image
if normalized_before_task_spec != task_spec:
    errors.append("all_container_configuration_changed")
for annotation in (
    "run.googleapis.com/cloudsql-instances",
    "run.googleapis.com/execution-environment",
):
    if before_annotations.get(annotation) != annotations.get(annotation):
        errors.append(f"{annotation}_changed")
before_status = before.get("status", {})
if before_status.get("executionCount") != status.get("executionCount"):
    errors.append("execution_count_changed")
if before_status.get("latestCreatedExecution", {}).get("name") != status.get(
    "latestCreatedExecution", {}
).get("name"):
    errors.append("latest_execution_changed")
if errors:
    print("QA bootstrap repin verification failed: " + ",".join(errors), file=sys.stderr)
    raise SystemExit(1)
PY
  then
    rm -f -- "${A0_QA_JOB_BEFORE}" "${A0_QA_JOB_AFTER}"
    echo "ERROR: caseops-ip-qa-bootstrap repin proof failed without execution."
    exit 1
  fi
  rm -f -- "${A0_QA_JOB_BEFORE}" "${A0_QA_JOB_AFTER}"
  A0_QA_JOB_BEFORE=""
  A0_QA_JOB_AFTER=""

  NONTERMINAL_EXECUTIONS=$(gcloud run jobs executions list \
    --region "${REGION}" \
    --project "${PROJECT}" \
    --format=json | python -c 'import json, sys; rows=json.load(sys.stdin); print("\n".join(str(row.get("metadata", {}).get("name", "<unknown>")) for row in rows if not any(condition.get("type") == "Completed" for condition in row.get("status", {}).get("conditions", []))))')
  if [[ -n "${NONTERMINAL_EXECUTIONS}" ]]; then
    echo "ERROR: nonterminal Cloud Run Job executions remain; refusing the A0 baseline:"
    printf '%s\n' "${NONTERMINAL_EXECUTIONS}"
    exit 1
  fi

  bash scripts/ip-rule-governance-fingerprint-job.sh \
    configure "${API_IMMUTABLE_IMAGE}" "${HEAD_SHA}"
  A0_BASELINE_TEMP=$(mktemp "${A0_RULE_GOVERNANCE_BASELINE_OUTPUT}.tmp.XXXXXX")
  if ! bash scripts/ip-rule-governance-fingerprint-job.sh \
    execute "${API_IMMUTABLE_IMAGE}" > "${A0_BASELINE_TEMP}"; then
    rm -f -- "${A0_BASELINE_TEMP}"
    echo "ERROR: A0 pre-route rule-governance fingerprint failed; aborting before API routing."
    exit 1
  fi
  if ! A0_RULE_GOVERNANCE_BASELINE_SHA=$(python \
    scripts/validate_ip_rule_governance_fingerprint.py \
    --require-postgresql \
    --print-sha \
    "${A0_BASELINE_TEMP}"); then
    rm -f -- "${A0_BASELINE_TEMP}"
    echo "ERROR: A0 fingerprint output was not the complete canonical snapshot; aborting before API routing."
    exit 1
  fi
  mv -- "${A0_BASELINE_TEMP}" "${A0_RULE_GOVERNANCE_BASELINE_OUTPUT}"
  A0_BASELINE_TEMP=""
  echo "A0_RULE_GOVERNANCE_BASELINE_SHA256=${A0_RULE_GOVERNANCE_BASELINE_SHA}"
  echo "  pre-route evidence=${A0_RULE_GOVERNANCE_BASELINE_OUTPUT}"
  trap - EXIT
fi

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
  --max "${API_MAX_INSTANCES}" \
  --max-instances "${API_MAX_INSTANCES}" \
  --timeout "${API_TIMEOUT}" \
  --min "${API_MIN_INSTANCES}" \
  --min-instances default \
  --container api \
  --port 8080 \
  --image "${API_IMAGE}" \
  --update-env-vars "CASEOPS_RELEASE_SHA=${HEAD_SHA},CASEOPS_IP_RULE_GOVERNANCE_ENABLED=false,CASEOPS_DB_STATEMENT_TIMEOUT_MS=60000,CASEOPS_DB_LOCK_TIMEOUT_MS=5000,CASEOPS_DB_IDLE_TRANSACTION_TIMEOUT_MS=60000" \
  --cpu "${API_CPU}" \
  --memory "${API_MEMORY}" \
  --container clamav \
  --image "${CLAMAV_IMAGE}" \
  --startup-probe "tcpSocket.port=3310,initialDelaySeconds=0,periodSeconds=2,timeoutSeconds=1,failureThreshold=120"
echo "  caseops-api at 100% traffic on ${TAG} (${API_CPU} CPU, ${API_MEMORY}, concurrency ${API_CONCURRENCY}, service-min ${API_MIN_INSTANCES}, service-max ${API_MAX_INSTANCES})."

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
LIVE_API_SERVICE_JSON=$(gcloud run services describe caseops-api \
  --region "${REGION}" \
  --project "${PROJECT}" \
  --format=json)
if ! LIVE_API_REVISION=$(python - "${HEAD_SHA}" "${API_MIN_INSTANCES}" "${LIVE_API_SERVICE_JSON}" <<'PY'
import json
import sys

expected_sha = sys.argv[1]
expected_min = sys.argv[2]
service = json.loads(sys.argv[3])
metadata = service.get("metadata") or {}
spec = service.get("spec") or {}
status = service.get("status") or {}
errors = []

annotations = metadata.get("annotations") or {}
if str(annotations.get("run.googleapis.com/minScale")) != expected_min:
    errors.append("service-level minimum capacity does not match API_MIN_INSTANCES")

if str(metadata.get("generation")) != str(status.get("observedGeneration")):
    errors.append("metadata.generation does not match status.observedGeneration")

conditions = {
    str(row.get("type")): str(row.get("status"))
    for row in status.get("conditions") or []
}
for condition in ("Ready", "ConfigurationsReady", "RoutesReady"):
    if conditions.get(condition) != "True":
        errors.append(f"{condition} is not True")

latest_created = str(status.get("latestCreatedRevisionName") or "")
latest_ready = str(status.get("latestReadyRevisionName") or "")
if not latest_ready or latest_created != latest_ready:
    errors.append("latest created and ready revisions do not match")

spec_traffic = spec.get("traffic") or []
if len(spec_traffic) != 1:
    errors.append("spec.traffic must contain exactly one entry")
else:
    row = spec_traffic[0]
    if row.get("latestRevision") is not True or int(row.get("percent") or 0) != 100:
        errors.append("spec.traffic is not 100% latest")
    if row.get("tag"):
        errors.append("spec.traffic still has a tag")

status_traffic = status.get("traffic") or []
if len(status_traffic) != 1:
    errors.append("status.traffic must contain exactly one entry")
else:
    row = status_traffic[0]
    if (
        str(row.get("revisionName") or "") != latest_ready
        or row.get("latestRevision") is not True
        or int(row.get("percent") or 0) != 100
    ):
        errors.append("status.traffic is not 100% on the exact latest-ready revision")
    if row.get("tag"):
        errors.append("status.traffic still has a tag")

containers = ((spec.get("template") or {}).get("spec") or {}).get("containers") or []
api = next((row for row in containers if row.get("name") == "api"), None)
if api is None:
    errors.append("api container is missing")
else:
    env = {str(row.get("name")): str(row.get("value")) for row in api.get("env") or []}
    if env.get("CASEOPS_RELEASE_SHA") != expected_sha:
        errors.append("CASEOPS_RELEASE_SHA does not match exact HEAD")
    if env.get("CASEOPS_IP_RULE_GOVERNANCE_ENABLED") != "false":
        errors.append("CASEOPS_IP_RULE_GOVERNANCE_ENABLED is not explicitly false")

if errors:
    print("; ".join(errors), file=sys.stderr)
    raise SystemExit(1)
print(latest_ready)
PY
); then
  echo "TRAFFIC/REVISION DRIFT: caseops-api did not converge to exact service capacity and one untagged exact-HEAD latest revision at 100%."
  exit 1
fi
LIVE_API_REVISION_IMAGE=$(gcloud run revisions describe "${LIVE_API_REVISION}" \
  --region "${REGION}" \
  --project "${PROJECT}" \
  --format='value(spec.containers[0].image)')
if [[ "${LIVE_API_REVISION_IMAGE}" != "${API_IMMUTABLE_IMAGE}" ]]; then
  echo "REVISION IMAGE DRIFT: revision=${LIVE_API_REVISION} image=${LIVE_API_REVISION_IMAGE} expected=${API_IMMUTABLE_IMAGE}"
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
echo "  api=${LIVE_API_TAG} revision=${LIVE_API_REVISION} web=${LIVE_WEB_TAG} (matches HEAD ${TAG}; rule governance explicitly false)"

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

# A push to main is not proof that a release started. Dispatch the exact-SHA
# browser gate only after both services pass every synchronous deploy gate.
echo "--- dispatch exact-release production verification ---"
gh workflow run prod-verify.yml \
  --repo mishrasanjeev/caseops \
  --ref main \
  -f "expected_release_sha=${HEAD_SHA}"
echo "  prod-verify.yml dispatched for exact release ${HEAD_SHA}."

echo "=== deploy-prod.sh — DONE ${TAG} ==="
