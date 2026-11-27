"""Nov 27 workbook row 1: the canonical bench picker had nothing to offer.

No migration, seed job or route ever wrote a ``benches`` row, so the curator
"Canonical bench" dropdown was empty in every environment and no bench alias
could be created. The earlier IPLF-060B proofs inserted their own Bench rows,
which hid the gap. These tests use only the migrated, release-owned catalogue.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import Bench, BenchAlias, Court
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_recommendations import _create_company_user

_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20261127_0006_seed_official_court_benches.py"
)


def _seed_module():
    spec = importlib.util.spec_from_file_location("bench_seed_20261127", _MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Written out rather than derived from the migration or from the courts that
# happen to exist: a court whose rows are silently skipped must fail here.
RELEASE_BENCHES: frozenset[tuple[str, str]] = frozenset(
    {
        ("andhra-pradesh-hc", "Principal Seat"),
        ("bombay-hc", "Bench at Aurangabad"),
        ("bombay-hc", "Bench at Kolhapur"),
        ("bombay-hc", "Bench at Nagpur"),
        ("bombay-hc", "High Court of Bombay at Goa"),
        ("bombay-hc", "Principal Seat at Bombay"),
        ("chhattisgarh-hc", "Principal Seat"),
        ("delhi-hc", "Principal Seat at Delhi"),
        ("gujarat-hc", "Principal Seat"),
        ("himachal-hc", "Principal Seat"),
        ("jammu-kashmir-hc", "Jammu Wing"),
        ("jammu-kashmir-hc", "Ladakh Bench"),
        ("jammu-kashmir-hc", "Srinagar Wing"),
        ("jharkhand-hc", "Principal Seat"),
        ("karnataka-hc", "Bench at Dharwad"),
        ("karnataka-hc", "Bench at Kalburagi"),
        ("karnataka-hc", "Principal Seat at Bengaluru"),
        ("kerala-hc", "Principal Seat"),
        ("madhya-pradesh-hc", "Bench at Gwalior"),
        ("madhya-pradesh-hc", "Bench at Indore"),
        ("madhya-pradesh-hc", "Bench at Jabalpur"),
        ("madras-hc", "Bench at Madurai"),
        ("madras-hc", "Principal Seat"),
        ("manipur-hc", "Principal Seat"),
        ("meghalaya-hc", "Principal Seat"),
        ("orissa-hc", "Principal Seat"),
        ("patna-hc", "Principal Seat at Patna"),
        ("punjab-hc", "Principal Seat"),
        ("rajasthan-hc", "Bench at Jaipur"),
        ("rajasthan-hc", "Principal Seat at Jodhpur"),
        ("sikkim-hc", "Principal Seat"),
        ("telangana-hc", "Principal Seat at Hyderabad"),
        ("tripura-hc", "Principal Seat"),
        ("uttarakhand-hc", "Principal Seat"),
    }
)
# Every High Court the court migrations create has its seats catalogued; only
# the Supreme Court (not a bench catalogue) is left without a bench row.
COURTS_WITHOUT_RELEASE_BENCHES = frozenset({"supreme-court-india"})
_OFFICIAL_SOURCE_HOSTS = (
    "https://bombayhighcourt.gov.in/",
    "https://hcraj.nic.in/",
    "https://jkhighcourt.nic.in/",
    "https://hcservices.ecourts.gov.in/",
)


def _expected_release_benches() -> set[tuple[str, str]]:
    return set(RELEASE_BENCHES)


def test_migrated_database_holds_exactly_the_release_benches(client: TestClient) -> None:
    module = _seed_module()
    declared = {(court_id, name) for court_id, name, *_ in module.OFFICIAL_BENCHES}
    with get_session_factory()() as session:
        courts = set(session.scalars(select(Court.id)))
        stored = set(session.execute(select(Bench.court_id, Bench.name)).tuples())
    # No declared row may depend on a court the migrations never create.
    assert {court_id for court_id, _ in declared} <= courts
    assert declared == RELEASE_BENCHES
    assert stored == RELEASE_BENCHES
    assert courts - {court_id for court_id, _ in stored} == COURTS_WITHOUT_RELEASE_BENCHES
    # Allahabad, Calcutta and Gauhati have no court row in any migration, so
    # their benches are documented in the revision instead of seeded.
    assert not {court_id for court_id, _ in declared} & {
        "allahabad-hc",
        "calcutta-hc",
        "gauhati-hc",
    }


def test_upgrade_refuses_to_drop_benches_of_a_missing_court(client: TestClient) -> None:
    module = _seed_module()
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    engine = get_session_factory()().get_bind()
    module.OFFICIAL_BENCHES = (
        *module.OFFICIAL_BENCHES,
        ("not-a-catalogued-hc", "Bench at Nowhere", None, ("x", "https://x.gov.in/"), "x"),
    )
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        with pytest.raises(RuntimeError, match="not-a-catalogued-hc"):
            module.upgrade()
    with get_session_factory()() as session:
        assert set(session.execute(select(Bench.court_id, Bench.name)).tuples()) == set(
            RELEASE_BENCHES
        )


def _list(client: TestClient, headers: dict[str, str], **params: object) -> dict:
    response = client.get("/api/judge-mapping/catalog/benches", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_release_catalogue_offers_official_benches_without_a_fixture(client: TestClient) -> None:
    headers = auth_headers(str(bootstrap_company(client)["access_token"]))
    expected = _expected_release_benches()
    assert len(expected) == 34

    payload = _list(client, headers, limit=200)
    listed = {(row["court_id"], row["name"]) for row in payload["benches"]}
    assert listed == expected
    assert payload["total_count"] == len(expected)
    assert payload["has_more"] is False
    for row in payload["benches"]:
        assert row["court_name"] and row["court_short_name"]
        assert row["source_url"].startswith(_OFFICIAL_SOURCE_HOSTS)
        assert "retrieved 2026-11-2" in row["source_reference"]
    assert [court["id"] for court in payload["courts_without_benches"]] == [
        "supreme-court-india"
    ]
    assert payload["courts_without_benches_total"] == 1


def test_single_seat_court_offers_its_principal_seat_and_accepts_the_alias(
    client: TestClient,
) -> None:
    headers = auth_headers(str(bootstrap_company(client)["access_token"]))
    # The tester most likely searched a single-seat court such as Delhi.
    delhi = _list(client, headers, q="Delhi High Court", limit=200)
    assert [(row["court_id"], row["name"]) for row in delhi["benches"]] == [
        ("delhi-hc", "Principal Seat at Delhi")
    ]
    assert delhi["courts_without_benches"] == []
    seat = delhi["benches"][0]
    assert seat["source_url"] == "https://hcservices.ecourts.gov.in/hcservices/main.php"
    assert "'Principal Bench at Delhi' only" in seat["source_reference"]
    created = client.post(
        f"/api/judge-mapping/benches/{seat['id']}/aliases",
        headers=headers,
        json={
            "alias_text": "High Court of Delhi at New Delhi",
            "source": "manual_curator",
            "source_url": "https://delhihighcourt.nic.in/",
        },
    )
    assert created.status_code == 200, created.text
    with get_session_factory()() as session:
        alias = session.scalar(
            select(BenchAlias).where(BenchAlias.id == created.json()["id"])
        )
        assert alias is not None and alias.bench_id == seat["id"]

    # Courts with several seats list every one, principal seat included.
    for query, names in {
        "Madras": {"Principal Seat", "Bench at Madurai"},
        "Karnataka": {"Principal Seat at Bengaluru", "Bench at Dharwad", "Bench at Kalburagi"},
        "Madhya Pradesh": {"Bench at Jabalpur", "Bench at Indore", "Bench at Gwalior"},
    }.items():
        assert {row["name"] for row in _list(client, headers, q=query)["benches"]} == names


def test_a_searched_court_without_catalogued_benches_is_named(client: TestClient) -> None:
    headers = auth_headers(str(bootstrap_company(client)["access_token"]))
    # Production may hold manually seeded courts that no migration creates.
    with get_session_factory()() as session:
        session.add(
            Court(
                id="allahabad-hc",
                name="Allahabad High Court",
                short_name="Allahabad HC",
                forum_level="high_court",
            )
        )
        session.add(
            Court(
                id="bugs7-retired-hc",
                name="Bugs7 Retired Allahabad Court",
                short_name="Retired HC",
                forum_level="high_court",
                is_active=False,
            )
        )
        session.commit()
    allahabad = _list(client, headers, q="Allahabad", limit=200)
    assert allahabad["benches"] == [] and allahabad["total_count"] == 0
    # A retired court is withdrawn here exactly as its benches are.
    assert allahabad["courts_without_benches"] == [
        {"id": "allahabad-hc", "name": "Allahabad High Court", "short_name": "Allahabad HC"}
    ]
    assert allahabad["courts_without_benches_total"] == 1
    by_id = _list(client, headers, court_id="allahabad-hc")
    assert [court["id"] for court in by_id["courts_without_benches"]] == ["allahabad-hc"]
    # A court with catalogued benches is never reported as uncatalogued.
    bombay = _list(client, headers, q="Bombay")
    assert bombay["courts_without_benches"] == [] and bombay["total_count"] == 5
    # The bounded list states its exact total.
    capped = _list(client, headers, limit=1)
    assert len(capped["courts_without_benches"]) == 1
    assert capped["courts_without_benches_total"] == 2


def test_tester_search_matches_court_seat_or_bench_in_any_order(client: TestClient) -> None:
    headers = auth_headers(str(bootstrap_company(client)["access_token"]))
    bombay = {name for court, name in _expected_release_benches() if court == "bombay-hc"}

    # The tester types the court; no bench name contains "Bombay High Court".
    by_court = _list(client, headers, q="Bombay High Court", limit=200)
    assert {row["name"] for row in by_court["benches"]} == bombay
    assert {row["name"] for row in _list(client, headers, q="nagpur")["benches"]} == {
        "Bench at Nagpur"
    }
    assert [row["name"] for row in _list(client, headers, q="Bombay HC Nagpur")["benches"]] == [
        "Bench at Nagpur"
    ]
    assert [row["name"] for row in _list(client, headers, q="Jaipur")["benches"]] == [
        "Bench at Jaipur"
    ]
    # LIKE wildcards are literal text, not "match everything".
    assert _list(client, headers, q="%")["total_count"] == 0
    assert _list(client, headers, q="_")["total_count"] == 0
    none = _list(client, headers, q="No Such Bench Anywhere")
    assert none["benches"] == [] and none["total_count"] == 0


def test_capped_page_states_the_server_total(client: TestClient) -> None:
    headers = auth_headers(str(bootstrap_company(client)["access_token"]))
    total = len(_expected_release_benches())
    page = _list(client, headers, limit=3)
    assert page["returned_count"] == 3
    assert page["total_count"] == total
    assert page["has_more"] is True


def test_every_offered_bench_is_accepted_and_a_retired_court_is_withdrawn_from_both(
    client: TestClient,
) -> None:
    headers = auth_headers(str(bootstrap_company(client)["access_token"]))
    offered = _list(client, headers, limit=200)["benches"]
    assert offered
    run = uuid4().hex[:8]
    for index, bench in enumerate(offered):
        created = client.post(
            f"/api/judge-mapping/benches/{bench['id']}/aliases",
            headers=headers,
            json={
                "alias_text": f"Bugs7 alias {run} {index}",
                "source": "manual_curator",
                "source_url": bench["source_url"],
            },
        )
        assert created.status_code == 200, (bench["name"], created.text)
        assert created.json()["is_active"] is True

    # State changes after the picker offered the row: the court is retired.
    rajasthan = next(row for row in offered if row["court_id"] == "rajasthan-hc")
    with get_session_factory()() as session:
        session.get(Court, "rajasthan-hc").is_active = False
        session.commit()
    try:
        remaining = _list(client, headers, limit=200)
        assert all(row["court_id"] != "rajasthan-hc" for row in remaining["benches"])
        assert remaining["total_count"] == len(offered) - 2
        stale = client.post(
            f"/api/judge-mapping/benches/{rajasthan['id']}/aliases",
            headers=headers,
            json={"alias_text": f"Stale {run}", "source": "manual_curator"},
        )
        assert stale.status_code == 422, stale.text
        assert stale.json()["detail"] == "Canonical bench not found."
    finally:
        with get_session_factory()() as session:
            session.get(Court, "rajasthan-hc").is_active = True
            session.commit()

    unknown = client.post(
        f"/api/judge-mapping/benches/{uuid4()}/aliases",
        headers=headers,
        json={"alias_text": "Unknown bench", "source": "manual_curator"},
    )
    assert unknown.status_code == 422


def test_bench_catalogue_and_alias_writes_require_the_curator_capability(
    client: TestClient,
) -> None:
    owner = bootstrap_company(client)
    owner_token = str(owner["access_token"])
    _, member_token = _create_company_user(
        client,
        owner_token,
        company_slug=str(owner["company"]["slug"]),
        email="bench-member@example.com",
        role="member",
    )
    member = auth_headers(member_token)
    bench_id = _list(client, auth_headers(owner_token), limit=1)["benches"][0]["id"]
    listing = client.get("/api/judge-mapping/catalog/benches", headers=member)
    assert listing.status_code == 403, listing.text
    write = client.post(
        f"/api/judge-mapping/benches/{bench_id}/aliases",
        headers=member,
        json={"alias_text": "Member alias", "source": "manual_curator"},
    )
    assert write.status_code == 403, write.text
    with get_session_factory()() as session:
        assert (
            session.scalar(select(BenchAlias).where(BenchAlias.alias_text == "Member alias"))
            is None
        )


def test_judge_catalogue_names_the_court_and_searches_it(client: TestClient) -> None:
    headers = auth_headers(str(bootstrap_company(client)["access_token"]))
    with get_session_factory()() as session:
        court = Court(
            name=f"Bugs7 Judge Court {uuid4().hex[:6]}",
            short_name="Bugs7 JC",
            forum_level="high_court",
        )
        session.add(court)
        session.flush()
        from caseops_api.db.models import Judge

        session.add(Judge(court_id=court.id, full_name="Justice Bugs Seven"))
        session.commit()
        court_name = court.name
    by_court = client.get(
        "/api/judge-mapping/catalog/judges", headers=headers, params={"q": court_name}
    )
    assert by_court.status_code == 200, by_court.text
    judges = by_court.json()["judges"]
    assert [row["full_name"] for row in judges] == ["Justice Bugs Seven"]
    assert judges[0]["court_name"] == court_name
    assert judges[0]["court_short_name"] == "Bugs7 JC"
    assert by_court.json()["total_count"] == 1


def test_seed_is_idempotent_and_never_overwrites_a_reviewed_row(client: TestClient) -> None:
    module = _seed_module()
    with get_session_factory()() as session:
        before = {
            row.id: (row.name, row.source_reference) for row in session.scalars(select(Bench))
        }
        nagpur = session.scalar(
            select(Bench).where(Bench.court_id == "bombay-hc", Bench.name == "Bench at Nagpur")
        )
        assert nagpur is not None
        assert nagpur.id == module.bench_id("bombay-hc", "Bench at Nagpur")
        nagpur.source_reference = "Curator-reviewed reference"
        session.commit()

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    engine = get_session_factory()().get_bind()
    with engine.begin() as connection:
        ops = Operations(MigrationContext.configure(connection))
        module.op = ops
        module.upgrade()
    with get_session_factory()() as session:
        after = {row.id: (row.name, row.source_reference) for row in session.scalars(select(Bench))}
    assert set(after) == set(before)
    nagpur_id = module.bench_id("bombay-hc", "Bench at Nagpur")
    assert after[nagpur_id][1] == "Curator-reviewed reference"

    # Restore-forward: downgrade never deletes a bench that holds an alias.
    with get_session_factory()() as session:
        session.add(
            BenchAlias(
                bench_id=nagpur_id,
                alias_text="Nagpur Bench",
                alias_normalised="nagpur bench",
                source="manual_curator",
            )
        )
        session.commit()
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.downgrade()
    with get_session_factory()() as session:
        remaining = set(session.scalars(select(Bench.id)))
    assert remaining == {nagpur_id}
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
    with get_session_factory()() as session:
        assert set(session.scalars(select(Bench.id))) == set(before)
