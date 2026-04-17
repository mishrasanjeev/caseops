from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class DocumentProcessingJobRecord(BaseModel):
    id: str
    company_id: str
    requested_by_membership_id: str | None
    requested_by_name: str | None
    target_type: Literal["matter_attachment", "contract_attachment"]
    attachment_id: str
    action: Literal["initial_index", "retry", "reindex"]
    status: Literal["queued", "processing", "completed", "failed"]
    attempt_count: int
    processed_char_count: int
    error_message: str | None
    queued_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime
