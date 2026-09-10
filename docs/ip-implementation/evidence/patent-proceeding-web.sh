#!/bin/sh
set -eu
: "${RUN_LABEL:?}"
: "${SOURCE_ARCHIVE:?}"
test ! -e "/output/web-${RUN_LABEL}.xml"
tar -C /app -xf "$SOURCE_ARCHIVE"
sha256sum "$SOURCE_ARCHIVE" > "/output/web-source-${RUN_LABEL}.sha256"
cd /app/apps/web
node /app/node_modules/typescript/bin/tsc --noEmit --incremental false > "/output/typecheck-${RUN_LABEL}.log" 2>&1
node /app/node_modules/vitest/vitest.mjs run --maxWorkers=1 --reporter=default --reporter=junit \
  --outputFile="/output/web-${RUN_LABEL}.xml" components/ip/PatentProceedingsWorkspace.test.tsx \
  components/ip/PatentProsecutionWorkspace.test.tsx components/ip/PatentApplicationWorkspace.test.tsx \
  lib/api/ip-patent-prosecution.test.ts
node /app/node_modules/next/dist/bin/next build > "/output/web-build-${RUN_LABEL}.log" 2>&1
sha256sum .next/BUILD_ID > "/output/web-build-id-${RUN_LABEL}.sha256"
exec node /app/node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 3000
