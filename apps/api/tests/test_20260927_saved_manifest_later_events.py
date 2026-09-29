"""Later source events keep saved private manifests fail-closed (2026-09-27).

``apply_private_projection_event`` tombstones affected projections only in the
generation that is active when the event applies. The saved-manifest check
compared a retired generation's rows with the active generation, so a manifest
saved one generation before an event came back to life at the next rebuild
whenever the event left its source's version and hash unchanged, while the same
manifest saved one generation later stayed locked for good. The check's
docstring claimed that events tombstone rows across generations; no test could
fail on that claim, because every "source later revoked" shape was asserted
only before a later rebuild.

Every manifest here comes from the capture path and is saved twice: in a
generation retired by an unrelated rebuild before the events, and in the
generation active when they apply. A member of an unrestricted tenant checks
each one before and after a later rebuild. The events are bare ones that leave
the source unchanged and real ones from the access and lifecycle endpoints; the
saved documents carry their SHA-256 as their version, which no Matter access or
lifecycle change alters.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from caseops_api.db.models import Matter
from caseops_api.db.session import get_session_factory
from caseops_api.services.private_retrieval import (
    capture_private_saved_source_manifest,
    private_saved_source_manifest_is_current,
    private_saved_source_manifests_are_current,
    private_source_version,
    propagate_private_projection_change,
)
from caseops_api.services.private_retrieval_jobs import rebuild_private_index
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_private_retrieval_foundation import _context, _create_member
from tests.test_private_retrieval_workflow import _indexed_matter_attachment
from tests.test_workspace_assistant_qa import _matter

UNCHANGED = "unchanged source"
# The member loses access to this Matter and keeps access to every other source.
MATTER_RESTRICTED = "Matter restricted"
BARE_EVENTS = {
    "bare access event on the Matter": "access_changed",
    "bare reindex event on the Matter": "reindex",
    "bare access event on the document's Matter": "access_changed",
}
DOCUMENT_SOURCES = (
    "bare access event on the document's Matter",
    "member granted on the document's Matter",
    "document's Matter disposed and reopened",
)


def _decisions(
    session: Session,
    member: SessionContext,
    manifests: dict[tuple[str, str], list[dict]],
) -> dict[tuple[str, str], bool]:
    """Each manifest's own decision; the batched decision must agree with it."""

    keys = list(manifests)
    one_at_a_time = {
        key: private_saved_source_manifest_is_current(
            session, context=member, manifest=manifests[key]
        )
        for key in keys
    }
    batched = private_saved_source_manifests_are_current(
        session, context=member, manifests=[manifests[key] for key in keys]
    )
    assert dict(zip(keys, batched, strict=True)) == one_at_a_time
    return one_at_a_time


def _lifecycle(client: TestClient, token: str, matter_id: str, to_status: str) -> None:
    current = client.get(f"/api/matters/{matter_id}", headers=auth_headers(token))
    assert current.status_code == 200, current.text
    response = client.patch(
        f"/api/matters/{matter_id}/lifecycle/status",
        headers=auth_headers(token),
        json={
            "to_status": to_status,
            "expected_from_status": current.json()["status"],
            "expected_updated_at": current.json()["updated_at"],
            "reason": f"Saved-manifest regression moves this Matter to {to_status}.",
        },
    )
    assert response.status_code == 200, response.text


