#!/usr/bin/env bash
# IPLF-027B A2: config-only rule-governance enable and rollback on Cloud Run.
#
# A1 serves 100% of caseops-api traffic with CASEOPS_IP_RULE_GOVERNANCE_ENABLED
# false. `enable` creates one new revision of that exact image in which only
# the flag (true) and its rollout expiry change. `rollback` restores the A1
# configuration: flag false, expiry removed. Each mode refuses unless the live
# service serves exactly the expected release, reads the new revision back, and
# writes before/after evidence. deploy-prod.sh applies the checked-in
# deploy/ip-rule-governance-state.json on every release, so an enable must be
# followed by the PR that records it there. Procedure:
# docs/runbooks/ip-rule-governance-a2.md.
set -euo pipefail

FLAG_NAME="CASEOPS_IP_RULE_GOVERNANCE_ENABLED"
EXPIRY_NAME="CASEOPS_IP_RULE_GOVERNANCE_ROLLOUT_EXPIRES_AT"
# Governance may be enabled only on a release carrying the A1 ownership schema.
A1_REVISION="20261031_0002"
# gcloud returns once the new revision is ready and routed; the bounded poll
# only absorbs read-after-write lag.
CONVERGENCE_ATTEMPTS=12
CONVERGENCE_INTERVAL_SECONDS=5

usage() {
  cat >&2 <<'EOF'
Usage:
  scripts/ip-rule-governance-a2.sh enable --project <project> --region <region>
    [--service caseops-api] --expected-sha <40-hex commit>
    --expected-image <region>-docker.pkg.dev/<project>/<repository>/<image>@sha256:<digest>
    --rollout-expires-at <YYYY-MM-DDTHH:MM:SSZ> --evidence-output <new JSON file>
  scripts/ip-rule-governance-a2.sh rollback --project <project> --region <region>
    [--service caseops-api] --expected-sha <40-hex commit>
    --expected-image <region>-docker.pkg.dev/<project>/<repository>/<image>@sha256:<digest>
    --evidence-output <new JSON file>

Both modes change only the api container's environment, with one
`gcloud run services update`, and write evidence only after the new revision
is verified.
EOF
}

if [[ $# -lt 1 ]]; then
  usage
  exit 2
fi
MODE="$1"
shift
if [[ "${MODE}" != "enable" && "${MODE}" != "rollback" ]]; then
  usage
  exit 2
fi

PROJECT=""
REGION=""
SERVICE="caseops-api"
EXPECTED_SHA=""
EXPECTED_IMAGE=""
ROLLOUT_EXPIRES_AT=""
EVIDENCE_OUTPUT=""
while [[ $# -gt 0 ]]; do
  if [[ $# -lt 2 ]]; then
    echo "ERROR: $1 requires a value." >&2
    usage
    exit 2
  fi
  case "$1" in
    --project) PROJECT="$2" ;;
    --region) REGION="$2" ;;
    --service) SERVICE="$2" ;;
    --expected-sha) EXPECTED_SHA="$2" ;;
    --expected-image) EXPECTED_IMAGE="$2" ;;
    --rollout-expires-at) ROLLOUT_EXPIRES_AT="$2" ;;
    --evidence-output) EVIDENCE_OUTPUT="$2" ;;
    *)
      echo "ERROR: unknown argument $1." >&2
      usage
      exit 2
      ;;
  esac
  shift 2
done

if [[ ! "${PROJECT}" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]]; then
  echo "ERROR: --project must be a Google Cloud project id." >&2
  exit 2
fi
if [[ ! "${REGION}" =~ ^[a-z]+-[a-z]+[0-9]+$ ]]; then
  echo "ERROR: --region must be a Cloud Run region such as asia-south1." >&2
  exit 2
fi
if [[ ! "${SERVICE}" =~ ^[a-z]([a-z0-9-]{0,47}[a-z0-9])?$ ]]; then
  echo "ERROR: --service must be a Cloud Run service name." >&2
  exit 2
