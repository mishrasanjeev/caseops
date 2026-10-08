from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from hashlib import sha256
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Client,
    CompanyMembership,
    IpDocketRecord,
    IpDocument,
    IpDocumentLink,
    IpDocumentTaxonomyEntry,
    IpDocumentVersion,
    MatterAccessGrant,
    PrivateProjectionEvent,
)
from caseops_api.schemas.ip_documents import (
    IpDocumentAddLinksRequest,
    IpDocumentLinkTarget,
    IpDocumentStateTransitionRequest,
)
from caseops_api.schemas.ip_lifecycle import IpLifecycleTransitionRequest
from caseops_api.schemas.ip_patents import (
    PatentDocumentSource,
    PatentFamilyCorrectionRequest,
    PatentFamilyCreateRequest,
)
from caseops_api.services.ip_document_workflow import (
    add_ip_document_links,
    get_ip_document,
    transition_ip_document_state,
)
from caseops_api.services.ip_lifecycle import transition_ip_docket_lifecycle
from caseops_api.services.ip_patent_families import (
    correct_patent_family,
    create_patent_family,
    get_patent_family,
)
from caseops_api.services.private_retrieval import (
    ensure_active_private_generation,
    lock_private_authority_writer,
)
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _ip_race_context,
    _seed_company,
    _seed_membership,
    _wait_for_postgres_lock_wait,
)

pytestmark = pytest.mark.postgres


def _seed_document_source(engine):
    with Session(engine) as session:
        company_id = _seed_company(session)
        actor_id = _seed_membership(session, company_id, role="admin")
        client = Client(company_id=company_id, name="Document lock client", client_type="corporate")
        session.add(client)
        session.commit()
        context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
        family = create_patent_family(
            session,
            context=context,
            payload=PatentFamilyCreateRequest(
                title="Document writer overlap disclosure",
                client_id=client.id,
                disclosure_date=date(2026, 10, 8),
                disclosure_narrative="Original immutable disclosure.",
            ),
            idempotency_key=str(uuid4()),
        )
        taxonomy = IpDocumentTaxonomyEntry(
            company_id=company_id,
            key="document-lock-evidence",
            label="Document lock evidence",
            updated_by_membership_id=actor_id,
        )
        target = IpDocketRecord(
            company_id=company_id,
            record_type="trademark",
            title="Additional authorized document target",
            status="draft",
            created_by_membership_id=actor_id,
        )
        session.add_all([taxonomy, target])
        session.flush()
        document = IpDocument(
            company_id=company_id,
            taxonomy_entry_id=taxonomy.id,
            title="Pinned inventor evidence",
            confidentiality="restricted",
            created_by_membership_id=actor_id,
        )
        session.add(document)
        session.flush()
        content = b"Immutable inventor evidence shared by correction and document writers."
        version = IpDocumentVersion(
            company_id=company_id,
            document_id=document.id,
            version=1,
            original_filename="inventor.txt",
            display_name="inventor.txt",
            storage_key=f"document-lock-test/{uuid4()}/inventor.txt",
            content_type="text/plain",
            size_bytes=len(content),
            sha256_hex=sha256(content).hexdigest(),
            uploaded_by_membership_id=actor_id,
        )
        session.add(version)
        session.flush()
        session.add(
            IpDocumentLink(
                company_id=company_id,
                document_id=document.id,
                target_type="docket",
                target_id=str(family.docket_id),
                docket_id=str(family.docket_id),
                created_by_membership_id=actor_id,
            )
        )
        # Exercise real epoch/event propagation, not its no-active-generation early return.
        ensure_active_private_generation(session, company_id=company_id)
        session.commit()
        return {
            "company_id": company_id,
            "actor_id": actor_id,
            "family": family,
            "document_id": document.id,
            "version_id": version.id,
            "target_id": target.id,
            "content_hash": version.sha256_hex,
        }


