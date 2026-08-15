#!/usr/bin/env bash
# Configure and execute the non-recurring IPLF-027B A0 fingerprint control.
#
# The job is deliberately absent from scheduler_inventory.py and has no Cloud
# Scheduler trigger. `configure` never starts an execution; `execute` proves
# both the configured job and its exact execution before returning evidence.
set -euo pipefail

PROJECT="perfect-period-305406"
REGION="asia-south1"
JOB="caseops-ip-rule-governance-fingerprint-a0"
SERVICE_ACCOUNT="caseops-runtime@${PROJECT}.iam.gserviceaccount.com"
CLOUD_SQL_INSTANCE="${PROJECT}:${REGION}:caseops-db"
EXPECTED_IMAGE_PREFIX="${REGION}-docker.pkg.dev/${PROJECT}/caseops-images/caseops-api@sha256:"
MODULE="caseops_api.scripts.ip_rule_governance_fingerprint"

usage() {
  cat >&2 <<'EOF'
Usage:
  scripts/ip-rule-governance-fingerprint-job.sh configure <immutable-api-image> <40-char-release-sha>
  scripts/ip-rule-governance-fingerprint-job.sh execute <immutable-api-image> [expected-overall-sha256]

`configure` creates or updates the one-off job but never executes it.
`execute` emits one canonical JSON snapshot and returns nonzero on any drift.
EOF
}

require_immutable_image() {
  local image="$1"
  if [[ ! "${image}" =~ ^${EXPECTED_IMAGE_PREFIX}[a-f0-9]{64}$ ]]; then
    echo "ERROR: image must be the production API repository pinned by sha256 digest." >&2
    exit 2
  fi
}

require_sha256() {
  local value="$1"
  if [[ ! "${value}" =~ ^[a-f0-9]{64}$ ]]; then
    echo "ERROR: expected fingerprint must be a lowercase SHA-256 value." >&2
    exit 2
  fi
}

describe_job() {
  local output="$1"
  gcloud run jobs describe "${JOB}" \
    --project "${PROJECT}" \
    --region "${REGION}" \
    --format=json > "${output}"
}

validate_job() {
  local description="$1"
  local image="$2"
  local expected_release="${3:-}"
  python - "${description}" "${image}" "${expected_release}" \
    "${SERVICE_ACCOUNT}" "${CLOUD_SQL_INSTANCE}" "${MODULE}" <<'PY'
import json
import re
import sys

path, image, expected_release, service_account, cloud_sql, module = sys.argv[1:]
value = json.load(open(path, encoding="utf-8"))
metadata = value.get("metadata", {})
status = value.get("status", {})
job_spec = value.get("spec", {}).get("template", {}).get("spec", {})
task_spec = job_spec.get("template", {}).get("spec", {})
container = (task_spec.get("containers") or [{}])[0]
env = {item.get("name"): item for item in container.get("env", [])}
labels = metadata.get("labels", {})
annotations = value.get("spec", {}).get("template", {}).get("metadata", {}).get(
    "annotations", {}
)
conditions = status.get("conditions", [])
release = labels.get("caseops-release", "")
errors = []
if str(metadata.get("generation")) != str(status.get("observedGeneration")):
    errors.append("generation")
if not any(
    item.get("type") == "Ready" and str(item.get("status")).lower() == "true"
    for item in conditions
):
    errors.append("ready")
if container.get("image") != image:
    errors.append("image")
if container.get("command") != ["python"]:
    errors.append("command")
if container.get("args") != ["-m", module]:
    errors.append("args")
for name, expected in {
    "CASEOPS_ENV": "cloud",
    "CASEOPS_AUTO_MIGRATE": "false",
}.items():
    if env.get(name, {}).get("value") != expected:
        errors.append(name.lower())
for name, secret_name in {
    "CASEOPS_AUTH_SECRET": "caseops-auth-secret",
    "CASEOPS_DATABASE_URL": "caseops-database-url",
}.items():
    reference = env.get(name, {}).get("valueFrom", {}).get("secretKeyRef", {})
    if reference.get("name") != secret_name or reference.get("key") != "latest":
        errors.append(name.lower())
if task_spec.get("serviceAccountName") != service_account:
    errors.append("service_account")
if annotations.get("run.googleapis.com/cloudsql-instances") != cloud_sql:
    errors.append("cloud_sql")
if job_spec.get("taskCount") != 1 or job_spec.get("parallelism") not in (None, 1):
    errors.append("task_shape")
if task_spec.get("maxRetries") != 0:
    errors.append("retries")
if task_spec.get("timeoutSeconds") not in (600, "600", "600s"):
    errors.append("timeout")
if expected_release:
    if release != expected_release:
        errors.append("release_label")
elif re.fullmatch(r"[a-f0-9]{40}", str(release)) is None:
    errors.append("release_label")
if errors:
    print("ERROR: fingerprint job configuration drift: " + ",".join(errors), file=sys.stderr)
    raise SystemExit(1)
PY
}