fi
if [[ ! "${EXPECTED_SHA}" =~ ^[a-f0-9]{40}$ ]]; then
  echo "ERROR: --expected-sha must be the exact lowercase 40-character commit." >&2
  exit 2
fi
IMAGE_REGISTRY="${REGION}-docker.pkg.dev/${PROJECT}/"
if [[ "${EXPECTED_IMAGE}" != "${IMAGE_REGISTRY}"* || \
  ! "${EXPECTED_IMAGE#"${IMAGE_REGISTRY}"}" =~ ^[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._/-]*@sha256:[a-f0-9]{64}$ ]]; then
  echo "ERROR: --expected-image must be an ${IMAGE_REGISTRY} image pinned by sha256 digest." >&2
  exit 2
fi
if [[ "${MODE}" == "enable" ]]; then
  # Same rule as deploy/ip-rule-governance-state.json in deploy-prod.sh.
  if ! python - "${ROLLOUT_EXPIRES_AT}" <<'PY'
import re
import sys
from datetime import datetime, timedelta, timezone

value = sys.argv[1]
if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value):
    print(
        "ERROR: --rollout-expires-at must be a UTC timestamp such as 2027-01-31T18:30:00Z.",
        file=sys.stderr,
    )
    raise SystemExit(1)
try:
    expiry = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
except ValueError:
    print(f"ERROR: --rollout-expires-at {value} is not a calendar time.", file=sys.stderr)
    raise SystemExit(1)
now = datetime.now(timezone.utc)
if expiry <= now:
    print(f"ERROR: --rollout-expires-at {value} has passed.", file=sys.stderr)
    raise SystemExit(1)
if expiry - now > timedelta(days=180):
    print(f"ERROR: --rollout-expires-at {value} is more than 180 days away.", file=sys.stderr)
    raise SystemExit(1)
PY
  then
    exit 2
  fi
elif [[ -n "${ROLLOUT_EXPIRES_AT}" ]]; then
  echo "ERROR: rollback removes the rollout expiry; do not pass --rollout-expires-at." >&2
  exit 2
fi
if [[ "${MODE}" == "enable" ]] && ! git grep --quiet \
  -E "^revision = \"${A1_REVISION}\"[[:space:]]*\$" "${EXPECTED_SHA}" -- apps/api/alembic/versions; then
  # The rule deploy-prod.sh applies to an enabled checked-in state.
  echo "ERROR: ${EXPECTED_SHA} is not a fetched commit carrying A1 migration ${A1_REVISION}; refusing to enable." >&2
  exit 2
fi
if [[ -z "${EVIDENCE_OUTPUT}" ]]; then
  echo "ERROR: --evidence-output is required." >&2
  exit 2
fi
if [[ -e "${EVIDENCE_OUTPUT}" || -L "${EVIDENCE_OUTPUT}" ]]; then
  echo "ERROR: refusing to overwrite existing evidence ${EVIDENCE_OUTPUT}." >&2
  exit 2
fi
if [[ ! -d "$(dirname "${EVIDENCE_OUTPUT}")" ]]; then
  echo "ERROR: evidence directory $(dirname "${EVIDENCE_OUTPUT}") does not exist." >&2
  exit 2
fi

if [[ "${MODE}" == "enable" ]]; then
  BEFORE_FLAG="false"
  BEFORE_EXPIRY=""
  AFTER_FLAG="true"
  AFTER_EXPIRY="${ROLLOUT_EXPIRES_AT}"
  UPDATE_FLAGS=(--update-env-vars "^|^${FLAG_NAME}=true|${EXPIRY_NAME}=${ROLLOUT_EXPIRES_AT}")
else
  BEFORE_FLAG="true"
  BEFORE_EXPIRY="*"
  AFTER_FLAG="false"
  AFTER_EXPIRY=""
  # gcloud applies --remove-env-vars first; the two keys differ.
  UPDATE_FLAGS=(--remove-env-vars "${EXPIRY_NAME}" --update-env-vars "${FLAG_NAME}=false")
fi

