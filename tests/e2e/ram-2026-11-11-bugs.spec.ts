/** BUG-003 partial candidate acceptance, against one exact API/web release.
 * Preview and marked 409 rejection are not delivery acceptance. Default-template
 * selection and full reusable-template editing remain open in workbook row 003.
 * Reuse the tester's auth helpers, never prepareTester's unrelated IP setup.
 */
import { randomUUID } from "node:crypto";
import { expect, test, type APIRequestContext } from "@playwright/test";

import { authContext, authSession, type AuthContext, type AuthSession } from "../../apps/web/lib/api/schemas";
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
      await compose.getByLabel("Message", { exact: true }).fill("Hi {[client_name]}, the next hearing is on {[hearing_date]}.");
      await expect(compose.getByRole("alert")).toContainText("Unsupported placeholders");
      await expect(compose.getByTestId("comm-send-preview")).toBeDisabled();
      await expect(compose.getByTestId("comm-send-submit")).toBeDisabled();

      await compose.getByTestId("comm-send-template").selectOption("");
      await compose.getByLabel("Subject", { exact: true }).fill("Reviewed update");
      await compose.getByLabel("Message", { exact: true }).fill("Hi {{client_name}}, no hearing date is confirmed.");
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
