/** IPLF-063B / UJ-18 source-frozen intelligent-review acceptance. */

import { expect, request, test } from "@playwright/test";

import {
  bootstrapIntelligentReviewTenant,
  createIntelligentReviewAuthorityFixture,
  enableIntelligentReviewIpWorkspace,
  signInIntelligentReviewTenant,
} from "./support/iplf063b";
import { apiBaseUrl } from "./support/env";
import { expectStatus } from "./support/iplf058b";

test("IPLF-063B completes UJ-18 normal and exception paths", async ({ page }) => {
  test.setTimeout(360_000);
  page.setDefaultTimeout(30_000);
  const api = await request.newContext();
  const tenant = await bootstrapIntelligentReviewTenant(api);
  await enableIntelligentReviewIpWorkspace(api, tenant);
  const fixture = createIntelligentReviewAuthorityFixture();
  const session = await signInIntelligentReviewTenant(page, tenant);
  const headers = { Authorization: `Bearer ${session.access_token}` };
  const run = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

  const matterResponse = await api.post(`${apiBaseUrl}/api/matters/`, {
    headers,
    data: {
      matter_code: `IR-${run}`,
      title: `Intelligent review opposition ${run}`,
      practice_area: "Intellectual Property",
      forum_level: "tribunal",
      court_name: "Trade Marks Registry Delhi",
      status: "intake",
    },
  });
  await expectStatus(matterResponse, 200, "create intelligent-review Matter");
  const matter = await matterResponse.json();

  const applicationResponse = await api.post(
    `${apiBaseUrl}/api/ip/trademark-applications/manual`,
    {
      headers,
      data: {
        title: `IPLF 063B MARK ${run}`,
        restricted: false,
        asset_title: `IPLF 063B MARK ${run}`,
        jurisdiction: "IN",
        office: "Trade Marks Registry Delhi",
        filing_phase: "draft",
        source_pending_identifier_allocation: false,
        application_number: {
          raw_value: `TM-063B-${run}`,
          source: "iplf-063b e2e registry fixture",
          effective_from: "2026-08-28",
          is_primary: true,
        },
        particulars: {
          form_key: "TM-A",
          form_version: "2026.1",
          mark_kind: "word",
          representation: { text: `IPLF 063B MARK ${run}`, evidence_reference: "e2e:063b:mark" },
          classes: [{ class_number: 45, specification: "Legal services" }],
          use_priority: null,
          parties: [{ role: "applicant", name: "IPLF 063B Applicant Private Limited" }],
          agent: null,
          filing_manifest: [{
            key: "representation",
            label: "Mark representation",
            required: true,
            evidence_reference: "e2e:063b:mark",
          }],
        },
      },
    },
  );
  await expectStatus(applicationResponse, 201, "create intelligent-review IP application");
  const application = await applicationResponse.json();
  const proceedingResponse = await api.post(
    `${apiBaseUrl}/api/ip/dockets/${application.docket.id}/proceedings`,
    {
      headers,
      data: {
        application_id: application.application.id,
        proceeding_kind: "opposition",
        side: "opponent",
        office: "Trade Marks Registry Delhi",
        jurisdiction: "IN",
        stage: "draft",
        origin_kind: "registry_event",
        source_pending_identifier_allocation: true,
      },
    },
  );
  await expectStatus(proceedingResponse, 201, "create intelligent-review opposition");
  const proceeding = await proceedingResponse.json();

  const reportResponse = await api.post(`${apiBaseUrl}/api/authorities/research-reports`, {
    headers,
    data: {
      name: `IPLF 063B frozen review ${run}`,
      query: "prior use and deceptive similarity",
      mode: "keyword",
      result_ids: fixture.accessibleIds,
      criteria: { language: "any" },
    },
  });
  await expectStatus(reportResponse, 201, "create accessible frozen report");
  const report = await reportResponse.json();

  const blockedReportResponse = await api.post(
    `${apiBaseUrl}/api/authorities/research-reports`,
    {
      headers,
      data: {
        name: `IPLF 063B inaccessible review ${run}`,
        query: "inaccessible authority exception",
        mode: "keyword",
        result_ids: [fixture.inaccessibleId],
        criteria: { language: "any" },
      },
    },
  );
  await expectStatus(blockedReportResponse, 201, "create inaccessible frozen report");
  const blockedReport = await blockedReportResponse.json();

  await test.step("IPLF-UJ-18-NORMAL generates, verifies, finalizes, and publishes", async () => {
    await page.goto(`/app/research/reviews?report=${encodeURIComponent(report.id)}`);
    await expect(
      page.getByRole("heading", { name: "Intelligent review", exact: true }),
    ).toBeVisible();
    await page.getByRole("combobox", { name: "Matter target" }).click();
    await page.getByRole("option", { name: new RegExp(`^${matter.matter_code} ·`) }).click();
    await page.getByLabel("Fact 1 label").fill("First use");
    await page.getByLabel("Fact 1 value").fill("2018");
    await page.getByLabel("Fact 1 source").fill("Client instruction");
    await page.getByRole("button", { name: "Add fact" }).click();
    await page.getByLabel("Fact 2 label").fill("First use");
    await page.getByLabel("Fact 2 value").fill("2019");
    await page.getByLabel("Fact 2 source").fill("Registry form");
    await page.getByLabel("Document references").fill("Client instruction v1\nRegistry form v2");
    await page.getByRole("button", { name: "Generate review" }).click();

    const detail = page.getByTestId("intelligent-review-detail");
    await expect(detail.getByText("Supporting and contrary authorities")).toBeVisible();
    await expect(detail.getByText(/Conflicting values remain for First use/)).toBeVisible();
    await test.step("IPLF-UJ-18-EXC-02 retains the stale-corpus warning", async () => {
      await expect(detail.getByText(/no recent retrieval timestamp/)).toBeVisible();
    });
    for (const url of new Set(fixture.sourceUrls)) {
      const matches = detail.getByText(url, { exact: true });
      const expectedCount = fixture.sourceUrls.filter((sourceUrl) => sourceUrl === url).length;
      await expect(matches).toHaveCount(expectedCount);
      for (let index = 0; index < expectedCount; index += 1) {
        await expect(matches.nth(index)).toBeVisible();
      }
    }
    await expect(detail.getByText(/not exhaustive legal research/)).toBeVisible();
  });

  await test.step("AI-REV-05 citation removal blocks finalization", async () => {
    const detail = page.getByTestId("intelligent-review-detail");
    const contraryCheckbox = detail.getByRole("checkbox", { name: /review authority 2/i });
    await contraryCheckbox.uncheck();
    await detail.getByRole("button", { name: "Save selection" }).click();
    await expect(detail.getByText(/no longer have a selected citation/)).toBeVisible();
    await expect(detail.getByRole("button", { name: "Finalize review" })).toBeDisabled();
    await contraryCheckbox.check();
    await detail.getByRole("button", { name: "Save selection" }).click();
    await expect(detail.getByText("Complete", { exact: true })).toBeVisible();
    await detail.getByLabel("Review notes").fill("Both sides checked against the frozen record.");
    await detail.getByRole("button", { name: "Finalize review" }).click();
    await detail.getByRole("button", { name: "Publish to Drafts" }).click();
    await expect(detail.getByRole("link", { name: /Open Draft/ })).toHaveAttribute(
      "href",
      new RegExp(`/app/matters/${matter.id}/drafts/[^/]+$`),
    );
  });

  await test.step("IPLF-UJ-18-NORMAL publishes into the exact IP opposition Draft", async () => {
    await page.goto(`/app/research/reviews?report=${encodeURIComponent(report.id)}`);
    await page.getByRole("tab", { name: "IP docket" }).click();
    await page.getByRole("combobox", { name: "IP docket target" }).click();
    await page.getByRole("option", { name: new RegExp(`^${application.identifier.raw_value} ·`) }).click();
    await page.getByRole("combobox", { name: "Opposition proceeding for Draft handoff" }).click();
    await page.getByRole("option", { name: /opponent.*draft.*Trade Marks Registry Delhi/i }).click();
    await page.getByRole("button", { name: "Generate review" }).click();

    const detail = page.getByTestId("intelligent-review-detail");
    await expect(detail.getByText("Supporting and contrary authorities")).toBeVisible();
    await detail.getByLabel("Review notes").fill("Approved for opposition pleading handoff.");
    await detail.getByRole("button", { name: "Finalize review" }).click();
    await detail.getByRole("button", { name: "Publish to Drafts" }).click();
    const draftLink = detail.getByRole("link", { name: /Open Draft/ });
    const expectedHref = new RegExp(
      `/app/ip\\?docket=${application.docket.id}&view=proceedings&proceeding=${proceeding.id}&draft=[^&]+$`,
    );
    await expect(draftLink).toHaveAttribute("href", expectedHref);
    const publishedDraftId = new URL(
      (await draftLink.getAttribute("href")) ?? "",
      "http://caseops.test",
    ).searchParams.get("draft");
    expect(publishedDraftId).toBeTruthy();
    await draftLink.click();
    await expect(page).toHaveURL(expectedHref);
    await expect(page.getByRole("tab", { name: "Proceedings" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.getByLabel("Opposition proceeding", { exact: true })).toHaveValue(
      proceeding.id,
    );
    await expect(page.getByTestId("ip-pleading-workspace")).toHaveAttribute(
      "aria-busy",
      "false",
      { timeout: 60_000 },
    );
    await expect(page.getByLabel("Pleading draft", { exact: true })).toHaveValue(
      publishedDraftId!,
    );
    await expect(page.getByLabel("Pleading body", { exact: true })).toHaveValue(
      /source-bounded decision support/i,
    );
  });

  await test.step("IPLF-UJ-18-EXC-01 and IPLF-UJ-18-EXC-03 inaccessible-only sources abstain", async () => {
    await page.goto(`/app/research/reviews?report=${encodeURIComponent(blockedReport.id)}`);
    await page.getByRole("combobox", { name: "Matter target" }).click();
    await page.getByRole("option", { name: new RegExp(`^${matter.matter_code} ·`) }).click();
    await page.getByRole("button", { name: "Generate review" }).click();
    await expect(
      page.getByTestId("intelligent-review-detail").getByText(/No selected authority has both an accessible source and usable text/),
    ).toBeVisible();
  });

  await test.step("The review, guide, and law-firm surfaces remain usable at 360px", async () => {
    await page.setViewportSize({ width: 360, height: 800 });
    await page.reload();
    for (const name of ["Frozen research report", "Matter target", "Issue for review"]) {
      await expect(page.getByLabel(name)).toBeVisible();
    }
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
      ),
    ).toBe(false);
    await page.goto("/guide");
    await expect(page.getByText("Intelligent-review safety boundary")).toBeVisible();
    await page.goto("/law-firms");
    await expect(page.getByRole("heading", { name: "Source-bounded intelligent review" })).toBeVisible();
  });

  await api.dispose();
});
