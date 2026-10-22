import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { activityFixture } from "@/lib/platform/activity-fixture.test-data";
import { formatMoneyMinor } from "@/lib/billing-format";
import { platformApi } from "@/lib/platform/client";

import { PlatformReports } from "./PlatformReports";

vi.mock("@/lib/platform/session", () => ({ usePlatformSession: () => ({ status: "ready", auth: { state: "authenticated", admin: { id: "viewer", role: "viewer" }, expires_at: "2099-01-01T00:00:00Z" }, signOut: vi.fn() }) }));
vi.mock("@/lib/platform/client", () => ({
  platformApi: { activity: vi.fn(), namedOverview: vi.fn(), namedReport: vi.fn() },
  consoleErrorMessage: () => "The report response could not be verified. No data is shown.",
}));

describe("all independent report views", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(platformApi.activity).mockResolvedValue(activityFixture());
    vi.mocked(platformApi.namedReport).mockResolvedValue({ items: [], generated_at: "2026-10-20T00:00:00Z", next_cursor: null, has_more: false, coverage: "recorded_usage" });
    vi.mocked(platformApi.namedOverview).mockResolvedValue({ generated_at: "2026-10-20T00:00:00Z", coverage: "recorded_rollups", rollup_count: 0, mrr_minor: 0, arr_minor: 0, active_subscriptions: 4, trial_count: 1, failed_payments: 0, gross_revenue_minor: null, recognized_revenue_minor: null, total_variable_cost_minor: null, gross_profit_minor: null, gross_margin_bps: null, margin_alerts: [], margin_alerts_has_more: false });
  });
  it("exposes all six views and loads only the selected view", async () => {
    const user = userEvent.setup();
    render(<PlatformReports />);
    expect(screen.getAllByRole("tab")).toHaveLength(6);
    await screen.findByText("Test-legal law firm");
    expect(platformApi.namedOverview).not.toHaveBeenCalled(); expect(platformApi.namedReport).not.toHaveBeenCalled();
    await user.click(screen.getByRole("tab", { name: "Usage" }));
    await waitFor(() => expect(platformApi.namedReport).toHaveBeenLastCalledWith("usage", null, expect.any(AbortSignal)));
    await user.click(screen.getByRole("tab", { name: "Profit" }));
    await waitFor(() => expect(platformApi.namedReport).toHaveBeenLastCalledWith("profit", null, expect.any(AbortSignal)));
    await user.click(screen.getByRole("tab", { name: "Account profitability" }));
    await waitFor(() => expect(platformApi.namedReport).toHaveBeenLastCalledWith("company-profitability", null, expect.any(AbortSignal)));
    await user.click(screen.getByRole("tab", { name: "Revenue" }));
    await waitFor(() => expect(platformApi.namedReport).toHaveBeenLastCalledWith("revenue", null, expect.any(AbortSignal)));
    expect(screen.queryByRole("link", { name: "Administrators" })).not.toBeInTheDocument();
  });
  it("separates positive configured run rates from absent paid-income rollups", async () => {
    vi.mocked(platformApi.namedOverview).mockResolvedValue({ generated_at: "2026-10-20T00:00:00Z", coverage: "recorded_rollups", rollup_count: 0, mrr_minor: 1234500, arr_minor: 14814000, active_subscriptions: 4, trial_count: 1, failed_payments: 0, gross_revenue_minor: null, recognized_revenue_minor: null, total_variable_cost_minor: null, gross_profit_minor: null, gross_margin_bps: null, margin_alerts: [], margin_alerts_has_more: false });
    const user = userEvent.setup(); render(<PlatformReports />);
    await user.click(screen.getByRole("tab", { name: "Overview" }));
    expect((await screen.findAllByText("Not recorded")).length).toBeGreaterThan(0);
    expect(screen.getByText("Configured monthly run rate").nextElementSibling).toHaveTextContent(formatMoneyMinor(1234500));
    expect(screen.getByText("Configured annual run rate").nextElementSibling).toHaveTextContent(formatMoneyMinor(14814000));
    expect(screen.getByText("Gross revenue").nextElementSibling).toHaveTextContent("Not recorded");
    expect(screen.getByText("Recorded rollups").nextElementSibling).toHaveTextContent(/^0$/);
    expect(screen.getByText("Configured rates include eligible trial/manual subscriptions; paid receipts and recorded rollups are separate.")).toBeVisible();
    expect(screen.queryByText("Monthly recurring revenue")).not.toBeInTheDocument();
    expect(screen.queryByText("Annual recurring revenue")).not.toBeInTheDocument();
    expect(screen.getByText(/recorded rollups only/)).toBeVisible();
  });
  it("shows a load failure separately from an empty report", async () => {
    vi.mocked(platformApi.namedReport).mockRejectedValue(new Error("raw-sensitive-detail"));
    const user = userEvent.setup(); render(<PlatformReports />);
    await user.click(screen.getByRole("tab", { name: "Usage" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be verified");
    expect(screen.queryByText("No recorded results for this page.")).not.toBeInTheDocument();
    expect(screen.queryByText("raw-sensitive-detail")).not.toBeInTheDocument();
  });
});
