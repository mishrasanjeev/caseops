import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ targets: vi.fn(), scope: vi.fn(), list: vi.fn(), get: vi.fn(), create: vi.fn(), decide: vi.fn(), finalize: vi.fn(), verify: vi.fn(), capability: vi.fn() }));
vi.mock("@/lib/api/access-reviews", () => ({ listReviewTargets: mocks.targets, fetchReviewScope: mocks.scope, listAccessReviews: mocks.list, fetchAccessReview: mocks.get, createAccessReview: mocks.create, decideAccessReview: mocks.decide, finalizeAccessReview: mocks.finalize }));
vi.mock("@/lib/api/endpoints", () => ({ completeMfaStepUp: mocks.verify }));
vi.mock("@/lib/capabilities", () => ({ useCapability: mocks.capability }));
vi.mock("@/lib/use-session", () => ({ useSession: () => ({ context: { user: { id: "owner" }, membership: { id: "owner-member" } } }) }));
import Page from "./page";

const scope = { target_type: "ip_docket", target_id: "docket", target_title: "Review target", access_policy_version: 2, grants: [{ id: "grant", record_version: 0, subject_type: "membership", subject_id: "subject", subject_label: "Grant recipient", reason: "Original engagement", effective_from: null, expires_at: null }] };
const campaign = { id: "campaign", title: "September review", reason: "Periodic certification", trigger: "periodic", status: "open", version: 1, creator_user_id: "owner", created_at: "2026-09-10T00:00:00Z", finalized_at: null, snapshot: scope, decisions: [] };
function mount() { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><Page /></QueryClientProvider>); }
async function fill() {
  await screen.findByRole("option", { name: "Review target" });
  fireEvent.change(screen.getByLabelText("Review target"), { target: { value: "docket" } });
  await screen.findByText("1 standing grants. Access version 2.");
  fireEvent.change(screen.getByLabelText("Campaign title"), { target: { value: campaign.title } });
  fireEvent.change(screen.getByLabelText("Reason or ticket"), { target: { value: campaign.reason } });
}
describe("Access review screen", () => {
  beforeEach(() => {
    vi.resetAllMocks(); mocks.capability.mockReturnValue(true);
    mocks.targets.mockResolvedValue({ targets: [{ id: "docket", title: "Review target" }], next_after_id: null });
    mocks.scope.mockResolvedValue(scope); mocks.list.mockResolvedValue({ campaigns: [], next_before_id: null }); mocks.get.mockResolvedValue(campaign);
  });
  it("opens the discovered scope and prevents preparer self-review without an error toast", async () => {
    mocks.create.mockResolvedValue(campaign); mount(); await fill();
    mocks.list.mockResolvedValue({ campaigns: [campaign], next_before_id: null });
    fireEvent.click(screen.getByRole("button", { name: "Open campaign" }));
    expect(await screen.findByText("Access review opened.")).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(mocks.create).toHaveBeenCalledWith(scope, campaign.title, campaign.reason, "periodic");
    expect(await screen.findByRole("button", { name: "Record decision" })).toBeDisabled();
  });
  it("retains source inputs after rejected creation", async () => {
    mocks.create.mockRejectedValue(new Error("Snapshot changed")); mount(); await fill();
    fireEvent.click(screen.getByRole("button", { name: "Open campaign" }));
    expect(await screen.findByRole("alert")).toBeVisible();
    expect(screen.getByLabelText("Campaign title")).toHaveValue(campaign.title);
    expect(screen.getByLabelText("Reason or ticket")).toHaveValue(campaign.reason);
    expect(screen.queryByText("Access review opened.")).not.toBeInTheDocument();
  });
  it("waits for initial authoritative discovery even when target scope arrives first", async () => {
    let reject!: (reason: Error) => void;
    mocks.list.mockReturnValue(new Promise((_resolve, failed) => { reject = failed; }));
    mount(); await fill();
    expect(screen.getByRole("button", { name: "Open campaign" })).toBeDisabled();
    reject(new Error("Register unavailable"));
    await screen.findByText("Could not load access reviews");
    expect(screen.getByRole("button", { name: "Open campaign" })).toBeDisabled();
    expect(mocks.create).not.toHaveBeenCalled();
  });
  it("performs no private discovery after capability denial", () => {
    mocks.capability.mockReturnValue(false); mount();
    expect(screen.getByRole("alert")).toHaveTextContent("Access administration is required.");
    expect(mocks.targets).not.toHaveBeenCalled(); expect(mocks.list).not.toHaveBeenCalled();
  });
  it("uses the canonical access-change step-up purpose", async () => {
    mocks.verify.mockResolvedValue({ status: "verified" }); mount();
    fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify identity" }));
    await waitFor(() => expect(mocks.verify).toHaveBeenCalledWith({ code: "123456", purpose: "record_access_change", method: "totp" }));
    expect(await screen.findByText("Identity verified for access changes.")).toBeVisible();
  });
});
