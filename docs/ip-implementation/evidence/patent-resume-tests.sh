#!/usr/bin/env bash
set -euo pipefail
: "${RUN_LABEL:?Fresh evidence label required}"
: "${CASEOPS_TEST_POSTGRES_URL:?Isolated PostgreSQL required}"
test ! -e "/output/${RUN_LABEL}.jsonl"
test ! -e "/output/${RUN_LABEL}.xml"
available_kib=$(df -Pk /tmp | awk 'NR == 2 { print $4 }')
test "${available_kib:-0}" -ge 2097152
probe=$(mktemp /tmp/patent-exec-probe.XXXXXX)
cp /bin/true "$probe"
chmod 700 "$probe"
"$probe"
rm -- "$probe"
source_git=/sourcegit/worktrees/codex-patent-closure-20260909
branch=$(git -c safe.directory='*' --git-dir="$source_git" symbolic-ref --short HEAD)
git -c safe.directory='*' clone --shared --branch "$branch" /sourcegit /candidate
cd /workspace
git -c safe.directory='*' --git-dir="$source_git" --work-tree=/workspace \
  ls-files -z --cached --others --exclude-standard \
  --exclude='**/.venv' --exclude='**/node_modules' > "/output/${RUN_LABEL}-paths.z"
tar --null -T "/output/${RUN_LABEL}-paths.z" -cf "/output/${RUN_LABEL}-source.tar"
sha256sum "/output/${RUN_LABEL}-source.tar" > "/output/${RUN_LABEL}-source.sha256"
tar -C /candidate -xf "/output/${RUN_LABEL}-source.tar"
cd /candidate
xargs -0 sha256sum < "/output/${RUN_LABEL}-paths.z" > "/output/${RUN_LABEL}-files.sha256"
cd apps/api
export PYTHONPATH=/candidate/apps/api/src
export CASEOPS_ENV=local CASEOPS_LLM_PROVIDER=mock CASEOPS_EMBEDDING_PROVIDER=mock
export CASEOPS_DATABASE_URL="$CASEOPS_TEST_POSTGRES_URL"
python -m alembic upgrade head > "/output/${RUN_LABEL}-migrate.log" 2>&1
export CASEOPS_TEST_RESULT_JOURNAL="/output/${RUN_LABEL}.jsonl"
exec timeout --signal=INT --kill-after=30s 1800 python -m pytest \
  -n 0 -q --tb=long -o faulthandler_timeout=90 \
  -p no:cacheprovider -p tests.retained_results \
  --junitxml="/output/${RUN_LABEL}.xml" "$@"
