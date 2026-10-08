"""Regression contract for the 2026-10-08 post-rebuild stale-source incident."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import Client, IpDocketRecord, Matter, PrivateIndexProjection
from caseops_api.db.session import get_session_factory
from caseops_api.scripts import private_projection_integrity
from caseops_api.services import private_retrieval, private_retrieval_jobs
from caseops_api.services.private_retrieval_jobs import (
    inspect_private_index_integrity,
    rebuild_private_index,
)
from tests.test_auth_company import bootstrap_company
from tests.test_private_retrieval_workflow import _context


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def source_client(request: pytest.FixtureRequest) -> TestClient:
    fixture = "isolated_postgres_client" if request.param == "postgres" else "client"
    return request.getfixturevalue(fixture)


def _source(source_type: str, company_id: str, value: str):
    if source_type == "client":
        return Client(company_id=company_id, name=value, is_active=True)
    if source_type == "matter":
        return Matter(
            company_id=company_id,
            matter_code="WHITESPACE-REBUILD",
            title="Whitespace regression",
            description=value,
            practice_area="Civil",
            forum_level="high_court",
            status="intake",
            is_active=True,
        )
    return IpDocketRecord(
        company_id=company_id,
        title=value,
        record_type="trademark",
        status="draft",
        is_active=True,
    )


@pytest.mark.parametrize("source_type", ["client", "matter", "ip_docket"])
@pytest.mark.parametrize(
    "value",
    ["Alpha Beta", "Alpha  Beta", "Alpha\r\nBeta", "Alpha\tBeta", "Alpha\u00a0Beta"],
    ids=["plain-control", "double-space", "multiline", "tab", "nbsp"],
)
def test_quiescent_rebuild_keeps_core_source_current(
    source_client: TestClient, source_type: str, value: str
) -> None:
    bootstrap = bootstrap_company(source_client)
    company_id = str(bootstrap["company"]["id"])
    context = _context(company_id, str(bootstrap["membership"]["id"]))
    with get_session_factory()() as session:
        source = _source(source_type, company_id, value)
        session.add(source)
        session.commit()
        source_id = source.id
        source_model = type(source)

    # Inspect both activations with fresh sessions and no intervening source writer.
    observations = []
    generations = []
    for _attempt in range(2):
        with get_session_factory()() as session:
            summary = rebuild_private_index(session, company_id=company_id, activate=True)
            assert summary.activated
            generations.append(summary.generation_id)
        with get_session_factory()() as session:
            report = inspect_private_index_integrity(session, company_id=company_id)
            projection = session.scalars(
                select(PrivateIndexProjection).where(
                    PrivateIndexProjection.company_id == company_id,
                    PrivateIndexProjection.generation_id == summary.generation_id,
                    PrivateIndexProjection.source_type == source_type,
                    PrivateIndexProjection.source_id == source_id,
                    PrivateIndexProjection.is_tombstoned.is_(False),
                )
            ).one()
            source = session.get(source_model, source_id)
            assert source is not None
            canonical = private_retrieval.private_source_projection_text(source)
            raw_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            normalized_hash = hashlib.sha256(" ".join(canonical.split()).encode()).hexdigest()
            current_ids = private_retrieval._source_versions_still_current(
                session, context=context, projections=[projection]
            )
            assert report.generation_manifest_matches
            assert report.pending_event_count == report.failed_event_count == 0
            assert report.orphan_scope_count == report.unsafe_tombstone_count == 0
            assert projection.source_version == private_retrieval.private_source_version(source)
            assert projection.content_sha256 == normalized_hash
            observations.append(
                {
                    "blockers": report.blockers,
                    "stale_source_count": report.stale_source_count,
                    "retrieval_current": projection.id in current_ids,
                    "raw_hash_matches_stored": raw_hash == projection.content_sha256,
                }
            )

    assert generations[0] != generations[1]
    assert observations == [
        {
            "blockers": (),
            "stale_source_count": 0,
            "retrieval_current": True,
            "raw_hash_matches_stored": True,
        }
    ] * 2


@pytest.mark.parametrize("source_type", ["client", "matter", "ip_docket"])
def test_substantive_core_source_change_stays_fail_closed(
    source_client: TestClient, source_type: str
) -> None:
    bootstrap = bootstrap_company(source_client)
    company_id = str(bootstrap["company"]["id"])
    context = _context(company_id, str(bootstrap["membership"]["id"]))
    with get_session_factory()() as session:
        source = _source(source_type, company_id, "Alpha Beta")
        session.add(source)
        session.commit()
        source_id = source.id
        source_model = type(source)
        summary = rebuild_private_index(session, company_id=company_id, activate=True)

    # Simulate a missed source event: currentness must reject changed content itself.
    with get_session_factory()() as session:
        source = session.get(source_model, source_id)
        assert source is not None
        field = {"client": "name", "matter": "description", "ip_docket": "title"}[source_type]
        setattr(source, field, "Changed substantive content")
        session.commit()

    with get_session_factory()() as session:
        report = inspect_private_index_integrity(session, company_id=company_id)
        projection = session.scalars(
            select(PrivateIndexProjection).where(
                PrivateIndexProjection.company_id == company_id,
                PrivateIndexProjection.generation_id == summary.generation_id,
                PrivateIndexProjection.source_type == source_type,
                PrivateIndexProjection.source_id == source_id,
            )
        ).one()
        assert report.blockers == ("stale_or_ineligible_sources",)
        assert report.stale_source_count == 1
        assert private_retrieval._source_versions_still_current(
            session, context=context, projections=[projection]
        ) == set()


@pytest.mark.parametrize("source_type", ["client", "matter", "ip_docket"])
@pytest.mark.parametrize("legacy_kind", ["raw-hash", "timestamp"])
def test_legacy_versions_reuse_vectors_without_rewriting_saved_or_retired_evidence(
    source_client: TestClient, source_type: str, legacy_kind: str
) -> None:
    bootstrap = bootstrap_company(source_client)
    company_id = str(bootstrap["company"]["id"])
    context = _context(company_id, str(bootstrap["membership"]["id"]))
    value = "Alpha  \r\nBeta"
    with get_session_factory()() as session:
        source = _source(source_type, company_id, value)
        session.add(source)
        session.commit()
        source_id = source.id
        canonical_version = private_retrieval.private_source_version(source)
        canonical = private_retrieval.private_source_projection_text(source)
        # These fixtures contain the source phrase exactly once. Restore the old
        # raw-text version format without rewriting any canonical source fields.
        assert canonical.count("Alpha Beta") == 1
        raw_text = canonical.replace("Alpha Beta", value)
        raw_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        assert raw_hash != hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        legacy_version = (
            canonical_version.rsplit(":", 1)[0] + ":" + raw_hash
            if legacy_kind == "raw-hash"
            else "1:2026-08-31T19:12:11.136017+00:00"
        )
        initial = rebuild_private_index(session, company_id=company_id, activate=True)
        projection = session.scalars(
            select(PrivateIndexProjection).where(
                PrivateIndexProjection.generation_id == initial.generation_id,
                PrivateIndexProjection.source_id == source_id,
            )
        ).one()
        projection.source_version = legacy_version
        projection.embedding_json = "[0.25,0.75]"
        projection.embedding_dimensions = 2
        projection.embedding_model = "retained-test-vector"
        projection.embedding_version = "mock:2"
        session.commit()
        session.refresh(projection)
        projection_id = projection.id
        retained = {
            column.name: getattr(projection, column.name)
            for column in PrivateIndexProjection.__table__.columns
        }
        saved = private_retrieval.capture_private_saved_source_manifest(
            session, context=context, sources=((source_type, source_id),)
        )
        assert saved[0]["source_version"] == legacy_version
        frozen_saved = json.dumps(saved, sort_keys=True)
        assert private_retrieval.private_saved_source_manifest_is_current(
            session, context=context, manifest=saved
        )

        # Reuse must copy only vectors and their metadata, even when the incoming
        # payload needs whitespace normalization and carries a different version.
        payload = private_retrieval.PrivateProjectionInput(
            source_type=source_type,
            source_id=source_id,
            source_version=canonical_version,
            chunk_ordinal=0,
            content=raw_text,
            label="Current label",
            source_state="approved",
            scopes=(private_retrieval.ProjectionScopeInput(source_type, source_id, 7),),
        )
        reused = private_retrieval_jobs._reuse_current_embeddings(
            session, company_id=company_id, generation_id=initial.generation_id,
            payloads=[payload], limit=10,
        )
        assert reused == [replace(
            payload, embedding=(0.25, 0.75), embedding_model="retained-test-vector",
            embedding_version="mock:2",
        )]

    with get_session_factory()() as session:
        rebuilt = rebuild_private_index(session, company_id=company_id, activate=True)
        assert rebuilt.provider_batch_count == rebuilt.provider_text_count == 0
        current = session.scalars(
            select(PrivateIndexProjection).where(
                PrivateIndexProjection.generation_id == rebuilt.generation_id,
                PrivateIndexProjection.source_id == source_id,
            )
        ).one()
        assert current.source_version == canonical_version != legacy_version
        assert current.embedding_json == "[0.25,0.75]"
        assert current.embedding_model == "retained-test-vector"
        assert current.embedding_version == "mock:2"
        assert current.embedding_dimensions == 2
        old = session.get(PrivateIndexProjection, projection_id)
        assert old is not None
        assert {
            column.name: getattr(old, column.name)
            for column in PrivateIndexProjection.__table__.columns
        } == retained
        assert json.dumps(saved, sort_keys=True) == frozen_saved
        assert not private_retrieval.private_saved_source_manifest_is_current(
            session, context=context, manifest=saved
        )
        assert not inspect_private_index_integrity(session, company_id=company_id).blockers
        current_manifest = private_retrieval.capture_private_saved_source_manifest(
            session, context=context, sources=((source_type, source_id),)
        )

    with get_session_factory()() as session:
        rebuild_private_index(session, company_id=company_id, activate=True)
        assert private_retrieval.private_saved_source_manifest_is_current(
            session, context=context, manifest=current_manifest
        )
        assert not private_retrieval.private_saved_source_manifest_is_current(
            session, context=context, manifest=saved
        )


@pytest.mark.parametrize("event_type", ["source_changed", "access_changed", "tombstoned"])
def test_whitespace_equivalence_never_reauthorizes_event_invalidated_saved_sources(
    source_client: TestClient, event_type: str
) -> None:
    bootstrap = bootstrap_company(source_client)
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    context = _context(company_id, membership_id)
    with get_session_factory()() as session:
        source = _source("matter", company_id, "Alpha \n Beta")
        session.add(source)
        session.commit()
        source_id = source.id
        rebuild_private_index(session, company_id=company_id, activate=True)
        saved = private_retrieval.capture_private_saved_source_manifest(
            session, context=context, sources=(("matter", source_id),)
        )
        # Retire the saved generation first: tombstones on the active generation
        # cannot by themselves prove the old saved proof stays rejected.
        rebuild_private_index(session, company_id=company_id, activate=True)
        assert private_retrieval.private_saved_source_manifest_is_current(
            session, context=context, manifest=saved
        )
        private_retrieval.propagate_private_projection_change(
            session, company_id=company_id, actor_membership_id=membership_id,
            idempotency_key=f"whitespace-event-{event_type}", event_type=event_type,
            target_type="matter", target_id=source_id, target_version=None,
            reason_code="whitespace_regression",
        )
        session.commit()
        assert not private_retrieval.private_saved_source_manifest_is_current(
            session, context=context, manifest=saved
        )
    with get_session_factory()() as session:
        rebuild_private_index(session, company_id=company_id, activate=True)
        assert not private_retrieval.private_saved_source_manifest_is_current(
            session, context=context, manifest=saved
        )
        assert not inspect_private_index_integrity(session, company_id=company_id).blockers


@pytest.mark.parametrize("tenant_count", [1, 6])
def test_maintenance_repairs_whitespace_once_per_tenant_and_respects_global_budget(
    source_client: TestClient, tenant_count: int
) -> None:
    companies = []
    for index in range(tenant_count):
        response = source_client.post(
            "/api/bootstrap/company",
            json={
                "company_name": f"Whitespace maintenance {index}",
                "company_slug": f"whitespace-maintenance-{index}",
                "company_type": "law_firm",
                "owner_full_name": "Maintenance Owner",
                "owner_email": f"whitespace-maintenance-{index}@example.com",
                "owner_password": "WhitespaceMaintenance2026!",
            },
        )
        assert response.status_code == 200, response.text
        bootstrap = response.json()
        company_id = str(bootstrap["company"]["id"])
        companies.append(company_id)
        with get_session_factory()() as session:
            sources = [
                _source(source_type, company_id, "Before repair")
                for source_type in ("client", "matter", "ip_docket")
            ]
            session.add_all(sources)
            session.commit()
            rebuild_private_index(session, company_id=company_id, activate=True)
            for source_type, field, source in zip(
                ("client", "matter", "ip_docket"), ("name", "description", "title"),
                sources, strict=True,
            ):
                setattr(source, field, "Alpha  \nBeta\tapproved")
                private_retrieval.propagate_private_projection_change(
                    session, company_id=company_id,
                    actor_membership_id=str(bootstrap["membership"]["id"]),
                    idempotency_key=f"maintenance-whitespace-{source_type}",
                    event_type="source_changed", target_type=source_type,
                    target_id=source.id,
                    target_version=private_retrieval.private_source_version(source),
                    reason_code="whitespace_regression",
                )
            session.commit()
            assert inspect_private_index_integrity(session, company_id=company_id).blockers

    capped = private_projection_integrity._maintain(
        max_companies=50, max_rebuilds=0, event_lag_slo_seconds=300,
    )
    assert capped["release_blocked"] is True
    assert capped["rebuild_count"] == 0
    assert all(row["blockers_after"] for row in capped["companies"])

    first = private_projection_integrity._maintain(
        max_companies=50, max_rebuilds=5, event_lag_slo_seconds=300,
    )
    assert first["candidate_company_count"] == tenant_count
    assert first["candidate_scan_truncated"] is False
    assert first["rebuild_count"] == min(tenant_count, 5)
    assert first["release_blocked"] is (tenant_count > 5)
    rebuilt = [row["company_id"] for row in first["companies"] if row["rebuilt"]]
    assert rebuilt == sorted(companies)[:5]
    assert all(not row["blockers_after"] for row in first["companies"] if row["rebuilt"])

    second = private_projection_integrity._maintain(
        max_companies=50, max_rebuilds=5, event_lag_slo_seconds=300,
    )
    assert second["release_blocked"] is False
    assert second["rebuild_count"] == max(tenant_count - 5, 0)
    for row in second["companies"]:
        assert row["blockers_after"] == []
        assert row["repair_deferred"] is False
        assert row["pending_event_count_after"] == row["failed_event_count_after"] == 0
        assert row["oldest_repair_lag_seconds_after"] is None

    clean = private_projection_integrity._maintain(
        max_companies=50, max_rebuilds=5, event_lag_slo_seconds=300,
    )
    assert clean["release_blocked"] is False
    assert clean["rebuild_count"] == 0
    assert all(not row["blockers_after"] and not row["rebuilt"] for row in clean["companies"])
