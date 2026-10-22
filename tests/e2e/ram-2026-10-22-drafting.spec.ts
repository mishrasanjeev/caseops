/** B3-001: actual local mock-provider recovery, never a paid production call. */
import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import path from "node:path";
import { expect, request, test, type APIRequestContext, type Page, type TestInfo } from "@playwright/test";
import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";
import { localTransportHeaders } from "./support/cost-controls";
import { assertPublicReleaseIdentity } from "./support/public-release-identity";

type Version = { id: string; revision: number; body: string; citations: string[]; verified_citation_count: number };
type Draft = { id: string; status: string; current_version_id: string; review_required: boolean;
  versions: Version[]; reviews: Array<{ action: string; version_id: string }> };
const loopback = (url: URL) => ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);

async function json<T>(api: APIRequestContext, url: string, method = "GET", data?: object, expected = 200): Promise<T> {
  const response = await api.fetch(url, { method, data, maxRetries: 0, maxRedirects: 0 });
  expect(response.status(), `${method} ${new URL(url).pathname}: ${await response.text()}`).toBe(expected);
  return response.json() as Promise<T>;
}

async function visibleControl(page: Page, id: string): Promise<void> {
  const locator = page.getByTestId(id);
  await locator.scrollIntoViewIfNeeded();
  await expect(locator).toBeVisible();
  const box = await locator.boundingBox(), viewport = page.viewportSize();
  expect(Boolean(box && viewport && box.width >= 40 && box.height >= 24 && box.x >= 0
    && box.x + box.width <= viewport.width + 1 && box.y >= 0 && box.y + box.height <= viewport.height + 1), id).toBe(true);
}

