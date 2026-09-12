import { createHmac, randomUUID } from "node:crypto";
import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";
import { apiBaseUrl } from "./support/env";
import { noPaidProviderHeaders } from "./support/cost-controls";

const password = "SyntheticHoldProof2026!";
const holdTitle = "Synthetic preservation September 09";

// RFC 4226/6238 test credential only; matches the canonical service's SHA1/30s TOTP.
function totp(secret: string): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const bits = [...secret].map((letter) => alphabet.indexOf(letter).toString(2).padStart(5, "0")).join("");
  const key = Buffer.from((bits.match(/.{8}/g) ?? []).map((byte) => parseInt(byte, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30_000)));
  const digest = createHmac("sha1", key).update(counter).digest();
  const offset = digest[digest.length - 1] & 15;
  return String((digest.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}

async function enroll(api: APIRequestContext, token: string): Promise<string> {
  const headers = { Authorization: `Bearer ${token}` };
  const started = await api.post(`${apiBaseUrl}/api/auth/mfa/enroll`, { headers });
  expect(started.status()).toBe(200);
  const { secret } = await started.json();
  const verified = await api.post(`${apiBaseUrl}/api/auth/mfa/enroll/verify`, { headers, data: { code: totp(secret) } });
  expect(verified.status()).toBe(200);
  return secret;
}

async function verify(page: Page, secret: string) {
  await page.getByLabel("Authenticator code").fill(totp(secret));
  await page.getByRole("button", { name: "Verify identity" }).click();
  await expect(page.getByText("Identity verified for preservation changes.")).toBeVisible();
  await noApplicationErrors(page);
}

async function noApplicationErrors(page: Page) {
  // Next's clipped accessibility route announcer is not application error feedback.
  await expect(page.locator('[role="alert"]:not(#__next-route-announcer__)')).toHaveCount(0);
}

async function enter(page: Page, auth: Record<string, unknown>) {
  expect((await page.request.get(`${apiBaseUrl}/api/health`)).status()).toBe(200);
  await page.addInitScript((context) => {
    localStorage.setItem("caseops.session.context", JSON.stringify(context));
  }, { company: auth.company, user: auth.user, membership: auth.membership, capabilities: auth.capabilities });
  await page.goto("/app/admin/data-governance/holds");
  await expect(page.getByRole("heading", { name: "Legal holds", exact: true })).toBeVisible();
}

test("IPLF-028B owner requests and independent administrator preserves/releases without deletion", async ({ browser }, testInfo) => {
  expect(new URL(apiBaseUrl).hostname).toBe("127.0.0.1");
  const slug = `holds-${randomUUID().slice(0, 12)}`;
  const ownerApi = await request.newContext({ extraHTTPHeaders: noPaidProviderHeaders });
  const reviewerApi = await request.newContext({ extraHTTPHeaders: noPaidProviderHeaders });
  const bootstrap = await ownerApi.post(`${apiBaseUrl}/api/bootstrap/company`, { data: {
    company_name: "Synthetic Hold Proof LLP", company_slug: slug, company_type: "law_firm",
    owner_full_name: "Preservation Owner", owner_email: `owner-${slug}@example.com`, owner_password: password,
  } });
  expect(bootstrap.status()).toBe(200);
  const ownerAuth = await bootstrap.json();
  const user = await ownerApi.post(`${apiBaseUrl}/api/companies/current/users`, { headers: { Authorization: `Bearer ${ownerAuth.access_token}` }, data: {
    full_name: "Preservation Reviewer", email: `reviewer-${slug}@example.com`, password, role: "admin",
  } });
  expect(user.status()).toBe(200);
  const login = await reviewerApi.post(`${apiBaseUrl}/api/auth/login`, { data: {
    company_slug: slug, email: `reviewer-${slug}@example.com`, password,
  } });
  expect(login.status()).toBe(200);
  const reviewerAuth = await login.json();
  expect(reviewerAuth.user.id).not.toBe(ownerAuth.user.id);
  expect((await reviewerApi.get(`${apiBaseUrl}/api/admin/data-governance/operations/dry-runs`)).status()).toBe(403);
  const ownerSecret = await enroll(ownerApi, ownerAuth.access_token);
  const reviewerSecret = await enroll(reviewerApi, reviewerAuth.access_token);
  const ownerContext = await browser.newContext({ storageState: await ownerApi.storageState(), extraHTTPHeaders: noPaidProviderHeaders });
  const reviewerContext = await browser.newContext({ storageState: await reviewerApi.storageState(), extraHTTPHeaders: noPaidProviderHeaders });
  try {
    for (const context of [ownerContext, reviewerContext]) {
      await context.route("**/*", (route) => new URL(route.request().url()).hostname === "127.0.0.1" ? route.continue() : route.abort("blockedbyclient"));
    }
    const owner = await ownerContext.newPage();
    const reviewer = await reviewerContext.newPage();
    await enter(owner, ownerAuth);
    await verify(owner, ownerSecret);
    await owner.getByLabel("Title", { exact: true }).fill(holdTitle);
    await owner.getByLabel("Authority reference", { exact: true }).fill("fixture://preservation-authority");
    await owner.getByLabel("Preservation scope").selectOption("tenant_data_operations");
    await owner.getByRole("button", { name: "Record draft" }).click();
    await expect(owner.getByText("Preservation draft recorded.")).toBeVisible();
    await noApplicationErrors(owner);
    await expect(owner.getByRole("button", { name: "Approve preservation" })).toBeDisabled();
    await enter(reviewer, reviewerAuth);
    await expect(reviewer.getByRole("button", { name: "Record draft" })).toHaveCount(0);
    await verify(reviewer, reviewerSecret);
    await reviewer.getByRole("button", { name: "Approve preservation" }).click();
    await expect(reviewer.getByText("Preservation is active.")).toBeVisible();
    await noApplicationErrors(reviewer);
    await owner.reload();
    await owner.getByRole("button", { name: `${holdTitle}: active` }).click();
    await owner.getByLabel("Release authority reference").fill("fixture://release-authority");
    for (const width of [1280, 800, 768, 767, 390, 360]) {
      await owner.setViewportSize({ width, height: 900 });
      const input = owner.getByLabel("Release authority reference");
      const action = owner.getByRole("button", { name: "Request release" });
      await expect(input).toBeVisible();
      await expect(action).toBeVisible();
      const a = await input.boundingBox();
      const b = await action.boundingBox();
      expect(a!.width).toBeGreaterThan(160);
      expect(b!.x + b!.width).toBeLessThanOrEqual(width);
      expect(a!.x + a!.width <= b!.x || a!.y + a!.height <= b!.y).toBeTruthy();
      if (width === 1280 || width === 360) await testInfo.attach(`legal-hold-${width}`, {
        body: await owner.screenshot({ fullPage: true }), contentType: "image/png",
      });
    }
    await owner.getByRole("button", { name: "Request release" }).click();
    await expect(owner.getByText("Release request recorded. Preservation remains active.")).toBeVisible();
    await expect(owner.getByRole("button", { name: "Approve release" })).toBeDisabled();
    await noApplicationErrors(owner);
    const activeHolds = await ownerApi.get(`${apiBaseUrl}/api/admin/data-governance/holds`);
    const activeHold = (await activeHolds.json()).holds.find((hold: { title: string }) => hold.title === holdTitle);
    const releaseUrl = `${apiBaseUrl}/api/admin/data-governance/holds/${activeHold.id}/release-requests`;
    const firstRequests = await ownerApi.get(releaseUrl);
    const firstProposal = (await firstRequests.json()).proposals[0];
    const csrf = (await ownerApi.storageState()).cookies.find((cookie) => cookie.name === "caseops_csrf");
    expect(csrf?.value).toBeTruthy();
    const mutationHeaders = { "X-CSRF-Token": csrf!.value };
    for (let index = 0; index < 25; index++) {
      const extra = await ownerApi.post(releaseUrl, { headers: mutationHeaders, data: {
        idempotency_key: randomUUID(), expected_updated_at: activeHold.updated_at,
        dry_run_id: firstProposal.dry_run_id, reason_reference: `fixture://extra-release-${index}`,
      } });
      expect(extra.status(), await extra.text()).toBe(201);
    }
    await reviewer.reload();
    await reviewer.getByRole("button", { name: `${holdTitle}: active` }).click();
    await expect(reviewer.getByRole("button", { name: "Older release requests" })).toBeEnabled();
    await reviewer.getByRole("button", { name: "Older release requests" }).click();
    await expect(reviewer.getByText("fixture://release-authority", { exact: true })).toBeVisible();
    await expect(reviewer.getByRole("button", { name: "Older release requests" })).toBeDisabled();
    await reviewer.getByRole("button", { name: "Approve release" }).click();
    await expect(reviewer.getByText("Hold released. No records were deleted.")).toBeVisible();
    await noApplicationErrors(reviewer);
    for (const page of [owner, reviewer]) {
      await page.reload();
      await expect(page.getByRole("button", { name: `${holdTitle}: released` })).toBeVisible();
    }
    const manifests = await ownerApi.get(`${apiBaseUrl}/api/admin/data-governance/operations/dry-runs`);
    expect(manifests.status()).toBe(200);
    const holds = await ownerApi.get(`${apiBaseUrl}/api/admin/data-governance/holds`);
    expect((await holds.json()).holds).toEqual([expect.objectContaining({ title: holdTitle, status: "released" })]);
    for (let index = 0; index < 26; index++) {
      const extra = await ownerApi.post(`${apiBaseUrl}/api/admin/data-governance/holds`, { headers: mutationHeaders, data: {
        idempotency_key: randomUUID(), title: `Synthetic continuation ${index}`,
        authority_reference: "fixture://continuation", scope: "data_classes", data_class_ids: ["legal_holds"],
      } });
      expect(extra.status(), await extra.text()).toBe(201);
    }
    await owner.reload();
    await expect(owner.getByRole("button", { name: `${holdTitle}: released` })).toHaveCount(0);
    await owner.getByRole("button", { name: "Older holds" }).click();
    await expect(owner.getByRole("button", { name: `${holdTitle}: released` })).toBeVisible();
    await expect(owner.getByRole("button", { name: "Older holds" })).toBeDisabled();
    for (const width of [1280, 768, 767, 390, 360]) {
      await owner.setViewportSize({ width, height: 900 });
      for (const name of ["Newer holds", "Older holds"]) {
        const control = owner.getByRole("button", { name, exact: true });
        await expect(control).toBeVisible();
        const box = (await control.boundingBox())!;
        expect(box.width).toBeGreaterThan(24);
        expect(box.x).toBeGreaterThanOrEqual(0);
        expect(box.x + box.width).toBeLessThanOrEqual(width);
      }
      if (width === 360 || width === 1280) await testInfo.attach(`legal-hold-pages-${width}`, {
        body: await owner.screenshot({ fullPage: true }), contentType: "image/png",
      });
    }
    await owner.getByRole("button", { name: "Newer holds" }).click();
    await expect(owner.getByRole("button", { name: "Synthetic continuation 25: draft" })).toBeVisible();
    await owner.reload();
    await expect(owner.getByRole("button", { name: "Synthetic continuation 25: draft" })).toBeVisible();
    await noApplicationErrors(owner);
  } finally {
    await ownerContext.close(); await reviewerContext.close();
    await ownerApi.dispose(); await reviewerApi.dispose();
  }
});
