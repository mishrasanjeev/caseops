"""Monitor OpenAI Batch jobs for authority metadata extraction."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from caseops_api.core.settings import get_settings
from caseops_api.scripts.authority_metadata_batch import append_ledger_event


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if hasattr(value, "model_dump"):
        try:
            return _jsonable(value.model_dump(mode="json"))
        except TypeError:
            return _jsonable(value.model_dump())
    if hasattr(value, "dict"):
        return _jsonable(value.dict())
    if hasattr(value, "__dict__"):
        return {
            str(key): _jsonable(item)
            for key, item in vars(value).items()
            if not str(key).startswith("_")
        }
    return str(value)


def _client():
    import openai  # type: ignore[import-not-found]

    settings = get_settings()
    api_key = settings.llm_api_key or settings.openai_api_key
    if not api_key:
        raise RuntimeError(
            "OpenAI API key required. Set CASEOPS_LLM_API_KEY or CASEOPS_OPENAI_API_KEY."
        )
    return openai.OpenAI(api_key=api_key)


def _load_manifest(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"shards": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_manifest(path: Path | None, manifest: dict[str, Any]) -> None:
    if path is not None:
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _batch_ids(manifest: dict[str, Any], explicit: list[str]) -> list[str]:
    ids = list(explicit)
    for shard in manifest.get("shards", []):
        batch_id = shard.get("batch_id")
        if batch_id and batch_id not in ids:
            ids.append(batch_id)
    return ids


def _download_file(client: Any, file_id: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = client.files.content(file_id)
    if hasattr(content, "write_to_file"):
        content.write_to_file(output_path)
        return
    data = content.read() if hasattr(content, "read") else bytes(content)
    output_path.write_bytes(data)


def monitor_batches(
    *,
    manifest_path: Path | None,
    ledger_path: Path | None,
    batch_ids: list[str],
    output_dir: Path,
    download_completed: bool,
    dry_run: bool,
) -> dict[str, Any]:
    manifest = _load_manifest(manifest_path)
    ids = _batch_ids(manifest, batch_ids)
    if dry_run:
        return {"dry_run": True, "batch_ids": ids}
    client = _client()
    statuses: list[dict[str, Any]] = []
    for batch_id in ids:
        batch = client.batches.retrieve(batch_id)
        status = {
            "batch_id": batch_id,
            "status": getattr(batch, "status", None),
            "output_file_id": getattr(batch, "output_file_id", None),
            "error_file_id": getattr(batch, "error_file_id", None),
            "request_counts": _jsonable(getattr(batch, "request_counts", None)),
        }
        output_file_id = status["output_file_id"]
        if download_completed and status["status"] == "completed" and output_file_id:
            output_path = output_dir / f"{batch_id}.output.jsonl"
            _download_file(client, output_file_id, output_path)
            status["output_path"] = str(output_path)
        statuses.append(status)
        if ledger_path:
            append_ledger_event(
                ledger_path,
                {"event": "monitored", "status": str(status["status"]), **status},
            )
        for shard in manifest.get("shards", []):
            if shard.get("batch_id") == batch_id:
                shard["status"] = status["status"]
                if status.get("output_path"):
                    shard["output_path"] = status["output_path"]
                if output_file_id:
                    shard["output_file_id"] = output_file_id
    _save_manifest(manifest_path, manifest)
    return {"dry_run": False, "batches": statuses}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="caseops-monitor-authority-metadata-batch")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--batch-id", action="append", default=[])
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".tmp/authority-metadata-batch/results"),
    )
    parser.add_argument("--download-completed", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    result = monitor_batches(
        manifest_path=args.manifest,
        ledger_path=args.ledger,
        batch_ids=args.batch_id,
        output_dir=args.output_dir,
        download_completed=args.download_completed,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
