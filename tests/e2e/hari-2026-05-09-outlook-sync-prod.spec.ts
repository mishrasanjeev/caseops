/**
 * BUG-039 (Hari 2026-05-09) — Outlook bounded bulk sync, prod
 * verification.
 *
 * Strategy:
 *   1. Visit `/app/calendar` as the QA bot. Confirm the Outlook
 *      panel renders and that the "Sync visible range to Outlook"
 *      button is NOT present (the QA tenant has no Outlook
 *      connection wired by default; the UI must mirror the
 *      disconnected API state).
 *   2. Hit POST /api/calendar/sync/outlook directly — expect 409
 *      with an actionable detail.
 *
 * No QA-tenant mutation: GET on /app/calendar is read-only; POST on
 * /sync/outlook returns 409 before any DB write because the
 * connection guard fires first. Driving a happy-path roundtrip
 * against Microsoft Graph requires a real OAuth flow we do not
 * commit credentials for; the backend pytest covers the upsert
 * path against the StubOutlookProvider fixture.
 */
import { expect, test } from "@playwright/test";

const PROD_BASE_URL =
  (process.env.PROD_BASE_URL ?? "").trim() || "https://caseops.ai";
const PROD_API_BASE_URL =
  (process.env.PROD_API_BASE_URL ?? "").trim() || "https://api.caseops.ai";

test.describe("BUG-039 Hari 2026-05-09 — Outlook bulk sync prod verification", () => {
  test.setTimeout(60_000);

  test("BUG-039 (UI, prod): /app/calendar renders the Outlook panel and hides sync button without a connection", async ({
    page,
  }) => {
    await page.goto(`${PROD_BASE_URL}/app/calendar`);
    await expect(page.getByTestId("calendar-outlook-panel")).toBeVisible();
    // QA bot tenant has no Outlook connection wired -> the bulk sync
    // button must not render. Either Connect button is visible (if
    // capability allows) or nothing is — but the sync button never.
    await expect(
      page.getByTestId("calendar-outlook-sync-range"),
    ).toHaveCount(0);
  });

  test("BUG-039 (API, prod): POST /api/calendar/sync/outlook is mounted and returns 409 without an Outlook connection", async ({
    page,
  }) => {
    const cookies = await page.context().cookies();
    const cookieHeader = cookies
      .filter((c) => c.domain.includes("caseops.ai"))
      .map((c) => `${c.name}=${c.value}`)
      .join("; ");
    const csrf =
      cookies.find((c) => c.name === "caseops_csrf")?.value ?? "";

    const resp = await page.context().request.post(
      `${PROD_API_BASE_URL}/api/calendar/sync/outlook`,
      {
        headers: {
          Cookie: cookieHeader,
          "Content-Type": "application/json",
          "X-CSRF-Token": csrf,
          Accept: "application/json",
        },
        data: { from: "2026-05-01", to: "2026-05-31" },
      },
    );
    // Mounted -> not 404. Without a connection -> 409.
    expect(resp.status(), `expected 409, got ${resp.status()}: ${await resp.text()}`).toBe(409);
    const detail = (await resp.json()).detail as string;
    expect(detail.toLowerCase()).toMatch(/connect|outlook/);
  });
});
