import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const PUBLIC_SITEMAP_PATHS = [
  "/",
  "/general-counsels",
  "/guide",
  "/law-firms",
  "/pricing",
  "/resources/legal-matter-management-india",
  "/resources/source-grounded-legal-recommendations",
  "/solo-lawyers",
] as const;

const PUBLIC_CONTENT_PAGES = PUBLIC_SITEMAP_PATHS;

const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 360, height: 800 },
] as const;

const normalizeText = (value: string) => value.replace(/\s+/g, " ").trim();

type FaqEntry = { question: string; answer: string };

function findFaqDocument(value: unknown): Record<string, unknown> | undefined {
  if (Array.isArray(value)) {
    for (const item of value) {
      const match = findFaqDocument(item);
      if (match) return match;
    }
    return undefined;
  }

  if (!value || typeof value !== "object") return undefined;

  const record = value as Record<string, unknown>;
  const types = Array.isArray(record["@type"])
    ? record["@type"]
    : [record["@type"]];
  if (types.includes("FAQPage")) return record;

  for (const nested of Object.values(record)) {
    const match = findFaqDocument(nested);
    if (match) return match;
  }
  return undefined;
}

async function readUiFaq(page: Page): Promise<FaqEntry[]> {
  return page.locator("#faq li").evaluateAll((items) =>
    items.map((item) => {
      const button = item.querySelector<HTMLButtonElement>(
        'button[aria-controls^="faq-panel-"]',
      );
      const panelId = button?.getAttribute("aria-controls");
      const panel = panelId ? document.getElementById(panelId) : null;
      return {
        question: (button?.textContent ?? "").replace(/\s+/g, " ").trim(),
        answer: (panel?.textContent ?? "").replace(/\s+/g, " ").trim(),
      };
    }),
  );
}

async function readStructuredFaq(page: Page): Promise<FaqEntry[]> {
  const scriptContents = await page
    .locator('script[type="application/ld+json"]')
    .allTextContents();
  const documents = scriptContents.map((content) => JSON.parse(content) as unknown);
  const faq = documents.map(findFaqDocument).find(Boolean);

  expect(faq, "landing page must expose an FAQPage JSON-LD document").toBeDefined();

  const entities = faq?.mainEntity;
  expect(Array.isArray(entities), "FAQPage.mainEntity must be an array").toBe(true);

  return (entities as Record<string, unknown>[]).map((entity) => {
    const acceptedAnswer = Array.isArray(entity.acceptedAnswer)
      ? entity.acceptedAnswer[0]
      : entity.acceptedAnswer;
    const answer = acceptedAnswer as Record<string, unknown> | undefined;
    return {
      question: normalizeText(String(entity.name ?? "")),
      answer: normalizeText(String(answer?.text ?? "")),
    };
  });
}

