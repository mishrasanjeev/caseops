#!/bin/sh
set -eu
: "${RUN_LABEL:?Use a new evidence label for each attempt}"
test ! -e "/output/${RUN_LABEL}-source.sha256"
test "$(sha256sum /app/package-lock.json | cut -d ' ' -f1)" = "$(sha256sum /workspace/package-lock.json | cut -d ' ' -f1)"
tar -C /workspace --exclude=.git --exclude=.tmp --exclude=node_modules --exclude=.venv -cf /tmp/source.tar .
sha256sum /tmp/source.tar > "/output/${RUN_LABEL}-source.sha256"
tar -C /app -xf /tmp/source.tar
cd /app/apps/web
node -p 'JSON.stringify({node:process.version,vitest:require("vitest/package.json").version,next:require("next/package.json").version})'
test ! -e "/output/${RUN_LABEL}.xml"
/app/node_modules/.bin/vitest run app/app/admin/data-governance/holds/page.test.tsx app/app/admin/data-governance/page.test.tsx lib/capabilities.test.ts lib/api/legal-holds.test.ts lib/api/legal-holds.transport.test.ts --reporter=default --reporter=junit --outputFile="/output/${RUN_LABEL}.xml"
cd /app
exec sh scripts/tests/check-ip-foundations-web.sh
