import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { contractMock, previewMock, capabilityMock, errorToastMock, grantsMock, publishMock } = vi.hoisted(() => ({
  contractMock: vi.fn(),
  previewMock: vi.fn(),
  capabilityMock: vi.fn(),
  errorToastMock: vi.fn(),
  grantsMock: vi.fn(),
  publishMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchIpReportFoundation: contractMock,
  previewIpReport: previewMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => capabilityMock(capability),
}));

vi.mock("@/lib/api/portal", () => ({
  fetchAdminPortalIpGrants: grantsMock,
  publishIpReportToPortal: publishMock,
}));

vi.mock("sonner", () => ({ toast: { error: errorToastMock } }));

import IpReportsPage from "@/app/app/ip/reports/page";

const DEFINITIONS = [
  "portfolio_register",
  "application_status",
  "opposition_status",
  "deadline_control",
  "renewal",
  "watch",
  "workload",
  "data_quality",
  "integration_freshness",
].map((key) => ({
  key,
  schema_version: `ip-${key}-v1`,
  canonical_sources: ["canonical_source"],
  synchronous_preview: true,
  background_execution: false,
  scheduled_delivery: false,
}));

const CONTRACT = {
  contract_version: "iplf-038b-v1",
  persistence: "none",
  execution_mode: "synchronous",
  artifact_storage: "none",
  delivery: "not_available",
  audience: "internal",
  hidden_restricted_count_policy: "omit_without_count",
  definitions: DEFINITIONS,
};

const REPORT = {
  report_kind: "opposition_status",
  schema_version: "ip-opposition-status-v1",
  generated_at: "2026-08-23T08:30:00Z",
  timezone: "UTC",
  audience: "internal",
  confidentiality: "restricted",
  filters: { row_limit: 25, portfolio: { opposition_only: true } },
  freshness: {
    status: "mixed",
    generated_at: "2026-08-23T08:30:00Z",
    source_cutoffs: { registry_sync: null },
    unavailable_sources: ["registry_sync"],
  },
  hidden_restricted_count_policy: "omit_without_count",
  row_count: 1,
  truncated: false,
  summary: { total: 1, returned_opposition_numbered: 1 },
  rows: [
    {
      docket_title: "ASTER DEVICE",
      application_numbers: ["TM / 2026 / 00421"],
      opposition_numbers: ["OPP / 88 / 2026"],
      filing_phase: "filed",
    },
  ],
  snapshot_sha256: "a".repeat(64),
};

function withClient(children: ReactNode) {
  return (
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>
      {children}
    </QueryClientProvider>
  );
}

describe("IpReportsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    capabilityMock.mockReturnValue(true);
    contractMock.mockResolvedValue(CONTRACT);
    previewMock.mockResolvedValue(REPORT);
    grantsMock.mockResolvedValue({ grants: [] });
    publishMock.mockResolvedValue({ id: "publication-1" });
  });

  it("publishes only an internal reviewed snapshot to selected active grants", async () => {
    const user = userEvent.setup();
    previewMock.mockResolvedValue({ ...REPORT, confidentiality: "internal" });
    grantsMock.mockResolvedValue({ grants: [{ id: "grant-1", portal_user_id: "portal-user-1", portal_user_name: "Asha Rao", portal_user_email: "asha@example.com", docket_title: "ASTER DEVICE", active: true }] });
    render(withClient(<IpReportsPage />));
    await user.click(await screen.findByRole("button", { name: "Generate" }));
    await user.selectOptions(await screen.findByLabelText("Client"), "portal-user-1");
    await user.type(screen.getByLabelText("Client title"), "Opposition update");
    await user.click(screen.getByLabelText("ASTER DEVICE"));
    await user.click(screen.getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(publishMock).toHaveBeenCalledWith(expect.objectContaining({ portalUserId: "portal-user-1", grantIds: ["grant-1"], expectedSnapshotSha256: "a".repeat(64) })));
  });

  it("generates a filtered, classified report with identifier and freshness evidence", async () => {
    const user = userEvent.setup();
    render(withClient(<IpReportsPage />));

    await user.selectOptions(await screen.findByLabelText("Report"), "opposition_status");
    await user.type(screen.getByLabelText("Keyword"), "Aster");
    await user.type(screen.getByLabelText("Jurisdiction"), "IN");
    await user.selectOptions(screen.getByLabelText("Confidentiality"), "restricted");
    await user.clear(screen.getByLabelText("Row limit"));
    await user.type(screen.getByLabelText("Row limit"), "25");
    await user.click(screen.getByRole("button", { name: "Generate" }));

    await waitFor(() => expect(previewMock).toHaveBeenCalledWith({
      reportKind: "opposition_status",
      rowLimit: 25,
      confidentiality: "restricted",
      filters: { query: "Aster", jurisdiction: ["IN"] },
      renewalStates: [],
    }));
    const result = await screen.findByTestId("ip-report-result");
    expect(within(result).getByText("OPP / 88 / 2026")).toBeInTheDocument();
    expect(within(result).getByText(/Unavailable sources: Registry sync/)).toBeInTheDocument();
    expect(within(result).getByText(/Restricted records outside your access are omitted/)).toBeInTheDocument();
    expect(within(result).getByText("aaaaaaaaaaaa")).toBeInTheDocument();
  });

  it("uses only relevant renewal filters", async () => {
    const user = userEvent.setup();
    previewMock.mockResolvedValue({ ...REPORT, report_kind: "renewal", rows: [] });
    render(withClient(<IpReportsPage />));

    await user.selectOptions(await screen.findByLabelText("Report"), "renewal");
    expect(screen.queryByLabelText("Keyword")).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Renewal state"), "grace");
    await user.click(screen.getByRole("button", { name: "Generate" }));

    await waitFor(() => expect(previewMock).toHaveBeenCalledWith(expect.objectContaining({
      reportKind: "renewal",
      filters: {},
      renewalStates: ["grace"],
    })));
  });

  it("surfaces generation failures and denies users without IP read access", async () => {
    const user = userEvent.setup();
    previewMock.mockRejectedValue(new Error("Report source timed out"));
    const view = render(withClient(<IpReportsPage />));
    await user.click(await screen.findByRole("button", { name: "Generate" }));
    await waitFor(() => expect(errorToastMock).toHaveBeenCalledWith("Report source timed out"));

    capabilityMock.mockReturnValue(false);
    view.rerender(withClient(<IpReportsPage />));
    expect(screen.getByText("IP access required")).toBeInTheDocument();
    expect(contractMock).toHaveBeenCalledTimes(1);
  });
});
