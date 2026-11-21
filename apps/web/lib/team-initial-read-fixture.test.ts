import type { APIResponse, Page, Route } from "@playwright/test";
import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchInitialTeamList, holdInitialTeamList } from "../../../tests/e2e/support/team-initial-read";

const origin = "https://api.caseops.ai";
const list = `${origin}/api/teams/`;
const bytes = Buffer.from('{\r\n"team_scoping_enabled":true,"teams":[{"name":"अदालत","id":"PRIVATE-TEAM"}]}');

function fixture() {
  const request = {
    url: vi.fn(() => list), method: vi.fn(() => "GET"),
    headers: vi.fn(() => ({ Authorization: "Bearer PRIVATE", Cookie: "session=PRIVATE",
      "x-caseops-automated-test": "wrong", "X-CaseOps-Automated-Test": "also-wrong", "If-None-Match": "tag" })),
  };
  const response = {
    status: vi.fn(() => 200),
    headers: vi.fn(() => ({ "content-type": "application/json; charset=utf-8", "content-encoding": "gzip",
      "content-length": "999", "access-control-allow-origin": "https://caseops.ai" })),
    body: vi.fn(async () => bytes),
  };
  const fetch = vi.fn(async (_options: Parameters<Route["fetch"]>[0]) => response as unknown as APIResponse);
  const route = { request: () => request, fetch, continue: vi.fn(async () => {}),
    fulfill: vi.fn(async () => {}), abort: vi.fn(async () => {}) };
  return { request, response, fetch, route, nativeRoute: route as unknown as Route };
}

function pageFixture() {
  let handler!: (route: Route) => Promise<void>;
  const page = {
    route: vi.fn(async (_url: string, received: (route: Route) => Promise<void>) => { handler = received; }),
    unroute: vi.fn(async () => {}),
  };
  return { page, nativePage: page as unknown as Page, invoke: (route: Route) => handler(route) };
}

afterEach(() => { vi.useRealTimers(); });

