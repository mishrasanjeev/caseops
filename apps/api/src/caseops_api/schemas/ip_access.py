from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class RecordAccessFoundationContract(BaseModel):
    contract_version: Literal["record-access-v1"] = "record-access-v1"
    canonical_writer: Literal[
        "MatterAccessGrant/EthicalWall via services/matter_access.py"
    ] = "MatterAccessGrant/EthicalWall via services/matter_access.py"
    supported_targets: list[Literal["matter", "ip_docket"]]
    supported_subjects: list[Literal["membership", "team"]]
    owner_bypass: dict[str, bool]
    forbidden_parallel_owners: list[str]
    excluded_persistence: list[str]


class RecordAccessReconciliationReport(BaseModel):
    generated_at: datetime
    company_id: str
    legacy_tail_count: int
    invalid_target_count: int
    invalid_subject_count: int
    target_company_mismatch_count: int
    subject_company_mismatch_count: int
    uncorrelated_ip_audit_count: int
    healthy: bool
