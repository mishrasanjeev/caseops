#!/usr/bin/env bash
# Cloud Run Job: backfill_hc_judges_from_corpus
#
# Extracts judge names from authority_documents.judges_json (populated
# by Layer-2 metadata extraction) and inserts any missing rows into
# the judges table + judge_aliases. Per-court floor of --min-occurrences=2
# drops one-off parser artifacts.
#
# Per the 2026-04-27 user directive: backfill the missing Delhi HC
# judges (Sachdeva, Manmohan, Endlaw, etc.) so bench-strategy resolves
# them on real lawyer matters.
#
# Usage:
#   scripts/backfill-hc-judges-from-corpus-job.sh <image-tag> [court]
#     court: pass a catalogued court_id (e.g. delhi-hc, bombay-hc) to
#       scope the backfill, OR pass "all" / omit to run across every
#       court matched by the script's _COURT_NAME_MATCHERS list (7
#       HCs as of 2026-04-27: delhi, bombay, madras, karnataka,
#       telangana, allahabad, calcutta).
set -euo pipefail
if [[ $# -lt 1 ]]; then echo "usage: $0 <image-tag> [court|all]" >&2; exit 1; fi

PROJECT=perfect-period-305406
REGION=asia-south1
JOB=caseops-backfill-hc-judges-from-corpus
IMAGE="asia-south1-docker.pkg.dev/${PROJECT}/caseops-images/caseops-api:$1"
SQL_INSTANCE="${PROJECT}:${REGION}:caseops-db"
COURT="${2:-all}"

# Build the args list. The unusual delimiter (^|^) is gcloud's way of
# saying "the next char (|) is the field separator for this list".
# Omit --court when "all" so the script iterates every matcher.
if [[ "$COURT" == "all" ]]; then
  ARGS_PIPE="-m|caseops_api.scripts.backfill_hc_judges_from_corpus"
else
  ARGS_PIPE="-m|caseops_api.scripts.backfill_hc_judges_from_corpus|--court|${COURT}"
fi

echo "=== ${JOB}: image=${IMAGE} court=${COURT} ==="
ACTION=$(gcloud run jobs describe "${JOB}" --region "${REGION}" --project "${PROJECT}" >/dev/null 2>&1 && echo update || echo create)
echo "--- ${ACTION} job ---"
gcloud run jobs $ACTION "${JOB}" \
  --image="${IMAGE}" \
  --region="${REGION}" --project="${PROJECT}" \
  --command=python \
  --args="^|^${ARGS_PIPE}" \
  --service-account="caseops-runtime@${PROJECT}.iam.gserviceaccount.com" \
  --set-env-vars "CASEOPS_ENV=cloud,CASEOPS_AUTO_MIGRATE=false" \
  --set-secrets "CASEOPS_DATABASE_URL=caseops-database-url:latest,CASEOPS_AUTH_SECRET=caseops-auth-secret:latest" \
  --set-cloudsql-instances "${SQL_INSTANCE}" \
  --task-timeout=3600 \
  --max-retries 1 --quiet

echo "--- executing job (court=${COURT}) ---"
gcloud run jobs execute "${JOB}" --region "${REGION}" --project "${PROJECT}" --wait --quiet
echo "=== ${JOB}: DONE court=${COURT} ==="
