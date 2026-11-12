/** BUG-003 partial candidate and B5-013/014 test-only draft, one exact release.
 * Preview and marked 409 rejection are not delivery acceptance. Default-template
 * selection and full reusable-template editing remain open in workbook row 003.
 * Reuse the tester's auth helpers, never prepareTester's unrelated IP setup.
 */
import { randomUUID } from "node:crypto";
import { expect, test, type APIRequestContext } from "@playwright/test";

import { authContext, authSession, type AuthContext, type AuthSession } from "../../apps/web/lib/api/schemas";
import type { AuthoritySearchMode, TenantAIPolicy, searchAuthorities } from "../../apps/web/lib/api/endpoints";
import type { AssistantAskResponse, AssistantScopeOption, AssistantSessionRecord } from "../../apps/web/lib/api/workspace-assistant";
import { localTransportHeaders } from "./support/cost-controls";
import { e2eEnv } from "./support/env";
import { assertPublicReleaseIdentity } from "./support/public-release-identity";
import { json, signIn, type TesterCredentials } from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

const loopback = (url: URL) => ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required; missing reporter setup is not a passing skip.`);
  return value;
}

function sessionFrom(value: unknown, credentials: TesterCredentials): AuthSession {
  const parsed = authSession.safeParse(value);
  if (!parsed.success) throw new Error("Reporter login did not match the canonical auth contract.");
  const actor = parsed.data;
  expect(actor.company.slug === credentials.slug && actor.user.email.toLowerCase() === credentials.email.toLowerCase(), "Authenticated reporter identity").toBe(true);
  expect(uuid.test(actor.company.id) && uuid.test(actor.user.id) && uuid.test(actor.membership.id), "Server-issued reporter identities").toBe(true);
  expect(actor.company.is_active && actor.user.is_active && actor.membership.is_active && actor.membership.role === "owner", "Existing active workspace owner").toBe(true);
  expect(!actor.mfa_challenge_required && !actor.mfa_enrollment_required, "Reporter authentication must complete without bypassing MFA").toBe(true);
  expect(["communications:write", "email_templates:manage"].every((cap) => actor.capabilities?.includes(cap)), "Communications and template capabilities").toBe(true);
  return actor;
}

function sameActor(value: unknown, actor: AuthSession): AuthContext {
  const parsed = authContext.safeParse(value);
  if (!parsed.success) throw new Error("Reporter self-auth did not match the canonical auth contract.");
  const current = parsed.data;
  expect(current.company.id === actor.company.id && current.company.slug === actor.company.slug
    && current.membership.id === actor.membership.id && current.user.id === actor.user.id
    && current.user.email === actor.user.email && current.membership.role === "owner"
    && current.company.is_active && current.user.is_active && current.membership.is_active,
  "Effective principal remains the authenticated reporter").toBe(true);
  expect(["communications:write", "email_templates:manage"].every((cap) => current.capabilities?.includes(cap)), "Reporter retains communications authority").toBe(true);
  return current;
}

type CreatedMatter = { id: string; matter_code: string; status: string; updated_at: string; next_hearing_on: string | null };
type CreatedTemplate = { id: string; company_id: string; name: string; created_by_membership_id: string; is_active: boolean };

type ResearchMatter = CreatedMatter & { company_id: string; title: string; practice_area: string };
type ResearchResponse = Awaited<ReturnType<typeof searchAuthorities>>;

for (const phone of [false, true]) {
  test(`${phone ? "[mobile] " : ""}BUG-003 communications resolved preview and missing-value guard ${phone ? "phone" : "desktop"}`, {
    annotation: { type: "caseops-b5-proof", description: "preview-no-paid-guard" },
  }, async ({ page, request, baseURL }) => {
    const web = new URL(baseURL ?? required("CASEOPS_WEB_BASE_URL"));
    const local = loopback(web);
    const api = new URL(local
      ? `http://${web.hostname}:${process.env.CASEOPS_E2E_API_PORT ?? "8000"}`
      : required("PROD_API_BASE_URL"));
    if (![web, api].every((url) => ["http:", "https:"].includes(url.protocol)
      && !url.username && !url.password && !url.search && !url.hash && url.pathname === "/")
      || local !== loopback(api)
      || (!local && (web.origin !== "https://caseops.ai" || api.origin !== "https://api.caseops.ai"))) {
      throw new Error("Communications acceptance requires the loopback or canonical production origin pair.");
    }
    const sha = local ? (process.env.CASEOPS_RELEASE_SHA?.trim() || e2eEnv.CASEOPS_RELEASE_SHA)
      : required("CASEOPS_EXPECTED_RELEASE_SHA");
    const release = () => assertPublicReleaseIdentity([`${api.origin}/api/build`, `${web.origin}/api/release-identity`], sha);
    await release();
    const nonce = randomUUID();
    const credentials: TesterCredentials = local
      ? { slug: `comms-${nonce}`, email: `owner-${nonce}@example.com`, password: `Offline!${randomUUID()}` }
      : { slug: process.env.CASEOPS_RAM_PROD_SLUG?.trim() || "test-legal", email: required("CASEOPS_RAM_PROD_EMAIL"), password: required("CASEOPS_RAM_PROD_PASSWORD") };
    if (!local && credentials.slug !== "test-legal") throw new Error("Production communications acceptance is authorized test-legal only.");
    const transport = localTransportHeaders(api.origin);
    if (local) {
      await release();
      await json(await request.post(`${api.origin}/api/bootstrap/company`, { headers: transport, maxRetries: 0, maxRedirects: 0, data: {
        company_name: "Communications QA", company_slug: credentials.slug, company_type: "law_firm",
        owner_full_name: "Communications QA", owner_email: credentials.email, owner_password: credentials.password,
      } }), "Loopback-only communications owner bootstrap");
    }
    const actor = sessionFrom(await json(await request.post(`${api.origin}/api/auth/login`, {
      headers: transport, maxRetries: 0, maxRedirects: 0,
      data: { company_slug: credentials.slug, email: credentials.email, password: credentials.password },
    }), "Reporter API authentication"), credentials);
    const headers = { ...transport, Authorization: `Bearer ${actor.access_token}` };
    const selfAuth = async (client: APIRequestContext, authHeaders: Record<string, string>) => sameActor(
      await json(await client.get(`${api.origin}/api/auth/me`, { headers: authHeaders, maxRetries: 0, maxRedirects: 0 }), "Reporter self-auth"), actor,
    );
    await selfAuth(request, headers);
    await page.setViewportSize(phone ? { width: 393, height: 851 } : { width: 1365, height: 900 });
    await page.route((url) => url.pathname.endsWith("/communications/send-email"), async (route) => {
      const outgoing = route.request();
      if (new URL(outgoing.url()).origin !== api.origin || outgoing.method() !== "POST"
        || outgoing.headers()["x-caseops-automated-test"] !== "no-paid-providers") {
        await route.abort("blockedbyclient");
        throw new Error("Unmarked or wrong-origin email delivery request blocked before transport.");
      }
      await route.continue();
    });
    const responseFor = (pathname: string, method = "POST") => page.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.origin === api.origin && url.pathname === pathname && response.request().method() === method;
    });
    const [browserLogin] = await Promise.all([responseFor("/api/auth/login"), signIn(page, { web }, credentials)]);
    const browserActor = sessionFrom(await json(browserLogin, "Reporter browser authentication"), credentials);
    sameActor(browserActor, actor);
    await selfAuth(page.request, transport);
    await release();

    const templateName = `BUG-003 QA ${nonce}`;
    const matterCode = `COMMS-${nonce.replaceAll("-", "").toUpperCase()}`;
    let templateId: string | undefined;
    let matterId: string | undefined;
    try {
      await page.goto(`${web.origin}/app/admin/email-templates`);
      await page.getByTestId("email-template-new-toggle").click();
      await page.getByTestId("email-template-name").fill(templateName);
      await page.getByTestId("email-template-subject").fill("Status update on your matter {{client_name}}");
      await page.getByTestId("email-template-body").fill("Hi {{client_name}}, the next hearing is on {{hearing_date}}.");
      await release();
      const templateSaved = responseFor("/api/admin/email-templates");
      await page.getByTestId("email-template-submit").click();
      const template = await json<CreatedTemplate>(await templateSaved, "UI-created synthetic template");
      templateId = template.id;
      expect(uuid.test(template.id) && template.name === templateName && template.company_id === actor.company.id
        && template.created_by_membership_id === actor.membership.id, "Only this reporter's uniquely named synthetic template").toBe(true);
      await release();

      await page.goto(`${web.origin}/app/matters`);
      await page.getByTestId("new-matter-trigger").first().click();
      const dialog = page.getByRole("dialog", { name: "New matter" });
      await dialog.getByLabel("Title", { exact: true }).fill(`Communications QA ${nonce}`);
      await dialog.getByLabel("Matter code", { exact: true }).fill(matterCode);
      await dialog.getByLabel("Practice area", { exact: true }).fill("Civil");
      await dialog.getByLabel("Client name", { exact: true }).fill("QA Client");
      await release();
      const matterSaved = responseFor("/api/matters/");
      await dialog.getByRole("button", { name: "Create matter", exact: true }).click();
      const matter = await json<CreatedMatter>(await matterSaved, "UI-created synthetic matter");
      matterId = matter.id;
      expect(uuid.test(matter.id) && matter.matter_code === matterCode && matter.next_hearing_on === null, "Fresh synthetic matter without an invented hearing date").toBe(true);
      await release();

      const communicationsPath = `/api/matters/${matterId}/communications`;
      await page.goto(`${web.origin}/app/matters/${matterId}/communications`);
      await page.getByTestId("comm-send-toggle").click();
      const compose = page.getByRole("region", { name: "Compose email" });
      await compose.getByTestId("comm-send-template").selectOption(templateId);
      await compose.getByLabel("Recipient email", { exact: true }).fill("no-delivery@example.com");
      await expect(compose.getByTestId("comm-send-submit")).toBeDisabled();
      async function preview() {
        await release();
        const rendered = responseFor(`${communicationsPath}/preview-email`);
        await compose.getByTestId("comm-send-preview").click();
        const response = await rendered;
        expect(response.request().headers()["x-caseops-automated-test"], "Preview keeps the no-paid marker").toBe("no-paid-providers");
        return json<{ subject: string; body: string; missing_variables: string[]; invalid_placeholders: string[]; preview_token: string | null }>(response, "Matter-scoped preview from the expected API");
      }
      const missing = await preview();
      expect(missing.missing_variables).toEqual(["hearing_date"]);
      expect(missing.preview_token).toBeNull();
      await expect(compose.getByRole("alert")).toContainText("hearing_date");
      await expect(compose.getByTestId("comm-send-preview-result")).toContainText("Hi QA Client");
      await expect(compose.getByTestId("comm-send-submit")).toBeDisabled();

      // Preserve the exact syntax of the retained production communication.
      await compose.getByLabel("Subject", { exact: true }).fill("Status update on your matter {[client_name]}");
      await compose.getByRole("textbox", { name: "Message", exact: true }).fill("Hi {[client_name]}, the next hearing is on {[hearing_date]}.");
      await expect(compose.getByRole("alert")).toContainText("Unsupported placeholders");
      await expect(compose.getByTestId("comm-send-preview")).toBeDisabled();
      await expect(compose.getByTestId("comm-send-submit")).toBeDisabled();

      await compose.getByTestId("comm-send-template").selectOption("");
      await compose.getByLabel("Subject", { exact: true }).fill("Reviewed update");
      await compose.getByRole("textbox", { name: "Message", exact: true }).fill("Hi {{client_name}}, no hearing date is confirmed.");
      const manual = await preview();
      expect(manual.body).toBe("Hi QA Client, no hearing date is confirmed.");
      expect(manual.missing_variables).toEqual([]);
      expect(manual.invalid_placeholders).toEqual([]);
      expect(manual.preview_token).toBeTruthy();
      await expect(compose.getByTestId("comm-send-preview-result")).toContainText(manual.body);
      await expect(compose.getByTestId("comm-send-submit")).toBeEnabled();
      await compose.getByLabel("Subject", { exact: true }).fill("Reviewed manual update");
      await expect(compose.getByTestId("comm-send-submit")).toBeDisabled();
      await preview();
      await expect(compose.getByTestId("comm-send-submit")).toBeEnabled();
      await compose.getByLabel("Recipient email", { exact: true }).fill("changed-recipient@example.com");
      await compose.getByLabel("Recipient email", { exact: true }).fill("no-delivery@example.com");
      await expect(compose.getByTestId("comm-send-submit")).toBeDisabled();
      await preview();
      // Another authorized writer changes this run's source after review.
      const beforeChange = await json<CreatedMatter>(await request.get(`${api.origin}/api/matters/${matterId}`, {
        headers, maxRetries: 0, maxRedirects: 0,
      }), "Read this execution's source version");
      expect(beforeChange.matter_code === matterCode, "Source change owns the synthetic matter").toBe(true);
      await release();
      await json(await request.patch(`${api.origin}/api/matters/${matterId}`, {
        headers, maxRetries: 0, maxRedirects: 0,
        data: { client_name: "Updated QA Client", expected_updated_at: beforeChange.updated_at },
      }), "Change only this execution's source after preview");
      await release();
      const stale = responseFor(`${communicationsPath}/send-email`);
      await compose.getByTestId("comm-send-submit").click();
      const staleResponse = await stale;
      expect(staleResponse.request().headers()["x-caseops-automated-test"]).toBe("no-paid-providers");
      const staleProblem = await json<{ detail: string }>(staleResponse, "Changed source requires a new preview", 409);
      expect(staleProblem.detail).toContain("Email preview expired or changed");
      await expect(page.getByText(staleProblem.detail, { exact: true })).toBeVisible();
      const updated = await preview();
      expect(updated.body).toBe("Hi Updated QA Client, no hearing date is confirmed.");
      expect(updated.preview_token).toBeTruthy();
      await expect(compose.getByTestId("comm-send-preview-result")).toContainText(updated.body);
      await release();
      const refused = responseFor(`${communicationsPath}/send-email`);
      await compose.getByTestId("comm-send-submit").click();
      const refusal = await refused;
      expect(refusal.request().headers()["x-caseops-automated-test"], "Delivery rejection must retain the authoritative marker").toBe("no-paid-providers");
      const rejected = await json<{ detail: string }>(refusal, "Marked send is rejected without delivery", 409);
      expect(rejected.detail).toBe("Email delivery is disabled during automated verification. No email was sent.");
      await expect(page.getByText(rejected.detail, { exact: true })).toBeVisible();
      const rows = await json<{ communications: unknown[] }>(await request.get(`${api.origin}${communicationsPath}`, {
        headers, maxRetries: 0, maxRedirects: 0,
      }), "No communication created by the rejected send");
      expect(rows.communications).toEqual([]);

      for (const id of ["comm-send-template", "comm-send-recipient-email", "comm-send-subject", "comm-send-body", "comm-send-preview", "comm-send-submit"]) {
        const control = compose.getByTestId(id);
        await control.scrollIntoViewIfNeeded();
        const rect = await control.boundingBox();
        expect(rect).toBeTruthy();
        expect(rect!.width).toBeGreaterThan(40);
        expect(rect!.x).toBeGreaterThanOrEqual(0);
        expect(rect!.x + rect!.width).toBeLessThanOrEqual(phone ? 394 : 1366);
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
      await page.reload();
      await expect(page.getByText("No communications yet", { exact: true })).toBeVisible();
      await selfAuth(request, headers);
      await selfAuth(page.request, transport);
      await release();
    } finally {
      // Never alter reported records or a fixture retained by another run.
      await release();
      await selfAuth(request, headers);
      if (templateId) {
        const owned = await json<CreatedTemplate>(await request.get(`${api.origin}/api/admin/email-templates/${templateId}`, {
          headers, maxRetries: 0, maxRedirects: 0,
        }), "Read only this execution's template before cleanup");
        expect(owned.name === templateName && owned.company_id === actor.company.id
          && owned.created_by_membership_id === actor.membership.id, "Cleanup owns the synthetic template").toBe(true);
        await release();
        const archived = await json<CreatedTemplate>(await request.delete(`${api.origin}/api/admin/email-templates/${templateId}`, {
          headers, maxRetries: 0, maxRedirects: 0,
        }), "Archive only this execution's template");
        expect(archived.is_active).toBe(false);
      }
      if (matterId) {
        const current = await json<CreatedMatter>(await request.get(`${api.origin}/api/matters/${matterId}`, {
          headers, maxRetries: 0, maxRedirects: 0,
        }), "Read only this execution's matter before cleanup");
        expect(current.id === matterId && current.matter_code === matterCode, "Cleanup owns the synthetic matter").toBe(true);
        if (current.status !== "disposed") {
          await release();
          await json(await request.patch(`${api.origin}/api/matters/${matterId}/lifecycle/status`, { headers, maxRetries: 0, maxRedirects: 0,
            data: { to_status: "disposed", expected_from_status: current.status, expected_updated_at: current.updated_at,
              reason: "BUG-003 synthetic acceptance fixture cleanup; no email dispatched" },
          }), "Dispose only this execution's matter");
        }
        const disposed = await json<CreatedMatter>(await request.get(`${api.origin}/api/matters/${matterId}`, {
          headers, maxRetries: 0, maxRedirects: 0,
        }), "Synthetic matter cleanup persisted");
        expect(disposed.status).toBe("disposed");
      }
      await release();
    }
  });
}

