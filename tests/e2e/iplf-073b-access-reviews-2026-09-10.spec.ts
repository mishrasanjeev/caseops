import { createHmac, randomUUID } from "node:crypto";
import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";
import { apiBaseUrl } from "./support/env";
import { noPaidProviderHeaders } from "./support/cost-controls";

const password = "SyntheticReviewProof2026!";
const title = "September independent access review";

function totp(secret: string) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const bits = [...secret].map((letter) => alphabet.indexOf(letter).toString(2).padStart(5, "0")).join("");
  const key = Buffer.from((bits.match(/.{8}/g) ?? []).map((byte) => parseInt(byte, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30_000)));
  const digest = createHmac("sha1", key).update(counter).digest();
  const offset = digest[digest.length - 1] & 15;
  return String((digest.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}

async function csrf(api: APIRequestContext) {
  const value = (await api.storageState()).cookies.find((cookie) => cookie.name === "caseops_csrf")?.value;
  expect(value).toBeTruthy();
  return { "X-CSRF-Token": value! };
}

async function enroll(api: APIRequestContext) {
  const headers = await csrf(api);
  const started = await api.post(`${apiBaseUrl}/api/auth/mfa/enroll`, { headers });
  expect(started.status(), await started.text()).toBe(200);
  const { secret } = await started.json();
  const verified = await api.post(`${apiBaseUrl}/api/auth/mfa/enroll/verify`, { headers, data: { code: totp(secret) } });
  expect(verified.status(), await verified.text()).toBe(200);
  return secret as string;
}

async function enter(page: Page, auth: Record<string, unknown>) {
  await page.addInitScript((context) => localStorage.setItem("caseops.session.context", JSON.stringify(context)), { company: auth.company, user: auth.user, membership: auth.membership, capabilities: auth.capabilities });
  await page.goto("/app/admin");
  await page.getByRole("link", { name: "Access reviews", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Access reviews", exact: true })).toBeVisible();
}

async function noErrors(page: Page) {
  await expect(page.locator('[role="alert"]:not(#__next-route-announcer__)')).toHaveCount(0);
}

async function verify(page: Page, secret: string) {
  await page.getByLabel("Authenticator code").fill(totp(secret));
  await page.getByRole("button", { name: "Verify identity" }).click();
  await expect(page.getByText("Identity verified for access changes.")).toBeVisible();
  await noErrors(page);
}

for (const kind of ["ip_docket", "matter"] as const) {
test(`IPLF-073 ${kind} independent review revokes through canonical owner and reloads`, async ({ browser }, testInfo) => {
  expect(new URL(apiBaseUrl).hostname).toBe("127.0.0.1");
  const slug = `review-${randomUUID().slice(0, 12)}`;
  const ownerApi = await request.newContext({ extraHTTPHeaders: noPaidProviderHeaders });
  const reviewerApi = await request.newContext({ extraHTTPHeaders: noPaidProviderHeaders });
  const bootstrap = await ownerApi.post(`${apiBaseUrl}/api/bootstrap/company`, { data: { company_name: "Synthetic Review Proof LLP", company_slug: slug, company_type: "law_firm", owner_full_name: "Review Owner", owner_email: `owner-${slug}@example.com`, owner_password: password } });
  expect(bootstrap.status(), await bootstrap.text()).toBe(200);
  const ownerAuth = await bootstrap.json();
  const created = await ownerApi.post(`${apiBaseUrl}/api/companies/current/users`, { headers: await csrf(ownerApi), data: { full_name: "Independent Reviewer", email: `reviewer-${slug}@example.com`, password, role: "admin" } });
  expect(created.status(), await created.text()).toBe(200);
  const login = await reviewerApi.post(`${apiBaseUrl}/api/auth/login`, { data: { company_slug: slug, email: `reviewer-${slug}@example.com`, password } });
  expect(login.status(), await login.text()).toBe(200);
  const reviewerAuth = await login.json();
  expect(reviewerAuth.user.id).not.toBe(ownerAuth.user.id);
  const ownerSecret = await enroll(ownerApi);
  const reviewerSecret = await enroll(reviewerApi);
  const step = await ownerApi.post(`${apiBaseUrl}/api/auth/mfa/step-up`, { headers: await csrf(ownerApi), data: { code: totp(ownerSecret), method: "totp", purpose: "record_access_change" } });
  expect(step.status(), await step.text()).toBe(200);
  const docketResult = kind === "ip_docket"
    ? await ownerApi.post(`${apiBaseUrl}/api/ip/dockets`, { headers: await csrf(ownerApi), data: { title: "Review target September", particulars: { form_key: "TM-A", form_version: "2026.1", mark_kind: "word", representation: { text: "REVIEW" }, classes: [{ class_number: 9, specification: "Downloadable software" }], parties: [{ role: "applicant", name: "Review Proof LLP" }], filing_manifest: [{ key: "representation", label: "Mark representation", required: true, evidence_reference: "fixture:review" }] } } })
    : await ownerApi.post(`${apiBaseUrl}/api/matters/`, { headers: await csrf(ownerApi), data: { title: "Review target September", matter_code: "SEPT-REVIEW", practice_area: "Intellectual Property", forum_level: "high_court", status: "active" } });
  expect(docketResult.status(), await docketResult.text()).toBe(kind === "ip_docket" ? 201 : 200);
  const docket = await docketResult.json();
  const accessUrl = kind === "ip_docket" ? `${apiBaseUrl}/api/ip/dockets/${docket.id}/access` : `${apiBaseUrl}/api/matters/${docket.id}/access`;
  if (kind === "ip_docket") {
  const panel = await (await ownerApi.get(accessUrl)).json();
  const grant = { action: "grant", subject_type: "membership", subject_id: ownerAuth.membership.id, expected_access_policy_version: panel.access_policy_version, reason: "Retained explicit owner grant" };
  const preview = await ownerApi.post(`${apiBaseUrl}/api/ip/dockets/${docket.id}/access/preview`, { headers: await csrf(ownerApi), data: grant });
  expect(preview.status(), await preview.text()).toBe(200);
  const applied = await ownerApi.post(`${apiBaseUrl}/api/ip/dockets/${docket.id}/access/apply`, { headers: await csrf(ownerApi), data: { ...grant, preview_token: (await preview.json()).preview_token } });
  expect(applied.status(), await applied.text()).toBe(200);
  } else {
    const granted = await ownerApi.post(`${accessUrl}/grants`, { headers: await csrf(ownerApi), data: { membership_id: ownerAuth.membership.id, reason: "Retained explicit owner grant" } });
    expect(granted.status(), await granted.text()).toBe(200);
  }
  const ownerContext = await browser.newContext({ storageState: await ownerApi.storageState(), extraHTTPHeaders: noPaidProviderHeaders });
  const reviewerContext = await browser.newContext({ storageState: await reviewerApi.storageState(), extraHTTPHeaders: noPaidProviderHeaders });
  try {
    for (const context of [ownerContext, reviewerContext]) await context.route("**/*", (route) => new URL(route.request().url()).hostname === "127.0.0.1" ? route.continue() : route.abort("blockedbyclient"));
    const owner = await ownerContext.newPage();
    const reviewer = await reviewerContext.newPage();
    await enter(owner, ownerAuth);
    await verify(owner, ownerSecret);
    await owner.getByLabel("Record type").selectOption(kind);
    await owner.getByLabel("Review target", { exact: true }).selectOption(docket.id);
    await expect(owner.getByText(/1 standing grants/)).toBeVisible();
    await owner.getByLabel("Campaign title").fill(title);
    await owner.getByLabel("Reason or ticket").fill("Periodic September access certification");
    await owner.getByRole("button", { name: "Open campaign" }).click();
    await expect(owner.getByText("Access review opened.")).toBeVisible();
    await expect(owner.getByRole("button", { name: "Record decision" })).toBeDisabled();
    await noErrors(owner);
    await enter(reviewer, reviewerAuth);
    await verify(reviewer, reviewerSecret);
    await reviewer.getByRole("button", { name: new RegExp(title) }).click();
    await reviewer.getByLabel("Decision", { exact: true }).selectOption("revoke");
    await reviewer.getByLabel("Decision reason").fill("Engagement ended; remove explicit grant");
    for (const width of [1280, 800, 768, 767, 390, 360]) {
      await reviewer.setViewportSize({ width, height: 900 });
      const input = reviewer.getByLabel("Decision reason");
      const action = reviewer.getByRole("button", { name: "Record decision" });
      await input.scrollIntoViewIfNeeded();
      await expect(input).toBeVisible();
      await expect(action).toBeVisible();
      const a = (await input.boundingBox())!;
      const b = (await action.boundingBox())!;
      expect(a.width).toBeGreaterThan(160);
      expect(a.x + a.width <= b.x || a.y + a.height <= b.y).toBeTruthy();
      expect(b.x + b.width).toBeLessThanOrEqual(width);
      if (width === 1280 || width === 360) await testInfo.attach(`access-review-${kind}-${width}`, { body: await reviewer.screenshot({ fullPage: true }), contentType: "image/png" });
    }
    await reviewer.getByRole("button", { name: "Record decision" }).click();
    await expect(reviewer.getByText("Independent decision recorded.")).toBeVisible();
    await expect(reviewer.getByRole("button", { name: "Finalize review" })).toBeDisabled();
    await noErrors(reviewer);
    await owner.reload();
    await owner.getByRole("button", { name: new RegExp(title) }).click();
    await expect(owner.getByText(/Decision: revoke/)).toBeVisible();
    await owner.getByRole("button", { name: "Finalize review" }).click();
    await expect(owner.getByText("Review finalized. Requested revocations applied.")).toBeVisible();
    await noErrors(owner);
    for (const page of [owner, reviewer]) {
      await page.reload();
      await page.getByRole("button", { name: new RegExp(title) }).click();
      await expect(page.getByText("Status: finalized. Version 3.")).toBeVisible();
      await expect(page.getByText(/Decision: revoke/)).toBeVisible();
      await noErrors(page);
    }
    const retained = await (await ownerApi.get(accessUrl)).json();
    if (kind === "ip_docket") {
      expect(retained.grants).toHaveLength(1);
      expect(retained.grants[0].revoked_at).toBeTruthy();
      expect(retained.grants[0].record_version).toBe(1);
    } else expect(retained.grants).toHaveLength(0);
    const campaigns = await (await ownerApi.get(`${apiBaseUrl}/api/access-reviews`)).json();
    const campaign = campaigns.campaigns[0];
    expect(campaign.status).toBe("finalized");
    expect(campaign.decisions[0].reviewer_user_id).toBe(reviewerAuth.user.id);
    const stale = await ownerApi.post(`${apiBaseUrl}/api/access-reviews/${campaign.id}/finalize`, { headers: await csrf(ownerApi), data: { expected_version: 2 } });
    expect(stale.status()).toBe(409);
  } finally {
    await ownerContext.close(); await reviewerContext.close(); await ownerApi.dispose(); await reviewerApi.dispose();
  }
});
}