describe("real initial Teams response fixture", () => {
  it("owns the no-paid marker and preserves authentication, request defaults and exact UTF-8 bytes", async () => {
    const f = fixture();
    const result = await fetchInitialTeamList(f.nativeRoute, origin);
    expect(f.fetch).toHaveBeenCalledExactlyOnceWith({
      headers: { Authorization: "Bearer PRIVATE", Cookie: "session=PRIVATE", "If-None-Match": "tag",
        "X-CaseOps-Automated-Test": "no-paid-providers" },
      timeout: 30_000, maxRedirects: 0, maxRetries: 0,
    });
    expect(result.response).toBe(f.response);
    expect(result.body).toBe(bytes);
    expect(result.body.toString("utf8")).toContain("अदालत");
    expect(result.body.includes(Buffer.from("\r\n"))).toBe(true);
    expect(f.response.body).toHaveBeenCalledTimes(1);
    expect(f.request.headers()).toHaveProperty("x-caseops-automated-test", "wrong");
  });

  it("does not decode failed HTTP responses or retry their marked request", async () => {
    for (const status of [401, 503]) {
      const f = fixture(); f.response.status.mockReturnValue(status);
      await expect(fetchInitialTeamList(f.nativeRoute, origin)).rejects.toThrow("Team initial list snapshot response was refused.");
      expect(f.fetch).toHaveBeenCalledTimes(1);
      expect(f.fetch.mock.calls[0][0]).toMatchObject({ headers: { "X-CaseOps-Automated-Test": "no-paid-providers" }, maxRetries: 0 });
      expect(f.response.body).not.toHaveBeenCalled();
    }
  });

  it("preserves a transport error without retrying or manufacturing response evidence", async () => {
    const f = fixture(); const refusal = new Error("PRIVATE transport detail"); f.fetch.mockRejectedValue(refusal);
    await expect(fetchInitialTeamList(f.nativeRoute, origin)).rejects.toBe(refusal);
    expect(f.fetch).toHaveBeenCalledTimes(1);
    expect(f.fetch.mock.calls[0][0]).toMatchObject({ headers: { "X-CaseOps-Automated-Test": "no-paid-providers" }, maxRedirects: 0, maxRetries: 0 });
    expect(f.response.body).not.toHaveBeenCalled();
  });

  it("refuses foreign origins, credentials, queries, wrong paths and writes before I/O", async () => {
    for (const [target, admitted, method] of [
      ["https://foreign.invalid/api/teams/", "https://foreign.invalid", "GET"],
      ["https://user:secret@api.caseops.ai/api/teams/", "https://user:secret@api.caseops.ai", "GET"],
      [`${list}?token=PRIVATE`, origin, "GET"],
      [`${origin}/api/teams/PRIVATE/members`, origin, "GET"],
      [list, origin, "POST"],
      [list, "http://api.caseops.ai", "GET"],
    ]) {
      const f = fixture(); f.request.url.mockReturnValue(target); f.request.method.mockReturnValue(method);
      await expect(fetchInitialTeamList(f.nativeRoute, admitted)).rejects.toThrow(/Team snapshot requires/);
      expect(f.fetch).not.toHaveBeenCalled(); expect(f.response.body).not.toHaveBeenCalled();
    }
  });

  it("rejects invalid UTF-8, invalid list shapes and oversized buffered fixture payloads", async () => {
    for (const body of [Buffer.from([0xff]), Buffer.from('{"teams":[]}'), Buffer.alloc(4_194_305)]) {
      const f = fixture(); f.response.body.mockResolvedValue(body);
      await expect(fetchInitialTeamList(f.nativeRoute, origin)).rejects.toThrow();
      expect(f.fetch).toHaveBeenCalledTimes(1); expect(f.response.body).toHaveBeenCalledTimes(1);
    }
  });

  it("holds one exact response, lets later reads continue, and removes only its own route once", async () => {
    const p = pageFixture(); const f = fixture();
    const held = await holdInitialTeamList(p.nativePage, origin);
    try {
      const pending = p.invoke(f.nativeRoute);
      await held.ready(); expect(f.route.fulfill).not.toHaveBeenCalled();
      const later = fixture(); await p.invoke(later.nativeRoute);
      expect(later.route.continue).toHaveBeenCalledTimes(1); expect(later.fetch).not.toHaveBeenCalled();
      await held.release(); await pending;
      expect(f.route.fulfill).toHaveBeenCalledExactlyOnceWith({ response: f.response, body: bytes,
        headers: { "content-type": "application/json; charset=utf-8", "access-control-allow-origin": "https://caseops.ai" } });
      await held.dispose(); await held.dispose();
      expect(p.page.unroute).toHaveBeenCalledExactlyOnceWith(list, p.page.route.mock.calls[0][1]);
    } finally { await held.dispose(); }
  });

  it("surfaces an early request failure before reporting a missing snapshot", async () => {
    const p = pageFixture(); const f = fixture(); const refusal = new Error("Original request failed");
    f.fetch.mockRejectedValue(refusal);
    const held = await holdInitialTeamList(p.nativePage, origin);
    await p.invoke(f.nativeRoute);
    await expect(held.ready()).rejects.toBe(refusal);
    await expect(held.dispose()).rejects.toBe(refusal);
    expect(f.route.abort).toHaveBeenCalledExactlyOnceWith("failed");
    expect(p.page.unroute).toHaveBeenCalledTimes(1);
  });

  it("keeps the readiness deadline at fifteen seconds and clears its timer", async () => {
    vi.useFakeTimers(); const p = pageFixture();
    const held = await holdInitialTeamList(p.nativePage, origin);
    let settled = false;
    const waiting = held.ready(); void waiting.finally(() => { settled = true; }).catch(() => {});
    const refused = expect(waiting).rejects.toThrow("Team initial list snapshot was not captured.");
    await vi.advanceTimersByTimeAsync(14_999); expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(1); await refused;
    expect(vi.getTimerCount()).toBe(0); await held.dispose();
    expect(p.page.unroute).toHaveBeenCalledTimes(1);
  });

  it("retains independent snapshot and unroute failures", async () => {
    const p = pageFixture(); const f = fixture(); const original = new Error("Request failed");
    const cleanup = new Error("Unroute failed"); f.fetch.mockRejectedValue(original); p.page.unroute.mockRejectedValue(cleanup);
    const held = await holdInitialTeamList(p.nativePage, origin);
    await p.invoke(f.nativeRoute); await expect(held.ready()).rejects.toBe(original);
    const failure = await held.dispose().catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(AggregateError);
    expect((failure as AggregateError).errors).toEqual([original, cleanup]);
    expect(p.page.unroute).toHaveBeenCalledTimes(1);
  });
});