for (const phone of [false, true]) {
  test(`${phone ? "[mobile] " : ""}B5-013/014 assistant factual citation, legal abstention and research mode navigation ${phone ? "phone" : "desktop"}`, {
    annotation: { type: "caseops-b5-proof", description: "assistant-research-no-paid-guard" },
  }, async ({ page, request, baseURL }) => {
    const web = new URL(baseURL ?? required("CASEOPS_WEB_BASE_URL"));
    const local = loopback(web);
    const api = new URL(local
      ? `http://${web.hostname}:${process.env.CASEOPS_E2E_API_PORT ?? "8000"}`
      : required("PROD_API_BASE_URL"));
    if (![web, api].every(url => ["http:", "https:"].includes(url.protocol)
      && !url.username && !url.password && !url.search && !url.hash && url.pathname === "/")
      || local !== loopback(api)
      || (local && [web, api].some(url => url.protocol !== "http:"))
      || (!local && (web.origin !== "https://caseops.ai" || api.origin !== "https://api.caseops.ai"))) {
      throw new Error("Assistant/research acceptance requires the loopback or canonical production origin pair.");
    }
    const sha = local ? (process.env.CASEOPS_RELEASE_SHA?.trim() || e2eEnv.CASEOPS_RELEASE_SHA)
      : required("CASEOPS_EXPECTED_RELEASE_SHA");
    expect(sha).toMatch(/^[a-f0-9]{40}$/);
    const release = () => assertPublicReleaseIdentity([`${api.origin}/api/build`, `${web.origin}/api/release-identity`], sha);
    await release();
    const nonce = randomUUID();
    const credentials: TesterCredentials = local
      ? { slug: `research-${nonce}`, email: `owner-${nonce}@example.com`, password: `Offline!${randomUUID()}` }
      : { slug: process.env.CASEOPS_RAM_PROD_SLUG?.trim() || "test-legal", email: required("CASEOPS_RAM_PROD_EMAIL"), password: required("CASEOPS_RAM_PROD_PASSWORD") };
    if (!local && credentials.slug !== "test-legal") throw new Error("Production assistant/research acceptance is existing test-legal only.");
    const transport = localTransportHeaders(api.origin);
    if (local) {
      await release();
      await json(await request.post(`${api.origin}/api/bootstrap/company`, { headers: transport, maxRetries: 0, maxRedirects: 0, data: {
        company_name: "Synthetic assistant research QA", company_slug: credentials.slug, company_type: "law_firm",
        owner_full_name: "Assistant research QA", owner_email: credentials.email, owner_password: credentials.password,
      } }), "Loopback-only assistant/research owner bootstrap");
    }
    // Reuse canonical owner/MFA/tenant validation, not prepareTester's IP grants.
    const actor = sessionFrom(await json(await request.post(`${api.origin}/api/auth/login`, {
      headers: transport, maxRetries: 0, maxRedirects: 0,
      data: { company_slug: credentials.slug, email: credentials.email, password: credentials.password },
    }), "Assistant/research reporter API authentication"), credentials);
    const headers = { ...transport, Authorization: `Bearer ${actor.access_token}` };
    const selfAuth = async (client: APIRequestContext, authHeaders: Record<string, string>) => {
      const current = sameActor(await json(await client.get(`${api.origin}/api/auth/me`, {
        headers: authHeaders, maxRetries: 0, maxRedirects: 0,
      }), "Assistant/research reporter self-auth"), actor);
      expect(["ai:generate", "authorities:search", "matters:write"].every(cap => current.capabilities?.includes(cap)),
        "Reporter retains assistant, research and owned-Matter authority").toBe(true);
      return current;
    };
    await selfAuth(request, headers);
    await page.setViewportSize(phone ? { width: 393, height: 851 } : { width: 1365, height: 900 });
    let guardedRequests = 0;
    // A transport-only fence: every answer below comes from the real API/UI.
    await page.route("**/api/**", async route => {
      const outgoing = route.request();
      const url = new URL(outgoing.url());
      const preflight = outgoing.method() === "OPTIONS" && outgoing.headers()["access-control-request-headers"]
        ?.split(",").some(header => header.trim().toLowerCase() === "x-caseops-automated-test");
      if (![api.origin, web.origin].includes(url.origin)
        || (!preflight && outgoing.headers()["x-caseops-automated-test"] !== "no-paid-providers")
        || /^\/api\/(?:authorities|case-tracking)\/providers\//.test(url.pathname)
        || url.pathname.endsWith("/communications/send-email")) {
        await route.abort("blockedbyclient");
        throw new Error("Unmarked, wrong-origin or external-provider browser API request blocked before transport.");
      }
      guardedRequests += 1;
      await route.continue();
    });
    const responseFor = (pathname: string, method = "POST") => page.waitForResponse(response => {
      const url = new URL(response.url());
      return url.origin === api.origin && url.pathname === pathname && response.request().method() === method;
    });
    const [browserLogin] = await Promise.all([responseFor("/api/auth/login"), signIn(page, { web }, credentials)]);
    sameActor(sessionFrom(await json(browserLogin, "Assistant/research reporter browser authentication"), credentials), actor);
    await selfAuth(page.request, transport);

    const policy = await json<TenantAIPolicy>(await request.get(`${api.origin}/api/admin/tenant-ai-policy`, {
      headers, maxRetries: 0, maxRedirects: 0,
    }), "Read existing assistant policy without production rewrites");
    expect(policy.company_id).toBe(actor.company.id);
    if (local) {
      await release();
      const enabled = await json<TenantAIPolicy>(await request.patch(`${api.origin}/api/admin/tenant-ai-policy`, {
        headers, maxRetries: 0, maxRedirects: 0, data: { expected_version: policy.policy_version,
          workspace_assistant_enabled: true, allowed_models_assistant: ["caseops-mock-1"],
          assistant_retention_days: policy.assistant_retention_days },
      }), "Enable only this execution's fresh loopback assistant tenant");
      expect(enabled.company_id === actor.company.id && enabled.workspace_assistant_enabled).toBe(true);
    } else {
      expect(policy.workspace_assistant_enabled, "Production policy must already permit this required workflow; never rewrite it or skip").toBe(true);
    }

    const title = `B5 assistant factual QA ${nonce}`;
    const matterCode = `B5RESEARCH-${nonce.replaceAll("-", "").toUpperCase()}`;
    let ownedMatter: ResearchMatter | undefined;
    let ownedConversation: Pick<AssistantSessionRecord, "id" | "title"> & {
      matterId: string; sourceVersion: string; companyId: string; membershipId: string; userId: string;
    } | undefined;
    try {
      await page.goto(`${web.origin}/app/matters`);
      await page.getByTestId("new-matter-trigger").first().click();
      const dialog = page.getByRole("dialog", { name: "New matter" });
      await dialog.getByLabel("Title", { exact: true }).fill(title);
      await dialog.getByLabel("Matter code", { exact: true }).fill(matterCode);
      await dialog.getByLabel("Practice area", { exact: true }).fill("Civil");
      await release();
      const researchCreated = responseFor("/api/matters/");
      await dialog.getByRole("button", { name: "Create matter", exact: true }).click();
      ownedMatter = await json<ResearchMatter>(await researchCreated, "UI-created factual-only research Matter");
      expect(uuid.test(ownedMatter.id) && ownedMatter.company_id === actor.company.id
        && ownedMatter.title === title && ownedMatter.matter_code === matterCode
        && ownedMatter.practice_area === "Civil" && ownedMatter.next_hearing_on === null).toBe(true);
      const matter = ownedMatter;
      const references = await json<{ references: unknown[] }>(await request.get(
        `${api.origin}/api/matters/${matter.id}/statute-references`, { headers, maxRetries: 0, maxRedirects: 0 },
      ), "Fresh Matter has no attached legal provisions");
      expect(references.references).toEqual([]);

      await page.goto(`${web.origin}/app/assistant`);
      await expect(page.getByRole("heading", { name: "Ask this Workspace", exact: true })).toBeVisible();
      await page.getByRole("textbox", { name: "Find workspace records", exact: true }).fill(matterCode);
      const searchingScope = responseFor("/api/workspace-assistant/scope-options", "GET");
      await page.getByRole("button", { name: "Find permitted records", exact: true }).click();
      const scopeResponse = await searchingScope;
      expect(new URL(scopeResponse.url()).searchParams.get("q")).toBe(matterCode);
      const options = await json<{ items: AssistantScopeOption[]; truncated: boolean }>(scopeResponse, "Real permitted Matter scope discovery");
      expect(options.truncated).toBe(false);
      const matches = options.items.filter(option => option.scope_type === "matter" && option.scope_id === matter.id);
      expect(matches).toHaveLength(1);
      const scope = matches[0];
      expect(scope.href).toBe(`/app/matters/${matter.id}`);
      expect(scope.resource_version).toBeTruthy();
      await page.getByRole("button", { name: `Add ${scope.label}`, exact: true }).click();
      await expect(page.getByTestId("assistant-active-scope")).toContainText(scope.label);
      await release();
      const starting = responseFor("/api/workspace-assistant/sessions");
      await page.getByRole("button", { name: "Start conversation", exact: true }).click();
      const started = await starting;
      expect(started.request().postDataJSON().scopes).toHaveLength(1);
      expect(started.request().postDataJSON().scopes).toMatchObject([{ scope_type: "matter", scope_id: matter.id }]);
      let conversation = await json<AssistantSessionRecord>(started, "UI-created exact Matter-scoped conversation", 201);
      ownedConversation = { id: conversation.id, title: conversation.title, matterId: matter.id,
        sourceVersion: scope.resource_version, companyId: actor.company.id, membershipId: actor.membership.id, userId: actor.user.id };
      expect(uuid.test(conversation.id) && conversation.scope_state === "current").toBe(true);
      expect(conversation.title).toContain(matterCode);
      expect(conversation.title).toContain(title);
      const conversationId = conversation.id;
      expect(conversation.scopes).toMatchObject([{ scope_type: "matter", scope_id: matter.id, resource_version: scope.resource_version }]);
      expect(conversation.scopes).toHaveLength(1);

      async function ask(question: string) {
        await selfAuth(page.request, transport);
        await release();
        const version = conversation.version;
        await page.getByRole("textbox", { name: "Ask this workspace", exact: true }).fill(question);
        const answering = responseFor(`/api/workspace-assistant/sessions/${conversation.id}/ask`);
        await page.getByRole("button", { name: "Ask", exact: true }).click();
        const response = await answering;
        expect(response.request().postDataJSON()).toEqual({ expected_version: version, question });
        const answer = await json<AssistantAskResponse>(response, "Real marked assistant answer");
        expect(answer.session.id).toBe(conversation.id);
        expect(answer.session.version).toBeGreaterThan(version);
        expect(answer.session.scope_state).toBe("current");
        expect(answer.session.scopes).toMatchObject([{ scope_type: "matter", scope_id: matter.id, resource_version: scope.resource_version }]);
        expect(answer.session.scopes).toHaveLength(1);
        expect(answer.user_turn.content).toBe(question);
        expect(answer.assistant_turn.render_status).toBe("visible");
        conversation = answer.session;
        const article = page.locator(`[data-turn-id="${answer.assistant_turn.id}"][data-turn-role="assistant"]`);
        await expect(article).toBeVisible();
        await expect(article).toContainText(answer.assistant_turn.content);
        return { answer: answer.assistant_turn, article };
      }

      // This is a factual exclusion, not a request for legal propositions.
      const factual = await ask("What is the status and practice area of this matter without adding case law?");
      expect(factual.answer.status).toBe("completed");
      expect(factual.answer.model?.provider, "The authoritative marker must select the offline provider").toBe("mock");
      expect(factual.answer.content).toContain(`Status ${matter.status}`);
      expect(factual.answer.content).toContain(`Practice area ${matter.practice_area}`);
      expect(factual.answer.citations).toHaveLength(1);
      const citation = factual.answer.citations[0];
      expect(citation.source_type).toBe("matter");
      expect(citation.source_id).toBe(matter.id);
      expect(citation.source_version).toBe(scope.resource_version);
      expect(citation.source_sha256).toMatch(/^[a-f0-9]{64}$/);
      expect(citation.source_url).toBe(`/app/matters/${matter.id}`);
      expect(citation.verified_at).toBeTruthy();
      const source = factual.article.getByRole("button", { name: `Open source: ${citation.label}`, exact: true });
      await expect(source).toBeVisible();
      const opening = responseFor(`/api/workspace-assistant/sessions/${conversation.id}/citations/${citation.id}/open`);
      await source.click();
      expect(await json(await opening, "Audited exact Matter citation opening"))
        .toEqual({ citation_id: citation.id, source_url: `/app/matters/${matter.id}` });
      await expect(page).toHaveURL(new RegExp(`/app/matters/${matter.id}(?:[/?#]|$)`));
      await page.goto(`${web.origin}/app/assistant`);
      const savedVersion = conversation.version;
      const reopening = responseFor(`/api/workspace-assistant/sessions/${conversation.id}`, "GET");
      await page.getByRole("button", { name: conversation.title, exact: true }).click();
      conversation = await json<AssistantSessionRecord>(await reopening, "Reopen only this execution's conversation");
      expect(conversation.id).toBe(conversationId);
      expect(conversation.version).toBe(savedVersion);
      expect(conversation.scopes).toMatchObject([{ scope_type: "matter", scope_id: matter.id, resource_version: scope.resource_version }]);
      expect(conversation.scopes).toHaveLength(1);
      await expect(page.locator(`[data-turn-id="${factual.answer.id}"]`)).toContainText(factual.answer.content);

      const legalQuestion = "What are the applicable sections and Acts in this matter?";
      const legal = await ask(legalQuestion);
      expect(legal.answer.status, "Matter metadata alone cannot establish applicable law").toBe("abstained");
      expect(legal.answer.model).toBeNull();
      expect(legal.answer.content).toBe("I do not have enough permitted, verified evidence to answer that safely.");
      expect(legal.answer.citations).toEqual([]);
      expect(legal.answer.proposed_actions.every(action => action.action_type === "search" && !action.requires_confirmation)).toBe(true);
      const actions = legal.answer.proposed_actions.filter(action => action.action_type === "search");
      expect(actions).toHaveLength(1);
      const link = legal.article.getByRole("link", { name: "Search verified legal sources", exact: true });
      await expect(link).toBeVisible();
      expect(await link.getAttribute("href")).toBe(actions[0].href);
      const destination = new URL(actions[0].href!, web.origin);
      expect(destination.origin).toBe(web.origin);
      expect(destination.pathname).toBe("/app/research");
      expect(actions[0].href).toMatch(/^\/app\/research\?query=/);
      expect(destination.searchParams.get("query")).toBe(legalQuestion);
      expect(destination.searchParams.has("q")).toBe(false);

      async function researchSurface(result: ResearchResponse, query: string, mode: AuthoritySearchMode) {
        expect(result.query).toBe(query);
        expect(result.mode).toBe(mode);
        expect(result.provider).toMatch(/^caseops-authority-(?:contextual-search-v1|search-v2)$/);
        expect(result.results.length).toBeLessThanOrEqual(10);
        expect(result.offset).toBe(0);
        expect(result.total_after_filter).toBeGreaterThanOrEqual(result.results.length);
        await expect(page.getByTestId("research-source-caseops-corpus")).toHaveAttribute("aria-pressed", "true");
        await expect(page.getByTestId(`research-mode-${mode.replace("_", "-")}`)).toHaveAttribute("aria-pressed", "true");
        await expect(page.getByRole("textbox", { name: "Research query", exact: true })).toHaveValue(query);
        await expect(page.getByTestId("research-query-submit")).toBeEnabled();
        const coverage = page.getByTestId("research-corpus-coverage");
        await expect(coverage).toContainText(result.corpus_coverage.scope_summary);
        await expect(coverage).toContainText(`index ${result.corpus_coverage.index_state}`);
        expect(result.corpus_coverage.document_count).toBeGreaterThanOrEqual(0);
        expect(["current", "stale", "unavailable"]).toContain(result.corpus_coverage.index_state);
        if (result.outcome === "results_found") {
          expect(result.results.length).toBeGreaterThan(0);
          const titles = page.getByTestId("research-results").getByRole("heading", { level: 3 });
          await expect(titles.first()).toBeVisible();
          const shown = await titles.allTextContents();
          expect(shown.length).toBeGreaterThan(0);
          expect(shown.every(title => result.results.some(record => record.title === title))).toBe(true);
        } else {
          const emptyTitles = { no_matching_documents: "No matching documents", corpus_unavailable: "Corpus unavailable",
            index_stale: "Index stale", unreadable_filtered: "Matching documents are unreadable" };
          expect(Object.keys(emptyTitles), "Only an explicit honest corpus/index outcome can replace results").toContain(result.outcome);
          expect(result.results).toEqual([]);
          if (result.outcome === "no_matching_documents") expect(result.corpus_coverage.index_state).toBe("current");
          if (result.outcome === "index_stale") expect(result.corpus_coverage.index_state).toBe("stale");
          if (result.outcome === "corpus_unavailable") expect(result.corpus_coverage.document_count).toBe(0);
          await expect(page.getByRole("heading", { name: emptyTitles[result.outcome as keyof typeof emptyTitles], exact: true })).toBeVisible();
          await expect(page.getByTestId("research-results")).toHaveCount(0);
          if (result.coverage_notice) await expect(page.getByText(result.coverage_notice, { exact: true })).toBeVisible();
        }
        return result;
      }

      async function researchResult(response: Awaited<ReturnType<typeof responseFor>>, query: string, mode: AuthoritySearchMode) {
        expect(response.request().postDataJSON()).toEqual({ query, mode, limit: 10, offset: 0, language: "en",
          forum_level: null, court_name: null, document_type: null });
        const result = await json<ResearchResponse>(response, `Real ${mode} corpus search; not a retrieval-quality claim`);
        return researchSurface(result, query, mode);
      }

      const following = responseFor("/api/authorities/search");
      await link.click();
      await expect(page.getByRole("heading", { name: "Grounded legal research", exact: true })).toBeVisible();
      await researchResult(await following, legalQuestion, "keyword");

      const query = "Madras High Court";
      await page.getByRole("textbox", { name: "Research query", exact: true }).fill(query);
      await page.getByTestId("research-mode-court").click();
      await expect(page.getByTestId("research-mode-court")).toHaveAttribute("aria-pressed", "true");
      const courtSearch = responseFor("/api/authorities/search");
      await page.getByTestId("research-query-submit").click();
      const courtResult = await researchResult(await courtSearch, query, "court");
      const courtTitles = await page.getByTestId("research-results").getByRole("heading", { level: 3 }).allTextContents();
      const courtCoverage = (await page.getByTestId("research-corpus-coverage").textContent())!;

      // Next integrates native history updates without remounting the page.
      // Keep q fixed: the mode-only transition must update both UI and request.
      const courtUrl = new URL("/app/research", web.origin);
      courtUrl.search = new URLSearchParams({ q: query, mode: "court" }).toString();
      await page.evaluate(href => window.history.replaceState(null, "", href), courtUrl.href);
      const timeOrigin = await page.evaluate(() => performance.timeOrigin);
      const keywordUrl = new URL(courtUrl);
      keywordUrl.searchParams.set("mode", "keyword");
      const [changed] = await Promise.all([
        responseFor("/api/authorities/search"),
        (async () => {
          await page.evaluate(href => window.history.pushState(null, "", href), keywordUrl.href);
          await expect(page).toHaveURL(keywordUrl.href);
          await expect(page.getByTestId("research-mode-keyword")).toHaveAttribute("aria-pressed", "true");
        })(),
      ]);
      expect(await page.evaluate(() => performance.timeOrigin)).toBe(timeOrigin);
      await researchResult(changed, query, "keyword");
      await page.goBack();
      await expect(page).toHaveURL(courtUrl.href);
      await expect(page.getByTestId("research-mode-court")).toHaveAttribute("aria-pressed", "true");
      await expect(page.getByRole("textbox", { name: "Research query", exact: true })).toHaveValue(query);
      // A valid cached response must restore the same surface before reload;
      // browser Back does not need to issue another HTTP request.
      await researchSurface(courtResult, query, "court");
      await expect(page.getByTestId("research-results").getByRole("heading", { level: 3 })).toHaveText(courtTitles);
      await expect(page.getByTestId("research-corpus-coverage")).toHaveText(courtCoverage);
      const reloading = responseFor("/api/authorities/search");
      await page.reload();
      await researchResult(await reloading, query, "court");
      for (const id of ["research-query-input", "research-query-submit", "research-mode-keyword", "research-mode-court"]) {
        const control = page.getByTestId(id);
        await control.scrollIntoViewIfNeeded();
        await expect(control).toBeVisible();
        const rect = await control.boundingBox();
        expect(rect!.width).toBeGreaterThan(40);
        expect(rect!.x).toBeGreaterThanOrEqual(0);
        expect(rect!.x + rect!.width).toBeLessThanOrEqual(phone ? 394 : 1366);
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
      expect(guardedRequests).toBeGreaterThan(0);
      await selfAuth(request, headers);
      await selfAuth(page.request, transport);
      await release();
    } finally {
      try {
        if (ownedConversation) {
          await release();
          const principal = await selfAuth(request, headers);
          expect(uuid.test(ownedConversation.id) && ownedConversation.companyId === principal.company.id
            && ownedConversation.membershipId === principal.membership.id && ownedConversation.userId === principal.user.id
            && ownedConversation.matterId === ownedMatter?.id && ownedMatter?.company_id === principal.company.id,
          "Archive receipt belongs only to this run's fresh Matter and authenticated creating owner").toBe(true);
          expect(ownedConversation.title).toContain(matterCode);
          expect(ownedConversation.title).toContain(title);
          const path = `${api.origin}/api/workspace-assistant/sessions/${ownedConversation.id}`;
          // The canonical GET/archive also enforce tenant and creating-member ownership.
          const currentSession = await json<AssistantSessionRecord>(await request.get(path, {
            headers, maxRetries: 0, maxRedirects: 0,
          }), "Read only this execution's conversation and fresh archive version");
          expect(currentSession.id).toBe(ownedConversation.id);
          expect(currentSession.title).toBe(ownedConversation.title);
          expect(currentSession.scope_state).toBe("current");
          expect(currentSession.scopes).toHaveLength(1);
          expect(currentSession.scopes).toMatchObject([{ scope_type: "matter", scope_id: ownedConversation.matterId,
            resource_version: ownedConversation.sourceVersion }]);
          let archived = currentSession;
          if (currentSession.status === "active") {
            await release();
            await selfAuth(request, headers);
            archived = await json<AssistantSessionRecord>(await request.post(`${path}/archive`, {
              headers, maxRetries: 0, maxRedirects: 0, data: { expected_version: currentSession.version },
            }), "Archive only this execution's conversation, never delete retained legal work");
            expect(archived.version).toBe(currentSession.version + 1);
          }
          expect(archived.id).toBe(ownedConversation.id);
          expect(archived.title).toBe(ownedConversation.title);
          expect(archived.status).toBe("archived");
          expect(archived.archived_at).toBeTruthy();
          expect(archived.retention_expires_at).toBe(currentSession.retention_expires_at);
          const retained = await json<AssistantSessionRecord>(await request.get(path, {
            headers, maxRetries: 0, maxRedirects: 0,
          }), "Owned conversation remains retained and archived before Matter disposal");
          expect(retained.id).toBe(ownedConversation.id);
          expect(retained.title).toBe(ownedConversation.title);
          expect(retained.status).toBe("archived");
          expect(retained.version).toBe(archived.version);
          expect(retained.archived_at).toBe(archived.archived_at);
          expect(retained.retention_expires_at).toBe(currentSession.retention_expires_at);
        }
      } finally {
        // An archive rejection stays a failure, but cannot suppress owned-Matter cleanup.
        if (ownedMatter) {
          await release();
          await selfAuth(request, headers);
          const current = await json<ResearchMatter>(await request.get(`${api.origin}/api/matters/${ownedMatter.id}`, {
            headers, maxRetries: 0, maxRedirects: 0,
          }), "Read only this execution's Matter before lifecycle cleanup");
          expect(current.id === ownedMatter.id && current.company_id === actor.company.id
            && current.title === title && current.matter_code === matterCode, "Cleanup owns this exact fresh tenant-scoped Matter").toBe(true);
          if (current.status !== "disposed") {
            await release();
            await json(await request.patch(`${api.origin}/api/matters/${current.id}/lifecycle/status`, {
              headers, maxRetries: 0, maxRedirects: 0, data: { to_status: "disposed", expected_from_status: current.status,
                expected_updated_at: current.updated_at, reason: "B5-013/014 fresh factual-only acceptance Matter cleanup" },
            }), "Dispose only this execution's fresh Matter with its current lifecycle version");
          }
          const disposed = await json<ResearchMatter>(await request.get(`${api.origin}/api/matters/${current.id}`, {
            headers, maxRetries: 0, maxRedirects: 0,
          }), "Owned Matter lifecycle cleanup persisted");
          expect(disposed.id === current.id && disposed.company_id === actor.company.id && disposed.status === "disposed").toBe(true);
        }
        await release();
      }
    }
  });
}
