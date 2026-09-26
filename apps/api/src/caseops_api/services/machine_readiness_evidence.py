"""Authenticate machine-readiness evidence bound to the exact serving release.

Production safety and the IP domain catalogue both accept this evidence, so the
verifier lives in its own leaf module that neither service needs to import the
other through.
"""

from __future__ import annotations

import hmac
import re

from caseops_api.core.machine_readiness_auth import machine_readiness_evidence_proof
from caseops_api.core.settings import get_settings

MACHINE_READINESS_EVIDENCE_SCHEMA = "caseops.machine-readiness/v1"
MACHINE_READINESS_PRODUCERS = frozenset(
    {
        "caseops/config-probe",
        "caseops/production-probe",
        "github-actions/prod-verify",
    }
)
_FULL_RELEASE_SHA = re.compile(r"[0-9a-f]{40}")
_MACHINE_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{2,199}")


def _exact_release_sha() -> str | None:
    release_sha = (get_settings().release_sha or "").strip().lower()
    return release_sha if _FULL_RELEASE_SHA.fullmatch(release_sha) else None


def _machine_evidence(
    *,
    evidence: dict | None,
    recorded_by_platform_admin_id: str | None,
    recorded_status: str,
    subject: str,
    evidence_ref: str | None,
    allowed_producers: frozenset[str] = MACHINE_READINESS_PRODUCERS,
) -> dict[str, object] | None:
    """Accept only automation evidence bound to the exact serving release.

    Historical readiness tables are retained for migration compatibility.  A
    platform-admin row is human attestation and is deliberately non-authoritative.
    Machine writers have no public mutation route and must persist the documented
    envelope with a null platform-admin recorder.
    """

    settings = get_settings()
    release_sha = _exact_release_sha()
    secret = settings.machine_readiness_evidence_secret
    if release_sha is None or not secret or recorded_by_platform_admin_id is not None:
        return None
    if recorded_status not in {"pass", "fail", "blocked"} or not isinstance(evidence, dict):
        return None
    producer = evidence.get("producer")
    run_id = evidence.get("run_id")
    if (
        evidence.get("schema") != MACHINE_READINESS_EVIDENCE_SCHEMA
        or not isinstance(producer, str)
        or producer not in allowed_producers
        or evidence.get("release_sha") != release_sha
        or evidence.get("subject") != subject
        or evidence.get("conclusion") != recorded_status
        or evidence.get("evidence_ref") != evidence_ref
        or not isinstance(run_id, str)
        or _MACHINE_RUN_ID.fullmatch(run_id) is None
    ):
        return None
    proof = evidence.get("proof")
    expected_proof = machine_readiness_evidence_proof(secret=secret, evidence=evidence)
    if not isinstance(proof, str) or not hmac.compare_digest(proof, expected_proof):
        return None
    return evidence
