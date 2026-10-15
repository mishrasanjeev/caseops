"""Independent date corrections through the canonical immutable version writer."""

from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy import select

from caseops_api.db.models import IpTrademarkParticularVersion
from caseops_api.schemas.ip_imports import IpImportDocketVersionCreateRequest
from caseops_api.services.audit import record_from_context
from caseops_api.services.ip_docket_access import _docket_or_404
from caseops_api.services.ip_domain_policy import assert_trademark_docket
from caseops_api.services.ip_portfolio_dates import current_dates, docket_date_edit_operational
from caseops_api.services.private_retrieval import lock_private_authority_writer


def update_portfolio_dates(
    session, *, context, docket_id, payload, _legacy_import_correction=False
):
    from caseops_api.services.ip_operations import append_ip_docket_version
    from caseops_api.services.ip_renewal_tracker_read import tracker_row

    try:
        lock_private_authority_writer(session, company_id=context.company.id)
        docket = _docket_or_404(session, context=context, docket_id=docket_id, for_update=True)
        assert_trademark_docket(docket)
        if not docket_date_edit_operational(docket):
            raise HTTPException(
                status_code=409, detail="A terminal trademark record cannot be edited."
            )
        if docket.current_version != payload.expected_current_version:
            raise HTTPException(
                status_code=409, detail="IP docket version changed; reload before saving."
            )
        version = session.scalar(
            select(IpTrademarkParticularVersion).where(
                IpTrademarkParticularVersion.company_id == context.company.id,
                IpTrademarkParticularVersion.docket_id == docket.id,
                IpTrademarkParticularVersion.version == docket.current_version,
            )
        )
        before = current_dates(session, version=version, docket_id=docket.id)
        representation = deepcopy(version.representation_json)
        corrections = representation.get("portfolio_dates")
        corrections = deepcopy(corrections) if isinstance(corrections, dict) else {}
        for field in payload.model_fields_set & {"application_date", "renewal_due_date"}:
            value = getattr(payload, field)
            corrections[field] = {"value": value.isoformat() if value else None, "origin": "manual"}
        representation["portfolio_dates"] = corrections
        if _legacy_import_correction:
            from caseops_api.services.ip_portfolio_source import _imported_source_row

            source = representation.get("portfolio_import")
            if not isinstance(source, dict) or not _imported_source_row(
                session, company_id=context.company.id, docket_id=docket.id, source=source
            ):
                raise HTTPException(
                    status_code=409, detail="This record has no imported source date."
                )
            source["renewal_due_date"] = corrections["renewal_due_date"]["value"]
            source["date_correction"] = {
                "writer": "portfolio_dates",
                "reason": payload.reason,
                "previous_due_date": before["source_renewal_due_on"].isoformat()
                if before["source_renewal_due_on"]
                else None,
                "previous_version": docket.current_version,
            }
        append_ip_docket_version(
            session,
            context=context,
            docket_id=docket.id,
            # These are retained server facts, not new filing particulars. The canonical
            # writer copies their original JSON without reinterpreting legacy shapes.
            payload=IpImportDocketVersionCreateRequest.model_construct(
                expected_current_version=payload.expected_current_version,
                form_key=version.form_key,
                form_version=version.form_version,
                mark_kind=version.mark_kind,
                representation=representation,
                classes=version.classes_json,
                parties=version.parties_json,
                use_priority=version.use_priority_json,
                agent=version.agent_json,
                filing_manifest=version.filing_manifest_json,
            ),
            commit=False,
            preserve_status=True,
            _allow_portfolio_dates=True,
            _copy_existing_particulars=True,
        )
        after_version = session.scalar(
            select(IpTrademarkParticularVersion).where(
                IpTrademarkParticularVersion.company_id == context.company.id,
                IpTrademarkParticularVersion.docket_id == docket.id,
                IpTrademarkParticularVersion.version == docket.current_version,
            )
        )
        after = current_dates(session, version=after_version, docket_id=docket.id)
        record_from_context(
            session,
            context,
            action="ip_portfolio.dates_corrected",
            target_type="ip_docket_record",
            target_id=docket.id,
            ip_docket_id=docket.id,
            matter_id=docket.matter_id,
            metadata={
                "reason": payload.reason,
                "previous_version": before["current_version"],
                "version": after["current_version"],
                "changed_fields": sorted(
                    payload.model_fields_set & {"application_date", "renewal_due_date"}
                ),
                "before": {
                    key: value.isoformat() if hasattr(value, "isoformat") else value
                    for key, value in before.items()
                },
                "after": {
                    key: value.isoformat() if hasattr(value, "isoformat") else value
                    for key, value in after.items()
                },
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    from caseops_api.schemas.ip_renewal_tracker import IpPortfolioDatesResponse

    return IpPortfolioDatesResponse(
        **after, tracker=tracker_row(session, context=context, docket_id=docket.id)
    )
