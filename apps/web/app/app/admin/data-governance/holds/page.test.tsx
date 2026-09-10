import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  list: vi.fn(), create: vi.fn(), activate: vi.fn(), proposals: vi.fn(), request: vi.fn(), approve: vi.fn(),
  catalog: vi.fn(), stepUp: vi.fn(), dryRun: vi.fn(), capability: vi.fn(),
}));
vi.mock("@/lib/api/legal-holds", () => ({ listLegalHolds: mocks.list, createLegalHold: mocks.create,
  activateLegalHold: mocks.activate, listHoldReleaseRequests: mocks.proposals, requestHoldRelease: mocks.request,
  approveHoldRelease: mocks.approve }));
vi.mock("@/lib/api/endpoints", () => ({ fetchTenantDataClassCatalog: mocks.catalog,
  completeMfaStepUp: mocks.stepUp, createTenantScopedDataOperationDryRun: mocks.dryRun }));
vi.mock("@/lib/capabilities", () => ({ useCapability: mocks.capability }));
vi.mock("@/lib/use-session", () => ({ useSession: () => ({ context: { membership: { id: "owner" } } }) }));

import Page from "./page";

const hold = { id: "hold-1", title: "Synthetic preservation", authority_reference: "fixture://authority",
  status: "draft", scope: "data_classes", data_class_ids: ["legal_holds"], created_by_membership_id: "owner",
  approved_by_membership_id: null, updated_at: "2026-09-09T00:00:00Z", activated_at: null, released_at: null };