validate_execution() {
  local description="$1"
  local image="$2"
  local expected_sha="${3:-}"
  local expected_execution="$4"
  python - "${description}" "${image}" "${expected_sha}" "${expected_execution}" \
    "${MODULE}" <<'PY'
import json
import sys

path, image, expected_sha, expected_execution, module = sys.argv[1:]
value = json.load(open(path, encoding="utf-8"))
metadata = value.get("metadata", {})
status = value.get("status", {})
spec = value.get("spec", {})
task_spec = spec.get("template", {}).get("spec", {})
container = (task_spec.get("containers") or [{}])[0]
conditions = status.get("conditions", [])
expected_args = ["-m", module]
if expected_sha:
    expected_args.append(f"--expect-sha256={expected_sha}")
errors = []
if str(metadata.get("name", "")).rsplit("/", 1)[-1] != expected_execution:
    errors.append("execution_identity")
if spec.get("taskCount") != 1:
    errors.append("task_count")
if container.get("image") != image:
    errors.append("image")
if container.get("command") != ["python"]:
    errors.append("command")
if container.get("args") != expected_args:
    errors.append("args")
if not any(
    item.get("type") == "Completed" and str(item.get("status")).lower() == "true"
    for item in conditions
):
    errors.append("completed")
if status.get("succeededCount") != 1:
    errors.append("succeeded_count")
if status.get("failedCount", 0) not in (0, None):
    errors.append("failed_count")
if status.get("cancelledCount", 0) not in (0, None):
    errors.append("cancelled_count")
if not status.get("startTime") or not status.get("completionTime"):
    errors.append("timestamps")
if errors:
    print("ERROR: fingerprint execution verification failed: " + ",".join(errors), file=sys.stderr)
    raise SystemExit(1)
PY
}