async function checkInternalLinks(
  page: Page,
  request: APIRequestContext,
  pathname: string,
): Promise<string[]> {
  const response = await page.goto(pathname, { waitUntil: "domcontentloaded" });
  expect(response?.status(), `${pathname} must render successfully`).toBeLessThan(400);

  const sourceUrl = new URL(page.url());
  const hrefs = await page
    .locator("header a[href], main a[href], footer a[href]")
    .evaluateAll((links) =>
      Array.from(
        new Set(
          links.map((link) => (link as HTMLAnchorElement).getAttribute("href") ?? ""),
        ),
      ),
    );

  const issues: string[] = [];
  const statusCache = new Map<string, number>();
  const idCache = new Map<string, Set<string>>();
  const currentRoute = `${sourceUrl.pathname}${sourceUrl.search}`;
  idCache.set(
    currentRoute,
    new Set(await page.locator("[id]").evaluateAll((nodes) => nodes.map((node) => node.id))),
  );

  const probe = await page.context().newPage();
  try {
    for (const href of hrefs) {
      if (!href.trim()) {
        issues.push("empty href");
        continue;
      }

      let target: URL;
      try {
        target = new URL(href, sourceUrl);
      } catch {
        issues.push(`${href} (invalid URL)`);
        continue;
      }

      if (target.protocol === "mailto:") {
        if (!target.pathname.includes("@")) issues.push(`${href} (malformed email link)`);
        continue;
      }
      if (target.protocol === "tel:") {
        if (!target.pathname.trim()) issues.push(`${href} (empty telephone link)`);
        continue;
      }
      if (target.protocol !== "http:" && target.protocol !== "https:") {
        issues.push(`${href} (unsupported protocol ${target.protocol})`);
        continue;
      }
      if (target.origin !== sourceUrl.origin) continue;

      const route = `${target.pathname}${target.search}`;
      let status = statusCache.get(route);
      if (status === undefined) {
        const linkedResponse = await request.get(route, { failOnStatusCode: false });
        status = linkedResponse.status();
        statusCache.set(route, status);
      }
      if (status >= 400) {
        issues.push(`${href} (HTTP ${status})`);
        continue;
      }

      if (target.hash) {
        let id: string;
        try {
          id = decodeURIComponent(target.hash.slice(1));
        } catch {
          issues.push(`${href} (invalid fragment encoding)`);
          continue;
        }
        if (!id) {
          issues.push(`${href} (empty fragment)`);
          continue;
        }

        let ids = idCache.get(route);
        if (!ids) {
          const fragmentResponse = await probe.goto(route, {
            waitUntil: "domcontentloaded",
          });
          if (!fragmentResponse || fragmentResponse.status() >= 400) {
            issues.push(`${href} (fragment page did not render)`);
            continue;
          }
          ids = new Set(
            await probe
              .locator("[id]")
              .evaluateAll((nodes) => nodes.map((node) => node.id)),
          );
          idCache.set(route, ids);
        }
        if (!ids.has(id)) issues.push(`${href} (missing #${id})`);
      } else if (href === "#") {
        issues.push(`${href} (empty fragment)`);
      }
    }
  } finally {
    await probe.close();
  }

  return issues;
}

