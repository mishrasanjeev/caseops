/** IPLF-060B exact-release production acceptance for canonical judge research. */

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { expectStatus } from "./support/iplf058b";

const WEB = (process.env.PROD_BASE_URL ?? "https://caseops.ai").trim();
const API = (process.env.PROD_API_BASE_URL ?? "https://api.caseops.ai").trim();
const SLUG = (process.env.CASEOPS_IP_QA_SLUG ?? "caseops-ip-qa").trim();
const EMAIL = (process.env.CASEOPS_IP_QA_EMAIL ?? "ip-qa-bot@caseops.ai").trim();
const PILOT_COURTS = ["Delhi High Court", "Bombay High Court", "Madras High Court"];

function required(name: string) {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required.`);
  return value;
}

async function authenticate(page: Page) {
  const response = await page.request.post(`${API}/api/auth/login`, {
    data: {
      company_slug: SLUG,
      email: EMAIL,
      password: required("CASEOPS_IP_QA_PASSWORD"),
    },
  });
  await expectStatus(response, 200, "IP QA sign-in");
  const session = await response.json();
  await page.goto(`${WEB}/`);
  await page.evaluate(
    (context) => {
      window.localStorage.setItem("caseops.session.context", JSON.stringify(context));
    },
    {
      company: session.company,
      user: session.user,
      membership: session.membership,
      capabilities: session.capabilities,
    },
  );
  return session;
}

async function getJson(
  api: APIRequestContext,
  path: string,
  headers: Record<string, string>,
) {
  const response = await api.get(`${API}${path}`, { headers });
  await expectStatus(response, 200, path);
  return response.json();
}

test("IPLF-060B production proves UJ-20, pilot mappings, source actions, and responsive UI", async ({
  page,
}) => {
  test.setTimeout(360_000);
  page.setDefaultTimeout(25_000);
  const expectedSha = required("CASEOPS_EXPECTED_RELEASE_SHA");
  const [apiIdentity, webIdentity] = await Promise.all([
    page.request.get(`${API}/api/build`),
    page.request.get(`${WEB}/api/release-identity`),
  ]);
  await expectStatus(apiIdentity, 200, "API release identity");
  await expectStatus(webIdentity, 200, "web release identity");
  expect((await apiIdentity.json()).release_sha).toBe(expectedSha);
  expect((await webIdentity.json()).release_sha).toBe(expectedSha);

  const session = await authenticate(page);
  const headers = { Authorization: `Bearer ${session.access_token}` };
  const courtsBody = await getJson(page.request, "/api/courts/", headers);
  const pilots = PILOT_COURTS.map((name) => {
    const court = courtsBody.courts.find((item: { name: string }) => item.name === name);
    expect(court, `${name} must exist in the canonical court catalog`).toBeTruthy();
    return court as { id: string; name: string };
  });

  let uiJudgeId = "";
  for (const court of pilots) {
    const listing = await getJson(
      page.request,
      `/api/courts/${encodeURIComponent(court.id)}/judges`,
      headers,
    );
    const judge = listing.judges.find(
      (item: { full_name: string; mapped_authority_count: number }) =>
        item.full_name.startsWith("Justice CaseOps QA Pilot -") &&
        item.mapped_authority_count > 0,
    );
    expect(
      judge,
      `${court.name} must have its bounded production QA judge mapping for JUDGE-10`,
    ).toBeTruthy();
    const authorities = await getJson(
      page.request,
      `/api/courts/judges/${encodeURIComponent(judge.id)}/authorities?limit=1`,
      headers,
    );
    expect(authorities.coverage_state).toBe("mapped_results");
    expect(authorities.authorities[0].source_action.state).toBe("available");
    expect(authorities.authorities[0].source_action.open_url).toBeTruthy();
    uiJudgeId ||= judge.id;
  }

  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto(`${WEB}/app/courts/judges/${uiJudgeId}`);
  await expect(page.getByText("Mapped authorities")).toBeVisible();
  await expect(page.getByText("Canonical identity")).toBeVisible();
  const mappedAuthorities = page
    .getByRole("heading", { name: "Mapped authorities" })
    .locator("../..");
  await expect(mappedAuthorities.getByRole("link", { name: "Source" }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: /research this judge/i })).toBeVisible();
  for (const name of ["From year", "To year", "Mapping confidence"]) {
    await expect(page.getByLabel(name)).toBeVisible();
  }
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    ),
  ).toBe(false);

  await page.goto(`${WEB}/app/admin/judge-aliases`);
  for (const name of ["Review queue", "Aliases", "Merge duplicates", "Reprocess"]) {
    await expect(page.getByRole("tab", { name })).toBeVisible();
  }
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    ),
  ).toBe(false);

  await page.goto(`${WEB}/guide`);
  await expect(
    page.getByRole("heading", { name: "Judge mapping and authority review" }),
  ).toBeVisible();
  await page.goto(`${WEB}/law-firms`);
  await expect(page.getByRole("heading", { name: "Source-backed judge research" })).toBeVisible();
});