# inspect <service|revision|config-only|evidence> ... reads gcloud JSON.
# An expected expiry of "" means the variable must be absent; "*" means any.
inspect() {
  python - "$@" <<'PY'
import json
import sys

FLAG = "CASEOPS_IP_RULE_GOVERNANCE_ENABLED"
EXPIRY = "CASEOPS_IP_RULE_GOVERNANCE_ROLLOUT_EXPIRES_AT"
CLIENT_ANNOTATIONS = {"run.googleapis.com/client-name", "run.googleapis.com/client-version"}


def load(path):
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def api_container(containers):
    rows = [row for row in containers or [] if row.get("name") == "api"]
    return rows[0] if len(rows) == 1 else None


def env_value(container, name):
    """The literal value, None when absent; a secret reference never matches."""
    for row in container.get("env") or []:
        if row.get("name") == name:
            return "<secret reference>" if "valueFrom" in row else str(row.get("value", ""))
    return None


def check_env(container, where, sha, flag, expiry, errors):
    if env_value(container, "CASEOPS_RELEASE_SHA") != sha:
        errors.append(f"{where} CASEOPS_RELEASE_SHA is not the expected release")
    if env_value(container, FLAG) != flag:
        errors.append(f"{where} {FLAG} is not {flag}")
    actual_expiry = env_value(container, EXPIRY)
    if expiry == "":
        if actual_expiry is not None:
            errors.append(f"{where} {EXPIRY} is set")
    elif expiry != "*" and actual_expiry != expiry:
        errors.append(f"{where} {EXPIRY} is not {expiry}")


def untagged_full(row, revision=None):
    return (
        row.get("latestRevision") is True
        and str(row.get("percent")) == "100"
        and not row.get("tag")
        and (revision is None or str(row.get("revisionName") or "") == revision)
    )


def fail(errors):
    if errors:
        print("ERROR: " + "; ".join(errors), file=sys.stderr)
        raise SystemExit(1)


def service(path, sha, flag, expiry):
    payload = load(path)
    metadata = payload.get("metadata") or {}
    spec = payload.get("spec") or {}
    status = payload.get("status") or {}
    errors = []
    if str(metadata.get("generation")) != str(status.get("observedGeneration")):
        errors.append("service generation is not yet observed")
    conditions = {
        str(row.get("type")): str(row.get("status")) for row in status.get("conditions") or []
    }
    for condition in ("Ready", "ConfigurationsReady", "RoutesReady"):
        if conditions.get(condition) != "True":
            errors.append(f"service {condition} is not True")
    latest_ready = str(status.get("latestReadyRevisionName") or "")
    if not latest_ready or str(status.get("latestCreatedRevisionName") or "") != latest_ready:
        errors.append("latest created and latest ready revisions differ")
    spec_traffic = spec.get("traffic") or []
    if len(spec_traffic) != 1 or not untagged_full(spec_traffic[0]):
        errors.append("declared traffic is not one untagged 100% latest-revision entry")
    status_traffic = status.get("traffic") or []
    if len(status_traffic) != 1 or not untagged_full(status_traffic[0], latest_ready):
        errors.append("served traffic is not one untagged 100% entry on the latest ready revision")
    api = api_container(((spec.get("template") or {}).get("spec") or {}).get("containers"))
    if api is None:
        errors.append("service template has no single api container")
    else:
        check_env(api, "service template", sha, flag, expiry, errors)
    fail(errors)
    print(latest_ready, api.get("image", ""))


def revision(path, name, image, sha, flag, expiry):
    payload = load(path)
    errors = []
    if str((payload.get("metadata") or {}).get("name") or "") != name:
        errors.append(f"revision description is not {name}")
    conditions = {
        str(row.get("type")): str(row.get("status"))
        for row in (payload.get("status") or {}).get("conditions") or []
    }
    if conditions.get("Ready") != "True":
        errors.append(f"revision {name} is not Ready")
    api = api_container((payload.get("spec") or {}).get("containers"))
    if api is None:
        errors.append(f"revision {name} has no single api container")
    else:
        if api.get("image") != image:
            errors.append(f"revision {name} api image is not {image}")
        check_env(api, f"revision {name}", sha, flag, expiry, errors)
    fail(errors)
    print(str((payload.get("status") or {}).get("imageDigest") or ""))


def material(payload):
    """The revision template without the governance variables and api image.

    The caller checks the api image separately: gcloud may pin a by-tag
    template to the serving revision's digest during an update.
    """
    template = json.loads(json.dumps((payload.get("spec") or {}).get("template") or {}))
    for container in (template.get("spec") or {}).get("containers") or []:
        if container.get("name") == "api":
            container.pop("image", None)
            container["env"] = sorted(
                (
                    row
                    for row in container.get("env") or []
                    if row.get("name") not in (FLAG, EXPIRY)
                ),
                key=lambda row: str(row.get("name")),
            )
    annotations = (template.get("metadata") or {}).get("annotations") or {}
    return template.get("spec") or {}, {
        key: value for key, value in annotations.items() if key not in CLIENT_ANNOTATIONS
    }


def config_only(before_path, after_path):
    before_spec, before_annotations = material(load(before_path))
    after_spec, after_annotations = material(load(after_path))
    errors = []
    changed = sorted(
        key
        for key in before_spec.keys() | after_spec.keys()
        if before_spec.get(key) != after_spec.get(key)
    )
    if changed:
        errors.append("revision template changed beyond the governance variables: " + ", ".join(changed))
    annotations = sorted(
        key
        for key in before_annotations.keys() | after_annotations.keys()
        if before_annotations.get(key) != after_annotations.get(key)
    )
    if annotations:
        errors.append("revision template annotations changed: " + ", ".join(annotations))
    fail(errors)


def governance_env(path):
    api = api_container((load(path).get("spec") or {}).get("containers")) or {}
    return {FLAG: env_value(api, FLAG), EXPIRY: env_value(api, EXPIRY)}


def evidence(output, mode, project, region, service_name, sha, image, before, after,
             before_revision, after_revision, started_at, updated_at, completed_at, *update):
    payload = {
        "schema_version": 1,
        "control": "iplf-027b-a2-rule-governance",
        "mode": mode,
        "project": project,
        "region": region,
        "service": service_name,
        "release_sha": sha,
        "image": image,
        "before": {"revision": before_revision, "environment": governance_env(before)},
        "after": {"revision": after_revision, "environment": governance_env(after)},
        "gcloud_update_arguments": list(update),
        "started_at": started_at,
        "updated_at": updated_at,
        "completed_at": completed_at,
    }
    with open(output, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")


command, arguments = sys.argv[1], sys.argv[2:]
{"service": service, "revision": revision, "config-only": config_only, "evidence": evidence}[
    command
](*arguments)
PY
}

BEFORE_SERVICE=""
BEFORE_REVISION_JSON=""
AFTER_SERVICE=""
AFTER_REVISION_JSON=""
CHECK_ERRORS=""
EVIDENCE_TEMP=""
cleanup() {
  [[ -z "${BEFORE_SERVICE}" ]] || rm -f -- "${BEFORE_SERVICE}"
  [[ -z "${BEFORE_REVISION_JSON}" ]] || rm -f -- "${BEFORE_REVISION_JSON}"
  [[ -z "${AFTER_SERVICE}" ]] || rm -f -- "${AFTER_SERVICE}"
  [[ -z "${AFTER_REVISION_JSON}" ]] || rm -f -- "${AFTER_REVISION_JSON}"
  [[ -z "${CHECK_ERRORS}" ]] || rm -f -- "${CHECK_ERRORS}"
  [[ -z "${EVIDENCE_TEMP}" ]] || rm -f -- "${EVIDENCE_TEMP}"
}
trap cleanup EXIT
BEFORE_SERVICE=$(mktemp)
BEFORE_REVISION_JSON=$(mktemp)
AFTER_SERVICE=$(mktemp)
AFTER_REVISION_JSON=$(mktemp)
CHECK_ERRORS=$(mktemp)

echo "--- ${MODE}: verify ${SERVICE} serves exactly ${EXPECTED_SHA} ---" >&2
gcloud run services describe "${SERVICE}" \
  --region "${REGION}" \
  --project "${PROJECT}" \
  --format=json > "${BEFORE_SERVICE}"
if ! BEFORE_IDENTITY=$(inspect service "${BEFORE_SERVICE}" \
  "${EXPECTED_SHA}" "${BEFORE_FLAG}" "${BEFORE_EXPIRY}" | tr -d '\r'); then
  echo "ERROR: ${SERVICE} is not the expected ${MODE} starting point; nothing was changed." >&2
  exit 1
fi
read -r BEFORE_REVISION BEFORE_TEMPLATE_IMAGE <<< "${BEFORE_IDENTITY}"
gcloud run revisions describe "${BEFORE_REVISION}" \
  --region "${REGION}" \
  --project "${PROJECT}" \
  --format=json > "${BEFORE_REVISION_JSON}"
if ! BEFORE_REVISION_DIGEST=$(inspect revision "${BEFORE_REVISION_JSON}" "${BEFORE_REVISION}" \
  "${EXPECTED_IMAGE}" "${EXPECTED_SHA}" "${BEFORE_FLAG}" "${BEFORE_EXPIRY}" | tr -d '\r'); then
  echo "ERROR: serving revision ${BEFORE_REVISION} is not the expected release; nothing was changed." >&2
  exit 1
fi
# An update without --image keeps a by-digest template as it is. gcloud pins a
# by-tag template to the serving revision's reported digest; without one,
# Cloud Run resolves the tag again, so the tag must still name the digest.
if [[ "${BEFORE_TEMPLATE_IMAGE}" != "${EXPECTED_IMAGE}" && \
  "${BEFORE_REVISION_DIGEST}" != "${EXPECTED_IMAGE}" ]]; then
  TEMPLATE_TAG="${BEFORE_TEMPLATE_IMAGE#"${EXPECTED_IMAGE%@*}:"}"
  if [[ "${TEMPLATE_TAG}" == "${BEFORE_TEMPLATE_IMAGE}" || \
    ! "${TEMPLATE_TAG}" =~ ^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$ ]]; then
    echo "ERROR: service template image ${BEFORE_TEMPLATE_IMAGE} is not ${EXPECTED_IMAGE} or a tag of it; nothing was changed." >&2
    exit 1
  fi
  if ! TEMPLATE_DIGEST=$(gcloud artifacts docker images describe "${BEFORE_TEMPLATE_IMAGE}" \
    --project "${PROJECT}" \
    --format='value(image_summary.digest)' | tr -d '\r'); then
    echo "ERROR: could not resolve ${BEFORE_TEMPLATE_IMAGE}; nothing was changed." >&2
    exit 1
  fi
  if [[ "${TEMPLATE_DIGEST}" != "${EXPECTED_IMAGE##*@}" ]]; then
    echo "ERROR: ${BEFORE_TEMPLATE_IMAGE} now resolves to ${TEMPLATE_DIGEST:-nothing}, not ${EXPECTED_IMAGE##*@}; a new revision would change the image. Nothing was changed." >&2
    exit 1
  fi
fi
echo "  ${BEFORE_REVISION} serves ${EXPECTED_IMAGE} with ${FLAG_NAME}=${BEFORE_FLAG}." >&2

STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "--- ${MODE}: config-only update of ${SERVICE} (api container environment) ---" >&2
if ! gcloud run services update "${SERVICE}" \
  --region "${REGION}" \
  --project "${PROJECT}" \
  --quiet \
  --container api \
  "${UPDATE_FLAGS[@]}"; then
  echo "ERROR: gcloud run services update failed; read the service before acting again." >&2
  exit 1
fi
UPDATED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)

