"""Generate UI fixtures through the canonical API DTO from pinned release content."""

import json
from pathlib import Path

from caseops_api.api.routes.statutes import StatuteSectionDetailResponse
from caseops_api.scripts.official_statute_release import load_release_bundle
from caseops_api.scripts.seed_statutes import SEED_PATH

ROOT = Path(__file__).resolve().parents[2]


def main():
    documents, sources = load_release_bundle()
    catalog = {row["id"]: row for row in json.loads(SEED_PATH.read_text())}
    fixtures = {}
    for act, number in [
        ("ndps-1985", "Schedule"),
        ("specific-relief-1963", "Schedule"),
        ("ipc-1860", "Section 302"),
        ("iea-1872", "Section 65B"),
    ]:
        source = sources[act, number]
        dto = StatuteSectionDetailResponse.model_validate(
            {
                "statute": {
                    **catalog[act],
                    "jurisdiction": "india",
                    "is_active": True,
                    "source_url": documents[act]["act_url"],
                },
                "section": {
                    **source,
                    "id": f"fixture-{act}-{number.replace(' ', '-')}",
                    "section_url": source["source_url"],
                    "source_version": 1,
                    "source_policy_json": source["source_policy"],
                    "parent_section_id": None,
                    "ordinal": 1,
                },
            }
        )
        fixtures[act] = dto.model_dump(mode="json")
    target = ROOT / "tests/fixtures/statutes/structured-schedule-api.json"
    target.write_text(json.dumps(fixtures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Generated {len(fixtures)} canonical source-backed API fixtures: {target}")


if __name__ == "__main__":
    main()
