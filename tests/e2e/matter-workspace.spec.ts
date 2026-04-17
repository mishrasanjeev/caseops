import { expect, test } from "@playwright/test";

import {
  bootstrapCompany,
  createCompanyUser,
  createMatter,
  makeUploadFixture,
  openMatter,
  plusDays,
  runDocumentWorkerOnce,
  uniqueId,
} from "./support/helpers";

test("runs the matter workspace flow across court sync, documents, billing, and AI summaries", async ({
  page,
}) => {
  const seed = uniqueId("matter");
  const company = {
    companyName: `CaseOps Matter ${seed}`,
    companySlug: `caseops-matter-${seed}`,
    companyType: "law_firm" as const,
    ownerFullName: "Matter Owner",
    ownerEmail: `owner.${seed}@example.com`,
    ownerPassword: "OwnerPass!2026",
  };
  const assignee = {
    fullName: "Riya Associate",
    email: `riya.${seed}@example.com`,
    password: "MemberPass!2026",
    role: "member" as const,
  };
  const matter = {
    title: "Acme Builders v. Metro Authority",
    matterCode: `MAT-${seed.toUpperCase()}`,
    clientName: "Acme Builders Private Limited",
    opposingParty: "Metro Authority",
    practiceArea: "Commercial Litigation",
    forumLevel: "high_court",
    courtName: "Delhi High Court",
    judgeName: "Justice Mehta",
    nextHearingOn: plusDays(14),
    description: "Interim injunction challenge and project payment dispute.",
  };

  await bootstrapCompany(page, company);
  await createCompanyUser(page, assignee);
  await createMatter(page, matter);
  await openMatter(page, matter.matterCode);

  const workspaceForm = page.getByTestId("matter-workspace-form");
  await workspaceForm.scrollIntoViewIfNeeded();
  await workspaceForm.getByLabel("Status").selectOption("active");
  await workspaceForm
    .getByLabel("Assignee")
    .selectOption({ label: `${assignee.fullName} (${assignee.role})` });
  await workspaceForm.getByRole("button", { name: "Update workspace" }).click();
  await expect(page.getByTestId("notice-banner")).toContainText("Matter workspace updated.");

  const taskForm = page.getByTestId("matter-task-form");
  await taskForm.scrollIntoViewIfNeeded();
  await taskForm.getByLabel("Task title").fill("Prepare injunction authorities");
  await taskForm.getByLabel("Owner").selectOption({
    label: `${assignee.fullName} (${assignee.role})`,
  });
  await taskForm.getByLabel("Due date").fill(plusDays(5));
  await taskForm.getByLabel("Priority").selectOption("urgent");
  await taskForm
    .getByLabel("Description")
    .fill("Build the authority chain on performance guarantees and interim restraint.");
  await taskForm.getByRole("button", { name: "Add task" }).click();
  await expect(page.getByTestId("notice-banner")).toContainText("Matter task added.");
  await expect(page.getByTestId("matter-task-list")).toContainText(
    "Prepare injunction authorities",
  );
  await page.getByRole("button", { name: "Complete", exact: true }).first().click();
  await expect(page.getByTestId("notice-banner")).toContainText("Matter task updated.");
  await expect(page.getByTestId("matter-task-list")).toContainText("completed");

  const courtSyncForm = page.getByTestId("court-sync-import-form");
  await courtSyncForm.scrollIntoViewIfNeeded();
  await courtSyncForm.getByLabel("Source").fill("Delhi High Court daily order");
  await courtSyncForm
    .getByLabel("Sync summary")
    .fill("Imported the latest listing and interim order for the matter.");
  await courtSyncForm.getByLabel("Listing date").fill(plusDays(7));
  await courtSyncForm.getByLabel("Forum name").fill("Delhi High Court");
  await courtSyncForm.getByLabel("Bench / judge").fill("Justice Mehta");
  await courtSyncForm.getByLabel("Courtroom").fill("Court 32");
  await courtSyncForm.getByLabel("Item number").fill("Item 18");
  await courtSyncForm.getByLabel("Stage").fill("Interim relief");
  await courtSyncForm.getByLabel("Listing reference").fill("Cause list page 14");
  await courtSyncForm
    .getByLabel("Listing notes")
    .fill("Bench indicated tight timeline for reply and rejoinder.");
  await courtSyncForm.getByLabel("Order date").fill(plusDays(7));
  await courtSyncForm.getByLabel("Order title").fill("Interim injunction order");
  await courtSyncForm.getByLabel("Order reference").fill("Order PDF page 3");
  await courtSyncForm
    .getByLabel("Order summary")
    .fill("Counterparty restrained from encashment and rejoinder directed.");
  await courtSyncForm
    .getByLabel("Order text")
    .fill("The respondent is restrained from encashing the performance guarantee until the next date of hearing.");
  await courtSyncForm.getByRole("button", { name: "Import court sync" }).click();
  await expect(page.getByTestId("notice-banner")).toContainText(
    "Court sync imported into the matter workspace.",
  );
  await expect(page.getByText("Interim injunction order", { exact: true })).toBeVisible();

  const noteForm = page.getByTestId("matter-note-form");
  await noteForm.scrollIntoViewIfNeeded();
  await noteForm
    .getByLabel("Internal note")
    .fill("Need an authority bundle on performance guarantees and interim restraint.");
  await noteForm.getByRole("button", { name: "Add note" }).click();
  await expect(page.getByTestId("notice-banner")).toContainText("Matter note added.");
  await expect(
    page
      .getByText("Need an authority bundle on performance guarantees and interim restraint.")
      .first(),
  ).toBeVisible();

  const hearingForm = page.getByTestId("matter-hearing-form");
  await hearingForm.scrollIntoViewIfNeeded();
  await hearingForm.getByLabel("Hearing date").fill(plusDays(14));
  await hearingForm.getByLabel("Forum name").fill("Delhi High Court");
  await hearingForm.getByLabel("Judge name").fill("Justice Mehta");
  await hearingForm.getByLabel("Purpose").fill("Interim relief hearing");
  await hearingForm.getByLabel("Status").selectOption("scheduled");
  await hearingForm.getByRole("button", { name: "Add hearing" }).click();
  await expect(page.getByTestId("notice-banner")).toContainText("Matter hearing added.");
  await expect(page.getByText("Interim relief hearing", { exact: true })).toBeVisible();

  const matterFile = makeUploadFixture(
    `matter-${seed}.txt`,
    [
      "Acme Builders seeks an interim injunction against encashment of the performance guarantee.",
      "The project payment delay and inspection notices triggered the present petition.",
      "Chronology: 2026-02-01 notice, 2026-02-15 reply, 2026-03-03 encashment threat.",
    ].join("\n"),
  );
  const attachmentForm = page.getByTestId("matter-attachment-form");
  await attachmentForm.scrollIntoViewIfNeeded();
  await attachmentForm.locator('input[type="file"]').setInputFiles(matterFile);
  await attachmentForm.getByRole("button", { name: "Upload attachment" }).click();
  await expect(page.getByTestId("notice-banner")).toContainText(
    "Document uploaded and queued for processing.",
  );

  await runDocumentWorkerOnce();
  await page.reload();
  await openMatter(page, matter.matterCode);

  const searchForm = page.getByTestId("matter-document-search-form");
  await searchForm.scrollIntoViewIfNeeded();
  await searchForm.getByLabel("Search uploaded matter documents").fill("performance guarantee");
  await searchForm.getByLabel("Result limit").selectOption("3");
  await searchForm.getByRole("button", { name: "Search documents" }).click();
  await expect(page.getByTestId("notice-banner")).toContainText(
    "Matter document search completed.",
  );
  await expect(
    page.getByText("Acme Builders seeks an interim injunction against encashment", {
      exact: false,
    }),
  ).toBeVisible();

  const reviewForm = page.getByTestId("matter-document-review-form");
  await reviewForm.scrollIntoViewIfNeeded();
  await reviewForm
    .getByLabel("Review focus")
    .fill("Chronology, filings, evidence gaps, and hearing readiness.");
  await reviewForm.getByRole("button", { name: "Generate document review" }).click();
  await expect(page.getByTestId("notice-banner")).toContainText(
    "Matter document review generated.",
  );
  await expect(page.getByText("Source attachments")).toBeVisible();
  await expect(page.getByText(`matter-${seed}.txt`, { exact: true }).first()).toBeVisible();

  const briefForm = page.getByTestId("matter-brief-form");
  await briefForm.scrollIntoViewIfNeeded();
  await briefForm.getByLabel("Brief type").selectOption("hearing_prep");
  await briefForm
    .getByLabel("Focus")
    .fill("Focus on interim injunction strategy and upcoming hearing posture.");
  await briefForm.getByRole("button", { name: "Generate brief" }).click();
  await expect(page.getByTestId("notice-banner")).toContainText("Matter brief generated.");
  await expect(page.getByText("Source provenance")).toBeVisible();

  const timeEntryForm = page.getByTestId("time-entry-form");
  await timeEntryForm.scrollIntoViewIfNeeded();
  await timeEntryForm.getByLabel("Work date").fill(plusDays(0));
  await timeEntryForm.getByLabel("Duration (minutes)").fill("90");
  await timeEntryForm
    .getByLabel("Description")
    .fill("Prepared the interim injunction brief and coordinated hearing strategy.");
  await timeEntryForm.getByLabel("Billable").selectOption("yes");
  await timeEntryForm.getByLabel("Rate per hour (INR)").fill("12000");
  await timeEntryForm.getByRole("button", { name: "Log time entry" }).click();
  await expect(page.getByTestId("notice-banner")).toContainText("Time entry logged.");
  await expect(
    page.getByText("Prepared the interim injunction brief and coordinated hearing strategy."),
  ).toBeVisible();

  const invoiceForm = page.getByTestId("invoice-form");
  await invoiceForm.scrollIntoViewIfNeeded();
  await invoiceForm.getByLabel("Invoice number").fill(`INV-${seed.toUpperCase()}`);
  await invoiceForm.getByLabel("Status").selectOption("issued");
  await invoiceForm.getByLabel("Issued on").fill(plusDays(0));
  await invoiceForm.getByLabel("Due on").fill(plusDays(15));
  await invoiceForm.getByLabel("Client name").fill(matter.clientName);
  await invoiceForm.getByLabel("Tax amount (INR)").fill("1800");
  await invoiceForm.getByLabel("Include open time entries").selectOption("yes");
  await invoiceForm.getByLabel("Manual item amount (INR)").fill("2500");
  await invoiceForm.getByLabel("Manual item description").fill("Registry and filing support");
  await invoiceForm
    .getByLabel("Invoice notes")
    .fill("Invoice includes hearing-prep time and filing coordination.");
  await invoiceForm.getByRole("button", { name: "Create invoice" }).click();
  await expect(page.getByTestId("notice-banner")).toContainText(
    "Invoice created for the selected matter.",
  );
  await expect(page.getByText(`INV-${seed.toUpperCase()}`, { exact: true }).first()).toBeVisible();
});
