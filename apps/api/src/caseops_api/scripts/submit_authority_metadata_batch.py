"""Submit exported authority metadata JSONL shards to OpenAI Batch.

This script is the paid boundary. Use ``--dry-run`` to inspect planned
submissions without uploading files or creating batch jobs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from caseops_api.core.settings import get_settings
from caseops_api.scripts.authority_metadata_batch import (
    OPENAI_BATCH_ENDPOINT,
    append_ledger_event,
)


def _load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _client():
    import openai  # type: ignore[import-not-found]

    settings = get_settings()
    api_key = settings.llm_api_key or settings.openai_api_key
    if not api_key:
        raise RuntimeError(
            "OpenAI API key required. Set CASEOPS_LLM_API_KEY or CASEOPS_OPENAI_API_KEY."
        )
    return openai.OpenAI(api_key=api_key)


def submit_manifest(*, manifest_path: Path, ledger_path: Path, dry_run: bool) -> dict[str, Any]:
    manifest = _load_manifest(manifest_path)
    endpoint = manifest.get("endpoint") or OPENAI_BATCH_ENDPOINT
    submitted: list[dict[str, Any]] = []
    client = None if dry_run else _client()

    for shard in manifest.get("shards", []):
        if shard.get("batch_id"):
            continue
        path = Path(shard["path"])
        if dry_run:
            submitted.append({
                "path": str(path),
                "count": shard.get("count", 0),
                "dry_run": True,
            })
            continue
        assert client is not None
        with path.open("rb") as fh:
            uploaded = client.files.create(file=fh, purpose="batch")
        batch = client.batches.create(
            input_file_id=uploaded.id,
            endpoint=endpoint,
            completion_window="24h",
            metadata={
                "caseops_job": "authority_metadata",
                "manifest": manifest_path.name,
                "shard": path.name,
            },
        )
        shard["file_id"] = uploaded.id
        shard["batch_id"] = batch.id
        shard["status"] = getattr(batch, "status", "validating")
        submitted.append({
            "path": str(path),
            "file_id": uploaded.id,
            "batch_id": batch.id,
            "status": shard["status"],
            "count": shard.get("count", 0),
        })
        append_ledger_event(
            ledger_path,
            {
                "event": "submitted",
                "status": "submitted",
                "manifest_path": str(manifest_path),
                "path": str(path),
                "file_id": uploaded.id,
                "batch_id": batch.id,
                "custom_ids": shard.get("custom_ids", []),
            },
        )

    if not dry_run:
        _save_manifest(manifest_path, manifest)
    return {"dry_run": dry_run, "submitted": submitted}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="caseops-submit-authority-metadata-batch")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    ledger = args.ledger or args.manifest.with_name("ledger.jsonl")
    result = submit_manifest(manifest_path=args.manifest, ledger_path=ledger, dry_run=args.dry_run)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

