"""Patent application corrections that must revalidate priority relationships.

A correction changes application facts that priority claims depend on, so it
coordinates both services. Keeping it here lets ``ip_patent_priorities`` build on
``ip_patent_applications`` without the application service importing priorities.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import IpAsset
from caseops_api.schemas.ip_patents import (
    PatentApplicationCorrectionRequest,
    PatentApplicationRecord,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.ip_operations import _lock_ip_writer_context
from caseops_api.services.ip_patent_applications import (
    _append_version,
    _application,
    _check_anchor,
    _link_sources,
    _lock_application_identity_writer,
    _sources,
    get_patent_application,
)
from caseops_api.services.ip_patent_families import _error, _lock_sources_and_dockets
from caseops_api.services.ip_patent_priorities import validate_application_priority_correction
from caseops_api.services.session_context import SessionContext


def correct_patent_application(
    session: Session,
    *,
    context: SessionContext,
    application_id: str,
    payload: PatentApplicationCorrectionRequest,
) -> PatentApplicationRecord:
    _lock_application_identity_writer(session, context)
    context = _lock_ip_writer_context(session, context=context, required_capability="ip:write")
    application = _application(session, context, application_id)
    dockets = _lock_sources_and_dockets(
        session, context, _sources(payload.facts), {application.docket_id}
    )
    docket = dockets[application.docket_id]
    _check_anchor(docket)
    if (
        docket.current_version != payload.expected_version
        or docket.lifecycle_version != payload.expected_lifecycle_version
    ):
        raise _error(
            "patent_application_stale", "The application changed. Reload before correcting it."
        )
    get_patent_application(session, context=context, application_id=application.id)
    validate_application_priority_correction(
        session,
        context=context,
        application=application,
        facts=payload.facts,
    )
    asset = session.scalar(
        select(IpAsset)
        .where(
            IpAsset.company_id == context.company.id,
            IpAsset.id == application.asset_id,
            IpAsset.docket_id == docket.id,
            IpAsset.asset_kind == "patent",
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if asset is None:
        raise _error("patent_application_integrity", "The application asset requires repair.")
    docket.current_version += 1
    docket.title = payload.facts.title
    asset.title = payload.facts.title
    asset.jurisdiction = payload.facts.jurisdiction
    asset.version += 1
    _append_version(session, context, application, docket, payload.facts, payload.reason)
    _link_sources(session, context, docket, payload.facts)
    record_from_context(
        session,
        context,
        action="ip_patent_application.corrected",
        target_type="ip_patent_application",
        target_id=application.id,
        ip_docket_id=docket.id,
        metadata={"version": docket.current_version, "reason": payload.reason},
    )
    result = get_patent_application(session, context=context, application_id=application.id)
    session.commit()
    return result