CONVERGED=false
for _attempt in $(seq 1 "${CONVERGENCE_ATTEMPTS}"); do
  if gcloud run services describe "${SERVICE}" \
    --region "${REGION}" \
    --project "${PROJECT}" \
    --format=json > "${AFTER_SERVICE}" && \
    AFTER_IDENTITY=$(inspect service "${AFTER_SERVICE}" \
      "${EXPECTED_SHA}" "${AFTER_FLAG}" "${AFTER_EXPIRY}" 2> "${CHECK_ERRORS}" | tr -d '\r'); then
    read -r AFTER_REVISION AFTER_TEMPLATE_IMAGE <<< "${AFTER_IDENTITY}"
    if [[ "${AFTER_REVISION}" != "${BEFORE_REVISION}" ]]; then
      CONVERGED=true
      break
    fi
    echo "ERROR: ${SERVICE} still serves ${BEFORE_REVISION}." > "${CHECK_ERRORS}"
  fi
  sleep "${CONVERGENCE_INTERVAL_SECONDS}"
done
if [[ "${CONVERGED}" != "true" ]]; then
  cat "${CHECK_ERRORS}" >&2
  echo "ERROR: ${SERVICE} did not converge to one new untagged ready revision at 100%; no evidence written. Read the service, and run rollback if the new configuration serves." >&2
  exit 1
