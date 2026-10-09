import { expect, test, type APIRequestContext } from "@playwright/test";
import { apiBaseUrl } from "./support/env";
import { noPaidProviderHeaders } from "./support/cost-controls";

const entries = [
  ["/#cta", "homepage", "solo"], ["/pricing", "pricing_page", "solo"],
  ["/demo/solo-lawyers", "solo_lawyers", "solo"], ["/demo/law-firms", "law_firms", "firm"],
  ["/demo/general-counsels", "general_counsels", "gc"], ["/demo/guide", "guide", "firm"],
  ["/demo/resource", "resource", "firm"],
] as const;
const publicPages = [
  ["/", "#cta"], ["/pricing", "#pricing-request"], ["/solo-lawyers", "/demo/solo-lawyers"],
  ["/law-firms", "/demo/law-firms"], ["/general-counsels", "/demo/general-counsels"],
  ["/guide", "/demo/guide"], ["/resources/legal-matter-management-india", "/demo/resource"],
] as const;

function localOnly(url: string) {
  const parsed = new URL(url);
  expect(["127.0.0.1", "localhost", "::1"], "Synthetic lead acceptance is loopback-only; never production.").toContain(parsed.hostname);
}

async function seoDemoLocalIdentity(api: APIRequestContext, slug: string, email: string, password: string) {
  localOnly(apiBaseUrl);
  const credentials = { company_slug: slug, email, password };
  const login = await api.post(`${apiBaseUrl}/api/auth/login`, { data: credentials, headers: noPaidProviderHeaders });
  if (login.status() === 200) return (await login.json()).access_token as string;
  expect(login.status()).toBe(401);
  const bootstrap = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    headers: noPaidProviderHeaders,
    data: { company_name: "Offline Demo Readback", company_slug: slug, company_type: "law_firm",
      owner_full_name: "Offline Readback Owner", owner_email: email, owner_password: password },
  });
  if (bootstrap.status() === 200) return (await bootstrap.json()).access_token as string;
  expect(bootstrap.status()).toBe(409);
  const existing = await api.post(`${apiBaseUrl}/api/auth/login`, { data: credentials, headers: noPaidProviderHeaders });
  expect(existing.status()).toBe(200);
  return (await existing.json()).access_token as string;
}

