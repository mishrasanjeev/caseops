import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchMock, historyMock, detailMock, holdSummaryMock, createMock, capabilityMock, requestReviewMock, approveReviewMock, rejectReviewMock } = vi.hoisted(() => ({ fetchMock: vi.fn(), historyMock: vi.fn(), detailMock: vi.fn(), holdSummaryMock: vi.fn(), createMock: vi.fn(), capabilityMock: vi.fn(), requestReviewMock: vi.fn(), approveReviewMock: vi.fn(), rejectReviewMock: vi.fn() }));
vi.mock("@/lib/api/endpoints", () => ({ fetchTenantDataGovernanceIntegrity: fetchMock, listTenantDataOperationDryRuns: historyMock, fetchTenantDataOperationDryRun: detailMock, fetchTenantLegalHoldSummary: holdSummaryMock, createTenantDataOperationDryRun: createMock, requestTenantDataOperationReview: requestReviewMock, approveTenantDataOperationReview: approveReviewMock, rejectTenantDataOperationReview: rejectReviewMock }));
vi.mock("@/lib/capabilities", () => ({ useCapability: (capability: string) => capabilityMock(capability) }));
import DataGovernancePage from "@/app/app/admin/data-governance/page";

function withClient(children: ReactNode) { return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>; }

describe("DataGovernancePage", () => {
  beforeEach(() => { capabilityMock.mockReset(); fetchMock.mockReset(); historyMock.mockReset(); detailMock.mockReset(); createMock.mockReset(); capabilityMock.mockImplementation(() => true); requestReviewMock.mockReset(); approveReviewMock.mockReset(); rejectReviewMock.mockReset(); requestReviewMock.mockResolvedValue({}); approveReviewMock.mockResolvedValue({}); rejectReviewMock.mockResolvedValue({}); fetchMock.mockResolvedValue({ checks: [{ check_id: "expired_unpurged", status: "unavailable", summary: "No approved schedule.", findings: [], blocked_by: "DATA-GOV-02" }], ok_count: 0, finding_count: 0, unavailable_count: 1, is_complete: false }); historyMock.mockResolvedValue({ operations: [{ id: "dry-run-1", operation_type: "tenant_export", execution_mode: "dry_run", status: "dry_run_complete", approval_status: "not_requested", rejection_reason: null, request_scope_hash: "scope-hash", manifest_hash: "manifest-hash", request_evidence_ref: "DATA-GOV-01", completed_at: "2026-08-20T00:00:00Z", as_of: "2026-08-20T00:00:00Z" }] }); detailMock.mockResolvedValue({ id: "dry-run-1", operation_type: "tenant_export", execution_mode: "dry_run", status: "dry_run_complete", approval_status: "not_requested", rejection_reason: null, request_scope_hash: "scope-hash", manifest_hash: "manifest-hash", request_evidence_ref: "DATA-GOV-01", completed_at: "2026-08-20T00:00:00Z", as_of: "2026-08-20T00:00:00Z", items: [], exclusions: [], offboarding_plan: [], dependency_plan: null }); createMock.mockResolvedValue({ id: "dry-run-created", operation_type: "tenant_export", execution_mode: "dry_run", status: "dry_run_complete", approval_status: "not_requested", rejection_reason: null, request_scope_hash: "scope-hash", manifest_hash: "manifest-hash", request_evidence_ref: "DATA-GOV-01", completed_at: "2026-08-20T00:00:00Z", as_of: "2026-08-20T00:00:00Z", items: [], exclusions: [], offboarding_plan: [], dependency_plan: null }); });
  beforeEach(() => { holdSummaryMock.mockReset(); holdSummaryMock.mockResolvedValue({ draft_count: 1, active_count: 2, released_count: 3, cancelled_count: 4, active_company_wide_count: 1, active_scoped_count: 1, active_item_count: 7, preservation_effective: true }); });
  it("shows unavailable controls as unavailable, not healthy", async () => { render(withClient(<DataGovernancePage />)); expect(await screen.findByTestId("governance-check-expired_unpurged")).toHaveTextContent("unavailable"); expect(screen.getByText("Blocked by: DATA-GOV-02")).toBeInTheDocument(); expect(screen.getByText(/never exports, purges, offboards, restores, or executes/i)).toBeInTheDocument(); });
  it("does not fetch for a member holding neither capability", () => { capabilityMock.mockImplementation(() => false); render(withClient(<DataGovernancePage />)); expect(screen.getByText(/Data-governance access required/i)).toBeInTheDocument(); expect(fetchMock).not.toHaveBeenCalled(); expect(historyMock).not.toHaveBeenCalled(); });
  it("reviews a selected dry-run manifest without exposing an operation control", async () => { render(withClient(<DataGovernancePage />)); fireEvent.click(await screen.findByTestId("dry-run-dry-run-1")); expect(await screen.findByText("manifest-hash")).toBeInTheDocument(); expect(screen.getByText(/not an execution authorization/i)).toBeInTheDocument(); expect(detailMock).toHaveBeenCalledWith("dry-run-1"); });
  it("creates only a hashed-input non-executable dry run", async () => { render(withClient(<DataGovernancePage />)); fireEvent.change(screen.getByLabelText(/Evidence reference/i), { target: { value: "ticket://review" } }); fireEvent.change(screen.getByLabelText(/Registered data class ID/i), { target: { value: "legal_holds" } }); fireEvent.change(screen.getByLabelText(/Target type/i), { target: { value: "tenant" } }); fireEvent.change(screen.getByLabelText(/SHA-256 target reference/i), { target: { value: "a".repeat(64) } }); fireEvent.click(screen.getByRole("button", { name: /Create non-executable dry run/i })); await screen.findByTestId("dry-run-detail"); expect(createMock).toHaveBeenCalledWith(expect.objectContaining({ operationType: "tenant_export", requestEvidenceRef: "ticket://review", items: [expect.objectContaining({ dataClassId: "legal_holds", targetReferenceHash: "a".repeat(64) })] })); expect(screen.getByText(/do not enter client, matter, or document identifiers/i)).toBeInTheDocument(); });
  it("shows aggregate legal-hold preservation without hold content", async () => { render(withClient(<DataGovernancePage />)); const summary = await screen.findByTestId("legal-hold-summary"); expect(summary).toHaveTextContent("preservation effective"); expect(summary).toHaveTextContent("Active holds"); expect(summary).toHaveTextContent("7"); expect(screen.getByText(/Hold records, scopes, authorities, and held-item references are never shown here/i)).toBeInTheDocument(); expect(holdSummaryMock).toHaveBeenCalledOnce(); });
  it("lets a reviewer who is not the owner see and act on the queue", async () => {
    // The case the whole capability split exists for. An admin holds
    // data_operations:review and NOT the owner-only audit:export. Before this,
    // the page refused them outright, so the second pair of eyes could not
    // reach the screen they were meant to review on.
    capabilityMock.mockImplementation((capability: string) => capability === "data_operations:review");
    detailMock.mockResolvedValue({ id: "dry-run-1", operation_type: "tenant_export", execution_mode: "dry_run", status: "dry_run_complete", approval_status: "requested", rejection_reason: null, request_scope_hash: "scope-hash", manifest_hash: "manifest-hash", request_evidence_ref: "DATA-GOV-01", completed_at: "2026-08-20T00:00:00Z", as_of: "2026-08-20T00:00:00Z", approved_operation_id: null, items: [], exclusions: [], offboarding_plan: [], dependency_plan: null });
    render(withClient(<DataGovernancePage />));

    fireEvent.click(await screen.findByTestId("dry-run-dry-run-1"));
    await screen.findByText("awaiting a second approver");
    const review = screen.getByTestId("data-operation-review");
    // Tenant-wide oversight is NOT widened by being a reviewer.
    expect(fetchMock).not.toHaveBeenCalled();
    expect(holdSummaryMock).not.toHaveBeenCalled();
    expect(screen.queryByTestId("legal-hold-summary")).toBeNull();

    fireEvent.change(screen.getByLabelText(/Approve as/i), { target: { value: "Records Partner" } });
    fireEvent.click(screen.getByRole("button", { name: /Approve/i }));
    await waitFor(() => expect(approveReviewMock).toHaveBeenCalledWith("dry-run-1", "Records Partner"));
  });

  it("never presents approval as execution", async () => {
    // A screen that authorises an export must not let the reader believe the
    // export happened. The status word, the card description and the detail
    // line all have to say authorised rather than done.
    detailMock.mockResolvedValue({ id: "dry-run-1", operation_type: "tenant_export", execution_mode: "dry_run", status: "dry_run_complete", approval_status: "requested", rejection_reason: null, request_scope_hash: "scope-hash", manifest_hash: "manifest-hash", request_evidence_ref: "DATA-GOV-01", completed_at: "2026-08-20T00:00:00Z", as_of: "2026-08-20T00:00:00Z", approved_operation_id: "execute-9", items: [], exclusions: [], offboarding_plan: [], dependency_plan: null });
    render(withClient(<DataGovernancePage />));

    fireEvent.click(await screen.findByTestId("dry-run-dry-run-1"));
    await screen.findByText("authorised, not executed");
    const review = screen.getByTestId("data-operation-review");
    expect(review).toHaveTextContent("execute-9");
    expect(review).toHaveTextContent(/planned and has not run/i);
    expect(review).toHaveTextContent(/does not run one/i);
    // A signed authorisation is revoked explicitly, so no refuse control here.
    expect(screen.queryByRole("button", { name: /Refuse this operation/i })).toBeNull();
  });

  it("explains four eyes and step-up before asking for an approval", async () => {
    detailMock.mockResolvedValue({ id: "dry-run-1", operation_type: "retention_purge", execution_mode: "dry_run", status: "dry_run_complete", approval_status: "requested", rejection_reason: null, request_scope_hash: "scope-hash", manifest_hash: "manifest-hash", request_evidence_ref: "DATA-GOV-01", completed_at: "2026-08-20T00:00:00Z", as_of: "2026-08-20T00:00:00Z", approved_operation_id: null, items: [], exclusions: [], offboarding_plan: [], dependency_plan: null });
    render(withClient(<DataGovernancePage />));

    fireEvent.click(await screen.findByTestId("dry-run-dry-run-1"));
    await screen.findByText(/second person and a recent MFA step-up/i);
    const review = screen.getByTestId("data-operation-review");
    expect(review).toHaveTextContent(/cannot approve it/i);
    // Refusing is deliberately ungated, and the copy says so rather than
    // leaving a blocked approver to assume they are stuck.
    expect(review).toHaveTextContent(/refusing needs neither/i);

    fireEvent.change(screen.getByLabelText(/Refuse, with a reason/i), { target: { value: "No approved schedule." } });
    fireEvent.click(screen.getByRole("button", { name: /Refuse this operation/i }));
    await waitFor(() => expect(rejectReviewMock).toHaveBeenCalledWith("dry-run-1", "No approved schedule."));
  });

  it("shows a refusal as final rather than retryable", async () => {
    detailMock.mockResolvedValue({ id: "dry-run-1", operation_type: "tenant_export", execution_mode: "dry_run", status: "dry_run_complete", approval_status: "rejected", rejection_reason: "The retention schedule cited here has not been approved.", request_scope_hash: "scope-hash", manifest_hash: "manifest-hash", request_evidence_ref: "DATA-GOV-01", completed_at: "2026-08-20T00:00:00Z", as_of: "2026-08-20T00:00:00Z", approved_operation_id: null, items: [], exclusions: [], offboarding_plan: [], dependency_plan: null });
    render(withClient(<DataGovernancePage />));

    fireEvent.click(await screen.findByTestId("dry-run-dry-run-1"));
    await screen.findByText("refused");
    const review = screen.getByTestId("data-operation-review");
    expect(review).toHaveTextContent("The retention schedule cited here has not been approved.");
    expect(review).toHaveTextContent(/A refusal is final/i);
    expect(screen.queryByRole("button", { name: /Approve/i })).toBeNull();
  });

});
