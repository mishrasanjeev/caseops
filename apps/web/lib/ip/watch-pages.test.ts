// @vitest-environment node
import { describe, expect, it } from "vitest";

import type { IpWatchWorkspace } from "@/lib/api/endpoints";
import { mergeWatchPages, nextWatchOffset, watchCountText } from "@/lib/ip/watch-pages";

function page(offset: number, ids: { profiles: string[]; hits: string[]; publications: string[] }, totals = { profile: 12, hit: 12, publication: 3 }): IpWatchWorkspace {
  return {
    limit: 5,
    offset,
    profiles: ids.profiles.map((id) => ({ id }) as never),
    profile_total: totals.profile,
    paused_profile_total: 1,
    hits: ids.hits.map((id) => ({ id }) as never),
    hit_total: totals.hit,
    hit_profiles: [],
    publications: ids.publications.map((id) => ({ id }) as never),
    publication_total: totals.publication,
    ingestion_runs: [{ id: `run-${offset}` } as never],
    ingestion_run_total: 40,
    ingestion_run_limit: 20,
    handoffs: [],
    intake_profile_count: 12,
  };
}

const range = (prefix: string, from: number, to: number) =>
  Array.from({ length: to - from }, (_, index) => `${prefix}${from + index}`);

describe("watch workspace pages", () => {
  it("reads three pages to the largest total, across two page boundaries", () => {
    const pages = [page(0, { profiles: range("p", 0, 5), hits: range("h", 0, 5), publications: range("e", 0, 3) })];
    expect(nextWatchOffset(pages)).toBe(5);
    pages.push(page(5, { profiles: range("p", 5, 10), hits: range("h", 5, 10), publications: [] }));
    expect(nextWatchOffset(pages)).toBe(10);
    // A row that shifted onto the next page between reads is listed once.
    pages.push(page(10, { profiles: ["p9", "p10", "p11"], hits: range("h", 10, 12), publications: [] }));
    expect(nextWatchOffset(pages)).toBeUndefined();

    const merged = mergeWatchPages(pages)!;
    expect(merged.hasMore).toBe(false);
    expect(merged.profiles.map((row) => row.id)).toEqual(range("p", 0, 12));
    expect(merged.hits.map((row) => row.id)).toEqual(range("h", 0, 12));
    expect(merged.hits[merged.hits.length - 1].id).toBe("h11");
    expect(merged.publications).toHaveLength(3);
    expect(merged.ingestion_runs.map((row) => row.id)).toEqual(["run-0"]);
  });

  it("a one-page reader would stop short: the first page alone has more", () => {
    const first = mergeWatchPages([page(0, { profiles: range("p", 0, 5), hits: range("h", 0, 5), publications: [] })])!;
    expect(first.hasMore).toBe(true);
    expect(watchCountText(first.hits.length, first.hit_total, ["hit", "hits"])).toBe("Showing 5 of 12 hits.");
  });

  it("states complete lists without a cap", () => {
    expect(watchCountText(12, 12, ["hit", "hits"])).toBe("12 hits.");
    expect(watchCountText(1, 1, ["profile", "profiles"])).toBe("1 profile.");
    expect(watchCountText(0, 0, ["hit", "hits"])).toBe("0 hits.");
    expect(mergeWatchPages([])).toBeUndefined();
  });
});
