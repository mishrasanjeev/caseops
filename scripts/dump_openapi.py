"""Dump the FastAPI app's OpenAPI schema to stdout (or to a file path).

Used by the OpenAPI-client-drift CI gate (P1-010 / QG-API-012). Avoids
spinning up uvicorn — `app.openapi()` is the same source-of-truth
the running server uses, but available without a network port.

Usage:
    python scripts/dump_openapi.py                    # stdout
    python scripts/dump_openapi.py path/to/file.json  # file
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api" / "src"))
    from caseops_api.main import app

    schema = app.openapi()
    payload = json.dumps(schema, indent=2, sort_keys=True)
    if len(sys.argv) >= 2:
        Path(sys.argv[1]).write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
