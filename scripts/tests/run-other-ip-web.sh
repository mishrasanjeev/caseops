#!/bin/sh
set -eu
mkdir /candidate
tar --exclude=.git -C /workspace -cf "/output/source-${RUN_LABEL}.tar" .
sha256sum "/output/source-${RUN_LABEL}.tar" > "/output/source-${RUN_LABEL}.sha256"
tar -C /candidate -xf "/output/source-${RUN_LABEL}.tar"
ln -s /app/node_modules /candidate/node_modules
if [ -d /app/apps/web/node_modules ]; then
  ln -s /app/apps/web/node_modules /candidate/apps/web/node_modules
fi
cd /candidate/apps/web
node /app/node_modules/typescript/bin/tsc --noEmit --incremental false > "/output/${RUN_LABEL}-typecheck.log" 2>&1
cd /candidate
node /app/node_modules/typescript/bin/tsc --project tsconfig.e2e.json > "/output/${RUN_LABEL}-e2e-typecheck.log" 2>&1
node /app/node_modules/@playwright/test/cli.js test --config playwright.docker.config.ts --list tests/e2e/iplf-090a-other-ip-domains-2026-09-09.spec.ts > "/output/${RUN_LABEL}-playwright-inventory.log" 2>&1
cd /candidate/apps/web
exec node /app/node_modules/vitest/vitest.mjs run --maxWorkers=1 --reporter=default --reporter=junit --outputFile="/output/${RUN_LABEL}.xml" components/ip/SpecialistWorkspace.test.tsx lib/api/ip-specialist.test.ts
