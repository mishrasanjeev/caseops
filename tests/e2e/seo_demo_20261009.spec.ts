import { expect, test } from "@playwright/test";

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

test.describe("seo_demo_20261009", () => {
  for (const width of [360, 1280]) for (const [path, target] of publicPages) {
    test(`public CTA and truthful copy ${path} at ${width}`, async ({ page, context }, info) => {
      const analytics: string[] = [];
      page.on("request", (request) => { if (/googletagmanager|google-analytics|gtag\/js|\/g\/collect/.test(request.url())) analytics.push(request.url()); });
      await page.setViewportSize({ width, height: 850 });
      const response = await page.goto(path);
      expect(response?.status()).toBe(200);
      await expect(page.locator(`a[href="${target}"]`).first()).toBeVisible();
      const content = await page.locator("main").innerText();
      expect(content).not.toMatch(/five (?:people|tools|logins)|half of the administration|within (?:a|one) working day|never guesses|We preload cause-list sync|We set up the sandbox|no surprise modals/i);
      await expect(page.locator('script[src*="googletagmanager"],script[src*="google-analytics"]')).toHaveCount(0);
      expect(analytics).toEqual([]);
      expect((await context.cookies()).filter((cookie) => /^_ga|^_gid|^_gat/.test(cookie.name))).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
      const link = page.locator(`a[href="${target}"]`).first();
      await link.scrollIntoViewIfNeeded();
      const box = await link.boundingBox();
      expect(box && box.width > 20 && box.x >= 0 && box.x + box.width <= width + 1).toBeTruthy();
      await page.screenshot({ path: info.outputPath(`public-${width}.png`) });
    });
  }

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
});
