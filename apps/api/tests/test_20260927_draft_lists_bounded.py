"""Bounded private-source reauthorization for Draft lists and reads (2026-09-27).

PR #490 gave ``private_saved_source_manifests_are_current`` one bounded
statement set for many saved-output manifests. The Matter drafts list, the IP
opposition drafts list and every single-draft read still reauthorized each
version's manifest on its own: about seven statements for every version that
carries a private source. The lists also read a manifest that is not a JSON
list as "no private source" and returned that draft's full body, while the
single-draft read refused the same draft with 409.

Every draft here carries the manifests the private capture path writes, saved
in the active generation and in a generation retired by an unrelated rebuild,
beside manifests whose private source was revoked in either generation and
malformed manifests. A draft must be listed exactly when each of its versions
is current on its own, its single-draft read must agree with the list, and
neither may cost more statements for more drafts or more versions.

The revocation tombstones only the generation active when it applies. The
second test lists and reads the same drafts after a later rebuild has retired
every saved generation: a draft citing the revoked source must stay hidden
whichever generation its proof was saved in.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from caseops_api.db.models import Draft, DraftVersion, Matter
from caseops_api.db.session import get_session_factory
from caseops_api.services.drafting import get_draft, get_ip_draft, list_drafts, list_ip_drafts
from caseops_api.services.private_retrieval import (
    capture_private_saved_source_manifest,
    private_saved_source_manifest_is_current,
    private_source_version,
    propagate_private_projection_change,
)
from caseops_api.services.private_retrieval_jobs import rebuild_private_index
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import auth_headers
from tests.test_ip_opposition_opponent_workflow import _fixture as opposition_fixture
from tests.test_private_retrieval_foundation import _context, _create_member
from tests.test_workspace_assistant_qa import _matter

# Statements for one list, whatever its draft and version counts, for a
# non-owner member. Matter list: the Matter, then the team-scoping flag and the
# visibility-filtered Matter for its access check; drafts, their versions and
# their reviews; the active generation, saved projections with their
# later-event ledger check, saved generations, active rows for retired
# manifests, the team-scoping flag with ACL-authorized projection IDs, and the
# team-scoping flag with current Matter versions.
MATTER_DRAFT_LIST_STATEMENT_BOUND = 14
# IP list: the docket and the visibility-filtered docket for its access check,
# and the opposition proceeding; drafts, versions and reviews; the same
# manifest statements, ending with current IP docket versions.
IP_DRAFT_LIST_STATEMENT_BOUND = 13
# A single-draft read issues the same statements for one draft.
DRAFT_READ_STATEMENT_BOUND = 14

# Draft handoff keeps the review's selected authorities beside its private
# entries; they are not private sources and never need reauthorization.
AUTHORITY_ENTRY = {
    "authority_document_id": "5a1f0c3e-7d0b-4d8e-9a54-2f7c7c1e9b10",
    "content_hash": "a" * 64,
    "included_for_generation": True,
    "source": "supreme_court_latest_orders",
}


def _capture(session: Session, context: SessionContext, *sources: tuple[str, str]) -> list[dict]:
    return list(capture_private_saved_source_manifest(session, context=context, sources=sources))


def build_draft_targets(
    client: TestClient,
    *,
    after_rebuild: Callable[[Session, str], None] | None = None,
    later_rebuild: bool = False,
) -> dict:
    """Capture a Matter's and an IP docket's manifests as saved outputs freeze them.

    Each target gets one manifest in each state: retired and active
    generation, each with and without a private source that is later revoked.
    ``later_rebuild`` then retires the active generation as well.
    """

    bootstrap, _docket_matter, docket, proceeding = opposition_fixture(client)
    owner_token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    owner_membership_id = str(bootstrap["membership"]["id"])
    member_membership_id, member_token = _create_member(client, owner_token)
    # The PostgreSQL client keeps the member's login cookie, and a cookie wins
    # over an explicit bearer; every request below must be the bearer's.
    client.cookies.clear()
    matter_id = str(_matter(client, owner_token, "DRAFT-LIST-001")["id"])
    revoked_matter_id = str(_matter(client, owner_token, "DRAFT-LIST-REVOKED")["id"])
    targets = {"matter": ("matter", matter_id), "ip": ("ip_docket", str(docket["id"]))}
    revoked = ("matter", revoked_matter_id)
    manifests: dict[str, dict[str, list[dict]]] = {kind: {} for kind in targets}
    factory = get_session_factory()

    def rebuild() -> None:
        with factory() as session:
            rebuild_private_index(session, company_id=company_id, activate=True)
            if after_rebuild is not None:
                after_rebuild(session, company_id)

    def owner(session: Session) -> SessionContext:
        return _context(session, company_id=company_id, membership_id=owner_membership_id)

    rebuild()
    with factory() as session:
        context = owner(session)
        for kind, target in targets.items():
            manifests[kind]["retired"] = _capture(session, context, target)
            manifests[kind]["retired, revoked"] = _capture(session, context, target, revoked)

    # Unrelated source creation followed by the bounded maintenance rebuild
    # retires the generation above without changing any saved source.
    _matter(client, owner_token, "DRAFT-LIST-UNRELATED")
    rebuild()
    with factory() as session:
        context = owner(session)
        for kind, target in targets.items():
            manifests[kind]["active, revoked"] = _capture(session, context, target, revoked)
        revoked_row = session.get(Matter, revoked_matter_id)
        assert revoked_row is not None
        propagate_private_projection_change(
            session,
            company_id=company_id,
            actor_membership_id=owner_membership_id,
            idempotency_key=f"draft-list-revoke:{uuid4()}",
            event_type="access_changed",
            target_type="matter",
            target_id=revoked_matter_id,
            target_version=private_source_version(revoked_row),
            reason_code="draft_list_access_revoked",
        )
        session.commit()
    with factory() as session:
        context = owner(session)
        for kind, target in targets.items():
            manifests[kind]["active"] = _capture(session, context, target)
    if later_rebuild:
        # The revocation never reached the first generation's rows, and this
        # rebuild recreates the revoked Matter unchanged. Drafts that cite the
        # first generation's proof of it must still stay hidden.
        _matter(client, owner_token, "DRAFT-LIST-LATER")
        rebuild()

    generations = {
        kind: {state: {item["generation_id"] for item in rows} for state, rows in states.items()}
        for kind, states in manifests.items()
    }
    for states in generations.values():
        assert all(len(ids) == 1 for ids in states.values()), states
        assert states["retired"] == states["retired, revoked"]
        assert states["active"] == states["active, revoked"]
        assert states["retired"] != states["active"]
    return {
        "company_id": company_id,
        "owner_membership_id": owner_membership_id,
        "member_membership_id": member_membership_id,
        "member_token": member_token,
        "matter_id": matter_id,
        "docket_id": str(docket["id"]),
        "proceeding_id": str(proceeding["id"]),
        "manifests": manifests,
        "newest": datetime.now(UTC),
        "inserted": 0,
    }


def draft_specs(manifests: dict[str, list[dict]]) -> list[dict]:
    """Each draft's versions as saved manifest text, oldest first."""

    active = manifests["active"]
    retired = manifests["retired"]

    def saved(*entries: dict) -> str:
        return json.dumps([*entries, AUTHORITY_ENTRY], sort_keys=True)

    def spec(label: str, versions: list[str], *, visible: bool) -> dict:
        return {"label": label, "versions": versions, "visible": visible}

    return [
        spec("active generation", [saved(*active)], visible=True),
        spec("retired generation", [saved(*retired)], visible=True),
        spec(
            "retired version, then an active version",
            [saved(*retired), saved(*active)],
            visible=True,
        ),
        spec("edits copy one manifest", [saved(*active)] * 3, visible=True),
        spec("authority sources only", [saved()], visible=True),
        spec("no version yet", [], visible=True),
        spec("undecodable text carries no saved private source", ['[{"schema": '], visible=True),
        spec(
            "retired generation, source later revoked",
            [saved(*manifests["retired, revoked"])],
            visible=False,
        ),
        spec(
            "active generation, source later revoked",
            [saved(*manifests["active, revoked"])],
            visible=False,
        ),
        spec(
            "revoked version between current versions",
            [saved(*retired), saved(*manifests["active, revoked"]), saved(*active)],
            visible=False,
        ),
        spec(
            "retired and active entries merged into one manifest",
            [saved(*retired, *active)],
            visible=False,
        ),
        spec(
            "manifest saved as a JSON object",
            [json.dumps(active[0], sort_keys=True)],
            visible=False,
        ),
        spec("manifest saved as JSON null", ["null"], visible=False),
        spec(
            "current version after a JSON object",
            [json.dumps(active[0], sort_keys=True), saved(*active)],
            visible=False,
        ),
        spec(
            "private entry without a projection ID",
            [saved({**active[0], "projection_id": None})],
            visible=False,
        ),
        spec("one projection claimed twice", [saved(*active, *active)], visible=False),
        spec(
            "unknown saved generation",
            [saved({**active[0], "generation_id": str(uuid4())})],
            visible=False,
        ),
        spec(
            "saved hash no longer matches",
            [saved({**active[0], "source_sha256": "0" * 64})],
            visible=False,
        ),
    ]


