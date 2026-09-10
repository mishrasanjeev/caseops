#!/bin/sh
set -eu
: "${RUN_LABEL:?Use a fresh evidence label}"
test ! -e "/output/${RUN_LABEL}-source.sha256"
test ! -e "/output/${RUN_LABEL}.xml"
test "$(sha256sum /app/package-lock.json | cut -d ' ' -f1)" = "$(sha256sum /workspace/package-lock.json | cut -d ' ' -f1)"
tar -C /workspace --exclude=.git --exclude=.tmp --exclude=node_modules --exclude=.venv -cf /tmp/source.tar .
sha256sum /tmp/source.tar > "/output/${RUN_LABEL}-source.sha256"
tar -C /app -xf /tmp/source.tar
cd /app/apps/web
/app/node_modules/.bin/vitest run app/app/admin/access-reviews/page.test.tsx lib/api/access-reviews.test.ts --reporter=default --reporter=junit --outputFile="/output/${RUN_LABEL}.xml"
/app/node_modules/.bin/tsc --noEmit --incremental false > "/output/${RUN_LABEL}-typescript.txt" 2>&1
cd /app
/app/node_modules/.bin/playwright test --config playwright.app.config.ts --list iplf-073b-access-reviews-2026-09-10.spec.ts > "/output/${RUN_LABEL}-collection.txt" 2>&1
