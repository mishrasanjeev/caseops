#!/usr/bin/env python3
"""Build and enforce the repository data-governance inventory.

This is a Definition-of-Ready control, not a retention, legal-hold, export,
purge, offboarding, restore, or backup implementation.  It takes an explicit,
versioned snapshot of every SQLAlchemy table and column, plus the repository's
known non-SQL data classes.  A changed data-bearing migration or provider/
storage/telemetry boundary must change the map before CI accepts it.

The default disposition handler is deliberately fail-closed while the named
Records/Privacy/Legal/Security policy approvals remain outstanding.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = REPO_ROOT / "docs" / "ip-implementation" / "DATA_GOVERNANCE_MAP.yaml"
GENERATED_VIEW_PATH = (
    REPO_ROOT / "docs" / "ip-implementation" / "generated" / "DATA_GOVERNANCE_MAP.md"
)
MIGRATION_DIR = REPO_ROOT / "apps" / "api" / "alembic" / "versions"

MAP_STATUS = "repository_inventory_snapshot_policy_unapproved"
DEFAULT_HANDLER_ID = "registry_fail_closed"
MIGRATION_MARKER = "DATA-GOVERNANCE-MAP: updated"
REQUIRED_NON_SQL_KINDS = {
    "object_prefix_version",
    "cache",
    "sql_index_projection",
    "search_vector_index",
    "queue_outbox_dead_letter",
    "log_trace_metric",
    "export_artifact",
    "provider_held_object",
    "backup",
}
REQUIRED_POLICY_FIELDS = {
    "legal_policy_basis",
    "sensitivity",
    "default_retention",
    "tenant_configurable",
    "tenant_retention_bounds",
    "disposition",
    "hold_behavior",
    "source_licence_limits",
    "region_subprocessor",
    "owner",
}
REQUIRED_NON_SQL_FIELDS = {
    "id",
    "kind",
    "purpose",
    "legal_policy_basis",
    "sensitivity",
    "default_retention",
    "tenant_configurable",
    "tenant_retention_bounds",
    "disposition",
    "hold_behavior",
    "source_licence_limits",
    "region_subprocessor",
    "owner",
    "disposition_handler_id",
    "status",
    "implementation_refs",
}
RISKY_PATHS = {
    "apps/api/src/caseops_api/core/observability.py",
    "apps/api/src/caseops_api/core/settings.py",
    "apps/api/src/caseops_api/services/document_storage.py",
    "apps/api/src/caseops_api/services/domain_outbox.py",
    "apps/api/src/caseops_api/services/embeddings.py",
    "apps/api/src/caseops_api/services/llm.py",
    "infra/cloudrun/api-service.yaml",
    "infra/cloudrun/document-worker-job.yaml",
}
RISKY_SOURCE_ROOTS = (
    "apps/api/src/",
    "apps/web/",
    "infra/",
)
# Matches a real provider/storage/telemetry boundary, not a passing mention of
# the word. The bare-word form used to fire on ordinary prose - a comment saying
# "Inbound legal requests from business units" and the route path
# `/api/intake/requests` both tripped it - which meant every edit to models.py or
# endpoints.ts demanded a governance-map regeneration that produced no diff.
# Anchoring on an import or an attribute access keeps the detection and drops the
# noise.
_RISKY_MODULES = (
    r"google\.cloud|boto3|azure\.storage|openai|anthropic|voyageai|google\.genai|"
    r"opentelemetry|redis|pubsub|httpx|requests|aiohttp|urllib3"
)
RISKY_SOURCE_PATTERN = re.compile(
    # `import x`, `from x import ...`, `require('x')`, `from "x"`
    rf"(?:^|\n)\s*(?:import|from)\s+(?:{_RISKY_MODULES})\b"
    # The `@?` matters: provider SDKs ship scoped on npm, so the real import is
    # `from "@opentelemetry/api"`. Anchoring the bare name to the quote missed
    # every one of them.
    rf"|require\(\s*['\"]@?(?:{_RISKY_MODULES})"
    rf"|from\s+['\"]@?(?:{_RISKY_MODULES})"
    # attribute access on the module, e.g. httpx.post(, redis.Redis(
    rf"|\b(?:{_RISKY_MODULES})\s*\.\s*\w+\s*\("
    # unambiguous single-token boundaries that are never ordinary prose
    r"|\bstorage\.Client\b|\bOTLPSpanExporter\b|\bcloud.?tasks\b",
    re.IGNORECASE,
)
# Anchoring on import/attribute syntax only works in files that HAVE syntax.
# Deploy manifests are YAML and Terraform: they name a provider boundary as a
# bare word by nature - an image reference, an env var, a sidecar - so the
# pattern above matches nothing in them. `infra/` is a RISKY_SOURCE_ROOT, and
# applying the code pattern there would leave the root advertised but unwatched,
# which is worse than not listing it. Manifests also carry none of the English
# prose that made bare-word matching noisy in source files, so the original form
# is still the right one here.
_CODE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
RISKY_MANIFEST_PATTERN = re.compile(
    rf"\b(?:{_RISKY_MODULES}|storage\.Client|OTLPSpanExporter|cloud.?tasks)\b",
    re.IGNORECASE,
)


def risky_source_match(path: str, source: str) -> bool:
    """Detect a provider/storage/telemetry boundary in a changed file."""
    pattern = (
        RISKY_SOURCE_PATTERN if path.endswith(_CODE_SUFFIXES) else RISKY_MANIFEST_PATTERN
    )
    return bool(pattern.search(source))


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _metadata() -> Any:
    # Importing models registers every SQLAlchemy table with Base.metadata.
    from caseops_api.db import models  # noqa: F401
    from caseops_api.db.base import Base

    return Base.metadata


def _column_type(column: Any) -> str:
    return str(column.type)


def current_sql_schema() -> dict[str, dict[str, dict[str, object]]]:
    """Return a deterministic table/column snapshot from the ORM metadata."""

    snapshot: dict[str, dict[str, dict[str, object]]] = {}
    for table_name, table in sorted(_metadata().tables.items()):
        snapshot[table_name] = {
            column.name: {
                "sql_type": _column_type(column),
                "nullable": bool(column.nullable),
            }
            for column in sorted(table.columns, key=lambda value: value.name)
        }
    return snapshot


def current_orm_indexes() -> list[dict[str, object]]:
    """Return all ORM-declared relational indexes as derived data classes."""

    indexes: list[dict[str, object]] = []
    for table_name, table in sorted(_metadata().tables.items()):
        for index in table.indexes:
            indexes.append(
                {
                    "table_name": table_name,
                    "index_name": str(index.name),
                    "columns": [column.name for column in index.columns],
                    "unique": bool(index.unique),
                }
            )
    return sorted(
        indexes,
        key=lambda item: (
            str(item["table_name"]),
            str(item["index_name"]),
            tuple(str(column) for column in item["columns"]),
        ),
    )


def _migration_index_names() -> list[str]:
    """Inventory index declarations that are not always represented by the ORM.

    The fingerprint intentionally includes conventional Alembic declarations and
    raw PostgreSQL search/vector DDL.  It is a release guard, not an inference
    that every index has a different retention rule: indexes inherit the source
    table/column class and the explicit derived-index classes below.
    """

    names: set[str] = set()
    direct = re.compile(
        r"(?:op|batch_op)\.create_index\(\s*(?:op\.f\()?['\"]([^'\"]+)['\"]",
        re.MULTILINE,
    )
    raw = re.compile(
        r"CREATE\s+(?:UNIQUE\s+)?INDEX(?:\s+CONCURRENTLY)?"
        r"(?:\s+IF\s+NOT\s+EXISTS)?\s+([A-Za-z0-9_]+)",
        re.IGNORECASE,
    )
    for path in sorted(MIGRATION_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        names.update(direct.findall(source))
        names.update(raw.findall(source))
    return sorted(names)


def _policy_profiles() -> dict[str, dict[str, object]]:
    pending_basis = (
        "Pending named Records/Privacy/Legal/Security approval; this repository "
        "inventory is not an asserted legal retention basis or policy activation."
    )
    pending_retention = (
        "No approved automated retention duration. Preserve existing records under "
        "current operational controls and do not schedule expiry or destruction."
    )
    pending_bounds = (
        "No tenant override is available until an approved versioned policy defines "
        "per-tenant bounds, legal basis, and authority."
    )
    common = {
        "legal_policy_basis": pending_basis,
        "default_retention": pending_retention,
        "tenant_configurable": False,
        "tenant_retention_bounds": pending_bounds,
        "disposition": (
            "No automated retention, hold, export, purge, offboarding, restore, or "
            "provider-deletion action is authorized by this inventory."
        ),
        "hold_behavior": (
            "A future approved legal hold must block conflicting disposition; the "
            "current registry does not activate or execute a hold."
        ),
        "region_subprocessor": (
            "Pending approved deployment, residency, international-transfer, and "
            "subprocessor policy; no residency guarantee is asserted."
        ),
        "owner": "Codex",
    }
    return {
        "tenant_restricted_legal_content": {
            **common,
            "sensitivity": "privileged_or_confidential",
            "source_licence_limits": (
                "Do not redistribute client, privileged, licensed, or source payload "
                "without the applicable approval and source terms."
            ),
        },
        "tenant_operational_record": {
            **common,
            "sensitivity": "confidential",
            "source_licence_limits": (
                "Record-specific source and contract limits must be checked before "
                "export or provider transmission."
            ),
        },
        "security_identity_control": {
            **common,
            "sensitivity": "restricted_security",
            "source_licence_limits": (
                "Never export authentication material, secrets, recovery codes, or "
                "provider credentials through a data operation."
            ),
        },
        "billing_provider_evidence": {
            **common,
            "sensitivity": "confidential_financial",
            "source_licence_limits": (
                "Provider, payment, and tax terms restrict disclosure; approved billing "
                "and legal review is required before export or deletion."
            ),
        },
        "public_or_licensed_legal_reference": {
            **common,
            "sensitivity": "internal_or_licensed_reference",
            "source_licence_limits": (
                "Authority, licence, attribution, retrieval, and redistribution terms "
                "must be verified; unverified material remains quarantined."
            ),
        },
        "platform_operational_reference": {
            **common,
            "sensitivity": "internal",
            "source_licence_limits": (
                "No external reuse or transfer is approved merely because a record is "
                "platform-scoped."
            ),
        },
    }


def _column_categories() -> dict[str, dict[str, object]]:
    return {
        "security_secret_or_credential": {
            "sensitivity": "restricted_security",
            "handling": "Redact from logs, exports, errors, metrics, and provider prompts.",
        },
        "privileged_or_raw_content": {
            "sensitivity": "privileged_or_confidential",
            "handling": (
                "Treat as content-bearing; retain, export, purge, and restore only "
                "through an approved handler."
            ),
        },
        "personal_or_contact_data": {
            "sensitivity": "confidential_personal_data",
            "handling": (
                "Do not expose through cross-tenant search, unaudited exports, or "
                "telemetry labels."
            ),
        },
        "financial_or_payment_data": {
            "sensitivity": "confidential_financial",
            "handling": (
                "Keep original evidence and do not expose payment data in telemetry or "
                "generic exports."
            ),
        },
        "external_or_provider_identifier": {
            "sensitivity": "confidential",
            "handling": (
                "Preserve provider terms and do not treat external identifiers as "
                "tenant-editable secrets."
            ),
        },
        "tenant_or_access_identifier": {
            "sensitivity": "confidential",
            "handling": (
                "Use only with company/access filtering; never use as an unauthenticated "
                "data-discovery key."
            ),
        },
        "derived_search_or_embedding_data": {
            "sensitivity": "confidential_derived_data",
            "handling": (
                "Reapply source access/tombstones before retrieval and before any future "
                "disposition action."
            ),
        },
        "lifecycle_or_audit_evidence": {
            "sensitivity": "confidential",
            "handling": (
                "Preserve immutable evidence through approved supersession/tombstone rules "
                "rather than generic update/delete."
            ),
        },
        "temporal_or_version_metadata": {
            "sensitivity": "internal",
            "handling": (
                "Use for lifecycle/reconciliation only; it inherits the source table "
                "retention policy."
            ),
        },
        "configuration_or_state_metadata": {
            "sensitivity": "internal_or_confidential",
            "handling": (
                "Treat configuration payloads as confidential until reviewed for embedded "
                "content or credentials."
            ),
        },
        "domain_attribute": {
            "sensitivity": "inherits_table_profile",
            "handling": (
                "Inherits the registered table profile; a more specific category may be "
                "selected through an explicit override."
            ),
        },
    }


def _table_profile(table_name: str, columns: Mapping[str, object]) -> str:
    normalized = table_name.lower()
    if any(
        token in normalized
        for token in (
            "token",
            "mfa",
            "secret",
            "security",
            "access_grant",
            "ethical_wall",
            "portal_magic",
            "identity_configuration",
        )
    ):
        return "security_identity_control"
    if any(
        token in normalized
        for token in (
            "billing",
            "payment",
            "invoice",
            "credit",
            "refund",
            "coupon",
            "pine_labs",
            "spend",
            "usage",
        )
    ):
        return "billing_provider_evidence"
    if any(
        token in normalized
        for token in (
            "statute",
            "authority",
            "judge",
            "court",
            "forum",
            "legal_update_source",
        )
    ) and "company_id" not in columns:
        return "public_or_licensed_legal_reference"
    if any(
        token in normalized
        for token in (
            "attachment",
            "document",
            "communication",
            "notice",
            "matter",
            "contract",
            "draft",
            "recommendation",
            "ip_",
            "client",
            "provider_snapshot",
        )
    ):
        return "tenant_restricted_legal_content"
    if "company_id" in columns:
        return "tenant_operational_record"
    return "platform_operational_reference"


def _column_category(column_name: str) -> str:
    value = column_name.lower()
    if any(
        token in value
        for token in (
            "secret",
            "password",
            "token",
            "credential",
            "api_key",
            "private_key",
            "recovery_code",
        )
    ):
        return "security_secret_or_credential"
    if any(token in value for token in ("embedding", "vector", "chunk")):
        return "derived_search_or_embedding_data"
    if any(
        token in value
        for token in (
            "body",
            "content",
            "prompt",
            "response",
            "payload",
            "raw",
            "text",
            "html",
            "markdown",
            "transcript",
            "document",
            "file",
            "description",
            "details",
        )
    ):
        return "privileged_or_raw_content"
    if any(
        token in value
        for token in ("email", "phone", "address", "name", "contact", "birth")
    ):
        return "personal_or_contact_data"
    if any(
        token in value
        for token in ("amount", "cost", "price", "fee", "payment", "currency", "tax")
    ):
        return "financial_or_payment_data"
    if any(
        token in value
        for token in ("provider", "external", "webhook", "source", "oauth")
    ):
        return "external_or_provider_identifier"
    if any(
        token in value
        for token in ("company_id", "membership", "user_id", "client_id", "portal_user")
    ) or value == "id" or value.endswith("_id"):
        return "tenant_or_access_identifier"
    if any(
        token in value
        for token in ("audit", "event", "lifecycle", "immutable", "hash", "checksum")
    ):
        return "lifecycle_or_audit_evidence"
    if value.endswith("_at") or value.endswith("_on") or any(
        token in value for token in ("date", "version", "expires", "created", "updated")
    ):
        return "temporal_or_version_metadata"
    if any(
        token in value
        for token in ("status", "state", "policy", "config", "setting", "mode", "type")
    ):
        return "configuration_or_state_metadata"
    return "domain_attribute"


def _non_sql_defaults() -> dict[str, object]:
    return {
        "legal_policy_basis": (
            "Pending named Records/Privacy/Legal/Security approval; this inventory is "
            "not an asserted legal retention basis or policy activation."
        ),
        "default_retention": (
            "No approved automated retention duration. Do not schedule deletion, expiry, "
            "provider deletion, or backup destruction from this registry."
        ),
        "tenant_configurable": False,
        "tenant_retention_bounds": (
            "No tenant override is available until an approved versioned policy defines "
            "per-tenant bounds and authority."
        ),
        "disposition": (
            "registry_fail_closed prevents a Definition-of-Ready pass for an unregistered "
            "class; it does not perform data I/O."
        ),
        "hold_behavior": (
            "A future approved hold must block conflicting disposition. This inventory "
            "does not activate or execute a hold."
        ),
        "region_subprocessor": (
            "Pending approved residency, international-transfer, and subprocessor policy; "
            "no guarantee is asserted."
        ),
        "owner": "Codex",
        "disposition_handler_id": DEFAULT_HANDLER_ID,
        "status": "inventory_registered_runtime_policy_unapproved",
    }


def _non_sql_data_classes() -> list[dict[str, object]]:
    defaults = _non_sql_defaults()
    return [
        {
            **defaults,
            "id": "document-object-prefix-and-version",
            "kind": "object_prefix_version",
            "purpose": (
                "Logical matter/contract attachment objects and any configured GCS object "
                "versions under the company-scoped storage-key namespace."
            ),
            "sensitivity": "privileged_or_confidential",
            "source_licence_limits": (
                "Client and licensed-source bytes must not be exported, replicated, or "
                "deleted outside approved source/contract and legal-hold rules."
            ),
            "implementation_refs": [
                "apps/api/src/caseops_api/services/document_storage.py",
                "apps/api/src/caseops_api/core/settings.py",
                "infra/cloudrun/api-service.yaml",
            ],
        },
        {
            **defaults,
            "id": "document-materialization-cache",
            "kind": "cache",
            "purpose": (
                "Ephemeral local document materialization and process-local caches used by "
                "the API and document worker."
            ),
            "sensitivity": "confidential_or_privileged",
            "source_licence_limits": "Inherits source object and tenant access restrictions.",
            "implementation_refs": [
                "apps/api/src/caseops_api/services/document_storage.py",
                "infra/cloudrun/document-worker-job.yaml",
            ],
        },
        {
            **defaults,
            "id": "sql-relational-index-projections",
            "kind": "sql_index_projection",
            "purpose": (
                "All ORM and Alembic relational indexes derived from registered SQL table "
                "and column classes; index fingerprints are checked below."
            ),
            "sensitivity": "inherits_source_table_or_column",
            "source_licence_limits": "Inherits the registered source table and column limits.",
            "implementation_refs": [
                "apps/api/src/caseops_api/db/models.py",
                "apps/api/alembic/versions",
            ],
        },
        {
            **defaults,
            "id": "authority-document-pgvector-index",
            "kind": "search_vector_index",
            "purpose": "Derived vector search projection for authority-document chunks.",
            "sensitivity": "confidential_derived_data",
            "source_licence_limits": (
                "Inherits authority/source terms and must respect retrieval access."
            ),
            "implementation_refs": [
                "apps/api/alembic/versions/20260417_0003_authority_embeddings.py",
                "apps/api/src/caseops_api/services/authorities.py",
            ],
        },
        {
            **defaults,
            "id": "matter-attachment-pgvector-index",
            "kind": "search_vector_index",
            "purpose": "Derived vector search projection for Matter attachment chunks.",
            "sensitivity": "confidential_derived_data",
            "source_licence_limits": (
                "Inherits Matter/document access, privilege, and source limits."
            ),
            "implementation_refs": [
                "apps/api/alembic/versions/20260418_0004_matter_attachment_embeddings.py",
                "apps/api/src/caseops_api/services/document_processing.py",
            ],
        },
        {
            **defaults,
            "id": "database-queues-outbox-and-dead-letter",
            "kind": "queue_outbox_dead_letter",
            "purpose": (
                "Database-backed document, court, notification, mailbox, and domain-outbox "
                "queue/dead-letter records, including idempotency and consumer-effect state."
            ),
            "sensitivity": "confidential_operational_and_content_metadata",
            "source_licence_limits": "Inherits the source event/document/provider contract.",
            "implementation_refs": [
                "apps/api/src/caseops_api/services/document_jobs.py",
                "apps/api/src/caseops_api/services/domain_outbox.py",
                "apps/api/src/caseops_api/db/models.py",
            ],
        },
        {
            **defaults,
            "id": "application-logs-traces-and-metrics",
            "kind": "log_trace_metric",
            "purpose": (
                "Application logging, optional OpenTelemetry traces, and operational metrics "
                "that must minimize/redact content and identifiers."
            ),
            "sensitivity": "internal_with_confidential_identifiers",
            "source_licence_limits": (
                "Logs/traces/metrics may not become a content or secret export channel."
            ),
            "implementation_refs": [
                "apps/api/src/caseops_api/core/observability.py",
                "apps/api/src/caseops_api/core/settings.py",
            ],
        },
        {
            **defaults,
            "id": "audit-export-artifacts",
            "kind": "export_artifact",
            "purpose": (
                "Existing audit-export job outputs and the reserved future tenant-data export "
                "artifact class. No tenant export dry-run or execute capability is claimed."
            ),
            "sensitivity": "confidential_or_privileged",
            "source_licence_limits": (
                "Exports must exclude secrets, cross-tenant/global data, internal cost/profit, "
                "and non-redistributable source payloads after approved policy review."
            ),
            "implementation_refs": [
                "apps/api/src/caseops_api/services/audit_exports.py",
                "apps/api/src/caseops_api/db/models.py",
            ],
        },
        {
            **defaults,
            "id": "llm-and-embedding-provider-held-content",
            "kind": "provider_held_object",
            "purpose": (
                "Configured or optional LLM, embedding, and prompt-cache provider request/response "
                "content and derived vectors, including bounded authority-metadata extraction "
                "and its one-document provider canary."
            ),
            "sensitivity": "privileged_or_confidential",
            "source_licence_limits": (
                "Provider training, retention, residency, deletion, and permitted-use settings "
                "require approved provider and tenant policy before content transmission."
            ),
            "implementation_refs": [
                "apps/api/src/caseops_api/services/llm.py",
                "apps/api/src/caseops_api/scripts/extract_authority_metadata.py",
                "apps/api/src/caseops_api/services/embeddings.py",
                "apps/api/src/caseops_api/core/settings.py",
            ],
        },
        {
            **defaults,
            "id": "connector-and-payment-provider-held-records",
            "kind": "provider_held_object",
            "purpose": (
                "External mailbox, calendar, Drive, court/source, and payment-provider objects "
                "referenced by connector or provider operations."
            ),
            "sensitivity": "confidential_provider_and_client_data",
            "source_licence_limits": (
                "Every provider/source contract, consent, permitted use, retention, and deletion "
                "capability must be approved before activation or data-operation execution."
            ),
            "implementation_refs": [
                "apps/api/src/caseops_api/services/integrations.py",
                "apps/api/src/caseops_api/services/case_tracking_providers.py",
                "apps/api/src/caseops_api/services/pine_labs.py",
            ],
        },
        {
            **defaults,
            "id": "database-and-object-backups",
            "kind": "backup",
            "purpose": (
                "Production database backups/PITR and object-version recovery copies, including "
                "the required tombstone/hold reapplication before a restore serves traffic."
            ),
            "sensitivity": "inherits_all_protected_source_data",
            "source_licence_limits": (
                "Backup retention and restoration require approved SRE/security/records "
                "evidence."
            ),
            "implementation_refs": [
                "external:approved SRE backup/PITR/object-version evidence required before M2 exit",
                "docs/PRD_IP_LAW_FIRM_PLATFORM_2026-08-01.md",
            ],
        },
    ]


def _skeleton() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "slice_id": "IPLF-028C",
        "status": MAP_STATUS,
        "policy_status": "pending_named_human_approval",
        "purpose": (
            "Versioned repository inventory for DATA-GOV-01 and DATA-GOV-03. It "
            "snapshots SQL tables/columns/indexes and known non-SQL classes so unregistered "
            "data-bearing changes fail Definition of Ready."
        ),
        "completion_boundary": (
            "This inventory does not claim approved retention bounds, legal-hold activation, "
            "tenant export, purge, offboarding, provider deletion, backup recovery/restore, "
            "residency, or data-governance/recovery milestone completion. The only current "
            "disposition behavior is fail-closed Definition-of-Ready validation."
        ),
        "requirement_refs": ["DATA-GOV-01", "DATA-GOV-03"],
        "disposition_handlers": [
            {
                "id": DEFAULT_HANDLER_ID,
                "status": "implemented_definition_of_ready_guard_no_data_operation",
                "implementation_ref": "scripts/ip_data_governance_map.py",
                "behavior": (
                    "Rejects an unregistered table, column, index snapshot, migration, or "
                    "declared provider/storage/telemetry boundary from passing CI. It performs "
                    "no retention, hold, export, purge, offboarding, restore, backup, or "
                    "provider I/O."
                ),
            }
        ],
        "policy_profiles": _policy_profiles(),
        "column_categories": _column_categories(),
        "table_policy_profile_overrides": {},
        "column_category_overrides": {},
        "change_controls": {
            "migration_marker": MIGRATION_MARKER,
            "ci_validate_command": (
                "uv --directory apps/api run python "
                "../../scripts/ip_data_governance_map.py validate"
            ),
            "ci_change_gate_command": (
                "uv --directory apps/api run python "
                "../../scripts/ip_data_governance_map.py check-change --base origin/main"
            ),
            "rule": (
                "A changed Alembic migration or registered storage/provider/telemetry boundary "
                "must change this map and use the migration marker. A future runtime operation "
                "may replace the fail-closed handler only after the required machine policy, "
                "dry-run, and exact-release checks pass."
            ),
        },
        "non_sql_data_classes": _non_sql_data_classes(),
        "sql_tables": [],
        "schema_fingerprint": "",
        "index_inventory": {},
    }


def _table_rows(
    schema: Mapping[str, Mapping[str, Mapping[str, object]]],
    *,
    table_overrides: Mapping[str, object],
    column_overrides: Mapping[str, object],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for table_name, columns in sorted(schema.items()):
        profile = str(table_overrides.get(table_name) or _table_profile(table_name, columns))
        raw_column_overrides = column_overrides.get(table_name, {})
        overrides = raw_column_overrides if isinstance(raw_column_overrides, Mapping) else {}
        rendered_columns: dict[str, dict[str, object]] = {}
        for column_name, details in sorted(columns.items()):
            category = str(overrides.get(column_name) or _column_category(column_name))
            rendered_columns[column_name] = {
                "category_id": category,
                "sql_type": str(details["sql_type"]),
                "nullable": bool(details["nullable"]),
            }
        rows.append(
            {
                "id": table_name,
                "table_name": table_name,
                "purpose": (
                    f"Repository SQL persistence class `{table_name}`; its exact column "
                    "inventory is intentionally versioned below."
                ),
                "policy_profile_id": profile,
                "disposition_handler_id": DEFAULT_HANDLER_ID,
                "columns": rendered_columns,
            }
        )
    return rows


def _schema_fingerprint_payload(
    schema: Mapping[str, Mapping[str, Mapping[str, object]]],
    orm_indexes: list[dict[str, object]],
    migration_indexes: list[str],
) -> dict[str, object]:
    return {
        "sql_schema": schema,
        "orm_indexes": orm_indexes,
        "migration_indexes": migration_indexes,
    }


def generate() -> dict[str, Any]:
    """Refresh only generated SQL inventory while preserving policy decisions."""

    data = copy.deepcopy(_load(MAP_PATH) if MAP_PATH.exists() else _skeleton())
    schema = current_sql_schema()
    orm_indexes = current_orm_indexes()
    migration_indexes = _migration_index_names()
    table_overrides = data.get("table_policy_profile_overrides", {})
    column_overrides = data.get("column_category_overrides", {})
    if not isinstance(table_overrides, Mapping):
        raise ValueError("table_policy_profile_overrides must be an object")
    if not isinstance(column_overrides, Mapping):
        raise ValueError("column_category_overrides must be an object")

    data["sql_tables"] = _table_rows(
        schema,
        table_overrides=table_overrides,
        column_overrides=column_overrides,
    )
    data["schema_fingerprint"] = _fingerprint(
        _schema_fingerprint_payload(schema, orm_indexes, migration_indexes)
    )
    data["index_inventory"] = {
        "orm_index_count": len(orm_indexes),
        "orm_index_fingerprint": _fingerprint(orm_indexes),
        "migration_index_count": len(migration_indexes),
        "migration_index_fingerprint": _fingerprint(migration_indexes),
        "interpretation": (
            "Relational indexes inherit registered source table/column treatment. The "
            "fingerprints deliberately force a reviewed map update for every index change; "
            "the named non-SQL classes separately identify pgvector projections."
        ),
    }
    _write(MAP_PATH, data)
    return data


def _required_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _relative(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def _validate_ref(ref: object) -> bool:
    if not _required_string(ref):
        return False
    ref_text = str(ref)
    if ref_text.startswith("external:"):
        return True
    return (REPO_ROOT / ref_text).exists()


def validate(
    data: dict[str, Any] | None = None,
    *,
    sql_schema: dict[str, dict[str, dict[str, object]]] | None = None,
    orm_indexes: list[dict[str, object]] | None = None,
    migration_indexes: list[str] | None = None,
    check_generated_view: bool = True,
) -> list[str]:
    """Return all map integrity errors without mutating the registry."""

    errors: list[str] = []
    if data is None:
        if not MAP_PATH.exists():
            return [f"data-governance map is missing: {_relative(MAP_PATH)}"]
        data = _load(MAP_PATH)
    if data.get("schema_version") != 1:
        errors.append("data-governance map schema_version must be 1")
    if data.get("slice_id") != "IPLF-028C":
        errors.append("data-governance map must remain bounded to IPLF-028C")
    if data.get("status") != MAP_STATUS:
        errors.append("data-governance map must preserve the policy-unapproved inventory status")
    if data.get("policy_status") != "pending_named_human_approval":
        errors.append("data-governance map must preserve pending human policy approval")
    completion_boundary = str(data.get("completion_boundary", "")).lower()
    for term in ("does not claim", "export", "purge", "restore", "residency"):
        if term not in completion_boundary:
            errors.append("data-governance map must state its explicit incomplete boundary")
            break
    if data.get("requirement_refs") != ["DATA-GOV-01", "DATA-GOV-03"]:
        errors.append("data-governance map must retain the DATA-GOV-01 and DATA-GOV-03 scope")

    profiles = data.get("policy_profiles")
    if not isinstance(profiles, Mapping) or not profiles:
        errors.append("data-governance map must define policy_profiles")
        profiles = {}
    for profile_id, profile in profiles.items():
        if not isinstance(profile, Mapping):
            errors.append(f"policy-profile/{profile_id}: must be an object")
            continue
        missing = sorted(REQUIRED_POLICY_FIELDS - set(profile))
        if missing:
            errors.append(f"policy-profile/{profile_id}: missing fields {missing}")
        for field in REQUIRED_POLICY_FIELDS - {"tenant_configurable"}:
            if not _required_string(profile.get(field)):
                errors.append(f"policy-profile/{profile_id}: {field} must be explicit")
        if not isinstance(profile.get("tenant_configurable"), bool):
            errors.append(f"policy-profile/{profile_id}: tenant_configurable must be boolean")

    categories = data.get("column_categories")
    if not isinstance(categories, Mapping) or not categories:
        errors.append("data-governance map must define column_categories")
        categories = {}
    for category_id, category in categories.items():
        if not isinstance(category, Mapping):
            errors.append(f"column-category/{category_id}: must be an object")
            continue
        for field in ("sensitivity", "handling"):
            if not _required_string(category.get(field)):
                errors.append(f"column-category/{category_id}: {field} must be explicit")

    handlers = data.get("disposition_handlers")
    if not isinstance(handlers, list):
        errors.append("data-governance map must define disposition_handlers")
        handlers = []
    handler_by_id = {
        str(row.get("id")): row for row in handlers if isinstance(row, Mapping)
    }
    handler = handler_by_id.get(DEFAULT_HANDLER_ID)
    if handler is None:
        errors.append("data-governance map must include registry_fail_closed handler")
    else:
        if handler.get("status") != "implemented_definition_of_ready_guard_no_data_operation":
            errors.append("registry_fail_closed handler must not overclaim runtime execution")
        if handler.get("implementation_ref") != "scripts/ip_data_governance_map.py":
            errors.append("registry_fail_closed handler must reference this validator")
        if not _required_string(handler.get("behavior")):
            errors.append("registry_fail_closed handler must describe fail-closed behavior")

    controls = data.get("change_controls")
    if not isinstance(controls, Mapping):
        errors.append("data-governance map must define change_controls")
    elif controls.get("migration_marker") != MIGRATION_MARKER:
        errors.append("data-governance map must preserve the required migration marker")

    actual_schema = sql_schema if sql_schema is not None else current_sql_schema()
    actual_orm_indexes = orm_indexes if orm_indexes is not None else current_orm_indexes()
    actual_migration_indexes = (
        migration_indexes if migration_indexes is not None else _migration_index_names()
    )
    rows = data.get("sql_tables")
    if not isinstance(rows, list) or not rows:
        errors.append("data-governance map must enumerate every sql_tables row")
        rows = []
    row_by_name: dict[str, Mapping[str, object]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            errors.append("sql-table entry must be an object")
            continue
        table_name = str(row.get("table_name", ""))
        if table_name in row_by_name:
            errors.append(f"duplicate sql-table entry: {table_name}")
        row_by_name[table_name] = row
    actual_table_names = set(actual_schema)
    registered_table_names = set(row_by_name)
    if registered_table_names != actual_table_names:
        missing = sorted(actual_table_names - registered_table_names)
        extra = sorted(registered_table_names - actual_table_names)
        errors.append(
            "sql-table inventory must exactly match SQLAlchemy metadata "
            f"(missing={missing}, extra={extra})"
        )
    for table_name, expected_columns in sorted(actual_schema.items()):
        row = row_by_name.get(table_name)
        if row is None:
            continue
        if row.get("id") != table_name:
            errors.append(f"sql-table/{table_name}: id must equal table_name")
        if not _required_string(row.get("purpose")):
            errors.append(f"sql-table/{table_name}: purpose must be explicit")
        profile_id = str(row.get("policy_profile_id", ""))
        if profile_id not in profiles:
            errors.append(f"sql-table/{table_name}: unknown policy_profile_id {profile_id!r}")
        if row.get("disposition_handler_id") not in handler_by_id:
            errors.append(f"sql-table/{table_name}: unknown disposition handler")
        columns = row.get("columns")
        if not isinstance(columns, Mapping):
            errors.append(f"sql-table/{table_name}: columns must be an object")
            continue
        if set(columns) != set(expected_columns):
            missing = sorted(set(expected_columns) - set(columns))
            extra = sorted(set(columns) - set(expected_columns))
            errors.append(
                f"sql-table/{table_name}: columns must exactly match metadata "
                f"(missing={missing}, extra={extra})"
            )
        for column_name, expected in expected_columns.items():
            column = columns.get(column_name)
            if not isinstance(column, Mapping):
                errors.append(f"sql-table/{table_name}/column/{column_name}: missing mapping")
                continue
            category_id = str(column.get("category_id", ""))
            if category_id not in categories:
                errors.append(
                    f"sql-table/{table_name}/column/{column_name}: unknown category {category_id!r}"
                )
            if column.get("sql_type") != expected["sql_type"]:
                errors.append(
                    f"sql-table/{table_name}/column/{column_name}: sql_type drift "
                    "requires map update"
                )
            if column.get("nullable") != expected["nullable"]:
                errors.append(
                    f"sql-table/{table_name}/column/{column_name}: nullability drift "
                    "requires map update"
                )

    table_overrides = data.get("table_policy_profile_overrides", {})
    if not isinstance(table_overrides, Mapping):
        errors.append("table_policy_profile_overrides must be an object")
    else:
        for table_name, profile_id in table_overrides.items():
            if table_name not in actual_schema:
                errors.append(f"table profile override references unknown table {table_name}")
            if profile_id not in profiles:
                errors.append(f"table profile override uses unknown profile {profile_id!r}")
    column_overrides = data.get("column_category_overrides", {})
    if not isinstance(column_overrides, Mapping):
        errors.append("column_category_overrides must be an object")
    else:
        for table_name, overrides in column_overrides.items():
            if table_name not in actual_schema:
                errors.append(f"column category override references unknown table {table_name}")
                continue
            if not isinstance(overrides, Mapping):
                errors.append(f"column category override for {table_name} must be an object")
                continue
            for column_name, category_id in overrides.items():
                if column_name not in actual_schema[table_name]:
                    errors.append(
                        "column category override references unknown column "
                        f"{table_name}.{column_name}"
                    )
                if category_id not in categories:
                    errors.append(
                        f"column category override uses unknown category {category_id!r}"
                    )

    expected_schema_fingerprint = _fingerprint(
        _schema_fingerprint_payload(
            actual_schema, actual_orm_indexes, actual_migration_indexes
        )
    )
    if data.get("schema_fingerprint") != expected_schema_fingerprint:
        errors.append("SQL schema/index fingerprint drift requires `generate` and review")
    index_inventory = data.get("index_inventory")
    if not isinstance(index_inventory, Mapping):
        errors.append("data-governance map must define index_inventory")
    else:
        expected_index_values = {
            "orm_index_count": len(actual_orm_indexes),
            "orm_index_fingerprint": _fingerprint(actual_orm_indexes),
            "migration_index_count": len(actual_migration_indexes),
            "migration_index_fingerprint": _fingerprint(actual_migration_indexes),
        }
        for key, expected in expected_index_values.items():
            if index_inventory.get(key) != expected:
                errors.append(f"index_inventory/{key}: drift requires map update")
        if not _required_string(index_inventory.get("interpretation")):
            errors.append("index_inventory must state the inherited-index treatment")

    non_sql = data.get("non_sql_data_classes")
    if not isinstance(non_sql, list) or not non_sql:
        errors.append("data-governance map must define non_sql_data_classes")
        non_sql = []
    seen_non_sql: set[str] = set()
    kinds: set[str] = set()
    for row in non_sql:
        if not isinstance(row, Mapping):
            errors.append("non-SQL data class must be an object")
            continue
        class_id = str(row.get("id", ""))
        if class_id in seen_non_sql:
            errors.append(f"duplicate non-SQL data class: {class_id}")
        seen_non_sql.add(class_id)
        kinds.add(str(row.get("kind", "")))
        missing = sorted(REQUIRED_NON_SQL_FIELDS - set(row))
        if missing:
            errors.append(f"non-SQL/{class_id}: missing fields {missing}")
        for field in REQUIRED_NON_SQL_FIELDS - {"tenant_configurable", "implementation_refs"}:
            if field in {"id", "kind", "disposition_handler_id", "status"}:
                continue
            if not _required_string(row.get(field)):
                errors.append(f"non-SQL/{class_id}: {field} must be explicit")
        if not _required_string(class_id) or not _required_string(row.get("kind")):
            errors.append("non-SQL data class id and kind must be explicit")
        if not isinstance(row.get("tenant_configurable"), bool):
            errors.append(f"non-SQL/{class_id}: tenant_configurable must be boolean")
        if row.get("disposition_handler_id") not in handler_by_id:
            errors.append(f"non-SQL/{class_id}: unknown disposition handler")
        if row.get("status") != "inventory_registered_runtime_policy_unapproved":
            errors.append(f"non-SQL/{class_id}: must not overclaim runtime policy approval")
        refs = row.get("implementation_refs")
        if not isinstance(refs, list) or not refs:
            errors.append(f"non-SQL/{class_id}: implementation_refs must be non-empty")
        elif any(not _validate_ref(ref) for ref in refs):
            errors.append(f"non-SQL/{class_id}: implementation ref does not exist")
    missing_kinds = sorted(REQUIRED_NON_SQL_KINDS - kinds)
    if missing_kinds:
        errors.append(f"non-SQL data classes missing required kinds: {missing_kinds}")
    if check_generated_view and not errors:
        expected = _render_markdown(data).encode("utf-8")
        if not GENERATED_VIEW_PATH.is_file():
            errors.append(
                "missing generated data-governance map "
                f"{_relative(GENERATED_VIEW_PATH)}"
            )
        elif GENERATED_VIEW_PATH.read_bytes() != expected:
            errors.append(
                "stale or independently edited generated data-governance map "
                f"{_relative(GENERATED_VIEW_PATH)}; run `render`"
            )
    return errors


def _render_markdown(data: Mapping[str, Any]) -> str:
    """Build the checked-in human projection without mutating the repository."""

    rows = data["sql_tables"]
    non_sql = data["non_sql_data_classes"]
    index_inventory = data["index_inventory"]
    lines = [
        "# Repository Data-Governance Map",
        "",
        "Generated from `DATA_GOVERNANCE_MAP.yaml`; do not edit this view directly.",
        "",
        "## Status",
        "",
        f"- Status: `{data['status']}`",
        f"- Policy approval: `{data['policy_status']}`",
        f"- Canonical map SHA-256: `{_fingerprint(data)}`",
        f"- SQL tables: `{len(rows)}`",
        f"- SQL columns: `{sum(len(row['columns']) for row in rows)}`",
        f"- ORM indexes: `{index_inventory['orm_index_count']}`",
        f"- Alembic/raw index declarations: `{index_inventory['migration_index_count']}`",
        f"- Non-SQL data classes: `{len(non_sql)}`",
        "",
        "## Boundary",
        "",
        data["completion_boundary"],
        "",
        "## SQL table inventory",
        "",
        "| Table | Policy profile | Columns | Disposition handler |",
        "| --- | --- | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            f"| `{row['table_name']}` | `{row['policy_profile_id']}` | "
            f"{len(row['columns'])} | `{row['disposition_handler_id']}` |"
        )
    lines.extend(
        [
            "",
            "## Known non-SQL data classes",
            "",
            "| ID | Kind | Disposition handler |",
            "| --- | --- | --- |",
        ]
    )
    for row in non_sql:
        lines.append(
            f"| `{row['id']}` | `{row['kind']}` | `{row['disposition_handler_id']}` |"
        )
    lines.extend(
        [
            "",
            "## Change control",
            "",
            "Any changed Alembic migration or registered storage/provider/telemetry "
            "boundary must update the machine-readable map. New migrations also require "
            f"the marker `{MIGRATION_MARKER}`. The current handler is intentionally "
            "fail-closed and performs no data operation.",
            "",
        ]
    )
    return "\n".join(lines)


def render(data: dict[str, Any] | None = None) -> Path:
    """Render a compact human view; the machine-readable map remains canonical."""

    if data is None:
        data = _load(MAP_PATH)
    errors = validate(data, check_generated_view=False)
    if errors:
        raise ValueError("cannot render invalid data-governance map: " + "; ".join(errors))
    GENERATED_VIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    GENERATED_VIEW_PATH.write_bytes(_render_markdown(data).encode("utf-8"))
    return GENERATED_VIEW_PATH


def _normalise_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def change_gate_errors(
    changed_paths: list[str], *, source_by_path: Mapping[str, str]
) -> list[str]:
    """Validate a supplied diff; exposed for deterministic unit tests."""

    normalized_paths = {_normalise_path(path) for path in changed_paths}
    map_changed = _relative(MAP_PATH) in normalized_paths
    risky_paths: list[str] = []
    migration_paths: list[str] = []
    for path in sorted(normalized_paths):
        if path.startswith("apps/api/alembic/versions/") and path.endswith(".py"):
            migration_paths.append(path)
            risky_paths.append(path)
            continue
        source = source_by_path.get(path, "")
        if path in RISKY_PATHS or (
            path.startswith(RISKY_SOURCE_ROOTS) and risky_source_match(path, source)
        ):
            risky_paths.append(path)
    errors: list[str] = []
    if risky_paths and not map_changed:
        errors.append(
            "data-bearing changes require DATA_GOVERNANCE_MAP.yaml update: "
            + ", ".join(risky_paths)
        )
    for path in migration_paths:
        source = source_by_path.get(path, "")
        if MIGRATION_MARKER not in source:
            errors.append(f"migration {path} is missing required marker: {MIGRATION_MARKER}")
    return errors


def _git_output(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=REPO_ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def _default_base() -> str:
    github_base = os.environ.get("GITHUB_BASE_REF", "").strip()
    if github_base:
        candidate = f"origin/{github_base}"
        try:
            _git_output("rev-parse", "--verify", candidate)
            return candidate
        except subprocess.CalledProcessError:
            pass
    for candidate in ("origin/main", "HEAD^"):
        try:
            _git_output("rev-parse", "--verify", candidate)
            return candidate
        except subprocess.CalledProcessError:
            continue
    return "HEAD"


def check_change(base: str | None = None) -> list[str]:
    """Run the Definition-of-Ready diff gate against a Git base revision."""

    selected_base = base or _default_base()
    try:
        diff = _git_output("diff", "--name-only", f"{selected_base}...HEAD")
    except subprocess.CalledProcessError as exc:
        return [f"cannot determine change set from {selected_base}: {exc.output.strip()}"]
    changed_paths = [line for line in diff.splitlines() if line.strip()]
    source_by_path: dict[str, str] = {}
    for path in changed_paths:
        normalized = _normalise_path(path)
        candidate = REPO_ROOT / normalized
        if candidate.is_file():
            source_by_path[normalized] = candidate.read_text(encoding="utf-8")
    return change_gate_errors(changed_paths, source_by_path=source_by_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("generate", "validate", "render", "check-change"),
        nargs="?",
        default="validate",
    )
    parser.add_argument("--base", help="Git revision used by check-change")
    args = parser.parse_args(argv)
    if args.command == "generate":
        data = generate()
        print(
            "generated data-governance map: "
            f"{len(data['sql_tables'])} SQL tables and "
            f"{sum(len(row['columns']) for row in data['sql_tables'])} columns"
        )
        return 0
    if args.command == "render":
        print(f"rendered {render()}")
        return 0
    errors = check_change(args.base) if args.command == "check-change" else validate()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if args.command == "check-change":
        print("data-governance change gate valid")
    else:
        print("data-governance map valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
