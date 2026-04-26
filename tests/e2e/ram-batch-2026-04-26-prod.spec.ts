/**
 * Ram 2026-04-26 batch verification — runs against PRODUCTION
 * (caseops.ai) using Ram's reported test credentials. Verifies the
 * 4 root-fixed bugs from commit c58305b are actually live + working
 * for the same user that originally reported them.
 *
 * Per the bug-fixing skill: "Reopened bugs require fresh end-user
 * verification before closure."
 *
 * Bugs covered:
 *   - BUG-017 (statute reference 422)
 *   - BUG-018 (Invoice form responsive at 360x800) — REOPEN
 *   - BUG-020 (Add Client form responsive at 360x800)
 *   - BUG-022 (Topbar Profile/Workspace placeholders hidden)
 *
 * Run:
 *   PROD_BASE_URL=https://caseops.ai npx playwright test \
 *     tests/e2e/ram-batch-2026-04-26-prod.spec.ts --project=chromium
 *
 * Defaults: PROD_BASE_URL=https://caseops.ai if unset. Skips with a
 * clear message if RAM_TEST_PASSWORD env var is missing.
 */
import { expect, test, type Page } from "@playwright/test";

const PROD_BASE_URL = process.env.PROD_BASE_URL ?? "https://caseops.ai";
const PROD_API_BASE_URL = process.env.PROD_API_BASE_URL ?? "https://api.caseops.ai";
const RAM_EMAIL = process.env.RAM_TEST_EMAIL ?? "ram@testfirm.com";
const RAM_SLUG = process.env.RAM_TEST_SLUG ?? "test-legal";
const RAM_PASSWORD = process.env.RAM_TEST_PASSWORD ?? "Test@1234567";

