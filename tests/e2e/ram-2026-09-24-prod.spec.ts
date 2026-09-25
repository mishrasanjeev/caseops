import { randomUUID } from "node:crypto";
import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";

const web = process.env.PROD_BASE_URL || process.env.CASEOPS_WEB_BASE_URL || "http://127.0.0.1:3000";
const api = process.env.PROD_API_BASE_URL || apiBaseUrl;
const production = new URL(web).hostname === "caseops.ai";

async function waitForSignInForm(page: import("@playwright/test").Page) {
  await page.waitForFunction(() => {
    const form = document.querySelector('form[aria-label="Sign in"]');
    return form && Object.keys(form).some((key) => key.startsWith("__react"));
  });
}

function localSignedMatterSelection(matterId: string, membershipId: string): string {
  const python = process.env.CASEOPS_E2E_PYTHON || path.join(
    repoRoot, "apps", "api", ".venv",
    process.platform === "win32" ? "Scripts" : "bin",
    process.platform === "win32" ? "python.exe" : "python",
  );
  const script = [
    "import sys",
    "from caseops_api.db.session import get_session_factory",
    "from caseops_api.db.models import Matter",
    "from caseops_api.schemas.case_tracking import CaseTrackingSearchResultRecord",
    "from caseops_api.services.case_tracking import _matter_selection_token",
    "from caseops_api.services.identity import get_session_context",
    "with get_session_factory()() as session:",
    "    matter = session.get(Matter, sys.argv[1])",
    "    context = get_session_context(session, sys.argv[2])",
    "    result = CaseTrackingSearchResultRecord(provider='ecourtsindia', cnr_number='DLHC010012342026', case_number='WP(C) 1/2026', court_code='DLHC', court_name='Delhi High Court', case_title='Selected candidate', party_names=[], current_status='Pending', current_stage='Arguments', next_hearing_on=None, source_url=None)",
    "    print(_matter_selection_token(context=context, matter=matter, result=result))",
  ].join("\n");
  const dockerProject = process.env.CASEOPS_E2E_DOCKER_PROJECT;
  const dockerComposeFile = process.env.CASEOPS_E2E_DOCKER_COMPOSE_FILE;
  if (dockerProject && !dockerComposeFile) {
    throw new Error("Docker acceptance requires its exact Compose file.");
  }
  const run = dockerProject && dockerComposeFile
    ? spawnSync("docker", [
        "compose", "--project-name", dockerProject, "--file", dockerComposeFile,
        "exec", "-T", "api", "python", "-c", script, matterId, membershipId,
      ], { cwd: repoRoot, encoding: "utf8", timeout: 30_000 })
    : spawnSync(python, ["-c", script, matterId, membershipId], {
        cwd: path.join(repoRoot, "apps", "api"),
        env: { ...process.env, ...e2eEnv, PYTHONPATH: path.join(repoRoot, "apps", "api", "src") },
        encoding: "utf8",
        timeout: 30_000,
      });
  if (run.error || run.status !== 0) {
    throw new Error(`Could not create local nonbillable selection: ${run.error?.message || run.stderr || `exit ${run.status}`}`);
  }
  return run.stdout.trim();
}

