#!/usr/bin/env bash
set -euo pipefail
: "${RUN_LABEL:?Use a new evidence label for each attempt}"
test ! -e "/output/${RUN_LABEL}.json"
test ! -e "/output/${RUN_LABEL}-build.txt"
available_kib=$(df -Pk /scratch | awk 'NR == 2 { print $4 }')
test "${available_kib:-0}" -ge 2097152
probe=$(mktemp /scratch/exec-probe.XXXXXX)
cp /bin/true "$probe"
chmod 700 "$probe"
"$probe"
test "$(sha256sum /opt/caseops-test-tools/temporal-test-server | cut -d' ' -f1)" = daa58458d32f6254a901085c27ad1c19a64a4e171679ed08b5b92c298baba6ce
mkdir /scratch/candidate
tar -C /workspace --exclude=.git --exclude=.tmp --exclude=node_modules --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache -cf /scratch/source.tar .
sha256sum /scratch/source.tar > "/output/${RUN_LABEL}-source.sha256"
tar -C /scratch/candidate -xf /scratch/source.tar
cp -a /tools/node_modules /scratch/candidate/node_modules
cd /scratch/candidate
node -e '
const fs = require("node:fs");
const lock = require("./package-lock.json");
for (const file of ["./package.json", "./apps/web/package.json"]) {
  const manifest = require(file);
  for (const name of Object.keys({...manifest.dependencies, ...manifest.devDependencies})) {
    const actual = JSON.parse(fs.readFileSync("node_modules/" + name + "/package.json")).version;
    const expected = lock.packages[(file.startsWith("./apps/web/") ? "apps/web/" : "") + "node_modules/" + name]?.version ?? lock.packages["node_modules/" + name]?.version;
    if (actual !== expected) throw new Error(`${name}: ${actual} does not match ${expected}`);
  }
}
console.log("All direct application/test dependencies match the candidate lockfile.");
' > "/output/${RUN_LABEL}-dependencies.txt"
export PYTHONPATH=/scratch/candidate/apps/api/src
export CASEOPS_E2E_PYTHON=/usr/local/bin/python
export NEXT_TELEMETRY_DISABLED=1
export NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
cd apps/web
node ../../node_modules/next/dist/bin/next build > "/output/${RUN_LABEL}-build.txt" 2>&1
cd ../..
node node_modules/@playwright/test/cli.js test --config playwright.ip-foundations.config.ts
