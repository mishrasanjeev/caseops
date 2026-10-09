/**
 * Shared Docker/exact-release production notice regression. No provider calls.
 * Live: CASEOPS_EXPECTED_RELEASE_SHA, PROD_API_BASE_URL, CASEOPS_NOTICE_QA_SLUG
 * (test-legal or caseops-qa) and CASEOPS_NOTICE_OWNER_EMAIL/PASSWORD are required.
 * Existing actors also require CASEOPS_NOTICE_DENIED_EMAIL/PASSWORD. Actors are same-tenant;
 * the denied actor needs documents:upload/manage but must not be an owner.
 * Only test-legal may opt into CASEOPS_NOTICE_CREATE_TEST_LEGAL_MEMBER=true;
 * it derives one fixed partner's password in memory from the owner secret,
 * deactivates it afterward, and never resets an existing user's credentials.
 * A rotated owner secret that no longer authenticates the retained fixture
 * fails closed and requires explicit fixture credential maintenance.
 * Do not run against production until the candidate is deployed and mutations
 * are authorized. Missing setup fails; no skip, retry, saved session or live media.
 */
import { expect, test, type Locator, type Page } from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import { NoticeAcceptance, status, type Notice } from "./support/notice-upload-access";

test.use({
  extraHTTPHeaders: noPaidProviderHeaders,
  storageState: { cookies: [], origins: [] },
  trace: "off", screenshot: "off", video: "off",
});
test.describe.configure({ retries: 0 });
test.setTimeout(240_000);

let fixture: NoticeAcceptance;
test.beforeAll(async ({ baseURL }) => {
  if (!baseURL) throw new Error("Use a standard app, Docker or exact-release production config.");
  fixture = new NoticeAcceptance(baseURL);
  await fixture.start();
});
test.afterAll(async () => { await fixture?.close(); });

async function usable(locator: Locator, page: Page) {
  await expect(locator).toBeVisible();
  await expect(locator).toBeEnabled();
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.width).toBeGreaterThan(24);
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(page.viewportSize()!.width + 1);
}

async function downloadBytes(page: Page, notice: Notice, expected: string) {
  const button = page.getByTestId(`notice-row-${notice.id}`).getByRole("button", { name: `Download ${notice.filename}`, exact: true });
  await usable(button, page);
  const downloaded = page.waitForEvent("download");
  await button.click();
  const download = await downloaded;
  expect(download.suggestedFilename()).toBe(notice.filename);
  const stream = await download.createReadStream();
  if (!stream) throw new Error("Browser notice download returned no bytes.");
  const chunks: Buffer[] = [];
  for await (const chunk of stream) chunks.push(Buffer.from(chunk));
  expect(Buffer.concat(chunks)).toEqual(Buffer.from(expected));
  expect(await download.failure()).toBeNull();
  await download.delete();
}

async function filteredRegister(page: Page, query: string, visibleIds: string[], hiddenId?: string) {
  const loaded = page.waitForResponse(response => {
    const url = new URL(response.url());
    return url.pathname === "/api/notices/" && response.request().method() === "GET"
      && url.searchParams.get("query") === query && url.searchParams.get("limit") === "100";
  });
  await page.locator("#notice-search").fill(query);
  const response = await loaded;
  expect(response.status(), "actual browser filtered register").toBe(200);
  expect(response.request().headers()["x-caseops-automated-test"]).toBe("no-paid-providers");
  const result = await response.json();
  expect(result.total).toBe(visibleIds.length);
  expect(result.next_cursor).toBeNull();
  expect(result.notices.map((notice: Notice) => notice.id).sort()).toEqual([...visibleIds].sort());
  for (const id of visibleIds) await expect(page.getByTestId(`notice-row-${id}`)).toBeVisible();
  if (hiddenId) await expect(page.getByTestId(`notice-row-${hiddenId}`)).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
}

