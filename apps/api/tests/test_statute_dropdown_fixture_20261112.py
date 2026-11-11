"""Local dropdown fixtures retain their identity in a shared statute catalog."""

from __future__ import annotations

import ast
import io
import json
import re
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from caseops_api.core import settings as settings_module
from caseops_api.db import session as session_module
from caseops_api.db.models import Statute, StatuteSection
from tests.test_auth_company import auth_headers, bootstrap_company


ROOT = Path(__file__).resolve().parents[3]
ORIGINAL_IDS = [f"b5-layout-{index:02}" for index in range(40)]
DECOY_ID = "b5-layout-short-decoy"
CONTROL_ID = "independent-dropdown-control"


@pytest.fixture(scope="module")
def seed_source() -> str:
    source = (ROOT / "tests/e2e/support/statute-dropdown-fixture.ts").read_text(encoding="utf-8")
    scripts = re.findall(r"  const script = `\n(.*?)\n`;", source, re.DOTALL)
    assert len(scripts) == 1
    assert "${" not in scripts[0], "The Python fixture must be a literal, not interpolated code"
    ast.parse(scripts[0])
    return scripts[0]


def execute_seed(source, monkeypatch, settings, factory, *, legacy=False):
    program = ast.parse(source)
    if legacy:
        # Establish the pre-decoy catalog without creating then deleting rows.
        scopes = [node for node in program.body if isinstance(node, ast.With)]
        assert len(scopes) == 1
        loops = [node for node in scopes[0].body if isinstance(node, ast.For)]
        assert len(loops) == 1
        loop = loops[0]
        assert ast.dump(loop.iter) == ast.dump(ast.parse("range(41)", mode="eval").body)
        loop.iter.args[0].value = 40
        scopes[0].body = [loop, ast.parse("session.commit()").body[0]]
        ast.fix_missing_locations(program)
    output = io.StringIO()
    with monkeypatch.context() as patch:
        patch.setattr(settings_module, "get_settings", lambda: settings)
        patch.setattr(session_module, "get_session_factory", lambda: factory)
        with redirect_stdout(output):
            exec(compile(program, "statute-dropdown-fixture.ts:python", "exec"), {})
    return json.loads(output.getvalue()) if output.getvalue().strip() else None


@pytest.fixture
def seed_local(client, seed_source, monkeypatch):
    settings = settings_module.get_settings()
    factory = session_module.get_session_factory()
    database = make_url(settings.database_url)
    assert database.get_backend_name() == "sqlite"
    monkeypatch.chdir(Path(database.database).resolve().parent)
    isolated = SimpleNamespace(env="e2e", database_url=settings.database_url)

    def seed(*, legacy=False):
        return execute_seed(seed_source, monkeypatch, isolated, factory, legacy=legacy)

    return seed


def snapshot(ids):
    with session_module.get_session_factory()() as session:
        return (
            list(session.execute(select(Statute.__table__).where(
                Statute.id.in_(ids),
            ).order_by(Statute.id)).mappings()),
            list(session.execute(select(StatuteSection.__table__).where(
                StatuteSection.statute_id.in_(ids),
            ).order_by(StatuteSection.id)).mappings()),
        )


@pytest.mark.parametrize("preexisting", ["empty", "legacy"])
def test_fresh_and_pre_decoy_seeds_preserve_original_counts_and_replay(seed_local, preexisting):
    assert snapshot(ORIGINAL_IDS) == ([], [])
    with session_module.get_session_factory()() as session:
        session.add(Statute(id=CONTROL_ID, short_name="Independent synthetic control",
                           long_name="Not owned by the dropdown seed", is_active=False))
        session.flush()
        session.add(StatuteSection(id="independent-dropdown-section", statute_id=CONTROL_ID,
                                  section_number="1", verification_status="unverified"))
        session.commit()
    control = snapshot([CONTROL_ID])
    if preexisting == "legacy":
        assert seed_local(legacy=True) is None
        assert len(snapshot(ORIGINAL_IDS)[0]) == 40
        assert snapshot([DECOY_ID]) == ([], [])
    prior = snapshot(ORIGINAL_IDS)
    fixture = seed_local()
    assert fixture["target"]["id"] == "b5-layout-39"
    assert fixture["target"]["catalog_section_count"] == 81
    assert fixture["target"]["section_count"] == 41
    assert fixture["competitor"]["id"] == DECOY_ID
    assert fixture["competitor"]["catalog_section_count"] == 83
    assert fixture["competitor"]["section_count"] == 42
    with session_module.get_session_factory()() as session:
        counts = dict(session.execute(select(
            StatuteSection.statute_id, func.count(StatuteSection.id),
        ).where(StatuteSection.statute_id.in_(ORIGINAL_IDS)).group_by(StatuteSection.statute_id)).all())
    assert counts == {key: 81 if key == "b5-layout-39" else 2 for key in ORIGINAL_IDS}
    if preexisting == "legacy":
        assert snapshot(ORIGINAL_IDS) == prior, "Do not repair retained fixture rows or their provenance"
    retained = snapshot([*ORIGINAL_IDS, DECOY_ID])
    assert seed_local() == fixture
    assert snapshot([*ORIGINAL_IDS, DECOY_ID]) == retained
    assert snapshot([CONTROL_ID]) == control, "Unrelated catalog records must remain untouched"


