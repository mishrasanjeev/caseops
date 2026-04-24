"""Backend venv sanity check — invoked by verify-backend.{sh,ps1}.

Asserts that every top-level runtime dependency declared in
``apps/api/pyproject.toml`` is importable from the active Python.
Catches the partial-uv-sync class of failure (Codex 2026-04-22
``ModuleNotFoundError: slowapi``) before pytest collection runs.

Module names differ from distribution names: fpdf2 -> fpdf,
python-docx -> docx, google-cloud-storage -> google.cloud.storage,
PyJWT -> jwt, etc. Keep this list aligned with pyproject.
"""
from __future__ import annotations

import importlib.util
import sys


REQUIRED = [
    "fastapi",
    "sqlalchemy",
    "alembic",
    "pydantic",
    "pydantic_settings",
    "slowapi",
    "httpx",
    "voyageai",
    "anthropic",
    "fpdf",
    "docx",
    "google.cloud.storage",
    "jwt",
    "pdfminer",
    "PIL",
    "fastembed",
    "boto3",
    "clamd",
    "cryptography",
]


def main() -> int:
    missing = [m for m in REQUIRED if importlib.util.find_spec(m) is None]
    if missing:
        print(
            "[verify-backend] FATAL - missing runtime deps in venv:",
            missing,
            file=sys.stderr,
        )
        print(
            "[verify-backend] Fix: uv sync --frozen --no-install-project",
            file=sys.stderr,
        )
        return 2
    print("[verify-backend] venv has all required runtime deps")
    return 0


if __name__ == "__main__":
    sys.exit(main())
