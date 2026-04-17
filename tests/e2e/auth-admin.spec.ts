import { test, expect } from "@playwright/test";

import {
  bootstrapCompany,
  createCompanyUser,
  login,
  logout,
  uniqueId,
  updateCompanyProfile,
  waitForAppReady,
} from "./support/helpers";

test("bootstraps a company, saves profile data, manages users, and authenticates with email/password", async ({
  page,
}) => {
  const seed = uniqueId("auth");
  const company = {
    companyName: `CaseOps Auth ${seed}`,
    companySlug: `caseops-auth-${seed}`,
    companyType: "law_firm" as const,
    ownerFullName: "Owner CaseOps",
    ownerEmail: `owner.${seed}@example.com`,
    ownerPassword: "OwnerPass!2026",
  };
  const adminUser = {
    fullName: "Priya Admin",
    email: `priya.${seed}@example.com`,
    password: "AdminPass!2026",
    role: "admin" as const,
  };

  await bootstrapCompany(page, company);

  await updateCompanyProfile(page, {
    name: `CaseOps Litigation ${seed}`,
    primaryContactEmail: `hello.${seed}@example.com`,
    billingContactName: "Accounts Desk",
    billingContactEmail: `billing.${seed}@example.com`,
    headquarters: "Bengaluru",
    timezone: "Asia/Calcutta",
    websiteUrl: "https://caseops.ai",
    practiceSummary: "Litigation, contracts, and outside-counsel oversight.",
  });

  await page.reload();
  await waitForAppReady(page);
  const profileForm = page.getByTestId("company-profile-form");
  await expect(profileForm.getByLabel("Company name")).toHaveValue(`CaseOps Litigation ${seed}`);
  await expect(profileForm.getByLabel("Headquarters")).toHaveValue("Bengaluru");
  await expect(profileForm.getByLabel("Website URL")).toHaveValue("https://caseops.ai/");

  await createCompanyUser(page, adminUser);

  const authoritySearchForm = page.getByTestId("authority-search-form");
  await authoritySearchForm.scrollIntoViewIfNeeded();
  await authoritySearchForm
    .getByLabel("Search authority corpus")
    .fill("interim relief maintainability");
  await authoritySearchForm.getByLabel("Result limit").selectOption("3");
  await authoritySearchForm.getByRole("button", { name: "Search authorities" }).click();
  await expect(page.getByTestId("notice-banner")).toContainText(
    "Authority corpus search completed.",
  );
  await expect(
    page.getByText("No matching authorities were found in the current corpus."),
  ).toBeVisible();

  await logout(page);
  await expect(page.getByRole("heading", { name: "No active session" })).toBeVisible();

  await login(page, {
    email: adminUser.email,
    password: adminUser.password,
    companySlug: company.companySlug,
  });

  await expect(page.getByText(company.companySlug, { exact: true })).toBeVisible();
  await expect(page.getByText(adminUser.fullName, { exact: true }).first()).toBeVisible();
  await expect(page.getByText("admin", { exact: true }).first()).toBeVisible();
});
