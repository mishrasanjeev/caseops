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
import {
  expect,
  test,
  type APIRequestContext,
  type APIResponse,
  type Page,
} from "@playwright/test";

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

async function expectApiOk(resp: APIResponse, action: string): Promise<void> {
  if (!resp.ok()) {
    throw new Error(`${action} failed: ${resp.status()} ${await resp.text()}`);
  }
}

async function runOptionalConflictReview(
  request: APIRequestContext,
  headers: Record<string, string>,
  matterId: string,
  opposingPartyName: string,
): Promise<void> {
  const runResp = await request.post(
    `${PROD_API_BASE_URL}/api/matters/${matterId}/conflict-checks`,
    {
      headers,
      data: {
        opposing_party_name: opposingPartyName,
        related_party_names: [],
      },
    },
  );
  await expectApiOk(runResp, "POST conflict check");
  const check = await runResp.json() as { id: string; status: string };
  if (check.status === "pending") {
    const clearResp = await request.patch(
      `${PROD_API_BASE_URL}/api/conflict-checks/${check.id}`,
      {
        headers,
        data: {
          status: "cleared",
          resolution_note: "Optional production fixture review found no real conflict.",
        },
      },
    );
    await expectApiOk(clearResp, "PATCH conflict check cleared");
    return;
  }
  expect(["cleared", "waived"]).toContain(check.status);
}

