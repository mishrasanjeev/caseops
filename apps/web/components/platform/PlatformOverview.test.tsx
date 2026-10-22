import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlatformFinancialReport, PlatformOverview } from "./PlatformFinancialReport";

const warning = {
  type: "case_refresh_cost_guardrail", severity: "warning", category: "case_refresh", provider: "case_tracking",
  unit_amount_minor: 37, message: "Actual tracked-case refresh cost is INR 0.10 or more. Pause public high-volume fixed-price bundles or require founder quote review.",
};
const overview = {
  generated_at: "2026-10-20T10:00:00Z", coverage: "recorded_rollups", rollup_count: 1,
  mrr_minor: 1200, arr_minor: 14400, active_subscriptions: 2, trial_count: 1, failed_payments: 0,
  gross_revenue_minor: 10000, recognized_revenue_minor: 10000, total_variable_cost_minor: 13000,
  gross_profit_minor: -3000, gross_margin_bps: -3000,
  margin_alerts: [
    { company_id: "loss-account", company_name: "Loss account", gross_margin_bps: -3000, gross_profit_minor: -3000 },
    { company_id: "unknown-margin-account", company_name: "Unknown margin account", gross_margin_bps: null, gross_profit_minor: 100 },
    warning,
  ],
  margin_alerts_has_more: true,
};
const profit = {
  company_id: "account", company_name: "Recorded account", period_start: "2026-10-01T00:00:00Z", period_end: "2026-11-01T00:00:00Z",
  gross_revenue_minor: 123456, recognized_revenue_minor: 123456, tax_minor: 0, tax_collected_minor: 0,
  discounts_minor: 0, discount_minor: 0, payment_provider_cost_minor: 0, payment_gateway_cost_minor: 0,
  llm_cost_minor: 37, embedding_cost_minor: 0, case_refresh_cost_minor: 0, document_processing_cost_minor: 0,
  storage_cost_minor: 0, manual_support_cost_minor: 0, manual_research_cost_minor: 0,
  total_variable_cost_minor: 37, gross_profit_minor: 123419, gross_margin_bps: 9997, status: "recorded",
};
const companyProfit = {
  company_id: "account", company_name: "Recorded account", rollup_count: 1,
  gross_revenue_minor: 123456, recognized_revenue_minor: 123456, tax_minor: 0, discounts_minor: 0,
  payment_provider_cost_minor: 0, payment_gateway_cost_minor: 0, llm_cost_minor: 37, embedding_cost_minor: 0,
  case_refresh_cost_minor: 0, document_processing_cost_minor: 0, storage_cost_minor: 0, manual_support_cost_minor: 0,
  manual_research_cost_minor: 0, total_variable_cost_minor: 37, gross_profit_minor: 123419, gross_margin_bps: 9997, loss_risk: false,
};

