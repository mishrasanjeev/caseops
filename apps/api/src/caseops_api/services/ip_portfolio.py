"""Trademark portfolio projection for IPLF-030A/B.

The legal rows remain a read-only projection over existing IP owners. IPLF-030B
adds only user-scoped presentation preferences and export-job control records;
neither becomes a second portfolio or legal-record writer.

Access is delegated to the canonical ``visible_ip_dockets_filter`` policy, so a
restricted record a user cannot open is **omitted entirely** rather than shown
as a redacted teaser.
"""

from __future__ import annotations

import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import UTC, date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import Select, String, and_, case, false, func, literal, or_, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Client,
    CompanyMembership,
    IpAsset,
    IpDeadline,
    IpDocketEvent,
    IpDocketRecord,
    IpIdentifier,
    IpPartyAndRole,
    IpProceeding,
    IpTrademarkParticularVersion,
    Matter,
    MatterClientAssignment,
    MatterStatus,
    Team,
    TrademarkApplication,
    TrademarkApplicationScope,
    TrademarkRepresentation,
    User,
)
from caseops_api.schemas.ip_portfolio import (
    IpPortfolioCounts,
    IpPortfolioFamily,
    IpPortfolioFamilyMember,
    IpPortfolioFamilyResponse,
    IpPortfolioFilters,
    IpPortfolioListResponse,
    IpPortfolioRow,
)
from caseops_api.services.ip_identifier_rules import normalize_ip_identifier
from caseops_api.services.matter_access import visible_ip_dockets_filter
from caseops_api.services.session_context import SessionContext

MAX_LIMIT = 200
DEFAULT_LIMIT = 50
MAX_FAMILY_LIMIT = 100
DEFAULT_FAMILY_LIMIT = 25
REGISTRY_FRESHNESS_WINDOW = timedelta(hours=24)

PROPRIETOR_ROLES = {"applicant", "owner", "proprietor"}
AGENT_ROLES = {"agent", "attorney", "counsel", "representative"}


def _normalize(values: list[str], *, lower: bool = True) -> list[str]:
    seen: list[str] = []
    for value in values:
        cleaned = value.strip()
        if not cleaned:
            continue
        cleaned = cleaned.lower() if lower else cleaned.upper()
        if cleaned not in seen:
            seen.append(cleaned)
    return seen


def _encode_cursor(updated_at, application_id: str) -> str:
    raw = f"{updated_at.isoformat()}|{application_id}".encode()
    return urlsafe_b64encode(raw).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    """Decode an opaque cursor into a comparable timestamp and tie-break id.

    The timestamp must be parsed back into a ``datetime``; comparing the raw
    string against a ``DateTime`` column silently fails to filter on SQLite.
    """

    try:
        raw = urlsafe_b64decode(cursor.encode()).decode()
        timestamp, application_id = raw.split("|", 1)
        parsed = datetime.fromisoformat(timestamp)
    except Exception as exc:  # noqa: BLE001 - opaque cursor is a client contract
        raise HTTPException(status_code=400, detail="Invalid portfolio cursor.") from exc
    if not application_id:
        raise HTTPException(status_code=400, detail="Invalid portfolio cursor.")
    return parsed, application_id


