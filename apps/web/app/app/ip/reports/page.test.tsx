import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { contractMock, previewMock, capabilityMock, errorToastMock, successToastMock, grantsMock, publishMock } = vi.hoisted(() => ({
  contractMock: vi.fn(),
  previewMock: vi.fn(),
  capabilityMock: vi.fn(),
  errorToastMock: vi.fn(),
  successToastMock: vi.fn(),
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

vi.mock("sonner", () => ({ toast: { error: errorToastMock, success: successToastMock } }));

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
    grantsMock.mockResolvedValue({ grants: [{ id: "grant-1", portal_user_id: "portal-user-1", portal_user_name: "Asha Rao", portal_user_email: "asha@example.com", docket_title: "ASTER DEVICE", active: true, publishable: true, publication_blocked_reason: null }] });
    render(withClient(<IpReportsPage />));
    await screen.findByText("Generate", { selector: "button" });
    expect(screen.getByRole("button", { name: "Generate" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Generate" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Generate" }));
    await user.selectOptions(await screen.findByLabelText("Client"), "portal-user-1");
    await user.type(screen.getByLabelText("Client title"), "Opposition update");
    await user.click(screen.getByLabelText("ASTER DEVICE"));
    await user.click(screen.getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(publishMock).toHaveBeenCalledWith(expect.objectContaining({ portalUserId: "portal-user-1", grantIds: ["grant-1"], expectedSnapshotSha256: "a".repeat(64) })));
    await waitFor(() => expect(successToastMock).toHaveBeenCalledWith("Client report published."));
    expect(screen.getByLabelText("Client title")).toHaveValue("");
    expect(screen.getByLabelText("ASTER DEVICE")).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Publish" })).toBeDisabled();
    expect(errorToastMock).not.toHaveBeenCalled();
  });

  it("retains the reviewed snapshot and client inputs when publication is rejected", async () => {
    const user = userEvent.setup();
    previewMock.mockResolvedValue({ ...REPORT, confidentiality: "internal" });
    grantsMock.mockResolvedValue({ grants: [{ id: "grant-1", portal_user_id: "portal-user-1", portal_user_name: "Asha Rao", portal_user_email: "asha@example.com", docket_title: "ASTER DEVICE", active: true, publishable: true, publication_blocked_reason: null }] });
    publishMock.mockRejectedValue(new Error("The reviewed source changed; generate a new snapshot."));
    render(withClient(<IpReportsPage />));
    await screen.findByText("Generate", { selector: "button" });
    expect(screen.getByRole("button", { name: "Generate" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Generate" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Generate" }));
    await user.selectOptions(await screen.findByLabelText("Client"), "portal-user-1");
    await user.type(screen.getByLabelText("Client title"), "Opposition update");
    await user.click(screen.getByLabelText("ASTER DEVICE"));
    await user.click(screen.getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(errorToastMock).toHaveBeenCalledWith("The reviewed source changed; generate a new snapshot."));
    expect(screen.getByLabelText("Client title")).toHaveValue("Opposition update");
    expect(screen.getByLabelText("ASTER DEVICE")).toBeChecked();
    expect(screen.getByTestId("ip-report-result")).toHaveTextContent("OPP / 88 / 2026");
    expect(publishMock).toHaveBeenCalledTimes(1);
    expect(successToastMock).not.toHaveBeenCalled();
  });

  it("BUG-015 offers only clients whose grant can receive the report and explains a load failure", async () => {
    const user = userEvent.setup();
    previewMock.mockResolvedValue({ ...REPORT, confidentiality: "internal" });
    grantsMock.mockResolvedValue({ grants: [
      { id: "grant-open", portal_user_id: "portal-user-1", portal_user_name: "Asha Rao", portal_user_email: "asha@example.com", docket_title: "ASTER DEVICE", active: true, publishable: true, publication_blocked_reason: null },
      { id: "grant-closed", portal_user_id: "portal-user-2", portal_user_name: "Ravi Iyer", portal_user_email: "ravi@example.com", docket_title: "CLOSED MARK", active: true, publishable: false, publication_blocked_reason: "docket_closed" },
    ] });
    const { unmount } = render(withClient(<IpReportsPage />));
    await user.click(await screen.findByText("Generate", { selector: "button" }));
    const client = await screen.findByLabelText<HTMLSelectElement>("Client");
    expect(Array.from(client.options, (option) => option.value)).toEqual(["", "portal-user-1"]);
    unmount();

    grantsMock.mockRejectedValue(new Error("Grant list unavailable."));
    render(withClient(<IpReportsPage />));
    await user.click(await screen.findByText("Generate", { selector: "button" }));
    const failed = await screen.findByLabelText<HTMLSelectElement>("Client");
    await waitFor(() => expect(failed.options[0]).toHaveTextContent("Clients could not be loaded"));
    expect(failed).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("Grant list unavailable.");
    expect(screen.queryByText(/Reports publish only to clients/)).not.toBeInTheDocument();
    grantsMock.mockResolvedValue({ grants: [] });
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(failed.options[0]).toHaveTextContent("No client has portal access"));
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

  it("B4-ADJ-02 never shows internal id columns or stored codes from a server-shaped portfolio row", async () => {
    const user = userEvent.setup();
    // IpPortfolioRow.model_dump: the first four keys are internal ids.
    previewMock.mockResolvedValue({ ...REPORT, report_kind: "portfolio_register", rows: [{
      application_id: "1f0e3c5a-9b8d-4c7e-a6f5-4e3d2c1b0a99",
      docket_id: "0b9c4c1e-6f1d-4a3e-9d55-2f1f6c1e7a10",
      matter_id: "5a6b7c8d-9e0f-4a1b-8c2d-3e4f5a6b7c8d",
      asset_id: "9f8e7d6c-5b4a-4392-8170-6f5e4d3c2b1a",
      asset_kind: "word_mark",
      asset_title: "ASTER",
      asset_jurisdiction: "IN",
      docket_title: "ASTER DEVICE",
      docket_status: "pending_examination",
      primary_identifier: "TM-421",
      application_numbers: ["TM / 2026 / 00421"],
      opposition_numbers: [],
      nice_classes: [9],
      goods_services: ["Downloadable legal software"],
      responsible_membership_id: "c0ffee00-1234-4abc-9def-0123456789ab",
      team_id: "deadbeef-1234-4abc-9def-0123456789ab",
      filing_phase: "filing_in_progress",
    }] });
    render(withClient(<IpReportsPage />));
    await user.selectOptions(await screen.findByLabelText("Report"), "portfolio_register");
    await user.click(screen.getByRole("button", { name: "Generate" }));
    const result = await screen.findByTestId("ip-report-result");
    const headers = within(result).getAllByRole("columnheader").map((cell) => cell.textContent);
    expect(headers).toContain("Docket title");
    expect(headers.some((header) => /id/i.test(header ?? ""))).toBe(false);
    const table = within(result).getByRole("table");
    expect(table.textContent).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i);
    expect(within(table).getByText("Pending examination")).toBeInTheDocument();
    expect(within(table).getByText("Word mark")).toBeInTheDocument();
    expect(table.textContent).not.toMatch(/[a-z]+(?:_[a-z]+)+/);
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
    await screen.findByText("Generate", { selector: "button" });
    expect(screen.getByRole("button", { name: "Generate" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Generate" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Generate" }));
    await waitFor(() => expect(errorToastMock).toHaveBeenCalledWith("Report source timed out"));

    capabilityMock.mockReturnValue(false);
    view.rerender(withClient(<IpReportsPage />));
    expect(screen.getByText("IP access required")).toBeInTheDocument();
    expect(contractMock).toHaveBeenCalledTimes(1);
  });
});
