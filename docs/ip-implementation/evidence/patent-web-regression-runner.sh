#!/bin/sh
set -eu
tar -C /app -xf "$SOURCE_ARCHIVE"
test_file=apps/web/components/ip/PatentProsecutionWorkspace.test.tsx
cp "/workspace/$test_file" "/app/$test_file"
sha256sum "$SOURCE_ARCHIVE" "/workspace/$test_file" > "/output/regression-source-${RUN_LABEL}.sha256"
cd /app/apps/web
exec node /app/node_modules/vitest/vitest.mjs run components/ip/PatentProsecutionWorkspace.test.tsx --maxWorkers=1 --reporter=default --reporter=junit --outputFile="/output/web-${RUN_LABEL}.xml"
