import { expect, test } from "@playwright/test";

import {
  bootstrapCompany,
  createMatter,
  openMatter,
  plusDays,
  uniqueId,
} from "./support/helpers";

const liveSourcesEnabled = process.env.CASEOPS_E2E_ENABLE_LIVE_SOURCES === "1";
const pineLabsEnabled = process.env.CASEOPS_E2E_ENABLE_PINE_LABS === "1";

test.describe("real external integrations", () => {
  test("pulls live official authorities and searches the ingested corpus", async ({ page }) => {
    test.skip(
      !liveSourcesEnabled,
      "Set CASEOPS_E2E_ENABLE_LIVE_SOURCES=1 to run against real official sources.",
    );

    const seed = uniqueId("authority-live");
    const company = {
      companyName: `CaseOps Live ${seed}`,
      companySlug: `caseops-live-${seed}`,
      companyType: "law_firm" as const,
      ownerFullName: "Live Source Owner",
      ownerEmail: `owner.${seed}@example.com`,
      ownerPassword: "OwnerPass!2026",
    };

    await bootstrapCompany(page, company);

    const ingestionForm = page.getByTestId("authority-ingestion-form");
    await ingestionForm.scrollIntoViewIfNeeded();
    await ingestionForm
      .getByLabel("Official source")
      .selectOption(process.env.CASEOPS_E2E_AUTHORITY_SOURCE ?? "supreme_court_latest_orders");
    await ingestionForm
      .getByLabel("Max documents")
      .selectOption(process.env.CASEOPS_E2E_AUTHORITY_MAX_DOCUMENTS ?? "5");
    await ingestionForm.getByRole("button", { name: "Pull official authorities" }).click();
    await expect(page.getByTestId("notice-banner")).toContainText(/authority/i);

    const searchForm = page.getByTestId("authority-search-form");
    await searchForm.scrollIntoViewIfNeeded();
    await searchForm
      .getByLabel("Search authority corpus")
      .fill(process.env.CASEOPS_E2E_AUTHORITY_QUERY ?? "interim relief");
    await searchForm.getByRole("button", { name: "Search authorities" }).click();
    await expect(page.getByTestId("notice-banner")).toContainText(
      "Authority corpus search completed.",
    );
    await expect(page.getByText(/score/i)).toBeVisible();
  });

  test("queues a real live court-data pull for a matter when a verified reference is provided", async ({
    page,
  }) => {
    test.skip(
      !liveSourcesEnabled,
      "Set CASEOPS_E2E_ENABLE_LIVE_SOURCES=1 and live court env vars to run against real official sources.",
    );

    const liveCourtSource = process.env.CASEOPS_E2E_LIVE_COURT_SOURCE;
    const liveCourtReference = process.env.CASEOPS_E2E_LIVE_COURT_REFERENCE;
    test.skip(!liveCourtSource || !liveCourtReference, "Missing live court source/reference.");

    const seed = uniqueId("court-live");
    const company = {
      companyName: `CaseOps Court ${seed}`,
      companySlug: `caseops-court-${seed}`,
      companyType: "law_firm" as const,
      ownerFullName: "Court Owner",
      ownerEmail: `owner.${seed}@example.com`,
      ownerPassword: "OwnerPass!2026",
    };
    const matter = {
      title: "Live court sync matter",
      matterCode: `MAT-${seed.toUpperCase()}`,
      clientName: "Live Client",
      opposingParty: "Live Opponent",
      practiceArea: "Litigation",
      forumLevel: "high_court",
      courtName: "Live Court",
      judgeName: "",
      nextHearingOn: plusDays(7),
      description: "Used for official-source live sync validation.",
    };

    await bootstrapCompany(page, company);
    await createMatter(page, matter);
    await openMatter(page, matter.matterCode);

    const liveForm = page.getByTestId("court-sync-live-form");
    await liveForm.scrollIntoViewIfNeeded();
    await liveForm.getByLabel("Live source").selectOption(liveCourtSource);
    await liveForm.getByLabel("Matching reference").fill(liveCourtReference);
    await liveForm.getByRole("button", { name: "Pull live court data" }).click();
    await expect(page.getByTestId("notice-banner")).toContainText(
      "Live court-data pull queued from the selected official source.",
    );
  });

  test("creates a Pine Labs payment link when real gateway credentials are present", async ({
    page,
  }) => {
    test.skip(
      !pineLabsEnabled,
      "Set CASEOPS_E2E_ENABLE_PINE_LABS=1 and provide Pine Labs env vars to run against the real gateway.",
    );

    const seed = uniqueId("payments-live");
    const company = {
      companyName: `CaseOps Payments ${seed}`,
      companySlug: `caseops-payments-${seed}`,
      companyType: "law_firm" as const,
      ownerFullName: "Payments Owner",
      ownerEmail: `owner.${seed}@example.com`,
      ownerPassword: "OwnerPass!2026",
    };
    const matter = {
      title: "Pine Labs invoice matter",
      matterCode: `MAT-${seed.toUpperCase()}`,
      clientName: "Invoice Client",
      opposingParty: "Invoice Opponent",
      practiceArea: "Fee ops",
      forumLevel: "advisory",
      courtName: "Internal",
      judgeName: "",
      nextHearingOn: "",
      description: "Used for Pine Labs end-to-end payment validation.",
    };

    await bootstrapCompany(page, company);
    await createMatter(page, matter);
    await openMatter(page, matter.matterCode);

    const timeEntryForm = page.getByTestId("time-entry-form");
    await timeEntryForm.getByLabel("Work date").fill(plusDays(0));
    await timeEntryForm.getByLabel("Duration (minutes)").fill("60");
    await timeEntryForm.getByLabel("Description").fill("Fee collection prep.");
    await timeEntryForm.getByLabel("Billable").selectOption("yes");
    await timeEntryForm.getByLabel("Rate per hour (INR)").fill("10000");
    await timeEntryForm.getByRole("button", { name: "Log time entry" }).click();
    await expect(page.getByTestId("notice-banner")).toContainText("Time entry logged.");

    const invoiceForm = page.getByTestId("invoice-form");
    await invoiceForm.getByLabel("Invoice number").fill(`INV-${seed.toUpperCase()}`);
    await invoiceForm.getByLabel("Status").selectOption("issued");
    await invoiceForm.getByLabel("Issued on").fill(plusDays(0));
    await invoiceForm.getByLabel("Client name").fill(matter.clientName);
    await invoiceForm.getByRole("button", { name: "Create invoice" }).click();
    await expect(page.getByTestId("notice-banner")).toContainText(
      "Invoice created for the selected matter.",
    );

    await page.getByLabel("Payment contact name").fill("Finance Team");
    await page.getByLabel("Payment contact email").fill("finance@example.com");
    await page.getByLabel("Payment contact phone").fill("9999999999");
    await page.getByRole("button", { name: /Create Pine Labs link|Refresh link/ }).click();
    await expect(page.getByTestId("notice-banner")).toContainText(
      "Pine Labs payment link created.",
    );
  });
});
