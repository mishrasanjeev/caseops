import { expect, test } from "@playwright/test";

import productGuideCatalog from "../../docs/ip-implementation/PRODUCT_GUIDE_CATALOG.json";
import { expectStatus } from "./support/iplf058b";

const WEB = (process.env.PROD_BASE_URL ?? "https://caseops.ai").trim();
const API = (process.env.PROD_API_BASE_URL ?? "https://api.caseops.ai").trim();
const SLUG = (process.env.CASEOPS_IP_QA_SLUG ?? "caseops-ip-qa").trim();
const EMAIL = (process.env.CASEOPS_IP_QA_EMAIL ?? "ip-qa-bot@caseops.ai").trim();

function required(name: string) {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required.`);
  return value;
}

test("IPLF-061A production proves the exact versioned guide foundation", async ({ page }) => {
  const expectedSha = required("CASEOPS_EXPECTED_RELEASE_SHA");
  const [apiIdentity, webIdentity] = await Promise.all([
    page.request.get(`${API}/api/build`),
    page.request.get(`${WEB}/api/release-identity`),
  ]);
  await expectStatus(apiIdentity, 200, "API release identity");
  await expectStatus(webIdentity, 200, "web release identity");
  expect((await apiIdentity.json()).release_sha).toBe(expectedSha);
  expect((await webIdentity.json()).release_sha).toBe(expectedSha);

  const login = await page.request.post(`${API}/api/auth/login`, {
    data: {
      company_slug: SLUG,
      email: EMAIL,
      password: required("CASEOPS_IP_QA_PASSWORD"),
    },
  });
  await expectStatus(login, 200, "IP QA sign-in");
  const session = await login.json();
  const headers = { Authorization: `Bearer ${session.access_token}` };

  const catalogResponse = await page.request.get(`${API}/api/product-guide/catalog`);
  await expectStatus(catalogResponse, 200, "production Product Guide catalog");
  const catalog = await catalogResponse.json();
  expect(catalog.content_version).toBe(productGuideCatalog.content_version);
  expect(catalog.sections).toHaveLength(27);
  expect(catalog.commands).toBeUndefined();

  const searchResponse = await page.request.get(`${API}/api/product-guide/search`, {
    headers,
    params: { q: "deadline control", client_version: "2026.08.22.1", limit: 3 },
  });
  await expectStatus(searchResponse, 200, "production guide command search");
  const search = await searchResponse.json();
  expect(search.version_status).toBe("stale");
  expect(search.results[0]).toMatchObject({
    kind: "command",
    id: "deadline-control",
    href: "/app/ip/docket",
  });

  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto(`${WEB}/guide`);
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
});
