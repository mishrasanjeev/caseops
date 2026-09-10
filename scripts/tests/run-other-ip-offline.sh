#!/usr/bin/env bash
set -euo pipefail
available_kib=$(df -Pk /tmp | awk 'NR == 2 { print $4 }')
test "${available_kib:-0}" -ge 2097152
probe=$(mktemp /tmp/other-ip-exec.XXXXXX)
cp /bin/true "$probe"
chmod 700 "$probe"
"$probe"
test -x "$CASEOPS_TEST_TEMPORAL_SERVER_PATH"
test "$(sha256sum "$CASEOPS_TEST_TEMPORAL_SERVER_PATH" | awk '{print $1}')" = "$CASEOPS_TEST_TEMPORAL_SERVER_SHA256"
mkdir /candidate
tar --exclude=.git -C /workspace -cf "/output/source-${RUN_LABEL}.tar" .
sha256sum "/output/source-${RUN_LABEL}.tar" > "/output/source-${RUN_LABEL}.sha256"
tar -C /candidate -xf "/output/source-${RUN_LABEL}.tar"
cd /candidate/apps/api
export PYTHONPATH=/candidate/apps/api/src
export CASEOPS_TEST_RESULT_JOURNAL="/output/${RUN_LABEL}.jsonl"
exec python -m pytest -q -p no:cacheprovider --tb=short --junitxml="/output/${RUN_LABEL}.xml" "$@"
