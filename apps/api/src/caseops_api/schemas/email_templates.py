"""Phase B M11 slice 2 — email template + send request shapes."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

EmailVariables = dict[
    Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", max_length=80)],
    Annotated[str, Field(max_length=2000)],
]


class EmailTemplateVariable(BaseModel):
    """One declared placeholder. ``name`` is the ``{{name}}`` token
    in the body / subject."""

    name: str = Field(min_length=1, max_length=80)
    label: str | None = Field(default=None, max_length=120)
    required: bool = True


class EmailTemplateRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    name: str
    kind: str
    description: str | None
    subject_template: str
    body_template: str
    variables: list[EmailTemplateVariable] = Field(default_factory=list)
    is_active: bool
    created_by_membership_id: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, model: Any) -> EmailTemplateRecord:
        raw_vars = model.variables_json or []
        try:
            variables = [EmailTemplateVariable.model_validate(v) for v in raw_vars]
        except Exception:  # noqa: BLE001 — bad JSON should not 500 the GET
            variables = []
        return cls(
            id=model.id,
            company_id=model.company_id,
            name=model.name,
            kind=model.kind,
            description=model.description,
            subject_template=model.subject_template,
            body_template=model.body_template,
            variables=variables,
            is_active=model.is_active,
            created_by_membership_id=model.created_by_membership_id,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


class EmailTemplateListResponse(BaseModel):
    templates: list[EmailTemplateRecord]


class EmailTemplateCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    kind: str = Field(min_length=2, max_length=40)
    description: str | None = Field(default=None, max_length=400)
    subject_template: str = Field(min_length=2, max_length=400)
    body_template: str = Field(min_length=2, max_length=20000)
    variables: list[EmailTemplateVariable] = Field(default_factory=list)


class EmailTemplateUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    kind: str | None = Field(default=None, min_length=2, max_length=40)
    description: str | None = Field(default=None, max_length=400)
    subject_template: str | None = Field(
        default=None, min_length=2, max_length=400,
    )
    body_template: str | None = Field(
        default=None, min_length=2, max_length=20000,
    )
    variables: list[EmailTemplateVariable] | None = None
    is_active: bool | None = None


class EmailRenderRequest(BaseModel):
    """Render the template with the given variables. Returns the
    fully-substituted subject + body without sending — used for the
    Compose dialog's preview pane."""

    variables: EmailVariables = Field(default_factory=dict, max_length=40)


class EmailRenderResponse(BaseModel):
    subject: str
    body: str
    missing_variables: list[str] = Field(default_factory=list)
    invalid_placeholders: list[str] = Field(default_factory=list)
    resolved_variables: dict[str, str] = Field(default_factory=dict)


class MatterEmailPreviewRequest(EmailRenderRequest):
    model_config = ConfigDict(extra="forbid")

    template_id: str | None = Field(default=None, min_length=1, max_length=36)
    subject: str | None = Field(default=None, min_length=2, max_length=400)
    body: str | None = Field(default=None, min_length=2, max_length=20000)
    recipient_email: EmailStr
    recipient_name: str | None = Field(default=None, max_length=255)
    client_id: str | None = None

    @model_validator(mode="after")
    def require_message(self) -> MatterEmailPreviewRequest:
        if self.template_id is None and not (
            self.subject and self.subject.strip() and self.body and self.body.strip()
        ):
            raise ValueError("Choose a template or enter a subject and message.")
        for text in (self.subject, self.body):
            if text is not None and not text.strip():
                raise ValueError("Subject and message cannot be blank.")
        return self


class MatterEmailPreviewResponse(EmailRenderResponse):
    preview_token: str | None = None
    preview_expires_at: datetime | None = None


class EmailSendRequest(MatterEmailPreviewRequest):
    """Delivery requires a current server-issued preview for the exact message."""

    preview_token: str = Field(min_length=1, max_length=256)
