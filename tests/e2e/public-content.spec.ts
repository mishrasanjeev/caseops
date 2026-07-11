import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const PUBLIC_SITEMAP_PATHS = [
  "/",
  "/general-counsels",
  "/guide",
  "/law-firms",
  "/llms-full.txt",
  "/llms.txt",
  "/pricing",
  "/solo-lawyers",
] as const;

const PUBLIC_CONTENT_PAGES = ["/", "/guide"] as const;

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
    await expect(page.getByText("User guide · v3 · 2026", { exact: true })).toBeVisible();
    await expect(page.locator("main > header")).toContainText(/Updated\s+11 July 2026/);
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
    expect(paths.some((path) => /^\/(?:app|account|portal|sign-in)(?:\/|$)/.test(path))).toBe(
      false,
    );
  });

  for (const viewport of VIEWPORTS) {
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