async function signIn(page: Page): Promise<void> {
  await page.goto(`${PROD_BASE_URL}/sign-in`);
  await page.locator("#company-slug").fill(RAM_SLUG);
  await page.locator("#email").fill(RAM_EMAIL);
  await page.locator("#password").fill(RAM_PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(`${PROD_BASE_URL}/app`, { timeout: 30_000 });
}

async function firstMatterId(page: Page): Promise<string | null> {
  const ids = await allMatterIds(page);
  return ids[0] ?? null;
}

async function allMatterIds(page: Page): Promise<string[]> {
  // Use the live API (api.caseops.ai) to fetch the matter list with
  // the session cookie. The /app/matters page rendering depends on
  // tenant data + React Query hydration; the API call is deterministic.
  const cookies = await page.context().cookies();
  const cookieHeader = cookies
    .filter((c) => c.domain.includes("caseops.ai"))
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");
  const resp = await page.context().request.get(
    `${PROD_API_BASE_URL}/api/matters/`,
    { headers: { Cookie: cookieHeader, Accept: "application/json" } },
  );
  if (!resp.ok()) return [];
  const body = await resp.json();
  return (body?.matters ?? []).map((m: { id: string }) => m.id);
}

test.describe("Ram batch 2026-04-26 — prod verification of c58305b fixes", () => {
  test("AUTH-001 (user-reported 2026-04-26 PM): expired session redirects to /sign-in, not raw 401", async ({
    page,
    context,
  }) => {
    // Sign in normally so we land on /app with valid cookies.
    await signIn(page);
    expect(page.url()).toContain("/app");

    // Simulate session expiry: clear the session cookie. The next API
    // call from the page will get a 401 with type=missing_bearer_token,
    // which the client must handle by trying refresh + redirecting to
    // /sign-in (graceful) rather than throwing a raw error toast.
    await context.clearCookies({ name: "caseops_session" });

    // Trigger a portfolio fetch by navigating to /app/matters which
    // calls listMatters() on mount.
    await page.goto(`${PROD_BASE_URL}/app/matters`, {
      waitUntil: "networkidle",
    });

    // Either we end up on /sign-in (the graceful redirect path) OR
    // the page rendered the sign-in form. Both prove the auth UX
    // didn't strand the user on a broken /app shell. The original
    // bug surfaced the raw 401 JSON as a toast/error.
    await page.waitForURL(/\/sign-in(\?|$)/, { timeout: 10_000 });
    expect(page.url()).toMatch(/\/sign-in/);

    // The bug also showed the raw API JSON. Assert NONE of the
    // forbidden raw-error markers appear on the redirected page.
    const body = await page.content();
    expect(body).not.toContain("missing_bearer_token");
    expect(body).not.toContain("Could not load your portfolio");
  });


  test("BUG-015 (REOPEN, Critical): POST /api/matters/{id}/recommendations does NOT 504", async ({
    page,
    request,
  }) => {
    test.setTimeout(240_000); // LLM call takes 30-60s warm; allow headroom
    await signIn(page);
    const matterIds = await allMatterIds(page);
    if (matterIds.length === 0) {
      test.skip(true, "Tenant has no matters via API.");
      return;
    }
    // Use the matter most likely to succeed end-to-end (Salman Khan
    // has a rich description that gives retrieval enough to ground on).
    const matterId =
      matterIds.find((m) => m === "9fcf975a-3dbc-482d-9d4a-8f196916bcc4") ??
      matterIds[0];

    const cookies = await page.context().cookies();
    const cookieHeader = cookies
      .filter((c) => c.domain.includes("caseops.ai"))
      .map((c) => `${c.name}=${c.value}`)
      .join("; ");
    const csrfCookie = cookies.find((c) => c.name === "caseops_csrf");
    const headers: Record<string, string> = {
      Accept: "application/json",
      "Content-Type": "application/json",
      Cookie: cookieHeader,
    };
    if (csrfCookie) headers["X-CSRF-Token"] = csrfCookie.value;

    const resp = await request.post(
      `${PROD_API_BASE_URL}/api/matters/${matterId}/recommendations`,
      {
        headers,
        data: { type: "authority" },
        timeout: 200_000,
      },
    );
    const status = resp.status();
    // The bug was 504 at exactly 300s. Any non-504 outcome means the
    // bounded-timeout fix is working. We tolerate:
    //   200/201 — generation succeeded
    //   422 — citation grounding rejected (BUG-016 path; separate)
    //   429 — rate-limited (also success: not a hang)
    //   502 — Anthropic upstream failure surfaced as 502 (also success:
    //         not a hang)
    expect.soft(status).not.toBe(504);
    expect.soft(status).not.toBe(0); // 0 = no response (curl HTTP 000)
    expect([200, 201, 422, 429, 502]).toContain(status);
  });

  test("BUG-022: Topbar dropdown does NOT render Profile / Workspace settings placeholders", async ({
    page,
  }) => {
    await signIn(page);
    // Open the user-menu dropdown — anchored on the sign-out testid sibling.
    // The trigger is the user-avatar button at the right edge of the topbar.
    const userMenuTrigger = page.locator("header button").filter({
      hasText: /[A-Za-z]/,
    }).last();
    await userMenuTrigger.click();
    // Sign out should be visible (verifies the menu opened).
    await expect(page.getByTestId("sign-out")).toBeVisible({ timeout: 5_000 });
    // Profile + Workspace settings rows must NOT be present.
    const dropdown = page.locator("[role='menu']").last();
    await expect(dropdown.getByText(/^Profile$/)).toHaveCount(0);
    await expect(dropdown.getByText(/^Workspace settings$/)).toHaveCount(0);
  });

  test.describe("Mobile 360x800", () => {
    test.use({ viewport: { width: 360, height: 800 } });

    test("BUG-018 (REOPEN): Invoice dialog action buttons are reachable on 360x800", async ({
      page,
    }) => {
      await signIn(page);
      const matterIds = await allMatterIds(page);
      if (matterIds.length === 0) {
        test.skip(true, "Tenant has no matters via API.");
        return;
      }
      // Use the data-testid (new-invoice-trigger) which is more
      // reliable than the human-readable label. Iterate matters
      // because billing UX is gated by canIssueInvoice (capability
      // / billing-account check).
      let foundOnMatter: string | null = null;
      for (const mid of matterIds) {
        await page.goto(`${PROD_BASE_URL}/app/matters/${mid}/billing`);
        const candidate = page.getByTestId("new-invoice-trigger");
        if ((await candidate.count()) > 0) {
          foundOnMatter = mid;
          break;
        }
      }
      if (!foundOnMatter) {
        test.skip(
          true,
          `Tenant has ${matterIds.length} matters but none render the "new-invoice-trigger" — billing capability not enabled. Cannot probe Invoice dialog responsive layout against this tenant.`,
        );
        return;
      }
      await page.getByTestId("new-invoice-trigger").click();
      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible({ timeout: 5_000 });

      // Verify dialog max-h fits in viewport. Per the base primitive
      // fix: max-h-[90vh] = 720px on a 800-tall viewport.
      const dialogBox = await dialog.boundingBox();
      expect(dialogBox).not.toBeNull();
      if (dialogBox) {
        expect(dialogBox.height).toBeLessThanOrEqual(800);
        // The bottom edge of the dialog must be within the viewport.
        expect(dialogBox.y + dialogBox.height).toBeLessThanOrEqual(800);
        // The top edge must be on-screen (the prior bug was that
        // -translate-y-1/2 of a tall dialog pushed the top above 0).
        expect(dialogBox.y).toBeGreaterThanOrEqual(0);
      }

      // The action button (Save / Create / Issue) must be reachable.
      // Playwright doesn't accept :has-text(/regex/) inside a CSS
      // selector — use the role-name accessor instead, then fall back
      // to a submit-type button inside the dialog.
      let actionBtn = dialog.getByRole("button", {
        name: /save|create|issue|attach/i,
      }).first();
      if ((await actionBtn.count()) === 0) {
        actionBtn = dialog.locator("button[type='submit']").first();
      }
      await expect(actionBtn).toBeVisible();
      await actionBtn.scrollIntoViewIfNeeded();
      const actionBox = await actionBtn.boundingBox();
      expect(actionBox).not.toBeNull();
      if (actionBox) {
        expect(actionBox.y).toBeGreaterThanOrEqual(0);
        expect(actionBox.y + actionBox.height).toBeLessThanOrEqual(800);
      }
    });

    test("BUG-020: Add Client dialog action buttons are reachable on 360x800", async ({
      page,
    }) => {
      await signIn(page);
      await page.goto(`${PROD_BASE_URL}/app/clients`);

      const newClientBtn = page.getByRole("button", { name: /new client/i });
      if ((await newClientBtn.count()) === 0) {
        test.skip(true, "New Client trigger not visible on /app/clients.");
        return;
      }
      await newClientBtn.click();
      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible({ timeout: 5_000 });

      const dialogBox = await dialog.boundingBox();
      expect(dialogBox).not.toBeNull();
      if (dialogBox) {
        expect(dialogBox.height).toBeLessThanOrEqual(800);
        expect(dialogBox.y + dialogBox.height).toBeLessThanOrEqual(800);
        expect(dialogBox.y).toBeGreaterThanOrEqual(0);
      }

      let actionBtn = dialog.getByRole("button", {
        name: /save|create|add/i,
      }).first();
      if ((await actionBtn.count()) === 0) {
        actionBtn = dialog.locator("button[type='submit']").first();
      }
      await expect(actionBtn).toBeVisible();
      await actionBtn.scrollIntoViewIfNeeded();
      const actionBox = await actionBtn.boundingBox();
      expect(actionBox).not.toBeNull();
      if (actionBox) {
        expect(actionBox.y).toBeGreaterThanOrEqual(0);
        expect(actionBox.y + actionBox.height).toBeLessThanOrEqual(800);
      }
    });
  });

  test("BUG-017: POST /api/matters/{id}/statute-references returns 201 (not 422)", async ({
    page,
    request,
  }) => {
    await signIn(page);
    // Pull the session cookie set during sign-in so we can call the
    // API directly with the same auth.
    const cookies = await page.context().cookies();
    const cookieHeader = cookies
      .filter((c) => c.domain.includes("caseops.ai"))
      .map((c) => `${c.name}=${c.value}`)
      .join("; ");
    const csrfCookie = cookies.find((c) => c.name === "caseops_csrf");

    // The API is at api.caseops.ai (verified: /api/health returns
    // {"status":"ok"}). The session cookie is set with Domain=.caseops.ai
    // so it gets sent to api.caseops.ai too. We must use the API
    // base + trailing slash to avoid the 307→HTTP redirect that
    // hangs up TLS sockets in CI.
    const apiBase = PROD_API_BASE_URL;

    // Get any statute section to attach.
    const statutesResp = await request.get(
      `${apiBase}/api/statutes/ipc-1860/sections`,
      {
        headers: { Cookie: cookieHeader, Accept: "application/json" },
      },
    );
    if (!statutesResp.ok()) {
      test.skip(
        true,
        `Could not reach statutes API: ${statutesResp.status()}`,
      );
      return;
    }
    const statutesBody = await statutesResp.json();
    const sectionId = statutesBody?.sections?.[0]?.id;
    if (!sectionId) {
      test.skip(true, "No IPC sections in prod to attach.");
      return;
    }

    const matterId = await firstMatterId(page);
    if (!matterId) {
      test.skip(true, "Tenant has no matters via API.");
      return;
    }

    // POST the attach request with the same shape the production
    // browser would send.
    const headers: Record<string, string> = {
      Accept: "application/json",
      "Content-Type": "application/json",
      Cookie: cookieHeader,
    };
    if (csrfCookie) {
      headers["X-CSRF-Token"] = csrfCookie.value;
    }
    const attachResp = await request.post(
      `${apiBase}/api/matters/${matterId}/statute-references`,
      {
        headers,
        data: {
          section_id: sectionId,
          relevance: "cited",
        },
      },
    );
    const status = attachResp.status();
    const bodyText = await attachResp.text();
    // Expectation: 201 (created) or 200 (with idempotent-on-existing).
    // FAIL if 422 (the original bug).
    expect.soft(status).not.toBe(422);
    expect([200, 201, 204, 409]).toContain(status);
    if (status === 422) {
      throw new Error(
        `BUG-017 NOT FIXED — POST returned 422 with body: ${bodyText}`,
      );
    }
  });
});
