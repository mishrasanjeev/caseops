#!/bin/sh
set -eu
OPENAPI_CLI=${OPENAPI_CLI:-/opt/node_modules/openapi-typescript/bin/cli.js}
RUN_LABEL=${RUN_LABEL:?Use a fresh retained evidence label}
test -f "$OPENAPI_CLI"
test ! -e "/output/web-focused-${RUN_LABEL}.xml"
tr -d '\r' < /output/web-source-paths.txt > /tmp/catalogue-source-paths
test -s /tmp/catalogue-source-paths
tar -C /workspace -T /tmp/catalogue-source-paths -cf /tmp/catalogue-source.tar
sha256sum /tmp/catalogue-source.tar > "/output/web-source-${RUN_LABEL}.sha256"
tar -C /app -xf /tmp/catalogue-source.tar
cd /app
node "$OPENAPI_CLI" --version
node "$OPENAPI_CLI" --alphabetize /output/openapi-final.json --output /output/openapi-types.ts
cp /output/openapi-types.ts /app/apps/web/lib/api/openapi-types.ts
node node_modules/typescript/bin/tsc --project tsconfig.e2e.json --incremental false
cd /app/apps/web
node ../../node_modules/typescript/bin/tsc --noEmit --incremental false
node ../../node_modules/vitest/vitest.mjs run app/app/statutes 'app/app/matters/[id]/statutes' --maxWorkers=1 --reporter=default --reporter=junit --outputFile="/output/web-focused-${RUN_LABEL}.xml"