fi
if [[ "${AFTER_TEMPLATE_IMAGE}" != "${BEFORE_TEMPLATE_IMAGE}" && \
  "${AFTER_TEMPLATE_IMAGE}" != "${EXPECTED_IMAGE}" ]]; then
  echo "ERROR: service template image changed to ${AFTER_TEMPLATE_IMAGE}; no evidence written. Run rollback." >&2
  exit 1
fi
if ! inspect config-only "${BEFORE_SERVICE}" "${AFTER_SERVICE}"; then
  echo "ERROR: the update changed more than the governance variables; no evidence written. Run rollback." >&2
  exit 1
fi
if ! gcloud run revisions describe "${AFTER_REVISION}" \
  --region "${REGION}" \
  --project "${PROJECT}" \
  --format=json > "${AFTER_REVISION_JSON}"; then
  echo "ERROR: could not read new revision ${AFTER_REVISION}; no evidence written." >&2
  exit 1
fi
if ! inspect revision "${AFTER_REVISION_JSON}" "${AFTER_REVISION}" "${EXPECTED_IMAGE}" \
  "${EXPECTED_SHA}" "${AFTER_FLAG}" "${AFTER_EXPIRY}" > /dev/null; then
  echo "ERROR: new revision ${AFTER_REVISION} is not the expected configuration; no evidence written. Run rollback." >&2
  exit 1
