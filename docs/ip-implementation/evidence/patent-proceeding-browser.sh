#!/usr/bin/env bash
set -euo pipefail
: "${RUN_LABEL:?}"
: "${SOURCE_ARCHIVE:?}"
test ! -e "/output/browser-${RUN_LABEL}"
test ! -e "/output/browser-${RUN_LABEL}.xml"
mkdir -p /patent-artifacts /candidate
retain_artifacts() {
  if [ -d "/patent-artifacts/browser-${RUN_LABEL}" ]; then
    cp -a "/patent-artifacts/browser-${RUN_LABEL}" /output/
  fi
  if [ -f "/patent-artifacts/browser-${RUN_LABEL}.xml" ]; then
    cp "/patent-artifacts/browser-${RUN_LABEL}.xml" /output/
  fi
}
trap retain_artifacts EXIT
tar -C /candidate -xf "$SOURCE_ARCHIVE"
sha256sum "$SOURCE_ARCHIVE" > "/output/browser-source-${RUN_LABEL}.sha256"
spec=tests/e2e/iplf-080b-patent-pregrant-proceeding-2026-09-10.spec.ts
cp "/workspace/$spec" "/candidate/$spec"
sha256sum /workspace/docs/ip-implementation/evidence/patent-proceeding-browser.sh > "/output/browser-runner-${RUN_LABEL}.sha256"
ln -s /tools/node_modules /candidate/node_modules
export PYTHONPATH=/candidate/apps/api/src
export CASEOPS_E2E_PYTHON=/usr/local/bin/python
export PLAYWRIGHT_JUNIT_OUTPUT_FILE="/patent-artifacts/browser-${RUN_LABEL}.xml"
cd /candidate
sha256sum tests/e2e/iplf-080b-patent-pregrant-proceeding-2026-09-10.spec.ts > "/output/browser-spec-${RUN_LABEL}.sha256"
node node_modules/typescript/bin/tsc -p tsconfig.e2e.json --noEmit --incremental false > "/output/e2e-types-${RUN_LABEL}.log" 2>&1
node node_modules/@playwright/test/cli.js test tests/e2e/iplf-080b-patent-pregrant-proceeding-2026-09-10.spec.ts \
  --config docs/ip-implementation/evidence/patent-browser.config.ts --workers=1 --retries=0 \
  --output "/patent-artifacts/browser-${RUN_LABEL}"
