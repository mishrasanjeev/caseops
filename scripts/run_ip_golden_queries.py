from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib import error, request


ALLOWED_MODES = {
    "keyword",
    "contextual",
    "exact_citation",
    "party",
    "court",
    "judge",
    "act_section",
}


def _validate(rows: object, *, require_approved: bool) -> list[dict]:
    assert isinstance(rows, list) and rows, "Fixture file must contain a non-empty list."
    ids: set[str] = set()
    approved_count = 0
    for row in rows:
        assert isinstance(row, dict)
        assert row["id"].startswith("IP-GOLDEN-")
        assert row["id"] not in ids
        assert len(row["query"].strip()) >= 8
        assert row["expected_terms"]
        assert row["mode"] in ALLOWED_MODES
        assert row["court_scope"].strip()
        assert row["practice_area"].strip()
        assert int(row["minimum_results"]) >= 1
        approval = row.get("approval")
        assert isinstance(approval, dict)
        assert approval.get("status") in {"pending_lawyer_review", "approved"}
        if approval["status"] == "approved":
            assert approval.get("approved_by")
            assert approval.get("approved_at")
            approved_count += 1
        ids.add(row["id"])
    if require_approved:
        assert approved_count == len(rows), (
            f"Lawyer approval is required: {approved_count}/{len(rows)} fixtures approved."
        )
    return rows


def _execute(base_url: str, token: str, rows: list[dict], timeout: float) -> list[dict]:
    results: list[dict] = []
    for row in rows:
        payload = json.dumps(
            {
                "query": row["query"],
                "mode": row["mode"],
                "limit": max(10, int(row["minimum_results"])),
                "language": row.get("language", "en"),
                "forum_level": row.get("forum_level"),
                "court_name": row.get("court_name"),
                "document_type": row.get("document_type"),
            }
        ).encode("utf-8")
        http_request = request.Request(
            f"{base_url.rstrip('/')}/api/authorities/search",
            data=payload,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )
        try:
            with request.urlopen(http_request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise AssertionError(f"{row['id']} returned HTTP {exc.code}: {detail}") from exc
        assert body["outcome"] == "results_found", (
            f"{row['id']} returned typed outcome {body['outcome']!r}; "
            "zero results or an unhealthy index is not a golden-query pass."
        )
        returned = body["results"]
        assert len(returned) >= int(row["minimum_results"])
        searchable = " ".join(
            str(value).casefold()
            for item in returned
            for value in (
                item.get("title", ""),
                item.get("summary", ""),
                item.get("snippet", ""),
                " ".join(item.get("matched_terms", [])),
            )
        )
        missing_terms = [
            term for term in row["expected_terms"] if term.casefold() not in searchable
        ]
        assert not missing_terms, f"{row['id']} missing expected terms: {missing_terms}"
        results.append(
            {
                "id": row["id"],
                "outcome": body["outcome"],
                "result_count": len(returned),
                "index_state": body["corpus_coverage"]["index_state"],
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate deterministic IP research golden-query fixtures."
    )
    parser.add_argument(
        "--fixtures",
        default=str(
            Path(__file__).resolve().parents[1]
            / "apps/api/tests/fixtures/research/ip_golden_queries.json"
        ),
    )
    parser.add_argument("--base-url", help="Execute fixtures against this CaseOps API.")
    parser.add_argument(
        "--token-env",
        default="CASEOPS_GOLDEN_QUERY_TOKEN",
        help="Environment variable containing an access token; never printed.",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--require-approved", action="store_true")
    args = parser.parse_args()
    path = Path(args.fixtures)
    rows = _validate(
        json.loads(path.read_text(encoding="utf-8")),
        require_approved=args.require_approved,
    )
    execution = None
    if args.base_url:
        token = os.environ.get(args.token_env, "").strip()
        assert token, f"Set {args.token_env} before live golden-query execution."
        execution = _execute(args.base_url, token, rows, args.timeout)
    print(
        json.dumps(
            {
                "result": "pass",
                "fixture_count": len(rows),
                "approved_count": sum(
                    row["approval"]["status"] == "approved" for row in rows
                ),
                "execution": execution,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