def _encode_family_cursor(member_count: int, label: str, family_key: str) -> str:
    raw = json.dumps(
        [member_count, label.casefold(), family_key],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode()
    return urlsafe_b64encode(raw).decode()


def _decode_family_cursor(cursor: str) -> tuple[int, str, str]:
    try:
        member_count, label, family_key = json.loads(
            urlsafe_b64decode(cursor.encode()).decode()
        )
        if (
            not isinstance(member_count, int)
            or member_count < 1
            or not isinstance(label, str)
            or not isinstance(family_key, str)
            or not family_key
        ):
            raise ValueError
    except Exception as exc:  # noqa: BLE001 - opaque cursor is a client contract
        raise HTTPException(status_code=400, detail="Invalid family cursor.") from exc
    return member_count, label, family_key


def _primary_client_expressions(company_id: str):
    """Return stable primary-client expressions without multiplying Matter rows."""

    assignment_order = (
        MatterClientAssignment.is_primary.desc(),
        MatterClientAssignment.created_at,
        MatterClientAssignment.id,
    )
    primary_client_id = (
        select(MatterClientAssignment.client_id)
        .join(Client, Client.id == MatterClientAssignment.client_id)
        .where(
            MatterClientAssignment.matter_id == IpDocketRecord.matter_id,
            Client.company_id == company_id,
        )
        .order_by(*assignment_order)
        .limit(1)
        .correlate(IpDocketRecord)
        .scalar_subquery()
    )
    primary_client_name = (
        select(Client.name)
        .join(
            MatterClientAssignment,
            MatterClientAssignment.client_id == Client.id,
        )
        .where(
            MatterClientAssignment.matter_id == IpDocketRecord.matter_id,
            Client.company_id == company_id,
        )
        .order_by(*assignment_order)
        .limit(1)
        .correlate(IpDocketRecord)
        .scalar_subquery()
    )
    legacy_name = func.trim(func.coalesce(Matter.client_name, ""))
    family_key = case(
        (primary_client_id.is_not(None), primary_client_id),
        (
            legacy_name != "",
            literal("legacy:") + func.lower(legacy_name),
        ),
        else_=None,
    )
    label = case(
        (primary_client_name.is_not(None), primary_client_name),
        else_=legacy_name,
    )
    return family_key, label


def _latest_registry_sync_at():
    return (
        select(func.max(IpDocketEvent.entered_at))
        .where(
            IpDocketEvent.company_id == TrademarkApplication.company_id,
            IpDocketEvent.docket_id == IpDocketRecord.id,
            IpDocketEvent.source == "registry_sync",
            IpDocketEvent.candidate_status == "confirmed",
        )
        .correlate(TrademarkApplication, IpDocketRecord)
        .scalar_subquery()
    )


def _primary_application_identifier():
    """Return the current primary number owned by the projected application."""

    return (
        select(IpIdentifier.raw_value)
        .where(
            IpIdentifier.company_id == TrademarkApplication.company_id,
            IpIdentifier.application_id == TrademarkApplication.id,
            IpIdentifier.identifier_kind == "application",
            IpIdentifier.is_primary.is_(True),
            IpIdentifier.effective_until.is_(None),
            IpIdentifier.superseded_by_identifier_id.is_(None),
        )
        .order_by(IpIdentifier.created_at.desc(), IpIdentifier.id.desc())
        .limit(1)
        .correlate(TrademarkApplication)
        .scalar_subquery()
    )


def _primary_application_identifiers(
    session: Session,
    *,
    company_id: str,
    application_ids: list[str],
) -> dict[str, str]:
    if not application_ids:
        return {}
    rows = session.execute(
        select(IpIdentifier.application_id, IpIdentifier.raw_value)
        .where(
            IpIdentifier.company_id == company_id,
            IpIdentifier.application_id.in_(application_ids),
            IpIdentifier.identifier_kind == "application",
            IpIdentifier.is_primary.is_(True),
            IpIdentifier.effective_until.is_(None),
            IpIdentifier.superseded_by_identifier_id.is_(None),
        )
        .order_by(
            IpIdentifier.application_id,
            IpIdentifier.created_at.desc(),
            IpIdentifier.id.desc(),
        )
    ).all()
    result: dict[str, str] = {}
    for application_id, raw_value in rows:
        if application_id is not None:
            result.setdefault(application_id, raw_value)
    return result


def _registry_state_predicate(state: str):
    latest = _latest_registry_sync_at()
    threshold = datetime.now(UTC) - REGISTRY_FRESHNESS_WINDOW
    if state == "current":
        return latest >= threshold
    if state == "stale":
        return and_(latest.is_not(None), latest < threshold)
    if state == "unavailable":
        return latest.is_(None)
    # No per-docket provider-failure owner exists before IPLF-043B. A caller
    # asking for failures therefore gets an empty scope, never a fabricated 0.
    return false()


def _scoped_query(
    session: Session,
    *,
    context: SessionContext,
    filters: IpPortfolioFilters,
) -> Select:
    """Company-scoped, access-filtered application rows joined to mark/docket."""

    statement = (
        select(TrademarkApplication, IpAsset, IpDocketRecord)
        .join(IpDocketRecord, IpDocketRecord.id == TrademarkApplication.docket_id)
        .outerjoin(IpAsset, IpAsset.id == TrademarkApplication.asset_id)
        .outerjoin(
            Matter,
            and_(
                Matter.id == IpDocketRecord.matter_id,
                Matter.company_id == context.company.id,
            ),
        )
        .where(
            TrademarkApplication.company_id == context.company.id,
            IpDocketRecord.company_id == context.company.id,
            IpDocketRecord.archived_by_matter_disposal.is_(False),
            visible_ip_dockets_filter(session, context=context),
            # Operational visibility is part of the SQL scope, not a
            # post-pagination filter.  Applying it after LIMIT can return an
            # empty page and discard the cursor even when later live records
            # exist.  Missing linked Matters fail closed; unlinked IP dockets
            # remain valid portfolio records.
            or_(
                IpDocketRecord.matter_id.is_(None),
                and_(
                    Matter.id.is_not(None),
                    Matter.is_active.is_(True),
                    Matter.status.in_(
                        [
                            MatterStatus.INTAKE.value,
                            MatterStatus.ACTIVE.value,
                            MatterStatus.ON_HOLD.value,
                        ]
                    ),
                ),
            ),
        )
    )
    if not filters.include_inactive:
        statement = statement.where(
            TrademarkApplication.is_active.is_(True),
            IpDocketRecord.is_active.is_(True),
        )
    if filters.matter_id:
        statement = statement.where(IpDocketRecord.matter_id == filters.matter_id)
    if filters.client:
        client_terms = _normalize(filters.client)
        linked_client_match = (
            select(MatterClientAssignment.id)
            .join(Client, Client.id == MatterClientAssignment.client_id)
            .where(
                MatterClientAssignment.matter_id == Matter.id,
                Client.company_id == context.company.id,
                func.lower(Client.name).in_(client_terms),
            )
            .exists()
        )
        statement = statement.where(
            or_(
                func.lower(func.coalesce(Matter.client_name, "")).in_(client_terms),
                linked_client_match,
            )
        )
    if filters.proprietor:
        proprietor_terms = _normalize(filters.proprietor)
        statement = statement.where(
            select(IpPartyAndRole.id)
            .where(
                IpPartyAndRole.company_id == context.company.id,
                IpPartyAndRole.docket_id == IpDocketRecord.id,
                func.lower(IpPartyAndRole.role_kind).in_(PROPRIETOR_ROLES),
                func.lower(IpPartyAndRole.party_name).in_(proprietor_terms),
                IpPartyAndRole.effective_until.is_(None),
            )
            .exists()
        )
    if filters.nice_class:
        statement = statement.where(
            select(TrademarkApplicationScope.id)
            .where(
                TrademarkApplicationScope.company_id == context.company.id,
                TrademarkApplicationScope.application_id == TrademarkApplication.id,
                TrademarkApplicationScope.class_number.in_(filters.nice_class),
                TrademarkApplicationScope.effective_until.is_(None),
            )
            .exists()
        )
    if filters.responsible_membership_id:
        statement = statement.where(
            Matter.responsible_lawyer_membership_id.in_(filters.responsible_membership_id)
        )
    if filters.team_id:
        statement = statement.where(Matter.team_id.in_(filters.team_id))
    if filters.jurisdiction:
        statement = statement.where(
            func.upper(TrademarkApplication.jurisdiction).in_(
                _normalize(filters.jurisdiction, lower=False)
            )
        )
    if filters.office:
        statement = statement.where(TrademarkApplication.office.in_(filters.office))
    if filters.filing_phase:
        statement = statement.where(
            TrademarkApplication.filing_phase.in_(_normalize(filters.filing_phase))
        )
    if filters.asset_kind:
        statement = statement.where(IpAsset.asset_kind.in_(_normalize(filters.asset_kind)))
    if filters.docket_status:
        statement = statement.where(IpDocketRecord.status.in_(_normalize(filters.docket_status)))
    if filters.deadline_state:
        deadline_states = set(_normalize(filters.deadline_state))
        deadline_predicates = []
        if "open" in deadline_states:
            deadline_predicates.append(IpDeadline.state.in_(("confirmed", "overdue")))
        if "unconfirmed" in deadline_states:
            deadline_predicates.append(IpDeadline.state.in_(("candidate", "provisional")))
        if "overdue" in deadline_states:
            deadline_predicates.append(
                and_(
                    IpDeadline.state.in_(("confirmed", "overdue")),
                    IpDeadline.result_on.is_not(None),
                    IpDeadline.result_on < date.today(),
                )
            )
        statement = statement.where(
            select(IpDeadline.id)
            .where(
                IpDeadline.company_id == context.company.id,
                IpDeadline.docket_id == IpDocketRecord.id,
                or_(*deadline_predicates) if deadline_predicates else false(),
            )
            .exists()
        )
    if filters.opposition_only:
        statement = statement.where(
            select(IpProceeding.id)
            .where(
                IpProceeding.company_id == context.company.id,
                IpProceeding.docket_id == IpDocketRecord.id,
                IpProceeding.application_id == TrademarkApplication.id,
                IpProceeding.proceeding_kind == "opposition",
            )
            .exists()
        )
    if filters.registry_sync_state:
        statement = statement.where(
            or_(*[_registry_state_predicate(state) for state in filters.registry_sync_state])
        )
    if filters.query:
        like = f"%{filters.query.strip().lower()}%"
        normalized_identifier = normalize_ip_identifier(filters.query)
        identifier_match = (
            select(IpIdentifier.id)
            .where(
                IpIdentifier.company_id == context.company.id,
                IpIdentifier.docket_id == IpDocketRecord.id,
                IpIdentifier.effective_until.is_(None),
                IpIdentifier.superseded_by_identifier_id.is_(None),
                IpIdentifier.normalized_value == normalized_identifier,
            )
            .exists()
        )
        party_match = (
            select(IpPartyAndRole.id)
            .where(
                IpPartyAndRole.company_id == context.company.id,
                IpPartyAndRole.docket_id == IpDocketRecord.id,
                IpPartyAndRole.effective_until.is_(None),
                func.lower(IpPartyAndRole.party_name).like(like),
            )
            .exists()
        )
        scope_match = (
            select(TrademarkApplicationScope.id)
            .where(
                TrademarkApplicationScope.company_id == context.company.id,
                TrademarkApplicationScope.application_id == TrademarkApplication.id,
                TrademarkApplicationScope.effective_until.is_(None),
                or_(
                    func.lower(TrademarkApplicationScope.specification).like(like),
                    func.cast(TrademarkApplicationScope.class_number, String).like(
                        filters.query.strip()
                    ),
                ),
            )
            .exists()
        )
        linked_client_match = (
            select(MatterClientAssignment.id)
            .join(Client, Client.id == MatterClientAssignment.client_id)
            .where(
                MatterClientAssignment.matter_id == Matter.id,
                Client.company_id == context.company.id,
                func.lower(Client.name).like(like),
            )
            .exists()
        )
        lawyer_match = (
            select(CompanyMembership.id)
            .join(User, User.id == CompanyMembership.user_id)
            .where(
                CompanyMembership.id == Matter.responsible_lawyer_membership_id,
                CompanyMembership.company_id == context.company.id,
                func.lower(User.full_name).like(like),
            )
            .exists()
        )
        team_match = (
            select(Team.id)
            .where(
                Team.id == Matter.team_id,
                Team.company_id == context.company.id,
                func.lower(Team.name).like(like),
            )
            .exists()
        )
        statement = statement.where(
            or_(
                func.lower(IpDocketRecord.title).like(like),
                func.lower(func.coalesce(IpAsset.title, "")).like(like),
                func.lower(func.coalesce(Matter.client_name, "")).like(like),
                identifier_match,
                party_match,
                scope_match,
                linked_client_match,
                lawyer_match,
                team_match,
            )
        )
    return statement


def _deadline_counts(session: Session, *, company_id: str, docket_ids: list[str]) -> dict:
    if not docket_ids:
        return {}
    today = date.today()
    rows = session.execute(
        select(
            IpDeadline.docket_id,
            func.count().filter(IpDeadline.state.in_(("confirmed", "overdue"))),
            func.count().filter(IpDeadline.state.in_(("candidate", "provisional"))),
            func.count().filter(
                IpDeadline.state.in_(("confirmed", "overdue")),
                IpDeadline.result_on.is_not(None),
                IpDeadline.result_on < today,
            ),
        )
        .where(
            IpDeadline.company_id == company_id,
            IpDeadline.docket_id.in_(docket_ids),
        )
        .group_by(IpDeadline.docket_id)
    ).all()
    return {row[0]: (int(row[1]), int(row[2]), int(row[3])) for row in rows}


def _portfolio_details(
    session: Session,
    *,
    company_id: str,
    application_ids: list[str],
    docket_ids: list[str],
) -> dict[str, dict[str, list]]:
    details = {
        application_id: {
            "application_numbers": [],
            "opposition_numbers": [],
            "nice_classes": [],
            "goods_services": [],
            "representation_kinds": [],
            "proprietors": [],
            "agents": [],
            "provenance": ["CaseOps legal record"],
        }
        for application_id in application_ids
    }
    if not application_ids:
        return details

    docket_to_applications: dict[str, list[str]] = {}
    for application_id, docket_id in session.execute(
        select(TrademarkApplication.id, TrademarkApplication.docket_id).where(
            TrademarkApplication.company_id == company_id,
            TrademarkApplication.id.in_(application_ids),
        )
    ):
        docket_to_applications.setdefault(docket_id, []).append(application_id)

    for identifier in session.scalars(
        select(IpIdentifier).where(
            IpIdentifier.company_id == company_id,
            IpIdentifier.docket_id.in_(docket_ids),
            IpIdentifier.effective_until.is_(None),
            IpIdentifier.superseded_by_identifier_id.is_(None),
        )
    ):
        targets = (
            [identifier.application_id]
            if identifier.application_id in details
            else docket_to_applications.get(identifier.docket_id, [])
        )
        if identifier.identifier_kind == "application":
            field = "application_numbers"
        elif identifier.identifier_kind == "opposition":
            field = "opposition_numbers"
        else:
            continue
        for target in targets:
            bucket = details[target]
            if identifier.raw_value not in bucket[field]:
                bucket[field].append(identifier.raw_value)
            provenance = f"Identifier: {identifier.source}"
            if provenance not in bucket["provenance"]:
                bucket["provenance"].append(provenance)

    today = date.today()
    for scope in session.scalars(
        select(TrademarkApplicationScope).where(
            TrademarkApplicationScope.company_id == company_id,
            TrademarkApplicationScope.application_id.in_(application_ids),
            TrademarkApplicationScope.effective_from <= today,
            or_(
                TrademarkApplicationScope.effective_until.is_(None),
                TrademarkApplicationScope.effective_until >= today,
            ),
        )
    ):
        bucket = details[scope.application_id]
        if scope.class_number not in bucket["nice_classes"]:
            bucket["nice_classes"].append(scope.class_number)
        if scope.specification not in bucket["goods_services"]:
            bucket["goods_services"].append(scope.specification)
        provenance = f"Class scope: {scope.source}"
        if provenance not in bucket["provenance"]:
            bucket["provenance"].append(provenance)

    for representation in session.scalars(
        select(TrademarkRepresentation).where(
            TrademarkRepresentation.company_id == company_id,
            TrademarkRepresentation.application_id.in_(application_ids),
        )
    ):
        kinds = details[representation.application_id]["representation_kinds"]
        if representation.representation_kind not in kinds:
            kinds.append(representation.representation_kind)

    for party in session.scalars(
        select(IpPartyAndRole).where(
            IpPartyAndRole.company_id == company_id,
            IpPartyAndRole.docket_id.in_(docket_ids),
            IpPartyAndRole.effective_from <= today,
            or_(
                IpPartyAndRole.effective_until.is_(None),
                IpPartyAndRole.effective_until >= today,
            ),
        )
    ):
        role = party.role_kind.casefold()
        if role in AGENT_ROLES:
            field = "agents"
        elif role in PROPRIETOR_ROLES:
            field = "proprietors"
        else:
            continue
        for target in docket_to_applications.get(party.docket_id, []):
            if party.party_name not in details[target][field]:
                details[target][field].append(party.party_name)
            provenance = f"Party: {party.source}"
            if provenance not in details[target]["provenance"]:
                details[target]["provenance"].append(provenance)

    for particulars in session.scalars(
        select(IpTrademarkParticularVersion)
        .join(
            IpDocketRecord,
            and_(
                IpDocketRecord.id == IpTrademarkParticularVersion.docket_id,
                IpDocketRecord.company_id == IpTrademarkParticularVersion.company_id,
                IpDocketRecord.current_version == IpTrademarkParticularVersion.version,
            ),
        )
        .where(
            IpTrademarkParticularVersion.company_id == company_id,
            IpTrademarkParticularVersion.docket_id.in_(docket_ids),
        )
    ):
        for target in docket_to_applications.get(particulars.docket_id, []):
            bucket = details[target]
            if particulars.mark_kind not in bucket["representation_kinds"]:
                bucket["representation_kinds"].append(particulars.mark_kind)
            for scope in particulars.classes_json or []:
                class_number = scope.get("class_number")
                specification = scope.get("specification")
                if isinstance(class_number, int) and class_number not in bucket["nice_classes"]:
                    bucket["nice_classes"].append(class_number)
                if isinstance(specification, str) and specification not in bucket["goods_services"]:
                    bucket["goods_services"].append(specification)
            for party in particulars.parties_json or []:
                role = str(party.get("role", "")).casefold()
                name = party.get("name")
                if role in PROPRIETOR_ROLES and isinstance(name, str):
                    if name not in bucket["proprietors"]:
                        bucket["proprietors"].append(name)
            agent_name = (particulars.agent_json or {}).get("name")
            if isinstance(agent_name, str) and agent_name not in bucket["agents"]:
                bucket["agents"].append(agent_name)
            provenance = f"Docket particulars: version {particulars.version}"
            if provenance not in bucket["provenance"]:
                bucket["provenance"].append(provenance)

    for bucket in details.values():
        for key in bucket:
            bucket[key] = sorted(bucket[key])
    return details


def _matter_details(
    session: Session,
    *,
    company_id: str,
    matter_ids: list[str],
) -> dict[str, dict[str, str | None]]:
    if not matter_ids:
        return {}
    matters = list(
        session.scalars(
            select(Matter).where(Matter.company_id == company_id, Matter.id.in_(matter_ids))
        ).all()
    )
    details = {
        matter.id: {
            "client_name": matter.client_name,
            "responsible_membership_id": matter.responsible_lawyer_membership_id,
            "responsible_lawyer": None,
            "team_id": matter.team_id,
            "team_name": None,
        }
        for matter in matters
    }
    for matter_id, client_name in session.execute(
        select(MatterClientAssignment.matter_id, Client.name)
        .join(Client, Client.id == MatterClientAssignment.client_id)
        .where(
            MatterClientAssignment.matter_id.in_(matter_ids),
            MatterClientAssignment.is_primary.is_(True),
            Client.company_id == company_id,
        )
    ):
        if matter_id in details:
            details[matter_id]["client_name"] = client_name
    membership_ids = {
        value["responsible_membership_id"]
        for value in details.values()
        if value["responsible_membership_id"]
    }
    if membership_ids:
        for membership_id, full_name in session.execute(
            select(CompanyMembership.id, User.full_name)
            .join(User, User.id == CompanyMembership.user_id)
            .where(
                CompanyMembership.company_id == company_id,
                CompanyMembership.id.in_(membership_ids),
            )
        ):
            for value in details.values():
                if value["responsible_membership_id"] == membership_id:
                    value["responsible_lawyer"] = full_name
    team_ids = {value["team_id"] for value in details.values() if value["team_id"]}
    if team_ids:
        team_names = dict(
            session.execute(
                select(Team.id, Team.name).where(
                    Team.company_id == company_id,
                    Team.id.in_(team_ids),
                )
            ).all()
        )
        for value in details.values():
            value["team_name"] = team_names.get(value["team_id"])
    return details


def _registry_sync_details(
    session: Session,
    *,
    company_id: str,
    docket_ids: list[str],
) -> dict[str, tuple[str, datetime | None]]:
    latest_by_docket = dict(
        session.execute(
            select(IpDocketEvent.docket_id, func.max(IpDocketEvent.entered_at))
            .where(
                IpDocketEvent.company_id == company_id,
                IpDocketEvent.docket_id.in_(docket_ids),
                IpDocketEvent.source == "registry_sync",
                IpDocketEvent.candidate_status == "confirmed",
            )
            .group_by(IpDocketEvent.docket_id)
        ).all()
    )
    threshold = datetime.now(UTC) - REGISTRY_FRESHNESS_WINDOW
    result: dict[str, tuple[str, datetime | None]] = {}
    for docket_id in docket_ids:
        latest = latest_by_docket.get(docket_id)
        if latest is None:
            result[docket_id] = ("unavailable", None)
            continue
        aware = latest if latest.tzinfo else latest.replace(tzinfo=UTC)
        result[docket_id] = ("current" if aware >= threshold else "stale", latest)
    return result


def _portfolio_counts(
    session: Session,
    *,
    context: SessionContext,
    statement: Select,
) -> tuple[IpPortfolioCounts, datetime | None, datetime | None]:
    projection = (
        statement.with_only_columns(
            TrademarkApplication.id.label("application_id"),
            IpDocketRecord.id.label("docket_id"),
            _primary_application_identifier().label("primary_identifier"),
            TrademarkApplication.source_pending_identifier_allocation.label("pending_identifier"),
            TrademarkApplication.office.label("office"),
            TrademarkApplication.jurisdiction.label("jurisdiction"),
            TrademarkApplication.updated_at.label("record_updated_at"),
            IpAsset.id.label("asset_id"),
            IpAsset.title.label("asset_title"),
            _latest_registry_sync_at().label("registry_last_success_at"),
        )
        .order_by(None)
        .subquery()
    )
    complete = and_(
        projection.c.asset_id.is_not(None),
        func.trim(func.coalesce(projection.c.asset_title, "")) != "",
        projection.c.primary_identifier.is_not(None),
        projection.c.pending_identifier.is_(False),
        func.trim(func.coalesce(projection.c.office, "")) != "",
        func.trim(func.coalesce(projection.c.jurisdiction, "")) != "",
    )
    today = date.today()
    unconfirmed_dockets = select(IpDeadline.docket_id).where(
        IpDeadline.company_id == context.company.id,
        IpDeadline.state.in_(("candidate", "provisional")),
    )
    overdue_dockets = select(IpDeadline.docket_id).where(
        IpDeadline.company_id == context.company.id,
        IpDeadline.state.in_(("confirmed", "overdue")),
        IpDeadline.result_on.is_not(None),
        IpDeadline.result_on < today,
    )
    freshness_threshold = datetime.now(UTC) - REGISTRY_FRESHNESS_WINDOW
    (
        total,
        complete_records,
        unconfirmed,
        overdue,
        stale,
        synchronized,
        latest_record_updated_at,
        latest_registry_success_at,
    ) = session.execute(
        select(
            func.count(),
            func.count().filter(complete),
            func.count().filter(projection.c.docket_id.in_(unconfirmed_dockets)),
            func.count().filter(projection.c.docket_id.in_(overdue_dockets)),
            func.count().filter(
                and_(
                    projection.c.registry_last_success_at.is_not(None),
                    projection.c.registry_last_success_at < freshness_threshold,
                )
            ),
            func.count().filter(projection.c.registry_last_success_at.is_not(None)),
            func.max(projection.c.record_updated_at),
            func.max(projection.c.registry_last_success_at),
        ).select_from(projection)
    ).one()
    total = int(total or 0)
    complete_records = int(complete_records or 0)
    synchronized = int(synchronized or 0)
    return (
        IpPortfolioCounts(
            total=total,
            complete_records=complete_records,
            incomplete_records=total - complete_records,
            unconfirmed_deadline_records=int(unconfirmed or 0),
            overdue_records=int(overdue or 0),
            stale_sync_records=int(stale or 0),
            synchronized_records=synchronized,
            sync_failure_records=None,
            registry_sync_state="available" if synchronized else "unavailable",
        ),
        latest_record_updated_at,
        latest_registry_success_at,
    )


def _incomplete_reasons(
    application: TrademarkApplication,
    asset: IpAsset | None,
    primary_identifier: str | None,
) -> list[str]:
    reasons: list[str] = []
    if asset is None:
        reasons.append("missing_mark")
    elif not (asset.title or "").strip():
        reasons.append("missing_mark_title")
    if not primary_identifier:
        reasons.append("missing_identifier")
    if application.source_pending_identifier_allocation:
        reasons.append("pending_identifier_allocation")
    if not application.office:
        reasons.append("missing_office")
    if not application.jurisdiction:
        reasons.append("missing_jurisdiction")
    return reasons


def list_ip_portfolio(
    session: Session,
    *,
    context: SessionContext,
    filters: IpPortfolioFilters,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> IpPortfolioListResponse:
    if not 1 <= limit <= MAX_LIMIT:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200.")

    statement = _scoped_query(session, context=context, filters=filters)
    page = statement.order_by(
        TrademarkApplication.updated_at.desc(), TrademarkApplication.id.desc()
    )
    if cursor:
        timestamp, application_id = _decode_cursor(cursor)
        page = page.where(
            or_(
                TrademarkApplication.updated_at < timestamp,
                (TrademarkApplication.updated_at == timestamp)
                & (TrademarkApplication.id < application_id),
            )
        )

    # One extra row tells us whether another page exists without a second count.
    candidates = list(session.execute(page.limit(limit + 1)).all())
    has_more = len(candidates) > limit
    candidates = candidates[:limit]

    visible = candidates

    application_ids = [application.id for application, _asset, _docket in visible]
    docket_ids = [docket.id for _a, _s, docket in visible]
    matter_ids = list({docket.matter_id for _a, _s, docket in visible if docket.matter_id})
    deadlines = _deadline_counts(session, company_id=context.company.id, docket_ids=docket_ids)
    details = _portfolio_details(
        session,
        company_id=context.company.id,
        application_ids=application_ids,
        docket_ids=docket_ids,
    )
    primary_identifiers = _primary_application_identifiers(
        session,
        company_id=context.company.id,
        application_ids=application_ids,
    )
    matters = _matter_details(
        session,
        company_id=context.company.id,
        matter_ids=matter_ids,
    )
    registry_sync = _registry_sync_details(
        session,
        company_id=context.company.id,
        docket_ids=docket_ids,
    )

    rows: list[IpPortfolioRow] = []
    for application, asset, docket in visible:
        open_count, unconfirmed, overdue = deadlines.get(docket.id, (0, 0, 0))
        primary_identifier = primary_identifiers.get(application.id)
        reasons = _incomplete_reasons(application, asset, primary_identifier)
        detail = details[application.id]
        matter_detail = matters.get(docket.matter_id or "", {})
        registry_state, registry_at = registry_sync[docket.id]
        rows.append(
            IpPortfolioRow(
                application_id=application.id,
                docket_id=docket.id,
                matter_id=docket.matter_id,
                asset_id=application.asset_id,
                asset_kind=asset.asset_kind if asset else None,
                asset_title=asset.title if asset else None,
                asset_jurisdiction=asset.jurisdiction if asset else None,
                docket_title=docket.title,
                docket_status=docket.status,
                primary_identifier=primary_identifier,
                application_numbers=detail["application_numbers"],
                opposition_numbers=detail["opposition_numbers"],
                nice_classes=detail["nice_classes"],
                goods_services=detail["goods_services"],
                representation_kinds=detail["representation_kinds"],
                proprietors=detail["proprietors"],
                agents=detail["agents"],
                client_name=matter_detail.get("client_name"),
                responsible_lawyer=matter_detail.get("responsible_lawyer"),
                responsible_membership_id=matter_detail.get("responsible_membership_id"),
                team_name=matter_detail.get("team_name"),
                team_id=matter_detail.get("team_id"),
                office=application.office,
                jurisdiction=application.jurisdiction,
                filing_phase=application.filing_phase,
                is_active=application.is_active,
                lifecycle_version=application.lifecycle_version,
                pending_identifier_allocation=(application.source_pending_identifier_allocation),
                record_complete=not reasons,
                incomplete_reasons=reasons,
                open_deadline_count=open_count,
                unconfirmed_deadline_count=unconfirmed,
                overdue_deadline_count=overdue,
                registry_sync_state=registry_state,
                registry_last_success_at=registry_at,
                provenance=detail["provenance"],
                application_created_at=application.created_at,
                updated_at=application.updated_at,
            )
        )

    counts, latest_record_updated_at, latest_registry_success_at = _portfolio_counts(
        session,
        context=context,
        statement=statement,
    )
    next_cursor = (
        _encode_cursor(rows[-1].updated_at, rows[-1].application_id) if has_more and rows else None
    )
    return IpPortfolioListResponse(
        rows=rows,
        counts=counts,
        filters=filters,
        limit=limit,
        next_cursor=next_cursor,
        latest_record_updated_at=latest_record_updated_at,
        latest_registry_success_at=latest_registry_success_at,
    )


def list_ip_portfolio_families(
    session: Session,
    *,
    context: SessionContext,
    grouping: str,
    filters: IpPortfolioFilters,
    limit: int = DEFAULT_FAMILY_LIMIT,
    cursor: str | None = None,
) -> IpPortfolioFamilyResponse:
    """IP-PROS-11 — group related applications without merging their identity.

    Grouping is presentational. Each member keeps its own application id,
    identifier, office, jurisdiction, filing phase and lifecycle version, and a
    family deliberately exposes no shared phase, deadline or identifier.
    """

    if grouping not in {"mark", "client"}:
        raise HTTPException(status_code=400, detail="grouping must be 'mark' or 'client'.")
    if limit < 1 or limit > MAX_FAMILY_LIMIT:
        raise HTTPException(
            status_code=422,
            detail=f"Family limit must be between 1 and {MAX_FAMILY_LIMIT}.",
        )

    statement = _scoped_query(session, context=context, filters=filters)
    if grouping == "mark":
        family_key_expression = TrademarkApplication.asset_id
        family_label_expression = func.coalesce(IpAsset.title, "")
    else:
        family_key_expression, family_label_expression = _primary_client_expressions(
            context.company.id
        )

    member_count_expression = func.count(TrademarkApplication.id)
    label_sort_expression = func.lower(func.coalesce(family_label_expression, ""))
    family_statement = (
        statement.with_only_columns(
            family_key_expression.label("family_key"),
            family_label_expression.label("family_label"),
            member_count_expression.label("member_count"),
        )
        .where(family_key_expression.is_not(None))
        .group_by(family_key_expression, family_label_expression)
    )
    if cursor:
        cursor_count, cursor_label, cursor_key = _decode_family_cursor(cursor)
        family_statement = family_statement.having(
            or_(
                member_count_expression < cursor_count,
                and_(
                    member_count_expression == cursor_count,
                    label_sort_expression > cursor_label,
                ),
                and_(
                    member_count_expression == cursor_count,
                    label_sort_expression == cursor_label,
                    family_key_expression > cursor_key,
                ),
            )
        )
    family_rows = list(
        session.execute(
            family_statement.order_by(
                member_count_expression.desc(),
                label_sort_expression,
                family_key_expression,
            ).limit(limit + 1)
        ).all()
    )
    has_more = len(family_rows) > limit
    family_rows = family_rows[:limit]
    selected_keys = [row.family_key for row in family_rows]

    if selected_keys:
        visible = list(
            session.execute(
                statement.add_columns(family_key_expression.label("family_key"))
                .where(family_key_expression.in_(selected_keys))
                .order_by(TrademarkApplication.id)
            ).all()
        )
    else:
        visible = []

    ungrouped = int(
        session.scalar(
            statement.with_only_columns(func.count(TrademarkApplication.id))
            .where(family_key_expression.is_(None))
            .order_by(None)
        )
        or 0
    )

    deadlines = _deadline_counts(
        session,
        company_id=context.company.id,
        docket_ids=[docket.id for _a, _s, docket, _family_key in visible],
    )
    primary_identifiers = _primary_application_identifiers(
        session,
        company_id=context.company.id,
        application_ids=[
            application.id for application, _asset, _docket, _family_key in visible
        ],
    )

    grouped: dict[str, dict] = {}
    labels_by_key = {row.family_key: row.family_label or "" for row in family_rows}
    for application, _asset, docket, key in visible:
        label = labels_by_key[key]
        open_count, _unconfirmed, overdue = deadlines.get(docket.id, (0, 0, 0))
        bucket = grouped.setdefault(key, {"label": label, "members": []})
        if not bucket["label"]:
            bucket["label"] = label
        bucket["members"].append(
            IpPortfolioFamilyMember(
                application_id=application.id,
                docket_id=docket.id,
                asset_id=application.asset_id,
                office=application.office,
                jurisdiction=application.jurisdiction,
                filing_phase=application.filing_phase,
                lifecycle_version=application.lifecycle_version,
                primary_identifier=primary_identifiers.get(application.id),
                open_deadline_count=open_count,
                overdue_deadline_count=overdue,
            )
        )

    family_by_key = {
        key: IpPortfolioFamily(
            grouping=grouping,
            family_key=key,
            label=bucket["label"],
            member_count=len(bucket["members"]),
            distinct_jurisdictions=sorted(
                {m.jurisdiction for m in bucket["members"] if m.jurisdiction}
            ),
            distinct_filing_phases=sorted(
                {m.filing_phase for m in bucket["members"]}
            ),
            members=sorted(
                bucket["members"], key=lambda m: (m.jurisdiction or "", m.application_id)
            ),
        )
        for key, bucket in grouped.items()
    }
    families = [
        family_by_key[row.family_key]
        for row in family_rows
        if row.family_key in family_by_key
    ]
    next_cursor = None
    if has_more and family_rows:
        last = family_rows[-1]
        next_cursor = _encode_family_cursor(
            int(last.member_count),
            last.family_label or "",
            last.family_key,
        )
    return IpPortfolioFamilyResponse(
        grouping=grouping,
        families=families,
        ungrouped_member_count=ungrouped,
        limit=limit,
        next_cursor=next_cursor,
    )


__all__ = ["list_ip_portfolio", "list_ip_portfolio_families"]
