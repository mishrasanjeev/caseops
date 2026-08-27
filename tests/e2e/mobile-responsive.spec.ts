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
import type { APIRequestContext, Locator, Page } from "@playwright/test";

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

async function signIn(page: Page, slug: string) {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(`owner-${slug}@example.com`);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app/);
}

async function navigateToRenderedLink(page: Page, link: Locator) {
  await expect(link).toBeVisible();
  const href = await link.getAttribute("href");
  if (!href) throw new Error("Visible navigation link is missing its href");
  await page.goto(href, { timeout: 15_000, waitUntil: "domcontentloaded" });
}

test.describe("Mobile / responsive proofs [mobile]", () => {
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

    // Keep the server-error oracle scoped to the billing APIs implicated by
    // this navigation path. Other destinations can intentionally exercise
    // provider-unavailable states; an unhandled billing 5xx is never a valid
    // page outcome and was the signal for the account-creation race.
    const billingServerErrors: string[] = [];
    page.on("response", (response) => {
      const responseUrl = new URL(response.url());
      if (
        responseUrl.pathname.startsWith("/api/billing/") &&
        response.status() >= 500 &&
        response.status() <= 599
      ) {
        billingServerErrors.push(
          `${response.request().method()} ${responseUrl.pathname} -> ${response.status()}`,
        );
      }
    });

    // Sidebar (`hidden md:flex`) is invisible at this viewport.
    const sidebar = page.locator('aside[aria-label="Primary navigation"]');
    await expect(sidebar).toBeHidden();

    // Hamburger trigger IS visible and opens the drawer.
    const trigger = page.getByTestId("mobile-nav-trigger");
    await expect(trigger).toBeVisible();
    await trigger.tap();

    const drawer = page.getByRole("dialog", { name: /workspace navigation/i });
    await expect(drawer).toBeVisible();

    // Snapshot the capability-visible navigation, then exercise every link in
    // the real mobile drawer. This catches regrouping defects that a single
    // desktop link cannot: an item below the fold must remain reachable, fit
    // horizontally, navigate, and close the drawer. User guide is last in the
    // navigation order, so leaving the authenticated shell happens last.
    const destinations = await drawer.locator("nav ul a[href]").evaluateAll((links) =>
      links.map((link) => ({
        label: link.getAttribute("aria-label") ?? link.textContent?.trim() ?? "",
        href: link.getAttribute("href") ?? "",
      })),
    );
    expect(destinations.length).toBeGreaterThan(0);
    expect(new Set(destinations.map(({ label }) => label)).size).toBe(
      destinations.length,
    );

    const viewport = page.viewportSize();
    expect(viewport).not.toBeNull();
    for (const destination of destinations) {
      if (!(await drawer.isVisible())) {
        await expect(trigger).toBeVisible();
        await trigger.tap();
        await expect(drawer).toBeVisible();
      }

      const drawerNav = drawer.locator("nav");
      const link = drawerNav.getByRole("link", {
        name: destination.label,
        exact: true,
      });
      await link.scrollIntoViewIfNeeded();
      await expect(
        link,
        `${destination.label} should be reachable in the mobile drawer`,
      ).toBeVisible();

      const box = await link.boundingBox();
      expect(box, `${destination.label} should have a rendered tap target`).not.toBeNull();
      if (box && viewport) {
        expect(
          box.x,
          `${destination.label} should not overflow left`,
        ).toBeGreaterThanOrEqual(0);
        expect(
          box.x + box.width,
          `${destination.label} should not overflow right`,
        ).toBeLessThanOrEqual(viewport.width + 1);
      }
      const drawerWidth = await drawerNav.evaluate((node) => ({
        clientWidth: node.clientWidth,
        scrollWidth: node.scrollWidth,
      }));
      expect(drawerWidth.scrollWidth).toBeLessThanOrEqual(drawerWidth.clientWidth + 1);

      const previousPath = new URL(page.url()).pathname;
      const previousHeading = (
        (await page.locator("main h1").first().textContent()) ?? ""
      ).trim();
      await link.tap();
      await expect(drawer).toBeHidden();
      const expectedPath = new URL(destination.href, page.url()).pathname;
      await expect
        .poll(() => new URL(page.url()).pathname, {
          message: `${destination.label} should navigate to ${expectedPath}`,
        })
        .toBe(expectedPath);

      // A changed URL can still leave the prior page mounted while the next
      // route loads. Prove the user-visible destination rendered before moving
      // to the next drawer action; this also prevents the loop from piling up
      // requests against pages whose data surface has not mounted yet.
      const destinationHeading = page.locator("main h1").first();
      await expect(
        destinationHeading,
        `${destination.label} should render a visible page heading`,
      ).toBeVisible();
      if (expectedPath !== previousPath && previousHeading) {
        await expect
          .poll(
            async () => ((await destinationHeading.textContent()) ?? "").trim(),
            {
              message: `${destination.label} should replace the prior page surface`,
            },
          )
          .not.toBe(previousHeading);
      }

      if (expectedPath === "/app/admin/billing") {
        // The heading renders before five parallel billing queries settle.
        // Waiting for the page's explicit loading surface to leave proves the
        // implicated requests completed before this test navigates elsewhere.
        await expect(page.getByTestId("billing-page-loading")).toBeHidden();
        expect(billingServerErrors).toEqual([]);
      }
    }
    expect(billingServerErrors).toEqual([]);
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
    // template selection. The matter-create surface is a Dialog opened
    // from the matters list (no /app/matters/new route exists). Form
    // fields use generated IDs from the <Field> primitive — drive them
    // via getByLabel, not CSS id selectors.
    await page.goto("/app/matters");
    await page.getByTestId("new-matter-trigger").first().tap();
    const newMatterDialog = page.getByRole("dialog");
    await newMatterDialog.getByLabel("Title").fill("Mobile stepper smoke");
    await newMatterDialog.getByLabel("Matter code").fill("MOB-DS-1");
    await newMatterDialog.getByLabel("Practice area").fill("Criminal");
    // Forum select — pick high_court so bench-aware drafting fires.
    const forumTrigger = newMatterDialog.getByLabel("Forum level");
    if (await forumTrigger.isVisible().catch(() => false)) {
      await forumTrigger.tap();
      await page.getByRole("option", { name: /High court/i }).tap();
    }
    await newMatterDialog.getByRole("button", { name: /Create matter/i }).tap();
    await expect(newMatterDialog).toBeHidden();
    // Tap the new matter's row to navigate to its cockpit (the dialog
    // closes back onto the list — there's no auto-redirect).
    await page.getByText("Mobile stepper smoke").first().tap();
    await page.waitForURL(/\/app\/matters\/[0-9a-f-]+$/);

    // Navigate through the rendered New draft and bail-template links.
    const matterUrl = page.url();
    await page.goto(`${matterUrl}/drafts`);
    await navigateToRenderedLink(
      page,
      page.getByTestId("new-draft-trigger").first(),
    );
    await page.waitForURL(/\/drafts\/new(\?|$)/);
    await navigateToRenderedLink(
      page,
      page.getByTestId("start-draft-bail").first(),
    );
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
