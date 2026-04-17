import { expect, test } from "@playwright/test";

import {
  bootstrapCompany,
  createContract,
  createMatter,
  makeUploadFixture,
  openContract,
  openMatter,
  plusDays,
  runDocumentWorkerOnce,
  uniqueId,
} from "./support/helpers";

test("runs the contract workspace flow across uploads, review, clauses, obligations, and playbook rules", async ({
  page,
}) => {
  const seed = uniqueId("contract");
  const company = {
    companyName: `CaseOps Contract ${seed}`,
    companySlug: `caseops-contract-${seed}`,
    companyType: "corporate_legal" as const,
    ownerFullName: "Contract Owner",
    ownerEmail: `owner.${seed}@example.com`,
    ownerPassword: "OwnerPass!2026",
  };
  const matter = {
    title: "Nimbus Cloud MSA dispute",
    matterCode: `MAT-${seed.toUpperCase()}`,
    clientName: "CaseOps India Private Limited",
    opposingParty: "Nimbus Cloud Services",
    practiceArea: "Technology Contracts",
    forumLevel: "advisory",
    courtName: "Internal legal",
    judgeName: "",
    nextHearingOn: plusDays(30),
    description: "Commercial advice and fallback litigation posture around a cloud MSA.",
  };
  const contract = {
    title: "Nimbus Cloud MSA",
    contractCode: `CTR-${seed.toUpperCase()}`,
    contractType: "MSA",
    counterpartyName: "Nimbus Cloud Services",
    status: "under_review",
    jurisdiction: "Delhi",
    effectiveOn: plusDays(-30),
    expiresOn: plusDays(335),
    renewalOn: plusDays(320),
    totalValue: "1500000",
    currency: "INR",
    summary: "Review fallback liability caps, termination rights, and data security obligations.",
  };

  await bootstrapCompany(page, company);
  await createMatter(page, matter);
  await openMatter(page, matter.matterCode);

  await createContract(page, contract);
  await openContract(page, contract.contractCode);

  const workspaceForm = page.getByTestId("contract-workspace-form");
  await workspaceForm.scrollIntoViewIfNeeded();
  await workspaceForm.getByLabel("Status").selectOption("negotiation");
  await workspaceForm.getByLabel("Linked matter").selectOption({
    label: `${matter.matterCode} - ${matter.title}`,
  });
  await workspaceForm.getByRole("button", { name: "Update contract" }).click();
  await expect(page.getByTestId("notice-banner")).toContainText("Contract workspace updated.");

  const contractFile = makeUploadFixture(
    `contract-${seed}.txt`,
    [
      "Termination for convenience requires a 60-day notice period and board-level approval.",
      "Vendor must deliver a quarterly security compliance report and notify incidents within 24 hours.",
      "Liability cap is limited to fees paid in the preceding twelve months, excluding confidentiality breaches.",
    ].join("\n"),
  );
  const attachmentForm = page.getByTestId("contract-attachment-form");
  await attachmentForm.scrollIntoViewIfNeeded();
  await attachmentForm.locator('input[type="file"]').setInputFiles(contractFile);
  await attachmentForm.getByRole("button", { name: "Upload contract document" }).click();
  await expect(page.getByTestId("notice-banner")).toContainText(
    "Contract document uploaded and queued for processing.",
  );

  await runDocumentWorkerOnce();
  await page.reload();
  await openContract(page, contract.contractCode);

  const reviewForm = page.getByTestId("contract-review-form");
  await reviewForm.scrollIntoViewIfNeeded();
  await reviewForm
    .getByLabel("Focus")
    .fill("Security posture, liability cap, termination fallback, and renewal risk.");
  await reviewForm.getByRole("button", { name: "Generate contract review" }).click();
  await expect(page.getByTestId("notice-banner")).toContainText("Contract review generated.");
  await expect(page.getByText("Key clauses")).toBeVisible();
  await expect(page.getByText("Risks")).toBeVisible();

  const clauseForm = page.getByTestId("contract-clause-form");
  await clauseForm.scrollIntoViewIfNeeded();
  await clauseForm.getByLabel("Clause title").fill("Termination for convenience");
  await clauseForm.getByLabel("Clause type").fill("termination");
  await clauseForm.getByLabel("Risk level").selectOption("high");
  await clauseForm
    .getByLabel("Clause text")
    .fill("Either party may terminate for convenience with 60 days' prior written notice.");
  await clauseForm
    .getByLabel("Notes")
    .fill("Requires fallback language for transition support and prepaid refund rights.");
  await clauseForm.getByRole("button", { name: "Add clause" }).click();
  await expect(page.getByTestId("notice-banner")).toContainText("Contract clause added.");
  await expect(page.getByText("Termination for convenience", { exact: true })).toBeVisible();

  const obligationForm = page.getByTestId("contract-obligation-form");
  await obligationForm.scrollIntoViewIfNeeded();
  await obligationForm.getByLabel("Priority").selectOption("high");
  await obligationForm.getByLabel("Status").selectOption("pending");
  await obligationForm.getByLabel("Due date").fill(plusDays(10));
  await obligationForm.getByLabel("Obligation title").fill("Deliver security addendum redlines");
  await obligationForm
    .getByLabel("Description")
    .fill("Send redlines covering breach notification timing and annual audit rights.");
  await obligationForm.getByRole("button", { name: "Add obligation" }).click();
  await expect(page.getByTestId("notice-banner")).toContainText("Contract obligation added.");
  await expect(
    page.getByText("Deliver security addendum redlines", { exact: true }),
  ).toBeVisible();

  const playbookForm = page.getByTestId("contract-playbook-rule-form");
  await playbookForm.scrollIntoViewIfNeeded();
  await playbookForm.getByLabel("Rule name").fill("Termination requires 30-day notice");
  await playbookForm.getByLabel("Clause type").fill("termination");
  await playbookForm.getByLabel("Severity").selectOption("high");
  await playbookForm.getByLabel("Keyword pattern").fill("30 days");
  await playbookForm
    .getByLabel("Expected position")
    .fill("Termination for convenience should require at least 30 days' prior written notice.");
  await playbookForm
    .getByLabel("Fallback text")
    .fill("If notice is shorter, require transition support and unused-fee refund language.");
  await playbookForm.getByRole("button", { name: "Add playbook rule" }).click();
  await expect(page.getByTestId("notice-banner")).toContainText(
    "Contract playbook rule added.",
  );
  await expect(
    page.getByText("Termination requires 30-day notice", { exact: true }).first(),
  ).toBeVisible();
});
