"""Read-only publication visibility shared by the portal and delivery owners."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    IpDocketRecord,
    IpDocument,
    IpDocumentVersion,
    MatterPortalGrant,
    PortalPublication,
    PortalPublicationTarget,
    PortalUser,
)
from caseops_api.services.ip_domain_policy import (
    disclosable_ip_document_ids,
    general_ip_disclosure_allowed,
)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def publication_grant_is_active(grant: MatterPortalGrant, *, now: datetime) -> bool:
    return bool(
        grant.revoked_at is None and (grant.expires_at is None or _aware(grant.expires_at) > now)
    )


def publication_target_is_current(
    target: PortalPublicationTarget,
    grant: MatterPortalGrant,
    docket: IpDocketRecord,
    *,
    now: datetime,
) -> bool:
    return bool(
        publication_grant_is_active(grant, now=now)
        and general_ip_disclosure_allowed(docket)
        and docket.is_active
        and not docket.archived_by_matter_disposal
        and docket.current_version == target.docket_version
        and docket.lifecycle_version == target.lifecycle_version
        and docket.access_policy_version == target.access_policy_version
    )


def publication_access_state(
    *,
    publication: PortalPublication,
    portal_user: PortalUser,
    targets_current: Sequence[bool],
    version: IpDocumentVersion | None,
    document: IpDocument | None,
    disclosable_document_ids: set[str],
    now: datetime,
) -> str:
    scheduled = bool(
        publication.status == "scheduled"
        and publication.scheduled_for is not None
        and _aware(publication.scheduled_for) > now
    )
    document_current = bool(
        publication.document_version_id is None
        or (
            version is not None
            and document is not None
            and document.company_id == portal_user.company_id
            and version.company_id == portal_user.company_id
            and version.document_id == document.id
            and version.version == document.current_version
            and not document.is_privileged
            and document.confidentiality == "internal"
            and document.id in disclosable_document_ids
            and version.state in {"approved", "filed", "served", "accepted"}
        )
    )
    current = bool(targets_current) and all(targets_current) and document_current
    return (
        "revoked"
        if publication.status == "revoked"
        else "scheduled"
        if scheduled
        else "available"
        if current
        else "review_required"
    )


@dataclass(frozen=True)
class PublicationVisibility:
    publication: PortalPublication
    targets: tuple[tuple[PortalPublicationTarget, MatterPortalGrant, IpDocketRecord], ...]
    version: IpDocumentVersion | None
    document: IpDocument | None
    disclosable_document_ids: set[str]


def load_publication_visibility(
    session: Session,
    *,
    portal_user: PortalUser,
    publication_id: str,
) -> PublicationVisibility | None:
    publication = session.scalar(
        select(PortalPublication).where(
            PortalPublication.id == publication_id,
            PortalPublication.company_id == portal_user.company_id,
            PortalPublication.portal_user_id == portal_user.id,
        )
    )
    if publication is None:
        return None
    targets = session.execute(
        select(PortalPublicationTarget, MatterPortalGrant, IpDocketRecord)
        .join(MatterPortalGrant, MatterPortalGrant.id == PortalPublicationTarget.portal_grant_id)
        .join(IpDocketRecord, IpDocketRecord.id == PortalPublicationTarget.ip_docket_record_id)
        .where(
            PortalPublicationTarget.company_id == publication.company_id,
            PortalPublicationTarget.publication_id == publication.id,
        )
        .order_by(IpDocketRecord.title, IpDocketRecord.id)
    ).all()
    version = (
        session.get(IpDocumentVersion, publication.document_version_id)
        if publication.document_version_id
        else None
    )
    document = session.get(IpDocument, version.document_id) if version is not None else None
    disclosable_document_ids = disclosable_ip_document_ids(
        session,
        company_id=portal_user.company_id,
        document_ids={document.id} if document is not None else set(),
    )
    return PublicationVisibility(
        publication, tuple(targets), version, document, disclosable_document_ids
    )


def publication_is_available(
    visibility: PublicationVisibility | None,
    *,
    portal_user: PortalUser,
    now: datetime,
) -> bool:
    return (
        visibility is not None
        and publication_access_state(
            publication=visibility.publication,
            portal_user=portal_user,
            targets_current=[
                publication_target_is_current(target, grant, docket, now=now)
                for target, grant, docket in visibility.targets
            ],
            version=visibility.version,
            document=visibility.document,
            disclosable_document_ids=visibility.disclosable_document_ids,
            now=now,
        )
        == "available"
    )