test("Matter court link shows the user-selected case without provider spend in local UI", async ({ page, request }) => {
  test.skip(production, "Local UI journey uses deterministic nonbillable provider evidence.");
  const suffix = randomUUID().slice(0, 8);
  const slug = `ecourt-link-${suffix}`;
  const email = `${slug}@example.com`;
  const password = `Local-${randomUUID()}!`;
  const boot = await request.post(`${api}/api/bootstrap/company`, {
    headers: noPaidProviderHeaders,
    data: {
      company_name: slug,
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "eCourts QA",
      owner_email: email,
      owner_password: password,
    },
  });
  expect(boot.status(), await boot.text()).toBe(200);
  const bootData = await boot.json();
  const headers = {
    ...noPaidProviderHeaders,
    Authorization: `Bearer ${bootData.access_token as string}`,
  };
  const created = await request.post(`${api}/api/matters/`, {
    headers,
    data: {
      title: "Example Petitioner v Example Respondent",
      matter_code: `EC-LINK-${suffix}`,
      practice_area: "litigation",
      forum_level: "high_court",
      court_name: "Delhi High Court",
      case_number: "WP(C) 1/2026",
      cnr_number: "DLHC010012342026",
      status: "active",
    },
  });
  expect(created.status(), await created.text()).toBe(200);
  const matterId = (await created.json()).id as string;
  const selectedToken = localSignedMatterSelection(matterId, bootData.membership.id as string);
  await page.setExtraHTTPHeaders(noPaidProviderHeaders);
  await page.goto(`${web}/sign-in`);
  await waitForSignInForm(page);
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
  await page.goto(`${web}/app/matters/${matterId}`);
  const court = page.getByRole("link", { name: "Delhi High Court" });
  await expect(court).toBeVisible();
  const href = await court.getAttribute("href");
  expect(href).toContain(`/app/case-tracking?matterId=${matterId}`);

  await page.route("**/api/case-tracking/status", async (route) => {
    await route.fulfill({ json: {
      enabled: true, configured: true, provider: "ecourtsindia",
      scheduled_sync_local_time: "18:00", scheduled_sync_timezone: "Asia/Kolkata",
    } });
  });
  await page.route(`**/api/case-tracking/matters/${matterId}/resolve`, async (route) => {
    expect(route.request().headers()["x-caseops-automated-test"]).toBe("no-paid-providers");
    await route.fulfill({ json: {
      provider: "ecourtsindia", status: "multiple_matches", results: [{
        provider: "ecourtsindia", cnr_number: "DLHC010099992026",
        case_number: "WP(C) 99/2026", court_code: "DLHC", court_name: "Delhi High Court",
        case_title: "First candidate", party_names: [],
        current_status: "Pending", current_stage: "Arguments", next_hearing_on: null,
        source_url: null, provenance_label: "Provider-normalized case status", link_token: "selection-1",
      }, {
        provider: "ecourtsindia", cnr_number: "DLHC010012342026",
        case_number: "WP(C) 1/2026", court_code: "DLHC", court_name: "Delhi High Court",
        case_title: "Selected candidate", party_names: [],
        current_status: "Pending", current_stage: "Arguments", next_hearing_on: null,
        source_url: null, provenance_label: "Provider-normalized case status", link_token: selectedToken,
      }],
    } });
  });
  await page.route("**/api/case-tracking/search", async (route) => {
    expect(route.request().headers()["x-caseops-automated-test"]).toBe("no-paid-providers");
    expect(route.request().postDataJSON()).toEqual({
      query: "Selected candidate", cnr_number: "DLHC010012342026", case_number: "WP(C) 1/2026",
      court_code: null, matter_id: matterId,
    });
    await route.fulfill({ json: {
      provider: "ecourtsindia", results: [{
        provider: "ecourtsindia", cnr_number: "DLHC010099992026",
        case_number: "WP(C) 99/2026", court_code: "DLHC", court_name: "Delhi High Court",
        case_title: "Unmatched result", party_names: [], current_status: "Pending",
        current_stage: null, next_hearing_on: null, source_url: null, link_token: null,
      }, {
        provider: "ecourtsindia", cnr_number: "DLHC010012342026",
        case_number: "WP(C) 1/2026", court_code: "DLHC", court_name: "Delhi High Court",
        case_title: "Selected candidate", party_names: [], current_status: "Pending",
        current_stage: null, next_hearing_on: null, source_url: null,
        link_token: selectedToken,
      }],
    } });
  });
  await page.goto(`${web}${href}`);
  await page.getByTestId("matter-case-resolve-submit").click();
  await expect(page.getByText(/Multiple verified candidates remain/)).toBeVisible();
  await expect(page.getByTestId("matter-case-candidate")).toHaveCount(2);
  const linkResponsePromise = page.waitForResponse((response) =>
    response.url().endsWith(`/api/case-tracking/matters/${matterId}/link`) &&
    response.request().method() === "POST",
  );
  await page.getByTestId("matter-case-candidate").nth(1).getByTestId("matter-case-link-submit").click();
  const linkResponse = await linkResponsePromise;
  expect(linkResponse.status(), await linkResponse.text()).toBe(200);
  expect(linkResponse.request().postDataJSON()).toEqual({ link_token: selectedToken });
  expect(linkResponse.request().headers()["x-caseops-automated-test"]).toBe("no-paid-providers");
  await expect(page.getByTestId("matter-case-candidate").nth(1).getByTestId("matter-case-linked")).toBeVisible();
  await expect(page.getByTestId("matter-case-candidate").first().getByTestId("matter-case-link-submit")).toBeVisible();
  await page.getByTestId("case-tracking-query").fill("Selected candidate");
  await page.getByTestId("case-tracking-search-submit").click();
  await expect(page.getByText("Does not match this Matter")).toBeVisible();
  const replayResponsePromise = page.waitForResponse((response) =>
    response.url().endsWith(`/api/case-tracking/matters/${matterId}/link`) &&
    response.request().method() === "POST",
  );
  await page.getByTestId("matter-search-link-submit").click();
  const replayResponse = await replayResponsePromise;
  expect(replayResponse.status(), await replayResponse.text()).toBe(200);
  expect(replayResponse.request().postDataJSON()).toEqual({ link_token: selectedToken });
  await expect(page.getByTestId("matter-search-linked")).toBeVisible();
  const bookmarks = await request.get(`${api}/api/case-tracking/bookmarks`, { headers });
  expect(bookmarks.status(), await bookmarks.text()).toBe(200);
  expect((await bookmarks.json()).bookmarks.filter((row: { matter_id: string }) =>
    row.matter_id === matterId,
  )).toHaveLength(1);
});

