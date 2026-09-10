#!/bin/sh
set -eu
: "${RUN_LABEL:?Use a new evidence label for each attempt}"
test ! -e "/output/${RUN_LABEL}-typescript.txt"
test ! -e "/output/${RUN_LABEL}-playwright-collection.txt"
test "$(sha256sum /app/package-lock.json | cut -d ' ' -f1)" = "$(sha256sum /workspace/package-lock.json | cut -d ' ' -f1)"
cp -a /workspace/apps/web/. /app/apps/web/
cp -a /workspace/tests /app/tests
cp /workspace/playwright.app.config.ts /app/playwright.app.config.ts
cd /app/apps/web
/app/node_modules/.bin/tsc --noEmit --incremental false > "/output/${RUN_LABEL}-typescript.txt" 2>&1
cd /app
/app/node_modules/.bin/playwright test --config playwright.app.config.ts --list iplf-028b-legal-holds-2026-09-09.spec.ts > "/output/${RUN_LABEL}-playwright-collection.txt" 2>&1
