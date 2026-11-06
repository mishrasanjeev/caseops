"""B4-ADJ-40: retired private generations must not keep deleted sources' text.

Every rebuild retires the previous generation and keeps its rows. A projection
event (deletion, disposal, archive, access change) tombstones rows only in the
generation that was active when it applied, so before this fix each retired
generation kept the full chunk text and embedding of every source it had ever
projected, including sources deleted afterwards. Nothing reads a retired
generation's text: retrieval only opens the active generation, embedding reuse
reads the generation active when a rebuild starts, and saved-output proofs
compare the retained identity columns. Retirement therefore blanks the payload
and keeps only that metadata.
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, or_, select, update

from caseops_api.db.models import (
    MatterAttachment,
    MatterAttachmentChunk,
    PrivateIndexGeneration,
    PrivateIndexProjection,
)
from caseops_api.db.session import get_session_factory
from caseops_api.scripts import private_projection_integrity
from caseops_api.services.embeddings import EmbeddingResult
from caseops_api.services.private_retrieval import (
    capture_private_saved_source_manifest,
    private_saved_source_manifest_is_current,
    propagate_private_projection_change,
)
from caseops_api.services.private_retrieval_jobs import (
    inspect_private_index_integrity,
    rebuild_private_index,
)
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_private_retrieval_workflow import _context, _other_company
from tests.test_workspace_assistant_qa import _matter

RETIRED_BLOCKER = "retained_private_payload"


class _CountingProvider:
    name = "external-spy"
    model = "private-spy-v1"
    dimensions = 3

    def __init__(self) -> None:
        self.texts: list[str] = []

    def embed(self, texts: list[str], *, input_type: str = "document") -> EmbeddingResult:
        self.texts.extend(texts)
        return EmbeddingResult(
            vectors=[[1.0, 0.0, 0.0] for _text in texts],
            provider=self.name,
            model=self.model,
            dimensions=self.dimensions,
        )


def _indexed_attachment(*, matter_id: str, membership_id: str, text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    with get_session_factory()() as session:
        attachment = MatterAttachment(
            matter_id=matter_id,
            uploaded_by_membership_id=membership_id,
            original_filename=f"{digest[:12]}.txt",
            storage_key=f"b4-adj-37/{digest}",
            content_type="text/plain",
            size_bytes=len(text.encode("utf-8")),
            sha256_hex=digest,
            processing_status="indexed",
            extracted_char_count=len(text),
            extracted_text=text,
        )
        session.add(attachment)
        session.flush()
        session.add(
            MatterAttachmentChunk(
                attachment_id=attachment.id,
                chunk_index=0,
                content=text,
                token_count=max(1, len(text.split())),
            )
        )
        session.commit()
        return str(attachment.id)


def _rebuild(company_id: str, provider: _CountingProvider | None = None) -> str:
    with get_session_factory()() as session:
        summary = rebuild_private_index(
            session,
            company_id=company_id,
            provider=provider,
            allow_external_provider=provider is not None,
            activate=True,
        )
        session.commit()
        return summary.generation_id


def _payload_rows(company_id: str, *, source_type: str, source_id: str) -> list[tuple]:
    """Every retained row of one source that still holds a label, text or a vector.

    Each tuple is (generation state, tombstoned, has text, has vector, has label).
    """
    with get_session_factory()() as session:
        return [
            tuple(row)
            for row in session.execute(
                select(
                    PrivateIndexGeneration.state,
                    PrivateIndexProjection.is_tombstoned,
                    PrivateIndexProjection.content_text != "",
                    PrivateIndexProjection.embedding_json.is_not(None),
                    PrivateIndexProjection.label != "",
                )
                .join(
                    PrivateIndexGeneration,
                    PrivateIndexGeneration.id == PrivateIndexProjection.generation_id,
                )
                .where(
                    PrivateIndexProjection.company_id == company_id,
                    PrivateIndexProjection.source_type == source_type,
                    PrivateIndexProjection.source_id == source_id,
                    or_(
                        PrivateIndexProjection.content_text != "",
                        PrivateIndexProjection.embedding_json.is_not(None),
                        PrivateIndexProjection.label != "",
                    ),
                )
                .order_by(PrivateIndexGeneration.generation_number)
            ).all()
        ]


def _retained_rows(company_id: str, *, source_type: str, source_id: str) -> list[str]:
    with get_session_factory()() as session:
        return list(
            session.scalars(
                select(PrivateIndexGeneration.state)
                .join(
                    PrivateIndexProjection,
                    PrivateIndexProjection.generation_id == PrivateIndexGeneration.id,
                )
                .where(
                    PrivateIndexProjection.company_id == company_id,
                    PrivateIndexProjection.source_type == source_type,
                    PrivateIndexProjection.source_id == source_id,
                )
                .order_by(PrivateIndexGeneration.generation_number)
            ).all()
        )


@pytest.mark.parametrize("deleted", ["document_direct", "matter_scope"])
def test_deleted_source_leaves_no_text_or_vector_in_any_retained_generation(
    client: TestClient,
    deleted: str,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    matter = _matter(client, token, f"B4-ADJ-40-{deleted.replace('_', '-')}")
    attachment_id = _indexed_attachment(
        matter_id=str(matter["id"]),
        membership_id=membership_id,
        text="B4-ADJ-40 privileged settlement memorandum clause seven.",
    )
    provider = _CountingProvider()

    _rebuild(company_id, provider)
    _rebuild(company_id, provider)
    # Two rebuilds: the source now has a row in a retired and an active generation.
    assert _retained_rows(company_id, source_type="matter_document", source_id=attachment_id) == [
        "retired",
        "active",
    ]

    with get_session_factory()() as session:
        propagate_private_projection_change(
            session,
            company_id=company_id,
            actor_membership_id=membership_id,
            idempotency_key=f"b4-adj-37:{deleted}:{attachment_id}",
            event_type="tombstoned",
            target_type="matter_document" if deleted == "document_direct" else "matter",
            target_id=attachment_id if deleted == "document_direct" else str(matter["id"]),
            target_version=None,
            reason_code="source_deleted" if deleted == "document_direct" else "matter_disposed",
        )
        session.commit()

    # Before the fix the retired generation still returned
    # ("retired", False, True, True): full text and the vector. The active
    # tombstone also kept the source's filename as its label.
    assert _payload_rows(company_id, source_type="matter_document", source_id=attachment_id) == []
    # The metadata rows stay, so saved-output proofs keep their evidence.
    assert _retained_rows(company_id, source_type="matter_document", source_id=attachment_id) == [
        "retired",
        "active",
    ]


def test_archived_client_text_is_gone_from_every_retained_generation(
    client: TestClient,
) -> None:
    """The real archive route, not a direct event, deletes the client's projection."""
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    created = client.post(
        "/api/clients/",
        headers=auth_headers(token),
        json={"name": "B4-ADJ-40 Archived Client Pvt Ltd", "client_type": "corporate"},
    )
    assert created.status_code == 200, created.text
    client_id = str(created.json()["id"])
    _rebuild(company_id)
    _rebuild(company_id)
    assert _retained_rows(company_id, source_type="client", source_id=client_id) == [
        "retired",
        "active",
    ]

    archived = client.delete(f"/api/clients/{client_id}", headers=auth_headers(token))
    assert archived.status_code == 200, archived.text

    assert _payload_rows(company_id, source_type="client", source_id=client_id) == []


