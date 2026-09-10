#!/usr/bin/env bash
set -euo pipefail
: "${RUN_LABEL:?Fresh source label required}"
test ! -e "/output/${RUN_LABEL}-source.tar"
test ! -e "/output/${RUN_LABEL}-paths.z"
cd /workspace
git -c safe.directory='*' --git-dir=/sourcegit/worktrees/codex-patent-closure-20260909 \
  --work-tree=/workspace ls-files -z --cached --others --exclude-standard \
  --exclude='**/.venv' --exclude='**/node_modules' > "/output/${RUN_LABEL}-paths.z"
test -s "/output/${RUN_LABEL}-paths.z"
tar --null -T "/output/${RUN_LABEL}-paths.z" -cf "/output/${RUN_LABEL}-source.tar"
sha256sum "/output/${RUN_LABEL}-source.tar" > "/output/${RUN_LABEL}-source.sha256"
xargs -0 sha256sum < "/output/${RUN_LABEL}-paths.z" > "/output/${RUN_LABEL}-files.sha256"
