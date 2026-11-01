import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { toast } from "sonner";
import type { IpImportPreview } from "@/lib/api/endpoints";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  commitMock,
  downloadErrorsMock,
  getImportMock,
  historyMock,
  reconcileMock,
  revalidateMock,
  resumeMock,
  uploadMock,
  useCapabilityMock,
  fetchDocketMock,
  updateDateMock,
} = vi.hoisted(() => ({
  commitMock: vi.fn(),
  downloadErrorsMock: vi.fn(),
  getImportMock: vi.fn(),
  historyMock: vi.fn(),
  reconcileMock: vi.fn(),
  revalidateMock: vi.fn(),
  resumeMock: vi.fn(),
  uploadMock: vi.fn(),
  useCapabilityMock: vi.fn(),
  fetchDocketMock: vi.fn(),
  updateDateMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  commitIpPortfolioImport: commitMock,
  downloadIpPortfolioImportErrors: downloadErrorsMock,
  getIpPortfolioImport: getImportMock,
  listIpPortfolioImports: historyMock,
  reconcileIpPortfolioImport: reconcileMock,
  revalidateIpPortfolioImport: revalidateMock,
  resumeIpPortfolioImport: resumeMock,
  uploadIpPortfolioImport: uploadMock,
  fetchIpDocket: fetchDocketMock,
  updateIpPortfolioRenewalDate: updateDateMock,
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

function preview(overrides: Record<string, unknown> = {}): IpImportPreview {
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
    vi.mocked(toast.success).mockClear();
    useCapabilityMock.mockReset();
    useCapabilityMock.mockReturnValue(true);
    historyMock.mockReset();
    historyMock.mockResolvedValue({ jobs: [] });
    uploadMock.mockReset();
    commitMock.mockReset();
    reconcileMock.mockReset();
    revalidateMock.mockReset();
    resumeMock.mockReset();
    getImportMock.mockReset();
    downloadErrorsMock.mockReset();
    fetchDocketMock.mockReset();
    updateDateMock.mockReset();
  });

  it("uploads and commits a validated CSV with a preview token and idempotency key", async () => {
    const result = preview();
    uploadMock.mockResolvedValue(result);
    commitMock.mockResolvedValue({
      ...result,
      job: { ...result.job, status: "committed", committed_rows: 1, committed_at: "2026-08-21T10:05:00Z" },
      rows: [{ ...result.rows[0], commit_status: "committed", created_docket_id: "docket-1" }],
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
    expect(await screen.findByText("1 created; 0 linked; 0 skipped (0 duplicates); 0 with notes; 0 failed.")).toBeInTheDocument();
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
    expect(await screen.findByText("Eligible rows will be committed; duplicate and unusable rows will be skipped.")).toBeInTheDocument();
    expect(toast.success).toHaveBeenCalledWith("1 valid source rows; 0 blocked rows. Duplicates and blocked rows are skipped by default.");
    expect(screen.getByRole("button", { name: "Commit to portfolio" })).toBeEnabled();

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

  it.each(["2029-04-30", null])("corrects the current canonical source date to %s without rewriting history", async (newDue) => {
    const source = preview();
    const committed = { ...source, job: { ...source.job, status: "committed", committed_rows: 1 },
      rows: [{ ...source.rows[0], created_docket_id: "docket-1", commit_status: "committed",
        normalized: { ...source.rows[0].normalized, renewal_due_date: "2029-03-31" } }] };
    historyMock.mockResolvedValue({ jobs: [committed.job] });
    getImportMock.mockResolvedValue(committed);
    fetchDocketMock.mockResolvedValue({ id: "docket-1", title: "ASTER", current_version: 7,
      current_particulars: { representation_json: { portfolio_import: { renewal_due_date: "2029-03-31" } } } });
    updateDateMock.mockResolvedValue({ current_version: 8 });
    render(withClient(<IpPortfolioImportsPage />));
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /trademarks.csv/i }));
    await user.click(await screen.findByRole("button", { name: "Edit source renewal date" }));
    expect(await screen.findByRole("dialog", { name: "Correct source renewal date" })).toBeVisible();
    expect(screen.getByLabelText("Renewal due date")).toHaveValue("2029-03-31");
    if (newDue) fireEvent.change(screen.getByLabelText("Renewal due date"), { target: { value: newDue } });
    else await user.click(screen.getByRole("button", { name: "Clear date" }));
    expect(screen.getByRole("button", { name: "Save source date" })).toBeDisabled();
    await user.type(screen.getByLabelText("Correction reason"), "Source date corrected");
    await user.click(screen.getByRole("button", { name: "Save source date" }));
    await waitFor(() => expect(updateDateMock).toHaveBeenCalledWith({ docketId: "docket-1",
      expectedCurrentVersion: 7, renewalDueDate: newDue, reason: "Source date corrected" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByText("2029-03-31", { exact: true })).toBeInTheDocument();
  });

  it("recovers a retained creator claim without browser storage or exposing its key", async () => {
    sessionStorage.clear();
    const retained = preview();
    retained.job.status = "staged";
    retained.job.preview_token = null;
    retained.job.recovery_available = true;
    historyMock.mockResolvedValue({ jobs: [retained.job] });
    getImportMock.mockResolvedValue(retained);
    resumeMock.mockResolvedValue({ ...retained, job: { ...retained.job, status: "committed", committed_rows: 1 },
      rows: [{ ...retained.rows[0], commit_status: "committed", created_docket_id: "docket-1" }], replayed: false });
    render(withClient(<IpPortfolioImportsPage />));
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /trademarks.csv/i }));
    await user.click(screen.getByRole("button", { name: "Commit to portfolio" }));
    await waitFor(() => expect(resumeMock).toHaveBeenCalledWith(expect.objectContaining({
      jobId: retained.job.id, expectedJobVersion: retained.job.version, previewToken: null,
      onProgress: expect.any(Function),
    })));
    expect(commitMock).not.toHaveBeenCalled();
    expect(sessionStorage.length).toBe(0);
  });

  it("does not enable a fresh commit for an all-unusable source", async () => {
    const unusable = preview();
    unusable.job.valid_rows = 0;
    unusable.job.invalid_rows = 1;
    uploadMock.mockResolvedValue(unusable);
    render(withClient(<IpPortfolioImportsPage />));
    const user = userEvent.setup();
    await user.upload(screen.getByLabelText("CSV or XLSX file"), new File(["Comment\nOnly notes"], "source.csv"));
    await user.click(screen.getByRole("button", { name: "Validate file" }));
    await screen.findByRole("heading", { name: "Review trademarks.csv" });
    expect(screen.getByRole("button", { name: "Commit to portfolio" })).toBeDisabled();
  });

  it("separates draft and image notes from blocking issues without disabling eligible rows", async () => {
    const source = preview();
    source.rows[0].normalized._warnings = [
      { field: "specification", code: "source_incomplete_draft" },
      { field: "image_reference", code: "source_reference_only" },
      { field: "jurisdiction", code: "configured_workspace_context" },
    ];
    source.rows[0].normalized.jurisdiction = "IN";
    uploadMock.mockResolvedValue(source);
    render(withClient(<IpPortfolioImportsPage />));
    const user = userEvent.setup();
    await user.upload(screen.getByLabelText("CSV or XLSX file"), new File(["Trademark\nSynthetic"], "source.csv"));
    await user.click(screen.getByRole("button", { name: "Validate file" }));
    const notes = await screen.findByRole("group", { name: "Non-blocking notes for row 1" });
    expect(within(notes).getByText("Specification: Not supplied; new imported records remain drafts.")).toBeVisible();
    expect(within(notes).getByText("Image reference: Source text retained; no image downloaded or attached.")).toBeVisible();
    expect(within(notes).getByText("Jurisdiction: Using workspace context (IN).")).toBeVisible();
    expect(screen.queryByRole("group", { name: "Blocking issues for row 1" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Commit to portfolio" })).toBeEnabled();
    expect(screen.queryByText(/source incomplete draft|source reference only/)).not.toBeInTheDocument();
  });

  it.each(["skip", "link_existing"] as const)("scopes retained %s notes to source data, not the existing record lifecycle", async (decision) => {
    const retained = preview();
    retained.job.status = "committed";
    retained.rows[0].reconciliation_decision = decision;
    retained.rows[0].reconciled_target_docket_id = decision === "link_existing" ? "existing-active" : null;
    retained.rows[0].duplicate_candidates = [{ docket_id: "existing-active", title: "Existing active mark", match_reasons: ["exact_application_number"] }];
    retained.rows[0].commit_status = decision === "skip" ? "skipped" : "committed";
    retained.rows[0].commit_error_code = decision === "skip" ? "duplicate_skipped" : null;
    retained.rows[0].normalized._warnings = [
      { field: "specification", code: "source_incomplete_draft" },
      { field: "application_date", code: "invalid_optional_date" },
    ];
    historyMock.mockResolvedValue({ jobs: [retained.job] });
    getImportMock.mockResolvedValue(retained);
    render(withClient(<IpPortfolioImportsPage />));
    await userEvent.click(await screen.findByRole("button", { name: /trademarks.csv/i }));
    const notes = await screen.findByRole("group", { name: "Non-blocking notes for row 1" });
    expect(within(notes).getByText("Specification: Not supplied; new imported records remain drafts.")).toBeVisible();
    expect(within(notes).getByText("Application date: Source date not recognized; it is not imported.")).toBeVisible();
    expect(screen.queryByText(/the record remains a draft|no date will be saved/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Commit to portfolio" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Refresh preview" })).not.toBeInTheDocument();
    expect(commitMock).not.toHaveBeenCalled();
    expect(fetchDocketMock).not.toHaveBeenCalled();
  });

  it.each([true, false])("refreshes a nonexpired context-blocked history preview with admin=%s", async (admin) => {
    useCapabilityMock.mockImplementation((capability: string) => capability !== "ip:taxonomy_admin" || admin);
    const blocked = preview();
    blocked.job.valid_rows = 0;
    blocked.job.invalid_rows = 1;
    blocked.rows[0].validation_status = "invalid";
    blocked.rows[0].errors = [
      { field: "jurisdiction", code: "workspace_context_required" },
      { field: "office", code: "workspace_context_required" },
    ];
    blocked.rows[0].normalized._warnings = [{ field: "specification", code: "source_incomplete_draft" }];
    const refreshed = preview();
    refreshed.job.version = 2;
    refreshed.job.preview_token = "refreshed-context-token";
    historyMock.mockResolvedValue({ jobs: [blocked.job] });
    getImportMock.mockResolvedValue(blocked);
    revalidateMock.mockResolvedValue(refreshed);
    commitMock.mockResolvedValue({ ...refreshed, job: { ...refreshed.job, status: "committed" } });
    render(withClient(<IpPortfolioImportsPage />));
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /trademarks.csv/i }));
    const issues = await screen.findByRole("group", { name: "Blocking issues for row 1" });
    expect(within(issues).getByText("Jurisdiction: Missing from source and no single workspace value was available.")).toBeVisible();
    expect(screen.getByRole("group", { name: "Non-blocking notes for row 1" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Commit to portfolio" })).toBeDisabled();
    expect(screen.getByText("Workspace context needs review")).toBeVisible();
    if (admin) expect(screen.getByRole("link", { name: "IP workspace" })).toHaveAttribute("href", "/app/ip");
    else expect(screen.getByText(/Ask a workspace administrator/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Refresh preview" }));
    await waitFor(() => expect(revalidateMock).toHaveBeenCalledWith("import-1", expect.anything()));
    await waitFor(() => expect(screen.queryByText("Workspace context needs review")).not.toBeInTheDocument());
    expect(uploadMock).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Commit to portfolio" }));
    await waitFor(() => expect(commitMock).toHaveBeenCalledWith(expect.objectContaining({ previewToken: "refreshed-context-token" })));
    expect(screen.queryByRole("button", { name: "Refresh preview" })).not.toBeInTheDocument();
  });

  it("B4-ADJ-11 explains the source status at the field: phase, unrecognised wording and missing number", async () => {
    const source = preview();
    source.rows[0].normalized.source_status = "Registered";
    source.rows[0].normalized._warnings = [{ field: "source_status", code: "declared_status_unverified" }];
    const refused = structuredClone(source.rows[0]);
    refused.row_number = 2;
    refused.id = "row-2";
    refused.normalized = { ...refused.normalized, source_status: "Regsitered",
      _warnings: [{ field: "source_status", code: "unrecognised_status" }] };
    const numberless = structuredClone(source.rows[0]);
    numberless.row_number = 3;
    numberless.id = "row-3";
    numberless.validation_status = "invalid";
    numberless.normalized = { ...numberless.normalized, _warnings: [] };
    numberless.errors = [{ field: "application_number", code: "required_for_source_status" }];
    source.rows.push(refused, numberless);
    uploadMock.mockResolvedValue(source);
    render(withClient(<IpPortfolioImportsPage />));
    const user = userEvent.setup();
    await user.upload(screen.getByLabelText("CSV or XLSX file"), new File(["Trademark\nSynthetic"], "source.csv"));
    await user.click(screen.getByRole("button", { name: "Validate file" }));
    const notes = await screen.findByRole("group", { name: "Non-blocking notes for row 1" });
    expect(within(notes).getByText(/Status: Imported as Filed\. "Registered" is kept as the unverified source status/)).toBeVisible();
    const typo = screen.getByRole("group", { name: "Non-blocking notes for row 2" });
    expect(within(typo).getByText(/Status: "Regsitered" is not a status this import recognises, so the row imports in the Draft phase/)).toBeVisible();
    expect(screen.queryByRole("group", { name: "Blocking issues for row 2" })).not.toBeInTheDocument();
    const missing = screen.getByRole("group", { name: "Blocking issues for row 3" });
    expect(within(missing).getByText(/Application number: Required: a "Registered" mark has been filed/)).toBeVisible();
  });

  it("retains unknown blocking codes and cannot refresh or commit without write access", async () => {
    useCapabilityMock.mockImplementation((capability: string) => capability === "ip:read");
    const blocked = preview();
    blocked.rows[0].errors = [{ field: "class_number", code: "out_of_range" }];
    blocked.rows[0].validation_status = "invalid";
    blocked.job.valid_rows = 0;
    blocked.job.invalid_rows = 1;
    historyMock.mockResolvedValue({ jobs: [blocked.job] });
    getImportMock.mockResolvedValue(blocked);
    render(withClient(<IpPortfolioImportsPage />));
    await userEvent.click(await screen.findByRole("button", { name: /trademarks.csv/i }));
    const issues = await screen.findByRole("group", { name: "Blocking issues for row 1" });
    expect(within(issues).getByText("Class: out of range")).toBeVisible();
    expect(screen.getByRole("button", { name: "Refresh preview" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Commit to portfolio" })).toBeDisabled();
    expect(revalidateMock).not.toHaveBeenCalled();
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