fi
COMPLETED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)

EVIDENCE_TEMP=$(mktemp "${EVIDENCE_OUTPUT}.tmp.XXXXXX")
inspect evidence "${EVIDENCE_TEMP}" "${MODE}" "${PROJECT}" "${REGION}" "${SERVICE}" \
  "${EXPECTED_SHA}" "${EXPECTED_IMAGE}" "${BEFORE_REVISION_JSON}" "${AFTER_REVISION_JSON}" \
  "${BEFORE_REVISION}" "${AFTER_REVISION}" "${STARTED_AT}" "${UPDATED_AT}" "${COMPLETED_AT}" \
  --container api "${UPDATE_FLAGS[@]}"
if [[ -e "${EVIDENCE_OUTPUT}" || -L "${EVIDENCE_OUTPUT}" ]]; then
  echo "ERROR: ${EVIDENCE_OUTPUT} appeared during the run; verified evidence left at ${EVIDENCE_TEMP}." >&2
  EVIDENCE_TEMP=""
  exit 1
fi
mv -- "${EVIDENCE_TEMP}" "${EVIDENCE_OUTPUT}"
EVIDENCE_TEMP=""
echo "  ${AFTER_REVISION} serves ${EXPECTED_IMAGE} with ${FLAG_NAME}=${AFTER_FLAG}${AFTER_EXPIRY:+ until ${AFTER_EXPIRY}}." >&2
echo "  evidence=${EVIDENCE_OUTPUT}" >&2
