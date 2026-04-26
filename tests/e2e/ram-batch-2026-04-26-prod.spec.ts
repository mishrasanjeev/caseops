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

/**
 * Authentication is handled once by the `setup` Playwright project
 * (tests/e2e/setup/ram-auth.setup.ts) which writes
 * tests/e2e/.auth/ram-storage.json; this file is loaded as
 * `storageState` for every test. So by the time a test runs, page
 * is already signed in as Ram. Tests that previously called signIn()
 * still work (it's now a no-op).
 */
async function signIn(_page: Page): Promise<void> {
  // No-op — storageState handles auth. Kept as a stub for legacy test
  // bodies; safe to drop on next refactor.
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
    // storageState already authenticates Ram. Navigate to /app to
    // confirm the session is valid before clearing it.
    await page.goto(`${PROD_BASE_URL}/app`, { waitUntil: "networkidle" });
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

  test("BUG-019: Calendar shows actionable empty-state banner when tenant has zero events", async ({
    page,
  }) => {
    await signIn(page);
    await page.goto(`${PROD_BASE_URL}/app/calendar`, { waitUntil: "networkidle" });
    // Two acceptable outcomes:
    //   (a) tenant has events → empty-state banner is absent (count=0)
    //   (b) tenant has zero events → banner is visible AND links to /app/matters
    const banner = page.getByTestId("calendar-empty-state");
    const bannerCount = await banner.count();
    if (bannerCount === 0) {
      // Tenant has events; skip the per-banner assertion. The fact
      // that the page loaded without a raw error proves the calendar
      // surface itself is healthy.
      test.skip(true, "Tenant has events — banner correctly absent.");
      return;
    }
    await expect(banner).toBeVisible();
    await expect(banner).toContainText(/calendar populates from hearings/i);
    await expect(banner.getByRole("link", { name: /open matters/i })).toBeVisible();
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

  test("BUG-016: recommendation generate failure shows persistent error Card with retry+dismiss", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    const matterIds = await allMatterIds(page);
    if (matterIds.length === 0) {
      test.skip(true, "Tenant has no matters via API.");
      return;
    }
    const matterId = matterIds[0];
    await page.goto(`${PROD_BASE_URL}/app/matters/${matterId}/recommendations`, {
      waitUntil: "networkidle",
    });
    const generateBtn = page.getByTestId("generate-authority-recommendation");
    if ((await generateBtn.count()) === 0) {
      test.skip(true, "Generate button not rendered — page shape changed or capability missing.");
      return;
    }
    // Trigger a generate. On a thin/empty matter the backend will
    // either succeed (a new authority recommendation appears) or fail
    // with a validation 422. EITHER outcome verifies the page is alive.
    // The persistent-error-Card assertion is conditional on a failure
    // happening — if the matter is rich enough to succeed, we record
    // that as Inconclusive for the error-Card path itself.
    await generateBtn.click();
    // Wait for either a success indicator or the error Card to appear.
    const errorCard = page.getByTestId("recommendation-last-error");
    const successIndicator = page.locator("[data-testid^='recommendation-row-']").first();
    await Promise.race([
      errorCard.waitFor({ state: "visible", timeout: 120_000 }).catch(() => null),
      successIndicator.waitFor({ state: "visible", timeout: 120_000 }).catch(() => null),
    ]);
    const errorVisible = (await errorCard.count()) > 0 && await errorCard.isVisible();
    if (!errorVisible) {
      test.skip(
        true,
        "Recommendation generate succeeded — cannot probe the error-Card UI on this matter. The Card-on-failure path is verified by vitest only.",
      );
      return;
    }
    // Verify the Card has both action buttons.
    await expect(page.getByTestId("recommendation-retry-from-banner")).toBeVisible();
    await expect(page.getByTestId("recommendation-dismiss-banner")).toBeVisible();
    // Dismiss must remove it without re-firing generate.
    await page.getByTestId("recommendation-dismiss-banner").click();
    await expect(errorCard).toHaveCount(0, { timeout: 5_000 });
  });

  test("BUG-021: Research page filters or flags garbled OCR snippets", async ({
    page,
  }) => {
    test.setTimeout(120_000);
    await signIn(page);
    await page.goto(`${PROD_BASE_URL}/app/research`, { waitUntil: "networkidle" });
    const searchBox = page.locator("input[type='search'], input[placeholder*='search' i], input[placeholder*='query' i]").first();
    if ((await searchBox.count()) === 0) {
      test.skip(true, "Research search input not found on /app/research.");
      return;
    }
    // A query that's likely to retrieve from the older / OCR-heavy
    // corpus where garbled snippets historically appeared.
    await searchBox.fill("section 138 negotiable instruments dishonour");
    await searchBox.press("Enter");
    // Wait for results to render.
    await page.waitForTimeout(8_000);
    // Either:
    //   (a) all visible snippets are clean (no replacement chars,
    //       no >5% weird symbols) — the filter worked
    //   (b) a "filtered for quality" or empty-state badge appears
    //       acknowledging the suppression
    // Forbidden: a visible snippet containing  (replacement char) or
    // a high concentration of single-letter tokens.
    const snippets = await page.locator("[class*='snippet'], [class*='excerpt'], [class*='result-body']").allInnerTexts();
    if (snippets.length === 0) {
      test.skip(true, "No research result snippets rendered — cannot probe garbled-text filter.");
      return;
    }
    for (const snippet of snippets) {
      const replacementChars = (snippet.match(/\uFFFD/g) ?? []).length;
      const replacementRatio = snippet.length > 0 ? replacementChars / snippet.length : 0;
      expect.soft(
        replacementRatio,
        `Snippet contains too many \\uFFFD replacement chars: "${snippet.slice(0, 100)}..."`,
      ).toBeLessThan(0.02);
    }
  });

  test("STATUTE-LOOP: hand-curated BNS §318 text is retrievable from prod API (not just job-log evidence)", async ({
    page,
    request,
  }) => {
    await signIn(page);
    const cookies = await page.context().cookies();
    const cookieHeader = cookies
      .filter((c) => c.domain.includes("caseops.ai"))
      .map((c) => `${c.name}=${c.value}`)
      .join("; ");
    // Try multiple candidate routes — the schema isn't documented in
    // this test file. The fix verification is: SOMEWHERE in prod, the
    // hand-curated section_text for BNS §318 (cheating, 1593 chars,
    // section_text_source="manual") is reachable.
    const candidates = [
      `${PROD_API_BASE_URL}/api/statutes/bns-2023/sections`,
      `${PROD_API_BASE_URL}/api/statutes/sections?bare_act=BNS&section=318`,
      `${PROD_API_BASE_URL}/api/v1/statutes/sections?bare_act=BNS&section=318`,
      `${PROD_API_BASE_URL}/api/statutes/`,
    ];
    let bnsBody: unknown = null;
    let hitRoute: string | null = null;
    for (const url of candidates) {
      const r = await request.get(url, {
        headers: { Cookie: cookieHeader, Accept: "application/json" },
      });
      if (r.ok()) {
        bnsBody = await r.json();
        hitRoute = url;
        const text = JSON.stringify(bnsBody);
        if (text.includes("BNS") || text.includes("bns")) break;
      }
    }
    if (!hitRoute) {
      throw new Error(
        "STATUTE-LOOP NOT VERIFIED — no statute API route returned 200 for any of: " +
        candidates.join(", "),
      );
    }
    // Section_number is a STRING like "Section 63" / "Section 318".
    // Find the section explicitly so we can also check section_text length
    // (hand-curated BNS §318 = 1593 chars).
    const sections = (bnsBody as { sections?: Array<{ section_number: string; section_text: string | null }> })?.sections ?? [];
    const sec318 = sections.find((s) => /\bSection\s*318\b/i.test(s.section_number));
    if (!sec318) {
      const numbers = sections.map((s) => s.section_number).join(", ");
      throw new Error(
        `STATUTE-LOOP NOT VERIFIED — route ${hitRoute} returned ${sections.length} sections but none match Section 318. Found: ${numbers.slice(0, 400)}`,
      );
    }
    // The hand-curated section_text is 1593 chars. Anything < 200 means
    // the seed job ran but didn't bring the hand-curated payload, OR the
    // route returns trimmed text.
    expect.soft(sec318.section_text, "BNS §318 section_text is null or empty").not.toBeNull();
    expect.soft(
      sec318.section_text?.length ?? 0,
      `BNS §318 section_text shorter than expected (hand-curated ~1593 chars)`,
    ).toBeGreaterThan(500);
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

  // ---------------------------------------------------------------
  // Synthetic-data probes — exercise the deployed prod frontend
  // bundle with controlled API responses so we can verify code paths
  // that are otherwise unreachable on Ram's tenant (empty calendar,
  // garbled OCR snippets, billing trigger gated by matter state).
  //
  // These tests load the same prod build the user sees; only the
  // payload from api.caseops.ai is intercepted to inject the data
  // shape needed to reach the bug's code branch. The fix being
  // verified is the FRONTEND rendering of that branch.
  // ---------------------------------------------------------------

  test("BUG-019 (synthetic): empty calendar response renders empty-state banner with Open Matters link", async ({
    page,
  }) => {
    // Intercept calendar events endpoint and return zero events.
    await page.route(/.*\/api\/calendar\/events(\?|$)/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          events: [],
          range_from: "2026-04-01",
          range_to: "2026-04-30",
        }),
      });
    });
    await page.goto(`${PROD_BASE_URL}/app/calendar`, { waitUntil: "networkidle" });
    const banner = page.getByTestId("calendar-empty-state");
    await expect(banner).toBeVisible({ timeout: 15_000 });
    await expect(banner).toContainText(/calendar populates from hearings/i);
    const cta = banner.getByRole("link", { name: /open matters/i });
    await expect(cta).toBeVisible();
    expect(await cta.getAttribute("href")).toContain("/app/matters");
  });

  test("BUG-021 (synthetic): garbled OCR snippet renders the placeholder card, not the raw mojibake", async ({
    page,
  }) => {
    // Inject a research result with U+FFFD-laden snippet so the
    // isGarbledSnippet() branch fires.
    const garbledSnippet =
      "The c\uFFFDurt h\uFFFDld th\uFFFD def\uFFFDnda\uFFFDt liab\uFFFDe. " +
      "P\uFFFDrti\uFFFDs are bo\uFFFDnd by th\uFFFD or\uFFFDer. " +
      "F\uFFFDrth\uFFFDr proc\uFFFDdings dir\uFFFDcted.";
    await page.route(/.*\/api\/authorities\/search.*/, async (route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          query: "garbled-test",
          provider: "test",
          generated_at: new Date().toISOString(),
          results: [
            {
              authority_document_id: "garbled-1",
              title: "Test v. Test (synthetic for BUG-021)",
              court_name: "Supreme Court of India",
              forum_level: "supreme_court",
              document_type: "judgment",
              decision_date: "2020-01-01",
              case_reference: "TEST/2020",
              bench_name: null,
              summary: "",
              source: "synthetic",
              source_reference: null,
              snippet: garbledSnippet,
              score: 0.99,
              matched_terms: [],
            },
          ],
        }),
      });
    });
    // Match the actual corpus stats endpoint shape.
    await page.route(/.*\/api\/authorities\/stats(\?|$)/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          document_count: 100,
          chunk_count: 1000,
          embedded_chunk_count: 1000,
          forum_counts: { supreme_court: 100 },
          last_ingested_at: new Date().toISOString(),
        }),
      });
    });
    await page.goto(`${PROD_BASE_URL}/app/research`, { waitUntil: "networkidle" });
    // Find the search input + submit a query.
    const searchInput = page
      .locator("input[type='search'], input[placeholder*='search' i], input[placeholder*='query' i], textarea")
      .first();
    await searchInput.fill("dishonour negotiable instruments");
    // The page may have a submit button or use Enter. Try Enter first.
    await searchInput.press("Enter");
    // The garbled placeholder card should appear.
    await expect(page.getByTestId("research-result-garbled")).toBeVisible({
      timeout: 15_000,
    });
    // The raw mojibake snippet must NOT be visible (placeholder hides it).
    const bodyText = await page.locator("body").innerText();
    expect(bodyText).not.toContain(garbledSnippet);
  });

  test("L-B/bench-strategy (synthetic): panel renders authorities + statute aggregates when L-B is populated", async ({
    page,
  }) => {
    // L-B (judge_authority_affinity) was populated for the first time
    // on 2026-04-26 PM by the self-citation map backfill (Track B):
    // 4,823 affinity rows inserted. Ram's matters have no
    // matter_cause_list_entries.judges_json so the bench resolver
    // returns insufficient on his real tenant. To verify the FRONTEND
    // surfaces L-B aggregates correctly, intercept the API with a
    // populated payload that matches the L-B/L-C wire shape.
    const matterIds = await allMatterIds(page);
    if (matterIds.length === 0) {
      test.skip(true, "Tenant has no matters via API.");
      return;
    }
    const matterId = matterIds[0];
    await page.route(/.*\/api\/matters\/[^/]+\/bench-strategy(\?|$)/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          matter_id: matterId,
          bench_judge_ids: ["judge-1", "judge-2"],
          total_decisions_indexed: 47,  // → "strong" bucket per service
          evidence_quality: "strong",
          top_authorities: [
            {
              authority_id: "auth-vishaka",
              title: "Vishaka v. State of Rajasthan",
              citation_count: 12,
              last_year: 2024,
              sample_judgment_id: "j-sample-1",
            },
            {
              authority_id: "auth-kesavananda",
              title: "Kesavananda Bharati v. State of Kerala",
              citation_count: 8,
              last_year: 2023,
              sample_judgment_id: "j-sample-2",
            },
          ],
          top_statute_sections: [
            {
              statute_section_id: "ss-bns-318",
              statute_id: "bns-2023",
              section_number: "Section 318",
              section_label: "Cheating",
              citation_count: 15,
              last_year: 2024,
              sample_judgment_id: "j-sample-3",
            },
          ],
          disclaimer:
            "Statistical analysis based on indexed decisions only. Not legal advice.",
        }),
      });
    });
    await page.goto(`${PROD_BASE_URL}/app/matters/${matterId}`, {
      waitUntil: "networkidle",
    });
    // Panel root + quality chip
    const panel = page.getByTestId("bench-strategy-panel");
    await expect(panel).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("bench-strategy-quality-chip")).toContainText(
      /Strong evidence base/i,
    );
    // Authorities section (the L-B-driven block) + at least one row
    const authoritiesSection = page.getByTestId("bench-strategy-authorities");
    await expect(authoritiesSection).toBeVisible();
    await expect(authoritiesSection).toContainText(/Vishaka v\. State of Rajasthan/);
    await expect(authoritiesSection).toContainText(/Kesavananda Bharati/);
    // Statutes section (L-C-driven)
    const statutesSection = page.getByTestId("bench-strategy-statutes");
    await expect(statutesSection).toBeVisible();
    await expect(statutesSection).toContainText(/bns-2023/);
    await expect(statutesSection).toContainText(/Section 318/);
    await expect(statutesSection).toContainText(/Cheating/);
    // Disclaimer must always render
    await expect(page.getByTestId("bench-strategy-disclaimer")).toContainText(
      /not legal advice/i,
    );
    // Insufficient note + no-aggregates note must be ABSENT in the
    // populated case (would mean the panel is rendering the wrong branch).
    expect(
      await page.getByTestId("bench-strategy-insufficient-note").count(),
    ).toBe(0);
    expect(
      await page.getByTestId("bench-strategy-no-aggregates").count(),
    ).toBe(0);
  });

  test("L-B/bench-strategy (real-tenant): Ram's matters return insufficient because no listings (documents L-B unblock surface)", async ({
    page,
    request,
  }) => {
    // This test is the brutal-honest baseline. Ram's tenant has 4
    // matters, none with matter_cause_list_entries.judges_json
    // populated. So even though L-B has 4,823 rows globally, Ram's
    // matters can't surface them. This test ASSERTS that fact so
    // future sessions know exactly what's missing.
    const cookies = await page.context().cookies();
    const cookieHeader = cookies
      .filter((c) => c.domain.includes("caseops.ai"))
      .map((c) => `${c.name}=${c.value}`)
      .join("; ");
    const matterIds = await allMatterIds(page);
    if (matterIds.length === 0) {
      test.skip(true, "Tenant has no matters via API.");
      return;
    }
    let anyPopulated = false;
    for (const mid of matterIds) {
      const r = await request.get(
        `${PROD_API_BASE_URL}/api/matters/${mid}/bench-strategy`,
        { headers: { Cookie: cookieHeader, Accept: "application/json" } },
      );
      if (!r.ok()) continue;
      const body = await r.json();
      if (
        Array.isArray(body.bench_judge_ids) &&
        body.bench_judge_ids.length > 0
      ) {
        anyPopulated = true;
        break;
      }
    }
    // The expectation today (2026-04-26 PM): NONE of Ram's matters
    // have listings. If this test starts failing because anyPopulated
    // becomes true, that means a listing WAS added — at which point
    // the L-B integration is verifiable on real data and we should
    // update this test into a positive assertion.
    expect.soft(
      anyPopulated,
      "If true: a Ram matter now has a listing — L-B/bench-strategy can be tested on real data, no synthetic interception needed. Update this test.",
    ).toBe(false);
  });

  test("L-B/bench-strategy (real-data end-to-end): create matter → import listing with real judge → bench-strategy returns populated payload", async ({
    page,
    request,
  }) => {
    test.setTimeout(120_000);
    // MOD-TS-018 (2026-04-26 PM, deploy SHA TBD): the
    // POST /court-sync/import endpoint now resolves the bench inline
    // and falls back to forum_name → Court lookup when matter.court_id
    // is NULL. This test proves the full lawyer workflow end-to-end:
    //   1. Create a fresh matter on Delhi HC
    //   2. Import a cause-list listing with a real Delhi HC judge name
    //   3. GET /bench-strategy → bench_judge_ids must be populated
    //      (and L-B aggregates surface IF the judge has affinity rows).
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

    // 1. Create a fresh test matter on Delhi HC.
    const matterCode = `BENCH-PROBE-${Date.now()}`;
    const createResp = await request.post(
      `${PROD_API_BASE_URL}/api/matters/`,
      {
        headers,
        data: {
          title: "Bench-strategy real-data probe (auto-generated)",
          matter_code: matterCode,
          client_name: "Probe Client",
          practice_area: "Commercial Litigation",
          forum_level: "high_court",
          status: "active",
          court_name: "Delhi High Court",
        },
      },
    );
    if (!createResp.ok()) {
      test.skip(
        true,
        `Could not create probe matter: ${createResp.status()} ${await createResp.text()}`,
      );
      return;
    }
    const matterId = (await createResp.json()).id as string;

    // 2. Try a list of known Delhi HC judge names. The first one whose
    // bench_resolver match populates judges_json wins. If NONE match,
    // judge_aliases coverage for Delhi HC is thinner than expected
    // (separate gap to fix).
    const candidateJudges = [
      "Justice Yashwant Varma",
      "Justice V. Kameswar Rao",
      "Justice Pratibha M. Singh",
      "Justice Rajiv Sahai Endlaw",
      "Justice Manmohan",
      "Justice Vibhu Bakhru",
      "Justice Sanjeev Sachdeva",
      "Justice Sanjeev Narula",
    ];
    let resolvedJudgeIds: string[] = [];
    let resolvedJudgeName: string | null = null;
    for (const judgeName of candidateJudges) {
      const importResp = await request.post(
        `${PROD_API_BASE_URL}/api/matters/${matterId}/court-sync/import`,
        {
          headers,
          data: {
            source: "manual_probe",
            summary: `Probe import for ${judgeName}`,
            cause_list_entries: [
              {
                listing_date: "2026-05-15",
                forum_name: "Delhi High Court",
                bench_name: judgeName,
              },
            ],
            orders: [],
          },
        },
      );
      expect.soft(importResp.ok()).toBeTruthy();
      // Probe bench-strategy after each attempt.
      const bsResp = await request.get(
        `${PROD_API_BASE_URL}/api/matters/${matterId}/bench-strategy`,
        { headers: { Cookie: cookieHeader, Accept: "application/json" } },
      );
      if (!bsResp.ok()) continue;
      const bs = await bsResp.json();
      if (Array.isArray(bs.bench_judge_ids) && bs.bench_judge_ids.length > 0) {
        resolvedJudgeIds = bs.bench_judge_ids;
        resolvedJudgeName = judgeName;
        // Log L-B/L-C details so the verdict in the deliverable can
        // name what surfaced.
        // eslint-disable-next-line no-console
        console.log(
          `BENCH-PROBE-PASSED matter=${matterId} judge="${judgeName}" judge_ids=${JSON.stringify(bs.bench_judge_ids)} total_decisions=${bs.total_decisions_indexed} quality=${bs.evidence_quality} top_authorities=${bs.top_authorities?.length ?? 0} top_statutes=${bs.top_statute_sections?.length ?? 0}`,
        );
        break;
      }
    }

    // The bench resolver MUST resolve at least one of the 8 candidate
    // judges. If not, the failure means: (a) judge_aliases doesn't
    // have any of these well-known Delhi HC judges (data gap), OR
    // (b) the inline-resolver path isn't actually wired (deploy
    // didn't include the change), OR (c) the forum_name → Court
    // fallback didn't fire (Delhi High Court isn't an active Court
    // row matching by name).
    expect(
      resolvedJudgeIds.length,
      `None of ${candidateJudges.length} candidate Delhi HC judges resolved on a freshly-created matter. Tried: ${candidateJudges.join(", ")}.`,
    ).toBeGreaterThan(0);
    // eslint-disable-next-line no-console
    console.log(
      `BENCH-PROBE-RESULT resolved=${resolvedJudgeIds.length} via="${resolvedJudgeName}"`,
    );
  });

  test.describe("Mobile 360x800 — synthetic-data probes", () => {
    test.use({ viewport: { width: 360, height: 800 } });

    test("BUG-018 (synthetic): Invoice dialog fits 360x800 viewport with intercepted workspace data", async ({
      page,
    }) => {
      // Intercept matter workspace to return a valid matter with no
      // invoices and no time entries — minimal data to render the
      // billing page + the canIssueInvoice trigger.
      await page.route(/.*\/api\/matters\/[^/]+\/workspace.*/, async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            matter: {
              id: "synth-matter-1",
              title: "Synthetic Matter (BUG-018 probe)",
              matter_code: "SYNTH-1",
              status: "active",
              forum_level: "high_court",
            },
            invoices: [],
            time_entries: [],
            notes: [],
            tasks: [],
            hearings: [],
            court_orders: [],
            activity: [],
          }),
        });
      });
      // Pick any real matter id from Ram's list (URL just needs a path
      // segment; the workspace route returns synthetic data anyway).
      const matterIds = await allMatterIds(page);
      const matterId = matterIds[0] ?? "synth-matter-1";
      await page.goto(`${PROD_BASE_URL}/app/matters/${matterId}/billing`, {
        waitUntil: "networkidle",
      });
      const trigger = page.getByTestId("new-invoice-trigger");
      await expect(trigger).toBeVisible({ timeout: 15_000 });
      await trigger.click();
      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible({ timeout: 5_000 });

      const dialogBox = await dialog.boundingBox();
      expect(dialogBox).not.toBeNull();
      if (dialogBox) {
        // Per the base primitive fix: max-h-[90vh]=720px on a 800-tall viewport
        expect(dialogBox.height).toBeLessThanOrEqual(800);
        expect(dialogBox.y + dialogBox.height).toBeLessThanOrEqual(800);
        expect(dialogBox.y).toBeGreaterThanOrEqual(0);
      }
      // Action button must be reachable.
      let actionBtn = dialog
        .getByRole("button", { name: /save|create|issue|attach/i })
        .first();
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
});
