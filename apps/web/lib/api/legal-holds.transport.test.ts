import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { activateLegalHold, approveHoldRelease, createLegalHold, requestHoldRelease, type LegalHold, type HoldRelease } from "./legal-holds";

const hold: LegalHold = {
  id: "hold", title: "Synthetic preservation", authority_reference: "fixture://authority",
  status: "draft", scope: "data_classes", data_class_ids: ["legal_holds"],
  created_by_membership_id: "owner", approved_by_membership_id: null,
  updated_at: "2026-09-10T00:00:00Z", activated_at: null, released_at: null,
};
const proposal: HoldRelease = {
  id: "proposal", hold_id: hold.id, request_hash: "a".repeat(64),
  expires_at: "2026-09-10T00:30:00Z", requester_membership_id: "owner",
  reason_reference: "fixture://release", dry_run_id: "dry-run",
};
const draft = { idempotency_key: "draft-key", title: hold.title,
  authority_reference: hold.authority_reference, scope: hold.scope, data_class_ids: hold.data_class_ids };
const release = { idempotency_key: "release-key", dry_run_id: proposal.dry_run_id, reason_reference: proposal.reason_reference };
const version = { expected_updated_at: hold.updated_at };
const commands = [
  { name: "create", send: () => createLegalHold(draft), body: draft, response: hold },
  { name: "activate", send: () => activateLegalHold(hold), body: version, response: hold },
  { name: "request release", send: () => requestHoldRelease(hold, release), body: { ...release, ...version }, response: proposal },
  { name: "approve release", send: () => approveHoldRelease(hold, proposal), body: version, response: hold },
];

describe("Preservation mutations through the real HTTP client", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => vi.unstubAllGlobals());
  it.each(commands)("serializes $name exactly once as a JSON object", async ({ send, body, response }) => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(response), {
      status: 200, headers: { "Content-Type": "application/json" },
    }));
    await expect(send()).resolves.toEqual(response);
    expect(fetch).toHaveBeenCalledTimes(1);
    const init = vi.mocked(fetch).mock.calls[0][1]!;
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual(body);
    expect(init.credentials).toBe("include");
  });
  it.each(commands)("preserves $name rejection without retrying the mutation", async ({ send }) => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({
      type: "legal_hold_stale", status: 409, detail: "The hold changed. Reload before issuing a new command.",
    }), { status: 409, headers: { "Content-Type": "application/problem+json" } }));
    await expect(send()).rejects.toMatchObject({ status: 409, problemType: "legal_hold_stale" });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
