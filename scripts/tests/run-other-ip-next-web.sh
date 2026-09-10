#!/bin/sh
set -eu
export NODE_OPTIONS=--max-old-space-size=1536
test ! -e "/output/$RUN_LABEL-source.tar"
phase=snapshot
trap 'code=$?; printf "{\"event\":\"web_run_finished\",\"phase\":\"%s\",\"exit_code\":%s}\n" "$phase" "$code" >> "/output/$RUN_LABEL-checks.jsonl"' EXIT
cd /workspace
tar --exclude=node_modules --exclude=.next --exclude=.venv --exclude=__pycache__ \
  -cf "/output/$RUN_LABEL-source.tar" apps/web tests scripts package.json package-lock.json tsconfig.e2e.json playwright*.config.ts docs/ip-implementation/PRODUCT_GUIDE_CATALOG.json
sha256sum "/output/$RUN_LABEL-source.tar" > "/output/$RUN_LABEL-source.sha256"
mkdir /candidate
tar -C /candidate -xf "/output/$RUN_LABEL-source.tar"
ln -s /app/node_modules /candidate/node_modules
if [ -d /app/apps/web/node_modules ]; then
  ln -s /app/apps/web/node_modules /candidate/apps/web/node_modules
fi
sha256sum /app/package-lock.json /candidate/package-lock.json > "/output/$RUN_LABEL-lockfiles.sha256"
cmp /app/package-lock.json /candidate/package-lock.json
cd /candidate/apps/web
phase=web_typecheck
node /app/node_modules/typescript/bin/tsc --noEmit --incremental false > "/output/$RUN_LABEL-types.log" 2>&1
printf '%s\n' '{"event":"web_typecheck_finished","exit_code":0}' >> "/output/$RUN_LABEL-checks.jsonl"
cd /candidate
phase=e2e_typecheck
node /app/node_modules/typescript/bin/tsc --noEmit --incremental false --project tsconfig.e2e.json > "/output/$RUN_LABEL-e2e-types.log" 2>&1
printf '%s\n' '{"event":"e2e_typecheck_finished","exit_code":0}' >> "/output/$RUN_LABEL-checks.jsonl"
cd /candidate/apps/web
phase=vitest
node /app/node_modules/vitest/vitest.mjs run --maxWorkers=1 --reporter=default --reporter=junit --outputFile="/output/$RUN_LABEL.xml" \
  components/ip/SpecialistWorkspace.test.tsx components/ip/SpecialistWorkflows.test.tsx components/ip/SpecialistLayoutWorkflows.test.tsx lib/api/ip-specialist.test.ts
