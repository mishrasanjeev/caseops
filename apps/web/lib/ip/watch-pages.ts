import type { IpWatchHit, IpWatchProfile, IpWatchWorkspace } from "@/lib/api/endpoints";

/** The loaded watch pages as one workspace, with each list's server total. */
export type MergedWatchWorkspace = IpWatchWorkspace & {
  /** Another offset still holds rows of at least one list. */
  hasMore: boolean;
};

function unique<T extends { id: string }>(rows: T[]): T[] {
  const seen = new Map<string, T>();
  for (const row of rows) if (!seen.has(row.id)) seen.set(row.id, row);
  return [...seen.values()];
}

/**
 * Pages are fetched at offsets 0, limit, 2*limit, ... for every list at once.
 * Rows are de-duplicated by id (a list can shift between reads); totals and
 * runs come from the newest page read, so the "N of M" text uses one count.
 */
export function mergeWatchPages(pages: IpWatchWorkspace[]): MergedWatchWorkspace | undefined {
  if (pages.length === 0) return undefined;
  const latest = pages[pages.length - 1];
  const profiles = unique(pages.flatMap((page) => page.profiles));
  return {
    ...latest,
    offset: 0,
    profiles,
    hits: unique(pages.flatMap((page) => page.hits)),
    hit_profiles: unique(pages.flatMap((page) => page.hit_profiles)),
    publications: unique(pages.flatMap((page) => page.publications)),
    handoffs: unique(pages.flatMap((page) => page.handoffs)),
    ingestion_runs: pages[0].ingestion_runs,
    hasMore: nextWatchOffset(pages) !== undefined,
  };
}

/** Rows a mutation's response just returned, as the server stored them. */
export type ConfirmedWatchRows = { profile?: IpWatchProfile; hit?: IpWatchHit };

/**
 * Writes rows the server just confirmed into every loaded page. A workspace
 * read takes seconds on a large tenant, so without this the screen kept the
 * old status (and the old version a next action must send) until the slower
 * refetch returned (BUG-014: "paused" stayed "active" for about 12 s).
 */
export function withConfirmedRows(pages: IpWatchWorkspace[], rows: ConfirmedWatchRows): IpWatchWorkspace[] {
  const swap = <T extends { id: string }>(list: T[], row: T | undefined) =>
    row ? list.map((item) => (item.id === row.id ? row : item)) : list;
  return pages.map((page) => ({
    ...page,
    profiles: swap(page.profiles, rows.profile),
    hit_profiles: swap(page.hit_profiles, rows.profile),
    hits: swap(page.hits, rows.hit),
  }));
}

/** The next offset to read, or undefined when every list is read to its total. */
export function nextWatchOffset(pages: IpWatchWorkspace[]): number | undefined {
  if (pages.length === 0) return 0;
  const latest = pages[pages.length - 1];
  const next = pages.length * latest.limit;
  const largest = Math.max(latest.profile_total, latest.hit_total, latest.publication_total);
  return next < largest ? next : undefined;
}

/** "Showing 100 of 340 hits." or "340 hits." for a list the reader has loaded. */
export function watchCountText(loaded: number, total: number, noun: [string, string]): string {
  const word = (count: number) => (count === 1 ? noun[0] : noun[1]);
  const shown = Math.min(loaded, total);
  return shown < total
    ? `Showing ${shown.toLocaleString("en-IN")} of ${total.toLocaleString("en-IN")} ${word(total)}.`
    : `${total.toLocaleString("en-IN")} ${word(total)}.`;
}
