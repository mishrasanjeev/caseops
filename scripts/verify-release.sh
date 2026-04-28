#!/usr/bin/env bash
# Canonical release sign-off verification (bash).
# Runs the repo's backend/web verification recipes, checks the deployed
# surface, and writes a Markdown evidence file with a strict verdict.
#
# Usage:
#   scripts/verify-release.sh
#   scripts/verify-release.sh --expected-commit a44ea31
#   scripts/verify-release.sh --skip-backend --skip-web
#   scripts/verify-release.sh --build-info-url https://api.caseops.ai/api/build

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

EXPECTED_COMMIT=""
API_HEALTH_URL="https://api.caseops.ai/api/health"
WEB_URL="https://caseops.ai/"
CODE_AVAILABLE_URL="https://api.caseops.ai/api/matters/code-available?code=RELEASE-SIGNOFF-TEST"
REMINDERS_URL="https://api.caseops.ai/api/matters/00000000-0000-0000-0000-000000000000/reminders"
BUILD_INFO_URL=""
EVIDENCE_PATH=""
SKIP_BACKEND=false
SKIP_WEB=false
SKIP_PROD=false
BACKEND_ARGS=()
WEB_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --expected-commit) EXPECTED_COMMIT="$2"; shift 2 ;;
    --api-health-url) API_HEALTH_URL="$2"; shift 2 ;;
    --web-url) WEB_URL="$2"; shift 2 ;;
    --code-available-url) CODE_AVAILABLE_URL="$2"; shift 2 ;;
    --reminders-url) REMINDERS_URL="$2"; shift 2 ;;
    --build-info-url) BUILD_INFO_URL="$2"; shift 2 ;;
    --evidence-path) EVIDENCE_PATH="$2"; shift 2 ;;
    --backend-arg) BACKEND_ARGS+=("$2"); shift 2 ;;
    --web-arg) WEB_ARGS+=("$2"); shift 2 ;;
    --skip-backend) SKIP_BACKEND=true; shift ;;
    --skip-web) SKIP_WEB=true; shift ;;
    --skip-prod) SKIP_PROD=true; shift ;;
    *)
      echo "[verify-release] unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$EXPECTED_COMMIT" ]]; then
  EXPECTED_COMMIT="$(git rev-parse --short HEAD)"
fi
GIT_HEAD="$(git rev-parse HEAD)"
GENERATED_AT="$(date '+%Y-%m-%d %H:%M:%S %z')"

if [[ -z "$EVIDENCE_PATH" ]]; then
  EVIDENCE_PATH="$REPO_ROOT/docs/runbooks/release-signoff-$(date '+%Y-%m-%d_%H%M%S').md"
