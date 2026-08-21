"""Canonical contracts for IP record identity and identifier history."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from hashlib import sha256
from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    IpAsset,
    IpIdentifier,
    IpPartyAndRole,
    IpProceeding,
    IpTrademarkParticularVersion,
    TrademarkApplication,
    TrademarkApplicationScope,
    TrademarkRepresentation,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.ip_identifier_rules import normalize_ip_identifier
from caseops_api.services.session_context import SessionContext

if TYPE_CHECKING:
    from caseops_api.schemas.ip_operations import ManualTrademarkApplicationCreateRequest
    from caseops_api.schemas.ip_records import (
        IpAssetCreateRequest,
        IpIdentifierCorrectionCreate,
        IpIdentifierCreate,
        IpProceedingCreateRequest,
        TrademarkApplicationCreateRequest,
        TrademarkApplicationPhaseUpdateRequest,
    )


def _project_current_particulars(
    session: Session,
    *,
    application: TrademarkApplication,
    docket,
) -> None:
    particulars = session.scalar(
        select(IpTrademarkParticularVersion).where(
            IpTrademarkParticularVersion.company_id == application.company_id,
            IpTrademarkParticularVersion.docket_id == docket.id,
            IpTrademarkParticularVersion.version == docket.current_version,
        )
    )
    if particulars is None:
        return
    effective_from = date.today()
    source = f"docket_particulars:v{particulars.version}"
    for scope in particulars.classes_json or []:
        class_number = scope.get("class_number")
        specification = scope.get("specification")
        if not isinstance(class_number, int) or not isinstance(specification, str):
            continue
        session.add(
            TrademarkApplicationScope(
                company_id=application.company_id,
                application_id=application.id,
                class_number=class_number,
                specification=specification,
                effective_from=effective_from,
                source=source,
            )
        )
    representation_payload = json.dumps(
        particulars.representation_json,
        sort_keys=True,
        separators=(",", ":"),
    )
    session.add(
        TrademarkRepresentation(
            company_id=application.company_id,
            application_id=application.id,
            version=particulars.version,
            representation_kind=particulars.mark_kind,
            display_text=(particulars.representation_json or {}).get("text"),
            document_reference=(particulars.representation_json or {}).get(
                "document_reference"
            ),
            content_sha256=sha256(representation_payload.encode()).hexdigest(),
            metadata_json={"source": source},
        )
    )
    current_parties = {
        (row.role_kind.casefold(), row.party_name.casefold())
        for row in session.scalars(
            select(IpPartyAndRole).where(
                IpPartyAndRole.company_id == application.company_id,
                IpPartyAndRole.docket_id == docket.id,
                IpPartyAndRole.effective_until.is_(None),
            )
        )
    }
    parties = list(particulars.parties_json or [])
    if particulars.agent_json:
        parties.append({"role": "agent", "name": particulars.agent_json.get("name")})
    for party in parties:
        role = str(party.get("role", "")).strip().casefold()
        name = str(party.get("name", "")).strip()
        if not role or not name or (role, name.casefold()) in current_parties:
            continue
        session.add(
            IpPartyAndRole(
                company_id=application.company_id,
                docket_id=docket.id,
                party_name=name,
                role_kind=role,
                effective_from=effective_from,
                source=source,
            )
        )
        current_parties.add((role, name.casefold()))

def assert_application_can_enter_filed_phase(
    application: TrademarkApplication,
    identifiers: Iterable[IpIdentifier],
) -> None:
    if application.source_pending_identifier_allocation:
        return
    has_current_application_number = any(
        row.identifier_kind == "application"
        and row.application_id == application.id
        and row.effective_until is None
        and row.reconciliation_status == "confirmed"
        for row in identifiers
    )
    if not has_current_application_number:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_application_identifier_required",
                "message": (
                    "A confirmed current application number is required before "
                    "the filing can enter filed phase."
                ),
            },
        )


def _docket(
    session: Session,
    context: SessionContext,
    docket_id: str,
    *,
    for_update: bool = True,
):
    # Reuse the existing docket access/lifecycle guard so core-IP commands
    # cannot invent a second authorization or terminal-state policy.
    from caseops_api.services.ip_operations import _docket_or_404

    return _docket_or_404(
        session,
        context=context,
        docket_id=docket_id,
        for_update=for_update,
    )


def _duplicate_identifiers(
    session: Session,
    *,
    company_id: str,
    identifier_kind: str,
    office: str,
    jurisdiction: str,
    normalized_value: str,
    exclude_ids: set[str] | None = None,
) -> list[IpIdentifier]:
    rows = list(
        session.scalars(
            select(IpIdentifier)
            .where(
                IpIdentifier.company_id == company_id,
                IpIdentifier.identifier_kind == identifier_kind,
                IpIdentifier.office == office,
                IpIdentifier.jurisdiction == jurisdiction,
                IpIdentifier.normalized_value == normalized_value,
                IpIdentifier.effective_until.is_(None),
            )
            .order_by(IpIdentifier.created_at, IpIdentifier.id)
        ).all()
    )
    excluded = exclude_ids or set()
    return [row for row in rows if row.id not in excluded]


def create_ip_asset(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpAssetCreateRequest,
    commit: bool = True,
) -> IpAsset:
    docket = _docket(session, context, docket_id)
    existing = session.scalar(
        select(IpAsset).where(
            IpAsset.company_id == context.company.id,
            IpAsset.docket_id == docket.id,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="This docket already has a canonical IP asset.")
    row = IpAsset(
        company_id=context.company.id,
        docket_id=docket.id,
        asset_kind=payload.asset_kind,
        jurisdiction=payload.jurisdiction,
        title=payload.title,
    )
    session.add(row)
    session.flush()
    record_from_context(
        session,
        context,
        action="ip_asset.created",
        target_type="ip_asset",
        target_id=row.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={"docket_id": docket.id, "asset_kind": row.asset_kind},
    )
    if commit:
        session.commit()
        session.refresh(row)
    else:
        session.flush()
    return row


def create_trademark_application(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: TrademarkApplicationCreateRequest,
    commit: bool = True,
) -> tuple[TrademarkApplication, IpIdentifier | None, list[IpIdentifier]]:
    docket = _docket(session, context, docket_id)
    asset = session.scalar(
        select(IpAsset).where(
            IpAsset.id == payload.asset_id,
            IpAsset.company_id == context.company.id,
            IpAsset.docket_id == docket.id,
        )
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="IP asset not found.")
    row = TrademarkApplication(
        company_id=context.company.id,
        docket_id=docket.id,
        asset_id=asset.id,
        office=payload.office,
        jurisdiction=payload.jurisdiction,
        filing_phase="draft",
        source_pending_identifier_allocation=payload.source_pending_identifier_allocation,
    )
    session.add(row)
    session.flush()
    identifier: IpIdentifier | None = None
    duplicates: list[IpIdentifier] = []
    if payload.application_number is not None:
        number = payload.application_number
        normalized = normalize_ip_identifier(number.raw_value)
        duplicates = _duplicate_identifiers(
            session,
            company_id=context.company.id,
            identifier_kind="application",
            office=payload.office,
            jurisdiction=payload.jurisdiction,
            normalized_value=normalized,
        )
        identifier = IpIdentifier(
            company_id=context.company.id,
            docket_id=docket.id,
            application_id=row.id,
            proceeding_id=None,
            identifier_kind="application",
            raw_value=number.raw_value,
            normalized_value=normalized,
            office=payload.office,
            jurisdiction=payload.jurisdiction,
            source=number.source,
            effective_from=number.effective_from,
            is_primary=number.is_primary,
            reconciliation_status="needs_review" if duplicates else "confirmed",
        )
        session.add(identifier)
        session.flush()
    if payload.filing_phase == "filed":
        assert_application_can_enter_filed_phase(
            row,
            [identifier] if identifier is not None else [],
        )
    row.filing_phase = payload.filing_phase
    _project_current_particulars(
        session,
        application=row,
        docket=docket,
    )
    record_from_context(
        session,
        context,
        action="ip_application.created",
        target_type="trademark_application",
        target_id=row.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "docket_id": docket.id,
            "asset_id": asset.id,
            "filing_phase": row.filing_phase,
            "identifier_id": identifier.id if identifier else None,
            "duplicate_candidate_ids": [candidate.id for candidate in duplicates],
        },
    )
    if commit:
        session.commit()
        session.refresh(row)
        if identifier is not None:
            session.refresh(identifier)
    else:
        session.flush()
    return row, identifier, duplicates


def create_manual_trademark_application(
    session: Session,
    *,
    context: SessionContext,
    payload: ManualTrademarkApplicationCreateRequest,
) -> tuple[
    str,
    IpAsset,
    TrademarkApplication,
    IpIdentifier | None,
    list[IpIdentifier],
]:
    """Materialize the complete manual record through the canonical writers."""

    from caseops_api.schemas.ip_operations import IpDocketCreateRequest
    from caseops_api.schemas.ip_records import (
        IpAssetCreateRequest,
        TrademarkApplicationCreateRequest,
    )
    from caseops_api.services.ip_operations import create_ip_docket

    try:
        docket = create_ip_docket(
            session,
            context=context,
            payload=IpDocketCreateRequest(
                title=payload.title,
                matter_id=payload.matter_id,
                primary_identifier=None,
                restricted=payload.restricted,
                particulars=payload.particulars,
            ),
            commit=False,
        )
        asset = create_ip_asset(
            session,
            context=context,
            docket_id=docket.id,
            payload=IpAssetCreateRequest(
                asset_kind="trademark",
                jurisdiction=payload.jurisdiction,
                title=payload.asset_title,
            ),
            commit=False,
        )
        application, identifier, duplicates = create_trademark_application(
            session,
            context=context,
            docket_id=docket.id,
            payload=TrademarkApplicationCreateRequest(
                asset_id=asset.id,
                office=payload.office,
                jurisdiction=payload.jurisdiction,
                filing_phase=payload.filing_phase,
                source_pending_identifier_allocation=(
                    payload.source_pending_identifier_allocation
                ),
                application_number=payload.application_number,
            ),
            commit=False,
        )
        session.commit()
        session.refresh(asset)
        session.refresh(application)
        if identifier is not None:
            session.refresh(identifier)
        return docket.id, asset, application, identifier, duplicates
    except Exception:
        session.rollback()
        raise


def create_ip_proceeding(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpProceedingCreateRequest,
) -> IpProceeding:
    docket = _docket(session, context, docket_id)
    if payload.application_id is not None:
        application = session.scalar(
            select(TrademarkApplication).where(
                TrademarkApplication.id == payload.application_id,
                TrademarkApplication.company_id == context.company.id,
                TrademarkApplication.docket_id == docket.id,
            )
        )
        if application is None:
            raise HTTPException(status_code=404, detail="Trademark application not found.")
    row = IpProceeding(
        company_id=context.company.id,
        docket_id=docket.id,
        application_id=payload.application_id,
        proceeding_kind=payload.proceeding_kind,
        side=payload.side,
        office=payload.office,
        jurisdiction=payload.jurisdiction,
        stage=payload.stage,
    )
    session.add(row)
    session.flush()
    record_from_context(
        session,
        context,
        action="ip_proceeding.created",
        target_type="ip_proceeding",
        target_id=row.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={"docket_id": docket.id, "proceeding_kind": row.proceeding_kind},
    )
    session.commit()
    session.refresh(row)
    return row


def create_ip_identifier(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpIdentifierCreate,
) -> tuple[IpIdentifier, list[IpIdentifier]]:
    docket = _docket(session, context, docket_id)
    _assert_identifier_owner_exists(
        session,
        company_id=context.company.id,
        docket_id=docket.id,
        application_id=payload.application_id,
        proceeding_id=payload.proceeding_id,
    )
    duplicates = _duplicate_identifiers(
        session,
        company_id=context.company.id,
        identifier_kind=payload.identifier_kind,
        office=payload.office,
        jurisdiction=payload.jurisdiction,
        normalized_value=payload.normalized_value,
    )
    if payload.is_primary:
        _clear_current_primary(
            session,
            company_id=context.company.id,
            identifier_kind=payload.identifier_kind,
            application_id=payload.application_id,
            proceeding_id=payload.proceeding_id,
        )
    row = IpIdentifier(
        company_id=context.company.id,
        docket_id=docket.id,
        application_id=payload.application_id,
        proceeding_id=payload.proceeding_id,
        identifier_kind=payload.identifier_kind,
        raw_value=payload.raw_value,
        normalized_value=payload.normalized_value,
        office=payload.office,
        jurisdiction=payload.jurisdiction,
        source=payload.source,
        effective_from=payload.effective_from,
        effective_until=payload.effective_until,
        is_primary=payload.is_primary,
        reconciliation_status="needs_review" if duplicates else "confirmed",
    )
    session.add(row)
    session.flush()
    record_from_context(
        session,
        context,
        action="ip_identifier.created",
        target_type="ip_identifier",
        target_id=row.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "docket_id": docket.id,
            "identifier_kind": row.identifier_kind,
            "source": row.source,
            "reconciliation_status": row.reconciliation_status,
            "duplicate_candidate_ids": [candidate.id for candidate in duplicates],
        },
    )
    session.commit()
    session.refresh(row)
    return row, duplicates


def _assert_identifier_owner_exists(
    session: Session,
    *,
    company_id: str,
    docket_id: str,
    application_id: str | None,
    proceeding_id: str | None,
) -> None:
    if application_id is not None:
        owner = session.scalar(
            select(TrademarkApplication.id).where(
                TrademarkApplication.id == application_id,
                TrademarkApplication.company_id == company_id,
                TrademarkApplication.docket_id == docket_id,
            )
        )
    else:
        owner = session.scalar(
            select(IpProceeding.id).where(
                IpProceeding.id == proceeding_id,
                IpProceeding.company_id == company_id,
                IpProceeding.docket_id == docket_id,
            )
        )
    if owner is None:
        raise HTTPException(status_code=404, detail="Identifier owner not found.")


def _clear_current_primary(
    session: Session,
    *,
    company_id: str,
    identifier_kind: str,
    application_id: str | None,
    proceeding_id: str | None,
) -> None:
    rows = session.scalars(
        select(IpIdentifier).where(
            IpIdentifier.company_id == company_id,
            IpIdentifier.identifier_kind == identifier_kind,
            IpIdentifier.application_id == application_id,
            IpIdentifier.proceeding_id == proceeding_id,
            IpIdentifier.effective_until.is_(None),
            IpIdentifier.is_primary.is_(True),
        )
    ).all()
    for row in rows:
        row.is_primary = False


def correct_ip_identifier(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    identifier_id: str,
    payload: IpIdentifierCorrectionCreate,
) -> tuple[IpIdentifier, list[IpIdentifier]]:
    docket = _docket(session, context, docket_id)
    previous = session.scalar(
        select(IpIdentifier)
        .where(
            IpIdentifier.id == identifier_id,
            IpIdentifier.company_id == context.company.id,
            IpIdentifier.docket_id == docket.id,
        )
        .with_for_update()
    )
    if previous is None:
        raise HTTPException(status_code=404, detail="IP identifier not found.")
    if payload.supersedes_identifier_id != previous.id:
        raise HTTPException(
            status_code=409,
            detail="Correction must supersede the routed identifier.",
        )
    if previous.effective_until is not None:
        raise HTTPException(status_code=409, detail="Only a current identifier can be corrected.")
    if payload.effective_from < previous.effective_from:
        raise HTTPException(
            status_code=409,
            detail="Correction cannot predate the prior identifier.",
        )
    if (
        payload.identifier_kind != previous.identifier_kind
        or payload.application_id != previous.application_id
        or payload.proceeding_id != previous.proceeding_id
    ):
        raise HTTPException(
            status_code=409,
            detail="Correction cannot change identifier kind or owner.",
        )
    _assert_identifier_owner_exists(
        session,
        company_id=context.company.id,
        docket_id=docket.id,
        application_id=payload.application_id,
        proceeding_id=payload.proceeding_id,
    )
    duplicates = _duplicate_identifiers(
        session,
        company_id=context.company.id,
        identifier_kind=payload.identifier_kind,
        office=payload.office,
        jurisdiction=payload.jurisdiction,
        normalized_value=payload.normalized_value,
        exclude_ids={previous.id},
    )
    previous.effective_until = payload.effective_from
    previous.is_primary = False
    row = IpIdentifier(
        company_id=context.company.id,
        docket_id=docket.id,
        application_id=payload.application_id,
        proceeding_id=payload.proceeding_id,
        identifier_kind=payload.identifier_kind,
        raw_value=payload.raw_value,
        normalized_value=payload.normalized_value,
        office=payload.office,
        jurisdiction=payload.jurisdiction,
        source=payload.source,
        effective_from=payload.effective_from,
        effective_until=payload.effective_until,
        is_primary=payload.is_primary,
        reconciliation_status="needs_review" if duplicates else "confirmed",
        supersedes_identifier_id=previous.id,
        correction_reason=payload.correction_reason,
    )
    session.add(row)
    session.flush()
    record_from_context(
        session,
        context,
        action="ip_identifier.corrected",
        target_type="ip_identifier",
        target_id=row.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "docket_id": docket.id,
            "supersedes_identifier_id": previous.id,
            "correction_reason": payload.correction_reason,
            "duplicate_candidate_ids": [candidate.id for candidate in duplicates],
        },
    )
    session.commit()
    session.refresh(row)
    return row, duplicates


def update_trademark_application_phase(
    session: Session,
    *,
    context: SessionContext,
    application_id: str,
    payload: TrademarkApplicationPhaseUpdateRequest,
) -> TrademarkApplication:
    candidate = session.scalar(
        select(TrademarkApplication)
        .where(
            TrademarkApplication.id == application_id,
            TrademarkApplication.company_id == context.company.id,
        )
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Trademark application not found.")
    # Lock the parent first so every core-record mutation follows the same
    # docket -> child lock order and lifecycle transitions cannot race a
    # filing-phase change.
    docket = _docket(session, context, candidate.docket_id)
    row = session.scalar(
        select(TrademarkApplication)
        .where(
            TrademarkApplication.id == application_id,
            TrademarkApplication.company_id == context.company.id,
            TrademarkApplication.docket_id == docket.id,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Trademark application not found.")
    if not row.is_active:
        raise HTTPException(
            status_code=409,
            detail=(
                "Terminal trademark applications are immutable; use a dedicated "
                "prosecution lifecycle event."
            ),
        )
    if row.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Application version changed; reload.")
    row.source_pending_identifier_allocation = payload.source_pending_identifier_allocation
    identifiers = list(
        session.scalars(
            select(IpIdentifier).where(
                IpIdentifier.company_id == context.company.id,
                IpIdentifier.application_id == row.id,
            )
        ).all()
    )
    if payload.filing_phase == "filed":
        assert_application_can_enter_filed_phase(row, identifiers)
    row.filing_phase = payload.filing_phase
    row.version += 1
    row.updated_at = datetime.now(UTC)
    record_from_context(
        session,
        context,
        action="ip_application.phase_changed",
        target_type="trademark_application",
        target_id=row.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "filing_phase": row.filing_phase,
            "version": row.version,
            "source_pending_identifier_allocation": (
                row.source_pending_identifier_allocation
            ),
        },
    )
    session.commit()
    session.refresh(row)
    return row


def list_ip_core_records(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
) -> dict[str, list[object]]:
    docket = _docket(session, context, docket_id, for_update=False)
    company_id = context.company.id
    return {
        "assets": list(
            session.scalars(
                select(IpAsset).where(
                    IpAsset.company_id == company_id,
                    IpAsset.docket_id == docket.id,
                )
            ).all()
        ),
        "applications": list(
            session.scalars(
                select(TrademarkApplication).where(
                    TrademarkApplication.company_id == company_id,
                    TrademarkApplication.docket_id == docket.id,
                )
            ).all()
        ),
        "proceedings": list(
            session.scalars(
                select(IpProceeding).where(
                    IpProceeding.company_id == company_id,
                    IpProceeding.docket_id == docket.id,
                )
            ).all()
        ),
        "identifiers": list(
            session.scalars(
                select(IpIdentifier)
                .where(
                    IpIdentifier.company_id == company_id,
                    IpIdentifier.docket_id == docket.id,
                )
                .order_by(IpIdentifier.created_at, IpIdentifier.id)
            ).all()
        ),
    }


def search_ip_identifiers(
    session: Session,
    *,
    context: SessionContext,
    query: str,
) -> list[IpIdentifier]:
    normalized = normalize_ip_identifier(query)
    if not normalized:
        raise HTTPException(status_code=422, detail="Identifier search value is empty.")
    # Search uses normalized equality by design: punctuation and spacing vary,
    # while fuzzy identifier matches would create unsafe legal-record leakage.
    rows = list(
        session.scalars(
            select(IpIdentifier)
            .where(
                IpIdentifier.company_id == context.company.id,
                IpIdentifier.normalized_value == normalized,
            )
            .order_by(IpIdentifier.created_at, IpIdentifier.id)
        ).all()
    )
    visible: list[IpIdentifier] = []
    checked_dockets: dict[str, bool] = {}
    for row in rows:
        allowed = checked_dockets.get(row.docket_id)
        if allowed is None:
            try:
                _docket(session, context, row.docket_id, for_update=False)
                allowed = True
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                allowed = False
            checked_dockets[row.docket_id] = allowed
        if allowed:
            visible.append(row)
    return visible


def _visible_identifiers(
    session: Session,
    *,
    context: SessionContext,
    rows: list[IpIdentifier],
) -> list[IpIdentifier]:
    """Drop identifiers whose docket the caller may not open."""

    visible: list[IpIdentifier] = []
    checked: dict[str, bool] = {}
    for row in rows:
        allowed = checked.get(row.docket_id)
        if allowed is None:
            try:
                _docket(session, context, row.docket_id, for_update=False)
                allowed = True
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                allowed = False
            checked[row.docket_id] = allowed
        if allowed:
            visible.append(row)
    return visible


def _duplicate_candidate(session: Session, row: IpIdentifier):
    from caseops_api.db.models import IpDocketRecord
    from caseops_api.schemas.ip_records import IpDuplicateCandidate

    docket = session.get(IpDocketRecord, row.docket_id)
    return IpDuplicateCandidate(
        identifier_id=row.id,
        docket_id=row.docket_id,
        application_id=row.application_id,
        proceeding_id=row.proceeding_id,
        matter_id=docket.matter_id if docket else None,
        raw_value=row.raw_value,
        normalized_value=row.normalized_value,
        source=row.source,
        is_primary=row.is_primary,
        reconciliation_status=row.reconciliation_status,
        docket_title=docket.title if docket else "",
        docket_status=docket.status if docket else "",
        docket_restricted=bool(docket.restricted) if docket else False,
        docket_is_active=bool(docket.is_active) if docket else False,
    )


TERMINAL_DOCKET_STATES = {"closed", "abandoned", "refused", "withdrawn", "registered"}


def _merge_blocking_reasons(subject, candidates) -> list[str]:
    """UJ-05-EXC-01: conditions that forbid an automatic merge.

    A blocked merge is not a failure; it means the decision belongs to a human
    owner. ``distinct`` stays available and only ``supersede`` is withheld.
    """

    reasons: list[str] = []
    all_rows = [subject, *candidates]
    if any(row.docket_status in TERMINAL_DOCKET_STATES for row in all_rows):
        reasons.append("conflicting_terminal_state")
    if len({row.matter_id for row in all_rows}) > 1:
        reasons.append("different_client_matter")
    if len({row.docket_restricted for row in all_rows}) > 1:
        reasons.append("privileged_permission_mismatch")
    if any(not row.docket_is_active for row in all_rows):
        reasons.append("inactive_record")
    return reasons


def _decision_token(subject: IpIdentifier, candidates: list[IpIdentifier]) -> str:
    parts = [subject.id, subject.reconciliation_status]
    parts.extend(sorted(f"{row.id}:{row.reconciliation_status}" for row in candidates))
    return sha256("|".join(parts).encode()).hexdigest()


def preview_ip_identifier_duplicates(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    identifier_id: str,
):
    """IP-ID-07 - show the competing records without merging anything."""

    from caseops_api.schemas.ip_records import IpDuplicatePreviewResponse

    docket = _docket(session, context, docket_id, for_update=False)
    row = session.scalar(
        select(IpIdentifier).where(
            IpIdentifier.id == identifier_id,
            IpIdentifier.company_id == context.company.id,
            IpIdentifier.docket_id == docket.id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Identifier not found.")

    candidates = _duplicate_identifiers(
        session,
        company_id=context.company.id,
        identifier_kind=row.identifier_kind,
        office=row.office,
        jurisdiction=row.jurisdiction,
        normalized_value=row.normalized_value,
        exclude_ids={row.id},
    )
    # Only competing records the caller may actually open participate in the
    # decision; a hidden record must not leak through a reconciliation preview.
    visible = _visible_identifiers(session, context=context, rows=candidates)
    subject = _duplicate_candidate(session, row)
    candidate_records = [_duplicate_candidate(session, item) for item in visible]
    reasons = _merge_blocking_reasons(subject, candidate_records)
    allowed = ["distinct"] if reasons or not candidate_records else ["distinct", "supersede"]
    return IpDuplicatePreviewResponse(
        identifier_id=row.id,
        identifier=subject,
        candidates=candidate_records,
        decision_token=_decision_token(row, visible),
        automatic_merge_blocked=bool(reasons),
        blocking_reasons=reasons,
        allowed_decisions=allowed,
    )


def resolve_ip_identifier_duplicate(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    identifier_id: str,
    payload,
):
    """IP-ID-07 / UJ-05 - resolve a flagged duplicate by explicit decision.

    Nothing is merged silently: the caller restates a current preview token,
    chooses a decision, and gives a reason. Both outcomes are audited and the
    prior value is preserved.
    """

    from caseops_api.schemas.ip_records import (
        IpDuplicateResolutionResponse,
        IpIdentifierResponse,
    )

    docket = _docket(session, context, docket_id, for_update=True)
    row = session.scalar(
        select(IpIdentifier)
        .where(
            IpIdentifier.id == identifier_id,
            IpIdentifier.company_id == context.company.id,
            IpIdentifier.docket_id == docket.id,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Identifier not found.")
    if row.effective_until is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A superseded identifier cannot be reconciled.",
        )
    if row.reconciliation_status != "needs_review":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only an identifier awaiting review can be reconciled.",
        )

    preview = preview_ip_identifier_duplicates(
        session, context=context, docket_id=docket.id, identifier_id=row.id
    )
    if payload.decision_token != preview.decision_token:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate set changed; preview again.",
        )
    if payload.decision not in preview.allowed_decisions:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_duplicate_merge_blocked",
                "message": (
                    "This duplicate cannot be merged automatically and requires "
                    "an explicit owner decision."
                ),
                "blocking_reasons": preview.blocking_reasons,
            },
        )

    now = datetime.now(UTC)
    resolved_ids = [item.identifier_id for item in preview.candidates]
    superseded_by_identifier_id: str | None = None
    if payload.decision == "distinct":
        row.reconciliation_status = "confirmed"
        row.correction_reason = payload.reason
    else:
        target_id = payload.superseded_by_identifier_id
        if not target_id or target_id not in resolved_ids:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A superseding identifier from the preview is required.",
            )
        target = session.scalar(
            select(IpIdentifier)
            .where(
                IpIdentifier.id == target_id,
                IpIdentifier.company_id == context.company.id,
                IpIdentifier.effective_until.is_(None),
                IpIdentifier.superseded_by_identifier_id.is_(None),
            )
            .with_for_update()
        )
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Superseding identifier changed; preview again.",
            )
        # The surviving record keeps the identity. This row retires with an
        # explicit forward link and reason, so the prior value stays in
        # history. ``supersedes_identifier_id`` has the opposite meaning: it
        # belongs on a newly-created correction and must remain untouched here.
        row.effective_until = now
        row.reconciliation_status = "superseded"
        row.superseded_by_identifier_id = target.id
        row.correction_reason = payload.reason
        row.is_primary = False
        target.reconciliation_status = "confirmed"
        superseded_by_identifier_id = target.id
        resolved_ids = [target.id]

    record_from_context(
        session,
        context,
        action="ip.identifier.duplicate_resolved",
        target_type="ip_identifier",
        target_id=row.id,
        ip_docket_id=docket.id,
        matter_id=docket.matter_id,
        metadata={
            "decision": payload.decision,
            "reason": payload.reason,
            "decision_token": payload.decision_token,
            "candidate_ids": resolved_ids,
            "superseded_by_identifier_id": superseded_by_identifier_id,
            "blocking_reasons": preview.blocking_reasons,
        },
    )
    session.commit()
    session.refresh(row)
    return IpDuplicateResolutionResponse(
        identifier=IpIdentifierResponse.model_validate(row),
        decision=payload.decision,
        resolved_candidate_ids=resolved_ids,
    )
