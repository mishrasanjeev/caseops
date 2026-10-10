// @vitest-environment node
import { randomBytes, createHmac } from "node:crypto";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DEMO_TARGET, forwardedRateHeaders, READINESS_TARGET, verifiedEdgeIP } from "./rate-identity";
import { POST } from "@/app/api/demo-request/route";
import { GET } from "@/app/api/demo-readiness/route";
vi.mock("server-only", () => ({}));

let purposeKey: string;
const fetchMock = vi.fn();
const sha = "9".repeat(40);
function claims(ip = "2001:0DB8::1") {
  return new Headers({ "x-caseops-edge-client-ip": ip, "x-caseops-edge-attestation": purposeKey });
}
beforeEach(() => {
  purposeKey = randomBytes(32).toString("hex");
  vi.stubEnv("CASEOPS_RATE_IDENTITY_EDGE_SECRET", purposeKey);
  vi.stubEnv("CASEOPS_RATE_IDENTITY_REQUIRED", "true");
  vi.stubEnv("CASEOPS_RATE_IDENTITY_EDGE_HTTPS", "true");
  vi.stubEnv("CASEOPS_RELEASE_SHA", sha);
  vi.stubEnv("CASEOPS_API_BASE_URL", "http://isolated-api");
  vi.stubGlobal("fetch", fetchMock.mockReset());
});
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.restoreAllMocks(); vi.useRealTimers(); });

it.each(["192.0.2.1", "2001:0DB8::1", "::ffff:192.0.2.1"])("signs only verified canonical IP %s", (ip) => {
  vi.spyOn(Date, "now").mockReturnValue(1791561600000);
  const headers = forwardedRateHeaders(claims(ip), "GET", READINESS_TARGET);
  const canonical = ip === "2001:0DB8::1" ? "2001:db8::1" : ip === "::ffff:192.0.2.1" ? "192.0.2.1" : ip;
  expect(headers["x-caseops-rate-client-ip"]).toBe(canonical);
  expect(headers["x-caseops-rate-signature"]).toBe(createHmac("sha256", purposeKey)
    .update(`caseops-rate-v1\nGET\n${READINESS_TARGET}\n${canonical}\n1791561600`).digest("hex"));
  expect(Object.keys(headers)).toHaveLength(3);
});
it.each(["", "192.0.2.1,192.0.2.2", "256.0.0.1", "fe80::1%eth0", "[::1]", "x".repeat(4096)])(
  "rejects malformed edge IP before signing (%s)", (ip) => expect(() => verifiedEdgeIP(claims(ip))).toThrow());
it.each(["x-caseops-edge-client-ip", "x-caseops-edge-attestation"])("rejects duplicate %s", (name) => {
  const headers = claims(); headers.append(name, headers.get(name)!);
  expect(() => verifiedEdgeIP(headers)).toThrow();
});
it.each(["x-caseops-rate-client-ip", "x-caseops-rate-timestamp", "x-caseops-rate-signature"])(
  "rejects caller-provided forwarding authority %s", (name) => {
    const headers = claims(); headers.set(name, "forged"); expect(() => verifiedEdgeIP(headers)).toThrow();
  });
it("never signs a raw XFF claim or accepts direct entry without attestation", () => {
  expect(() => forwardedRateHeaders(new Headers({ "x-forwarded-for": "192.0.2.1", "x-real-ip": "::1" }), "POST", DEMO_TARGET)).toThrow();
  const headers = claims(); headers.set("x-caseops-edge-attestation", randomBytes(32).toString("hex"));
  expect(() => verifiedEdgeIP(headers)).toThrow();
});
it.each([["POST", READINESS_TARGET], ["GET", DEMO_TARGET], ["POST", "/api/auth/login"]])(
  "will not sign an arbitrary target %s %s", (method, path) => expect(() => forwardedRateHeaders(claims(), method, path)).toThrow());
it("preserves no-paid isolation and drops raw headers, token and cookie on demo proxy", async () => {
  const id = crypto.randomUUID();
  fetchMock.mockResolvedValue(Response.json({ id, status: "demo_requested" }));
  const headers = claims(); headers.set("content-type", "application/json");
  headers.set("x-forwarded-for", "198.51.100.200"); headers.set("x-real-ip", "198.51.100.201");
  headers.set("cookie", "private=never-forward"); headers.set("authorization", "Bearer never-forward");
  headers.set("x-caseops-automated-test", "no-paid-providers");
  const response = await POST(new Request("http://web/api/demo-request", { method: "POST", headers,
    body: JSON.stringify({ contact_name: "Offline", contact_email: "offline@example.com", role: "solo_advocate",
      segment: "solo", intent: "pilot", source: "solo_lawyers", idempotency_key: id, privacy_notice_version: "2026-10-09" }) }));
  expect(response.status).toBe(202);
  const sent = fetchMock.mock.calls[0][1].headers;
  expect(sent["X-CaseOps-Automated-Test"]).toBe("no-paid-providers");
  expect(sent["x-caseops-rate-client-ip"]).toBe("2001:db8::1");
  expect(JSON.stringify(sent)).not.toContain(purposeKey);
  for (const name of ["x-forwarded-for", "x-real-ip", "cookie", "authorization", "x-caseops-edge-attestation"]) expect(sent[name]).toBeUndefined();
});
it("does not transport malformed or missing authority", async () => {
  expect((await GET(new Request("http://web/api/demo-readiness"))).status).toBe(503);
  expect(fetchMock).not.toHaveBeenCalled();
});
it("readiness proves signed GET provenance and reveals only readiness/release", async () => {
  fetchMock.mockResolvedValue(Response.json({ ready: true, provenance: "web-forward", release_sha: sha }));
  const response = await GET(new Request("http://web/api/demo-readiness", { headers: claims() }));
  expect(response.status).toBe(200);
  expect(await response.json()).toEqual({ ready: true, provenance: "web-forward", release_sha: sha });
  expect(fetchMock.mock.calls[0][0]).toBe(`http://isolated-api${READINESS_TARGET}`);
  expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "GET", credentials: "omit", redirect: "error", cache: "no-store" });
});
it.each([{ ready: true, provenance: "edge", release_sha: sha }, { ready: true, provenance: "web-forward", release_sha: "0".repeat(40) },
  { ready: true, provenance: "web-forward", release_sha: sha, ip: "192.0.2.1" }])("rejects unproven or identifying readiness %j", async (body) => {
  fetchMock.mockResolvedValue(Response.json(body));
  const response = await GET(new Request("http://web/api/demo-readiness", { headers: claims() }));
  expect(response.status).toBe(503);
  expect(Object.keys(await response.json()).sort()).toEqual(["provenance", "ready", "release_sha"]);
});
