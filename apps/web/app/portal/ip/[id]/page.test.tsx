import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ record: vi.fn(), publications: vi.fn(), submit: vi.fn() }));
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "docket-1" }) }));
vi.mock("@/lib/api/portal", () => ({ fetchPortalIpRecord: mocks.record, fetchPortalPublications: mocks.publications, submitPortalInstruction: mocks.submit }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import PortalIpRecordPage from "@/app/portal/ip/[id]/page";

const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;
const SNAKE = /[a-z]+(?:_[a-z]+)+/;

// The rows the server publishes (services/portal_ip.py _safe_report_rows):
// docket_id is always present because the server scopes rows by it.
const PORTFOLIO_ROW = {
  docket_id: "0b9c4c1e-6f1d-4a3e-9d55-2f1f6c1e7a10",
  asset_title: "ASTER DEVICE",
  docket_title: "ASTER DEVICE",
  docket_status: "pending_examination",
  primary_identifier: "TM-421",
  application_numbers: ["TM-421"],
  opposition_numbers: ["OPP-88"],
  nice_classes: [9, 42],
  goods_services: ["Downloadable legal software"],
  office: "Trade Marks Registry Delhi",
  jurisdiction: "IN",
  filing_phase: "opposition_pending",
  open_deadline_count: 2,
  overdue_deadline_count: 0,
  registry_sync_state: "unavailable",
  registry_last_success_at: null,
  updated_at: "2026-10-31T10:15:00Z",
};
const RENEWAL_ROW = {
  docket_id: "7d3f2a91-1c2b-4e5f-8a9b-0c1d2e3f4a5b",
  docket_title: "ASTER DEVICE",
  primary_identifier: "TM-421",
  record_type: "trademark",
  reporting_state: "filing_in_progress",
  renewal_due_on: "2027-03-14",
  grace_due_on: "2027-09-14",
  calendar_phase: "due",
  action_required: "record_filing_initiation",
};

describe("PortalIpRecordPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.record.mockResolvedValue({ id: "docket-1", title: "ASTER DEVICE", record_type: "trademark", status: "filed", primary_identifier: "TM-421", identifiers: ["TM-421", "OPP-88"], events: [], upcoming_dates: [], grant_expires_at: null });
    mocks.publications.mockResolvedValue({ publications: [{ id: "pub-1", publication_kind: "report", title: "Opposition status", status: "published", access_state: "available", delivery_status: "delivered", report_kind: "opposition_status", summary: { published_record_count: 1, report_kind: "opposition_status" }, rows: [PORTFOLIO_ROW], document_filename: null, targets: [{ ip_docket_record_id: "docket-1", docket_title: "ASTER DEVICE", current: true }] }, { id: "pub-2", publication_kind: "report", title: "Renewal status", status: "published", access_state: "available", delivery_status: "delivered", report_kind: "renewal", summary: { published_record_count: 1, report_kind: "renewal" }, rows: [RENEWAL_ROW], document_filename: null, targets: [{ ip_docket_record_id: "docket-1", docket_title: "ASTER DEVICE", current: true }] }] });
    mocks.submit.mockResolvedValue({ id: "instruction-1", status: "pending" });
  });

  it("shows approved data and sends a structured instruction", async () => {
    const user = userEvent.setup();
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><PortalIpRecordPage /></QueryClientProvider>);
    const [rows, renewalRows] = await screen.findAllByTestId("portal-publication-rows");
    // B4-ADJ-02: rows read as labelled values from an allowlist: never raw
    // JSON, never the docket's internal id, never a stored code.
    expect(rows).toHaveTextContent("Opposition numbers");
    expect(rows).toHaveTextContent("OPP-88");
    expect(rows).toHaveTextContent("StatusPending examination");
    expect(rows).toHaveTextContent("Filing stageOpposition pending");
    expect(rows).toHaveTextContent("Classes9, 42");
    expect(rows).toHaveTextContent("Registry checkUnavailable");
    // The mark repeats the record title, so it is not shown twice; no id field.
    expect(rows).not.toHaveTextContent(/Docket id|MarkASTER/);
    expect(renewalRows).toHaveTextContent("Renewal statusFiling in progress");
    expect(renewalRows).toHaveTextContent("Renewal due14 Mar 2027");
    expect(renewalRows).toHaveTextContent("Next stepRecord filing initiation");
    for (const list of [rows, renewalRows]) {
      expect(list.textContent).not.toMatch(UUID);
      expect(list.textContent).not.toMatch(SNAKE);
      expect(list.textContent).not.toMatch(/[{}"]/);
    }
    const summaries = screen.getAllByTestId("portal-publication-summary");
    expect(summaries[0]).toHaveTextContent("ReportOpposition status");
    expect(summaries[0]).toHaveTextContent("Records shared1");
    expect(summaries[1]).toHaveTextContent("ReportRenewal");
    for (const summary of summaries) expect(summary.textContent).not.toMatch(SNAKE);
    expect(document.body.textContent).not.toMatch(UUID);
    await user.selectOptions(screen.getByLabelText("Approved publication"), "pub-1");
    await user.selectOptions(screen.getByLabelText("Instruction type"), "proceeding");
    await user.type(screen.getByLabelText("Instruction details"), "Proceed with the opposition response.");
    await user.click(screen.getByRole("button", { name: "Send for firm acknowledgement" }));
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledWith(expect.objectContaining({ publicationId: "pub-1", docketId: "docket-1", instructionKind: "proceeding", decision: "proceed" })));
  });

  it("disables the publication select with a reason when nothing can be answered", async () => {
    mocks.publications.mockResolvedValue({ publications: [] });
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><PortalIpRecordPage /></QueryClientProvider>);
    const select = await screen.findByLabelText("Approved publication");
    expect(select).toBeDisabled();
    expect(screen.getByText(/None is available yet/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Send for firm acknowledgement" })).toBeDisabled();
  });
});