def _write_document(session, context, fixture, operation, *, expected_version=1):
    if operation == "links":
        return add_ip_document_links(
            session,
            context=context,
            document_id=fixture["document_id"],
            payload=IpDocumentAddLinksRequest(
                expected_current_version=expected_version,
                version_id=fixture["version_id"],
                links=[IpDocumentLinkTarget(target_type="docket", target_id=fixture["target_id"])],
            ),
        )
    assert operation == "state"
    return transition_ip_document_state(
        session,
        context=context,
        document_id=fixture["document_id"],
        version_number=1,
        payload=IpDocumentStateTransitionRequest(
            expected_current_version=expected_version,
            expected_state="draft",
            target_state="review",
        ),
    )


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("operation", ["links", "state"])
def test_document_writer_takes_company_before_source_locks_on_postgres(
    pg_engine, operation, autoflush
):
    fixture = _seed_document_source(pg_engine)
    company_id, actor_id = fixture["company_id"], fixture["actor_id"]
    family = fixture["family"]
    source = PatentDocumentSource(
        document_id=fixture["document_id"],
        document_version_id=fixture["version_id"],
        content_sha256=fixture["content_hash"],
    )
    application_name = f"ip-document-{operation}-{uuid4().hex[:12]}"

    def document_writer():
        with Session(pg_engine, autoflush=autoflush) as session:
            session.execute(text("SET LOCAL lock_timeout = '10s'"))
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": application_name},
            )
            context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
            return _write_document(session, context, fixture, operation)

    with ThreadPoolExecutor(max_workers=1) as pool, Session(pg_engine) as correction:
        context = _ip_race_context(correction, company_id=company_id, membership_id=actor_id)
        correction.execute(text("SET LOCAL lock_timeout = '2s'"))
        lock_private_authority_writer(correction, company_id=company_id)
        correction_pid = correction.scalar(text("SELECT pg_backend_pid()"))
        writer = pool.submit(document_writer)
        try:
            _wait_for_postgres_lock_wait(pg_engine, application_name=application_name)
            with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
                waiting = observer.execute(
                    text(
                        "SELECT query, pg_blocking_pids(pid) AS blockers FROM pg_stat_activity "
                        "WHERE application_name = :name AND wait_event_type = 'Lock'"
                    ),
                    {"name": application_name},
                ).mappings().one()
                assert "FROM companies" in waiting["query"]
                assert "FOR NO KEY UPDATE" in waiting["query"]
                assert correction_pid in waiting["blockers"]

            # Company remains held throughout these probes and the real correction.
            # A Company waiter owning either source row would invert this writer's order.
            with Session(pg_engine) as probe:
                for model, row_id in (
                    (IpDocument, fixture["document_id"]),
                    (IpDocumentVersion, fixture["version_id"]),
                ):
                    assert probe.scalar(
                        select(model.id).where(model.id == row_id).with_for_update(nowait=True)
                    ) == row_id
                probe.rollback()
                # Read-only document access must not acquire the tenant writer fence.
                probe.execute(text("SET LOCAL lock_timeout = '500ms'"))
                read_context = _ip_race_context(
                    probe, company_id=company_id, membership_id=actor_id
                )
                readable = get_ip_document(
                    probe, context=read_context, document_id=fixture["document_id"]
                )
                assert readable.current_version == 1
            corrected = correct_patent_family(
                correction,
                context=context,
                family_id=str(family.id),
                payload=PatentFamilyCorrectionRequest(
                    expected_version=family.version,
                    expected_lifecycle_version=family.lifecycle_version,
                    facts=family.facts.model_copy(update={"source": source}),
                    reason="Pin the source while a document mutation waits for tenant authority.",
                ),
            )
            assert corrected.version == family.version + 1
            assert corrected.facts.source == source
        finally:
            correction.rollback()
            # Surface worker exceptions even when a lock probe failed; never leave a live writer.
            result = writer.result(timeout=15)

    assert result.current_version == 1
    with Session(pg_engine) as verify:
        context = _ip_race_context(verify, company_id=company_id, membership_id=actor_id)
        retained = get_ip_document(verify, context=context, document_id=fixture["document_id"])
        assert retained.current_version == 1
        assert retained.versions[0].state == ("review" if operation == "state" else "draft")
        expected_targets = {str(family.docket_id)}
        if operation == "links":
            expected_targets.add(fixture["target_id"])
        assert {row.target_id for row in retained.links} == expected_targets
        version = verify.get(IpDocumentVersion, fixture["version_id"])
        assert version.sha256_hex == fixture["content_hash"]
        retained_family = get_patent_family(verify, context=context, family_id=str(family.id))
        assert retained_family.version == family.version + 1
        assert retained_family.facts.source == source
        original = get_patent_family(
            verify, context=context, family_id=str(family.id), version_number=family.version
        )
        assert original.facts == family.facts
        document_event = verify.scalars(
            select(PrivateProjectionEvent).where(
                PrivateProjectionEvent.company_id == company_id,
                PrivateProjectionEvent.target_id == fixture["document_id"],
                PrivateProjectionEvent.reason_code == f"ip_document_{operation}_changed",
            )
        ).one()
        assert document_event.status == "applied"
        assert document_event.target_version == "1"
        expected_event = "access_changed" if operation == "links" else "source_changed"
        assert document_event.event_type == expected_event


