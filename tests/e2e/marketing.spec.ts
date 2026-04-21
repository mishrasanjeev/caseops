import { expect, test } from "@playwright/test";

test.describe("Marketing site", () => {
  test("landing page renders primary copy, navigation, and SEO surface", async ({ page }) => {
    const response = await page.goto("/");
    expect(response?.status()).toBe(200);

    await expect(page).toHaveTitle(/CaseOps — The matter-native legal operating system/);

    const canonical = page.locator('link[rel="canonical"]');
    await expect(canonical).toHaveAttribute("href", /caseops\.ai/);

    await expect(page.locator('meta[name="description"]')).toHaveAttribute(
      "content",
      /matter management/i,
    );
    await expect(page.locator('meta[property="og:image"]').first()).toHaveAttribute(
      "content",
      /opengraph-image/,
    );
    await expect(page.locator('meta[name="twitter:card"]')).toHaveAttribute(
      "content",
      "summary_large_image",
    );

    const jsonLdCount = await page
      .locator('script[type="application/ld+json"]')
      .count();
    expect(jsonLdCount).toBeGreaterThanOrEqual(3);

    await expect(
      page.getByRole("heading", { level: 1, name: /operating system for/i }),
    ).toBeVisible();

    await expect(page.getByRole("link", { name: "Sign in" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Request a demo" }).first()).toBeVisible();

    // Nav now links to segment + guide pages instead of on-page anchors (see siteConfig.nav.primary).
    for (const label of ["Product", "Pricing", "Law firms", "General counsels", "Solo lawyers", "Guide"]) {
      await expect(
        page.getByRole("link", { name: label, exact: true }).first(),
      ).toBeVisible();
    }

    await expect(page.getByRole("heading", { name: /Matter Cockpit/ })).toBeVisible();
    await expect(page.getByRole("heading", { name: /Drafting Studio/ })).toBeVisible();
    await expect(page.getByRole("heading", { name: /Hearing Prep/ })).toBeVisible();
    await expect(page.getByRole("heading", { name: /Trust Plane/ })).toBeVisible();
  });

  test("FAQ panels expand and collapse", async ({ page }) => {
    await page.goto("/");
    const secondBtn = page.getByRole("button", {
      name: /How does CaseOps avoid hallucinated citations/,
    });
    const secondPanel = page.locator("#faq-panel-1");
    await expect(secondPanel).toBeHidden();

    await secondBtn.scrollIntoViewIfNeeded();
    await secondBtn.click();
    await expect(secondPanel).toBeVisible();
    await expect(secondPanel).toContainText(/retrieval and source systems/i);

    const firstPanel = page.locator("#faq-panel-0");
    await expect(firstPanel).toBeHidden();
  });

  test("robots and sitemap are served", async ({ request }) => {
    const robots = await request.get("/robots.txt");
    expect(robots.status()).toBe(200);
    const robotsText = await robots.text();
    expect(robotsText).toMatch(/User-Agent: \*/i);
    expect(robotsText).toMatch(/Disallow: \/app/);
    expect(robotsText).toMatch(/Sitemap: /);

    const sitemap = await request.get("/sitemap.xml");
    expect(sitemap.status()).toBe(200);
    const sitemapText = await sitemap.text();
    expect(sitemapText).toContain("<urlset");
    expect(sitemapText).toContain("<loc>");
  });

  test("Open Graph image route returns a PNG", async ({ request }) => {
    const res = await request.get("/opengraph-image");
    expect(res.status()).toBe(200);
    expect(res.headers()["content-type"]).toMatch(/image\/png/);
    const body = await res.body();
    expect(body.byteLength).toBeGreaterThan(5000);
  });

  test("demo request API validates input", async ({ request }) => {
    const ok = await request.post("/api/demo-request", {
      data: {
        name: "Asha Rao",
        email: "asha@example.com",
        company: "Rao Legal LLP",
        role: "Partner",
      },
    });
    expect(ok.status()).toBe(202);
    expect(await ok.json()).toEqual({ accepted: true });

    const bad = await request.post("/api/demo-request", {
      data: { name: "x" },
    });
    expect(bad.status()).toBe(400);

    const badEmail = await request.post("/api/demo-request", {
      data: { name: "x", email: "not-an-email", company: "c", role: "r" },
    });
    expect(badEmail.status()).toBe(400);
  });

  test("demo form on the landing page submits successfully", async ({ page }) => {
    await page.goto("/#cta");
    const form = page.locator("form[aria-label='Request a demo']");
    await form.locator("input[name='name']").fill("Asha Rao");
    await form.locator("input[name='email']").fill("asha@example.com");
    await form.locator("input[name='company']").fill("Rao Legal LLP");
    await form.locator("select[name='role']").selectOption({ index: 1 });
    await form.getByRole("button", { name: /Request a demo/i }).click();
    await expect(page.getByText(/we'll be in touch within a working day/i)).toBeVisible();
  });

  test("every CTA on the landing page leads somewhere (not a dead mailto or 404)", async ({
    page,
    request,
  }) => {
    // Regression guard: the Pricing "Talk to sales" card shipped as a
    // raw `mailto:` once, which does nothing in browsers without a
    // default mail client — the user has to go back to the form. This
    // test walks every link/button on the landing page and verifies:
    //   - hash anchors point at something that actually exists on the page
    //   - internal routes return 200
    //   - mailto: links carry a non-empty address
    // External https links are skipped (we don't want to spider the web
    // on every CI run), but at least their href is logged.
    await page.goto("/");

    const hrefs = await page.$$eval("main a[href], header a[href]", (els) =>
      Array.from(new Set(els.map((el) => (el as HTMLAnchorElement).getAttribute("href") ?? ""))),
    );

    expect(hrefs.length).toBeGreaterThan(0);

    const deadLinks: string[] = [];

    for (const href of hrefs) {
      if (!href) {
        deadLinks.push("(empty href)");
        continue;
      }
      if (href.startsWith("#")) {
        const id = href.slice(1);
        if (!id) continue;
        const target = page.locator(`#${id}`);
        if ((await target.count()) === 0) deadLinks.push(`${href} (no element)`);
        continue;
      }
      if (href.startsWith("mailto:")) {
        const addr = href.slice("mailto:".length).split("?")[0];
        if (!addr || !addr.includes("@")) deadLinks.push(`${href} (malformed)`);
        continue;
      }
      if (href.startsWith("/")) {
        const res = await request.get(href);
        if (res.status() >= 400) deadLinks.push(`${href} (HTTP ${res.status()})`);
        continue;
      }
      // External: skip but record. Nothing to assert in CI.
    }

    expect(deadLinks, `dead landing-page links: ${deadLinks.join(", ")}`).toEqual([]);
  });

  test("legacy route redirects into the new app", async ({ page }) => {
    // Sprint 6 parity proof: the old /legacy console is gone. Browsers
    // landing on legacy bookmarks should resolve into the new cockpit,
    // not 404.
    const response = await page.goto("/legacy");
    expect(response?.status()).toBe(200);
    // Middleware redirects before the /app sign-in gate short-circuits,
    // so we land on either /app or /sign-in depending on session state.
    await expect(page).toHaveURL(/\/(app|sign-in)/);
    expect(page.url()).not.toMatch(/\/legacy/);
  });

  test("legacy subpaths redirect into the new app", async ({ page }) => {
    const response = await page.goto("/legacy/contracts");
    expect(response?.status()).toBe(200);
    await expect(page).toHaveURL(/\/(app|sign-in)/);
    expect(page.url()).not.toMatch(/\/legacy/);
  });

  // Segment landing pages + long-form guide. Codex 2026-04-20 test-suite
  // gap audit flagged these four new routes as having zero e2e coverage.
  // Smoke test: page renders 200, carries a canonical <link>, has the
  // expected <h1>, and has no browser console errors.
  const segmentPages: { path: string; heading: RegExp; canonical: RegExp }[] = [
    {
      path: "/law-firms",
      heading: /operating system for litigation-heavy law firms/i,
      canonical: /\/law-firms$/,
    },
    {
      path: "/general-counsels",
      heading: /operating layer for in-house legal/i,
      canonical: /\/general-counsels$/,
    },
    {
      path: "/solo-lawyers",
      heading: /operate like a 20-lawyer practice\. alone\./i,
      canonical: /\/solo-lawyers$/,
    },
    {
      path: "/guide",
      heading: /how to run your practice on caseops/i,
      canonical: /\/guide$/,
    },
  ];

  for (const { path, heading, canonical } of segmentPages) {
    test(`segment landing page ${path} renders and is SEO-ready`, async ({ page }) => {
      const consoleErrors: string[] = [];
      page.on("console", (msg) => {
        if (msg.type() === "error") consoleErrors.push(msg.text());
      });

      const response = await page.goto(path);
      expect(response?.status()).toBe(200);

      // Pitch primitives (solo-lawyers, general-counsels) render slide titles as <h2>;
      // law-firms uses an inline <h1>; guide has an <h1>. Match by accessible name only.
      await expect(
        page.getByRole("heading", { name: heading }).first(),
      ).toBeVisible();

      await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
        "href",
        canonical,
      );
      await expect(page.locator('meta[name="description"]')).toHaveAttribute(
        "content",
        /CaseOps|legal|matter|practice/i,
      );

      // JSON-LD schema markup — Organization / SoftwareApplication /
      // WebSite blocks ship from layout. At least one must be present
      // on every page so SEO surfaces don't silently regress.
      const jsonLdCount = await page
        .locator('script[type="application/ld+json"]')
        .count();
      expect(jsonLdCount).toBeGreaterThanOrEqual(1);

      expect(
        consoleErrors,
        `console errors on ${path}: ${consoleErrors.join(" | ")}`,
      ).toEqual([]);
    });
  }
});
