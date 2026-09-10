import { beforeEach, describe, expect, it, vi } from "vitest";

const apiRequest = vi.hoisted(() => vi.fn());
vi.mock("./client", () => ({ apiRequest }));
import { listHoldReleaseRequests, listLegalHolds } from "./legal-holds";

describe("Preservation page contracts", () => {
  beforeEach(() => vi.resetAllMocks());
  it("uses bounded server-issued hold cursors and caller cancellation", async () => {
    const signal = new AbortController().signal;
    apiRequest.mockResolvedValue({ holds: [], has_more: false, next_before_id: null });
    await listLegalHolds(signal, "cursor&tenant=other");
    expect(apiRequest).toHaveBeenCalledWith("/api/admin/data-governance/holds?limit=25&before_id=cursor%26tenant%3Dother", { signal });
  });
  it("validates the complete nested release proposal page", async () => {
    const signal = new AbortController().signal;
    const proposal = { id: "proposal", hold_id: "hold", request_hash: "a".repeat(64),
      expires_at: "2026-09-10T00:30:00Z", requester_membership_id: "reviewer",
      reason_reference: "fixture://authority", dry_run_id: "dry-run" };
    apiRequest.mockResolvedValue({ proposals: [proposal], has_more: true, next_before_id: "proposal" });
    expect((await listHoldReleaseRequests("hold", signal, "previous")).proposals).toEqual([proposal]);
    expect(apiRequest).toHaveBeenCalledWith("/api/admin/data-governance/holds/hold/release-requests?limit=25&before_id=previous", { signal });
    apiRequest.mockResolvedValue({ proposals: [{ ...proposal, dry_run_id: undefined }], has_more: false, next_before_id: null });
    await expect(listHoldReleaseRequests("hold")).rejects.toThrow();
    apiRequest.mockResolvedValue([proposal]);
    await expect(listHoldReleaseRequests("hold")).rejects.toThrow();
  });
});