def test_retirement_keeps_active_payload_saved_proofs_and_embedding_reuse(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    matter = _matter(client, token, "B4-ADJ-40-KEEP")
    attachment_id = _indexed_attachment(
        matter_id=str(matter["id"]),
        membership_id=membership_id,
        text="B4-ADJ-40 retained engagement letter text.",
    )
    provider = _CountingProvider()
    first_generation = _rebuild(company_id, provider)
    first_embedded = len(provider.texts)
    assert first_embedded >= 1

    context = _context(company_id, membership_id)
    with get_session_factory()() as session:
        manifest = capture_private_saved_source_manifest(
            session,
            context=context,
            sources=[("matter_document", attachment_id)],
        )
        assert {entry["generation_id"] for entry in manifest} == {first_generation}
        assert private_saved_source_manifest_is_current(session, context=context, manifest=manifest)

    # Without a provider a rebuild reuses the vectors of the generation active
    # when it starts. Both later rebuilds must still find them, although each
    # predecessor is blanked as soon as it retires.
    second_generation = _rebuild(company_id)
    _rebuild(company_id)
    assert len(provider.texts) == first_embedded

    with get_session_factory()() as session:
        # A manifest saved in a now-retired, now-blanked generation still verifies.
        assert private_saved_source_manifest_is_current(session, context=context, manifest=manifest)
        states = dict(
            session.execute(
                select(PrivateIndexGeneration.id, PrivateIndexGeneration.state).where(
                    PrivateIndexGeneration.id.in_((first_generation, second_generation))
                )
            ).all()
        )
        assert states == {first_generation: "retired", second_generation: "retired"}
        active_payload = session.execute(
            select(
                PrivateIndexProjection.content_text,
                PrivateIndexProjection.embedding_json,
            )
            .join(
                PrivateIndexGeneration,
                PrivateIndexGeneration.id == PrivateIndexProjection.generation_id,
            )
            .where(
                PrivateIndexProjection.company_id == company_id,
                PrivateIndexProjection.source_id == attachment_id,
                PrivateIndexGeneration.state == "active",
            )
        ).one()
        assert "retained engagement letter" in active_payload.content_text
        assert active_payload.embedding_json is not None
        report = inspect_private_index_integrity(session, company_id=company_id)
        assert report.blockers == ()
        assert report.retained_payload_count == 0


def _inject_retired_payload(company_id: str) -> int:
    """Restore text to retired rows, as every pre-fix rebuild left them."""
    with get_session_factory()() as session:
        retired = select(PrivateIndexGeneration.id).where(
            PrivateIndexGeneration.company_id == company_id,
            PrivateIndexGeneration.state == "retired",
        )
        result = session.execute(
            update(PrivateIndexProjection)
            .where(
                PrivateIndexProjection.company_id == company_id,
                PrivateIndexProjection.generation_id.in_(retired),
                PrivateIndexProjection.is_tombstoned.is_(False),
            )
            .values(content_text="legacy retained text", embedding_json="[1.0, 0.0, 0.0]")
        )
        session.commit()
        return int(result.rowcount or 0)


def test_integrity_blocks_retained_retired_payload_until_purged_per_tenant(
    client: TestClient,
) -> None:
    first = bootstrap_company(client)
    first_id = str(first["company"]["id"])
    for index in range(3):
        _matter(client, str(first["access_token"]), f"B4-ADJ-40-A-{index}")
    second = _other_company(client)
    second_id = str(second["company"]["id"])
    _matter(client, str(second["access_token"]), "B4-ADJ-40-B")
    for company_id in (first_id, second_id):
        _rebuild(company_id)
        _rebuild(company_id)
    injected = _inject_retired_payload(first_id)
    other_injected = _inject_retired_payload(second_id)
    assert injected >= 3 and other_injected >= 1

    from caseops_api.services.private_retrieval_jobs import purge_retained_private_payloads

    with get_session_factory()() as session:
        report = inspect_private_index_integrity(session, company_id=first_id)
        assert report.retained_payload_count == injected
        assert RETIRED_BLOCKER in report.blockers
        assert report.release_blocked

        # A bounded purge stops at its budget and says so.
        partial = purge_retained_private_payloads(
            session, company_id=first_id, batch_size=1, max_batches=2
        )
        assert (partial.purged_count, partial.drained) == (2, False)
        rest = purge_retained_private_payloads(session, company_id=first_id)
        assert (rest.purged_count, rest.drained) == (injected - 2, True)

        cleared = inspect_private_index_integrity(session, company_id=first_id)
        assert cleared.retained_payload_count == 0
        assert RETIRED_BLOCKER not in cleared.blockers
        # One tenant's purge never touches another tenant's rows.
        untouched = inspect_private_index_integrity(session, company_id=second_id)
        assert untouched.retained_payload_count == other_injected
        assert RETIRED_BLOCKER in untouched.blockers


def test_maintenance_purges_the_pre_fix_backlog_and_reports_it(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    company_id = str(bootstrap["company"]["id"])
    _matter(client, str(bootstrap["access_token"]), "B4-ADJ-40-MAINTAIN")
    _rebuild(company_id)
    _rebuild(company_id)
    injected = _inject_retired_payload(company_id)
    assert injected >= 1

    payload = private_projection_integrity._maintain(
        max_companies=10,
        max_rebuilds=0,
        event_lag_slo_seconds=300,
    )

    tenant = next(row for row in payload["companies"] if row["company_id"] == company_id)
    assert tenant["retained_payload_purged_count"] == injected
    assert tenant["retained_payload_drained"] is True
    assert RETIRED_BLOCKER not in tenant["blockers_after"]
    assert payload["release_blocked"] is False
    with get_session_factory()() as session:
        remaining = session.scalar(
            select(func.count(PrivateIndexProjection.id))
            .join(
                PrivateIndexGeneration,
                PrivateIndexGeneration.id == PrivateIndexProjection.generation_id,
            )
            .where(
                PrivateIndexProjection.company_id == company_id,
                PrivateIndexGeneration.state == "retired",
                or_(
                    PrivateIndexProjection.content_text != "",
                    PrivateIndexProjection.embedding_json.is_not(None),
                ),
            )
        )
    assert remaining == 0


def test_pre_fix_tombstone_labels_are_counted_and_purged(client: TestClient) -> None:
    """Tombstones written before B4-ADJ-40 kept the deleted source's name."""
    from caseops_api.services.private_retrieval_jobs import purge_retained_private_payloads

    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    created = client.post(
        "/api/clients/",
        headers=auth_headers(token),
        json={"name": "B4-ADJ-40 Legacy Tombstone Client", "client_type": "corporate"},
    )
    assert created.status_code == 200, created.text
    client_id = str(created.json()["id"])
    _rebuild(company_id)
    archived = client.delete(f"/api/clients/{client_id}", headers=auth_headers(token))
    assert archived.status_code == 200, archived.text
    with get_session_factory()() as session:
        restored = session.execute(
            update(PrivateIndexProjection)
            .where(
                PrivateIndexProjection.company_id == company_id,
                PrivateIndexProjection.source_id == client_id,
                PrivateIndexProjection.is_tombstoned.is_(True),
            )
            .values(label="B4-ADJ-40 Legacy Tombstone Client")
        )
        session.commit()
        assert restored.rowcount == 1

        report = inspect_private_index_integrity(session, company_id=company_id)
        assert report.retained_payload_count == 1
        assert RETIRED_BLOCKER in report.blockers
        purge = purge_retained_private_payloads(session, company_id=company_id)
        assert (purge.purged_count, purge.drained) == (1, True)
        assert _payload_rows(company_id, source_type="client", source_id=client_id) == []
        # The tombstone itself, and its tombstone evidence, remain.
        assert session.execute(
            select(
                PrivateIndexProjection.is_tombstoned,
                PrivateIndexProjection.tombstone_reason,
            ).where(
                PrivateIndexProjection.company_id == company_id,
                PrivateIndexProjection.source_id == client_id,
            )
        ).one() == (True, "client_archived")


def test_undrained_backlog_never_stops_maintenance_rebuilding_a_stale_generation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Payload retention blocks the release but is drained by the purge, not a rebuild.

    Maintenance rebuilds only when every blocker is repairable. Counting the
    retained-payload blocker there would leave a new source invisible for as
    long as a pre-fix backlog takes to drain.
    """
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    _matter(client, token, "B4-ADJ-40-STALE-A")
    _rebuild(company_id)
    _rebuild(company_id)
    injected = _inject_retired_payload(company_id)
    assert injected >= 1
    # A new source invalidates the active manifest: a repairable blocker.
    _matter(client, token, "B4-ADJ-40-STALE-B")
    with get_session_factory()() as session:
        before = inspect_private_index_integrity(session, company_id=company_id)
    assert set(before.blockers) == {"active_generation_manifest_mismatch", RETIRED_BLOCKER}
    assert before.oldest_repair_lag_seconds is not None

    # The maintenance pass's own purge budget is exhausted this run.
    monkeypatch.setattr(
        private_projection_integrity,
        "purge_retained_private_payloads",
        lambda _session, *, company_id, **_kwargs: type(
            "Undrained", (), {"purged_count": 0, "batch_count": 0, "drained": False}
        )(),
    )
    payload = private_projection_integrity._maintain(
        max_companies=10,
        max_rebuilds=1,
        event_lag_slo_seconds=300,
    )

    tenant = next(row for row in payload["companies"] if row["company_id"] == company_id)
    assert tenant["rebuilt"] is True
    assert "active_generation_manifest_mismatch" not in tenant["blockers_after"]
    # The rebuild's own post-activation purge then drained the backlog.
    assert tenant["blockers_after"] == []
    assert tenant["retained_payload_drained"] is True