async function journey(page: Page, baseURL: string | undefined, info: TestInfo, mobile: boolean): Promise<void> {
  if (!baseURL) throw new Error("Configured Docker/app baseURL is required.");
  const web = new URL(baseURL), api = new URL(apiBaseUrl);
  if (![web, api].every(loopback) || web.hostname !== api.hostname) {
    throw new Error("Synthetic authorities and mock generation are strictly loopback-only.");
  }
  expect(info.config.workers).toBe(1);
  expect(info.project.retries).toBe(0);
  if (mobile) {
    expect(info.project.name).toBe("app-mobile");
    expect(info.project.use.isMobile).toBe(true);
    expect(info.project.use.hasTouch).toBe(true);
    expect(page.viewportSize()?.width).toBe(393);
  } else await page.setViewportSize({ width: 1280, height: 1000 });
  const release = () => assertPublicReleaseIdentity([
    `${api.origin}/api/build`, `${web.origin}/api/release-identity`,
  ], e2eEnv.CASEOPS_RELEASE_SHA);
  await release();
  const run = randomUUID(), slug = `b3draft-${run}`, email = `${slug}@example.com`, password = `Synthetic!${run}aA9`;
  let http = await request.newContext({ extraHTTPHeaders: localTransportHeaders(api.origin), timeout: 30_000 });
  const generatedBodies: object[] = [];
  try {
    const tenant = await json<{ access_token: string; company: { id: string }; membership: { id: string } }>(http,
      `${api.origin}/api/bootstrap/company`, "POST", { company_name: `Synthetic QA drafting ${run}`, company_slug: slug,
        company_type: "law_firm", owner_full_name: "Synthetic QA owner", owner_email: email, owner_password: password });
    await http.dispose();
    http = await request.newContext({ extraHTTPHeaders: { ...localTransportHeaders(api.origin),
      Authorization: `Bearer ${tenant.access_token}` }, timeout: 30_000 });
    const matter = await json<{ id: string; status: string; lifecycle_version: number }>(http, `${api.origin}/api/matters/`, "POST", {
      title: `Synthetic QA batch3 draft ${run}`, matter_code: `B3DRAFT-${run}`, practice_area: "Civil",
      forum_level: "high_court", status: "intake",
    });
    const created = await json<Draft>(http, `${api.origin}/api/matters/${matter.id}/drafts`, "POST", {
      title: `Synthetic QA Appeal Memorandum ${run}`, draft_type: "memo", template_type: "appeal_memorandum",
    });
    const python = process.env.CASEOPS_E2E_PYTHON?.trim() || path.join(repoRoot, "apps", "api", ".venv",
      process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
    const fixture = spawnSync(python, [path.join(repoRoot, "tests/e2e/support/ram_batch3_draft_fixture.py")], {
      cwd: repoRoot, encoding: "utf8", timeout: 30_000,
      input: JSON.stringify({ web: web.origin, api: api.origin, run, company_id: tenant.company.id,
        membership_id: tenant.membership.id, matter_id: matter.id, draft_id: created.id }),
      env: { ...process.env, ...e2eEnv, CASEOPS_LLM_PROVIDER: "mock", CASEOPS_EMBEDDING_PROVIDER: "mock",
        PYTHONPATH: path.join(repoRoot, "apps/api/src") },
    });
    expect(fixture.status, `${fixture.stdout}\n${fixture.stderr}`).toBe(0);
    const seeded = JSON.parse(fixture.stdout.trim()) as { citation: string; version_id: string };
    const draftUrl = `${api.origin}/api/matters/${matter.id}/drafts/${created.id}`;
    const read = () => json<Draft>(http, draftUrl);
    const initial = await read();
    expect(initial.versions).toHaveLength(1);
    expect(initial.versions[0].verified_citation_count).toBe(0);
    await json(http, `${draftUrl}/submit`, "POST", {});
    await json(http, `${draftUrl}/approve`, "POST", {}, 422);
    expect((await read()).status).toBe("in_review");
    await page.setExtraHTTPHeaders(localTransportHeaders(web.origin));
    await page.context().route("**/*", async route => {
      const pending = route.request(), url = new URL(pending.url());
      if (![web.origin, api.origin].includes(url.origin)) throw new Error("No external requests in the drafting QA journey.");
      if (pending.method() !== "OPTIONS") expect(pending.headers()["x-caseops-automated-test"]).toBe("no-paid-providers");
      if (pending.method() === "POST" && url.pathname === new URL(`${draftUrl}/generate`).pathname) {
        generatedBodies.push(pending.postDataJSON());
      }
      await route.continue();
    });
    await page.goto(`${web.origin}/sign-in`);
    await page.locator("#company-slug").fill(slug);
    await page.locator("#email").fill(email);
    await page.locator("#password").fill(password);
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await page.waitForURL(/\/app(?:[/?]|$)/);
    await page.goto(`${web.origin}/app/matters/${matter.id}/drafts/${created.id}`);
    await expect(page.getByTestId("draft-citation-status")).toContainText("Revision 1 has no verified citations");
    await expect(page.getByTestId("draft-approve")).toBeDisabled();
    await page.reload();
    await expect(page.getByTestId("draft-approve")).toBeDisabled();
    await visibleControl(page, "draft-request-changes");
    await page.getByTestId("draft-request-changes").click();
    await expect.poll(async () => (await read()).status).toBe("changes_requested");
    const focus = `Review the synthetic QA record only.\n- CITATION: ${seeded.citation}`;
    await expect(page.getByRole("link", { name: "Matter context", exact: true })).toHaveAttribute("href", `/app/matters/${matter.id}`);
    await page.getByLabel("Regeneration focus", { exact: true }).fill(focus);
    await visibleControl(page, "draft-generate");
    await page.getByTestId("draft-generate").click();
    await expect(page.getByTestId("draft-current-revision")).toHaveText("Revision 2");
    expect(generatedBodies).toEqual([{ focus_note: focus, template_key: null }]);
    const second = await read(), v2 = second.versions.find(version => version.id === second.current_version_id)!;
    expect(second.status).toBe("draft");
    expect(second.review_required).toBe(true);
    expect(v2.verified_citation_count).toBeGreaterThan(0);
    expect(v2.citations).toContain(seeded.citation);
    expect(second.versions.find(version => version.id === seeded.version_id)).toEqual(initial.versions[0]);
    await page.getByTestId("draft-submit").click();
    await expect(page.getByTestId("draft-approve")).toBeEnabled();
    await page.getByTestId("draft-approve").click();
    await expect(page.getByTestId("draft-finalize")).toBeEnabled();
    const approved = await read();
    expect(approved.reviews.some(review => review.action === "approve" && review.version_id === v2.id)).toBe(true);
    await page.getByTestId("draft-edit-toggle").click();
    await page.getByTestId("draft-body-editor").fill("Synthetic QA replacement without any authority. Not legal advice.");
    await page.getByTestId("draft-save-edit").click();
    await expect(page.getByTestId("draft-current-revision")).toHaveText("Revision 3");
    await page.getByTestId("draft-submit").click();
    await expect(page.getByTestId("draft-approve")).toBeDisabled();
    await expect(page.getByTestId("draft-citation-status")).toContainText("Revision 3 has no verified citations");
    await json(http, `${draftUrl}/approve`, "POST", {}, 422);
    await page.getByLabel("Regeneration focus", { exact: true }).fill(focus);
    await page.getByTestId("draft-generate").click();
    await expect(page.getByTestId("draft-current-revision")).toHaveText("Revision 4");
    await page.getByTestId("draft-submit").click();
    await expect(page.getByTestId("draft-approve")).toBeEnabled();
    await page.getByTestId("draft-approve").click();
    await page.getByTestId("draft-finalize").click();
    await expect(page.getByTestId("draft-generate")).toBeDisabled();
    const finalized = await read();
    expect(finalized.status).toBe("finalized");
    expect(finalized.review_required).toBe(false);
    expect(finalized.versions).toHaveLength(4);
    expect(finalized.reviews.some(review => review.action === "finalize" && review.version_id === finalized.current_version_id)).toBe(true);
    await json(http, `${draftUrl}/generate`, "POST", { focus_note: focus }, 409);
    expect(await read()).toEqual(finalized);
    await visibleControl(page, "draft-download-docx");
    const download = page.waitForEvent("download");
    await page.getByTestId("draft-download-docx").click();
    expect((await download).suggestedFilename()).toMatch(/\.docx$/);
    await page.reload();
    await expect(page.getByTestId("draft-current-revision")).toHaveText("Revision 4");
    await expect(page.getByTestId("draft-generate")).toBeDisabled();
    expect(await page.getByTestId("draft-edit-toggle").count()).toBe(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
    expect((await json<{ status: string; lifecycle_version: number }>(http, `${api.origin}/api/matters/${matter.id}`)).status).toBe("intake");
    await info.attach(`synthetic-draft-final-${mobile ? "mobile" : "desktop"}`, { body: await page.screenshot(), contentType: "image/png" });
    await release();
  } finally { await http.dispose(); }
}

test("B3-DRAFT local zero-citation recovery, latest-revision approval and finalization", async ({ page, baseURL }, info) => {
  await journey(page, baseURL, info, false);
});
test("B3-DRAFT [mobile] local recovery preserves safeguards through edit and finalization", async ({ page, baseURL }, info) => {
  await journey(page, baseURL, info, true);
});
