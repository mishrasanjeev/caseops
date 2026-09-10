#!/bin/sh
set -eu
tar -C /app -xf "$SOURCE_ARCHIVE"
sha256sum "$SOURCE_ARCHIVE" > "/output/web-source-${RUN_LABEL}.sha256"
cd /app/apps/web
node /app/node_modules/next/dist/bin/next build > "/output/web-build-${RUN_LABEL}.log" 2>&1
sha256sum .next/BUILD_ID > "/output/web-build-id-${RUN_LABEL}.sha256"
exec node /app/node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 3000