def add_drafts(
    targets: dict, kind: str, specs: list[dict], *, copies: int, repeat: int
) -> list[dict]:
    """Insert ``copies`` drafts per spec, each with its versions repeated ``repeat`` times.

    Repeating a draft's versions keeps its decision, so a larger list must
    return the same kinds of drafts at the same statement cost. Each insert
    is older than the previous one, so a list returns them in insert order.
    """

    rows: list[dict] = []
    with get_session_factory()() as session:
        for copy in range(copies):
            for spec in specs:
                stamp = targets["newest"] - timedelta(seconds=targets["inserted"])
                targets["inserted"] += 1
                versions = [
                    DraftVersion(
                        id=str(uuid4()),
                        revision=revision,
                        body=f"{spec['label']}: revision {revision}",
                        source_manifest_json=manifest_text,
                        generated_by_membership_id=targets["owner_membership_id"],
                        created_at=stamp,
                    )
                    for revision, manifest_text in enumerate(spec["versions"] * repeat, start=1)
                ]
                draft = Draft(
                    company_id=targets["company_id"],
                    matter_id=targets["matter_id"] if kind == "matter" else None,
                    ip_docket_id=targets["docket_id"] if kind == "ip" else None,
                    ip_proceeding_id=targets["proceeding_id"] if kind == "ip" else None,
                    created_by_membership_id=targets["owner_membership_id"],
                    title=f"{spec['label']} ({copy + 1})",
                    draft_type="memo",
                    template_type="intelligent_review_report",
                    status="draft",
                    review_required=True,
                    # Set with the insert: a later update would reset updated_at.
                    current_version_id=versions[-1].id if versions else None,
                    created_at=stamp,
                    updated_at=stamp,
                    versions=versions,
                )
                session.add(draft)
                session.flush()
                rows.append({**spec, "id": draft.id, "version_count": len(versions)})
        session.commit()
    return rows


