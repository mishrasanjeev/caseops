"""Public domain claims, separate from tenant permissions and entitlements."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

IpDomainStage = Literal["unavailable", "intake_only", "beta", "ga"]


class IpDomainCapability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    domain: str
    label: str
    stage: IpDomainStage
    contract_version: str
    jurisdictions: list[str]
    offices: list[str]
    intake_available: bool
    authoritative_automation_available: bool
    blockers: list[str]
    required_journeys: list[str]


class IpDomainCatalogue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalogue_version: str
    domains: list[IpDomainCapability]


class IpDomainCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    check_id: str = Field(min_length=1, max_length=120)
    outcome: Literal["passed", "failed", "skipped", "not_run"]
    evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class IpDomainReleaseEvidence(BaseModel):
    """Release-owned evidence only; this is never a tenant-writable request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    domain: str
    contract_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    release_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    stage: Literal["beta", "ga"]
    jurisdictions: tuple[str, ...] = Field(min_length=1, max_length=40)
    offices: tuple[str, ...] = Field(min_length=1, max_length=80)
    recorded_at: datetime
    expires_at: datetime
    checks: tuple[IpDomainCheck, ...] = Field(min_length=1, max_length=300)
