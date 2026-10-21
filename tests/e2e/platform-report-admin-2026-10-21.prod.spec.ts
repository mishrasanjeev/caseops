/** Fake-state renderer contracts, never real owner setup/MFA or report-access acceptance. */
import { expect, test } from "./support/prod-diagnostic-test";
import { noPaidProviderHeaders } from "./support/cost-controls";
import { e2eEnv } from "./support/env";
import { CONSOLE, CSRF_COOKIE, CSRF_HEADER, assertRelease, controlBounds, noOverflow, origins, totp,
  type ConsoleAuth, type Origins } from "./support/platform-report-admin";
import { AUTHENTICATOR_QR_LABEL, renderedTotpSecret } from "./support/platform-report-qr";
import type { BrowserContext } from "@playwright/test";

test.use({ storageState: { cookies: [], origins: [] }, extraHTTPHeaders: noPaidProviderHeaders,
  trace: "off", screenshot: "off", video: "off", serviceWorkers: "block" });
test.describe.configure({ retries: 0, mode: "default" });

const fakeAccount = { id: "00000000-0000-4000-8000-000000000021", email: "qr-renderer@example.com",
  full_name: "Local QR renderer fixture", role: "manager" as const };
// Public, synthetic test material only; no real user's factor or session is used.
const fakeSecret = "JBSWY3DPEHPK3PXP";
const fakeCsrf = "qr-renderer-only-csrf";
const enrollment = { secret: fakeSecret, otpauth_url: `otpauth://totp/${encodeURIComponent(`CaseOps Reports:${fakeAccount.email}`)}`
  + `?secret=${fakeSecret}&issuer=CaseOps%20Reports&algorithm=SHA1&digits=6&period=30` };

async function mockConsole(context: BrowserContext, target: Origins, initial: ConsoleAuth["state"] | "anonymous") {
  let state = initial;
  const calls = { enroll: 0, verify: 0, refused: 0, external: 0, expectedCode: "" };
  const auth = (): ConsoleAuth => ({ state: state === "anonymous" ? "mfa_challenge_required" : state,
    admin: state === "authenticated" ? fakeAccount : null, expires_at: "2099-01-01T00:00:00Z" });
  await context.addCookies([{ name: CSRF_COOKIE, value: fakeCsrf, url: target.web.origin, sameSite: "Lax" }]);
  await context.route("**/*", async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (![target.web.origin, target.api.origin].includes(url.origin)) {
      calls.external++; await route.abort("blockedbyclient"); return;
    }
    const headers = { "access-control-allow-origin": target.web.origin, "access-control-allow-credentials": "true",
      "access-control-allow-headers": `Content-Type, ${CSRF_HEADER}, X-CaseOps-Automated-Test`, "access-control-allow-methods": "GET, POST, OPTIONS" };
    if (url.origin === target.api.origin && url.pathname.startsWith(`${CONSOLE}/`)) {
      if (request.method() === "OPTIONS") { await route.fulfill({ status: 204, headers }); return; }
      if (request.method() === "GET" && url.pathname === `${CONSOLE}/auth/session`) {
        await route.fulfill({ status: state === "anonymous" ? 401 : 200, headers,
          json: state === "anonymous" ? { detail: "Authentication required." } : auth() }); return;
      }
      if (request.method() === "POST" && state === "mfa_enrollment_required"
        && request.headers()[CSRF_HEADER.toLowerCase()] === fakeCsrf) {
        if (url.pathname === `${CONSOLE}/auth/mfa/enroll`) {
          calls.enroll++; expect(request.postDataJSON()).toEqual({});
          await route.fulfill({ status: 200, headers, json: enrollment }); return;
        }
        if (url.pathname === `${CONSOLE}/auth/mfa/verify` && calls.enroll === 1) {
          const body = request.postDataJSON();
          expect(Object.keys(body)).toEqual(["code"]);
          expect(Boolean(calls.expectedCode && body.code === calls.expectedCode), "Only the decoded synthetic factor is accepted.").toBe(true);
          calls.verify++; state = "authenticated";
          await route.fulfill({ status: 200, headers, json: { ...auth(), recovery_codes: ["LOCAL-ONLY-RECOVERY-1", "LOCAL-ONLY-RECOVERY-2"] } }); return;
        }
      }
      calls.refused++; await route.abort("blockedbyclient"); return;
    }
    if (url.origin === target.web.origin && ["GET", "HEAD"].includes(request.method())) {
      await route.continue(); return;
    }
    calls.refused++; await route.abort("blockedbyclient");
  });
  return { calls, setState(next: ConsoleAuth["state"] | "anonymous") { state = next; } };
}

for (const width of [1280, 393]) {
  test(`PRA-09 QR renderer component contract ${width}px decodes pixels and removes enrollment after mocked verification`, async ({ page, context, baseURL }, info) => {
    info.annotations.push({ type: "scope", description: "Synthetic renderer contract only; no real owner acceptance or API mutation." });
    const target = origins(baseURL, false, e2eEnv.CASEOPS_RELEASE_SHA);
    if (!target.local) await assertRelease(target);
    const mocked = await mockConsole(context, target, "anonymous");
    const { calls } = mocked;
    await page.setViewportSize({ width, height: 900 });
    for (const state of ["anonymous", "mfa_challenge_required"] as const) {
      mocked.setState(state);
      await page.goto(`${target.web.origin}/platform/security`);
      if (state === "anonymous") await expect(page.getByText("Sign in to manage your platform account.", { exact: true })).toBeVisible();
      else await expect(page.getByRole("heading", { name: "Verify multi-factor authentication", exact: true })).toBeVisible();
      await expect(page.getByRole("img", { name: AUTHENTICATOR_QR_LABEL, exact: true })).toHaveCount(0);
      await expect(page.getByLabel("Authenticator setup key", { exact: true })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Set up authenticator", exact: true })).toHaveCount(0);
      await expect(page.getByRole("link", { name: "Administrators", exact: true })).toHaveCount(0);
      await noOverflow(page);
      expect(calls).toEqual({ enroll: 0, verify: 0, refused: 0, external: 0, expectedCode: "" });
    }
    mocked.setState("mfa_enrollment_required");
    await page.goto(`${target.web.origin}/platform/security`);
    const qr = page.getByRole("img", { name: AUTHENTICATOR_QR_LABEL, exact: true });
    await expect(page.getByRole("button", { name: "Set up authenticator", exact: true })).toBeVisible();
    await expect(qr).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Administrators", exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Set up authenticator", exact: true }).click();
    const decoded = await renderedTotpSecret(page, enrollment, fakeAccount.email);
    await controlBounds(qr, page);
    await noOverflow(page);
    const setupKey = page.getByLabel("Authenticator setup key", { exact: true });
    await expect(setupKey).toHaveAttribute("readonly", "");
    expect(await setupKey.inputValue() === decoded, "Manual fallback must match decoded synthetic QR.").toBe(true);
    calls.expectedCode = totp(decoded);
    await page.getByLabel("Six-digit code", { exact: true }).fill(calls.expectedCode);
    await page.getByRole("button", { name: "Verify MFA", exact: true }).click();
    await expect(page.getByRole("heading", { name: "MFA verified", exact: true })).toBeVisible();
    await expect(qr).toHaveCount(0);
    await expect(setupKey).toHaveCount(0);
    expect((await page.content()).includes(fakeSecret), "Enrollment secret must leave the rendered document after success.").toBe(false);
    expect(calls).toEqual({ enroll: 1, verify: 1, refused: 0, external: 0, expectedCode: calls.expectedCode });
    if (!target.local) await assertRelease(target);
  });
}