test.describe("seo_demo_20261009", () => {
  for (const width of [360, 1280]) for (const [path, target] of publicPages) {
    test(`public CTA and truthful copy ${path} at ${width}`, async ({ page, context }, info) => {
      const analytics: string[] = [];
      const admissions: string[] = [];
      page.on("request", (request) => { if (/googletagmanager|google-analytics|gtag\/js|\/g\/collect/.test(request.url())) analytics.push(request.url()); });
      page.on("request", (request) => { if (request.method() === "POST" && /\/api\/(?:demo-request|billing\/enrollments\/demo-request)(?:[/?]|$)/.test(request.url())) admissions.push(request.url()); });
      await page.setViewportSize({ width, height: 850 });
      const response = await page.goto(path);
      expect(response?.status()).toBe(200);
      await expect(page.locator(`a[href="${target}"]`).first()).toBeVisible();
      const content = await page.locator("main").innerText();
      expect(content).not.toMatch(/five (?:people|tools|logins)|half of the administration|within (?:a|one) working day|never guesses|We preload cause-list sync|We set up the sandbox|no surprise modals/i);
      expect(content).not.toMatch(/no cross-statute confusion|Every substantive output is grounded|not a polished hallucination|is never confused|every inline citation has a source/i);
      if (path === "/solo-lawyers") {
        expect(content).toContain("not every attribution error");
        expect(content).toContain("Verify the Act, subsection and current law before use.");
      } else if (path === "/law-firms") {
        expect(content).toContain("Generated output can contain legal or factual errors.");
        expect(content).toContain("Verify any proposed citations against the sources before use.");
      } else if (path === "/guide") {
        expect(content).toContain("Review the Act and subsection before use.");
        expect(content).toContain("generated text may contain errors.");
      }
      await expect(page.locator('script[src*="googletagmanager"],script[src*="google-analytics"]')).toHaveCount(0);
      expect(analytics).toEqual([]);
      expect((await context.cookies()).filter((cookie) => /^_ga|^_gid|^_gat/.test(cookie.name))).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
      const link = page.locator(`a[href="${target}"]`).first();
      await link.scrollIntoViewIfNeeded();
      const box = await link.boundingBox();
      expect(box && box.width > 20 && box.x >= 0 && box.x + box.width <= width + 1).toBeTruthy();
      await page.screenshot({ path: info.outputPath(`public-${width}.png`) });
      if (target.startsWith("/demo/")) {
        const demoEntry = entries.find(([entryPath]) => entryPath === target);
        expect(demoEntry).toBeDefined();
        const demoResponse = await page.goto(target);
        expect(demoResponse?.status()).toBe(200);
        await expect(page.getByRole("heading", { level: 1, name: "Request a CaseOps conversation" })).toBeVisible();
        const form = page.getByRole("form", { name: "Request a demo" });
        await expect(form).toBeVisible();
        await expect(form.getByLabel("Practice / team")).toHaveValue(demoEntry![2]);
        await expect(form.getByLabel("Full name")).toBeEditable();
        await expect(form.getByLabel("Work email")).toBeEditable();
        await expect(form.getByLabel("Role", { exact: true })).toBeEnabled();
        await expect(form.getByRole("button", { name: "Request a conversation" })).toBeEnabled();
        await expect(form.getByRole("link", { name: "Request privacy notice" })).toHaveAttribute("href", "/demo/privacy");
        await expect(form.getByRole("status")).toHaveCount(0);
        await expect(page.locator('script[src*="googletagmanager"],script[src*="google-analytics"]')).toHaveCount(0);
        expect(analytics).toEqual([]);
        expect((await context.cookies()).filter((cookie) => /^_ga|^_gid|^_gat/.test(cookie.name))).toEqual([]);
      }
      expect(admissions, "Public read-only coverage must never submit a lead.").toEqual([]);
    });
  }

  test.describe("public read-only prototype source rejection", () => {
    for (const source of ["constructor", "__proto__"]) {
      test(`unsupported prototype source ${source} returns 404 without an actionable demo form`, async ({ page, context }) => {
        const admissions: string[] = [];
        const analytics: string[] = [];
        page.on("request", (request) => {
          if (request.method() === "POST" && /\/api\/(?:demo-request|billing\/enrollments\/demo-request)(?:[/?]|$)/.test(request.url())) admissions.push(request.url());
          if (/googletagmanager|google-analytics|gtag\/js|\/g\/collect/.test(request.url())) analytics.push(request.url());
        });
        const response = await page.goto(`/demo/${source}`);
        expect(response?.status()).toBe(404);
        await expect(page.getByRole("form", { name: "Request a demo" })).toHaveCount(0);
        await expect(page.locator('form[action*="demo"],input[name="contact_email"]')).toHaveCount(0);
        await expect(page.getByRole("button", { name: "Request a conversation" })).toHaveCount(0);
        await expect(page.locator('script[src*="googletagmanager"],script[src*="google-analytics"]')).toHaveCount(0);
        expect(admissions).toEqual([]);
        expect(analytics).toEqual([]);
        expect((await context.cookies()).filter((cookie) => /^_ga|^_gid|^_gat/.test(cookie.name))).toEqual([]);
      });
    }
  });

  for (const [path, source, segment] of entries) {
    test(`durable admission ${source}, replay and no tracking`, async ({ page, request, context, baseURL }, info) => {
      test.skip(!["127.0.0.1", "localhost", "::1"].includes(new URL(baseURL!).hostname), "Synthetic public-demo admission is loopback-only; production is read-only.");
      await page.goto(path);
      localOnly(page.url());
      await page.setViewportSize({ width: 360, height: 850 });
      const form = page.getByRole("form", { name: "Request a demo" });
      await form.getByLabel("Full name").fill("Offline Demo Advocate");
      await form.getByLabel("Work email").fill(`seo-${source}@example.com`);
      await form.getByLabel("Role", { exact: true }).selectOption("solo_advocate");
      await expect(form.getByLabel("Practice / team")).toHaveValue(segment);
      const submitted = page.waitForRequest((request) => request.url().endsWith("/api/demo-request") && request.method() === "POST");
      await form.getByRole("button", { name: "Request a conversation" }).click();
      const payload = (await submitted).postDataJSON();
      expect(payload).toMatchObject({ source, segment, privacy_notice_version: "2026-10-09", role: "solo_advocate" });
      expect(Object.keys(payload).sort()).toEqual(["company_name", "contact_email", "contact_name", "idempotency_key", "intent", "notes", "privacy_notice_version", "role", "segment", "selected_plan", "source"]);
      await expect(form.getByRole("status")).toContainText(`Reference: ${payload.idempotency_key}`);
      await expect(form.getByRole("button", { name: "Request a conversation" })).toBeDisabled();
      const duplicate = await request.post("/api/demo-request", { data: payload });
      expect(duplicate.status()).toBe(202);
      expect(await duplicate.json()).toEqual({ accepted: true, id: payload.idempotency_key, status: "demo_requested" });
      const conflict = await request.post("/api/demo-request", { data: { ...payload, role: "partner" } });
      expect(conflict.status()).toBe(409);
      expect((await context.cookies()).filter((cookie) => /^_ga|^_gid|^_gat/.test(cookie.name))).toEqual([]);
      await form.screenshot({ path: info.outputPath("saved-form-mobile.png") });
    });
  }

  test("ambiguous browser transport retains one key and no automatic retry", async ({ page, baseURL }) => {
    test.skip(!["127.0.0.1", "localhost", "::1"].includes(new URL(baseURL!).hostname), "Synthetic public-demo admission is loopback-only; production is read-only.");
    await page.goto("/demo/solo-lawyers");
    localOnly(page.url());
    const form = page.getByRole("form", { name: "Request a demo" });
    const bodies: string[] = [];
    await page.route("**/api/demo-request", async (route) => {
      const body = route.request().postData()!;
      bodies.push(body);
      if (bodies.length === 1) return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: "Could not confirm the saved request." }) });
      return route.continue();
    });
    await form.getByLabel("Full name").fill("Offline Retry Advocate");
    await form.getByLabel("Work email").fill("seo-retry@example.com");
    await form.getByLabel("Role", { exact: true }).selectOption("solo_advocate");
    await form.getByRole("button", { name: "Request a conversation" }).click();
    await expect(form.getByRole("alert")).toBeVisible();
    expect(bodies).toHaveLength(1);
    await expect(form.getByLabel("Full name")).toBeDisabled();
    await expect(form.getByRole("status")).toHaveCount(0);
    await form.getByRole("button", { name: "Retry the same request" }).click();
    await expect(form.getByRole("status")).toContainText("Request saved.");
    expect(bodies[0]).toBe(bodies[1]);
  });

  test("invalid admission is never accepted", async ({ request, baseURL }) => {
    test.skip(!["127.0.0.1", "localhost", "::1"].includes(new URL(baseURL!).hostname), "Public-demo POST probes are loopback-only; production is read-only.");
    localOnly(baseURL!);
    const response = await request.post("/api/demo-request", { data: { name: "x", referrer: "private" } });
    expect(response.status()).toBe(400);
    expect(await response.json()).toEqual({ error: "Review the request fields and try again." });
  });

  test("protected founder readback retains the saved public request after reload", async ({ page, request, baseURL }, info) => {
    test.skip(!["127.0.0.1", "localhost", "::1"].includes(new URL(baseURL!).hostname)
      || !["127.0.0.1", "localhost", "::1"].includes(new URL(apiBaseUrl).hostname),
    "Synthetic admission and identity bootstrap are loopback-only; production is read-only.");
    localOnly(baseURL!);
    localOnly(apiBaseUrl);
    await page.goto("/demo/law-firms");
    const form = page.getByRole("form", { name: "Request a demo" });
    const email = `seo-readback-${Date.now()}@example.com`;
    await form.getByLabel("Full name").fill("Offline Readback Partner");
    await form.getByLabel("Work email").fill(email);
    await form.getByLabel("Firm / company (optional)").fill("Offline Readback Practice");
    await form.getByLabel("Role", { exact: true }).selectOption("partner");
    await form.getByLabel("What would you like to discuss? (optional)").fill("Discuss an offline scoped pilot; no client information.");
    const submitted = page.waitForRequest((r) => r.url().endsWith("/api/demo-request") && r.method() === "POST");
    await form.getByRole("button", { name: "Request a conversation" }).click();
    const savedRequest = await submitted;
    expect(savedRequest.headers()["x-caseops-automated-test"]).toBe("no-paid-providers");
    const identity = savedRequest.postDataJSON().idempotency_key as string;
    await expect(form.getByRole("status")).toContainText(identity);

    const slug = "platform-admin-e2e";
    const founderEmail = "platform-admin-e2e@example.com";
    const password = "PlatformAdminE2E!";
    const founderToken = await seoDemoLocalIdentity(request, slug, founderEmail, password);
    const protectedRead = await request.get(`${apiBaseUrl}/api/platform-admin/enrollments`, {
      headers: { ...noPaidProviderHeaders, Authorization: `Bearer ${founderToken}` },
    });
    expect(protectedRead.status()).toBe(200);
    expect((await protectedRead.json()).enrollments.find((r: { id: string }) => r.id === identity)).toMatchObject({
      contact_email: email, source: "law_firms", attribution: { role: "partner", intent: "pilot" },
      demo_notification: { notification_status: "pending", last_error_code: "sender_approval_pending" },
    });
    await page.goto("/sign-in");
    await page.locator("#company-slug").fill(slug);
    await page.locator("#email").fill(founderEmail);
    await page.locator("#password").fill(password);
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await page.waitForURL(/\/app(?:[/?]|$)/);
    await page.goto("/app/platform-admin");
    for (const width of [1280, 360]) {
      await page.setViewportSize({ width, height: 900 });
      await page.reload();
      const table = page.getByRole("table", { name: "Recent enrollments" });
      const row = table.getByRole("row").filter({ hasText: identity });
      await expect(row.getByText(email, { exact: true })).toBeVisible();
      await expect(row.getByText("Offline Readback Partner", { exact: true })).toBeVisible();
      await expect(row.getByText("Discuss an offline scoped pilot; no client information.", { exact: true })).toBeVisible();
      await row.getByText("Law firms", { exact: true }).scrollIntoViewIfNeeded();
      await expect(row.getByText("Role: Partner", { exact: true })).toBeVisible();
      await expect(row.getByText("Intent: Pilot discussion", { exact: true })).toBeVisible();
      await row.getByText("Pending sender approval", { exact: true }).scrollIntoViewIfNeeded();
      await expect(row.getByText("Error code: sender_approval_pending", { exact: true })).toBeVisible();
      await expect(row.getByText("No delivery confirmed.", { exact: true })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
      await table.screenshot({ path: info.outputPath(`protected-readback-${width}.png`) });
    }
    const ordinary = await seoDemoLocalIdentity(request, `seo-readback-${Date.now()}`, `seo-tenant-${Date.now()}@example.com`, "OfflineReadbackTenant20261009!");
    const denied = await request.get(`${apiBaseUrl}/api/platform-admin/enrollments`, {
      headers: { ...noPaidProviderHeaders, Authorization: `Bearer ${ordinary}` },
    });
    expect(denied.status()).toBe(403);
    expect(await denied.text()).not.toContain(email);
  });
});