function mount() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><Page /></QueryClientProvider>);
}
function fillDraft() {
  fireEvent.change(screen.getByLabelText("Title"), { target: { value: hold.title } });
  fireEvent.change(screen.getByLabelText("Authority reference"), { target: { value: hold.authority_reference } });
  fireEvent.change(screen.getByLabelText("Preservation scope"), { target: { value: "legal_holds" } });
}
describe("Legal hold commands", () => {
  beforeEach(() => {
    vi.resetAllMocks(); mocks.capability.mockReturnValue(true);
    mocks.list.mockResolvedValue({ holds: [], has_more: false, next_before_id: null });
    mocks.catalog.mockResolvedValue({ data_classes: [{ id: "legal_holds", label: "Preservation records" }] });
    mocks.proposals.mockResolvedValue({ proposals: [], has_more: false, next_before_id: null });
  });
  it("records a draft with server-owned scope and keeps success free of errors", async () => {
    mocks.create.mockResolvedValue(hold);
    mount(); await screen.findByRole("option", { name: "Preservation records" }); fillDraft();
    mocks.list.mockResolvedValue({ holds: [hold], has_more: false, next_before_id: null });
    fireEvent.click(screen.getByRole("button", { name: "Record draft" }));
    expect(await screen.findByText("Preservation draft recorded.")).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({ scope: "data_classes", data_class_ids: ["legal_holds"] }));
    expect(screen.getByRole("button", { name: "Approve preservation" })).toBeDisabled();
    expect(screen.getByLabelText("Title")).toHaveValue("");
  });
  it("retains inputs and has no success feedback after a rejected command", async () => {
    mocks.create.mockRejectedValue(new Error("MFA step-up is required"));
    mount(); await screen.findByRole("option", { name: "Preservation records" }); fillDraft();
    fireEvent.click(screen.getByRole("button", { name: "Record draft" }));
    expect(await screen.findByRole("alert")).toBeVisible();
    expect(screen.getByLabelText("Title")).toHaveValue(hold.title);
    expect(screen.queryByText("Preservation draft recorded.")).not.toBeInTheDocument();
  });
  it("waits for authoritative discovery and keeps failed discovery noneditable", async () => {
    let reject!: (reason: Error) => void;
    mocks.list.mockReturnValue(new Promise((_resolve, rejectPromise) => { reject = rejectPromise; }));
    mount(); await screen.findByRole("option", { name: "Preservation records" }); fillDraft();
    expect(screen.getByRole("button", { name: "Record draft" })).toBeDisabled();
    reject(new Error("Inventory unavailable"));
    await screen.findByText("Could not load legal holds");
    expect(screen.getByRole("button", { name: "Record draft" })).toBeDisabled();
    expect(mocks.create).not.toHaveBeenCalled();
  });
  it("keeps whole-workspace release unavailable and displays the preserved authority", async () => {
    mocks.list.mockResolvedValue({ holds: [{ ...hold, scope: "company", status: "active", data_class_ids: [] }], has_more: false, next_before_id: null });
    mount(); fireEvent.click(await screen.findByRole("button", { name: "Synthetic preservation: active" }));
    expect(await screen.findByText("Release unavailable: the complete workspace data inventory is not certified.")).toBeVisible();
    expect(screen.getByText("fixture://authority")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Request release" })).not.toBeInTheDocument();
  });
  it("binds MFA verification to the preservation purpose", async () => {
    mocks.stepUp.mockResolvedValue({ status: "verified", expires_at: "2026-09-09T00:10:00Z" });
    mount(); fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify identity" }));
    await waitFor(() => expect(mocks.stepUp).toHaveBeenCalledWith({ code: "123456", purpose: "legal_hold_change", method: "totp" }));
    expect(await screen.findByText("Identity verified for preservation changes.")).toBeVisible();
  });
  it("does not fetch preservation metadata without capability", () => {
    mocks.capability.mockReturnValue(false); mount();
    expect(screen.getByRole("alert")).toHaveTextContent("Preservation administration access is required.");
    expect(mocks.list).not.toHaveBeenCalled(); expect(mocks.catalog).not.toHaveBeenCalled();
  });
  it("lets an independent administrator approve without exposing owner-only diagnostics", async () => {
    mocks.capability.mockImplementation((capability: string) => capability === "legal_holds:manage");
    const draft = { ...hold, created_by_membership_id: "another-person" };
    const active = { ...draft, status: "active", approved_by_membership_id: "owner" };
    mocks.list.mockResolvedValue({ holds: [draft], has_more: false, next_before_id: null });
    mocks.activate.mockResolvedValue(active);
    mount();
    const approve = await screen.findByRole("button", { name: "Approve preservation" });
    mocks.list.mockResolvedValue({ holds: [active], has_more: false, next_before_id: null });
    fireEvent.click(approve);
    expect(await screen.findByText("Preservation is active.")).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Record draft" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Request release" })).not.toBeInTheDocument();
    expect(mocks.catalog).not.toHaveBeenCalled();
  });
  it.each([true, false])("retains the release proposal and reports its actual outcome: %s", async (success) => {
    const active = { ...hold, status: "active" };
    const released = { ...active, status: "released" };
    const proposal = { id: "proposal", hold_id: hold.id, requester_membership_id: "another-person",
      request_hash: "a".repeat(64), expires_at: "2026-09-09T00:30:00Z",
      reason_reference: "fixture://release-authority", dry_run_id: "dry-run" };
    mocks.list.mockResolvedValue({ holds: [active], has_more: false, next_before_id: null });
    mocks.proposals.mockResolvedValue({ proposals: [proposal], has_more: false, next_before_id: null });
    if (success) mocks.approve.mockResolvedValue(released);
    else mocks.approve.mockRejectedValue(new Error("Preservation evidence changed"));
    mount(); fireEvent.click(await screen.findByRole("button", { name: "Synthetic preservation: active" }));
    expect(await screen.findByText(proposal.reason_reference)).toBeVisible();
    if (success) mocks.list.mockResolvedValue({ holds: [released], has_more: false, next_before_id: null });
    fireEvent.click(await screen.findByRole("button", { name: "Approve release" }));
    if (success) {
      expect(await screen.findByText("Hold released. No records were deleted.")).toBeVisible();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Synthetic preservation: released" })).toBeVisible();
    } else {
      expect(await screen.findByRole("alert")).toBeVisible();
      expect(screen.getByText(proposal.reason_reference)).toBeVisible();
      expect(screen.getByRole("button", { name: "Synthetic preservation: active" })).toBeVisible();
      expect(screen.queryByText("Hold released. No records were deleted.")).not.toBeInTheDocument();
    }
  });
  it("navigates bounded hold pages and can recover after a failed continuation", async () => {
    const older = { ...hold, id: "older", title: "Older preservation" };
    mocks.list.mockImplementation((_signal: AbortSignal, cursor: string | null) => cursor
      ? Promise.reject(new Error("Continuation unavailable"))
      : Promise.resolve({ holds: [hold], has_more: true, next_before_id: hold.id }));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Synthetic preservation: draft" }));
    fireEvent.click(screen.getByRole("button", { name: "Older holds" }));
    expect(await screen.findByText("Could not load legal holds")).toBeVisible();
    expect(screen.getByRole("button", { name: "Record draft" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Older holds" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Newer holds" }));
    await screen.findByRole("button", { name: "Synthetic preservation: draft" });
    mocks.list.mockImplementation((_signal: AbortSignal, cursor: string | null) => Promise.resolve(cursor
      ? { holds: [older], has_more: false, next_before_id: null }
      : { holds: [hold], has_more: true, next_before_id: hold.id }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Older holds" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Older holds" }));
    expect(await screen.findByRole("button", { name: "Older preservation: draft" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Synthetic preservation: draft" })).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
  it("returns a newly created hold to the first page instead of losing the successful record", async () => {
    const older = { ...hold, id: "older", title: "Older preservation" };
    mocks.list.mockImplementation((_signal: AbortSignal, cursor: string | null) => Promise.resolve(cursor
      ? { holds: [older], has_more: false, next_before_id: null }
      : { holds: [hold], has_more: true, next_before_id: hold.id }));
    mount();
    await screen.findByRole("button", { name: "Synthetic preservation: draft" });
    fireEvent.click(screen.getByRole("button", { name: "Older holds" }));
    await screen.findByRole("button", { name: "Older preservation: draft" });
    fillDraft();
    const created = { ...hold, id: "created", title: "New preservation" };
    mocks.create.mockResolvedValue(created);
    mocks.list.mockResolvedValue({ holds: [created, hold], has_more: true, next_before_id: hold.id });
    fireEvent.click(screen.getByRole("button", { name: "Record draft" }));
    expect(await screen.findByText("Preservation draft recorded.")).toBeVisible();
    expect(screen.getByRole("button", { name: "New preservation: draft" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Newer holds" })).toBeDisabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
  it("navigates release proposals without carrying the cursor to another hold", async () => {
    const active = { ...hold, status: "active" };
    const other = { ...active, id: "other", title: "Other preservation" };
    const proposal = { id: "proposal", hold_id: hold.id, requester_membership_id: "another-person",
      request_hash: "a".repeat(64), expires_at: "2026-09-09T00:30:00Z",
      reason_reference: "fixture://release-one", dry_run_id: "dry-run" };
    mocks.list.mockResolvedValue({ holds: [active, other], has_more: false, next_before_id: null });
    mocks.proposals.mockImplementation((_id: string, _signal: AbortSignal, cursor: string | null) => Promise.resolve(cursor
      ? { proposals: [{ ...proposal, id: "older-proposal", reason_reference: "fixture://release-two" }], has_more: false, next_before_id: null }
      : { proposals: [proposal], has_more: true, next_before_id: proposal.id }));
    mount(); fireEvent.click(await screen.findByRole("button", { name: "Synthetic preservation: active" }));
    await screen.findByText("fixture://release-one");
    fireEvent.click(screen.getByRole("button", { name: "Older release requests" }));
    expect(await screen.findByText("fixture://release-two")).toBeVisible();
    expect(screen.queryByText("fixture://release-one")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Other preservation: active" }));
    await screen.findByText("fixture://release-one");
    expect(mocks.proposals).toHaveBeenLastCalledWith("other", expect.any(AbortSignal), null);
    expect(screen.getByRole("button", { name: "Newer release requests" })).toBeDisabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
