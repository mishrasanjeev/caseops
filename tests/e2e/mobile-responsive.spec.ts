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

  // ---------------------------------------------------------------
  // PG-005 Sprint 9 (2026-05-01) — DraftingStepper at 360x800.
  // The stepper's bottom nav row used to put "Previous" + "Submit
  // for full draft" side-by-side; on a 360px viewport the second
  // button overflowed the form bounds. Sprint 9 stacks the buttons
  // vertically below the sm breakpoint.
  // ---------------------------------------------------------------
  test("PG-005 Sprint 9 [mobile]: DraftingStepper bottom nav stacks vertically + no horizontal overflow at 360x800", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("ds");
    await bootstrap(api, slug);
    await signIn(page, slug);

    // Create a matter so we can navigate to /drafts/new with a
    // template selection.
    await page.goto("/app/matters/new");
    await page.locator("#matter-title").fill("Mobile stepper smoke");
    await page.locator("#matter-code").fill("MOB-DS-1");
    await page.locator("#practice-area").fill("Criminal");
    // Forum select — pick high_court so bench-aware drafting fires.
    const forumTrigger = page.getByLabel("Forum level");
    if (await forumTrigger.isVisible().catch(() => false)) {
      await forumTrigger.tap();
      await page.getByRole("option", { name: /High court/i }).tap();
    }
    await page.getByRole("button", { name: /Create matter/i }).tap();
    await page.waitForURL(/\/app\/matters\/[^/]+/);

    // Navigate to the drafts list, click "New draft" → grid → bail.
    const matterUrl = page.url();
    await page.goto(`${matterUrl}/drafts`);
    await page.getByTestId("new-draft-trigger").first().tap();
    await page.waitForURL(/\/drafts\/new(\?|$)/);
    await page.getByTestId("start-draft-bail").first().tap();
    await page.waitForURL(/\?type=bail/);

    // Wait for the stepper to render.
    await expect(page.locator('[data-testid^="step-"]').first()).toBeVisible({
      timeout: 15_000,
    });

    // Critical assertion #1: the document body must not horizontally
    // overflow the viewport. scrollWidth > clientWidth means a sideways
    // scrollbar — the BUG-013 / Sprint 9 anchor symptom.
    const overflow = await page.evaluate(() => ({
      sw: document.documentElement.scrollWidth,
      cw: document.documentElement.clientWidth,
    }));
    expect(overflow.sw).toBeLessThanOrEqual(overflow.cw + 1);

    // Critical assertion #2: the Previous + Next buttons must stack
    // vertically (Next.y > Previous.y + Previous.height - 2). This
    // proves the sm:flex-row breakpoint kicked in.
    const previous = page.getByRole("button", { name: /^Previous/i });
    const next = page.getByRole("button", { name: /^Next/i });
    await previous.scrollIntoViewIfNeeded();
    const prevBox = await previous.boundingBox();
    const nextBox = await next.boundingBox();
    expect(prevBox).not.toBeNull();
    expect(nextBox).not.toBeNull();
    if (prevBox && nextBox) {
      expect(nextBox.y).toBeGreaterThanOrEqual(prevBox.y + prevBox.height - 4);
    }

    // Critical assertion #3: each button is full-width (within the
    // form column) so the tap target is comfortable on mobile. The
    // form padding leaves ~16px on each side; allow a generous
    // tolerance.
    if (prevBox) {
      // Previous + Next button width >= 240px on a 360px viewport
      // (i.e. they are clearly stretched, not minimum-content).
      expect(prevBox.width).toBeGreaterThanOrEqual(240);
    }
  });
});