test.describe("Public landing page and user guide", () => {
  test("every public page has one primary heading and distinct crawl metadata", async ({ page }) => {
    const titles = new Set<string>();
    const descriptions = new Set<string>();

    for (const pathname of PUBLIC_SITEMAP_PATHS) {
      const response = await page.goto(pathname, { waitUntil: "domcontentloaded" });
      expect(response?.status(), `${pathname} must render`).toBe(200);
      await expect(page.locator("main h1"), `${pathname} must have one H1`).toHaveCount(1);

      const canonical = await page.locator('link[rel="canonical"]').getAttribute("href");
      expect(canonical, `${pathname} must have a canonical`).toBeTruthy();
      const canonicalUrl = new URL(canonical!);
      expect(canonicalUrl.origin).toBe("https://caseops.ai");
      expect(canonicalUrl.pathname).toBe(pathname);

      const title = await page.title();
      const description = await page.locator('meta[name="description"]').getAttribute("content");
      expect(title.trim(), `${pathname} title must not be empty`).toBeTruthy();
      expect(description?.trim(), `${pathname} description must not be empty`).toBeTruthy();
      expect(titles.has(title), `${pathname} title must be unique`).toBe(false);
      expect(descriptions.has(description!), `${pathname} description must be unique`).toBe(false);
      titles.add(title);
      descriptions.add(description!);
    }
  });

  test("fresh landing and guide content is published", async ({ page }) => {
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "Intake & Conflict Checks", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", {
        name: "Notices & Response Deadlines",
        exact: true,
      }),
    ).toBeVisible();

    await page.goto("/guide");
    await expect(page.getByText("User guide · v5 · 2026", { exact: true })).toBeVisible();
    await expect(page.locator("main > header")).toContainText(/Updated\s+7 September 2026/);
  });

  for (const pathname of PUBLIC_CONTENT_PAGES) {
    test(`${pathname} has no dead internal links or fragments`, async ({
      page,
      request,
    }) => {
      const issues = await checkInternalLinks(page, request, pathname);
      expect(issues, `dead links on ${pathname}:\n${issues.join("\n")}`).toEqual([]);
    });
  }

  test("guide contents map one-to-one to unique section IDs", async ({ page }) => {
    await page.goto("/guide");

    const sectionIds = await page
      .locator("article > section[id]")
      .evaluateAll((sections) => sections.map((section) => section.id));
    expect(sectionIds.length).toBeGreaterThan(0);
    expect(new Set(sectionIds).size, "guide section IDs must be unique").toBe(
      sectionIds.length,
    );

    const contents = [page.locator('nav[aria-label="Contents"]'), page.locator("main details")];
    for (const container of contents) {
      await expect(container).toHaveCount(1);
      const hrefs = await container
        .locator('a[href^="#"]')
        .evaluateAll((links) =>
          links.map((link) => (link as HTMLAnchorElement).getAttribute("href") ?? ""),
        );
      const tocIds = hrefs.map((href) => decodeURIComponent(href.slice(1)));
      expect(new Set(tocIds).size, "each contents list must have unique links").toBe(
        tocIds.length,
      );
      expect(tocIds, "contents order must match rendered guide sections").toEqual(
        sectionIds,
      );
    }

    const duplicateTargets = await page.evaluate((ids) =>
      ids.filter(
        (id) => Array.from(document.querySelectorAll("[id]")).filter((node) => node.id === id).length !== 1,
      ),
    sectionIds);
    expect(duplicateTargets, "every contents target must resolve exactly once").toEqual([]);
  });

  test("FAQ UI and FAQPage JSON-LD stay in exact parity", async ({ page }) => {
    await page.goto("/");
    const uiFaq = await readUiFaq(page);
    const structuredFaq = await readStructuredFaq(page);

    expect(uiFaq.length).toBeGreaterThan(0);
    expect(structuredFaq).toEqual(uiFaq);
  });

  test("sitemap contains exactly the public content routes", async ({ request }) => {
    const response = await request.get("/sitemap.xml");
    expect(response.status()).toBe(200);
    expect(response.headers()["content-type"]).toMatch(/xml/i);

    const xml = await response.text();
    const paths = Array.from(xml.matchAll(/<loc>([^<]+)<\/loc>/g), (match) => {
      const path = new URL(match[1]).pathname;
      return path.length > 1 ? path.replace(/\/+$/, "") : path;
    }).sort();

    expect(paths).toEqual([...PUBLIC_SITEMAP_PATHS].sort());
    expect(xml).not.toContain("<lastmod>");
    expect(paths.some((path) => /^\/(?:app|account|portal|sign-in)(?:\/|$)/.test(path))).toBe(
      false,
    );
  });

  test("sign-in noindex is crawlable while app and API exclusions remain", async ({ page, request }) => {
    const response = await request.get("/robots.txt");
    expect(response.status()).toBe(200);
    const rules = (await response.text()).split(/\r?\n/).map((line) => line.trim());
    const userAgents = rules.filter((line) => /^User-Agent:/i.test(line));
    const disallowed = rules.filter((line) => /^Disallow:/i.test(line));
    expect(userAgents.length).toBeGreaterThan(0);
    expect(disallowed.filter((line) => line === "Disallow: /app")).toHaveLength(userAgents.length);
    expect(disallowed.filter((line) => line === "Disallow: /api/")).toHaveLength(userAgents.length);
    expect(disallowed, "robots must let crawlers read the public sign-in noindex").not.toContain("Disallow: /sign-in");

    const signIn = await page.goto("/sign-in");
    expect(signIn?.status()).toBe(200);
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", "noindex, nofollow");
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", "https://caseops.ai/sign-in");
    await expect(page.getByRole("textbox", { name: "Work email", exact: true })).toBeVisible();
  });

  for (const path of ["/account/forgot-password", "/portal/sign-in"]) {
    test(`${path} remains noindex without submitting credentials`, async ({ page }) => {
      const response = await page.goto(path);
      expect(response?.status()).toBe(200);
      await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", "noindex, nofollow");
    });
  }

  test("home retains the Google Search Console ownership tag", async ({ page }) => {
    const response = await page.goto("/");
    expect(response?.status()).toBe(200);
    await expect(page.locator('meta[name="google-site-verification"]')).toHaveAttribute(
      "content",
      "PMGfTyh9A92sieEPcMzxE1pEAjez7zyvTiP1UorJ9T8",
    );
  });

  test("matter-management resource answers the query and qualifies provider limits", async ({ page }) => {
    const response = await page.goto("/resources/legal-matter-management-india");
    expect(response?.status()).toBe(200);
    const nonce = response?.headers()["content-security-policy"]?.match(/script-src[^;]*'nonce-([^']+)'/)?.[1];
    expect(nonce, "resource JSON-LD must use the request's CSP nonce").toBeTruthy();
    await expect(page.getByRole("heading", { level: 1, name: "Legal matter management in India" })).toBeVisible();
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
      "href",
      "https://caseops.ai/resources/legal-matter-management-india",
    );
    await expect(page.locator("#checklist li")).toHaveCount(7);
    await expect(page.locator("#court-data")).toContainText("does not guarantee");
    const article = await page.locator('script[type="application/ld+json"]').allTextContents();
    expect(article.map((value) => JSON.parse(value) as { "@type"?: string }).some((value) => value["@type"] === "Article")).toBe(true);
    const articleNonce = await page.locator("#matter-management-article-jsonld")
      .evaluate((element) => (element as HTMLScriptElement).nonce);
    expect(articleNonce).toBe(nonce);
  });

  test("solo page does not promise unmeasured savings or universal provider coverage", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#workflows")).toContainText("Run a solo practice from one matter workspace.");
    await expect(page.locator("#workflows")).not.toContainText("20-lawyer practice");

    await page.goto("/solo-lawyers");
    await expect(page.locator("main h1")).toHaveText("Practice management for solo advocates in India.");
    await expect(page.locator("#ai-angle")).toContainText("The advocate checks the facts, citations");
    await expect(page.locator("#ai-angle")).toContainText("tenant eligibility, court coverage");
    const copy = await page.locator("main").innerText();
    expect(copy).not.toMatch(/2[–-]3 hours|Two to three hours|30-second pre-filing|Never a fabricated citation|Under a minute|One login replaces five subscriptions/i);
  });

  for (const viewport of VIEWPORTS) {
    test(`${viewport.name} October 11 recommendation article is discoverable, source-qualified and read-only`, async ({
      page,
    }, testInfo) => {
      const pathname = "/resources/source-grounded-legal-recommendations";
      const title = "Source-grounded recommendations for law firms";
      await page.setViewportSize(viewport);
      await page.goto("/", { waitUntil: "domcontentloaded" });
      const entry = page.locator(`footer a[href="${pathname}"]`);
      await expect(entry).toHaveCount(1);
      await entry.scrollIntoViewIfNeeded();
      await expect(entry).toBeVisible();
      await entry.click();
      await expect(page).toHaveURL(new RegExp(`${pathname}$`));

      const response = await page.reload({ waitUntil: "domcontentloaded" });
      expect(response?.status()).toBe(200);
      const nonce = response?.headers()["content-security-policy"]?.match(/script-src[^;]*'nonce-([^']+)'/)?.[1];
      expect(nonce, "article JSON-LD must use the request CSP nonce").toBeTruthy();
      await expect(page.locator("main h1")).toHaveText(title);
      await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
      await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", `https://caseops.ai${pathname}`);
      await expect(page.locator('meta[property="og:type"]')).toHaveAttribute("content", "article");
      const description = await page.locator('meta[name="description"]').getAttribute("content");
      const jsonLd = page.locator("#source-grounded-recommendations-article-jsonld");
      const article = JSON.parse((await jsonLd.textContent())!) as Record<string, unknown>;
      expect(article).toMatchObject({
        "@context": "https://schema.org",
        "@type": "Article",
        headline: title,
        description,
        mainEntityOfPage: `https://caseops.ai${pathname}`,
        inLanguage: "en-IN",
      });
      await expect(page.locator("main > header")).toContainText(String(description));
      expect(await jsonLd.evaluate((element) => (element as HTMLScriptElement).nonce)).toBe(nonce);

      const contents = page.getByRole("navigation", { name: "On this page" });
      const targets = await page.locator("article > section[id]").evaluateAll(
        (sections) => sections.map((section) => `#${section.id}`),
      );
      expect(await contents.locator("a").evaluateAll(
        (links) => links.map((link) => link.getAttribute("href")),
      )).toEqual(targets);
      expect(new Set(targets).size).toBe(targets.length);
      for (const link of await contents.getByRole("link").all()) {
        await link.scrollIntoViewIfNeeded();
        await expect(link).toBeVisible();
        const box = await link.boundingBox();
        expect(box).not.toBeNull();
        expect(box!.x).toBeGreaterThanOrEqual(0);
        expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width + 1);
      }
      await contents.getByRole("link", { name: "The workflow", exact: true }).click();
      await expect(page).toHaveURL(/#workflow$/);
      const workflow = page.locator("#workflow");
      await expect(workflow.getByRole("heading", { level: 2 })).toBeVisible();
      await expect(workflow.locator("ol > li")).toHaveCount(5);
      await expect(workflow).toContainText("assumptions and missing facts");
      await expect(workflow).toContainText("generation may be refused");
      await expect(workflow).toContainText("Recording a decision is not a court filing");

      const review = page.locator("#source-checks");
      await review.scrollIntoViewIfNeeded();
      await expect(review.getByRole("heading", { level: 2 })).toBeVisible();
      await expect(review).toContainText("Generated output can contain legal or factual errors");
      await expect(review).toContainText("The lawyer must verify each authority, quotation and material fact");
      await expect(review).toContainText("A confidence label is not a probability of winning a case");
      for (const paragraph of await review.locator("p").all()) {
        await paragraph.evaluate((element) => element.scrollIntoView({ block: "center", behavior: "auto" }));
        await expect(paragraph).toBeVisible();
        const box = await paragraph.boundingBox();
        const navigation = await page.getByRole("banner").boundingBox();
        expect(box).not.toBeNull();
        expect(navigation).not.toBeNull();
        expect(box!.x).toBeGreaterThanOrEqual(0);
        expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width + 1);
        expect(box!.y).toBeGreaterThanOrEqual(navigation!.y + navigation!.height);
        expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height + 1);
      }
      await testInfo.attach("recommendation-review-limitations", {
        body: await review.screenshot(), contentType: "image/png",
      });

      const access = page.locator("#controlled-access");
      await access.scrollIntoViewIfNeeded();
      await expect(access.getByRole("heading", { level: 2 })).toBeVisible();
      await expect(access).toContainText("ethical wall");
      await expect(access).toContainText("Tenant AI policy and available source coverage");
      await expect(page.locator("#team-checklist ul > li")).toHaveCount(5);
      await expect(page.locator("article form, article input, article textarea")).toHaveCount(0);
      await expect(page.locator('article a[href^="/demo"]')).toHaveCount(0);
      await expect(page.locator('script[src*="googletagmanager"], script[src*="google-analytics"]')).toHaveCount(0);
      const copy = `${await page.locator("main").innerText()} ${await jsonLd.textContent()}`;
      expect(copy).not.toMatch(/\b(?:gpt[\w.-]*|claude|gemini|llama|mistral|deepseek|qwen|voyage[\w.-]*|bge[\w.-]*)\b/i);
      expect(copy).not.toMatch(/hallucination[- ]free|guaranteed (?:win|success|outcome)|100% (?:accuracy|correctness)|\u20b9|\$\d/i);

      const widths = await page.evaluate(() => ({
        client: document.documentElement.clientWidth,
        scroll: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
      }));
      expect(widths.scroll, `article overflows at ${viewport.width}px`).toBeLessThanOrEqual(widths.client + 1);
      const guide = page.locator("article").getByRole("link", { name: "product guide", exact: true });
      await guide.scrollIntoViewIfNeeded();
      await expect(guide).toBeVisible();
      await guide.click();
      await expect(page).toHaveURL(/\/guide$/);
      await expect(page.getByRole("heading", { level: 1, name: /how to run your practice on caseops/i })).toBeVisible();

      await page.goto("/resources/legal-matter-management-india", { waitUntil: "domcontentloaded" });
      const related = page.locator("article").getByRole("link", { name: title, exact: true });
      await related.scrollIntoViewIfNeeded();
      await expect(related).toBeVisible();
      await related.click();
      await expect(page).toHaveURL(new RegExp(`${pathname}$`));
      await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
    });

    test(`${viewport.name} September 10 guide and sales copy preserve source and provider limits`, async ({
      page,
    }, testInfo) => {
      await page.setViewportSize(viewport);
      await page.goto("/guide", { waitUntil: "domcontentloaded" });
      const statutes = page.locator("#statutes");
      await statutes.scrollIntoViewIfNeeded();
      await expect(statutes).toContainText("Catalog coverage remains incomplete.");
      await expect(statutes).toContainText("exact source version");
      await expect(statutes).toContainText("checked provision-level link");
      await expect(statutes).not.toContainText("3,393 sections");
      await expect(statutes).not.toContainText("Complete catalog visibility");
      await testInfo.attach("statute-coverage", {
        body: await statutes.screenshot(), contentType: "image/png",
      });
      const tracking = page.locator("#case-tracking");
      await tracking.scrollIntoViewIfNeeded();
      await expect(tracking).toContainText("Party names alone never identify a case.");
      await expect(tracking).toContainText("queued provider refresh");
      await expect(tracking).toContainText("processed asynchronously");
      await expect(tracking).toContainText("does not undo the saved provider update");
      await expect(tracking).toContainText("persistent QA");
      await expect(tracking).toContainText("never reopens");
      await testInfo.attach("hearing-recovery", {
        body: await tracking.screenshot(), contentType: "image/png",
      });
      await page.goto("/law-firms", { waitUntil: "domcontentloaded" });
      const sourceControls = page.getByText("Licensed Indian Kanoon research and eCourts case tracking require", { exact: false });
      await sourceControls.scrollIntoViewIfNeeded();
      await expect(sourceControls).toBeVisible();
      await expect(sourceControls).toContainText("unconfirmed reservations");
      await expect(sourceControls).toContainText("credentials alone do not establish provider availability");
      await testInfo.attach("licensed-provider-claims", {
        body: await sourceControls.screenshot(), contentType: "image/png",
      });
    });

    test(`${viewport.name} public pages have no overflow or serious accessibility issues`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);

      for (const pathname of PUBLIC_CONTENT_PAGES) {
        await page.goto(pathname, { waitUntil: "domcontentloaded" });
        await page.evaluate(async () => {
          await document.fonts.ready;
        });

        const widths = await page.evaluate(() => ({
          bodyClient: document.body.clientWidth,
          bodyScroll: document.body.scrollWidth,
          documentClient: document.documentElement.clientWidth,
          documentScroll: document.documentElement.scrollWidth,
        }));
        expect(
          Math.max(widths.bodyScroll, widths.documentScroll),
          `${pathname} overflows at ${viewport.width}px: ${JSON.stringify(widths)}`,
        ).toBeLessThanOrEqual(Math.max(widths.bodyClient, widths.documentClient) + 1);

        const results = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
          .analyze();
        const blockers = results.violations
          .filter(
            (violation) =>
              violation.impact === "serious" || violation.impact === "critical",
          )
          .map((violation) => ({
            id: violation.id,
            impact: violation.impact,
            targets: violation.nodes.map((node) => node.target),
          }));
        expect(
          blockers,
          `${pathname} has serious/critical axe violations at ${viewport.width}px`,
        ).toEqual([]);
      }
    });
  }

  test("mobile navigation and guide contents are keyboard- and touch-usable", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 360, height: 800 });
    await page.goto("/");

    const menuButton = page.locator('button[aria-controls="mobile-nav"]');
    await expect(menuButton).toBeVisible();
    await menuButton.click();
    await expect(menuButton).toHaveAttribute("aria-expanded", "true");

    const mobileNav = page.locator("#mobile-nav");
    await expect(mobileNav).toBeVisible();
    await expect(mobileNav.getByRole("link", { name: "Product", exact: true })).toBeVisible();
    await expect(mobileNav.getByRole("link", { name: "Pricing", exact: true })).toBeVisible();
    await mobileNav.getByRole("link", { name: "Guide", exact: true }).click();

    await expect(page).toHaveURL(/\/guide$/);
    await expect(
      page.getByRole("heading", { level: 1, name: /how to run your practice on caseops/i }),
    ).toBeVisible();

    const contents = page.locator("main details");
    await expect(contents).toBeVisible();
    await contents.locator("summary").click();
    await expect(contents).toHaveAttribute("open", "");

    const firstLink = contents.locator('a[href^="#"]').first();
    const href = await firstLink.getAttribute("href");
    expect(href).toMatch(/^#[a-z0-9-]+$/);
    await firstLink.click();
    await expect(page).toHaveURL(new RegExp(`${href}$`));
    await expect(page.locator(href!)).toBeVisible();
  });
});