for (const width of [1280, 393]) {
  test.describe(`notice upload/access at ${width}px`, () => {
    test.use({ viewport: { width, height: 900 }, isMobile: width === 393, hasTouch: width === 393 });

    test("first upload, replacement and reload preserve bytes; unassigned restricted links stay hidden", async ({ page, browser }, info) => {
      await fixture.assertRelease();
      const prefix = `N1008-${fixture.run}-${width}`;
      const subject = `${prefix} standalone`;
      const initialBody = `${prefix}: original standalone notice bytes.\n`;
      const replacementBody = `${prefix}: replacement bytes, different length and content.\n`;
      const initialName = "first-notice.txt";
      const replacementName = "replacement-notice.txt";

      await fixture.signIn(page, "owner");
      await page.goto("/app/notices");
      await expect(page.getByRole("heading", { name: "Notice management" })).toBeVisible();
      await usable(page.getByRole("button", { name: "New notice" }).first(), page);
      await page.getByRole("button", { name: "New notice" }).first().click();
      const dialog = page.getByTestId("create-notice-dialog");
      await dialog.getByLabel("Subject", { exact: true }).fill(subject);
      await dialog.getByLabel("Owner", { exact: true }).selectOption(fixture.owner.membership.id);
      await dialog.getByLabel("Notice document (optional)").setInputFiles({
        name: initialName, mimeType: "text/plain", buffer: Buffer.from(initialBody),
      });
      const created = page.waitForResponse(r => new URL(r.url()).pathname === "/api/notices/" && r.request().method() === "POST");
      const uploaded = page.waitForResponse(r => /\/api\/notices\/[^/]+\/file$/.test(new URL(r.url()).pathname) && r.request().method() === "POST");
      await usable(dialog.getByRole("button", { name: "Create notice", exact: true }), page);
      await dialog.getByRole("button", { name: "Create notice", exact: true }).click();
      const createdResponse = await created;
      expect(createdResponse.status()).toBe(201);
      let standalone = await createdResponse.json() as Notice;
      fixture.notices.add(standalone.id);
      expect(standalone).toMatchObject({ source_kind: "standalone", has_file: false, matter_links: [] });
      const uploadResponse = await uploaded;
      expect(new URL(uploadResponse.url()).pathname).toBe(`/api/notices/${standalone.id}/file`);
      expect(uploadResponse.status(), "original first-upload request must succeed, without retry").toBe(200);
      standalone = await uploadResponse.json() as Notice;
      expect(standalone).toMatchObject({ has_file: true, filename: initialName, size_bytes: Buffer.byteLength(initialBody), matter_links: [] });
      await expect(dialog).toBeHidden();
      const standaloneRow = page.getByTestId(`notice-row-${standalone.id}`);
      await expect(standaloneRow).toContainText("Standalone - no linked matters");
      await downloadBytes(page, standalone, initialBody);

      const replace = standaloneRow.getByRole("button", { name: `Replace document for ${subject}`, exact: true });
      await usable(replace, page);
      const chooser = page.waitForEvent("filechooser");
      await replace.click();
      const replacement = page.waitForResponse(r => new URL(r.url()).pathname === `/api/notices/${standalone.id}/file` && r.request().method() === "POST");
      await (await chooser).setFiles({ name: replacementName, mimeType: "text/plain", buffer: Buffer.from(replacementBody) });
      const replacementResponse = await replacement;
      expect(replacementResponse.status(), "one replacement attempt must succeed").toBe(200);
      standalone = await replacementResponse.json() as Notice;
      expect(standalone).toMatchObject({ has_file: true, filename: replacementName, size_bytes: Buffer.byteLength(replacementBody), matter_links: [] });
      await downloadBytes(page, standalone, replacementBody);
      await page.reload();
      await filteredRegister(page, prefix, [standalone.id]);
      expect(await fixture.readNotice(standalone.id)).toMatchObject({ filename: replacementName, updated_at: standalone.updated_at, matter_links: [] });
      await downloadBytes(page, standalone, replacementBody);

      const restrictedMatter = await fixture.createMatter(`${prefix}-R`, true);
      const visibleMatter = await fixture.createMatter(`${prefix}-V`, false);
      const restrictedBody = `${prefix}: restricted linked notice bytes.`;
      const visibleBody = `${prefix}: visible sibling notice bytes.`;
      let restricted = await fixture.createLinkedNotice(`${prefix} restricted`, restrictedMatter, restrictedBody);
      const sibling = await fixture.createLinkedNotice(`${prefix} sibling`, visibleMatter, visibleBody);
      expect(restricted.matter_links).toEqual([expect.objectContaining({ matter_id: restrictedMatter.id })]);
      expect(sibling.matter_links).toEqual([expect.objectContaining({ matter_id: visibleMatter.id })]);

      await page.reload();
      await filteredRegister(page, prefix, [standalone.id, restricted.id, sibling.id]);
      await downloadBytes(page, restricted, restrictedBody);
      await downloadBytes(page, sibling, visibleBody);
      const ownerUpdate = await fixture.ownerApi.patch(`${fixture.apiUrl}/api/notices/${restricted.id}`, {
        data: { status: "Under Review", expected_updated_at: restricted.updated_at },
      });
      await status(ownerUpdate, 200, "owner can update the restricted linked notice");
      restricted = await fixture.readNotice(restricted.id);
      expect(restricted.status).toBe("Under Review");

      const deniedContext = await browser.newContext({
        baseURL: fixture.webUrl, viewport: { width, height: 900 },
        isMobile: width === 393, hasTouch: width === 393,
        storageState: { cookies: [], origins: [] }, extraHTTPHeaders: noPaidProviderHeaders,
      });
      try {
        const deniedPage = await deniedContext.newPage();
        await fixture.signIn(deniedPage, "denied");
        await deniedPage.goto("/app/notices");
        await filteredRegister(deniedPage, prefix, [standalone.id, sibling.id], restricted.id);
        await downloadBytes(deniedPage, standalone, replacementBody);
        await downloadBytes(deniedPage, sibling, visibleBody);

        // One actor, valid capability, positive sibling: 404 cannot be an expired
        // session, cross-tenant probe, missing file, stale token, or viewer role.
        const api = fixture.deniedApi;
        await status(await api.get(`${fixture.apiUrl}/api/notices/${sibling.id}`), 200, "denied actor sibling GET succeeds");
        await status(await api.get(`${fixture.apiUrl}/api/notices/${restricted.id}`), 404, "restricted notice GET denied");
        await status(await api.get(`${fixture.apiUrl}/api/notices/${restricted.id}/download`), 404, "restricted notice download denied");
        await status(await api.patch(`${fixture.apiUrl}/api/notices/${restricted.id}`, {
          data: { status: "Closed", expected_updated_at: restricted.updated_at },
        }), 404, "restricted notice update denied");
        await status(await api.post(`${fixture.apiUrl}/api/notices/${restricted.id}/file`, {
          multipart: { expected_updated_at: restricted.updated_at,
            file: { name: "denied.txt", mimeType: "text/plain", buffer: Buffer.from("must not replace") } },
        }), 404, "restricted notice replacement denied");
        expect(await fixture.readNotice(restricted.id)).toEqual(restricted);

        const siblingRow = deniedPage.getByTestId(`notice-row-${sibling.id}`);
        const statusControl = siblingRow.getByLabel(`Status for ${sibling.subject}`);
        await usable(statusControl, deniedPage);
        const updated = deniedPage.waitForResponse(r => new URL(r.url()).pathname === `/api/notices/${sibling.id}` && r.request().method() === "PATCH");
        await statusControl.selectOption("Under Review");
        expect((await updated).status(), "same denied actor can update permitted sibling through UI").toBe(200);
        await deniedPage.reload();
        await filteredRegister(deniedPage, prefix, [standalone.id, sibling.id], restricted.id);
        await expect(statusControl).toHaveValue("Under Review");
        await downloadBytes(deniedPage, sibling, visibleBody);
        if (fixture.local) await deniedPage.screenshot({ path: info.outputPath(`notice-denied-${width}.png`), fullPage: true });
      } finally {
        await deniedContext.close();
      }

      await page.reload();
      await filteredRegister(page, prefix, [standalone.id, restricted.id, sibling.id]);
      await expect(page.getByTestId(`notice-row-${restricted.id}`).getByLabel(`Status for ${restricted.subject}`)).toHaveValue("Under Review");
      await downloadBytes(page, restricted, restrictedBody);
      if (fixture.local) await page.screenshot({ path: info.outputPath(`notice-owner-${width}.png`), fullPage: true });
      await fixture.assertRelease();
    });
  });
}