extract_snapshot_log() {
  local raw_log="$1"
  local canonical_output="$2"
  python - "${raw_log}" "${canonical_output}" <<'PY'
import json
import re
import sys

raw_path, output_path = sys.argv[1:]
candidates = []
raw = open(raw_path, encoding="utf-8").read()
try:
    parsed = json.loads(raw)
except json.JSONDecodeError:
    parsed = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError:
            continue
if isinstance(parsed, dict) and isinstance(parsed.get("entries"), list):
    parsed = parsed["entries"]
if not isinstance(parsed, list):
    parsed = [parsed]
for entry in parsed:
    if not isinstance(entry, dict):
        continue
    value = entry.get("jsonPayload")
    if not isinstance(value, dict):
        value = entry.get("textPayload", entry)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            continue
    if (
        isinstance(value, dict)
        and value.get("schema_version") == 1
        and re.fullmatch(r"[a-f0-9]{64}", str(value.get("overall_sha256", "")))
    ):
        candidates.append(value)
if len(candidates) != 1:
    raise SystemExit(1)
with open(output_path, "w", encoding="utf-8", newline="\n") as stream:
    json.dump(candidates[0], stream, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    stream.write("\n")
PY
}

read_execution_logs() {
  local log_filter="$1"
  local stream_name="$2"
  local output_path="$3"
  local log_name="projects/${PROJECT}/logs/run.googleapis.com%2F${stream_name}"
  local read_status=1

  if [[ "${LOGGING_REST_ONLY}" != "true" ]]; then
    set +e
    timeout --kill-after=5s 20s \
      gcloud logging read "${log_filter} AND logName=\"${log_name}\"" \
        --project "${PROJECT}" \
        --order desc \
        --limit 20 \
        --format=json > "${output_path}"
    read_status=$?
    set -e
    if [[ ${read_status} -eq 0 ]]; then
      # A successful CLI call can still return an empty indexed page. If its
      # payload is absent, the caller's next attempt must use entries:list.
      LOGGING_REST_ONLY=true
      return 0
    fi
    echo "WARNING: bounded gcloud log read failed; using the Logging API fallback." >&2
    LOGGING_REST_ONLY=true
  fi

  python - "${PROJECT}" "${log_filter} AND logName=\"${log_name}\"" "${LOG_REQUEST}" <<'PY'
import json
import sys

project, log_filter, output_path = sys.argv[1:]
with open(output_path, "w", encoding="utf-8", newline="\n") as stream:
    json.dump(
        {
            "filter": log_filter,
            "orderBy": "timestamp desc",
            "pageSize": 20,
            "resourceNames": [f"projects/{project}"],
        },
        stream,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    stream.write("\n")
PY
  local access_token=""
  set +e
  access_token=$(timeout --kill-after=5s 20s gcloud auth print-access-token --quiet)
  read_status=$?
  set -e
  if [[ ${read_status} -ne 0 || -z "${access_token}" ]]; then
    echo "WARNING: bounded Logging API credential lookup failed." >&2
    return 1
  fi
  umask 077
  printf 'Authorization: Bearer %s\n' "${access_token}" > "${LOG_AUTH_HEADER}"
  access_token=""
  set +e
  timeout --kill-after=5s 25s \
    curl --fail --silent --show-error \
      --request POST \
      --header "@${LOG_AUTH_HEADER}" \
      --header "Content-Type: application/json" \
      --data-binary "@${LOG_REQUEST}" \
      "https://logging.googleapis.com/v2/entries:list" > "${output_path}"
  read_status=$?
  set -e
  : > "${LOG_AUTH_HEADER}"
  return "${read_status}"
}

if [[ $# -lt 1 ]]; then
  usage
  exit 2
fi

ACTION="$1"
shift

case "${ACTION}" in
  configure)
    if [[ $# -ne 2 ]]; then
      usage
      exit 2
    fi
    IMAGE="$1"
    RELEASE_SHA="$2"
    require_immutable_image "${IMAGE}"
    if [[ ! "${RELEASE_SHA}" =~ ^[a-f0-9]{40}$ ]]; then
      echo "ERROR: release SHA must be the exact lowercase 40-character commit." >&2
      exit 2
    fi

    echo "Configuring non-recurring ${JOB} at immutable image ${IMAGE}." >&2
    gcloud run jobs deploy "${JOB}" \
      --project "${PROJECT}" \
      --region "${REGION}" \
      --image "${IMAGE}" \
      --command "python" \
      --args="^|^-m|${MODULE}" \
      --service-account "${SERVICE_ACCOUNT}" \
      --set-env-vars "CASEOPS_ENV=cloud,CASEOPS_AUTO_MIGRATE=false" \
      --set-secrets "CASEOPS_DATABASE_URL=caseops-database-url:latest,CASEOPS_AUTH_SECRET=caseops-auth-secret:latest" \
      --set-cloudsql-instances "${CLOUD_SQL_INSTANCE}" \
      --tasks 1 \
      --parallelism 1 \
      --max-retries 0 \
      --task-timeout 600s \
      --cpu 1 \
      --memory 512Mi \
      --labels "caseops-control=ip-rule-fingerprint,caseops-release=${RELEASE_SHA}" \
      --quiet >&2

    JOB_DESCRIPTION=$(mktemp)
    trap 'rm -f -- "${JOB_DESCRIPTION}"' EXIT
    describe_job "${JOB_DESCRIPTION}"
    validate_job "${JOB_DESCRIPTION}" "${IMAGE}" "${RELEASE_SHA}"
    echo "Configured and verified ${JOB}; no execution was started." >&2
    ;;

  execute)
    if [[ $# -lt 1 || $# -gt 2 ]]; then
      usage
      exit 2
    fi
    IMAGE="$1"
    EXPECTED_SHA="${2:-}"
    require_immutable_image "${IMAGE}"
    if [[ -n "${EXPECTED_SHA}" ]]; then
      require_sha256 "${EXPECTED_SHA}"
    fi

    JOB_DESCRIPTION=""
    EXECUTE_RESPONSE=""
    EXECUTION_DESCRIPTION=""
    RAW_STDOUT=""
    CANONICAL_STDOUT=""
    LOG_REQUEST=""
    LOG_AUTH_HEADER=""
    cleanup_execution_files() {
      [[ -z "${JOB_DESCRIPTION}" ]] || rm -f -- "${JOB_DESCRIPTION}"
      [[ -z "${EXECUTE_RESPONSE}" ]] || rm -f -- "${EXECUTE_RESPONSE}"
      [[ -z "${EXECUTION_DESCRIPTION}" ]] || rm -f -- "${EXECUTION_DESCRIPTION}"
      [[ -z "${RAW_STDOUT}" ]] || rm -f -- "${RAW_STDOUT}"
      [[ -z "${CANONICAL_STDOUT}" ]] || rm -f -- "${CANONICAL_STDOUT}"
      [[ -z "${LOG_REQUEST}" ]] || rm -f -- "${LOG_REQUEST}"
      [[ -z "${LOG_AUTH_HEADER}" ]] || rm -f -- "${LOG_AUTH_HEADER}"
    }
    trap cleanup_execution_files EXIT
    JOB_DESCRIPTION=$(mktemp)
    EXECUTE_RESPONSE=$(mktemp)
    EXECUTION_DESCRIPTION=$(mktemp)
    RAW_STDOUT=$(mktemp)
    CANONICAL_STDOUT=$(mktemp)
    LOG_REQUEST=$(mktemp)
    LOG_AUTH_HEADER=$(mktemp)
    describe_job "${JOB_DESCRIPTION}"
    validate_job "${JOB_DESCRIPTION}" "${IMAGE}"

    EXECUTION_ARGS="^|^-m|${MODULE}"
    if [[ -n "${EXPECTED_SHA}" ]]; then
      EXECUTION_ARGS="${EXECUTION_ARGS}|--expect-sha256=${EXPECTED_SHA}"
    fi
    echo "Executing ${JOB} at verified immutable image ${IMAGE}." >&2
    set +e
    gcloud run jobs execute "${JOB}" \
      --project "${PROJECT}" \
      --region "${REGION}" \
      --args="${EXECUTION_ARGS}" \
      --async \
      --quiet \
      --format=json > "${EXECUTE_RESPONSE}"
    EXECUTE_STATUS=$?
    set -e

    if ! EXECUTION=$(python -c 'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("metadata", {}).get("name", ""))' "${EXECUTE_RESPONSE}"); then
      echo "ERROR: Cloud Run execute response was not valid JSON." >&2
      exit 1
    fi
    if [[ -z "${EXECUTION}" ]]; then
      echo "ERROR: Cloud Run execute response omitted the exact execution identity." >&2
      exit 1
    fi
    EXECUTION_LABEL="${EXECUTION##*/}"
    EXECUTION_TERMINAL=false
    for _attempt in $(seq 1 132); do
      gcloud run jobs executions describe "${EXECUTION_LABEL}" \
        --project "${PROJECT}" \
        --region "${REGION}" \
        --format=json > "${EXECUTION_DESCRIPTION}"
      if python -c 'import json, sys; value=json.load(open(sys.argv[1], encoding="utf-8")); raise SystemExit(0 if any(item.get("type") == "Completed" and str(item.get("status", "")).lower() in {"true", "false"} for item in value.get("status", {}).get("conditions", [])) else 1)' "${EXECUTION_DESCRIPTION}"; then
        EXECUTION_TERMINAL=true
        break
      fi
      sleep 5
    done

    EXECUTION_VERIFIED=true
    if [[ "${EXECUTION_TERMINAL}" != "true" ]] || \
      ! validate_execution \
        "${EXECUTION_DESCRIPTION}" "${IMAGE}" "${EXPECTED_SHA}" "${EXECUTION_LABEL}"; then
      EXECUTION_VERIFIED=false
    fi

    LOG_FILTER="resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"${JOB}\" AND labels.\"run.googleapis.com/execution_name\"=\"${EXECUTION_LABEL}\""
    LOGGING_REST_ONLY=false
    SNAPSHOT_FOUND=false
    for _attempt in $(seq 1 30); do
      if read_execution_logs "${LOG_FILTER}" "stdout" "${RAW_STDOUT}" && \
        extract_snapshot_log "${RAW_STDOUT}" "${CANONICAL_STDOUT}"; then
        SNAPSHOT_FOUND=true
        break
      fi
      sleep 2
    done
    if [[ "${SNAPSHOT_FOUND}" == "true" ]]; then
      command cat "${CANONICAL_STDOUT}"
    else
      echo "ERROR: canonical fingerprint stdout was absent after bounded log polling." >&2
    fi

    SNAPSHOT_MATCHED=true
    if [[ -n "${EXPECTED_SHA}" && "${SNAPSHOT_FOUND}" == "true" ]] && \
      ! python -c 'import json, sys; value=json.load(open(sys.argv[1], encoding="utf-8")); raise SystemExit(0 if value.get("overall_sha256") == sys.argv[2] else 1)' "${CANONICAL_STDOUT}" "${EXPECTED_SHA}"; then
      echo "ERROR: fingerprint stdout did not match the expected overall SHA-256." >&2
      SNAPSHOT_MATCHED=false
    fi

    if [[ ${EXECUTE_STATUS} -ne 0 || "${EXECUTION_VERIFIED}" != "true" || "${SNAPSHOT_FOUND}" != "true" || "${SNAPSHOT_MATCHED}" != "true" ]]; then
      if read_execution_logs "${LOG_FILTER}" "stderr" "${RAW_STDOUT}"; then
        command cat "${RAW_STDOUT}" >&2
      fi
      exit 1
    fi
    ;;

  *)
    usage
    exit 2
    ;;
esac
