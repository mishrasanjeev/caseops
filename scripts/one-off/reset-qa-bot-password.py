"""One-off: reset the CaseOps QA Bot password.

Why: the QA Bot password was held only in the operator's password
manager. Using it from the workstation requires manual paste each
session, which blocks autonomous test runs. Move the source of truth
to Secret Manager (caseops-qa-password) so any operator + any
automation can fetch it via:

    gcloud secrets versions access latest --secret=caseops-qa-password

This script:
  1. Generates a 32-byte URL-safe random password.
  2. Hashes it via apps/api/src/caseops_api/core/security.hash_password
     (same scrypt parameters the auth flow uses to verify).
  3. UPDATEs users SET password_hash = <hash> WHERE email = qa-bot@caseops.ai.
  4. Writes the plaintext to Secret Manager as a new version.

Run only against an instance you own (the QA workspace).

Usage:
    # On caseops-ingest-vm (cloud-sql-proxy already on :5432):
    cd ~/caseops/apps/api
    /home/mishra_sanjeev_gmail_com/.local/bin/uv run --no-sync \
        python /tmp/reset-qa-bot-password.py
"""
from __future__ import annotations

import os
import secrets
import subprocess
import sys

# Make the apps/api source importable when run from the VM.
sys.path.insert(0, "/home/mishra_sanjeev_gmail_com/caseops/apps/api/src")

from sqlalchemy import create_engine, text  # noqa: E402

from caseops_api.core.security import hash_password  # noqa: E402
from caseops_api.core.settings import get_settings  # noqa: E402

QA_EMAIL = "qa-bot@caseops.ai"
SECRET_NAME = "caseops-qa-password"
PROJECT = "perfect-period-305406"


def main() -> int:
    new_password = secrets.token_urlsafe(32)
    new_hash = hash_password(new_password)

    settings = get_settings()
    sync_url = settings.database_url.replace("postgresql+asyncpg", "postgresql+psycopg")
    engine = create_engine(sync_url, future=True)

    with engine.begin() as conn:
        result = conn.execute(
            text("UPDATE users SET password_hash = :h WHERE email = :e RETURNING id"),
            {"h": new_hash, "e": QA_EMAIL},
        )
        rows = result.all()

    if not rows:
        print(f"ERROR: no user with email {QA_EMAIL}", file=sys.stderr)
        return 1

    user_id = rows[0][0]
    print(f"updated user_id={user_id} email={QA_EMAIL}")

    # Push the plaintext to Secret Manager. We use stdin so the password
    # never lands in shell history / proc args.
    proc = subprocess.run(
        [
            "gcloud", "secrets", "versions", "add", SECRET_NAME,
            "--data-file=-", "--project", PROJECT,
        ],
        input=new_password.encode("utf-8"),
        capture_output=True,
    )
    if proc.returncode != 0:
        # Try creating the secret if it doesn't exist yet.
        if b"NOT_FOUND" in proc.stderr or b"does not exist" in proc.stderr:
            create = subprocess.run(
                [
                    "gcloud", "secrets", "create", SECRET_NAME,
                    "--replication-policy=automatic", "--project", PROJECT,
                ],
                capture_output=True,
            )
            if create.returncode != 0:
                print("ERROR creating secret:", create.stderr.decode(), file=sys.stderr)
                return 2
            proc = subprocess.run(
                [
                    "gcloud", "secrets", "versions", "add", SECRET_NAME,
                    "--data-file=-", "--project", PROJECT,
                ],
                input=new_password.encode("utf-8"),
                capture_output=True,
            )
            if proc.returncode != 0:
                print("ERROR pushing secret:", proc.stderr.decode(), file=sys.stderr)
                return 3
        else:
            print("ERROR pushing secret:", proc.stderr.decode(), file=sys.stderr)
            return 4

    print("Credential latest version pushed")
    print(
        "Fetch the secret from Secret Manager using the documented "
        "caseops-qa-password runbook."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