async function prepareAndActivateMatter(
  request: APIRequestContext,
  headers: Record<string, string>,
  matterId: string,
  opposingPartyName: string,
): Promise<void> {
  // Preserve conflict-review coverage without treating it as an activation gate.
  await runOptionalConflictReview(request, headers, matterId, opposingPartyName);
  const currentResp = await request.get(
    `${PROD_API_BASE_URL}/api/matters/${matterId}`,
    { headers },
  );
  await expectApiOk(currentResp, "GET matter before activation");
  const current = (await currentResp.json()) as { updated_at: string };
  const activateResp = await request.patch(
    `${PROD_API_BASE_URL}/api/matters/${matterId}`,
    {
      headers,
      data: { status: "active", expected_updated_at: current.updated_at },
    },
  );
  await expectApiOk(activateResp, "PATCH matter active");
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
      },
    },
  );
  await expectApiOk(resp, "POST /api/matters/");
  const body = await resp.json();
  await prepareAndActivateMatter(
    page.context().request,
    {
      Cookie: cookie,
      "X-CSRF-Token": csrf,
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body.id,
    "Beta Engineering Ltd",
  );
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

    const csrf = await csrfToken(page);
    expect(csrf, "caseops_csrf cookie should be present after sign-in").toBeTruthy();

    const matterId = await createFreshMatter(page, csrf!);
    const cookie = await cookieHeader(page);

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

  test("PG-107 v1.5 (2026-05-01): admin toggle flips bench panel mode badge end-to-end", async ({
    page,
  }) => {
    // PG-107 v1.5: workspace owner flips predictive_bench_strategy_enabled
    // on the Admin page. The bench-strategy-context API echoes mode +
    // disclaimer; UI surfaces a Predictive badge + amber disclaimer
    // banner. Reset back to evidence_only at the end so other tests
    // (and human users) don't inherit a flipped policy.
    await page.goto(`${PROD_BASE_URL}/app/admin`, { waitUntil: "networkidle" });
    expect(page.url()).toContain("/app/admin");

    // Card should render for QA Bot (owner role).
    const card = page.locator('[data-testid="tenant-ai-policy-card"]');
    await expect(card).toBeVisible({ timeout: 30_000 });

    // Read current state via the API to know whether to flip on or off.
    const cookie = await cookieHeader(page);
    const csrf = await csrfToken(page);
    expect(csrf).toBeTruthy();
    const before = await page.context().request.get(
      `${PROD_API_BASE_URL}/api/admin/tenant-ai-policy`,
      { headers: { Cookie: cookie, Accept: "application/json" }, timeout: 30_000 },
    );
    expect(before.ok()).toBeTruthy();
    const beforeBody = await before.json();
    const startedEnabled = !!beforeBody.predictive_bench_strategy_enabled;

    try {
      // Click the toggle to flip ON (or OFF if already on).
      await card
        .locator('[data-testid="tenant-ai-policy-predictive-toggle"]')
        .click();
      // Verify the API now reports the flipped state.
      await expect.poll(async () => {
        const r = await page.context().request.get(
          `${PROD_API_BASE_URL}/api/admin/tenant-ai-policy`,
          { headers: { Cookie: cookie, Accept: "application/json" }, timeout: 15_000 },
        );
        return (await r.json()).predictive_bench_strategy_enabled;
      }, { timeout: 30_000 }).toBe(!startedEnabled);
    } finally {
      // Restore original state.
      await page.context().request.patch(
        `${PROD_API_BASE_URL}/api/admin/tenant-ai-policy`,
        {
          headers: {
            Cookie: cookie,
            "X-CSRF-Token": csrf!,
            "Content-Type": "application/json",
            Accept: "application/json",
          },
          data: { predictive_bench_strategy_enabled: startedEnabled },
          timeout: 15_000,
        },
      );
    }
  });

  test("PG-001 (2026-04-30): conflict check on matter cockpit runs + flags overlap + clears", async ({
    page,
  }) => {
    // PG-001 deep-cut: optional pre-engagement conflict-of-interest review. Flow:
    //   1. create matter A with client_name "Acme Pvt Ltd"
    //   2. create matter B with opposing_party "Acme Pvt Ltd" — should
    //      conflict with matter A
    //   3. open matter B's cockpit, run conflict check → status=pending
    //      with at least one candidate (matter A).
    //   4. click "Clear (no real conflict)" — status flips to cleared.
    await page.goto(`${PROD_BASE_URL}/app`, { waitUntil: "networkidle" });
    expect(page.url()).toContain("/app");

    const cookie = await cookieHeader(page);
    const csrf = await csrfToken(page);
    expect(csrf).toBeTruthy();

    // Step 1+2: seed two matters whose names overlap.
    const tag = Date.now();
    const seedClient = `Conflict-Acme-${tag}`;
    const matterAResp = await page.context().request.post(
      `${PROD_API_BASE_URL}/api/matters/`,
      {
        headers: {
          Cookie: cookie,
          "X-CSRF-Token": csrf!,
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        data: {
          title: "Acme contract dispute",
          matter_code: `CONF-A-${tag}`,
          practice_area: "litigation",
          forum_level: "high_court",
          court_name: "Delhi High Court",
          client_name: seedClient,
          description: "Existing matter for conflict probe.",
        },
      },
    );
    expect(matterAResp.ok()).toBeTruthy();

    const matterBResp = await page.context().request.post(
      `${PROD_API_BASE_URL}/api/matters/`,
      {
        headers: {
          Cookie: cookie,
          "X-CSRF-Token": csrf!,
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        data: {
          title: "New retainer flagged for conflict",
          matter_code: `CONF-B-${tag}`,
          practice_area: "litigation",
          forum_level: "high_court",
          court_name: "Delhi High Court",
          client_name: "Beta Corp",
          opposing_party: seedClient,
          description: "New matter whose opposing_party hits matter A.",
        },
      },
    );
    expect(matterBResp.ok()).toBeTruthy();
    const matterBId = (await matterBResp.json()).id;

    // Step 3: open matter B and run conflict check from the UI card.
    await page.goto(`${PROD_BASE_URL}/app/matters/${matterBId}`, {
      waitUntil: "networkidle",
    });
    const card = page.locator('[data-testid="matter-conflict-card"]');
    await expect(card).toBeVisible({ timeout: 30_000 });
    await card.locator('[data-testid="conflict-run-open"]').click();
    await page.locator('[data-testid="conflict-run-opposing"]').fill(seedClient);
    await page.locator('[data-testid="conflict-run-submit"]').click();

    // Pending badge should appear — matter A is the overlap.
    await expect(
      card.locator('[data-testid="conflict-status-pending"]'),
    ).toBeVisible({ timeout: 30_000 });

    // Step 4: clear it.
    await card.locator('[data-testid="conflict-resolve-clear"]').click();
    await expect(
      card.locator('[data-testid="conflict-status-cleared"]'),
    ).toBeVisible({ timeout: 30_000 });
  });

  test("BUG-019/025: matter cockpit empty-state shows '+ Add hearing' that schedules a hearing end-to-end", async ({
    page,
  }) => {
    // BUG-019/025 durable closure (2026-04-30): the calendar empty-state
    // banner was only a Partial fix. The workflow fix is the "+ Add
    // hearing" affordance on the matter cockpit, which posts to
    // POST /api/matters/{id}/hearings and surfaces the result in
    // /api/calendar/events. This spec exercises the user-visible flow
    // end-to-end on prod.
    await page.goto(`${PROD_BASE_URL}/app`, { waitUntil: "networkidle" });
    expect(page.url()).toContain("/app");

    const csrf = await csrfToken(page);
    expect(csrf).toBeTruthy();

    // Create a fresh matter so the cockpit is in the empty-state shape.
    const matterId = await createFreshMatter(page, csrf!);

    // Land on the cockpit. Empty-state card carries the "Add hearing"
    // CTA AND the data-testid we asserted in vitest, which keeps a
    // future regression visible at the prod surface.
    await page.goto(`${PROD_BASE_URL}/app/matters/${matterId}`, {
      waitUntil: "networkidle",
    });
    const emptyCard = page.locator('[data-testid="matter-overview-no-hearings"]');
    await expect(emptyCard).toBeVisible({ timeout: 30_000 });
    await emptyCard.locator('[data-testid="schedule-hearing-open"]').click();

    // Fill the dialog using the same testids the vitest + hearings-tab
    // tests use, so the contract stays consistent across surfaces.
    const today = new Date();
    today.setDate(today.getDate() + 14);
    const iso = today.toISOString().slice(0, 10);
    await page.locator('[data-testid="schedule-hearing-date"]').fill(iso);
    await page.locator("#forum_name").fill("Delhi High Court");
    await page.locator("#purpose").fill("Initial listing");
    await page.locator('[data-testid="schedule-hearing-submit"]').click();

    // The mutation invalidates the matter workspace query, so the
    // cockpit repaints with the populated "Upcoming hearings" card.
    // No empty-state card now — that's the workflow proof.
    await expect(
      page.locator('[data-testid="matter-overview-no-hearings"]'),
    ).toBeHidden({ timeout: 30_000 });

    // And the hearing reaches /api/calendar/events — close the loop on
    // BUG-019/025's original "calendar should show hearings" complaint.
    const calendarCookie = await cookieHeader(page);
    const cal = await page.context().request.get(
      `${PROD_API_BASE_URL}/api/calendar/events?from=${iso}&to=${iso}`,
      { headers: { Cookie: calendarCookie, Accept: "application/json" }, timeout: 30_000 },
    );
    expect(cal.ok()).toBeTruthy();
    const calBody = await cal.json();
    const events: Array<{ kind: string; matter_id?: string }> = calBody?.events ?? [];
    expect(
      events.some((e) => e.kind === "hearing" && e.matter_id === matterId),
      `calendar should surface the new hearing for matter ${matterId}`,
    ).toBe(true);
  });

  test("BUG-015 root cause (HNSW prefilter): stress matter responds in <120s, no 504, no hang", async ({
    page,
  }) => {
    // Pre-deploy probe (2026-04-29) showed the stress matter
    // 31f0577f-ea2e-4033-b16b-d04e16b13729 ("BUG-024 citation grounding
    // probe") hung >180s on POST recommendations because the prior CTE
    // shape forced a sequential scan over 1.8M chunks. The 2026-04-30
    // fix rewrites _pg_prefilter_document_ids so the inner CTE uses
    // ORDER BY <=> LIMIT directly — pgvector serves it from the HNSW
    // index in O(log n). This case proves the read path stays fast even
    // on richly-described matters.
    //
    // Acceptance: the endpoint MUST return within 120s (config default
    // test timeout). Any 200, 422 ("none matched verified authorities"),
    // or other 4xx counts as the fix landing — the bug is the *hang*,
    // not the verdict. A 504 or a Playwright-level timeout fails.
    await page.goto(`${PROD_BASE_URL}/app`, { waitUntil: "networkidle" });
    expect(page.url()).toContain("/app");

    const cookie = await cookieHeader(page);
    const csrf = await csrfToken(page);
    expect(csrf).toBeTruthy();

    const STRESS_MATTER_ID = "31f0577f-ea2e-4033-b16b-d04e16b13729";

    // Confirm the stress matter still belongs to QA Bot (defense against
    // a future tenant re-bootstrap silently making this a no-op probe).
    const matterResp = await page.context().request.get(
      `${PROD_API_BASE_URL}/api/matters/${STRESS_MATTER_ID}`,
      { headers: { Cookie: cookie, Accept: "application/json" }, timeout: 30_000 },
    );
    expect(
      matterResp.status(),
      `Stress matter ${STRESS_MATTER_ID} not visible to QA Bot — re-pick a stress matter id`,
    ).toBe(200);

    const t0 = Date.now();
    const resp = await page.context().request.post(
      `${PROD_API_BASE_URL}/api/matters/${STRESS_MATTER_ID}/recommendations`,
      {
        headers: {
          Cookie: cookie,
          "X-CSRF-Token": csrf!,
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        data: { type: "authority" },
        timeout: 110_000,
      },
    );
    const elapsedMs = Date.now() - t0;
    // Hard upper bound: must complete within 110s (well under 120s test
    // cap). If we hit 504 or the timeout, the BUG-015 fix has NOT landed
    // for this matter shape.
    expect(
      elapsedMs,
      `Stress matter took ${elapsedMs}ms — BUG-015 root cause has not landed`,
    ).toBeLessThan(110_000);
    expect(
      resp.status(),
      `Stress matter returned 504 — gateway hang, BUG-015 not fixed`,
    ).not.toBe(504);
    // 200 (full success) or any 4xx (LLM grounding refused, citations
    // unverified, etc.) both count as the read path succeeding fast.
    expect(resp.status()).toBeGreaterThanOrEqual(200);
    expect(resp.status()).toBeLessThan(500);
  });
});