def test_api_proves_exact_long_fixture_despite_higher_ranked_short_competitor(client, seed_local):
    fixture = seed_local()
    headers = {
        **auth_headers(str(bootstrap_company(client)["access_token"])),
        "X-CaseOps-Automated-Test": "no-paid-providers",
    }
    response = client.get("/api/statutes/", headers=headers)
    assert response.status_code == 200, response.text
    catalog = response.json()["statutes"]
    ranked = sorted(
        (act for act in catalog if 0 < act["section_count"] < act["catalog_section_count"]),
        key=lambda act: act["catalog_section_count"], reverse=True,
    )
    ranked_ids = [act["id"] for act in ranked]
    assert ranked_ids.index(DECOY_ID) < ranked_ids.index(fixture["target"]["id"])
    assert ranked_ids[0] != fixture["target"]["id"]
    for expected in fixture.values():
        matches = [act for act in catalog if act["id"] == expected["id"]]
        assert len(matches) == 1
        assert {key: matches[0][key] for key in (
            "id", "short_name", "long_name", "section_count", "catalog_section_count",
        )} == {key: expected[key] for key in (
            "id", "short_name", "long_name", "section_count", "catalog_section_count",
        )}
        response = client.get(f"/api/statutes/{expected['id']}/sections", headers=headers)
        assert response.status_code == 200, response.text
        sections = response.json()
        assert sections["statute"]["id"] == expected["id"]
        assert sections["statute"]["long_name"] == expected["long_name"]
        assert sections["catalog_section_count"] == expected["catalog_section_count"]
        assert len(sections["catalog_sections"]) == expected["catalog_section_count"]
        assert sections["verified_section_count"] == expected["section_count"]
        assert len(sections["sections"]) == expected["section_count"]
        assert {row["statute_id"] for row in sections["sections"]} == {expected["id"]}
        assert {row["statute_id"] for row in sections["catalog_sections"]} == {expected["id"]}
        assert sections["sections"][-1]["id"] == expected["positive_section_id"]
        assert sections["sections"][-1]["verification_status"] == "verified_official"
        pending = next(row for row in sections["catalog_sections"] if row["id"] == expected["pending_section_id"])
        assert pending["selection_state"] == "verification_pending"
    assert len(fixture["target"]["long_name"]) > 100
    assert len(fixture["competitor"]["short_name"] + fixture["competitor"]["long_name"]) < 100


@pytest.mark.parametrize(("environment", "database", "docker"), [
    ("production", "sqlite+pysqlite:///{root}/fixture.db", ""),
    ("local", "sqlite+pysqlite:///{root}/fixture.db", ""),
    ("e2e", "sqlite+pysqlite:///:memory:", ""),
    ("e2e", "sqlite+pysqlite:///{outside}/fixture.db", ""),
    ("e2e", "postgresql+psycopg://fixture:fixture@remote.invalid/fixture", "1"),
    ("e2e", "postgresql+psycopg://fixture:fixture@127.0.0.1/fixture", ""),
])
def test_seed_rejects_non_e2e_or_unowned_storage_before_session(
    seed_source, monkeypatch, tmp_path, environment, database, docker,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CASEOPS_B5_FIXTURE_DOCKER", docker)
    settings = SimpleNamespace(
        env=environment,
        database_url=database.format(root=tmp_path.as_posix(), outside=tmp_path.parent.as_posix()),
    )
    calls = []

    def forbidden_session():
        calls.append("session")
        raise AssertionError("Rejected fixture storage must never open a session")

    with pytest.raises(RuntimeError, match="isolated e2e runtime|belong to this test checkout|remote database storage"):
        execute_seed(seed_source, monkeypatch, settings, forbidden_session)
    assert calls == []
