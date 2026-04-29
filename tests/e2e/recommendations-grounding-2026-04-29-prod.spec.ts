/**
 * Recommendations grounding fix verification — runs against PRODUCTION
 * (caseops.ai) signed in as the dedicated CaseOps QA Bot.
 *
 * Anchors BUG-015 / BUG-024 / BUG-033 / BUG-034 / BUG-035: prior fix
 * attempts left POST /api/matters/{id}/recommendations probabilistically
 * 422'ing with "none matched verified authorities". The 2026-04-29 fix
 * adds a bracket-tag fast path in services/citations.verify_citations
 * that resolves "[N] ..." citations by index — deterministic, skips the
 * proposition gate, falls back to fuzzy on legacy free-form output.
 *
 * Per the bug-fixing skill's brutal-honest rule:
 * - "Properly fixed" requires this spec to PASS on the deployed commit
 *   SHA against the deployed surface.
 * - A 422 here keeps the verdict at "Partially fixed" — the fix lowered
 *   the rate but did not eliminate it.
 *
 * Auth: storageState from tests/e2e/setup/qa-auth.setup.ts. The QA Bot
 * workspace owns its own matter so this test does not depend on Ram's
 * or Hari's tenant data.
 *
 * Run:
 *   CASEOPS_QA_PASSWORD=... npx playwright test \
 *     --config playwright.prod-ram.config.ts \
 *     -g "recommendations grounding"
 */
import { expect, test, type Page } from "@playwright/test";

const envOr = (key: string, fallback: string): string => {
  const v = (process.env[key] ?? "").trim();
  return v.length > 0 ? v : fallback;
};
const PROD_BASE_URL = envOr("PROD_BASE_URL", "https://caseops.ai");
const PROD_API_BASE_URL = envOr("PROD_API_BASE_URL", "https://api.caseops.ai");

async function cookieHeader(page: Page): Promise<string> {
  const cookies = await page.context().cookies();
  return cookies
    .filter((c) => c.domain.includes("caseops.ai"))
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");
}

async function csrfToken(page: Page): Promise<string | undefined> {
  const cookies = await page.context().cookies();
  return cookies.find((c) => c.name === "caseops_csrf")?.value;
}

async function createFreshMatter(page: Page, csrf: string): Promise<string> {
  // Create a fresh minimal matter for each run so the LLM call is fast +
  // deterministic. Using QA Bot's pre-existing matters (some seeded with
  // long stress descriptions) routinely takes >180s to come back, which
  // is BUG-015 territory unrelated to the grounding fix this spec covers.
  const cookie = await cookieHeader(page);
  const code = `GROUND-${Date.now()}`;
  const resp = await page.context().request.post(
    `${PROD_API_BASE_URL}/api/matters/`,
    {
      headers: {
        Cookie: cookie,
        "X-CSRF-Token": csrf,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      data: {
        title: "Section 34 patent illegality challenge",
        matter_code: code,
        practice_area: "Arbitration",
        forum_level: "high_court",
        court_name: "Delhi High Court",
        client_name: "Acme Pvt Ltd",
        opposing_party: "Beta Engineering Ltd",
        description: "Limited challenge under Section 34 of the Arbitration and Conciliation Act, 1996 on patent illegality grounds.",
        status: "active",
      },
    },
  );
  expect(resp.ok(), `POST /api/matters/ failed: ${resp.status()} ${await resp.text()}`).toBeTruthy();
  const body = await resp.json();
  return body.id;
}

test.describe("Recommendations grounding fix (2026-04-29) — prod verification", () => {
  // Recommendations on prod can take 90-180s (retrieval up to the 60s
  // statement_timeout from BUG-015 + Haiku call + verification). Bump
  // beyond the config's default 120s test cap.
  test.setTimeout(300_000);

  test("recommendations grounding: POST returns 200 with at least one verified citation", async ({
    page,
  }) => {
    await page.goto(`${PROD_BASE_URL}/app`, { waitUntil: "networkidle" });
    expect(page.url()).toContain("/app");

    const cookie = await cookieHeader(page);
    const csrf = await csrfToken(page);
    expect(csrf, "caseops_csrf cookie should be present after sign-in").toBeTruthy();

    const matterId = await createFreshMatter(page, csrf!);

    const resp = await page.context().request.post(
      `${PROD_API_BASE_URL}/api/matters/${matterId}/recommendations`,
      {
        headers: {
          Cookie: cookie,
          "X-CSRF-Token": csrf!,
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        data: { type: "authority" },
        timeout: 180_000,
      },
    );

    if (!resp.ok()) {
      const body = await resp.text();
      throw new Error(
        `POST /api/matters/${matterId}/recommendations returned ${resp.status()} — ` +
          `grounding fix has not closed BUG-024/033/034. Body: ${body}`,
      );
    }
    expect(resp.status()).toBe(200);

    const payload = await resp.json();
    expect(payload.review_required).toBe(true);
    expect(payload.options.length).toBeGreaterThan(0);

    const totalVerified = (payload.options as Array<{ supporting_citations: string[] }>)
      .map((o) => o.supporting_citations.length)
      .reduce((a, b) => a + b, 0);
    expect(
      totalVerified,
      "At least one option must carry a verified citation — grounding fix proves citations are getting through",
    ).toBeGreaterThan(0);

    // Every surfaced citation should be a clean canonical string (no
    // residual "[N] " prefix from the model's bracket-tag emission).
    for (const option of payload.options as Array<{ supporting_citations: string[] }>) {
      for (const citation of option.supporting_citations) {
        expect(
          citation,
          `Citation "${citation}" still has a [N] prefix — _filter_and_verify_options should have replaced with canonical identifier`,
        ).not.toMatch(/^\s*\[\d+\]/);
      }
    }
  });
});
