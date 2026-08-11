"""Canonical contracts for IP record identity and identifier history."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    IpAsset,
    IpIdentifier,
    IpProceeding,
    TrademarkApplication,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.ip_identifier_rules import normalize_ip_identifier
from caseops_api.services.session_context import SessionContext

if TYPE_CHECKING:
    from caseops_api.schemas.ip_records import (
        IpAssetCreateRequest,
        IpIdentifierCorrectionCreate,
        IpIdentifierCreate,
        IpProceedingCreateRequest,
        TrademarkApplicationCreateRequest,
        TrademarkApplicationPhaseUpdateRequest,
    )

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
    session.commit()
    session.refresh(row)
    return row


def create_trademark_application(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: TrademarkApplicationCreateRequest,
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
    session.commit()
    session.refresh(row)
    if identifier is not None:
        session.refresh(identifier)
    return row, identifier, duplicates


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
