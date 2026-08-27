import { expect, request, test } from "@playwright/test";

import { apiBaseUrl } from "./support/env";
import { expectStatus } from "./support/iplf058b";

test("IPLF-061A serves one versioned guide index and permission-aware command contract", async ({
  page,
}) => {
  const api = await request.newContext({ baseURL: apiBaseUrl });
  const runId = `${Date.now()}`;
  const bootstrap = await api.post("/api/bootstrap/company", {
    data: {
      company_name: `Guide foundation ${runId}`,
      company_slug: `guide-foundation-${runId}`,
      company_type: "law_firm",
      owner_full_name: "Guide Foundation Owner",
      owner_email: `guide-${runId}@example.com`,
      owner_password: "GuideFoundation123!",
    },
  });
  await expectStatus(bootstrap, 200, "guide tenant bootstrap");
  const session = await bootstrap.json();
  const headers = { Authorization: `Bearer ${session.access_token}` };

  const catalogResponse = await api.get("/api/product-guide/catalog");
  await expectStatus(catalogResponse, 200, "public Product Guide catalog");
  const catalog = await catalogResponse.json();
  expect(catalog.content_version).toBe("2026.08.27.2");
  expect(catalog.sections).toHaveLength(27);
  expect(catalog.sections.some((section: { id: string }) => section.id === "judge-mapping")).toBe(
    true,
  );
  expect(catalog.commands).toBeUndefined();

  const searchResponse = await api.get("/api/product-guide/search", {
    headers,
    params: { q: "deadline control", client_version: "2026.08.22.1", limit: 3 },
  });
  await expectStatus(searchResponse, 200, "permission-aware guide search");
  const search = await searchResponse.json();
  expect(search.version_status).toBe("stale");
  expect(search.results[0]).toMatchObject({
    kind: "command",
    id: "deadline-control",
    href: "/app/ip/docket",
  });

  const noMatchResponse = await api.get("/api/product-guide/search", {
    headers,
    params: { q: "xylophone nebula quasar" },
  });
  await expectStatus(noMatchResponse, 200, "deterministic guide abstention");
  expect((await noMatchResponse.json()).status).toBe("no_match");

  for (const viewport of [
    { width: 360, height: 800 },
    { width: 1280, height: 900 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto("/guide");
    await expect(page.locator("[data-guide-version]")).toHaveAttribute(
      "data-guide-version",
      catalog.content_version,
    );
    await expect(page.locator("article > section[id]")).toHaveCount(catalog.sections.length);
    await expect(page.locator("#judge-mapping")).toBeAttached();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
      ),
    ).toBe(false);
  }
  await api.dispose();
});
