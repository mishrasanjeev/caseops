/** Reviewed Drive import through real HTTP and storage, without Google transport. */
import { createHash, randomUUID } from "node:crypto";
import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import { apiBaseUrl, repoRoot } from "./support/env";

const fixtureRoot = apiBaseUrl + "/_e2e/drive-import/fixtures";
const password = "DriveBrowserRegression123!";

type DriveFixture = {
  candidate_id: string; connection_id: string; matter_id: string;
  filename: string; content: string; size_bytes: number; sha256: string;
};

function requireLoopback(value: string): void {
  const url = new URL(value);
  expect(url.protocol, "Drive fixtures must never mutate production").toBe("http:");
  expect(["localhost", "127.0.0.1", "[::1]"]).toContain(url.hostname);
}

async function prepare(page: Page, scenario = "success"): Promise<DriveFixture> {
  const suffix = randomUUID().slice(0, 12);
  const slug = "drive-browser-" + suffix;
  const email = slug + "@example.com";
  const bootstrap = await page.request.post(apiBaseUrl + "/api/bootstrap/company", {
    headers: noPaidProviderHeaders,
    data: {
      company_name: "Offline reviewed Drive import", company_slug: slug,
      company_type: "law_firm", owner_full_name: "Drive Import Tester",
      owner_email: email, owner_password: password,
    },
  });
  expect(bootstrap.status(), await bootstrap.text()).toBe(200);
  const { access_token: token } = await bootstrap.json();
  const headers = { ...noPaidProviderHeaders, Authorization: "Bearer " + token };
  const configuration = await page.request.patch(apiBaseUrl + "/api/admin/google-workspace-configuration", {
    headers,
    data: {
      client_id: "caseops-drive-browser-emulator", client_secret: "offline-drive-browser-fixture-secret",
      drive_redirect_uri: apiBaseUrl + "/api/drive/google/callback",
      gmail_redirect_uri: apiBaseUrl + "/api/mailbox/gmail/callback",
      calendar_redirect_uri: apiBaseUrl + "/api/calendar/connections/google-calendar/callback",
      drive_enabled: true, gmail_enabled: false, calendar_enabled: false, enabled: true,
    },
  });
  expect(configuration.status(), await configuration.text()).toBe(200);
  const controls = await page.request.patch(apiBaseUrl + "/api/drive/google/controls", {
    headers, data: {
      mode: "review_import", auto_import_enabled: false,
      allowed_mime_types: ["text/plain"], max_file_size_bytes: 4096,
      allowed_folders: ["offline-reviewed-evidence"], blocked_folders: [],
    },
  });
  expect(controls.status(), await controls.text()).toBe(200);
  const matter = await page.request.post(apiBaseUrl + "/api/matters", {
    headers, data: {
      title: "Reviewed Drive evidence " + suffix, matter_code: "DRIVE-" + suffix.toUpperCase(),
      practice_area: "Commercial", forum_level: "high_court", status: "active",
    },
  });
  expect(matter.status(), await matter.text()).toBe(200);
  const createdMatter = await matter.json();
  expect(createdMatter).toMatchObject({
    title: "Reviewed Drive evidence " + suffix, matter_code: "DRIVE-" + suffix.toUpperCase(),
    forum_level: "high_court", status: "active", is_active: true,
  });
  const matterId = createdMatter.id;
  const seeded = await page.request.post(fixtureRoot, { headers, data: { matter_id: matterId, scenario } });
  expect(seeded.status(), await seeded.text()).toBe(200);
  const fixture = await seeded.json() as DriveFixture;
  expect(fixture.matter_id).toBe(matterId);
  expect(createHash("sha256").update(fixture.content).digest("hex")).toBe(fixture.sha256);

  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  const login = page.waitForResponse((response) =>
    new URL(response.url()).pathname === "/api/auth/login" && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  expect((await login).status()).toBe(200);
  await page.waitForURL(/\/app(?:[/?]|$)/);
  return fixture;
}

test("Drive browser emulator cannot activate in production or fetch other fixture bytes", async ({ baseURL }, testInfo) => {
  requireLoopback(apiBaseUrl);
  requireLoopback(baseURL!);
  const python = process.env.CASEOPS_E2E_PYTHON ?? path.join(
    repoRoot, "apps", "api", ".venv", process.platform === "win32" ? "Scripts" : "bin",
    process.platform === "win32" ? "python.exe" : "python",
  );
  const result = spawnSync(python, [
    "-m", "unittest", "discover", "-s", "tests/e2e/support/oauth",
    "-p", "test_drive_import_emulator.py", "-v",
  ], {
    cwd: repoRoot, encoding: "utf8", timeout: 60_000,
    env: {
      ...process.env,
      PYTHONPATH: [path.join(repoRoot, "apps", "api", "src"), process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
    },
  });
  const output = result.stdout + result.stderr;
  await testInfo.attach("drive-emulator-isolation", { body: output, contentType: "text/plain" });
  expect(result.error, output).toBeUndefined();
  expect(result.status, output).toBe(0);
  expect(output).toContain("Ran 7 tests");
});

for (const viewport of [{ width: 1280, height: 900 }, { width: 393, height: 851 }]) {
  test.describe("Reviewed Drive import at " + viewport.width + "px", () => {
    test.use({ viewport });
    test("Import publishes once, survives reload and downloads byte-identical Matter evidence", async ({ page, baseURL }, testInfo) => {
      requireLoopback(apiBaseUrl);
      requireLoopback(baseURL!);
      const fixture = await prepare(page);
      const reviewPath = "/api/drive/candidates/" + fixture.candidate_id;
      let mutationCount = 0;
      page.on("request", (request) => {
        if (new URL(request.url()).pathname === reviewPath && request.method() === "PATCH") mutationCount++;
      });
      await page.goto("/app/drive");
      await expect(page.getByRole("heading", { name: "Document review queue" })).toBeVisible();
      await expect(page.getByText(fixture.filename, { exact: true })).toBeVisible();
      const importButton = page.getByRole("button", { name: "Import", exact: true });
      await importButton.scrollIntoViewIfNeeded();
      await expect(importButton).toBeEnabled();
      const box = await importButton.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.width).toBeGreaterThan(40);
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width);
      const reviewed = page.waitForResponse((response) =>
        new URL(response.url()).pathname === reviewPath && response.request().method() === "PATCH",
      );
      await importButton.click();
      const response = await reviewed;
      expect(response.status(), await response.text()).toBe(200);
      expect(await response.request().headerValue("X-CaseOps-Automated-Test")).toBe("no-paid-providers");
      const result = await response.json();
      expect(result.candidate).toMatchObject({
        id: fixture.candidate_id, status: "content_imported", linked_matter_id: fixture.matter_id,
        imported_attachment_id: result.imported_attachment_id, last_error_redacted: null,
      });
      expect(result.imported_attachment_id).toEqual(expect.any(String));
      expect(result.imported_attachment_id).not.toBe("");
      await expect(page.getByText("content imported", { exact: true })).toBeVisible();
      await page.reload();
      await expect(page.getByText(fixture.filename, { exact: true })).toBeVisible();
      await expect(page.getByText("content imported", { exact: true })).toBeVisible();
      expect(mutationCount).toBe(1);
      const listed = await page.request.get(apiBaseUrl + "/api/drive/candidates");
      expect(listed.status()).toBe(200);
      const queue = await listed.json();
      expect(queue.candidates).toHaveLength(1);
      expect(queue.candidates[0]).toMatchObject({
        id: fixture.candidate_id, status: "content_imported", imported_attachment_id: result.imported_attachment_id,
      });
      const matter = await page.request.get(apiBaseUrl + "/api/matters/" + fixture.matter_id + "/workspace");
      expect(matter.status(), await matter.text()).toBe(200);
      const persisted = await matter.json();
      expect(persisted.attachments).toHaveLength(1);
      expect(persisted.attachments[0]).toMatchObject({
        id: result.imported_attachment_id, original_filename: fixture.filename,
        size_bytes: fixture.size_bytes, sha256_hex: fixture.sha256,
      });
      const download = await page.request.get(
        `${apiBaseUrl}/api/matters/${fixture.matter_id}/attachments/${result.imported_attachment_id}/download`,
      );
      expect(download.status(), await download.text()).toBe(200);
      const bytes = await download.body();
      expect(bytes.toString("utf8")).toBe(fixture.content);
      expect(createHash("sha256").update(bytes).digest("hex")).toBe(fixture.sha256);
      const evidence = await page.request.get(fixtureRoot + "/" + fixture.candidate_id);
      expect(evidence.status(), await evidence.text()).toBe(200);
      expect(await evidence.json()).toMatchObject({
        fetch_calls: 1, status: "content_imported", attachment_id: result.imported_attachment_id,
        attachment_sha256: fixture.sha256, job_count: 1, import_audit_count: 1,
      });
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
      await testInfo.attach("drive-imported-after-reload", {
        body: await page.screenshot({ fullPage: true }), contentType: "image/png",
      });
      await testInfo.attach("drive-import-persistence", { body: JSON.stringify({ fixture, result }), contentType: "application/json" });
    });

    test("Import 409 refreshes revoked consent and exposes Reconnect without reload", async ({ page, baseURL }, testInfo) => {
      requireLoopback(apiBaseUrl);
      requireLoopback(baseURL!);
      const fixture = await prepare(page, "reauthorization_required");
      await page.goto("/app/drive");
      const sync = page.getByRole("button", { name: "Sync Google Drive", exact: true });
      await expect(sync).toBeEnabled();
      await expect(page.getByText(fixture.filename, { exact: true })).toBeVisible();
      let mutationCount = 0;
      page.on("request", (request) => {
        if (new URL(request.url()).pathname === "/api/drive/candidates/" + fixture.candidate_id && request.method() === "PATCH") mutationCount++;
      });
      const refreshedStatus = page.waitForResponse((response) =>
        new URL(response.url()).pathname === "/api/drive/google/status" && response.request().method() === "GET",
      );
      const responsePromise = page.waitForResponse((response) =>
        new URL(response.url()).pathname === "/api/drive/candidates/" + fixture.candidate_id &&
        response.request().method() === "PATCH",
      );
      await page.getByRole("button", { name: "Import", exact: true }).click();
      const response = await responsePromise;
      expect(response.status(), await response.text()).toBe(409);
      expect(await response.request().headerValue("X-CaseOps-Automated-Test")).toBe("no-paid-providers");
      expect((await response.json()).detail).toContain("Reconnect");
      const statusResponse = await refreshedStatus;
      expect(statusResponse.status()).toBe(200);
      expect((await statusResponse.json()).connections).toEqual([
        expect.objectContaining({ id: fixture.connection_id, status: "error" }),
      ]);
      await expect(page).toHaveURL(/\/app\/drive$/);
      await expect(page.getByText("Google Drive authorization needs to be reconnected. Existing review items are retained.")).toBeVisible();
      const reconnect = page.getByRole("button", { name: "Reconnect Google Drive", exact: true });
      await reconnect.scrollIntoViewIfNeeded();
      await expect(reconnect).toBeVisible();
      await expect(reconnect).toBeEnabled();
      await expect(sync).toBeDisabled();
      expect(mutationCount).toBe(1);
      const evidence = await page.request.get(fixtureRoot + "/" + fixture.candidate_id);
      expect(evidence.status()).toBe(200);
      expect(await evidence.json()).toMatchObject({
        fetch_calls: 1, status: "new", attachment_id: null, job_count: 0, import_audit_count: 0,
      });
      await testInfo.attach("drive-import-reconnect-without-reload", {
        body: await page.screenshot({ fullPage: true }), contentType: "image/png",
      });
    });
  });
}
