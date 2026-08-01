from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate deterministic IP research golden-query fixtures."
    )
    parser.add_argument(
        "--fixtures",
        default="apps/api/tests/fixtures/research/ip_golden_queries.json",
    )
    args = parser.parse_args()
    path = Path(args.fixtures)
    rows = json.loads(path.read_text(encoding="utf-8"))
    ids: set[str] = set()
    for row in rows:
        assert row["id"].startswith("IP-GOLDEN-")
        assert row["id"] not in ids
        assert len(row["query"].strip()) >= 8
        assert row["expected_terms"]
        ids.add(row["id"])
    print(json.dumps({"result": "pass", "fixture_count": len(rows)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
