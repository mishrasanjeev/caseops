#!/usr/bin/env bash
set -euo pipefail
test "$(df -Pk /tmp | awk 'NR == 2 { print $4 }')" -ge 2097152
probe=$(mktemp /tmp/other-ip-next-exec.XXXXXX)
cp /bin/true "$probe"
chmod 700 "$probe"
"$probe"
test -x "$CASEOPS_TEST_TEMPORAL_SERVER_PATH"
test "$(sha256sum "$CASEOPS_TEST_TEMPORAL_SERVER_PATH" | awk '{print $1}')" = "$CASEOPS_TEST_TEMPORAL_SERVER_SHA256"
test ! -e "/output/$RUN_LABEL-source.tar"
tar -C /workspace --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache --exclude=.ruff_cache \
  -cf "/output/$RUN_LABEL-source.tar" apps/api tests/fixtures docs/ip-implementation/child-prds
sha256sum "/output/$RUN_LABEL-source.tar" > "/output/$RUN_LABEL-source.sha256"
mkdir /candidate
tar -C /candidate -xf "/output/$RUN_LABEL-source.tar"
cd /candidate
find apps/api tests/fixtures docs/ip-implementation/child-prds -type f -print0 | sort -z | xargs -0 sha256sum > "/output/$RUN_LABEL-files.sha256"
cd apps/api
export PYTHONPATH=/candidate/apps/api/src:/candidate/apps/api
export CASEOPS_TEST_RESULT_JOURNAL="/output/$RUN_LABEL.jsonl"
python -c 'import caseops_api; from pathlib import Path; p=Path(caseops_api.__file__).resolve(); print("Resolved candidate:", p); assert p.is_relative_to("/candidate/apps/api/src")'
exec python -B -m pytest -q -p no:cacheprovider --tb=long --basetemp="/tmp/$RUN_LABEL" --junitxml="/output/$RUN_LABEL.xml" "$@"