test("QA-owned matter has a canonical hearing and automated eCourts lookup cannot spend", async ({ page, request }) => {
  test.skip(!production, "Production QA workspace acceptance only.");
  const slug = process.env.CASEOPS_PROD_TEST_SLUG ?? process.env.CASEOPS_RAM_PROD_SLUG;
  const email = process.env.CASEOPS_PROD_TEST_EMAIL ?? process.env.CASEOPS_RAM_PROD_EMAIL;
  const password = process.env.CASEOPS_PROD_TEST_PASSWORD ?? process.env.CASEOPS_RAM_PROD_PASSWORD;
  if (!slug || !email || !password) throw new Error("Production test credentials are required.");
  const login = await request.post(`${api}/api/auth/login`, {
    headers: noPaidProviderHeaders,
    data: { company_slug: slug, email, password },
  });
  expect(login.status(), await login.text()).toBe(200);
  const headers = {
    ...noPaidProviderHeaders,
    Authorization: `Bearer ${(await login.json()).access_token as string}`,
  };
  const hearingDate = new Date(Date.now() + 4 * 86_400_000).toISOString().slice(0, 10);
  const code = `SEP24-${randomUUID().slice(0, 8).toUpperCase()}`;
  const created = await request.post(`${api}/api/matters/`, {
    headers,
    data: {
      title: "QA canonical hearing acceptance",
      matter_code: code,
      practice_area: "litigation",
      forum_level: "high_court",
      court_name: "Delhi High Court",
      case_number: `WP(C) ${randomUUID().slice(0, 6)}/2026`,
      next_hearing_on: hearingDate,
      status: "active",
    },
  });
  expect(created.status(), await created.text()).toBe(200);
  const matterId = (await created.json()).id as string;
  const workspace = await request.get(`${api}/api/matters/${matterId}/workspace`, { headers });
  expect(workspace.status(), await workspace.text()).toBe(200);
  const data = await workspace.json();
  expect(data.matter.next_hearing_on).toBe(hearingDate);
  expect(data.hearings.filter((row: { hearing_on: string; status: string }) =>
    row.hearing_on === hearingDate && row.status === "scheduled",
  )).toHaveLength(1);
  await page.setExtraHTTPHeaders(noPaidProviderHeaders);
  await page.goto(`${web}/sign-in`);
  await waitForSignInForm(page);
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
  await page.goto(`${web}/app/matters/${matterId}`);
  const court = page.locator('a[href*="/app/case-tracking?matterId="]').first();
  await expect(court).toBeVisible();
  const href = await court.getAttribute("href");
  expect(href).toContain("/app/case-tracking?matterId=");
  await page.goto(`${web}${href}`);
  await page.getByTestId("matter-case-resolve-submit").click();
  await expect(page.getByRole("alert")).toContainText(/no external request was made/i);
  await page.goto(`${web}/app/hearings`);
  await page.getByLabel("Exact hearing date").fill(hearingDate);
  await expect(page.locator(`a[href*="/app/matters/${matterId}"]`).first()).toBeVisible();
});
