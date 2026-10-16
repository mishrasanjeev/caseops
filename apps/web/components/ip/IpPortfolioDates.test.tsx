import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import type { IpRenewalTrackerRow } from "@/lib/api/endpoints";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { updateDates, fetchTracker, capability, success } = vi.hoisted(() => ({
  updateDates: vi.fn(), fetchTracker: vi.fn(), capability: vi.fn(), success: vi.fn(),
}));
vi.mock("@/lib/api/endpoints", () => ({ updateIpPortfolioDates: updateDates, fetchIpRenewalTracker: fetchTracker }));
vi.mock("@/lib/capabilities", () => ({ useCapability: capability }));
vi.mock("sonner", () => ({ toast: { success } }));
import { IpPortfolioRenewalTracker, PortfolioDateEditButton, PortfolioDateEditor, PortfolioDateValue,
  type EditablePortfolioDates } from "./IpPortfolioDates";

const row: EditablePortfolioDates = {
  docket_id: "docket-1", docket_title: "Aster Trademark", current_version: 7,
  source_application_on: "2026-01-31", source_renewal_due_on: "2028-03-31",
  source_application_state: "imported_unverified", source_renewal_state: "manual",
};
const trackerRow: IpRenewalTrackerRow = { ...row, docket_operational: true,
  application_numbers: ["TM-42"], nice_classes: [9], reminder_start_on: "2028-02-29",
  next_reminder_at: "2028-02-29T03:30:00Z", timezone: "Asia/Kolkata", cadence_days: 1,
  delivery_time: "09:00", days_remaining: 31, status: "scheduled", last_attempt_at: null,
  delivered_at: null, last_error: null };
