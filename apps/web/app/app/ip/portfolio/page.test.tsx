import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  createExportMock,
  fetchFamiliesMock,
  fetchPortfolioMock,
  listExportsMock,
  listViewsMock,
  previewExportMock,
  retryExportMock,
  useCapabilityMock,
} = vi.hoisted(() => ({
  createExportMock: vi.fn(),
  fetchFamiliesMock: vi.fn(),
  fetchPortfolioMock: vi.fn(),
  listExportsMock: vi.fn(),
  listViewsMock: vi.fn(),
  previewExportMock: vi.fn(),
  retryExportMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchIpPortfolio: fetchPortfolioMock,
  fetchIpPortfolioFamilies: fetchFamiliesMock,
  listIpPortfolioSavedViews: listViewsMock,
  listIpPortfolioExports: listExportsMock,
  createIpPortfolioExport: createExportMock,
  previewIpPortfolioExport: previewExportMock,
  retryIpPortfolioExport: retryExportMock,
  createIpPortfolioSavedView: vi.fn(),
  updateIpPortfolioSavedView: vi.fn(),
  deleteIpPortfolioSavedView: vi.fn(),
  downloadIpPortfolioExport: vi.fn(),
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => useCapabilityMock(capability),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import IpPortfolioPage from "@/app/app/ip/portfolio/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const RESPONSE = {
  rows: [
    {
      application_id: "application-1",
      docket_id: "docket-1",
      matter_id: "matter-1",
      asset_id: "asset-1",
      asset_kind: "trademark",
      asset_title: "Aster Device",
      asset_jurisdiction: "IN",
      docket_title: "Aster Device Mark",
      docket_status: "ready",
      primary_identifier: "TM / 2026 / 00421",
      application_numbers: ["TM / 2026 / 00421"],
      opposition_numbers: ["OPP / 88 / 2026"],
      nice_classes: [9],
      goods_services: ["Downloadable legal workflow software"],
      representation_kinds: ["device"],
      proprietors: ["Aster Products Private Limited"],
      agents: ["Rao Trademark Agents"],
      client_name: "Aster Products",
      responsible_lawyer: "Portfolio Partner",
      responsible_membership_id: "membership-1",
      team_name: "IP Team",
      team_id: "team-1",
      office: "Trade Marks Registry Mumbai",
      jurisdiction: "IN",
      filing_phase: "filed",
      is_active: true,
      lifecycle_version: 2,
      pending_identifier_allocation: false,
      record_complete: true,
      incomplete_reasons: [],
      open_deadline_count: 2,
      unconfirmed_deadline_count: 1,
      overdue_deadline_count: 0,
      registry_sync_state: "unavailable" as const,
      registry_last_success_at: null,
      provenance: ["CaseOps legal record", "Identifier: registry_fixture"],
      application_created_at: "2026-08-20T04:30:00Z",
      updated_at: "2026-08-21T04:30:00Z",
    },
  ],
  counts: {
    total: 1,
    complete_records: 1,
    incomplete_records: 0,
    unconfirmed_deadline_records: 1,
    overdue_records: 0,
    stale_sync_records: 0,
    sync_failure_records: null,
    registry_sync_state: "unavailable" as const,
  },
  filters: {},
  limit: 50,
  next_cursor: null,
};

const FAMILY_RESPONSE = {
  grouping: "mark" as const,
  families: [
    {
      grouping: "mark" as const,
      family_key: "asset-1",
      label: "Aster Device",
      member_count: 2,
      distinct_jurisdictions: ["GB", "IN"],
      distinct_filing_phases: ["filed", "pre_filing"],
      members: [
        {
          application_id: "application-1",
          docket_id: "docket-1",
          asset_id: "asset-1",
          office: "Trade Marks Registry Mumbai",
          jurisdiction: "IN",
          filing_phase: "filed",
          lifecycle_version: 2,
          primary_identifier: "TM / 2026 / 00421",
          open_deadline_count: 2,
          overdue_deadline_count: 0,
        },
        {
          application_id: "application-2",
          docket_id: "docket-2",
          asset_id: "asset-1",
          office: "UKIPO",
          jurisdiction: "GB",
          filing_phase: "pre_filing",
          lifecycle_version: 1,
          primary_identifier: "UK00004123456",
          open_deadline_count: 1,
          overdue_deadline_count: 1,
        },
      ],
    },
  ],
  ungrouped_member_count: 1,
  limit: 25,
  next_cursor: null,
};

describe("IpPortfolioPage", () => {
  beforeEach(() => {
    useCapabilityMock.mockReset();
    useCapabilityMock.mockReturnValue(true);
    fetchPortfolioMock.mockReset();
    fetchPortfolioMock.mockResolvedValue(RESPONSE);
    fetchFamiliesMock.mockReset();
    fetchFamiliesMock.mockResolvedValue(FAMILY_RESPONSE);
    listViewsMock.mockReset();
    listViewsMock.mockResolvedValue({ views: [] });
    listExportsMock.mockReset();
    listExportsMock.mockResolvedValue({ jobs: [] });
    createExportMock.mockReset();
    createExportMock.mockResolvedValue({ id: "export-1", status: "pending" });
    previewExportMock.mockReset();
    previewExportMock.mockResolvedValue({
      format: "csv",
      columns: ["mark", "application_numbers"],
      row_limit: 50000,
      row_count: 1,
      truncated: false,
      omitted_restricted_count: null,
      preview_token: "export-preview-token",
    });
    retryExportMock.mockReset();
  });

  it("renders exact registry identifiers, aggregate counts and unavailable sync state", async () => {
    render(withClient(<IpPortfolioPage />));

    expect(screen.getByRole("heading", { name: "Trademark portfolio" })).toBeInTheDocument();
    await waitFor(() => expect(fetchPortfolioMock).toHaveBeenCalledTimes(1));
    expect((await screen.findAllByText("Aster Device")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("TM / 2026 / 00421").length).toBeGreaterThan(0);
    expect(screen.getAllByText("OPP / 88 / 2026").length).toBeGreaterThan(0);
    expect(screen.getByText("Registry sync unavailable")).toBeInTheDocument();
    expect(screen.getByText("Unconfirmed deadlines")).toBeInTheDocument();
  });

  it("submits exact-number search and queues a bounded background export", async () => {
    render(withClient(<IpPortfolioPage />));
    await waitFor(() => expect(fetchPortfolioMock).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("Search marks and registry numbers"), {
      target: { value: "OPP / 88 / 2026" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search portfolio" }));
    await waitFor(() =>
      expect(fetchPortfolioMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ query: "OPP / 88 / 2026" }),
        expect.objectContaining({ limit: 50 }),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    expect(await screen.findByRole("heading", { name: "Confirm portfolio export" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Queue export" }));
    await waitFor(() =>
      expect(createExportMock).toHaveBeenCalledWith(
        expect.objectContaining({ rowLimit: 50000, previewToken: "export-preview-token" }),
      ),
    );
  });

  it("renders paginated application families and switches grouping axes", async () => {
    render(withClient(<IpPortfolioPage />));
    fireEvent.click(screen.getByRole("button", { name: "Family view" }));

    await waitFor(() =>
      expect(fetchFamiliesMock).toHaveBeenCalledWith(
        expect.any(Object),
        expect.objectContaining({ grouping: "mark", limit: 25, cursor: null }),
      ),
    );
    expect(await screen.findByRole("heading", { name: "Aster Device" })).toBeVisible();
    expect(screen.getByText("UK00004123456")).toBeVisible();
    expect(screen.getByText("1 ungrouped applications")).toBeVisible();
    expect(screen.getByRole("link", { name: /UK00004123456/ })).toHaveAttribute(
      "href",
      "/app/ip?docket=docket-2",
    );

    fireEvent.click(screen.getByRole("button", { name: "Client families" }));
    await waitFor(() =>
      expect(fetchFamiliesMock).toHaveBeenLastCalledWith(
        expect.any(Object),
        expect.objectContaining({ grouping: "client" }),
      ),
    );
  });

  it("fails closed when the member lacks ip read capability", () => {
    useCapabilityMock.mockReturnValue(false);
    render(withClient(<IpPortfolioPage />));
    expect(screen.getByText("IP portfolio access required")).toBeInTheDocument();
    expect(fetchPortfolioMock).not.toHaveBeenCalled();
  });
});
