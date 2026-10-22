"""Opt-in account names without widening the strict legacy report DTOs."""

from __future__ import annotations

from caseops_api.schemas.platform_console import (
    ConsoleCompanyProfitRecord,
    ConsoleCostGuardrailAlert,
    ConsoleMarginAlert,
    ConsoleOverviewResponse,
    ConsoleProfitRecord,
    ConsoleReportPage,
    ConsoleRevenueRecord,
    ConsoleUsageRecord,
)


class ConsoleNamedUsageRecord(ConsoleUsageRecord):
    company_name: str | None


class ConsoleNamedRevenueRecord(ConsoleRevenueRecord):
    company_name: str | None


class ConsoleNamedMarginAlert(ConsoleMarginAlert):
    company_name: str | None


class ConsoleNamedReportPage(ConsoleReportPage):
    items: list[
        ConsoleNamedUsageRecord
        | ConsoleProfitRecord
        | ConsoleNamedRevenueRecord
        | ConsoleCompanyProfitRecord
    ]


class ConsoleNamedOverviewResponse(ConsoleOverviewResponse):
    margin_alerts: list[ConsoleNamedMarginAlert | ConsoleCostGuardrailAlert]
