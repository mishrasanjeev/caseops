#!/usr/bin/env bash
# Canonical web verification. Rebuilds the Next.js bundle FIRST, then
# runs vitest + tsc + Playwright (app suite). The rebuild step is the
# critical guard — Playwright's webServer is `npx next start` against
# the prebuilt `.next/` directory, so a stale bundle silently reports
# old behaviour and a real fix can look like it didn't land.
#
# Usage:
#   scripts/verify-web.sh                              # vitest + tsc + full e2e
#   scripts/verify-web.sh --quick                      # vitest + tsc only
#   scripts/verify-web.sh --e2e-only -g "BUG-011"      # one Playwright spec
#
# Designed for outside reviewers (Codex, second agent) — the rebuild
# is mandatory so frontend verdicts are never based on a stale
# bundle. The bug-fixing skill says "Reopened bugs require fresh
# end-user verification before closure"; that requires fresh code.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WEB_DIR="$REPO_ROOT/apps/web"
cd "$WEB_DIR"

QUICK=false
E2E_ONLY=false
PLAYWRIGHT_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --quick) QUICK=true ;;
    --e2e-only) E2E_ONLY=true ;;
    *) PLAYWRIGHT_ARGS+=("$arg") ;;
  esac
done

if [[ "$E2E_ONLY" == false ]]; then
  echo "[verify-web] vitest"
  npx vitest run --reporter=dot
  echo "[verify-web] tsc --noEmit"
  npx tsc --noEmit
fi

if [[ "$QUICK" == true ]]; then
  echo "[verify-web] --quick set; skipping build + Playwright"
  exit 0
fi

# REBUILD-FIRST is the whole point of this script.
echo "[verify-web] npm run build (mandatory; prevents stale-bundle false negatives)"
npm run build

cd "$REPO_ROOT"
echo "[verify-web] Playwright app suite ${PLAYWRIGHT_ARGS[*]:-(all)}"
exec npx playwright test --config playwright.app.config.ts "${PLAYWRIGHT_ARGS[@]}"
