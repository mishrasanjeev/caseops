import { beforeEach, describe, expect, it, vi } from "vitest";

const { call } = vi.hoisted(() => ({ call: vi.fn() }));
vi.mock("./client", () => ({
  apiRequest: call, apiBlobRequest: vi.fn(), fetchWithTimeout: vi.fn(), getCsrfHeaders: vi.fn(),
}));
import {
  fetchEveryIpDocket, fetchIpForeignAssociateInstructions, fetchIpRecordals, fetchMadridRecords,
} from "./endpoints";

const TOTAL = 230;

/** A server that serves `TOTAL` rows 100 at a time, as the IP list routes do. */
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

describe("IP offset-paged lists read the whole population", () => {
  beforeEach(() => call.mockReset());

  it("returns recordal 101 onwards instead of stopping at the first page", async () => {
    serveOffsetPages("recordal");
    const page = await fetchIpRecordals({ status: "draft" });
    expect(page.total).toBe(TOTAL);
    expect(page.items).toHaveLength(TOTAL);
    expect(page.items.at(-1)?.id).toBe(`recordal-${TOTAL - 1}`);
    expect(requested().map((url) => url.searchParams.get("offset"))).toEqual(["0", "100", "200"]);
    // Filters travel with every page, not only the first.
    expect(requested().every((url) => url.pathname === "/api/ip/recordals")).toBe(true);
    expect(requested().every((url) => url.searchParams.get("status") === "draft")).toBe(true);
  });

  it("returns every foreign-associate instruction and every Madrid record", async () => {
    serveOffsetPages("instruction");
    const instructions = await fetchIpForeignAssociateInstructions({ docketId: "docket-1" });
    expect(instructions.items).toHaveLength(TOTAL);
    expect(requested().every((url) => url.searchParams.get("docket_id") === "docket-1")).toBe(true);

    call.mockReset();
    serveOffsetPages("madrid");
    const madrid = await fetchMadridRecords({ recordKind: "international_designation" });
    expect(madrid.items).toHaveLength(TOTAL);
    expect(requested()).toHaveLength(3);
    expect(requested().every((url) => url.pathname === "/api/ip/international-registrations")).toBe(true);
  });

  it("makes one request for a short list", async () => {
    call.mockResolvedValueOnce({ items: [{ id: "a" }, { id: "b" }], total: 2, limit: 100, offset: 0 });
    const short = await fetchIpRecordals();
    expect(short.items.map((row) => row.id)).toEqual(["a", "b"]);
    expect(call).toHaveBeenCalledTimes(1);
  });

  it("reads again when a record updated mid-read jumped back to page one", async () => {
    const first = Array.from({ length: 100 }, (_, index) => ({ id: `row-${index}` }));
    call
      .mockResolvedValueOnce({ items: first, total: 101, limit: 100, offset: 0 })
      // row-100 was updated after page one was read: newest-change-first order
      // moves it to offset 0, so offset 100 now holds row-99 again and row-100
      // is never served on this pass.
      .mockResolvedValueOnce({ items: [{ id: "row-99" }], total: 101, limit: 100, offset: 100 })
      .mockResolvedValueOnce({ items: [{ id: "row-100" }, ...first.slice(0, 99)], total: 101, limit: 100, offset: 0 })
      .mockResolvedValueOnce({ items: [{ id: "row-99" }], total: 101, limit: 100, offset: 100 });
    const moved = await fetchIpRecordals();
    expect(call).toHaveBeenCalledTimes(4);
    expect(moved.items).toHaveLength(101);
    expect(new Set(moved.items.map((row) => row.id)).size).toBe(101);
    expect(moved.items.some((row) => row.id === "row-100")).toBe(true);
  });

  it("fails instead of returning a short list when the list keeps changing", async () => {
    const first = Array.from({ length: 100 }, (_, index) => ({ id: `row-${index}` }));
    call.mockImplementation(async (path: string) => {
      const offset = Number(new URL(path, "http://api.test").searchParams.get("offset"));
      return offset === 0
        ? { items: first, total: 101, limit: 100, offset }
        : { items: [{ id: "row-99" }], total: 101, limit: 100, offset };
    });
    await expect(fetchIpRecordals()).rejects.toThrow("This list changed while it was loading");
    expect(call).toHaveBeenCalledTimes(4);
  });

  it("forwards the query's abort signal to every page request", async () => {
    serveOffsetPages("madrid");
    const controller = new AbortController();
    await fetchMadridRecords(undefined, { signal: controller.signal });
    expect(call).toHaveBeenCalledTimes(3);
    expect(call.mock.calls.every(([, init]) => init?.signal === controller.signal)).toBe(true);
  });

  it("surfaces a failed later page instead of returning a silent partial list", async () => {
    call
      .mockResolvedValueOnce({
        items: Array.from({ length: 100 }, (_, index) => ({ id: `row-${index}` })),
        total: 150,
        limit: 100,
        offset: 0,
      })
      .mockRejectedValueOnce(new Error("Service unavailable"));
    await expect(fetchIpRecordals()).rejects.toThrow("Service unavailable");
  });
});

describe("every IP docket follows the keyset cursor", () => {
  beforeEach(() => call.mockReset());

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
