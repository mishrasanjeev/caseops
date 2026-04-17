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

    for (const label of ["Product", "Workflows", "Security", "Pricing", "FAQ"]) {
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

  test("legacy app route is not indexed", async ({ page }) => {
    const response = await page.goto("/legacy");
    expect(response?.status()).toBe(200);
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute(
      "content",
      /noindex/i,
    );
  });
});