describe("canonical overview wire responses", () => {
  let fetcher: ReturnType<typeof vi.fn>;
  beforeEach(() => { fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher); });
  afterEach(() => { vi.unstubAllGlobals(); });
  const serve = (body: unknown) => fetcher.mockResolvedValue(new Response(JSON.stringify(body), { status: 200 }));

  it("renders both canonical alert types through the real client, retaining warning cost and unknown margins", async () => {
    serve(overview);
    render(<PlatformOverview />);
    const alerts = await screen.findByRole("list", { name: "Margin and cost alerts" });
    expect(within(alerts).getAllByRole("listitem")).toHaveLength(3);
    expect(within(alerts).getByText(/loss-account:/)).toHaveTextContent("margin -30.0%");
    expect(within(alerts).getByText(/unknown-margin-account:/)).toHaveTextContent("margin not recorded");
    const cost = within(alerts).getByText("Cost guardrail warning").closest("li")!;
    expect(cost).toHaveTextContent(warning.message);
    expect(cost).toHaveTextContent("case_refresh / case_tracking");
    expect(cost).toHaveTextContent("\u20b90.37 per unit");
    expect(cost).not.toHaveTextContent("undefined");
    expect(cost).not.toHaveTextContent("margin not recorded");
    expect(screen.getByText("Alerts on this page").nextElementSibling).toHaveTextContent(/^3$/);
    expect(screen.getByText("Additional margin alerts exist beyond this bounded overview.")).toBeVisible();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("does not turn a standalone warning or absent financial evidence into zero cost", async () => {
    serve({ ...overview, rollup_count: 0, gross_revenue_minor: null, recognized_revenue_minor: null,
      total_variable_cost_minor: null, gross_profit_minor: null, gross_margin_bps: null,
      margin_alerts: [warning], margin_alerts_has_more: false });
    render(<PlatformOverview />);
    expect(await screen.findByText("Cost guardrail warning")).toBeVisible();
    expect(screen.getByText("Variable cost").nextElementSibling).toHaveTextContent("Not recorded");
    expect(screen.getByText("Alerts on this page").nextElementSibling).toHaveTextContent(/^1$/);
    expect(screen.getByText("case_refresh / case_tracking: \u20b90.37 per unit")).toBeVisible();
  });
  it("renders warning text as text, never HTML", async () => {
    const message = '<img src="untrusted" onerror="alert(1)">';
    serve({ ...overview, margin_alerts: [{ ...warning, message }] });
    render(<PlatformOverview />);
    expect(await screen.findByText(message)).toBeVisible();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
  it.each([
    { kind: "usage" as const, coverage: "recorded_usage", row: { company_id: "named-account", company_name: "Named legal office", feature_key: "document_read", quantity: 2, credits: 0, estimated_internal_cost_minor: 37 } },
    { kind: "revenue" as const, coverage: "recorded_payments", row: { company_id: "named-account", company_name: "Named legal office", paid_at: "2026-10-20T00:00:00Z", merchant_reference: "recorded-payment", amount_paid_minor: 123456, tax_amount_minor: 37 } },
  ])("shows the authoritative account name alongside its retained identifier in $kind", async ({ kind, coverage, row }) => {
    serve({ items: [row], generated_at: "2026-10-20T10:00:00Z", next_cursor: null, has_more: false, coverage });
    render(<PlatformFinancialReport kind={kind} />);
    const table = await screen.findByRole("table");
    expect(within(table).getByText("Named legal office", { exact: true })).toBeVisible();
    expect(within(table).getByText("named-account", { exact: true })).toBeVisible();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("names account-specific overview alerts without inventing an account for provider warnings", async () => {
    serve({ ...overview, margin_alerts: [
      { company_id: "named-account", company_name: "Named legal office", gross_margin_bps: -3000, gross_profit_minor: -3000 },
      warning,
    ] });
    render(<PlatformOverview />);
    const alerts = await screen.findByRole("list", { name: "Margin and cost alerts" });
    expect(within(alerts).getByText("Named legal office", { exact: true })).toBeVisible();
    expect(within(alerts).getByText(/named-account:/)).toBeVisible();
    expect(within(alerts).getByText("Cost guardrail warning")).toBeVisible();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it.each([null, ""])("shows absent account-name evidence honestly (%s)", async (company_name) => {
    serve({ items: [{ company_id: "unnamed-account", company_name, feature_key: "document_read", quantity: 2, credits: 0, estimated_internal_cost_minor: 37 }],
      generated_at: "2026-10-20T10:00:00Z", next_cursor: null, has_more: false, coverage: "recorded_usage" });
    render(<PlatformFinancialReport kind="usage" />);
    const table = await screen.findByRole("table");
    expect(within(table).getByText("Account name not recorded", { exact: true })).toBeVisible();
    expect(within(table).getByText("unnamed-account", { exact: true })).toBeVisible();
  });
  it("renders a submitted account label as plain text, not HTML", async () => {
    const company_name = '<img src="untrusted-account" onerror="alert(1)">';
    serve({ items: [{ company_id: "text-account", company_name, feature_key: "document_read", quantity: 2, credits: 0, estimated_internal_cost_minor: 37 }],
      generated_at: "2026-10-20T10:00:00Z", next_cursor: null, has_more: false, coverage: "recorded_usage" });
    render(<PlatformFinancialReport kind="usage" />);
    expect(await screen.findByText(company_name, { exact: true })).toBeVisible();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
  it("retains literal paise in overview run rates and recorded totals without changing whole-rupee display", async () => {
    serve({ ...overview, mrr_minor: 123456, total_variable_cost_minor: 37 });
    render(<PlatformOverview />);
    expect((await screen.findByText("Configured monthly run rate")).nextElementSibling).toHaveTextContent(/^\u20b91,234\.56$/);
    expect(screen.getByText("Variable cost").nextElementSibling).toHaveTextContent(/^\u20b90\.37$/);
    expect(screen.getByText("Configured annual run rate").nextElementSibling).toHaveTextContent(/^\u20b9144$/);
  });
  it.each([
    { kind: "usage" as const, coverage: "recorded_usage", row: { company_id: "account", company_name: "Recorded account", feature_key: "document_read", quantity: 2, credits: 0, estimated_internal_cost_minor: 37 } },
    { kind: "revenue" as const, coverage: "recorded_payments", row: { company_id: "account", company_name: "Recorded account", paid_at: "2026-10-20T00:00:00Z", merchant_reference: "recorded-payment", amount_paid_minor: 123456, tax_amount_minor: 37 } },
    { kind: "profit" as const, coverage: "recorded_rollups", row: profit },
    { kind: "company-profitability" as const, coverage: "recorded_rollups", row: companyProfit },
  ])("retains literal minor-unit amounts in the canonical $kind response", async ({ kind, coverage, row }) => {
    serve({ items: [row], generated_at: "2026-10-20T10:00:00Z", next_cursor: null, has_more: false, coverage });
    render(<PlatformFinancialReport kind={kind} />);
    const table = await screen.findByRole("table");
    expect(within(table).getAllByText("\u20b90.37").length).toBeGreaterThan(0);
    if (kind !== "usage") expect(within(table).getAllByText("\u20b91,234.56").length).toBeGreaterThan(0);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it.each([
    { ...warning, type: "unreviewed_warning" },
    { ...warning, severity: "critical" },
    { ...warning, message: undefined },
    { ...warning, company_id: "mixed-variant" },
  ])("fails closed for an unknown or incomplete warning instead of showing partial or empty-success totals %#", async (alert) => {
    serve({ ...overview, margin_alerts: [alert] });
    render(<PlatformOverview />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The report response could not be verified. No data is shown.");
    expect(screen.queryByText("Gross revenue")).not.toBeInTheDocument();
    expect(screen.queryByText("No recorded results for this page.")).not.toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
