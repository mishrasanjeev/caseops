"""Report catalogue-wide source gaps independently of a successful partial seed."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "apps/api/src/caseops_api/scripts/seed_data"
INVENTORY = ROOT / "docs/ip-implementation/catalogue-sources-2026-09-08.json"


def audit_catalogue() -> dict:
    catalogue = json.loads((DATA / "statutes.json").read_text(encoding="utf-8"))
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    documents = json.loads((DATA / "verified_statute_documents.json").read_text(encoding="utf-8"))["documents"]
    expected = {row["id"] for row in catalogue}
    inventoried = [row["statute_id"] for row in inventory["catalogue"]]
    if set(inventoried) != expected or len(inventoried) != len(expected):
        raise ValueError("Source inventory does not reconcile every existing catalogue Act")
    if any(not row["source_candidates"] for row in inventory["catalogue"]):
        raise ValueError("An existing catalogue Act has no identified source candidate")
    retained = {row["statute_id"] for row in documents}
    page_inventory_missing = sorted(
        row["statute_id"] for row in documents if row.get("non_provision_pages") is None
    )
    missing_documents = sorted(expected - retained)
    # This audit does not turn extraction into applicability or journey proof.
    # Additional source packs must acquire their own versioned admission contract.
    additional_pending = [row["key"] for row in inventory["additional_required_sources"]]
    return {
        "catalogue_act_count": len(expected),
        "inventoried_act_count": len(inventoried),
        "retained_release_document_count": len(documents),
        "missing_release_documents": missing_documents,
        "missing_whole_document_page_inventory": page_inventory_missing,
        "additional_source_packs_pending": additional_pending,
        "complete": not (missing_documents or page_inventory_missing or additional_pending),
        "scope": "Source inventory, not current-law, E2E or production certification",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    result = audit_catalogue()
    print(json.dumps(result, indent=2))
    if args.require_complete and not result["complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
