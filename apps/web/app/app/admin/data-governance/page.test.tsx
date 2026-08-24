import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  fetchMock,
  historyMock,
  detailMock,
  holdSummaryMock,
  catalogMock,
  createMock,
  capabilityMock,
} = vi.hoisted(() => ({
  fetchMock: vi.fn(),
  historyMock: vi.fn(),
  detailMock: vi.fn(),
  holdSummaryMock: vi.fn(),
  catalogMock: vi.fn(),
  createMock: vi.fn(),
  capabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchTenantDataGovernanceIntegrity: fetchMock,
  listTenantDataOperationDryRuns: historyMock,
  fetchTenantDataOperationDryRun: detailMock,
  fetchTenantLegalHoldSummary: holdSummaryMock,
  fetchTenantDataClassCatalog: catalogMock,
  createTenantScopedDataOperationDryRun: createMock,
}));
vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => capabilityMock(capability),
}));

import DataGovernancePage from "@/app/app/admin/data-governance/page";

function withClient(children: ReactNode) {
  return (
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      {children}
    </QueryClientProvider>
  );
}

const manifest = {
  id: "dry-run-1",
  operation_type: "tenant_export",
  execution_mode: "dry_run",
  status: "dry_run_complete",
  approval_status: "not_requested",
  rejection_reason: null,
  approved_operation_id: null,
  request_scope_hash: "scope-hash",
  manifest_hash: "manifest-hash",
  request_evidence_ref: "caseops://automatic",
  completed_at: "2026-08-24T00:00:00Z",
  as_of: "2026-08-24T00:00:00Z",
  items: [],
  exclusions: [],
  offboarding_plan: [],
  dependency_plan: null,
};

describe("DataGovernancePage", () => {
  beforeEach(() => {
    capabilityMock.mockReset();
    capabilityMock.mockReturnValue(true);
    fetchMock.mockReset();
    fetchMock.mockResolvedValue({
      checks: [
        {
          check_id: "expired_unpurged",
          status: "unavailable",
          summary: "No active schedule.",
          findings: [],
          blocked_by: "DATA-GOV-02",
        },
      ],
      ok_count: 0,
      finding_count: 0,
      unavailable_count: 1,
      is_complete: false,
    });
    historyMock.mockReset();
    historyMock.mockResolvedValue({ operations: [manifest] });
    detailMock.mockReset();
    detailMock.mockResolvedValue(manifest);
    holdSummaryMock.mockReset();
    holdSummaryMock.mockResolvedValue({
      draft_count: 1,
      active_count: 2,
      released_count: 3,
      cancelled_count: 4,
      active_company_wide_count: 1,
      active_scoped_count: 1,
      active_item_count: 7,
      preservation_effective: true,
    });
    catalogMock.mockReset();
    catalogMock.mockResolvedValue({
      data_classes: [
        { id: "legal_holds", label: "Legal Holds", confidentiality: "privileged" },
        {
          id: "tenant_data_operations",
          label: "Tenant Data Operations",
          confidentiality: "privileged",
        },
      ],
    });
    createMock.mockReset();
    createMock.mockResolvedValue({ ...manifest, id: "dry-run-created" });
  });

  it("shows unavailable controls as unavailable, not healthy", async () => {
    render(withClient(<DataGovernancePage />));
    expect(await screen.findByTestId("governance-check-expired_unpurged")).toHaveTextContent(
      "unavailable",
    );
    expect(screen.getByText("Blocked by: DATA-GOV-02")).toBeInTheDocument();
  });

  it("does not fetch without tenant oversight capability", () => {
    capabilityMock.mockReturnValue(false);
    render(withClient(<DataGovernancePage />));
    expect(screen.getByText(/Data-governance access required/i)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(historyMock).not.toHaveBeenCalled();
    expect(catalogMock).not.toHaveBeenCalled();
  });

  it("creates a server-scoped dry run from the reviewed catalog", async () => {
    render(withClient(<DataGovernancePage />));
    const dataClass = await screen.findByLabelText("Registered data class");
    fireEvent.change(dataClass, { target: { value: "tenant_data_operations" } });
    fireEvent.change(screen.getByLabelText(/Evidence reference/i), {
      target: { value: "ticket://ram-2026-08-24" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Create non-executable dry run/i }));

    await waitFor(() =>
      expect(createMock).toHaveBeenCalledWith({
        operationType: "tenant_export",
        dataClassIds: ["tenant_data_operations"],
        requestEvidenceRef: "ticket://ram-2026-08-24",
      }),
    );
    expect(screen.queryByLabelText(/Target type/i)).toBeNull();
    expect(screen.queryByLabelText(/SHA-256 target reference/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /Submit for approval/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Approve/i })).toBeNull();
  });

  it("opens manifest detail without exposing an approval or execution control", async () => {
    render(withClient(<DataGovernancePage />));
    fireEvent.click(await screen.findByTestId("dry-run-dry-run-1"));
    expect(await screen.findByText("manifest-hash")).toBeInTheDocument();
    expect(screen.getByText(/cannot execute an operation/i)).toBeInTheDocument();
    expect(detailMock).toHaveBeenCalledWith("dry-run-1");
    expect(screen.queryByTestId("data-operation-review")).toBeNull();
  });

  it("shows aggregate legal-hold preservation without hold content", async () => {
    render(withClient(<DataGovernancePage />));
    const summary = await screen.findByTestId("legal-hold-summary");
    expect(summary).toHaveTextContent("preservation effective");
    expect(summary).toHaveTextContent("Active holds");
    expect(summary).toHaveTextContent("7");
    expect(
      screen.getByText(/Hold records, scopes, authorities, and held-item references are never shown here/i),
    ).toBeInTheDocument();
  });
});
