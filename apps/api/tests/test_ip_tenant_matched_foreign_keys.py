"""Database-boundary tenant matching for new IP operational references."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from caseops_api.db.models import (
    BulkImportJob,
    IpDeadlineCoverage,
    IpDocketControlReview,
    IpDocketQueue,
    IpIdentifier,
    IpImportRow,
)
from caseops_api.db.session import get_engine
from tests.test_auth_company import bootstrap_company

EXPECTED_MODEL_CONSTRAINTS = {
    BulkImportJob: {
        "fk_bulk_import_job_creator_company": ["created_by_membership_id", "company_id"]
    },
    IpImportRow: {
        "fk_ip_import_row_created_docket_company": ["created_docket_id", "company_id"]
    },
    IpDocketControlReview: {
        "fk_ip_control_review_signer_company": [
            "signed_off_by_membership_id",
            "company_id",
        ],
        "fk_ip_control_review_creator_company": ["created_by_membership_id", "company_id"],
    },
    IpDeadlineCoverage: {
        "fk_ip_coverage_pending_replacement_company": [
            "pending_replacement_membership_id",
            "company_id",
        ],
        "fk_ip_coverage_emergency_escalation_company": [
            "emergency_escalation_membership_id",
            "company_id",
        ],
    },
    IpDocketQueue: {
        "fk_ip_docket_queue_team_company": ["team_id", "company_id"],
        "fk_ip_docket_queue_owner_company": ["owner_membership_id", "company_id"],
        "fk_ip_docket_queue_creator_company": ["created_by_membership_id", "company_id"],
    },
    IpIdentifier: {
        "fk_ip_identifier_supersedes_company": ["supersedes_identifier_id", "company_id"],
        "fk_ip_identifier_superseded_by_company": [
            "superseded_by_identifier_id",
            "company_id",
        ],
    },
}


def _bootstrap_other_company(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Tenant Boundary Two LLP",
            "company_slug": "tenant-boundary-two",
            "company_type": "law_firm",
            "owner_full_name": "Tenant Two Owner",
            "owner_email": "owner@tenant-boundary-two.example",
            "owner_password": "TenantBoundaryTwo!234",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _assert_cross_tenant_rejected(statement: str, parameters: dict[str, object]) -> None:
    engine = get_engine()
    with pytest.raises(IntegrityError) as excinfo:
        with engine.begin() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            connection.execute(text(statement), parameters)
    assert "FOREIGN KEY constraint failed" in str(excinfo.value)


def test_orm_declares_every_new_tenant_matched_foreign_key() -> None:
    for model, expected_by_name in EXPECTED_MODEL_CONSTRAINTS.items():
        actual_by_name = {
            constraint.name: list(constraint.column_keys)
            for constraint in model.__table__.foreign_key_constraints
            if constraint.name
        }
        for name, columns in expected_by_name.items():
            assert actual_by_name[name] == columns


def test_new_ip_operational_foreign_keys_reject_existing_cross_tenant_targets(
    client: TestClient,
) -> None:
    tenant_a = bootstrap_company(client)
    tenant_b = _bootstrap_other_company(client)
    company_a = str(tenant_a["company"]["id"])
    company_b = str(tenant_b["company"]["id"])
    membership_b = str(tenant_b["membership"]["id"])
    now = datetime.now(UTC)

    # The single-column membership FK accepts this existing membership. Only
    # the paired company FK can reject attaching it to tenant A's import job.
    _assert_cross_tenant_rejected(
        "INSERT INTO bulk_import_jobs "
        "(id, company_id, domain, filename, source_sha256, "
        " created_by_membership_id, creator_label_snapshot, created_at, updated_at) "
        "VALUES (:id, :company, 'ip_trademark', 'tenant.csv', :sha, "
        " :membership, 'Wrong tenant', :now, :now)",
        {
            "id": str(uuid4()),
            "company": company_a,
            "sha": "a" * 64,
            "membership": membership_b,
            "now": now,
        },
    )

    _assert_cross_tenant_rejected(
        "INSERT INTO ip_docket_control_reviews "
        "(id, company_id, generated_at, filters_json, freshness_json, "
        " incompleteness_reasons_json, mandatory_exception_ids_json, "
        " query_version, report_snapshot_json, manifest_sha256, "
        " signed_off_by_membership_id, created_at, updated_at) "
        "VALUES (:id, :company, :now, '{}', '{}', '[]', '[]', "
        " 'daily-docket-v1', '{}', :sha, :membership, :now, :now)",
        {
            "id": str(uuid4()),
            "company": company_a,
            "membership": membership_b,
            "sha": "b" * 64,
            "now": now,
        },
    )

    _assert_cross_tenant_rejected(
        "INSERT INTO ip_docket_queues "
        "(id, company_id, name, filters_json, owner_membership_id, "
        " created_at, updated_at) "
        "VALUES (:id, :company, 'Foreign owner', '{}', :membership, :now, :now)",
        {
            "id": str(uuid4()),
            "company": company_a,
            "membership": membership_b,
            "now": now,
        },
    )

    team_b = str(uuid4())
    engine = get_engine()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO teams "
                "(id, company_id, name, slug, kind, is_active, created_at, updated_at) "
                "VALUES (:id, :company, 'Foreign Team', 'foreign-team', "
                "'team', 1, :now, :now)"
            ),
            {"id": team_b, "company": company_b, "now": now},
        )
    _assert_cross_tenant_rejected(
        "INSERT INTO ip_docket_queues "
        "(id, company_id, name, filters_json, team_id, created_at, updated_at) "
        "VALUES (:id, :company, 'Foreign team queue', '{}', :team, :now, :now)",
        {
            "id": str(uuid4()),
            "company": company_a,
            "team": team_b,
            "now": now,
        },
    )


def test_paired_tenant_constraints_preserve_set_null_and_cascade_actions(
    client: TestClient,
) -> None:
    tenant = bootstrap_company(client)
    company_id = str(tenant["company"]["id"])
    now = datetime.now(UTC)
    user_id = str(uuid4())
    membership_id = str(uuid4())
    import_id = str(uuid4())
    queue_id = str(uuid4())
    engine = get_engine()

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, email, full_name, password_hash, is_active, created_at) "
                "VALUES (:id, :email, 'Ephemeral Member', 'not-used', 1, :now)"
            ),
            {
                "id": user_id,
                "email": f"ephemeral-{user_id[:8]}@example.com",
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO company_memberships "
                "(id, company_id, user_id, role, is_active, created_at) "
                "VALUES (:id, :company, :user, 'member', 1, :now)"
            ),
            {
                "id": membership_id,
                "company": company_id,
                "user": user_id,
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO bulk_import_jobs "
                "(id, company_id, domain, filename, source_sha256, "
                " created_by_membership_id, creator_label_snapshot, created_at, updated_at) "
                "VALUES (:id, :company, 'ip_trademark', 'valid.csv', :sha, "
                " :membership, 'Ephemeral Member', :now, :now)"
            ),
            {
                "id": import_id,
                "company": company_id,
                "sha": "c" * 64,
                "membership": membership_id,
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO ip_docket_queues "
                "(id, company_id, name, filters_json, owner_membership_id, "
                " created_at, updated_at) "
                "VALUES (:id, :company, 'Ephemeral queue', '{}', :membership, :now, :now)"
            ),
            {
                "id": queue_id,
                "company": company_id,
                "membership": membership_id,
                "now": now,
            },
        )
        connection.execute(
            text("DELETE FROM company_memberships WHERE id = :id"),
            {"id": membership_id},
        )

        import_row = connection.execute(
            text(
                "SELECT company_id, created_by_membership_id "
                "FROM bulk_import_jobs WHERE id = :id"
            ),
            {"id": import_id},
        ).one()
        assert import_row == (company_id, None)
        assert (
            connection.scalar(
                text("SELECT count(*) FROM ip_docket_queues WHERE id = :id"),
                {"id": queue_id},
            )
            == 0
        )
