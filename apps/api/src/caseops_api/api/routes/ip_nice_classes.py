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
    NICE_CATALOGUES,
    NiceCatalogue,
    nice_catalogue_in_force,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()


def _response(catalogue: NiceCatalogue) -> NiceClassCatalogueResponse:
    return NiceClassCatalogueResponse(
        edition=catalogue.edition,
        in_force_from=catalogue.in_force_from,
        source_url=catalogue.source_url,
        source_data_url=catalogue.source_data_url,
        retrieved_on=catalogue.retrieved_on,
        headings_sha256=catalogue.headings_sha256,
        attribution=catalogue.attribution,
        classes=[
            NiceClassRecord(number=row.number, kind=row.kind, heading=row.heading, note=row.note)
            for row in catalogue.classes
        ],
    )


_RESPONSES = {catalogue.edition: _response(catalogue) for catalogue in NICE_CATALOGUES}


@router.get("/nice-classes", response_model=NiceClassCatalogueResponse)
def nice_class_catalogue(
    _context: Annotated[SessionContext, Depends(require_capability("ip:read"))],
) -> NiceClassCatalogueResponse:
    # The edition in force on the server date, the same one the class-row
    # validator accepts and stamps.
    return _RESPONSES[nice_catalogue_in_force().edition]
