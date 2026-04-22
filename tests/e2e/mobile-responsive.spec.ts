/**
 * Strict Ledger #6 (2026-04-22) — mobile / responsive proof for the
 * Ram bug batch (BUG-004, BUG-005, BUG-006). The original commits
 * (29d6b65 + 7376873) shipped grid-cols-1 sm:grid-cols-2, mandatory
 * Dialog max-h+overflow, and a Topbar hamburger trigger — but only
 * desktop Playwright proved them. The bug-fixing skill rejects
 * desktop-only proof for mobile bugs.
 *
 * Every test in this file is tagged `[mobile]` so the
 * `app-mobile` project picks them up. The project is configured
 * with `devices['iPhone 13']` (390x844, touch, Mobile Safari UA).
 * If a future fix breaks the dialog footer or the hamburger nav on
 * a phone-class viewport, these tests fail loudly.
 */
import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "MobileProof2026!Strong";

async function bootstrap(
  api: APIRequestContext,
  slug: string,
): Promise<{ slug: string; token: string }> {
  const resp = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Mobile Proof LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Mobile Owner",
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
  return `${prefix}-${Math.random().toString(36).slice(2, 6)}`;
}

async function signIn(page: import("@playwright/test").Page, slug: string) {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(`owner-${slug}@example.com`);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app/);
}

test.describe("Mobile / responsive proofs [mobile]", () => {
  test.setTimeout(120_000);

  // ---------------------------------------------------------------
  // Ram-BUG-005 — Topbar hamburger MUST be visible + functional on
  // a phone-class viewport. The desktop sidebar is `hidden md:flex`,
  // so without the hamburger the user has no nav at all.
  // ---------------------------------------------------------------
  test("Ram-BUG-005 [mobile]: Topbar hamburger opens nav drawer + auto-closes on navigate", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("m5");
    await bootstrap(api, slug);
    await signIn(page, slug);
    await page.goto("/app");

    // Sidebar (`hidden md:flex`) is invisible at this viewport.
    const sidebar = page.locator('aside[aria-label="Primary navigation"]');
    await expect(sidebar).toBeHidden();

    // Hamburger trigger IS visible and opens the drawer.
    const trigger = page.getByTestId("mobile-nav-trigger");
    await expect(trigger).toBeVisible();
    await trigger.tap();

    const drawer = page.getByRole("dialog", { name: /workspace navigation/i });
    await expect(drawer).toBeVisible();

    // The drawer body contains the same nav items the desktop
    // sidebar would. Tap one and assert two things:
    //  1) the URL changes (navigation happened)
    //  2) the drawer auto-closes (so the user lands cleanly)
    await drawer.getByRole("link", { name: /Matters/ }).first().tap();
    await page.waitForURL(/\/app\/matters/);
    await expect(drawer).toBeHidden();
  });

  // ---------------------------------------------------------------
  // Ram-BUG-004 / Ram-BUG-006 — Dialog forms must not clip the
  // submit/cancel footer on a phone-class viewport. The fix added
  // `max-h-[90vh] overflow-y-auto` to DialogContent + stacked the
  // grid-cols-2 fields with a `grid-cols-1 sm:` prefix.
  // ---------------------------------------------------------------
  test("Ram-BUG-004 [mobile]: New Contract dialog footer remains reachable", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("m4");
    await bootstrap(api, slug);
    await signIn(page, slug);
    await page.goto("/app/contracts");

    // Two triggers exist on a fresh contracts page (header + empty
    // state). Tap the first.
    await page.getByTestId("new-contract-trigger").first().tap();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    // The submit + cancel buttons must be inside a scrollable
    // container — at the iPhone-13 viewport (390x844) the form is
    // taller than the dialog, so the footer is below the fold
    // until scrolled. scrollIntoViewIfNeeded() proves it's
    // REACHABLE (would fail if the footer were clipped behind
    // overflow-hidden — exactly the BUG-004 symptom).
    const submit = dialog.getByRole("button", { name: /Create contract/i });
    await submit.scrollIntoViewIfNeeded();
    await expect(submit).toBeVisible();
    const cancel = dialog.getByRole("button", { name: /^Cancel$/ });
    await cancel.scrollIntoViewIfNeeded();
    await expect(cancel).toBeVisible();

    // The two-column field grid must stack on mobile — the Code +
    // Type inputs sit on different rows. Compare bounding-box
    // y-coordinates: Type's top should be below Code's bottom.
    const codeBox = await dialog.locator("#contract-code").boundingBox();
    const typeBox = await dialog.locator("#contract-type").boundingBox();
    expect(codeBox).not.toBeNull();
    expect(typeBox).not.toBeNull();
    if (codeBox && typeBox) {
      expect(typeBox.y).toBeGreaterThanOrEqual(codeBox.y + codeBox.height - 2);
    }
  });

  // ---------------------------------------------------------------
  // Ram-BUG-006 — same shape as BUG-004 but for the New Counsel
  // dialog, which the original report referenced via
  // /app/outside-counsel.
  // ---------------------------------------------------------------
  test("Ram-BUG-006 [mobile]: New Counsel dialog footer remains reachable on /app/outside-counsel", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("m6");
    await bootstrap(api, slug);
    await signIn(page, slug);
    await page.goto("/app/outside-counsel");

    // Two triggers (header + empty-state CTA) on a fresh tenant.
    await page.getByTestId("new-counsel-trigger").first().tap();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    const submit = dialog.getByTestId("new-counsel-submit");
    await submit.scrollIntoViewIfNeeded();
    await expect(submit).toBeVisible();
    await expect(submit).toHaveText(/Add to panel/);
    const cancel = dialog.getByRole("button", { name: /^Cancel$/ });
    await cancel.scrollIntoViewIfNeeded();
    await expect(cancel).toBeVisible();
  });
});
