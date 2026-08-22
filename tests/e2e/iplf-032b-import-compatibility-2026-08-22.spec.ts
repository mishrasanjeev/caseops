/** IPLF-032B: shared read-only history across canonical and legacy import owners. */

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "ImportCompatibility2026!";

async function bootstrap(api: APIRequestContext) {
  const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const slug = `import-compat-${suffix}`;
  const email = `owner-${suffix}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 032B Import Compatibility LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Import Operations Partner",
      owner_email: email,
      owner_password: PASSWORD,
    },
  });
  expect(response.status(), await response.text()).toBe(200);
  return { ...(await response.json()), slug, email };
}

async function signIn(page: Page, slug: string, email: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

test("IPLF-032B reconciles all import owners without rewriting legacy jobs", async ({ page }) => {
  test.setTimeout(180_000);
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  const headers = { Authorization: `Bearer ${tenant.access_token}` };

  const ipUpload = await api.post(`${apiBaseUrl}/api/ip/imports/upload`, {
    headers,
    multipart: {
      file: {
        name: "iplf-032b-trademarks.csv",
        mimeType: "text/csv",
        buffer: Buffer.from([
          "title,mark,class,applicant,goods/services,application number,jurisdiction,office",
          "ASTER COMPATIBILITY,ASTER,9,Aster Products LLP,Legal software,TM/2026/3201,IN,Trade Marks Registry Mumbai",
        ].join("\n"), "utf8"),
      },
    },
  });
  expect(ipUpload.status(), await ipUpload.text()).toBe(201);

  const matterUpload = await api.post(`${apiBaseUrl}/api/matters/imports/preview`, {
    headers,
    multipart: {
      file: {
        name: "iplf-032b-matters.csv",
        mimeType: "text/csv",
        buffer: Buffer.from([
          "Matter Title,Matter Code,Practice Area,Matter Status,Client Name,Forum,Client Email,Court Forum Number",
          `Import compatibility matter,IPLF-032B-${Date.now()},Commercial,ACTIVE,,High Court,client@example.com,Court 7`,
        ].join("\n"), "utf8"),
      },
    },
  });
  expect(matterUpload.status(), await matterUpload.text()).toBe(200);

  const employeeUpload = await api.post(
    `${apiBaseUrl}/api/companies/current/employees/imports/preview`,
    {
      headers,
      multipart: {
        file: {
          name: "iplf-032b-employees.csv",
          mimeType: "text/csv",
          buffer: Buffer.from([
            "Name,Email,Role,Mobile,Designation,Department,EmployeeCode,ManagerEmail",
            ",missing-name-032b@example.com,member,,,,,",
          ].join("\n"), "utf8"),
        },
      },
    },
  );
  expect(employeeUpload.status(), await employeeUpload.text()).toBe(200);

  const historyResponse = await api.get(`${apiBaseUrl}/api/imports/history`, { headers });
  expect(historyResponse.status(), await historyResponse.text()).toBe(200);
  const history = await historyResponse.json() as {
    accessible_domains: string[];
    jobs: Array<{
      id: string;
      domain: string;
      source_owner: string;
      source_status: string;
      status: string;
      read_only_adapter: boolean;
    }>;
  };
  expect(history.accessible_domains).toEqual(["ip_trademark", "matter", "employee"]);
  expect(new Set(history.jobs.map((job) => job.domain))).toEqual(
    new Set(["ip_trademark", "matter", "employee"]),
  );
  expect(history.jobs.find((job) => job.domain === "ip_trademark")).toMatchObject({
    source_owner: "bulk_import_jobs",
    read_only_adapter: false,
  });
  expect(history.jobs.find((job) => job.domain === "matter")).toMatchObject({
    source_owner: "matter_bulk_import_jobs",
    source_status: "validated",
    status: "preview_ready",
    read_only_adapter: true,
  });
  expect(history.jobs.find((job) => job.domain === "employee")).toMatchObject({
    source_owner: "employee_bulk_import_jobs",
    source_status: "previewed",
    status: "preview_ready",
    read_only_adapter: true,
  });

  const employeeJob = history.jobs.find((job) => job.domain === "employee")!;
  const manifestResponse = await api.get(
    `${apiBaseUrl}/api/imports/employee/${employeeJob.id}/manifest`,
    { headers },
  );
  expect(manifestResponse.status(), await manifestResponse.text()).toBe(200);
  expect(await manifestResponse.json()).toMatchObject({
    schema_version: "bulk-import-manifest-v1",
    compatibility_mode: "read_only_adapter",
    limitations: ["Legacy employee jobs did not persist an input checksum."],
  });
  const errorResponse = await api.get(
    `${apiBaseUrl}/api/imports/employee/${employeeJob.id}/errors`,
    { headers },
  );
  expect(errorResponse.status(), await errorResponse.text()).toBe(200);
  expect(await errorResponse.text()).toContain("Name is required");

  await signIn(page, tenant.slug, tenant.email);
  await page.goto("/app/imports");
  await expect(page.getByRole("heading", { name: "Import activity" })).toBeVisible();
  await expect(page.getByText("iplf-032b-trademarks.csv")).toBeVisible();
  await expect(page.getByText("iplf-032b-matters.csv")).toBeVisible();
  await expect(page.getByText("iplf-032b-employees.csv")).toBeVisible();

  await page.getByRole("tab", { name: "Employees" }).click();
  await expect(page.getByText("iplf-032b-employees.csv")).toBeVisible();
  await expect(page.getByText("iplf-032b-matters.csv")).toHaveCount(0);
  await page.getByRole("button", { name: "View manifest for iplf-032b-employees.csv" }).click();
  await expect(page.getByText("Legacy read-only")).toBeVisible();
  await expect(page.getByText("Legacy employee jobs did not persist an input checksum.")).toBeVisible();

  await page.getByRole("button", { name: "Close" }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("heading", { name: "Import activity" })).toBeVisible();
  const bodyWidth = await page.locator("body").evaluate((body) => body.getBoundingClientRect().width);
  expect(bodyWidth).toBeLessThanOrEqual(390);

  await api.dispose();
});
