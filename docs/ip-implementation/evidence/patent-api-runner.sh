#!/usr/bin/env bash
set -euo pipefail
mkdir -p /candidate
tar -C /candidate -xf "$SOURCE_ARCHIVE"
sha256sum "$SOURCE_ARCHIVE" > "/output/api-source-${RUN_LABEL}.sha256"
cd /candidate/apps/api
export PYTHONPATH=/candidate/apps/api/src
python -m alembic upgrade head > "/output/api-migrate-${RUN_LABEL}.log" 2>&1
exec python -m uvicorn caseops_api.main:app --host 127.0.0.1 --port 8000 --header 'Connection: close'
