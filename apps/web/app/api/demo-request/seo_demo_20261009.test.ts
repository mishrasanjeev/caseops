// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST } from "./route";

const id = "94112f70-d234-4dbd-8d09-e97a0b49c6a4";
const payload = { contact_name: "Demo Advocate", contact_email: "demo@example.com", company_name: null,
  role: "solo_advocate", segment: "solo", intent: "pilot", source: "solo_lawyers", notes: null,
  selected_plan: null, idempotency_key: id, privacy_notice_version: "2026-10-09" };
const request = (body: unknown = payload) => new Request("http://localhost/api/demo-request", {
  method: "POST", body: JSON.stringify(body), headers: { "content-type": "application/json", cookie: "private=do-not-forward", referer: "https://example.com/private?secret=redact" },
});

describe("seo_demo_20261009 durable proxy", () => {
  const fetchMock = vi.fn();
  beforeEach(() => vi.stubGlobal("fetch", fetchMock.mockReset()));
  afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });
  it("uses the server-owned origin and preserves only the no-paid marker across the proxy", async () => {
    vi.stubEnv("CASEOPS_API_BASE_URL", "http://api:8000");
    fetchMock.mockResolvedValue(Response.json({ id, status: "demo_requested" }));
    const incoming = request();
    incoming.headers.set("X-CaseOps-Automated-Test", "no-paid-providers");
    incoming.headers.set("Authorization", "Bearer never-forward");
    expect((await POST(incoming)).status).toBe(202);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api:8000/api/billing/enrollments/demo-request");
    expect(init.headers).toEqual({ "Content-Type": "application/json", "X-CaseOps-Automated-Test": "no-paid-providers" });
  });
  it("acknowledges only a matching saved enrollment and forwards minimal fields", async () => {
    fetchMock.mockResolvedValue(Response.json({ id, status: "demo_requested" }));
    const response = await POST(request());
    expect(response.status).toBe(202);
    expect(await response.json()).toEqual({ accepted: true, id, status: "demo_requested" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/billing/enrollments/demo-request");
    expect(JSON.parse(init.body)).toEqual(payload);
    expect(init.headers).toEqual({ "Content-Type": "application/json" });
    expect(init).toMatchObject({ cache: "no-store", credentials: "omit", redirect: "error" });
  });
  it.each([400, 409, 422, 429, 500, 503])("does not acknowledge upstream status %s or echo private errors", async (status) => {
    fetchMock.mockResolvedValue(Response.json({ error: "demo@example.com private provider error" }, { status }));
    const response = await POST(request());
    expect(response.status).toBe(status >= 500 ? 503 : status);
    expect(await response.text()).not.toContain("demo@example.com");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
  it.each([{ id: "wrong", status: "demo_requested" }, { id: crypto.randomUUID(), status: "demo_requested" }, { id, status: "queued" }])("rejects unproven acknowledgment %j", async (body) => {
    fetchMock.mockResolvedValue(Response.json(body));
    expect((await POST(request())).status).toBe(503);
  });
  it("retains ambiguous timeout as unconfirmed, with no automatic retry", async () => {
    fetchMock.mockRejectedValue(new DOMException("timeout", "TimeoutError"));
    expect((await POST(request())).status).toBe(503);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
  it.each([{ role: "owner" }, { source: "https://example.com?secret=redact" }, { idempotency_key: undefined }, { privacy_notice_version: undefined }, { referrer: "secret" }, { utm_json: { query: "secret" } }])("rejects invalid or tracking payload %j before transport", async (change) => {
    expect((await POST(request({ ...payload, ...change }))).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
