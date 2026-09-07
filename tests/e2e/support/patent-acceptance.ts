import { randomUUID } from "node:crypto";
import { expect, type APIRequestContext, type Page, type TestInfo } from "@playwright/test";
import { apiBaseUrl as localApiBaseUrl } from "./env";
import { noPaidProviderHeaders } from "./cost-controls";
import {
  bootstrapIntelligentReviewTenant,
  enableIntelligentReviewIpWorkspace,
  signInIntelligentReviewTenant,
} from "./iplf063b";

export const existingPatentQa = Boolean(process.env.PROD_API_BASE_URL);
const existingQa = existingPatentQa;
export const apiBaseUrl = process.env.PROD_API_BASE_URL || localApiBaseUrl;
export const patentRunId = () => randomUUID().replaceAll("-", "").slice(0, 12);

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for existing patent QA acceptance.`);
  return value;
}

export async function assertPatentRelease(api: APIRequestContext) {
  if (!existingQa) return;
  const expected = required("CASEOPS_EXPECTED_RELEASE_SHA");
  expect(expected).toMatch(/^[0-9a-f]{40}$/);
  for (const url of [
    `${apiBaseUrl}/api/build`,
    `${required("PROD_BASE_URL")}/api/release-identity`,
  ]) {
    const response = await api.get(url, { headers: noPaidProviderHeaders });
    expect(response.status()).toBe(200);
    expect((await response.json()).release_sha).toBe(expected);
  }
}

async function existingSession(api: APIRequestContext, other: boolean) {
  // These two dedicated tenants already have governed billing and IP setup.
  // Production acceptance must never bootstrap or rewrite that configuration.
  const slug = other ? "caseops-qa" : "caseops-ip-qa";
  const email = other
    ? process.env.CASEOPS_QA_EMAIL || "qa-bot@caseops.ai"
    : process.env.CASEOPS_IP_QA_EMAIL || "ip-qa-bot@caseops.ai";
  const response = await api.post(`${apiBaseUrl}/api/auth/login`, {
    headers: noPaidProviderHeaders,
    data: { company_slug: slug, email,
      password: required(other ? "CASEOPS_QA_PASSWORD" : "CASEOPS_IP_QA_PASSWORD") },
  });
  expect(response.status(), "Dedicated patent QA authentication").toBe(200);
  const session = await response.json();
  expect(session.company.slug).toBe(slug);
  return { ...session, slug, email };
}

export async function bootstrapPatentTenant(api: APIRequestContext, other = false) {
  if (!existingQa) return bootstrapIntelligentReviewTenant(api);
  await assertPatentRelease(api);
  return existingSession(api, other);
}

export async function enablePatentWorkspace(
  api: APIRequestContext,
  tenant: { access_token: string; membership: { id: string } },
) {
  if (!existingQa) return enableIntelligentReviewIpWorkspace(api, tenant);
  const headers = { ...noPaidProviderHeaders, Authorization: `Bearer ${tenant.access_token}` };
  const response = await api.get(`${apiBaseUrl}/api/ip/workspace/configuration`, { headers });
  expect(response.status(), "Existing governed IP configuration").toBe(200);
  const state = await response.json();
  expect(state.configuration?.workspace_enabled).toBe(true);
  expect(state.ready_for_manual_docketing).toBe(true);
  return headers;
}

export async function signInPatentTenant(page: Page, tenant: { slug: string; email: string }) {
  if (!existingQa) return signInIntelligentReviewTenant(page, tenant);
  expect(["caseops-ip-qa", "caseops-qa"]).toContain(tenant.slug);
  const session = await existingSession(page.request, tenant.slug === "caseops-qa");
  expect(session.company.slug).toBe(tenant.slug);
  await page.goto(`${required("PROD_BASE_URL")}/`);
  await page.evaluate((context) => {
    window.localStorage.setItem("caseops.session.context", JSON.stringify(context));
  }, { company: session.company, user: session.user,
    membership: session.membership, capabilities: session.capabilities });
  return session;
}

export async function patentScreenshot(page: Page, info: TestInfo, name: string) {
  // A shared production QA page may contain retained authenticated records.
  // Keep local visual proof, but do not persist production browser media.
  if (!existingQa || ["localhost", "127.0.0.1"].includes(new URL(apiBaseUrl).hostname)) {
    await page.screenshot({ path: info.outputPath(name), fullPage: true });
  }
}
