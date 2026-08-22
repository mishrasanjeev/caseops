import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  commitMock,
  downloadErrorsMock,
  getImportMock,
  historyMock,
  reconcileMock,
  revalidateMock,
  uploadMock,
  useCapabilityMock,
} = vi.hoisted(() => ({
  commitMock: vi.fn(),
  downloadErrorsMock: vi.fn(),
  getImportMock: vi.fn(),
  historyMock: vi.fn(),
  reconcileMock: vi.fn(),
  revalidateMock: vi.fn(),
  uploadMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  commitIpPortfolioImport: commitMock,
  downloadIpPortfolioImportErrors: downloadErrorsMock,
  getIpPortfolioImport: getImportMock,
  listIpPortfolioImports: historyMock,
  reconcileIpPortfolioImport: reconcileMock,
  revalidateIpPortfolioImport: revalidateMock,
  uploadIpPortfolioImport: uploadMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => useCapabilityMock(capability),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import IpPortfolioImportsPage from "@/app/app/ip/portfolio/imports/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function preview(overrides: Record<string, unknown> = {}) {
  return {
    job: {
      id: "import-1",
      domain: "ip_portfolio",
      filename: "trademarks.csv",
      source_sha256: "a".repeat(64),
      status: "preview_ready",
      total_rows: 1,
      valid_rows: 1,
      invalid_rows: 0,
      committed_rows: 0,
      failed_rows: 0,
      preview_token: "preview-token-1",
      preview_expires_at: "2026-08-21T12:00:00Z",
      committed_at: null,
      creator_label_snapshot: "Portfolio Partner",
      version: 1,
      created_at: "2026-08-21T10:00:00Z",
    },
    rows: [{
      id: "row-1",
      row_number: 1,
      validation_status: "valid",
      errors: [],
      commit_status: "pending",
      commit_error_code: null,
      created_docket_id: null,
      normalized: {
        title: "ASTER DEVICE",
        mark_text: "ASTER",
        class_number: 9,
        applicant_name: "Aster Products Private Limited",
        application_number: "TM / 2026 / 00421",
      },
      duplicate_candidates: [],
      reconciliation_decision: null,
      reconciled_target_docket_id: null,
    }],
    preview_expired: false,
    ...overrides,
  };
}

describe("IpPortfolioImportsPage", () => {
  beforeEach(() => {
    useCapabilityMock.mockReset();
    useCapabilityMock.mockReturnValue(true);
    historyMock.mockReset();
    historyMock.mockResolvedValue({ jobs: [] });
    uploadMock.mockReset();
    commitMock.mockReset();
    reconcileMock.mockReset();
    revalidateMock.mockReset();
    getImportMock.mockReset();
    downloadErrorsMock.mockReset();
  });

  it("uploads and commits a validated CSV with a preview token and idempotency key", async () => {
    const result = preview();
    uploadMock.mockResolvedValue(result);
    commitMock.mockResolvedValue({
      ...result,
      job: { ...result.job, status: "committed", committed_rows: 1, committed_at: "2026-08-21T10:05:00Z" },
      rows: [{ ...result.rows[0], commit_status: "created", created_docket_id: "docket-1" }],
      replayed: false,
    });
    render(withClient(<IpPortfolioImportsPage />));

    const file = new File([
      "Title,Mark Text,Nice Class,Applicant\nASTER DEVICE,ASTER,9,Aster Products Private Limited",
    ], "trademarks.csv", { type: "text/csv" });
    fireEvent.change(screen.getByLabelText("CSV or XLSX file"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "Validate file" }));

    expect(await screen.findByRole("heading", { name: "Review trademarks.csv" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Commit to portfolio" }));
    await waitFor(() => expect(commitMock).toHaveBeenCalledWith(expect.objectContaining({
      jobId: "import-1",
      previewToken: "preview-token-1",
      idempotencyKey: expect.any(String),
    })));
    expect(await screen.findByText("1 rows committed; 0 failed.")).toBeInTheDocument();
  });

  it("requires an explicit accessible-docket decision and uses the rotated token", async () => {
    const duplicate = preview({
      rows: [{
        ...preview().rows[0],
        duplicate_candidates: [{ docket_id: "docket-existing", title: "ASTER", match_reasons: ["exact_application_number"] }],
      }],
    });
    const reconciled = {
      ...duplicate,
      job: { ...duplicate.job, version: 2, preview_token: "preview-token-2" },
      rows: [{ ...duplicate.rows[0], reconciliation_decision: "link_existing", reconciled_target_docket_id: "docket-existing" }],
    };
    uploadMock.mockResolvedValue(duplicate);
    reconcileMock.mockResolvedValue(reconciled);
    commitMock.mockResolvedValue({ ...reconciled, job: { ...reconciled.job, status: "committed", committed_rows: 1 }, replayed: false });
    render(withClient(<IpPortfolioImportsPage />));
    const user = userEvent.setup();

    const file = new File(["Title,Mark Text,Nice Class,Applicant\nASTER,ASTER,9,Aster"], "duplicates.csv", { type: "text/csv" });
    await user.upload(screen.getByLabelText("CSV or XLSX file"), file);
    await user.click(screen.getByRole("button", { name: "Validate file" }));
    expect(await screen.findByText("1 duplicate rows still need a decision.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Commit to portfolio" })).toBeDisabled();

    await user.click(screen.getByLabelText("Decision for row 1"));
    await user.click(screen.getByRole("option", { name: "Link existing docket" }));
    await user.click(screen.getByLabelText("Existing docket for row 1"));
    await user.click(screen.getByRole("option", { name: "ASTER" }));
    await user.click(screen.getByRole("button", { name: "Save duplicate decisions" }));

    await waitFor(() => expect(reconcileMock).toHaveBeenCalledWith({
      jobId: "import-1",
      expectedJobVersion: 1,
      decisions: [{ rowId: "row-1", decision: "link_existing", targetDocketId: "docket-existing" }],
    }));
    await user.click(screen.getByRole("button", { name: "Commit to portfolio" }));
    await waitFor(() => expect(commitMock).toHaveBeenCalledWith(expect.objectContaining({ previewToken: "preview-token-2" })));
  });

  it("revalidates an expired history preview and fails closed without read access", async () => {
    const expired = preview({ preview_expired: true });
    const refreshed = preview();
    historyMock.mockResolvedValue({ jobs: [expired.job] });
    getImportMock.mockResolvedValue(expired);
    revalidateMock.mockResolvedValue(refreshed);
    const { unmount } = render(withClient(<IpPortfolioImportsPage />));
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /trademarks.csv/i }));
    expect(await screen.findByText(/This preview expired/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Commit to portfolio" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Refresh preview" }));
    await waitFor(() => expect(revalidateMock).toHaveBeenCalledWith("import-1", expect.anything()));
    expect(screen.getByRole("button", { name: "Commit to portfolio" })).toBeEnabled();

    const historyCalls = historyMock.mock.calls.length;
    unmount();
    useCapabilityMock.mockReturnValue(false);
    render(withClient(<IpPortfolioImportsPage />));
    expect(screen.getByText("IP portfolio access required")).toBeInTheDocument();
    expect(historyMock).toHaveBeenCalledTimes(historyCalls);
  });
});
