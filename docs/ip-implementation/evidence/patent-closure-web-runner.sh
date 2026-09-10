#!/bin/sh
set -eu
test -n "$RUN_LABEL"
test -s "$SOURCE_PATHS"
node -e 'const fs = require("fs"); const paths = fs.readFileSync(process.env.SOURCE_PATHS, "utf8").split("\0").filter(Boolean); if (!paths.length || paths.some(p => /[\r\n]/.test(p) || p.startsWith("/") || p.split("/").includes(".."))) throw new Error("Invalid source inventory"); fs.writeFileSync("/tmp/patent-source-paths", paths.join("\n") + "\n");'
tar -C /workspace -T /tmp/patent-source-paths -cf /tmp/patent-source.tar
sha256sum /tmp/patent-source.tar > "/output/source-${RUN_LABEL}.sha256"
tar -C /app -xf /tmp/patent-source.tar
cd /app/apps/web
node ../../node_modules/typescript/bin/tsc --noEmit --incremental false > "/output/typecheck-${RUN_LABEL}.log" 2>&1
exec node ../../node_modules/vitest/vitest.mjs run --maxWorkers=1 --reporter=default --reporter=junit --outputFile="/output/web-${RUN_LABEL}.xml" components/ip/PatentProsecutionWorkspace.test.tsx components/ip/PatentApplicationWorkspace.test.tsx lib/api/ip-patent-prosecution.test.ts
