#!/usr/bin/env bash
set -euo pipefail
: "${RUN_LABEL:?Use a new evidence label for each attempt}"
: "${CASEOPS_TEST_RESULT_JOURNAL:?Structured per-phase evidence is required}"
test ! -e "$CASEOPS_TEST_RESULT_JOURNAL"
test ! -e "/output/${RUN_LABEL}.xml"
test ! -e "/output/${RUN_LABEL}-source.sha256"
test "$(df -Pk /tmp | awk 'NR == 2 {print $4}')" -ge 2097152
cp /bin/true /tmp/foundations-exec-probe
chmod 700 /tmp/foundations-exec-probe
/tmp/foundations-exec-probe
test -x "$CASEOPS_TEST_TEMPORAL_SERVER_PATH"
printf '%s  %s\n' "$CASEOPS_TEST_TEMPORAL_SERVER_SHA256" "$CASEOPS_TEST_TEMPORAL_SERVER_PATH" | sha256sum --check
mkdir /tmp/candidate
tar -C /workspace --exclude=.git --exclude=.tmp --exclude=node_modules --exclude=.venv -cf /tmp/source.tar .
sha256sum /tmp/source.tar > "/output/${RUN_LABEL}-source.sha256"
tar -C /tmp/candidate -xf /tmp/source.tar
export PYTHONPATH=/tmp/candidate/apps/api/src
cd /tmp/candidate/apps/api
for selected in "$@"; do
  test -f "${selected%%::*}"
done
python -c 'import caseops_api; print(caseops_api.__file__)'
if [[ -n "${CASEOPS_TEST_POSTGRES_URL:-}" ]]; then
  export CASEOPS_DATABASE_URL="$CASEOPS_TEST_POSTGRES_URL"
  export CASEOPS_ENV=local
  python -m alembic upgrade head
fi
exec python -m pytest -q --tb=long -p tests.retained_results -p no:cacheprovider --junitxml="/output/${RUN_LABEL}.xml" "$@"
