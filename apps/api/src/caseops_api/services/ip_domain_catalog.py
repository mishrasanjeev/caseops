"""Release-owned domain claims used by API, UI, exports and public pages.

No client payload, tenant setting or generic IP rollout flag may promote a
domain. Existing feature authorization remains in ip_capability_catalog.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.schemas.ip_domains import (
    IpDomainCapability,
    IpDomainCatalogue,
    IpDomainReleaseEvidence,
)

CATALOGUE_VERSION = "2026-09-06.1"
BASE_CHECKS = frozenset(
    {
        "child_prd",
        "source_pack",
        "legal_fixtures",
        "migration",
        "security",
        "performance",
        "support",
        "exact_release",
        "normal",
        "exception",
        "contested",
        "transfer",
        "maintenance",
        "closure",
        "source_failure",
        "access_revocation",
    }
)
GA_CHECKS = frozenset({"production_journeys", "recovery", "cross_ip_reconciliation"})


@dataclass(frozen=True, slots=True)
class IpDomainDefinition:
    domain: str
    label: str
    contract_version: str
    contract_path: str | None
    intake_implemented: bool
    jurisdictions: tuple[str, ...]
    offices: tuple[str, ...]
    journeys: tuple[str, ...]
    child_prd_sha256: str | None = None

    @property
    def contract_sha256(self) -> str:
        return sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


DOMAIN_DEFINITIONS = (
    IpDomainDefinition(
        "trademark",
        "Trademarks",
        "IPLF-2026-08-01",
        "docs/PRD_IP_LAW_FIRM_PLATFORM_2026-08-01.md",
        True,
        ("IN",),
        ("IP India",),
        tuple(f"UJ-{value:02d}" for value in (2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 14, 31, 32)),
        child_prd_sha256="96b655bc84dd8ae705c036de04f1cd3b12128c325d673c6cfa8d68485a874cf3",
    ),
    IpDomainDefinition(
        "patent",
        "Patents",
        "PAT-2026-09-06.1",
        "docs/PRD_PATENT_DOMAIN_2026-09-06.md",
        True,
        ("IN",),
        ("IP India",),
        ("UJ-29", "UJ-39", "UJ-40"),
        child_prd_sha256="af9ee6ffa14d573bd164b2475aab6b1443b047b0f542edba4d1e6ecc90b3806c",
    ),
    IpDomainDefinition("design", "Designs", "pending", None, False, (), (), ("UJ-30", "UJ-41")),
    IpDomainDefinition(
        "copyright", "Copyright", "pending", None, False, (), (), ("UJ-30", "UJ-42")
    ),
    IpDomainDefinition("domain_name", "Domain names", "pending", None, False, (), (), ("UJ-45",)),
    IpDomainDefinition(
        "licensing", "Licensing", "pending", None, False, (), (), ("UJ-43", "UJ-60", "UJ-61")
    ),
    IpDomainDefinition(
        "geographical_indication",
        "Geographical indications",
        "pending",
        None,
        False,
        (),
        (),
        ("UJ-44",),
    ),
    IpDomainDefinition(
        "plant_variety", "Plant varieties", "pending", None, False, (), (), ("UJ-44",)
    ),
    IpDomainDefinition(
        "semiconductor_layout", "Semiconductor layouts", "pending", None, False, (), (), ("UJ-44",)
    ),
    IpDomainDefinition("trade_secret", "Trade secrets", "pending", None, False, (), (), ("UJ-44",)),
    IpDomainDefinition(
        "customs_enforcement", "Customs and enforcement", "pending", None, False, (), (), ("UJ-45",)
    ),
)
DOMAIN_BY_ID = {definition.domain: definition for definition in DOMAIN_DEFINITIONS}

DOMAIN_EVIDENCE_PRODUCERS = frozenset({"github-actions/prod-verify"})


def evaluate_domain(
    definition: IpDomainDefinition,
    *,
    release_sha: str | None,
    evidence: IpDomainReleaseEvidence | None = None,
    now: datetime | None = None,
) -> IpDomainCapability:
    current = now or datetime.now(UTC)
    blockers: list[str] = []
    intake = bool(
        definition.intake_implemented and definition.contract_path and definition.child_prd_sha256
    )
    if not intake:
        blockers.append("domain_implementation_missing")
    if not definition.contract_path or not definition.child_prd_sha256:
        blockers.append("child_prd_missing")
    stage = "intake_only" if intake else "unavailable"
    if evidence is None:
        blockers.append("release_evidence_missing")
    else:
        if evidence.domain != definition.domain:
            blockers.append("evidence_domain_mismatch")
        if evidence.contract_sha256 != definition.contract_sha256:
            blockers.append("contract_changed")
        if (
            not re.fullmatch(r"[a-f0-9]{40}", release_sha or "")
            or evidence.release_sha != release_sha
        ):
            blockers.append("release_mismatch")
        if (
            current.utcoffset() is None
            or evidence.recorded_at.utcoffset() is None
            or evidence.expires_at.utcoffset() is None
            or not evidence.recorded_at <= current < evidence.expires_at
            or evidence.expires_at - evidence.recorded_at > timedelta(days=30)
        ):
            blockers.append("evidence_not_current")
        if (
            len(set(evidence.jurisdictions)) != len(evidence.jurisdictions)
            or len(set(evidence.offices)) != len(evidence.offices)
            or set(evidence.jurisdictions) != set(definition.jurisdictions)
            or set(evidence.offices) != set(definition.offices)
        ):
            blockers.append("jurisdiction_office_mismatch")
        checks = {check.check_id: check for check in evidence.checks}
        if len(checks) != len(evidence.checks):
            blockers.append("duplicate_check")
        required = BASE_CHECKS | set(definition.journeys)
        if evidence.stage == "ga":
            required |= GA_CHECKS
        for check_id in sorted(required):
            check = checks.get(check_id)
            if check is None or check.outcome != "passed":
                blockers.append(f"check_not_passed:{check_id}")
        if any(check.outcome != "passed" for check in evidence.checks):
            blockers.append("failed_or_skipped_check")
        if not blockers:
            stage = evidence.stage
    return IpDomainCapability(
        domain=definition.domain,
        label=definition.label,
        stage=stage,
        contract_version=definition.contract_version,
        jurisdictions=list(definition.jurisdictions),
        offices=list(definition.offices),
        intake_available=intake,
        authoritative_automation_available=stage in {"beta", "ga"},
        blockers=blockers,
        required_journeys=list(definition.journeys),
    )


def _domain_evidence(session: Session) -> dict[str, IpDomainReleaseEvidence]:
    from caseops_api.db.models import PlatformOperationalReadinessEvidence
    from caseops_api.services.production_safety import _machine_evidence

    # Reuse the HMAC-authenticated release evidence owner. One bounded query,
    # no tenant lookups, no independent approvals table or new control plane.
    rows = session.scalars(
        select(PlatformOperationalReadinessEvidence)
        .where(
            PlatformOperationalReadinessEvidence.category == "ip_domain",
            PlatformOperationalReadinessEvidence.gate_code.in_(tuple(DOMAIN_BY_ID)),
        )
        .limit(len(DOMAIN_BY_ID) + 1)
    ).all()
    if len(rows) > len(DOMAIN_BY_ID):
        return {}
    result: dict[str, IpDomainReleaseEvidence] = {}
    for row in rows:
        if row.gate_code in result:
            return {}
        machine = _machine_evidence(
            evidence=row.evidence_json,
            recorded_by_platform_admin_id=row.recorded_by_platform_admin_id,
            recorded_status=row.status,
            subject=row.gate_code,
            evidence_ref=row.evidence_ref,
            allowed_producers=DOMAIN_EVIDENCE_PRODUCERS,
        )
        if machine is None or row.status != "pass":
            continue
        try:
            result[row.gate_code] = IpDomainReleaseEvidence.model_validate(
                machine.get("domain_evidence")
            )
        except ValidationError:
            continue
    return result


def domain_catalogue(session: Session | None = None) -> IpDomainCatalogue:
    evidence_by_domain = _domain_evidence(session) if session is not None else {}
    release_sha = get_settings().release_sha
    return IpDomainCatalogue(
        catalogue_version=CATALOGUE_VERSION,
        domains=[
            evaluate_domain(
                definition,
                release_sha=release_sha,
                evidence=evidence_by_domain.get(definition.domain),
            )
            for definition in DOMAIN_DEFINITIONS
        ],
    )


def assert_domain_operation(
    domain: str, *, session: Session | None = None, authoritative: bool = False
) -> None:
    decision = next(
        (row for row in domain_catalogue(session).domains if row.domain == domain), None
    )
    available = decision is not None and (
        decision.authoritative_automation_available if authoritative else decision.intake_available
    )
    if not available:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ip_domain_not_available",
                "domain": domain,
                "message": "This IP domain has not passed its implementation and source gates.",
                "blockers": decision.blockers if decision else ["unknown_domain"],
            },
        )
