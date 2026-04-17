import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

import { expect, type Locator, type Page } from "@playwright/test";

import { e2eEnv, repoRoot, uploadsRoot } from "./env";

export type CompanySeed = {
  companyName: string;
  companySlug: string;
  companyType: "law_firm" | "corporate_legal";
  ownerFullName: string;
  ownerEmail: string;
  ownerPassword: string;
};

export type UserSeed = {
  fullName: string;
  email: string;
  password: string;
  role: "admin" | "member";
};

export type MatterSeed = {
  title: string;
  matterCode: string;
  clientName: string;
  opposingParty: string;
  practiceArea: string;
  forumLevel: string;
  courtName: string;
  judgeName: string;
  nextHearingOn: string;
  description: string;
};

export type ContractSeed = {
  title: string;
  contractCode: string;
  contractType: string;
  counterpartyName: string;
  status: string;
  jurisdiction: string;
  effectiveOn: string;
  expiresOn: string;
  renewalOn: string;
  totalValue: string;
  currency: string;
  summary: string;
};

function submitButton(form: Locator, buttonName: string): Locator {
  return form.getByRole("button", { name: buttonName, exact: true });
}

export async function waitForAppReady(page: Page): Promise<void> {
  await expect(page.getByTestId("app-ready")).toHaveText("yes");
}

export function uniqueId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
}

