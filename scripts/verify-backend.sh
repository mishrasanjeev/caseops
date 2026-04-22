#!/usr/bin/env bash
# Canonical backend verification. Bypasses `uv run`'s implicit sync
# step (which fails on Windows when a long-running process holds a
# lock on .venv/Scripts/*.exe — most often the corpus sweep).
#
# Usage:
#   scripts/verify-backend.sh [pytest-args...]
#
# Examples:
#   scripts/verify-backend.sh                           # full backend suite
#   scripts/verify-backend.sh tests/test_intake.py      # one file
#   scripts/verify-backend.sh -k "reminders or intake"  # by keyword
#
# Goal of this script: an outside agent (Codex, human reviewer) who
# clones the repo can run a clean `uv sync --frozen` and a targeted
# pytest group without first stopping unrelated background processes
# or guessing the right Python interpreter.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API_DIR="$REPO_ROOT/apps/api"
cd "$API_DIR"

# Pick the right venv binary path per OS.
if [[ "${OS:-}" == "Windows_NT" ]] || [[ "$(uname -s)" == MINGW* ]] || [[ "$(uname -s)" == CYGWIN* ]]; then
  VENV_PY="$API_DIR/.venv/Scripts/python.exe"
  VENV_PYTEST="$API_DIR/.venv/Scripts/pytest.exe"
  VENV_RUFF="$API_DIR/.venv/Scripts/ruff.exe"
else
  VENV_PY="$API_DIR/.venv/bin/python"
  VENV_PYTEST="$API_DIR/.venv/bin/pytest"
  VENV_RUFF="$API_DIR/.venv/bin/ruff"
fi

# Ensure the venv exists and packages are in sync with uv.lock.
# --frozen means uv refuses to update the lock — which is what we
# want for verification: the lock IS the contract. --no-install-project
# skips re-installing the local caseops_api package, which avoids
# rebuilding .venv/Scripts/*.exe wrappers (the file lock that bites
# when the corpus sweep is running). The local package is editable in
# the existing venv anyway, so this is a no-op when the venv is fresh.
if [[ ! -x "$VENV_PY" ]]; then
  echo "[verify-backend] venv missing — bootstrapping with uv sync --frozen"
  uv sync --frozen --no-install-project
fi

# Sanity import check — fails loudly if a top-level runtime dep is
# missing from the venv. This catches the exact symptom that bit
# Codex's verification on 2026-04-22 (ModuleNotFoundError: slowapi).
"$VENV_PY" -c "
import sys
import importlib.util
# Keep this list aligned with apps/api/pyproject.toml ``dependencies``.
# Module names use the import path (not the distribution name) — e.g.
# fpdf2 -> fpdf, python-docx -> docx, google-cloud-storage -> google.
# We list every top-level runtime dep so a partial sync surfaces here
# instead of mid-pytest as a confusing ImportError.
required = [
    'fastapi', 'sqlalchemy', 'alembic', 'pydantic', 'pydantic_settings',
    'slowapi', 'httpx', 'voyageai', 'anthropic', 'fpdf', 'docx',
    'google.cloud.storage', 'jwt', 'pdfminer', 'PIL', 'fastembed',
    'boto3', 'clamd',
]
missing = [m for m in required if importlib.util.find_spec(m) is None]
if missing:
    print('[verify-backend] FATAL — missing runtime deps in venv:', missing, file=sys.stderr)
    print('[verify-backend] Fix: uv sync --frozen --no-install-project', file=sys.stderr)
    sys.exit(2)
print('[verify-backend] venv has all required runtime deps')
"

echo "[verify-backend] running ruff"
"$VENV_RUFF" check src tests

echo "[verify-backend] running pytest $*"
exec "$VENV_PYTEST" "$@"
