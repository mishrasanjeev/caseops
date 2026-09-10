import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { campaignSchema, createAccessReview, decideAccessReview, finalizeAccessReview, type Campaign } from "./access-reviews";

const campaign: Campaign = { id: "review", title: "Review", reason: "Quarterly certification", trigger: "periodic", status: "open", version: 1, creator_user_id: "owner", created_at: "2026-09-10T00:00:00Z", finalized_at: null, snapshot: { target_type: "ip_docket", target_id: "target", target_title: "Reviewed docket", access_policy_version: 7, grants: [{ id: "grant", record_version: 2, subject_type: "team", subject_id: "team", subject_label: "Review team", reason: "Prior grant", effective_from: null, expires_at: null }] }, decisions: [] };
const commands = [
  { name: "create", send: () => createAccessReview(campaign.snapshot, campaign.title, campaign.reason, "periodic"), body: { target_type: "ip_docket", target_id: "target", expected_access_policy_version: 7, title: campaign.title, reason: campaign.reason, trigger: "periodic" } },
  { name: "decide", send: () => decideAccessReview(campaign, "grant", "revoke", "Engagement ended"), body: { expected_version: 1, grant_id: "grant", decision: "revoke", reason: "Engagement ended" } },
  { name: "finalize", send: () => finalizeAccessReview(campaign), body: { expected_version: 1 } },
];

describe("Access review transport", () => {
  beforeEach(() => { window.localStorage.clear(); vi.stubGlobal("fetch", vi.fn()); });
  afterEach(() => vi.unstubAllGlobals());
  it.each(commands)("encodes $name once and validates the nested response", async ({ send, body }) => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(campaign), { status: 200, headers: { "Content-Type": "application/json" } }));
    await expect(send()).resolves.toEqual(campaign);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(JSON.parse(vi.mocked(fetch).mock.calls[0][1]!.body as string)).toEqual(body);
  });
  it.each(commands)("retains $name conflict without automatic replay", async ({ send }) => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ status: 409, detail: "Snapshot changed", type: "review_stale" }), { status: 409, headers: { "Content-Type": "application/problem+json" } }));
    await expect(send()).rejects.toMatchObject({ status: 409 });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("rejects a simplified grant missing its authoritative version", () => {
    expect(() => campaignSchema.parse({ ...campaign, snapshot: { ...campaign.snapshot, grants: [{ id: "grant", subject_label: "Unsafe simplified fixture" }] } })).toThrow();
  });
});
