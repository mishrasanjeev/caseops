from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import UUID4, BaseModel, ConfigDict, Field


class WorkspaceConductAccept(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    version: str = Field(min_length=10, max_length=10, pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


class WorkspaceConductStatus(BaseModel):
    version: str
    policy_url: str
    accepted_at: datetime | None


ReportReason = Literal[
    "harassment_threats",
    "exploitation",
    "impersonation",
    "unlawful_content",
    "spam_malware_fraud",
    "unauthorized_disclosure",
    "other",
]


class ConductReportSource(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    matter_id: UUID
    item_id: UUID


class ConductNoteReportTarget(ConductReportSource):
    kind: Literal["note"]


class ConductFileReportTarget(ConductReportSource):
    kind: Literal["file"]


class ConductUserReportTarget(ConductReportSource):
    kind: Literal["user"]
    membership_id: UUID
    source_kind: Literal["note", "file"]


class WorkspaceConductReportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    operation_id: UUID4
    reason: ReportReason
    target: Annotated[
        ConductNoteReportTarget | ConductFileReportTarget | ConductUserReportTarget,
        Field(discriminator="kind"),
    ]


class WorkspaceConductReportReceipt(BaseModel):
    id: UUID
    operation_id: UUID4
    status: Literal["received"] = "received"
    received_at: datetime


class WorkspaceConductReportMetadata(BaseModel):
    id: UUID
    company_id: UUID
    target_membership_id: UUID | None
    target_kind: Literal["note", "file", "user"]
    reason: ReportReason
    received_at: datetime


class WorkspaceConductReportPage(BaseModel):
    reports: list[WorkspaceConductReportMetadata]
    next_cursor: UUID | None
