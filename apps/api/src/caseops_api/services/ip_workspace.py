"""Tenant-scoped IP workspace configuration and safe readiness probes."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    CompanyMembership,
    IpWorkspaceConfiguration,
    IpWorkspaceTestResult,
)
from caseops_api.schemas.ip_records import (
    IpWorkspaceConfigurationStatusResponse,
    IpWorkspaceConfigurationUpsertRequest,
    IpWorkspaceEnableRequest,
    IpWorkspaceTestRunRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.session_context import SessionContext

AUTOMATION_REQUIRED_TESTS: dict[str, frozenset[str]] = {
    "registry_sync": frozenset({"connection", "source_open"}),
    "deadline_automation": frozenset({"deadline_calculation"}),
    "notification_automation": frozenset({"notification"}),
}

TEST_FEATURE: dict[str, str] = {
    "connection": "registry_sync",
    "source_open": "registry_sync",
    "deadline_calculation": "deadline_automation",
    "notification": "notification_automation",
}


def _configuration(
    session: Session,
    *,
    company_id: str,
    for_update: bool = False,
) -> IpWorkspaceConfiguration | None:
    stmt = select(IpWorkspaceConfiguration).where(
        IpWorkspaceConfiguration.company_id == company_id
    )
    if for_update:
        stmt = stmt.with_for_update()
    return session.scalar(stmt)


def _active_membership(
    session: Session,
    *,
    company_id: str,
    membership_id: str,
) -> CompanyMembership:
    row = session.scalar(
        select(CompanyMembership).where(
            CompanyMembership.id == membership_id,
            CompanyMembership.company_id == company_id,
            CompanyMembership.is_active.is_(True),
        )
    )
    if row is None:
        raise HTTPException(
            status_code=422,
            detail="Escalation owner is not an active tenant member.",
        )
    return row


def _tests_for_current_version(
    session: Session,
    configuration: IpWorkspaceConfiguration,
) -> list[IpWorkspaceTestResult]:
    return list(
        session.scalars(
            select(IpWorkspaceTestResult)
            .where(
                IpWorkspaceTestResult.company_id == configuration.company_id,
                IpWorkspaceTestResult.configuration_id == configuration.id,
                IpWorkspaceTestResult.config_version == configuration.version,
            )
            .order_by(
                IpWorkspaceTestResult.performed_at.desc(),
                IpWorkspaceTestResult.id.desc(),
            )
        ).all()
    )


def _latest_test_statuses(
    rows: list[IpWorkspaceTestResult],
) -> dict[tuple[str, str | None], str]:
    statuses: dict[tuple[str, str | None], str] = {}
    for row in rows:
        statuses.setdefault((row.test_kind, row.feature_id), row.status)
    return statuses


def _enablement_blockers(
    configuration: IpWorkspaceConfiguration | None,
    tests: list[IpWorkspaceTestResult],
    automations: list[str] | None = None,
) -> list[str]:
    if configuration is None:
        return ["workspace_configuration_missing"]
    blockers: list[str] = []
    if not configuration.enabled_asset_types_json:
        blockers.append("asset_types_missing")
    if not configuration.jurisdictions_json:
        blockers.append("jurisdictions_missing")
    if not configuration.offices_json:
        blockers.append("offices_missing")
    if not configuration.deadline_rule_versions_json:
        blockers.append("deadline_rules_missing")
    if not configuration.notification_channels_json:
        blockers.append("notification_channels_missing")
    if configuration.provider_keys_json and not configuration.provider_terms_accepted_at:
        blockers.append("provider_terms_not_accepted")
    statuses = _latest_test_statuses(tests)
    requested = automations if automations is not None else configuration.enabled_automations_json
    for feature_id in requested:
        for test_kind in sorted(AUTOMATION_REQUIRED_TESTS[feature_id]):
            if statuses.get((test_kind, feature_id)) != "passed":
                blockers.append(f"{feature_id}:{test_kind}_not_passed")
    return blockers


def get_ip_workspace_configuration_status(
    session: Session,
    *,
    context: SessionContext,
) -> IpWorkspaceConfigurationStatusResponse:
    configuration = _configuration(session, company_id=context.company.id)
    tests = _tests_for_current_version(session, configuration) if configuration else []
    blockers = _enablement_blockers(configuration, tests)
    return IpWorkspaceConfigurationStatusResponse(
        configuration=configuration,
        tests=tests,
        ready_for_manual_docketing=(configuration is not None and not _enablement_blockers(
            configuration,
            tests,
            [],
        )),
        enablement_blockers=blockers,
    )


def upsert_ip_workspace_configuration(
    session: Session,
    *,
    context: SessionContext,
    payload: IpWorkspaceConfigurationUpsertRequest,
) -> IpWorkspaceConfigurationStatusResponse:
    company_id = context.company.id
    _active_membership(
        session,
        company_id=company_id,
        membership_id=payload.escalation_owner_membership_id,
    )
    row = _configuration(session, company_id=company_id, for_update=True)
    now = datetime.now(UTC)
    if row is None:
        if payload.expected_version is not None:
            raise HTTPException(status_code=409, detail="Workspace configuration does not exist.")
        row = IpWorkspaceConfiguration(
            company_id=company_id,
            version=1,
            timezone=payload.timezone,
            holiday_calendar_key=payload.holiday_calendar_key,
            document_taxonomy_version=payload.document_taxonomy_version,
            event_catalog_version=payload.event_catalog_version,
            escalation_owner_membership_id=payload.escalation_owner_membership_id,
            updated_by_membership_id=context.membership.id,
        )
        session.add(row)
    else:
        if payload.expected_version != row.version:
            raise HTTPException(status_code=409, detail="Workspace configuration changed; reload.")
        row.version += 1
        row.workspace_enabled = False
        row.enabled_automations_json = []
        row.updated_by_membership_id = context.membership.id
        row.updated_at = now

    providers_unchanged = (
        list(row.provider_keys_json or []) == payload.provider_keys
        and row.provider_terms_version == payload.provider_terms_version
    )
    if payload.provider_keys and not payload.accept_provider_terms and not (
        providers_unchanged and row.provider_terms_accepted_at is not None
    ):
        raise HTTPException(
            status_code=409,
            detail="Provider attribution and cost terms must be accepted for configured providers.",
        )

    row.enabled_asset_types_json = payload.enabled_asset_types
    row.jurisdictions_json = payload.jurisdictions
    row.offices_json = payload.offices
    row.timezone = payload.timezone
    row.holiday_calendar_key = payload.holiday_calendar_key
    row.working_day_policy_json = payload.working_day_policy
    row.document_taxonomy_version = payload.document_taxonomy_version
    row.event_catalog_version = payload.event_catalog_version
    row.deadline_rule_versions_json = payload.deadline_rule_versions
    row.notification_channels_json = payload.notification_channels
    row.critical_event_policy_json = payload.critical_event_policy
    row.escalation_owner_membership_id = payload.escalation_owner_membership_id
    row.provider_keys_json = payload.provider_keys
    row.provider_terms_version = payload.provider_terms_version
    if payload.accept_provider_terms:
        row.provider_terms_accepted_by_membership_id = context.membership.id
        row.provider_terms_accepted_at = now
    elif not payload.provider_keys:
        row.provider_terms_accepted_by_membership_id = None
        row.provider_terms_accepted_at = None
    session.flush()
    record_from_context(
        session,
        context,
        action="ip_workspace.configuration_saved",
        target_type="ip_workspace_configuration",
        target_id=row.id,
        metadata={
            "version": row.version,
            "jurisdictions": row.jurisdictions_json,
            "offices": row.offices_json,
            "provider_keys": row.provider_keys_json,
            "provider_terms_version": row.provider_terms_version,
            "workspace_enabled": False,
        },
    )
    session.commit()
    return get_ip_workspace_configuration_status(session, context=context)


def run_ip_workspace_test(
    session: Session,
    *,
    context: SessionContext,
    payload: IpWorkspaceTestRunRequest,
) -> IpWorkspaceTestResult:
    row = _configuration(session, company_id=context.company.id, for_update=True)
    if row is None:
        raise HTTPException(status_code=409, detail="Configure the IP workspace first.")
    if row.version != payload.expected_config_version:
        raise HTTPException(status_code=409, detail="Workspace configuration changed; reload.")
    expected_feature = TEST_FEATURE[payload.test_kind]
    if payload.feature_id is not None and payload.feature_id != expected_feature:
        raise HTTPException(
            status_code=422,
            detail="Test kind does not match the automation feature.",
        )

    passed, failure_code, details = _execute_safe_test(row, payload)
    result = IpWorkspaceTestResult(
        company_id=context.company.id,
        configuration_id=row.id,
        config_version=row.version,
        test_kind=payload.test_kind,
        feature_id=expected_feature,
        provider_key=payload.provider_key,
        status="passed" if passed else "failed",
        failure_code=failure_code,
        details_json=details,
        performed_by_membership_id=context.membership.id,
    )
    session.add(result)
    session.flush()
    record_from_context(
        session,
        context,
        action="ip_workspace.readiness_test_completed",
        target_type="ip_workspace_test_result",
        target_id=result.id,
        metadata={
            "configuration_id": row.id,
            "config_version": row.version,
            "test_kind": result.test_kind,
            "feature_id": result.feature_id,
            "provider_key": result.provider_key,
            "status": result.status,
            "failure_code": result.failure_code,
            "dry_run": True,
        },
    )
    session.commit()
    session.refresh(result)
    return result


def _execute_safe_test(
    configuration: IpWorkspaceConfiguration,
    payload: IpWorkspaceTestRunRequest,
) -> tuple[bool, str | None, dict[str, object]]:
    if payload.test_kind in {"connection", "source_open"}:
        if not payload.provider_key or payload.provider_key not in configuration.provider_keys_json:
            return False, "provider_not_configured", {"dry_run": True, "external_call": False}
        if configuration.provider_terms_accepted_at is None:
            return False, "provider_terms_not_accepted", {"dry_run": True, "external_call": False}
        return True, None, {
            "dry_run": True,
            "external_call": False,
            "provider_reference_present": True,
            "terms_version": configuration.provider_terms_version,
        }
    if payload.test_kind == "notification":
        if not configuration.notification_channels_json:
            return False, "notification_channel_missing", {"dry_run": True, "sent": False}
        return True, None, {
            "dry_run": True,
            "sent": False,
            "validated_channels": configuration.notification_channels_json,
        }
    if not configuration.deadline_rule_versions_json:
        return False, "deadline_rule_missing", {"dry_run": True}
    working_days = set(configuration.working_day_policy_json["working_weekdays"])
    sample = date(2026, 8, 7)
    candidate = sample + timedelta(days=1)
    while candidate.weekday() not in working_days:
        candidate += timedelta(days=1)
    return True, None, {
        "dry_run": True,
        "sample_start": sample.isoformat(),
        "sample_next_working_day": candidate.isoformat(),
        "holiday_calendar_key": configuration.holiday_calendar_key,
        "rule_versions": configuration.deadline_rule_versions_json,
        "legal_deadline": False,
    }


def enable_ip_workspace(
    session: Session,
    *,
    context: SessionContext,
    payload: IpWorkspaceEnableRequest,
) -> IpWorkspaceConfigurationStatusResponse:
    row = _configuration(session, company_id=context.company.id, for_update=True)
    if row is None:
        raise HTTPException(status_code=409, detail="Configure the IP workspace first.")
    if row.version != payload.expected_config_version:
        raise HTTPException(status_code=409, detail="Workspace configuration changed; reload.")
    tests = _tests_for_current_version(session, row)
    blockers = _enablement_blockers(row, tests, payload.enabled_automations)
    if blockers:
        raise HTTPException(
            status_code=409,
            detail={"code": "ip_workspace_not_ready", "blockers": blockers},
        )
    row.enabled_automations_json = payload.enabled_automations
    row.workspace_enabled = True
    row.updated_by_membership_id = context.membership.id
    row.updated_at = datetime.now(UTC)
    record_from_context(
        session,
        context,
        action="ip_workspace.enabled",
        target_type="ip_workspace_configuration",
        target_id=row.id,
        metadata={
            "version": row.version,
            "workspace_enabled": True,
            "enabled_automations": row.enabled_automations_json,
            "test_result_ids": [test.id for test in tests],
        },
    )
    session.commit()
    return get_ip_workspace_configuration_status(session, context=context)