@pytest.mark.parametrize("operation", ["links", "state"])
@pytest.mark.parametrize(
    "boundary", ["stale_version", "capability", "terminal", "revoked", "foreign_tenant"]
)
def test_document_writer_retains_mutation_guards_on_postgres(pg_engine, operation, boundary):
    fixture = _seed_document_source(pg_engine)
    company_id, actor_id = fixture["company_id"], fixture["actor_id"]
    family = fixture["family"]
    expected_status = 409 if boundary == "stale_version" else 404
    with Session(pg_engine) as setup:
        if boundary == "capability":
            setup.get(CompanyMembership, actor_id).role = "member"
            expected_status = 403
        elif boundary == "revoked":
            grant = setup.scalars(
                select(MatterAccessGrant).where(
                    MatterAccessGrant.company_id == company_id,
                    MatterAccessGrant.ip_docket_id == str(family.docket_id),
                    MatterAccessGrant.membership_id == actor_id,
                )
            ).one()
            grant.revoked_at = datetime.now(UTC)
        elif boundary == "terminal":
            context = _ip_race_context(setup, company_id=company_id, membership_id=actor_id)
            docket, _ = transition_ip_docket_lifecycle(
                setup,
                context=context,
                docket_id=str(family.docket_id),
                payload=IpLifecycleTransitionRequest(
                    expected_lifecycle_version=family.lifecycle_version,
                    to_status="closed",
                    effective_at=datetime.now(UTC),
                    reason="Client instructed closure before the document write.",
                    outcome="closed",
                    source="lawyer_review",
                    evidence_ref="test:document-write-terminal-boundary",
                    linked_matter_handling="reviewed",
                ),
            )
            assert docket.status == "closed" and not docket.is_active
        elif boundary == "foreign_tenant":
            company_id = _seed_company(setup)
            actor_id = _seed_membership(setup, company_id, role="admin")
        setup.commit()
        events_before = setup.scalar(
            select(func.count()).select_from(PrivateProjectionEvent).where(
                PrivateProjectionEvent.company_id == fixture["company_id"]
            )
        )

    with Session(pg_engine) as writer:
        context = _ip_race_context(writer, company_id=company_id, membership_id=actor_id)
        with pytest.raises(HTTPException) as rejected:
            _write_document(
                writer,
                context,
                fixture,
                operation,
                expected_version=2 if boundary == "stale_version" else 1,
            )
        assert rejected.value.status_code == expected_status
        if boundary == "stale_version":
            assert rejected.value.detail["code"] == "ip_document_version_conflict"
        if boundary == "capability":
            assert "documents:manage" in rejected.value.detail
        writer.rollback()

    with Session(pg_engine) as verify:
        assert verify.get(IpDocument, fixture["document_id"]).current_version == 1
        assert verify.get(IpDocumentVersion, fixture["version_id"]).state == "draft"
        links = verify.scalars(
            select(IpDocumentLink).where(IpDocumentLink.document_id == fixture["document_id"])
        ).all()
        assert [link.target_id for link in links] == [str(family.docket_id)]
        assert verify.scalar(
            select(func.count()).select_from(PrivateProjectionEvent).where(
                PrivateProjectionEvent.company_id == fixture["company_id"]
            )
        ) == events_before
        docket = verify.get(IpDocketRecord, str(family.docket_id))
        assert docket.is_active is (boundary != "terminal")
        assert docket.lifecycle_version == (1 if boundary == "terminal" else 0)


@pytest.mark.parametrize("journey", ["version_state", "document_links"])
def test_document_workflow_http_journey_on_postgres(isolated_postgres_client, journey):
    from tests.test_ip_document_workflow import (
        test_duplicate_detection_uses_content_and_reuses_one_document_across_links,
        test_ip_document_end_to_end_version_processing_and_approval_lock,
    )

    run_journey = {
        "version_state": test_ip_document_end_to_end_version_processing_and_approval_lock,
        "document_links": (
            test_duplicate_detection_uses_content_and_reuses_one_document_across_links
        ),
    }[journey]
    run_journey(isolated_postgres_client)
