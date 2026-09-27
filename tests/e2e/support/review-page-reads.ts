import { expect, type Page, type Request } from "@playwright/test";

/**
 * Record the Intelligent Review page's API reads from navigation until it settles.
 *
 * Each Cloud Run API instance serves one request and four stay warm. On
 * 2026-09-27 the page opened with five concurrent reads and the fifth waited
 * 32 seconds for a new instance (prod-verify run 36291638337). First load may
 * keep at most two reads in flight and loads IP dockets only when their tab is
 * opened. Callers select a terminal review inside the bounded history, which
 * already carries that complete record, so no single-review read is allowed.
 */
export async function expectBoundedReviewPageLoad(
  page: Page,
  options: {
    apiOrigin: string;
    navigate: () => Promise<unknown>;
  },
) {
  const apiOrigin = options.apiOrigin.replace(/\/+$/, "");
  const inFlight = new Set<Request>();
  const reads: string[] = [];
  let maxInFlight = 0;
  const isApiRead = (request: Request) =>
    request.method() === "GET" && request.url().startsWith(`${apiOrigin}/api/`);
  const started = (request: Request) => {
    if (!isApiRead(request)) return;
    const url = new URL(request.url());
    reads.push(`${url.pathname}${url.search}`);
    inFlight.add(request);
    maxInFlight = Math.max(maxInFlight, inFlight.size);
  };
  const ended = (request: Request) => {
    inFlight.delete(request);
  };
  page.on("request", started);
  page.on("requestfinished", ended);
  page.on("requestfailed", ended);
  try {
    await options.navigate();
    await expect(page.getByTestId("intelligent-review-detail")).toBeVisible();
    // Matter targets load after the frozen reports; wait for both to settle.
    await expect(page.getByRole("combobox", { name: "Matter target" })).toContainText(
      "Choose a Matter",
    );
    await expect.poll(() => inFlight.size).toBe(0);
  } finally {
    page.off("request", started);
    page.off("requestfinished", ended);
    page.off("requestfailed", ended);
  }
  const summary = JSON.stringify({ maxInFlight, reads });
  expect(maxInFlight, summary).toBeLessThanOrEqual(2);
  expect(reads.filter((read) => read.startsWith("/api/research/reviews?")).length, summary)
    .toBeGreaterThanOrEqual(1);
  expect(reads.filter((read) => /^\/api\/research\/reviews\/[^/?]+/.test(read)), summary)
    .toEqual([]);
  expect(reads.filter((read) => read.startsWith("/api/ip/portfolio")), summary).toEqual([]);
  return { maxInFlight, reads };
}
