from __future__ import annotations

import hashlib
import hmac
import json

MACHINE_READINESS_SIGNATURE_CONTEXT = b"caseops.machine-readiness-write/v1"
MACHINE_READINESS_PROOF_CONTEXT = b"caseops.machine-readiness-proof/v1"


def machine_readiness_signature(*, secret: str, timestamp: str, body: bytes) -> str:
    """Sign the exact request bytes so evidence cannot be altered in transit."""

    message = MACHINE_READINESS_SIGNATURE_CONTEXT + b"\n" + timestamp.encode("ascii") + b"\n" + body
    return (
        "sha256="
        + hmac.new(
            secret.encode("utf-8"),
            message,
            hashlib.sha256,
        ).hexdigest()
    )


def machine_readiness_evidence_proof(
    *,
    secret: str,
    evidence: dict[str, object],
) -> str:
    """MAC one normalized stored envelope so later DB edits fail closed."""

    unsigned = {key: value for key, value in evidence.items() if key != "proof"}
    body = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return (
        "sha256="
        + hmac.new(
            secret.encode("utf-8"),
            MACHINE_READINESS_PROOF_CONTEXT + b"\n" + body,
            hashlib.sha256,
        ).hexdigest()
    )


__all__ = [
    "MACHINE_READINESS_PROOF_CONTEXT",
    "MACHINE_READINESS_SIGNATURE_CONTEXT",
    "machine_readiness_evidence_proof",
    "machine_readiness_signature",
]
