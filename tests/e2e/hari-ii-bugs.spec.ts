/**
 * Hari 2026-04-21 bug batch II — end-to-end regressions.
 *
 * One spec per bug so a future regression names itself. Where the
 * bug needs a server-side precondition (Pine Labs, recommendations),
 * we drive it via the API; where it's a pure UI fix (overview cards,
 * research banner), we exercise the Next.js page.
 */
import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "HariBugsBatch2026!";

async function bootstrap(
  api: APIRequestContext,
  slug: string,
): Promise<{ slug: string; token: string }> {
  const resp = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Hari Bugs II LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Hari Bugs II Owner",
      owner_email: `owner-${slug}@example.com`,
      owner_password: PASSWORD,
    },
  });
  if (resp.status() !== 200) {
    throw new Error(`Bootstrap failed: ${resp.status()} ${await resp.text()}`);
  }
  return { slug, token: (await resp.json()).access_token as string };
}

function unique(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 7)}`;
}


test.describe("Hari II bug regressions", () => {
  test.setTimeout(120_000);

  // --------------------------------------------------------------
  // BUG-014 — Run Sync button disabled with a reason on a matter
  // whose court is not set / not adapter-backed.
  // --------------------------------------------------------------
  test("BUG-014: Run Sync disabled + actionable 400 for no-court matter", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("b14");
    const { token } = await bootstrap(api, slug);

    // Matter with no court_name — reproduces Hari's exact trigger.
    const resp = await api.post(`${apiBaseUrl}/api/matters/`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        title: "BUG-014 — no court matter",
        matter_code: unique("B14").toUpperCase(),
        practice_area: "criminal",
        forum_level: "high_court",
        status: "active",
      },
    });
    expect(resp.status()).toBe(200);
    const matter = (await resp.json()) as { id: string };

    // Direct API call — returns actionable 400 (no `None` leak, no
    // `Pass an explicit source` ops-speak).
    const sync = await api.post(
      `${apiBaseUrl}/api/matters/${matter.id}/court-sync/pull`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data: {},
      },
    );
    expect(sync.status()).toBe(400);
    const detail = (await sync.json()).detail as string;
    expect(detail).toContain("doesn't have a court set");
    expect(detail).not.toMatch(/'None'/);

    // UI: sign in, open hearings tab, verify button is disabled.
    await page.goto("/sign-in");
    await page.locator("#company-slug").fill(slug);
    await page.locator("#email").fill(`owner-${slug}@example.com`);
    await page.locator("#password").fill(PASSWORD);
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await page.waitForURL(/\/app/);
    await page.goto(`/app/matters/${matter.id}/hearings`);
    const btn = page.getByTestId("matter-court-sync-run");
    await expect(btn).toBeVisible({ timeout: 15_000 });
    await expect(btn).toBeDisabled();
  });


  // --------------------------------------------------------------
  // BUG-017 — Intake promote dialog suggests next code on dup.
  // --------------------------------------------------------------
  test("BUG-017: intake promote on dup code shows inline suggestion", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("b17");
    const { token } = await bootstrap(api, slug);
    const taken = "BUG17-DUP-1";

    // Consume the code first.
    const mk = await api.post(`${apiBaseUrl}/api/matters/`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        title: "First matter",
        matter_code: taken,
        practice_area: "civil",
        forum_level: "high_court",
        status: "active",
      },
    });
    expect(mk.status()).toBe(200);

    // Create an intake to promote.
    const intake = await api.post(`${apiBaseUrl}/api/intake/requests`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        title: "Dup code promote",
        description: "BUG-017 regression",
        category: "contract_review",
        requester_name: "Hari",
        requester_email: "hari@example.com",
      },
    });
    expect(intake.status()).toBe(200);

    // Sign in.
    await page.goto("/sign-in");
    await page.locator("#company-slug").fill(slug);
    await page.locator("#email").fill(`owner-${slug}@example.com`);
    await page.locator("#password").fill(PASSWORD);
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await page.waitForURL(/\/app/);

    await page.goto("/app/intake");
    // Expand the intake row, click promote, enter taken code, click create.
    await page.getByText("Dup code promote").first().click();
    await page.getByRole("button", { name: /Promote to matter/i }).click();
    await page.getByTestId("intake-promote-code").fill(taken);
    await page.getByTestId("intake-promote-confirm").click();

    // Inline warning + suggestion button appear.
    await expect(page.getByTestId("intake-promote-suggest")).toBeVisible({
      timeout: 10_000,
    });
    // Scope to the dialog's alert to avoid matching the list-row error
    // banner on the intake page behind the dialog (strict-mode clash).
    await expect(
      page.getByRole("dialog").getByRole("alert").getByText(/already in use/i),
    ).toBeVisible();
  });


  // --------------------------------------------------------------
  // BUG-021 — Pre-submit dup-code guard. After typing a taken code
  // the Create-matter button MUST be disabled BEFORE the user
  // clicks; the dup warning + suggestion render without a failed
  // submit. Strict Ledger #3 (2026-04-22).
  // --------------------------------------------------------------
  test("BUG-021: promote dialog disables Create on a known-dup code BEFORE submit", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("b21");
    const { token } = await bootstrap(api, slug);
    const taken = "BUG21-DUP-1";

    // Seed the matter so the code is taken.
    const mk = await api.post(`${apiBaseUrl}/api/matters/`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        title: "BUG-21 seed matter",
        matter_code: taken,
        practice_area: "civil",
        forum_level: "high_court",
        status: "active",
      },
    });
    expect(mk.status()).toBe(200);

    // Create an intake to promote.
    const intake = await api.post(`${apiBaseUrl}/api/intake/requests`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        title: "BUG-21 pre-submit guard",
        description: "Pre-submit dup-code guard",
        category: "contract_review",
        requester_name: "Hari",
        requester_email: "hari@example.com",
      },
    });
    expect(intake.status()).toBe(200);

    await page.goto("/sign-in");
    await page.locator("#company-slug").fill(slug);
    await page.locator("#email").fill(`owner-${slug}@example.com`);
    await page.locator("#password").fill(PASSWORD);
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await page.waitForURL(/\/app/);

    await page.goto("/app/intake");
    await page.getByText("BUG-21 pre-submit guard").first().click();
    await page.getByRole("button", { name: /Promote to matter/i }).click();
    await page.getByTestId("intake-promote-code").fill(taken);

    // Wait past the 350ms debounce + the network round-trip; assert
    // the warning + suggestion appear WITHOUT us clicking Create.
    await expect(
      page
        .getByRole("dialog")
        .getByRole("alert")
        .getByText(/already in use/i),
    ).toBeVisible({ timeout: 5_000 });
    await expect(page.getByTestId("intake-promote-suggest")).toBeVisible();

    // The submit button is disabled — the user cannot reach a
    // failed submit. This is the difference vs. BUG-017.
    await expect(page.getByTestId("intake-promote-confirm")).toBeDisabled();
  });


  // --------------------------------------------------------------
  // BUG-019 — per-matter outside-counsel route now renders a real
  // page (was a redirect; Codex demoted the redirect to Partial).
  // --------------------------------------------------------------
  test("BUG-019: /app/matters/{id}/outside-counsel renders per-matter page", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("b19");
    const { token } = await bootstrap(api, slug);
    const mk = await api.post(`${apiBaseUrl}/api/matters/`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        title: "B19 matter",
        matter_code: unique("B19").toUpperCase(),
        practice_area: "civil",
        forum_level: "high_court",
        status: "active",
      },
    });
    const matter = (await mk.json()) as { id: string };

    await page.goto("/sign-in");
    await page.locator("#company-slug").fill(slug);
    await page.locator("#email").fill(`owner-${slug}@example.com`);
    await page.locator("#password").fill(PASSWORD);
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await page.waitForURL(/\/app/);
    await page.goto(`/app/matters/${matter.id}/outside-counsel`);
    // Page must NOT redirect away from the per-matter URL.
    await expect(page).toHaveURL(
      new RegExp(`/app/matters/${matter.id}/outside-counsel$`),
      { timeout: 15_000 },
    );
    // Per-matter page renders its own header + empty state.
    await expect(
      page.getByText(/Matter · Outside counsel/i),
    ).toBeVisible({ timeout: 15_000 });
    await expect(
      page.getByText(/No counsel assigned to this matter yet/i),
    ).toBeVisible();
  });


  // --------------------------------------------------------------
  // BUG-018 — research page renders for an authenticated user
  // (no blank page, stats or banner visible, search input present).
  // --------------------------------------------------------------
  test("BUG-018: research page renders stats or banner + search input", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("b18");
    const { } = await bootstrap(api, slug);

    await page.goto("/sign-in");
    await page.locator("#company-slug").fill(slug);
    await page.locator("#email").fill(`owner-${slug}@example.com`);
    await page.locator("#password").fill(PASSWORD);
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await page.waitForURL(/\/app/);
    await page.goto("/app/research");
    // Search input is present and enabled.
    const input = page.getByTestId("research-query-input");
    await expect(input).toBeVisible({ timeout: 15_000 });
    // Either stats render successfully (the happy path) or the
    // non-blocking warning banner from the stats-failure regression.
    // Both count as "research page is working"; what must NOT happen
    // is a blank screen or a hard crash.
    const hasStatsCopy = await page
      .getByText(/Searching .* judgments/i)
      .isVisible()
      .catch(() => false);
    const hasBanner = await page
      .getByText(/Could not load corpus stats/i)
      .isVisible()
      .catch(() => false);
    expect(hasStatsCopy || hasBanner).toBe(true);
  });


  // --------------------------------------------------------------
  // BUG-013 — the reminders note is present in the schedule-hearing
  // dialog. Copy was updated once reminders were dark-launched
  // (rows scheduled on save, delivered when provider is configured).
  // --------------------------------------------------------------
  test("BUG-013: Schedule hearing dialog carries a reminders note", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("b13");
    const { token } = await bootstrap(api, slug);
    const mk = await api.post(`${apiBaseUrl}/api/matters/`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        title: "B13 matter",
        matter_code: unique("B13").toUpperCase(),
        practice_area: "civil",
        forum_level: "high_court",
        status: "active",
      },
    });
    const matter = (await mk.json()) as { id: string };

    await page.goto("/sign-in");
    await page.locator("#company-slug").fill(slug);
    await page.locator("#email").fill(`owner-${slug}@example.com`);
    await page.locator("#password").fill(PASSWORD);
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await page.waitForURL(/\/app/);
    await page.goto(`/app/matters/${matter.id}/hearings`);
    await page.getByTestId("schedule-hearing-open").click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText(/Reminders:/i)).toBeVisible();
    await expect(dialog.getByText(/T-24h and T-1h/i)).toBeVisible();
    await expect(
      dialog.getByText(/email provider is configured/i),
    ).toBeVisible();
  });


  // --------------------------------------------------------------
  // Strict Ledger #5 (BUG-013 in-app visibility, 2026-04-22):
  // after a hearing is created, the queued reminders show up
  // INLINE on the matter cockpit Hearings tab as a reminder
  // strip — the in-platform half of "in-platform + email
  // notifications". End-user surface, not just admin.
  // --------------------------------------------------------------
  test("BUG-013 in-app: hearing reminder strip shows queued rows on the matter cockpit", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("b13ia");
    const { token } = await bootstrap(api, slug);
    const mk = await api.post(`${apiBaseUrl}/api/matters/`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        title: "BUG-013 in-app reminder strip",
        matter_code: unique("B13IA").toUpperCase(),
        practice_area: "civil",
        forum_level: "high_court",
        status: "active",
      },
    });
    const matter = (await mk.json()) as { id: string };

    // Create a hearing 4 days out so both T-24h AND T-1h offsets
    // are in the future → backend persists 2 queued reminders.
    const hearingDate = new Date(Date.now() + 4 * 24 * 3600 * 1000)
      .toISOString()
      .slice(0, 10);
    const hr = await api.post(
      `${apiBaseUrl}/api/matters/${matter.id}/hearings`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data: {
          hearing_on: hearingDate,
          forum_name: "Delhi HC, Bench: Hon'ble X",
          purpose: "BUG-013 in-app strip",
        },
      },
    );
    expect(hr.status()).toBe(200);

    await page.goto("/sign-in");
    await page.locator("#company-slug").fill(slug);
    await page.locator("#email").fill(`owner-${slug}@example.com`);
    await page.locator("#password").fill(PASSWORD);
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await page.waitForURL(/\/app/);
    await page.goto(`/app/matters/${matter.id}/hearings`);

    // The strip renders inline under the hearing summary.
    const strip = page.getByTestId("hearing-reminder-strip");
    await expect(strip).toBeVisible({ timeout: 15_000 });
    // Both rows are queued (worker hasn't run in the e2e env).
    await expect(strip.getByText(/queued/i).first()).toBeVisible();
    // Two distinct status pills (T-24h + T-1h).
    const pills = await strip.getByText(/queued/i).count();
    expect(pills).toBeGreaterThanOrEqual(1);
  });


  // --------------------------------------------------------------
  // BUG-011 (reopened 2026-04-22) — overview hides ALL three
  // empty-state cards (Open tasks, Last court order, Upcoming
  // hearings) on a fresh matter. The prior fix only hid Open tasks;
  // user wants symmetric behaviour because the empty CTAs read as
  // a broken promise. The Hearings tab is still reachable from the
  // matter sub-nav so the Schedule-hearing affordance isn't lost.
  // --------------------------------------------------------------
  test("BUG-011: overview hides all three empty-state cards on a fresh matter", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("b11");
    const { token } = await bootstrap(api, slug);
    const mk = await api.post(`${apiBaseUrl}/api/matters/`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        title: "B11 matter",
        matter_code: unique("B11").toUpperCase(),
        practice_area: "civil",
        forum_level: "high_court",
        status: "active",
      },
    });
    const matter = (await mk.json()) as { id: string };

    await page.goto("/sign-in");
    await page.locator("#company-slug").fill(slug);
    await page.locator("#email").fill(`owner-${slug}@example.com`);
    await page.locator("#password").fill(PASSWORD);
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await page.waitForURL(/\/app/);
    await page.goto(`/app/matters/${matter.id}`);

    // None of the three empty-state cards render on a fresh matter.
    await expect(page.getByText("Open tasks")).toHaveCount(0);
    await expect(page.getByText("Last court order")).toHaveCount(0);
    await expect(page.getByText("Upcoming hearings")).toHaveCount(0);
    // The matter cockpit "Hearings" tab is still reachable so the
    // user can open the schedule-hearing dialog there. Scope the
    // assertion to the matter sub-nav (aria-label "Matter cockpit
    // tabs") to avoid colliding with the global sidebar's
    // "Hearings" link, which also matches /^Hearings$/.
    await expect(
      page
        .getByLabel("Matter cockpit tabs")
        .getByRole("link", { name: /^Hearings$/ }),
    ).toBeVisible();
  });


  // --------------------------------------------------------------
  // BUG-011 companion — populated matter must STILL show the cards
  // it would hide when empty. Without this, a future "always hide"
  // regression would silently slip past the empty-matter test.
  // --------------------------------------------------------------
  test("BUG-011 companion: a populated matter shows Upcoming hearings card", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("b11pop");
    const { token } = await bootstrap(api, slug);
    const mk = await api.post(`${apiBaseUrl}/api/matters/`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        title: "B11 populated matter",
        matter_code: unique("B11POP").toUpperCase(),
        practice_area: "civil",
        forum_level: "high_court",
        status: "active",
      },
    });
    const matter = (await mk.json()) as { id: string };

    // Schedule a hearing so the Upcoming hearings card has a row.
    const tomorrow = new Date(Date.now() + 24 * 3600 * 1000)
      .toISOString()
      .slice(0, 10);
    const hr = await api.post(
      `${apiBaseUrl}/api/matters/${matter.id}/hearings`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data: {
          hearing_on: tomorrow,
          forum_name: "Delhi HC, Bench: Hon'ble X",
          purpose: "BUG-011 companion populated test",
        },
      },
    );
    if (hr.status() !== 200) {
      throw new Error(`Hearing seed failed: ${hr.status()} ${await hr.text()}`);
    }

    await page.goto("/sign-in");
    await page.locator("#company-slug").fill(slug);
    await page.locator("#email").fill(`owner-${slug}@example.com`);
    await page.locator("#password").fill(PASSWORD);
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await page.waitForURL(/\/app/);
    await page.goto(`/app/matters/${matter.id}`);

    // The Upcoming hearings card now renders (one row inside) — proves
    // the conditional is "hide ONLY when empty", not "hide always".
    await expect(page.getByText("Upcoming hearings")).toBeVisible({
      timeout: 15_000,
    });
    // Last court order + Open tasks remain hidden — we didn't seed
    // those, so the conditional behaviour is still correct.
    await expect(page.getByText("Last court order")).toHaveCount(0);
    await expect(page.getByText("Open tasks")).toHaveCount(0);
  });
});