function wrap(child: ReactNode) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>{child}</QueryClientProvider>;
}
describe("IP15 portfolio date editor and tracker", () => {
  beforeEach(() => { vi.clearAllMocks(); capability.mockReturnValue(true); });

  it("sends only the changed date and current version, and waits for confirmed save", async () => {
    let resolve: (value: unknown) => void = () => {};
    updateDates.mockImplementation(() => new Promise((done) => { resolve = done; }));
    const close = vi.fn();
    render(wrap(<PortfolioDateEditor row={row} onClose={close} />));
    fireEvent.change(screen.getByLabelText("Application Date"), { target: { value: "2026-02-01" } });
    fireEvent.change(screen.getByLabelText("Reason for change"), { target: { value: "Corrected from original filing receipt" } });
    fireEvent.click(screen.getByRole("button", { name: "Save dates" }));
    await waitFor(() => expect(updateDates).toHaveBeenCalledWith("docket-1", {
      expected_current_version: 7, application_date: "2026-02-01", reason: "Corrected from original filing receipt",
    }));
    expect(close).not.toHaveBeenCalled();
    expect(success).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Saving" })).toBeDisabled();
    await act(async () => resolve({ ...row, current_version: 8 }));
    await waitFor(() => expect(close).toHaveBeenCalledOnce());
    expect(success).toHaveBeenCalledWith("Portfolio dates saved.");
  });

  it("clears renewal explicitly without sending an unrelated application date", async () => {
    updateDates.mockResolvedValue({ ...row, source_renewal_due_on: null });
    render(wrap(<PortfolioDateEditor row={row} onClose={vi.fn()} />));
    fireEvent.change(screen.getByLabelText("Renewal Due Date"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Reason for change"), { target: { value: "Remove unsupported renewal source" } });
    fireEvent.click(screen.getByRole("button", { name: "Save dates" }));
    await waitFor(() => expect(updateDates).toHaveBeenCalledWith("docket-1", {
      expected_current_version: 7, renewal_due_date: null, reason: "Remove unsupported renewal source",
    }));
  });

  it("retains edited values and displays an actual rejected write without success", async () => {
    updateDates.mockRejectedValue(new Error("The trademark changed. Refresh before saving."));
    const close = vi.fn();
    render(wrap(<PortfolioDateEditor row={row} onClose={close} />));
    fireEvent.change(screen.getByLabelText("Renewal Due Date"), { target: { value: "2028-04-30" } });
    fireEvent.change(screen.getByLabelText("Reason for change"), { target: { value: "Review corrected registration evidence" } });
    fireEvent.click(screen.getByRole("button", { name: "Save dates" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The trademark changed. Refresh before saving.");
    expect(screen.getByLabelText("Renewal Due Date")).toHaveValue("2028-04-30");
    expect(close).not.toHaveBeenCalled();
    expect(success).not.toHaveBeenCalled();
    expect(updateDates).toHaveBeenCalledOnce();
  });

  it("does not offer write controls without ip:write", () => {
    capability.mockReturnValue(false);
    render(<PortfolioDateEditButton row={row} onEdit={vi.fn()} />);
    expect(capability).toHaveBeenCalledWith("ip:write");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders normalized calendar dates without a timezone shift and states provenance", () => {
    render(<PortfolioDateValue value="2028-03-31" state="manual" />);
    expect(screen.getByText("31 Mar 2028")).toHaveAttribute("datetime", "2028-03-31");
    expect(screen.getByText("Manual, unverified")).toBeInTheDocument();
    expect(screen.queryByText("Verified", { exact: true })).not.toBeInTheDocument();
  });

  it.each(["2028-02-31", "not-a-date"])("does not normalize a malformed source date into another calendar date (%s)", value => {
    render(<PortfolioDateValue value={value} state="manual" />);
    expect(screen.getByText("Invalid date")).toBeInTheDocument();
    expect(screen.queryByText("Manual, unverified")).not.toBeInTheDocument();
  });

  it("keeps a tracker load failure distinct from an empty authorized scope", async () => {
    fetchTracker.mockRejectedValueOnce(new Error("Tracker unavailable"));
    fetchTracker.mockResolvedValue({ rows: [], counts: { upcoming: 0, active: 0, due_today: 0, overdue: 0, missing: 0, failed: 0 }, limit: 50, next_cursor: null });
    render(wrap(<IpPortfolioRenewalTracker onQueryChange={vi.fn()} onCategoryChange={vi.fn()} onEdit={vi.fn()} />));
    expect(await screen.findByText("Could not load the deadline tracker")).toBeInTheDocument();
    expect(screen.queryByText("No matching renewal records")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("No matching renewal records")).toBeInTheDocument();
    expect(fetchTracker).toHaveBeenCalledTimes(2);
  });

  it("uses the real returned reminder timestamps without treating scheduled as delivered", async () => {
    fetchTracker.mockResolvedValue({ rows: [trackerRow], counts: { upcoming: 1, active: 0, due_today: 0, overdue: 0, missing: 0, failed: 0 },
      limit: 50, next_cursor: null });
    render(wrap(<IpPortfolioRenewalTracker onQueryChange={vi.fn()} onCategoryChange={vi.fn()} onEdit={vi.fn()} />));
    expect(await screen.findByText("Scheduled")).toBeInTheDocument();
    expect(screen.getByText("29 Feb 2028")).toBeInTheDocument();
    expect(screen.getByText("31 days remaining")).toBeInTheDocument();
    expect(screen.queryByText(/^Delivered:/)).not.toBeInTheDocument();
  });

  it("does not invite a date mutation on a closed docket merely because its date is missing", async () => {
    fetchTracker.mockResolvedValue({ rows: [{ ...trackerRow, docket_operational: false,
      source_renewal_due_on: null, source_renewal_state: "missing", next_reminder_at: null,
      reminder_start_on: null, days_remaining: null, status: "missing_date" }],
      counts: { upcoming: 0, active: 0, due_today: 0, overdue: 0, missing: 1, failed: 0 }, limit: 50, next_cursor: null });
    const edit = vi.fn();
    render(wrap(<IpPortfolioRenewalTracker onQueryChange={vi.fn()} onCategoryChange={vi.fn()} onEdit={edit} />));
    const button = await screen.findByRole("button", { name: "Edit dates for Aster Trademark" });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(edit).not.toHaveBeenCalled();
  });
});
