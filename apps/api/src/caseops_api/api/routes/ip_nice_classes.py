"""Nice class catalogue read API (BUG-002).

The catalogue is tenant-independent reference data. The route still requires
an authenticated membership holding ``ip:read`` so it sits behind the same
boundary as every other IP read.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from caseops_api.api.dependencies import require_capability
from caseops_api.schemas.ip_nice_classes import NiceClassCatalogueResponse, NiceClassRecord
from caseops_api.services.ip_nice_classes import (
    NICE_ATTRIBUTION,
    NICE_CLASSES,
    NICE_EDITION,
    NICE_HEADINGS_SHA256,
    NICE_IN_FORCE_FROM,
    NICE_RETRIEVED_ON,
    NICE_SOURCE_DATA_URL,
    NICE_SOURCE_URL,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()

_CATALOGUE = NiceClassCatalogueResponse(
    edition=NICE_EDITION,
    in_force_from=NICE_IN_FORCE_FROM,
    source_url=NICE_SOURCE_URL,
    source_data_url=NICE_SOURCE_DATA_URL,
    retrieved_on=NICE_RETRIEVED_ON,
    headings_sha256=NICE_HEADINGS_SHA256,
    attribution=NICE_ATTRIBUTION,
    classes=[
        NiceClassRecord(number=row.number, kind=row.kind, heading=row.heading, note=row.note)
        for row in NICE_CLASSES
    ],
)


@router.get("/nice-classes", response_model=NiceClassCatalogueResponse)
def nice_class_catalogue(
    _context: Annotated[SessionContext, Depends(require_capability("ip:read"))],
) -> NiceClassCatalogueResponse:
    return _CATALOGUE
