#Requires -Version 5.1
# Canonical backend verification (Windows PowerShell variant).
# Same goal as scripts/verify-backend.sh — see that file for rationale.
#
# Usage:
#   ./scripts/verify-backend.ps1                    # full backend suite
#   ./scripts/verify-backend.ps1 tests/test_intake.py
#   ./scripts/verify-backend.ps1 -k "reminders or intake"

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path "$PSScriptRoot\.."
$ApiDir = Join-Path $RepoRoot "apps\api"
Set-Location $ApiDir

$VenvPy = Join-Path $ApiDir ".venv\Scripts\python.exe"
$VenvPytest = Join-Path $ApiDir ".venv\Scripts\pytest.exe"
$VenvRuff = Join-Path $ApiDir ".venv\Scripts\ruff.exe"

if (-not (Test-Path $VenvPy)) {
    Write-Host "[verify-backend] venv missing — bootstrapping with uv sync --frozen"
    & uv sync --frozen --no-install-project
}

# Sanity import check — fails loudly if a top-level runtime dep is
# missing. Catches the ModuleNotFoundError: slowapi symptom that bit
# Codex on 2026-04-22.
& $VenvPy -c @'
import sys
import importlib.util
# Keep aligned with apps/api/pyproject.toml dependencies. Module names
# differ from distribution names (fpdf2 -> fpdf, python-docx -> docx,
# google-cloud-storage -> google.cloud.storage, PyJWT -> jwt).
required = [
    "fastapi", "sqlalchemy", "alembic", "pydantic", "pydantic_settings",
    "slowapi", "httpx", "voyageai", "anthropic", "fpdf", "docx",
    "google.cloud.storage", "jwt", "pdfminer", "PIL", "fastembed",
    "boto3", "clamd",
]
missing = [m for m in required if importlib.util.find_spec(m) is None]
if missing:
    print("[verify-backend] FATAL - missing runtime deps in venv:", missing, file=sys.stderr)
    print("[verify-backend] Fix: uv sync --frozen --no-install-project", file=sys.stderr)
    sys.exit(2)
print("[verify-backend] venv has all required runtime deps")
'@
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[verify-backend] running ruff"
& $VenvRuff check src tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[verify-backend] running pytest $args"
& $VenvPytest @args
exit $LASTEXITCODE