@contextmanager
def recorded_statements(session: Session) -> Iterator[list[str]]:
    statements: list[str] = []

    def record(_conn, _cursor, statement, _params, _context, _many) -> None:
        statements.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)


def _member_session(
    targets: dict,
    prepare_session: Callable[[Session], None] | None,
) -> tuple[Session, SessionContext]:
    session = get_session_factory()()
    if prepare_session is not None:
        prepare_session(session)
    member = _context(
        session,
        company_id=targets["company_id"],
        membership_id=targets["member_membership_id"],
    )
    return session, member


def listed_drafts(
    targets: dict,
    kind: str,
    prepare_session: Callable[[Session], None] | None = None,
) -> tuple[list[str], list[str]]:
    """List as the member in a fresh session, as a request would."""

    session, member = _member_session(targets, prepare_session)
    with session, recorded_statements(session) as statements:
        if kind == "matter":
            drafts = list_drafts(session, context=member, matter_id=targets["matter_id"])
        else:
            drafts = list_ip_drafts(
                session,
                context=member,
                docket_id=targets["docket_id"],
                proceeding_id=targets["proceeding_id"],
            )
        return [draft.id for draft in drafts], statements


def read_draft(
    targets: dict,
    kind: str,
    draft_id: str,
    prepare_session: Callable[[Session], None] | None = None,
) -> tuple[bool, list[str]]:
    """Read one draft as the member; ``False`` when the read refuses it with 409."""

    session, member = _member_session(targets, prepare_session)
    with session, recorded_statements(session) as statements:
        try:
            if kind == "matter":
                get_draft(
                    session,
                    context=member,
                    matter_id=targets["matter_id"],
                    draft_id=draft_id,
                )
            else:
                get_ip_draft(
                    session,
                    context=member,
                    docket_id=targets["docket_id"],
                    proceeding_id=targets["proceeding_id"],
                    draft_id=draft_id,
                )
        except HTTPException as exc:
            assert exc.status_code == 409, exc.detail
            return False, statements
        return True, statements


def version_decision(session: Session, member: SessionContext, manifest_text: str) -> bool:
    """One version's decision from the one-manifest form of the policy."""

    try:
        manifest = json.loads(manifest_text)
    except json.JSONDecodeError:
        manifest = []
    return isinstance(manifest, list) and private_saved_source_manifest_is_current(
        session,
        context=member,
        manifest=manifest,
    )


