import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "IpDocketProof2026!";

function unique(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

async function bootstrap(api: APIRequestContext, slug: string): Promise<{ token: string; membershipId: string }> {
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IP Docket Proof LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "IP Proof Owner",
      owner_email: `owner-${slug}@example.com`,
      owner_password: PASSWORD,
    },
  });
  expect(response.status()).toBe(200);
  const body = await response.json();
  return { token: body.access_token as string, membershipId: body.membership.id as string };
}

async function seedLinkedIpDocket(api: APIRequestContext, token: string, membershipId: string): Promise<void> {
  const headers = { Authorization: `Bearer ${token}` };
  const matterResponse = await api.post(`${apiBaseUrl}/api/matters/`, {
    headers,
    data: { title: "IP operations Matter", matter_code: unique("IP-E2E").toUpperCase(), practice_area: "intellectual_property", forum_level: "tribunal", status: "intake" },
  });
  expect(matterResponse.status()).toBe(200);
  const matterId = (await matterResponse.json()).id as string;
  const communication = await api.post(`${apiBaseUrl}/api/matters/${matterId}/communications`, {
    headers,
    data: { direction: "inbound", channel: "email", subject: "Client filing instruction", body: "Proceed with the registry response." },
  });
  expect(communication.status()).toBe(200);
  const deadline = await api.post(`${apiBaseUrl}/api/matters/${matterId}/deadlines`, {
    headers,
    data: { source: "custom", kind: "filing", title: "Registry response", due_on: "2026-09-30", assignee_membership_id: membershipId },
  });
  expect(deadline.status()).toBe(200);
  const deadlineId = (await deadline.json()).id as string;
  const docket = await api.post(`${apiBaseUrl}/api/ip/dockets`, {
    headers,
    data: {
      title: "ORBIT linked mark", matter_id: matterId, primary_identifier: unique("TM-LINKED"),
      particulars: {
        form_key: "TM-A", form_version: "2026.1", mark_kind: "word",
        representation: { text: "ORBIT", evidence_reference: "attachment:orbit-mark" },
        classes: [{ class_number: 42, specification: "Legal software services" }],
        use_priority: null, parties: [{ role: "applicant", name: "Orbit Legal LLP" }], agent: null,
        filing_manifest: [{ key: "representation", label: "Mark representation", required: true, evidence_reference: "attachment:orbit-mark" }],
      },
    },
  });
  expect(docket.status()).toBe(201);
  const docketId = (await docket.json()).id as string;
  const coverage = await api.post(`${apiBaseUrl}/api/ip/dockets/${docketId}/deadline-coverages`, {
    headers,
    data: { matter_deadline_id: deadlineId, responsible_membership_id: membershipId, coverage_status: "accepted" },
  });
  expect(coverage.status()).toBe(200);
}

async function signIn(page: Page, slug: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(`owner-${slug}@example.com`);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

test.describe("Ram 2026-08-01 IP law firm slices", () => {
  test.setTimeout(120_000);

  test("IP docket creates a validated trademark and keeps every grouped action visible at 360px", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("ip-proof");
    await bootstrap(api, slug);
    await signIn(page, slug);

    await page.setViewportSize({ width: 360, height: 800 });
    await page.goto("/app/ip");
    await expect(page.getByRole("heading", { name: "Trademark docket" })).toBeVisible();

    const create = page.getByRole("button", { name: "New trademark" });
    await expect(create).toBeVisible();
    const createBox = await create.boundingBox();
    expect(createBox).not.toBeNull();
    expect(createBox!.x).toBeGreaterThanOrEqual(0);
    expect(createBox!.x + createBox!.width).toBeLessThanOrEqual(360);
    await create.click();

    await page.getByLabel("Docket title").fill("ASTER mobile mark");
    await page.getByLabel("Application / client reference").fill("TM-MOBILE-001");
    await page.getByLabel("Word mark").fill("ASTER");
    await page.getByLabel("Nice class").fill("42");
    await page.getByLabel("Goods / services specification").fill("Legal software services");
    await page.getByLabel("Applicant").fill("Aster Legal LLP");
    await page
      .getByLabel("Representation evidence reference")
      .fill("attachment:mobile-mark-proof");
    const submit = page.getByRole("button", { name: "Validate and create" });
    await expect(submit).toBeVisible();
    const submitBox = await submit.boundingBox();
    expect(submitBox).not.toBeNull();
    expect(submitBox!.x + submitBox!.width).toBeLessThanOrEqual(360);
    await submit.click();

    await expect(
      page.getByRole("heading", { name: "ASTER mobile mark", exact: true }),
    ).toBeVisible();
    const workspace = page.getByTestId("ip-docket-workspace");
    await expect(workspace).toBeVisible();
    await expect(workspace.getByText("Readiness")).toBeVisible();
    await expect(workspace.getByText("Operational links")).toBeVisible();
    await expect(page.getByRole("button", { name: "Add ownership evidence" })).toBeVisible();
  });

  test("linked Matter evidence, obligations, coverage, and reconciliation complete through the browser", async ({ page }) => {
    const api = await request.newContext();
    const slug = unique("ip-complete");
    const { token, membershipId } = await bootstrap(api, slug);
    await seedLinkedIpDocket(api, token, membershipId);
    await signIn(page, slug);
    await page.setViewportSize({ width: 360, height: 900 });
    await page.goto("/app/ip");

    await expect(page.getByRole("heading", { name: "ORBIT linked mark", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Discover Matter evidence" }).click();
    await expect(page.getByText("Client filing instruction")).toBeVisible();
    await page.getByRole("button", { name: "Accept and link" }).click();
    await expect(page.getByText(/Evidence review recorded/)).toBeVisible();

    await page.getByLabel("Obligation", { exact: true }).fill("Record assignment");
    await page.getByLabel("Owner membership ID").fill(membershipId);
    await page.getByLabel("Obligation evidence").fill("attachment:assignment-deed");
    await page.getByRole("button", { name: "Add recordal obligation" }).click();
    await expect(page.getByText("Record assignment")).toBeVisible();

    const costSubmit = page.getByRole("button", { name: "Add cost evidence" });
    const costForm = costSubmit.locator("xpath=ancestor::form");
    await costForm.getByLabel("Description").fill("Registry fee");
    await costForm.getByLabel("Amount (INR)").fill("9000");
    await costForm.getByLabel("Evidence reference").fill("receipt:registry-fee");
    await costSubmit.click();
    await expect(page.getByText("Registry fee")).toBeVisible();
    await page.getByRole("button", { name: "Reconcile with Matter billing" }).click();

    for (const name of ["Discover Matter evidence", "Transfer covered deadlines", "Add recordal obligation", "Reconcile with Matter billing"]) {
      const control = page.getByRole("button", { name });
      await expect(control).toBeVisible();
      const box = await control.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(360);
    }
  });
});