elif [[ "$EVIDENCE_PATH" != /* && ! "$EVIDENCE_PATH" =~ ^[A-Za-z]:[\\/].* ]]; then
  EVIDENCE_PATH="$REPO_ROOT/$EVIDENCE_PATH"
fi
mkdir -p "$(dirname "$EVIDENCE_PATH")"

CHECK_ROWS=()
CAVEATS=()
HAS_FAIL=false
HAS_CAVEAT=false

escape_md() {
  printf '%s' "$1" | tr '\r\n' '  ' | sed 's/|/\\|/g'
}

add_check() {
  local name="$1"
  local command="$2"
  local result="$3"
  local note="$4"
  CHECK_ROWS+=("| $(escape_md "$name") | $(escape_md "$command") | $(escape_md "$result") | $(escape_md "$note") |")
  if [[ "$result" == "fail" ]]; then
    HAS_FAIL=true
  fi
  if [[ "$result" == "skipped" || "$result" == "caveat" ]]; then
    HAS_CAVEAT=true
  fi
}

add_caveat() {
  if [[ -n "$1" ]]; then
    CAVEATS+=("$1")
  fi
}

run_check() {
  local name="$1"
  local command="$2"
  shift 2
  echo "[verify-release] $name"
  if "$@"; then
    add_check "$name" "$command" "pass" "exit code 0"
  else
    add_check "$name" "$command" "fail" "exit code $?"
  fi
}

url_check() {
  local name="$1"
  local url="$2"
  local expected="$3"
  local body_file
  body_file="$(mktemp)"
  local status
  status="$(curl -sS -L -o "$body_file" -w '%{http_code}' "$url" || true)"
  local body
  body="$(tr '\r\n' '  ' < "$body_file" | cut -c1-180)"
  rm -f "$body_file"

  if [[ "$status" == "$expected" ]]; then
    add_check "$name" "$url" "pass" "expected $expected, actual $status; $body"
  else
    add_check "$name" "$url" "fail" "expected $expected, actual $status; $body"
  fi
}

build_check() {
  local body_file
  body_file="$(mktemp)"
  local status
  status="$(curl -sS -L -o "$body_file" -w '%{http_code}' "$BUILD_INFO_URL" || true)"
  local body
  body="$(cat "$body_file")"
  rm -f "$body_file"

  if [[ "$status" == "200" && "$body" == *"$EXPECTED_COMMIT"* ]]; then
    add_check "Build fingerprint" "$BUILD_INFO_URL" "pass" "Response contains expected commit $EXPECTED_COMMIT"
  elif [[ "$status" == "200" ]]; then
    add_check "Build fingerprint" "$BUILD_INFO_URL" "caveat" "Endpoint responded 200 but did not prove expected commit $EXPECTED_COMMIT"
    add_caveat "Build fingerprint endpoint did not prove the expected commit."
  else
    add_check "Build fingerprint" "$BUILD_INFO_URL" "caveat" "expected 200, actual $status"
    add_caveat "Build fingerprint endpoint could not be verified."
  fi
}

if [[ "$SKIP_BACKEND" == true ]]; then
  add_check "Backend verification" "scripts/verify-backend.sh" "skipped" "Skipped by caller"
  add_caveat "Backend verification was skipped."
else
  run_check "Backend verification" "scripts/verify-backend.sh ${BACKEND_ARGS[*]:-}" "$REPO_ROOT/scripts/verify-backend.sh" "${BACKEND_ARGS[@]}"
fi

if [[ "$SKIP_WEB" == true ]]; then
  add_check "Web verification" "scripts/verify-web.sh" "skipped" "Skipped by caller"
  add_caveat "Web verification was skipped."
else
  run_check "Web verification" "scripts/verify-web.sh ${WEB_ARGS[*]:-}" "$REPO_ROOT/scripts/verify-web.sh" "${WEB_ARGS[@]}"
fi

if [[ "$SKIP_PROD" == true ]]; then
  add_check "Production smoke checks" "prod urls" "skipped" "Skipped by caller"
  add_caveat "Production smoke checks were skipped."
else
  url_check "API health" "$API_HEALTH_URL" "200"
  url_check "Web root" "$WEB_URL" "200"
  url_check "Code available endpoint (unauthenticated)" "$CODE_AVAILABLE_URL" "401"
  url_check "Reminders endpoint (unauthenticated)" "$REMINDERS_URL" "401"
fi

if [[ -n "$BUILD_INFO_URL" ]]; then
  build_check
else
  add_check "Build fingerprint" "(not supplied)" "caveat" "No build info URL supplied; deployed commit not proven from live surface"
  add_caveat "No build fingerprint URL supplied; deployed commit not proven from the live surface."
fi

VERDICT="GO"
if [[ "$HAS_FAIL" == true ]]; then
  VERDICT="NO-GO"
elif [[ "$HAS_CAVEAT" == true || "${#CAVEATS[@]}" -gt 0 ]]; then
  VERDICT="GO with caveat"
fi

{
  echo "# Release Sign-Off Evidence"
  echo
  echo "- Generated at: \`$GENERATED_AT\`"
  echo "- Target commit: \`$EXPECTED_COMMIT\`"
  echo "- Local git HEAD: \`$GIT_HEAD\`"
  echo "- Verdict: \`$VERDICT\`"
  echo
  echo "## Checks"
  echo
  echo "| Check | Command / URL | Result | Notes |"
  echo "| --- | --- | --- | --- |"
  printf '%s\n' "${CHECK_ROWS[@]}"
  echo
  echo "## Caveats"
  echo
  if [[ "${#CAVEATS[@]}" -eq 0 ]]; then
    echo "- None"
  else
    for caveat in "${CAVEATS[@]}"; do
      echo "- $caveat"
    done
  fi
  echo
  echo "## Reviewer Notes"
  echo
  echo "- Add any manual observations, screenshots, or deployment metadata here."
} > "$EVIDENCE_PATH"

echo "[verify-release] evidence written to $EVIDENCE_PATH"
echo "[verify-release] verdict: $VERDICT"

if [[ "$VERDICT" == "NO-GO" ]]; then
  exit 1
fi