def membership_problems(name: str, rows: list[dict], listed_ids: list[str]) -> list[str]:
    """Describe how a list differs from its visible drafts, newest first."""

    expected = [row["id"] for row in rows if row["visible"]]
    if listed_ids == expected:
        return []
    listed = set(listed_ids)
    wrongly_listed = [row["label"] for row in rows if row["id"] in listed and not row["visible"]]
    wrongly_hidden = [row["label"] for row in rows if row["id"] not in listed and row["visible"]]
    if not wrongly_listed and not wrongly_hidden:
        return [f"{name} of {len(rows)} drafts returned the visible drafts out of order"]
    return [
        f"{name} of {len(rows)} drafts listed although refused: {wrongly_listed}; "
        f"hidden although readable: {wrongly_hidden}"
    ]


def assert_bounded_draft_lists(
    client: TestClient,
    targets: dict,
    *,
    copies: int = 2,
    repeat: int = 3,
    prepare_session: Callable[[Session], None] | None = None,
) -> None:
    bounds = {"matter": MATTER_DRAFT_LIST_STATEMENT_BOUND, "ip": IP_DRAFT_LIST_STATEMENT_BOUND}
    headers = auth_headers(targets["member_token"])
    for kind, bound in bounds.items():
        specs = draft_specs(targets["manifests"][kind])
        labels = [spec["label"] for spec in specs]
        session, member = _member_session(targets, prepare_session)
        with session:
            decisions = {
                text: version_decision(session, member, text)
                for spec in specs
                for text in spec["versions"]
            }
        one_at_a_time = [all(decisions[text] for text in spec["versions"]) for spec in specs]
        assert list(zip(labels, one_at_a_time, strict=True)) == [
            (spec["label"], spec["visible"]) for spec in specs
        ]

        # Collect every membership and cost problem before failing, so one run
        # shows the complete difference from the per-version implementation.
        small = add_drafts(targets, kind, specs, copies=1, repeat=1)
        small_ids, small_statements = listed_drafts(targets, kind, prepare_session)
        large = small + add_drafts(targets, kind, specs, copies=copies, repeat=repeat)
        large_ids, large_statements = listed_drafts(targets, kind, prepare_session)
        problems = [
            *membership_problems(f"{kind} list", small, small_ids),
            *membership_problems(f"{kind} list", large, large_ids),
        ]
        if len(large_statements) != len(small_statements) or len(large_statements) > bound:
            problems.append(
                f"{kind} list: {len(small_statements)} statements for {len(small)} drafts and "
                f"{sum(row['version_count'] for row in small)} versions, "
                f"{len(large_statements)} for {len(large)} drafts and "
                f"{sum(row['version_count'] for row in large)} versions; the bound is {bound}"
            )
            if len(large_statements) == len(small_statements):
                problems.extend(large_statements)

        # A single-draft read makes the same decision at a cost that does not
        # grow with the draft's versions.
        read_costs: dict[str, int] = {}
        for row in large:
            readable, statements = read_draft(targets, kind, row["id"], prepare_session)
            first_cost = read_costs.setdefault(row["label"], len(statements))
            if readable != row["visible"]:
                problems.append(f"{kind} read of {row['label']!r} returned readable={readable}")
            if len(statements) != first_cost or len(statements) > DRAFT_READ_STATEMENT_BOUND:
                problems.append(
                    f"{kind} read of {row['label']!r}: {len(statements)} statements at "
                    f"{row['version_count']} versions, {first_cost} at its first size; "
                    f"the bound is {DRAFT_READ_STATEMENT_BOUND}"
                )
        assert not problems, "\n".join(problems)

        if kind == "matter":
            base = f"/api/matters/{targets['matter_id']}/drafts"
        else:
            base = (
                f"/api/ip/dockets/{targets['docket_id']}/proceedings/"
                f"{targets['proceeding_id']}/drafts"
            )
        response = client.get(base, headers=headers)
        assert response.status_code == 200, response.text
        listed = [item["id"] for item in response.json()["drafts"]]
        assert not membership_problems(f"{kind} HTTP list", large, listed)
        for row in small:
            read = client.get(f"{base}/{row['id']}", headers=headers)
            assert read.status_code == (200 if row["visible"] else 409), (row["label"], read.text)


def test_draft_lists_and_reads_reauthorize_every_version_in_one_bounded_query_set(
    client: TestClient,
) -> None:
    targets = build_draft_targets(client)
    assert_bounded_draft_lists(client, targets)


def test_draft_lists_and_reads_keep_revoked_sources_hidden_after_a_later_rebuild(
    client: TestClient,
) -> None:
    targets = build_draft_targets(client, later_rebuild=True)
    assert_bounded_draft_lists(client, targets)
