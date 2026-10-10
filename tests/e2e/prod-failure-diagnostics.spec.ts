import { test, expect } from "./support/prod-diagnostic-test";

test("sanitized failure evidence retains completed and failed browser transports without private payloads", async ({ page, baseURL, safeNetworkEvidence }) => {
  const target = new URL(baseURL ?? "http://127.0.0.1:3100");
  test.skip(!["127.0.0.1", "localhost", "[::1]"].includes(target.hostname), "Controlled network faults are loopback-only.");
  const privateMarker = "fixture-only-private-detail";
  const id = "5a5b40a1d7454dedb456398600bce991";
  const body = JSON.stringify({ type: "database_lock_timeout", request_id: id, detail: privateMarker, token: privateMarker });
  await page.route("**/api/auth/login?*", (route) => route.fulfill({
    status: 503,
    headers: { "content-type": "application/problem+json", "content-length": String(Buffer.byteLength(body)), "x-request-id": id },
    body,
  }));
  await page.route("**/api/auth/refresh?*", (route) => route.abort("connectionreset"));
  await page.goto("/sign-in");
  await page.evaluate(async (marker) => {
    await fetch(`/api/auth/login?token=${marker}`, { method: "POST", body: JSON.stringify({ password: marker }) });
    await fetch(`/api/auth/refresh?token=${marker}`, { method: "POST" }).catch(() => undefined);
  }, privateMarker);
  await expect.poll(() => safeNetworkEvidence.snapshot().records.filter((row) => row.route === "auth/session").length).toBe(2);
  const records = safeNetworkEvidence.snapshot().records.filter((row) => row.route === "auth/session");
  const completed = records.find((row) => row.outcome === "response_completed");
  expect(completed).toMatchObject({ status: 503, requestId: id, problemType: null, method: "POST" });
  expect(new Date(String(completed?.finishedAt)).getTime()).toBeGreaterThanOrEqual(new Date(String(completed?.startedAt)).getTime());
  expect(records.find((row) => row.outcome === "transport_failed")).toMatchObject({ failureCode: "net::ERR_CONNECTION_RESET" });
  const serialized = JSON.stringify(records);
  expect(serialized).not.toContain(privateMarker);
  expect(serialized).not.toContain("password");
  expect(serialized).not.toContain("https://");
  expect(serialized).not.toContain("/api/");
});
