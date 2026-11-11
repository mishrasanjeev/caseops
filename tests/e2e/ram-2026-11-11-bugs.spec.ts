/** BUG-003 candidate acceptance. Loopback only; no email delivery or paid calls.
 * The real API proves resolution/guards. API tests separately prove mocked
 * delivery persistence; this browser journey never labels logging as delivery.
 */
import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";
import { localTransportHeaders } from "./support/cost-controls";

for (const phone of [false, true]) {
  test(`BUG-003 communications resolved preview and missing-value guard ${phone ? "phone" : "desktop"}`, async ({ page, request, baseURL }, info) => {
    const web = new URL(baseURL!);
    if (!["127.0.0.1", "localhost"].includes(web.hostname)) throw new Error("BUG-003 candidate journey is loopback-only; production acceptance belongs to the parent release.");
    const api = `http://${web.hostname}:${process.env.CASEOPS_E2E_API_PORT ?? "8000"}`;
    const headers = localTransportHeaders(api);
    const nonce = randomUUID().slice(0, 8);
    const credentials = { company_slug: `comms-${nonce}`, email: `owner-${nonce}@example.com`, password: `Offline!${randomUUID()}` };
    const boot = await request.post(`${api}/api/bootstrap/company`, { headers, data: {
      company_name: "Communications QA", company_slug: credentials.company_slug, company_type: "law_firm",
      owner_full_name: "Communications QA", owner_email: credentials.email, owner_password: credentials.password,
    } });
    expect(boot.status()).toBe(200);
    await page.setViewportSize(phone ? { width: 393, height: 851 } : { width: 1365, height: 900 });
    await page.setExtraHTTPHeaders(localTransportHeaders(web.origin));
    await page.goto("/sign-in");
    await page.locator("#company-slug").fill(credentials.company_slug);
    await page.locator("#email").fill(credentials.email);
    await page.locator("#password").fill(credentials.password);
    await expect(page.getByRole("link", { name: "Forgot password?" })).toHaveAttribute("href", new RegExp(credentials.company_slug));
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await page.waitForURL(/\/app(?:[/?]|$)/);

    await page.goto("/app/admin/email-templates");
    await page.getByTestId("email-template-new-toggle").click();
    await page.getByTestId("email-template-name").fill(`Comms ${nonce}`);
    await page.getByTestId("email-template-subject").fill("Status update on your matter {{client_name}}");
    await page.getByTestId("email-template-body").fill("Hi {{client_name}}, the next hearing is on {{hearing_date}}.");
    const templateSaved = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/admin/email-templates" && r.request().method() === "POST");
    await page.getByTestId("email-template-submit").click();
    const template = await templateSaved;
    expect(template.status()).toBe(200);
    const templateId = (await template.json()).id as string;

    await page.goto("/app/matters");
    await page.getByTestId("new-matter-trigger").first().click();
    const dialog = page.getByRole("dialog", { name: "New matter" });
    await dialog.getByLabel("Title", { exact: true }).fill(`Communications QA ${nonce}`);
    await dialog.getByLabel("Matter code", { exact: true }).fill(`COMMS-${nonce}`);
    await dialog.getByLabel("Practice area", { exact: true }).fill("Civil");
    await dialog.getByLabel("Client name", { exact: true }).fill("QA Client");
    const matterSaved = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/matters" && r.request().method() === "POST");
    await dialog.getByRole("button", { name: "Create matter", exact: true }).click();
    const matterResponse = await matterSaved;
    expect(matterResponse.status()).toBe(200);
    const matterId = (await matterResponse.json()).id as string;
    await page.goto(`/app/matters/${matterId}/communications`);
    await page.getByTestId("comm-send-toggle").click();
    const compose = page.getByRole("region", { name: "Compose email" });
    await compose.getByTestId("comm-send-template").selectOption(templateId);
    await compose.getByLabel("Recipient email", { exact: true }).fill("no-delivery@example.com");
    await expect(compose.getByTestId("comm-send-submit")).toBeDisabled();
    await compose.getByTestId("comm-send-preview").click();
    await expect(compose.getByRole("alert")).toContainText("hearing_date");
    await expect(compose.getByTestId("comm-send-preview-result")).toContainText("Hi QA Client");
    await expect(compose.getByTestId("comm-send-submit")).toBeDisabled();

    // Preserve the exact syntax observed in the retained production record.
    await compose.getByLabel("Subject", { exact: true }).fill("Status update on your matter {[client_name]}");
    await compose.getByLabel("Message", { exact: true }).fill("Hi {[client_name]}, the next hearing is on {[hearing_date]}.");
    await compose.getByTestId("comm-send-preview").click();
    await expect(compose.getByRole("alert")).toContainText("unsupported placeholders");
    await expect(compose.getByTestId("comm-send-submit")).toBeDisabled();

    await compose.getByTestId("comm-send-template").selectOption("");
    await compose.getByLabel("Subject", { exact: true }).fill("Reviewed update");
    await compose.getByLabel("Message", { exact: true }).fill("Hi {{client_name}}, no hearing date is confirmed.");
    await compose.getByTestId("comm-send-preview").click();
    await expect(compose.getByTestId("comm-send-preview-result")).toContainText("Hi QA Client, no hearing date is confirmed.");
    await expect(compose.getByTestId("comm-send-submit")).toBeEnabled();
    await compose.getByLabel("Subject", { exact: true }).fill("Reviewed manual update");
    await expect(compose.getByTestId("comm-send-submit")).toBeDisabled();
    await compose.getByTestId("comm-send-preview").click();
    await expect(compose.getByTestId("comm-send-submit")).toBeEnabled();
    const refused = page.waitForResponse((r) => new URL(r.url()).pathname.endsWith("/communications/send-email"));
    await compose.getByTestId("comm-send-submit").click();
    expect((await refused).status()).toBe(409);
    await expect(page.getByText("Email delivery is disabled during automated verification. No email was sent.")).toBeVisible();
    const actor = await boot.json();
    const rows = await request.get(`${api}/api/matters/${matterId}/communications`, { headers: { ...headers, Authorization: `Bearer ${actor.access_token}` } });
    expect(rows.status()).toBe(200);
    expect((await rows.json()).communications).toEqual([]);

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
    await compose.screenshot({ path: info.outputPath(`comms-${phone ? "phone" : "desktop"}.png`) });
    await page.reload();
    await expect(page.getByText("No communications yet", { exact: true })).toBeVisible();
  });
}