export function plusDays(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

export function makeUploadFixture(filename: string, contents: string): string {
  fs.mkdirSync(uploadsRoot, { recursive: true });
  const filePath = path.join(uploadsRoot, filename);
  fs.writeFileSync(filePath, contents, "utf8");
  return filePath;
}

export async function runDocumentWorkerOnce(): Promise<void> {
  const result = spawnSync(
    "uv",
    ["--directory", "apps/api", "run", "caseops-document-worker", "--once"],
    {
      cwd: repoRoot,
      env: {
        ...process.env,
        ...e2eEnv,
      },
      encoding: "utf8",
    },
  );

  if (result.status !== 0) {
    throw new Error(
      `Document worker failed with status ${result.status}.\nSTDOUT:\n${result.stdout}\nSTDERR:\n${result.stderr}`,
    );
  }
}

export async function bootstrapCompany(page: Page, company: CompanySeed): Promise<void> {
  await page.goto("/legacy");
  await waitForAppReady(page);
  const form = page.getByTestId("bootstrap-form");
  await form.scrollIntoViewIfNeeded();
  await form.getByLabel("Company name").fill(company.companyName);
  await form.getByLabel("Company slug").fill(company.companySlug);
  await form.getByLabel("Company type").selectOption(company.companyType);
  await form.getByLabel("Owner full name").fill(company.ownerFullName);
  await form.getByLabel("Owner email").fill(company.ownerEmail);
  await form.getByLabel("Owner password").fill(company.ownerPassword);
  await submitButton(form, "Create company").click();
  await expect(page.getByRole("button", { name: "Logout", exact: true })).toBeVisible();
  await expect(page.getByText(company.companySlug, { exact: true })).toBeVisible();
  const noticeBanner = page.getByTestId("notice-banner");
  if ((await noticeBanner.count()) > 0) {
    await expect(noticeBanner).toContainText("Company created and owner session started.");
  }
}

export async function login(
  page: Page,
  payload: { email: string; password: string; companySlug: string },
): Promise<void> {
  await waitForAppReady(page);
  const form = page.getByTestId("login-form");
  await form.scrollIntoViewIfNeeded();
  await form.getByLabel("Email").fill(payload.email);
  await form.getByLabel("Password").fill(payload.password);
  await form.getByLabel("Company slug").fill(payload.companySlug);
  await submitButton(form, "Login").click();
  await expect(page.getByRole("button", { name: "Logout", exact: true })).toBeVisible();
  const noticeBanner = page.getByTestId("notice-banner");
  if ((await noticeBanner.count()) > 0) {
    await expect(noticeBanner).toContainText("Logged in successfully.");
  }
}

export async function logout(page: Page): Promise<void> {
  await waitForAppReady(page);
  await page.getByRole("button", { name: "Logout", exact: true }).click();
  await expect(page.getByRole("heading", { name: "No active session" })).toBeVisible();
  const noticeBanner = page.getByTestId("notice-banner");
  if ((await noticeBanner.count()) > 0) {
    await expect(noticeBanner).toContainText("Session cleared.");
  }
}

export async function updateCompanyProfile(
  page: Page,
  payload: {
    name: string;
    primaryContactEmail: string;
    billingContactName: string;
    billingContactEmail: string;
    headquarters: string;
    timezone: string;
    websiteUrl: string;
    practiceSummary: string;
  },
): Promise<void> {
  const form = page.getByTestId("company-profile-form");
  await form.scrollIntoViewIfNeeded();
  await form.getByLabel("Company name").fill(payload.name);
  await form.getByLabel("Primary contact email").fill(payload.primaryContactEmail);
  await form.getByLabel("Billing contact name").fill(payload.billingContactName);
  await form.getByLabel("Billing contact email").fill(payload.billingContactEmail);
  await form.getByLabel("Headquarters").fill(payload.headquarters);
  await form.getByLabel("Timezone").fill(payload.timezone);
  await form.getByLabel("Website URL").fill(payload.websiteUrl);
  await form.getByLabel("Practice summary").fill(payload.practiceSummary);
  await submitButton(form, "Save company profile").click();
  await expect(page.getByTestId("notice-banner")).toContainText("Company profile updated.");
}

export async function createCompanyUser(page: Page, user: UserSeed): Promise<void> {
  const form = page.getByTestId("create-user-form");
  await form.scrollIntoViewIfNeeded();
  await form.getByLabel("Full name").fill(user.fullName);
  await form.getByLabel("Email").fill(user.email);
  await form.getByLabel("Password").fill(user.password);
  await form.getByLabel("Role").selectOption(user.role);
  await submitButton(form, "Add company user").click();
  await expect(page.getByTestId("notice-banner")).toContainText("Company user created.");
  await expect(page.getByText(user.fullName, { exact: true })).toBeVisible();
  await expect(page.getByText(user.email, { exact: true })).toBeVisible();
}

export async function createMatter(page: Page, matter: MatterSeed): Promise<void> {
  const form = page.getByTestId("create-matter-form");
  await form.scrollIntoViewIfNeeded();
  await form.getByLabel("Matter title").fill(matter.title);
  await form.getByLabel("Matter code").fill(matter.matterCode);
  await form.getByLabel("Client name").fill(matter.clientName);
  await form.getByLabel("Opposing party").fill(matter.opposingParty);
  await form.getByLabel("Status").selectOption("active");
  await form.getByLabel("Practice area").fill(matter.practiceArea);
  await form.getByLabel("Forum level").selectOption(matter.forumLevel);
  await form.getByLabel("Court name").fill(matter.courtName);
  await form.getByLabel("Judge name").fill(matter.judgeName);
  await form.getByLabel("Next hearing date").fill(matter.nextHearingOn);
  await form.getByLabel("Description").fill(matter.description);
  await submitButton(form, "Create matter").click();
  await expect(page.getByTestId("notice-banner")).toContainText("Matter created.");
  await expect(page.getByTestId(`open-matter-${matter.matterCode}`)).toBeVisible();
}

export async function openMatter(page: Page, matterCode: string): Promise<void> {
  await waitForAppReady(page);
  await page.getByTestId(`open-matter-${matterCode}`).click();
  await expect(page.getByTestId("matter-workspace-form")).toBeVisible();
}

export async function createContract(page: Page, contract: ContractSeed): Promise<void> {
  const form = page.getByTestId("create-contract-form");
  await form.scrollIntoViewIfNeeded();
  await form.getByLabel("Contract title").fill(contract.title);
  await form.getByLabel("Contract code").fill(contract.contractCode);
  await form.getByLabel("Contract type").fill(contract.contractType);
  await form.getByLabel("Counterparty").fill(contract.counterpartyName);
  await form.getByLabel("Status").selectOption(contract.status);
  await form.getByLabel("Jurisdiction").fill(contract.jurisdiction);
  await form.getByLabel("Effective date").fill(contract.effectiveOn);
  await form.getByLabel("Expiry date").fill(contract.expiresOn);
  await form.getByLabel("Renewal date").fill(contract.renewalOn);
  await form.getByLabel("Total value").fill(contract.totalValue);
  await form.getByLabel("Currency").fill(contract.currency);
  await form.getByLabel("Summary").fill(contract.summary);
  await submitButton(form, "Create contract").click();
  await expect(page.getByTestId("notice-banner")).toContainText("Contract created.");
  await expect(page.getByTestId(`open-contract-${contract.contractCode}`)).toBeVisible();
}

export async function openContract(page: Page, contractCode: string): Promise<void> {
  await waitForAppReady(page);
  await page.getByTestId(`open-contract-${contractCode}`).click();
  await expect(page.getByTestId("contract-workspace-form")).toBeVisible();
}
