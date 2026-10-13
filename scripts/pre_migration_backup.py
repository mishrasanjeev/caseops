#!/usr/bin/env python3
"""Create one exact-release SQL checkpoint; never retry an unknown creation."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from time import monotonic, sleep
from uuid import uuid4

import scheduler_inventory as inventory


class BackupError(RuntimeError):
    pass


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise BackupError("Backup timestamp is missing.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BackupError("Backup timestamp is invalid.") from exc
    if parsed.tzinfo is None:
        raise BackupError("Backup timestamp must include its time zone.")
    return parsed.astimezone(UTC)


def checkpoint(*, project: str, region: str, instance: str, release_sha: str,
               wait_seconds: int = 720) -> dict:
    if (
        not re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", project)
        or not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", instance)
        or not re.fullmatch(r"[a-z]+-[a-z]+[0-9]", region)
        or not re.fullmatch(r"[a-f0-9]{40}", release_sha)
        or isinstance(wait_seconds, bool) or not 1 <= wait_seconds <= 900
    ):
        raise BackupError("Invalid exact-release backup identity or deadline.")
    deadline = monotonic() + wait_seconds
    requested_at = datetime.now(UTC)
    description = f"caseops-pre-migration-{release_sha}-{uuid4().hex}"

    def emit(event: str, **fields) -> None:
        print(json.dumps({"event": event, "release_sha": release_sha,
                          "project": project, "instance": instance, **fields}), flush=True)

    def call(arguments: list[str], fields: str):
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise BackupError("Backup checkpoint deadline exceeded; migration remains blocked.")
        try:
            return inventory.run_gcloud(
                [*arguments, "--project", project, "--quiet", f"--format=json({fields})"],
                expect_json=True, timeout=min(60, remaining),
            )
        except (inventory.InventoryError, OSError):
            # CLI exceptions can contain raw credentials/errors. Keep only the
            # checkpoint identity and unknown-outcome recovery instruction.
            raise BackupError(
                f"Backup control-plane outcome unavailable; reconcile description {description}. "
                "Do not repeat creation blindly. Migration remains blocked."
            ) from None

    metadata = call(["sql", "instances", "describe", instance],
                    "name,region,state,connectionName,databaseVersion")
    if not isinstance(metadata, dict) or metadata != {
        "name": instance, "region": region, "state": "RUNNABLE",
        "connectionName": f"{project}:{region}:{instance}", "databaseVersion": "POSTGRES_17",
    }:
        raise BackupError("SQL instance identity/state does not match this release.")
    operations = call(["sql", "operations", "list", "--instance", instance, "--limit=1000"],
                      "name,status,targetId,targetProject")
    if not isinstance(operations, list) or len(operations) >= 1000:
        raise BackupError("SQL operation inventory is incomplete; migration remains blocked.")
    seen = set()
    for row in operations:
        if not isinstance(row, dict) or (
            not isinstance(row.get("name"), str)
            or not re.fullmatch(r"[a-z0-9-]{1,80}", row["name"])
            or row["name"] in seen or row.get("targetId") != instance
            or row.get("targetProject") != project
            or not isinstance(row.get("status"), str)
            or row["status"] not in {"PENDING", "RUNNING", "DONE"}
        ):
            raise BackupError("SQL operation inventory has invalid identities/status.")
        seen.add(row["name"])
    if any(row["status"] != "DONE" for row in operations):
        raise BackupError("SQL has unfinished or unverifiable operations; migration remains blocked.")
    emit("backup_requested", description=description, requested_at=requested_at.isoformat())
    operation = call(["sql", "backups", "create", "--instance", instance,
                      "--description", description, "--async"],
                     "name,status,operationType,targetId,targetProject,backupContext,error")
    if isinstance(operation, dict) and isinstance(operation.get("name"), str) and re.fullmatch(
        r"[a-z0-9-]{1,80}", operation["name"],
    ):
        status = operation.get("status")
        emit("backup_operation_observed", operation=operation["name"],
             status=status if isinstance(status, str)
             and status in {"PENDING", "RUNNING", "DONE"} else "unrecognized",
             identity_validated=False, description=description)

    def validate_operation(payload) -> str:
        if not isinstance(payload, dict) or (
            payload.get("targetId") != instance or payload.get("targetProject") != project
            or payload.get("operationType") != "BACKUP_VOLUME"
            or not isinstance(payload.get("name"), str)
            or not re.fullmatch(r"[a-z0-9-]{1,80}", payload["name"])
            or not isinstance(payload.get("status"), str)
            or payload["status"] not in {"PENDING", "RUNNING", "DONE"}
        ):
            raise BackupError("Backup operation identity/status is invalid; migration remains blocked.")
        if payload.get("error"):
            raise BackupError("Backup operation failed; migration remains blocked.")
        return payload["name"]

    operation_name = validate_operation(operation)
    emit("backup_operation", operation=operation_name, description=description)
    while operation["status"] != "DONE":
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise BackupError(f"Backup operation {operation_name} is pending; do not recreate it.")
        sleep(min(5, remaining))
        operation = call(["sql", "operations", "describe", operation_name],
                         "name,status,operationType,targetId,targetProject,backupContext,error")
        if validate_operation(operation) != operation_name:
            raise BackupError("Backup operation changed identity; migration remains blocked.")
    context = operation.get("backupContext") or {}
    backup_id = context.get("backupId") if isinstance(context, dict) else None
    if backup_id is None:
        raise BackupError(
            f"Completed operation {operation_name} has no backup ID. "
            "Reconcile that operation; migration remains blocked.",
        )
    if isinstance(backup_id, bool) or not re.fullmatch(r"[1-9][0-9]{0,19}", str(backup_id)):
        raise BackupError("Completed backup has no valid numeric ID; migration remains blocked.")
    backup = call(["sql", "backups", "describe", str(backup_id), "--instance", instance],
                  "id,instance,status,type,description,location,startTime,endTime")
    if not isinstance(backup, dict) or (
        str(backup.get("id")) != str(backup_id) or backup.get("instance") != instance
        or backup.get("description") != description or backup.get("type") != "ON_DEMAND"
        or backup.get("status") != "SUCCESSFUL" or not backup.get("location")
    ):
        raise BackupError("Backup readback does not certify this checkpoint; migration remains blocked.")
    started, completed = _timestamp(backup.get("startTime")), _timestamp(backup.get("endTime"))
    if not requested_at <= started <= completed <= datetime.now(UTC):
        raise BackupError("Backup timestamps do not bind to this invocation; migration remains blocked.")
    receipt = {"operation": operation_name, "backup_id": str(backup_id),
               "description": description, "location": backup["location"],
               "started_at": started.isoformat(), "completed_at": completed.isoformat()}
    emit("backup_completed", **receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("project", "region", "instance", "release-sha"):
        parser.add_argument(f"--{field}", required=True)
    parser.add_argument("--wait-seconds", type=int, default=720)
    args = parser.parse_args()
    try:
        checkpoint(**vars(args))
    except BackupError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
