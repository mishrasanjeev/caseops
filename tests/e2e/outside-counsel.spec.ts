import { expect, test } from "@playwright/test";

import { bootstrapCompany, createMatter, plusDays, uniqueId } from "./support/helpers";

test("runs the outside counsel flow across panel creation, assignment, spend, and recommendation", async ({
  page,
}) => {
  const seed = uniqueId("counsel");
  const company = {
    companyName: `CaseOps Counsel ${seed}`,
    companySlug: `caseops-counsel-${seed}`,
    companyType: "corporate_legal" as const,
    ownerFullName: "Counsel Owner",
    ownerEmail: `owner.${seed}@example.com`,
    ownerPassword: "OwnerPass!2026",
  };

  const commercialMatter = {
    title: "Delta Projects injunction appeal",
    matterCode: `COMM-${seed.toUpperCase()}`,
    clientName: "Delta Projects",
    opposingParty: "Metro Infrastructure Board",
    practiceArea: "Commercial Litigation",
    forumLevel: "high_court",
    courtName: "Delhi High Court",
    judgeName: "Justice Mehta",
    nextHearingOn: plusDays(12),
    description: "Urgent interim relief strategy around encashment and bank guarantee restraint.",
  };

  const arbitrationMatter = {
    title: "Echo Tech arbitration strategy",
    matterCode: `ARB-${seed.toUpperCase()}`,
    clientName: "Echo Tech",
    opposingParty: "Nimbus Networks",
    practiceArea: "Arbitration",
    forumLevel: "arbitration",
    courtName: "SIAC",
    judgeName: "",
    nextHearingOn: plusDays(24),
    description: "Arbitration-only posture for an unrelated technology dispute.",
  };

  await bootstrapCompany(page, company);
  await createMatter(page, commercialMatter);
  await createMatter(page, arbitrationMatter);

  const profileForm = page.getByTestId("outside-counsel-profile-form");
  await profileForm.scrollIntoViewIfNeeded();
  await profileForm.getByLabel("Firm or chamber name").fill("Khanna Advisory Chambers");
  await profileForm.getByLabel("Panel status").selectOption("preferred");
  await profileForm.getByLabel("Contact name").fill("Anika Khanna");
  await profileForm.getByLabel("Contact email").fill("anika@khanna.example");
  await profileForm.getByLabel("Contact phone").fill("+91-9876543210");
  await profileForm.getByLabel("Base city").fill("New Delhi");
  await profileForm
    .getByLabel("Jurisdictions")
    .fill("Delhi High Court, Supreme Court of India");
  await profileForm
    .getByLabel("Practice areas")
    .fill("Commercial Litigation, Arbitration");
  await profileForm
    .getByLabel("Internal panel note")
    .fill("Strong on injunction hearings and fast-turnaround appellate support.");
  await profileForm.getByRole("button", { name: "Add counsel profile" }).click();
  await expect(page.getByTestId("notice-banner")).toContainText(
    "Outside counsel profile created for Khanna Advisory Chambers.",
  );
  await expect(page.getByText("Khanna Advisory Chambers", { exact: true }).first()).toBeVisible();

  const assignmentForm = page.getByTestId("outside-counsel-assignment-form");
  await assignmentForm.scrollIntoViewIfNeeded();
  await assignmentForm
    .getByLabel("Matter")
    .selectOption({ label: `${commercialMatter.matterCode} · ${commercialMatter.title}` });
  await assignmentForm
    .getByLabel("Counsel")
    .selectOption({ label: "Khanna Advisory Chambers" });
  await assignmentForm.getByLabel("Assignment status").selectOption("active");
  await assignmentForm.getByLabel("Budget (minor units)").fill("500000");
  await assignmentForm
    .getByLabel("Role summary")
    .fill("Lead arguing counsel for admission and interim relief.");
  await assignmentForm
    .getByLabel("Internal note")
    .fill("Approved for immediate engagement by the litigation head.");
  await assignmentForm.getByRole("button", { name: "Link counsel to matter" }).click();
  await expect(page.getByTestId("notice-banner")).toContainText(
    `Linked Khanna Advisory Chambers to ${commercialMatter.matterCode}.`,
  );

  const spendForm = page.getByTestId("outside-counsel-spend-form");
  await spendForm.scrollIntoViewIfNeeded();
  await spendForm
    .getByLabel("Spend matter")
    .selectOption({ label: `${commercialMatter.matterCode} · ${commercialMatter.title}` });
  await spendForm.getByLabel("Spend counsel").selectOption({ label: "Khanna Advisory Chambers" });
  await spendForm.getByLabel("Spend status").selectOption("partially_approved");
  await spendForm.getByLabel("Invoice ref").fill("KAC/2026/044");
  await spendForm.getByLabel("Stage label").fill("Interim relief hearing");
  await spendForm
    .getByLabel("Description")
    .fill("Interim hearing fee, partner conference, and chronology review.");
  await spendForm.getByLabel("Amount (minor units)").fill("250000");
  await spendForm.getByLabel("Approved amount").fill("200000");
  await spendForm
    .getByLabel("Note")
    .fill("Approved subject to cap after portfolio spend review.");
  await spendForm.getByRole("button", { name: "Record spend" }).click();
  await expect(page.getByTestId("notice-banner")).toContainText(
    "Recorded spend for Khanna Advisory Chambers.",
  );
  await expect(page.getByText("Submitted ₹2,500.00 · approved ₹2,000.00")).toBeVisible();

  const recommendationForm = page.getByTestId("outside-counsel-recommendation-form");
  await recommendationForm.scrollIntoViewIfNeeded();
  await recommendationForm
    .getByLabel("Matter for recommendation")
    .selectOption({ label: `${commercialMatter.matterCode} · ${commercialMatter.title}` });
  await recommendationForm.getByLabel("Result limit").selectOption("3");
  await recommendationForm.getByRole("button", { name: "Recommend counsel" }).click();
  await expect(page.getByTestId("notice-banner")).toContainText(
    "Generated 1 outside counsel recommendation(s).",
  );
  await expect(page.getByTestId("outside-counsel-results")).toContainText(
    "Khanna Advisory Chambers",
  );
  await expect(page.getByTestId("outside-counsel-results")).toContainText(
    "Practice area match for Commercial Litigation.",
  );
});