def test_later_source_events_keep_saved_manifests_fail_closed_in_every_generation(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    owner_membership_id = str(bootstrap["membership"]["id"])
    member_membership_id, _member_token = _create_member(client, owner_token)
    # The PostgreSQL client keeps the member's login cookie, and a cookie wins
    # over an explicit bearer; every request below must be the owner's.
    client.cookies.clear()
    owner_headers = auth_headers(owner_token)
    factory = get_session_factory()

    def matter(code: str) -> str:
        return str(_matter(client, owner_token, f"LATER-EVENT-{code}")["id"])

    matters = {
        UNCHANGED: matter("UNCHANGED"),
        "bare access event on the Matter": matter("BARE-ACCESS"),
        "bare reindex event on the Matter": matter("BARE-REINDEX"),
        MATTER_RESTRICTED: matter("RESTRICTED"),
        "Matter restricted, member granted": matter("GRANTED"),
        **{label: matter(f"PARENT-{index}") for index, label in enumerate(DOCUMENT_SOURCES)},
    }
    sources = {
        label: ("matter", matter_id)
        for label, matter_id in matters.items()
        if label not in DOCUMENT_SOURCES
    }
    for label in DOCUMENT_SOURCES:
        sources[label] = (
            "matter_document",
            _indexed_matter_attachment(
                matter_id=matters[label],
                membership_id=owner_membership_id,
                text=f"Saved-manifest regression evidence for {label} {uuid4()}.",
            ),
        )

    def rebuild() -> None:
        with factory() as session:
            rebuild_private_index(session, company_id=company_id, activate=True)

    def capture_all() -> dict[str, list[dict]]:
        with factory() as session:
            owner = _context(session, company_id=company_id, membership_id=owner_membership_id)
            captured = {
                label: list(
                    capture_private_saved_source_manifest(session, context=owner, sources=(source,))
                )
                for label, source in sources.items()
            }
        assert all(captured.values()), captured
        return captured

    def member_decisions(manifests: dict[tuple[str, str], list[dict]]) -> dict:
        with factory() as session:
            member = _context(session, company_id=company_id, membership_id=member_membership_id)
            return _decisions(session, member, manifests)

    rebuild()
    retired = capture_all()
    # Unrelated source creation followed by the bounded maintenance rebuild
    # retires the generation above without changing any saved source.
    _matter(client, owner_token, "LATER-EVENT-UNRELATED")
    rebuild()
    active = capture_all()
    saved = {
        **{("saved before an unrelated rebuild", label): rows for label, rows in retired.items()},
        **{("saved in the event's generation", label): rows for label, rows in active.items()},
    }
    assert {
        generation
        for rows in saved.values()
        for generation in {item["generation_id"] for item in rows}
    } == {retired[UNCHANGED][0]["generation_id"], active[UNCHANGED][0]["generation_id"]}
    assert retired[UNCHANGED][0]["generation_id"] != active[UNCHANGED][0]["generation_id"]
    assert all(member_decisions(saved).values()), "an unrelated rebuild revoked a manifest"

    with factory() as session:
        for label, event_type in BARE_EVENTS.items():
            row = session.get(Matter, matters[label])
            assert row is not None
            propagate_private_projection_change(
                session,
                company_id=company_id,
                actor_membership_id=owner_membership_id,
                idempotency_key=f"later-event:{uuid4()}",
                event_type=event_type,
                target_type="matter",
                target_id=row.id,
                target_version=private_source_version(row),
                reason_code="saved_manifest_later_event",
            )
        session.commit()
    for label in (MATTER_RESTRICTED, "Matter restricted, member granted"):
        restricted = client.post(
            f"/api/matters/{matters[label]}/access/restricted",
            headers=owner_headers,
            json={"restricted": True},
        )
        assert restricted.status_code == 200, restricted.text
    for label in ("Matter restricted, member granted", "member granted on the document's Matter"):
        granted = client.post(
            f"/api/matters/{matters[label]}/access/grants",
            headers=owner_headers,
            json={"membership_id": member_membership_id, "reason": "Assigned to the review."},
        )
        assert granted.status_code == 200, granted.text
    _lifecycle(client, owner_token, matters["document's Matter disposed and reopened"], "disposed")
    _lifecycle(client, owner_token, matters["document's Matter disposed and reopened"], "intake")

    def expected(*, after_later_rebuild: bool) -> dict[tuple[str, str], bool]:
        # Only the unchanged source stays current. Every event reaches both
        # saved generations; the active generation's epoch fence also holds
        # the unchanged source until the next rebuild.
        return {
            key: key[1] == UNCHANGED
            and (after_later_rebuild or key[0] == "saved before an unrelated rebuild")
            for key in saved
        }

    problems: list[str] = []
    for after_later_rebuild in (False, True):
        if after_later_rebuild:
            rebuild()
        state = "after a later rebuild" if after_later_rebuild else "before a later rebuild"
        actual = member_decisions(saved)
        problems.extend(
            f"{state}, {generation}, {label}: current={actual[(generation, label)]}"
            for (generation, label), is_current in expected(
                after_later_rebuild=after_later_rebuild
            ).items()
            if actual[(generation, label)] != is_current
        )
    assert not problems, "\n".join(problems)

    # A proof captured after the events and the rebuild is current again for
    # the member exactly where the member can still read its source.
    fresh = {("captured after the rebuild", label): rows for label, rows in capture_all().items()}
    assert member_decisions(fresh) == {key: key[1] != MATTER_RESTRICTED for key in fresh}
