import { beforeEach, describe, expect, it, vi } from "vitest";

const { call } = vi.hoisted(() => ({ call: vi.fn() }));
vi.mock("./client", () => ({
  apiRequest: call, apiBlobRequest: vi.fn(), fetchWithTimeout: vi.fn(), getCsrfHeaders: vi.fn(),
}));
import {
  fetchEveryIpDocket, fetchIpForeignAssociateInstructions, fetchIpRecordals, fetchMadridRecords,
  ipListRows, nextIpListOffset,
} from "./endpoints";

/** A tenant whose history is far larger than one page, as the production QA tenant is. */
const TOTAL = 5000;

/** A server that serves `TOTAL` rows by limit and offset, as the IP list routes do. */
function serveOffsetPages(prefix: string) {
  call.mockImplementation(async (path: string) => {
    const url = new URL(path, "http://api.test");
    const limit = Number(url.searchParams.get("limit"));
    const offset = Number(url.searchParams.get("offset"));
    const count = Math.max(0, Math.min(limit, TOTAL - offset));
    return {
      items: Array.from({ length: count }, (_, index) => ({ id: `${prefix}-${offset + index}` })),
      total: TOTAL,
      limit,
      offset,
    };
  });
}

function requested(): URL[] {
  return call.mock.calls.map(([path]) => new URL(String(path), "http://api.test"));
}

describe("IP offset-paged lists read one page per request", () => {
  beforeEach(() => {
    call.mockReset();
  });

  it("renders from one request however large the tenant's history is", async () => {
    serveOffsetPages("recordal");
    const page = await fetchIpRecordals({ status: "draft" });
    expect(call).toHaveBeenCalledTimes(1);
    expect(page.items).toHaveLength(100);
    expect(page.total).toBe(TOTAL);
    const [url] = requested();
    expect(url.pathname).toBe("/api/ip/recordals");
    expect([url.searchParams.get("limit"), url.searchParams.get("offset")]).toEqual(["100", "0"]);
    expect(url.searchParams.get("status")).toBe("draft");
  });

  it("reads the requested later page with its filters for each list", async () => {
    serveOffsetPages("instruction");
    const instructions = await fetchIpForeignAssociateInstructions({ docketId: "docket-1" }, { offset: 200 });
    expect(instructions.items[0]?.id).toBe("instruction-200");
    serveOffsetPages("madrid");
    const madrid = await fetchMadridRecords({ recordKind: "international_designation" }, { offset: 100 });
    expect(madrid.items[0]?.id).toBe("madrid-100");
    expect(requested().map((url) => [url.pathname, url.searchParams.get("offset")])).toEqual([
      ["/api/ip/foreign-associate-instructions", "200"],
      ["/api/ip/international-registrations", "100"],
    ]);
    expect(requested()[0].searchParams.get("docket_id")).toBe("docket-1");
    expect(requested()[1].searchParams.get("record_kind")).toBe("international_designation");
  });

  it("forwards the query's abort signal", async () => {
    serveOffsetPages("madrid");
    const controller = new AbortController();
    await fetchMadridRecords(undefined, { signal: controller.signal });
    expect(call.mock.calls[0]?.[1]?.signal).toBe(controller.signal);
  });

  it("offers Load more until the server's total is reached, so every row stays reachable", () => {
    const page = (offset: number, count: number, total: number) => ({
      items: Array.from({ length: count }, (_, index) => ({ id: `row-${offset + index}` })),
      total,
      limit: 100,
      offset,
    });
    expect(nextIpListOffset(page(0, 100, 230))).toBe(100);
    expect(nextIpListOffset(page(100, 100, 230))).toBe(200);
    expect(nextIpListOffset(page(200, 30, 230))).toBeUndefined();
    expect(nextIpListOffset(page(0, 2, 2))).toBeUndefined();
    // An empty page ends paging even if the count grew meanwhile.
    expect(nextIpListOffset(page(300, 0, 400))).toBeUndefined();
  });

  it("shows a record updated between two reads once", () => {
    const first = { items: [{ id: "a" }, { id: "b" }], total: 3, limit: 2, offset: 0 };
    // "b" was updated after page one was read, so newest-change-first order
    // served it again on the next page.
    const second = { items: [{ id: "b" }, { id: "c" }], total: 3, limit: 2, offset: 2 };
    expect(ipListRows([first, second]).map((row) => row.id)).toEqual(["a", "b", "c"]);
    expect(ipListRows(undefined)).toEqual([]);
  });
});

describe("every IP docket follows the keyset cursor", () => {
  beforeEach(() => {
    call.mockReset();
  });

  function page(ids: string[], next: string | null, total: number) {
    return { dockets: ids.map((id) => ({ id })), count: ids.length, has_more: next !== null, next_cursor: next, total_count: total };
  }

  it("returns docket 201 onwards for the recordal title check", async () => {
    const ids = Array.from({ length: 230 }, (_, index) => `docket-${index}`);
    call
      .mockResolvedValueOnce(page(ids.slice(0, 200), "c1", 230))
      .mockResolvedValueOnce(page(ids.slice(200), null, 230));
    const every = await fetchEveryIpDocket();
    expect(every.map((docket) => docket.id)).toEqual(ids);
    expect(requested().map((url) => [url.searchParams.get("limit"), url.searchParams.get("cursor")])).toEqual([
      ["200", null],
      ["200", "c1"],
    ]);
  });

  it("reads again, then fails visibly, when dockets keep moving mid-read", async () => {
    call.mockResolvedValue(page(["docket-0"], null, 2));
    await expect(fetchEveryIpDocket()).rejects.toThrow(/changed while it was loading/);
    expect(call).toHaveBeenCalledTimes(2);
  });
});
