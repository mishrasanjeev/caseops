import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { activityFixture } from "@/lib/platform/activity-fixture.test-data";

import { ActivityReportView } from "./PlatformActivity";

describe("canonical platform account activity", () => {
  it("includes internal and solo accounts without client-side name exclusions", () => {
    render(<ActivityReportView report={activityFixture()} />);
    expect(screen.getByText("All registered accounts")).toBeVisible();
    expect(screen.getByText(/4 accounts in this report; 0 excluded/)).toBeVisible();
    expect(screen.getByText("Test-legal law firm")).toBeVisible();
    expect(screen.getByText("Dormant solo advocate")).not.toBeVisible();
    const summary = screen.getByText("No recorded activity for 30 days (1)");
    expect(summary.closest("details")).not.toHaveAttribute("open");
    fireEvent.click(summary);
    expect(screen.getByText("Dormant solo advocate")).toBeVisible();
  });
  it("keeps unknown engagement expanded and does not equate account disablement with inactivity", () => {
    render(<ActivityReportView report={activityFixture()} />);
    expect(screen.getByText("Corporate unknown evidence")).toBeVisible();
    expect(screen.getByText("Unknown-category account")).toBeVisible();
    expect(screen.getByText("Engagement unknown (2)")).toBeVisible();
    const recent = screen.getByRole("region", { name: "Recent engagement" });
    expect(within(recent).getByText("Disabled")).toBeVisible();
    expect(screen.getByText(/Successful human audit events only/)).toBeVisible();
  });
  it("uses accessible category, name and metric-period filters without changing source totals", () => {
    render(<ActivityReportView report={activityFixture()} />);
    fireEvent.change(screen.getByLabelText("Category"), { target: { value: "solo_lawyers" } });
    expect(screen.queryByText("Test-legal law firm")).not.toBeInTheDocument();
    expect(screen.getByText(/1 matching accounts/)).toBeVisible();
    fireEvent.change(screen.getByLabelText("Metric period"), { target: { value: "month" } });
    expect(screen.getByText(/2026-09-01 - 2026-09-30/)).toBeVisible();
    fireEvent.change(screen.getByLabelText("Account name"), { target: { value: "nonexistent account" } });
    expect(screen.getByText("No accounts match these filters.")).toBeVisible();
    expect(screen.getByText(/4 accounts in this report/)).toBeVisible();
  });
  it("shows an operational-email scope and exclusions without claiming all accounts", () => {
    const report = activityFixture(); report.account_scope = "operational_email"; report.excluded_account_count = 2;
    render(<ActivityReportView report={report} />);
    expect(screen.getByText("Operational email account scope")).toBeVisible();
    expect(screen.getByText(/2 excluded by the server/)).toBeVisible();
    expect(screen.queryByText("All registered accounts")).not.toBeInTheDocument();
  });
  it("retains literal minor units in account evidence and canonical category totals", () => {
    const report = activityFixture();
    const segment = report.segments.law_firms;
    segment.periods.day.invoiced_amount_minor = 123456;
    segment.periods.day.collections_minor = 37;
    segment.accounts[0].periods.day.invoiced_amount_minor = 123456;
    segment.accounts[0].periods.day.collections_minor = 37;
    segment.accounts[0].current.outstanding_amount_minor = 37;
    render(<ActivityReportView report={report} />);
    const recent = screen.getByRole("region", { name: "Recent engagement" });
    fireEvent.click(within(recent).getByText("Activity and current totals"));
    expect(within(recent).getByText("Invoiced value").nextElementSibling).toHaveTextContent(/^\u20b91,234\.56$/);
    expect(within(recent).getByText("Collections").nextElementSibling).toHaveTextContent(/^\u20b90\.37$/);
    expect(within(recent).getByText("Outstanding value").nextElementSibling).toHaveTextContent(/^\u20b90\.37$/);
    fireEvent.click(screen.getByText("Canonical category totals"));
    const totals = screen.getByRole("region", { name: "Category metric totals" });
    expect(within(totals).getByRole("cell", { name: "\u20b91,234.56" })).toBeVisible();
  });
});
