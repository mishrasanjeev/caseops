import { test, expect, type Locator, type Page, type TestInfo } from "@playwright/test";
import { startNativeMfaHttpFixture, mfaFixtureIdentity, mfaFixtureQuery, type MfaFixtureMode } from "./native-mfa-http-fixture";

async function withMfaFixture(page: Page, baseURL: string, mode: MfaFixtureMode, action: (fixture: Awaited<ReturnType<typeof startNativeMfaHttpFixture>>) => Promise<void>) {
  const fixture = await startNativeMfaHttpFixture(process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000", baseURL, mode);
  let failed = false, original: unknown;
  try { await action(fixture); expect(fixture.failures).toEqual([]); }
  catch (error) { failed = true; original = error; }
  let closeFailed = false, closeError: unknown;
  try { await fixture.stop(); } catch (error) { closeFailed = true; closeError = error; }
  if (failed && closeFailed) throw new AggregateError([original, closeError], "MFA_BROWSER_BODY_AND_OWNED_FIXTURE_CLOSE");
  if (failed) throw original;
  if (closeFailed) throw closeError;
}

async function openChallenge(page: Page, testInfo: TestInfo) {
  if (testInfo.project.use.isMobile) await page.setViewportSize({ width: 360, height: 640 });
  await page.goto(`/native/sign-in?${mfaFixtureQuery}`);
  const connect = page.getByRole("button", { name: "Connect app", exact: true });
  await expect(connect).toBeEnabled();
  if (testInfo.project.use.hasTouch) await connect.tap(); else await connect.click();
}

async function visibleTarget(page: Page, target: Locator) {
  await expect(target).toBeVisible();
  const box = await target.boundingBox();
  expect(box).not.toBeNull(); expect(box!.height).toBeGreaterThanOrEqual(44);
  expect(box!.x).toBeGreaterThanOrEqual(0); expect(box!.y).toBeGreaterThanOrEqual(0);
  const viewport = page.viewportSize()!;
  expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width);
  expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
}

test("MOB-WEB-05 MFA verification continues the displayed account connection once", async ({ page, baseURL }, testInfo) => {
  await withMfaFixture(page, baseURL!, "verified", async fixture => {
    await openChallenge(page, testInfo);
    const code = page.getByLabel("Six-digit code", { exact: true });
    await expect(code).toBeEnabled(); await expect(code).toBeFocused();
    await visibleTarget(page, code);
    await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
    await expect(page.getByRole("status")).toHaveText(/Verify and continue connects this account to CaseOps/);
    const verify = page.getByRole("button", { name: "Verify and continue", exact: true });
    await expect(verify).toBeDisabled(); // Empty code is correctly non-interactive.
    await code.fill("123456");
    await expect(verify).toBeEnabled(); await visibleTarget(page, verify);
    expect(await verify.evaluate(element => {
      const r = element.getBoundingClientRect(), hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
      return !!hit && (hit === element || element.contains(hit));
    })).toBe(true);
    if (testInfo.project.use.hasTouch) await verify.tap(); else await verify.click();
    const open = page.getByRole("button", { name: "Open CaseOps", exact: true });
    await expect(open).toBeEnabled(); await expect(open).toBeFocused(); await visibleTarget(page, open);
    await expect(open).toHaveAccessibleDescription("Sign-in is ready. Open CaseOps to finish.");
    await expect(page.getByRole("button", { name: "Connect app", exact: true })).toHaveCount(0);
    expect(fixture.requests.map(({ method, route, status }) => ({ method, route, status }))).toEqual([
      { method: "GET", route: "/api/auth/me", status: 200 },
      { method: "POST", route: "/api/auth/native/authorize", status: 403 },
      { method: "POST", route: "/api/auth/mfa/step-up", status: 200 },
      { method: "GET", route: "/api/auth/me", status: 200 },
      { method: "POST", route: "/api/auth/native/authorize", status: 200 },
    ]);
    // Do not launch an OS app in this browser-only contract. The final gesture
    // remains separate, with no callback/code in DOM, storage or navigation.
    expect(new URL(page.url()).pathname).toBe("/native/sign-in");
    expect(await page.content()).not.toContain("c".repeat(43));
    expect(await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }))).not.toContain("c".repeat(43));
    expect(fixture.requests.every(row => row.markerVerified && !row.authorizationHeaderPresent)).toBe(true);
  });
});

test("MOB-WEB-06 a rejected verification code never grants an app connection", async ({ page, baseURL }, testInfo) => {
  await withMfaFixture(page, baseURL!, "rejected-code", async fixture => {
    await openChallenge(page, testInfo);
    const code = page.getByLabel("Six-digit code", { exact: true });
    await expect(code).toBeEnabled(); await expect(code).toBeFocused(); await code.fill("123456");
    const verify = page.getByRole("button", { name: "Verify and continue", exact: true });
    if (testInfo.project.use.hasTouch) await verify.tap(); else await verify.click();
    await expect(page.getByRole("main").getByRole("alert")).toHaveText("The code was not accepted.");
    await expect(code).toHaveValue(""); await expect(code).toBeEnabled(); await expect(code).toBeFocused();
    await expect(page.getByRole("button", { name: "Open CaseOps", exact: true })).toHaveCount(0);
    expect(fixture.requests.filter(row => row.route === "/api/auth/native/authorize")).toHaveLength(1);
    expect(fixture.requests.filter(row => row.route === "/api/auth/mfa/step-up")).toHaveLength(1);
  });
});

test("MOB-WEB-07 an expired native browser session is not refreshed or replayed", async ({ page, baseURL }, testInfo) => {
  // This public context makes the ordinary client's refresh precondition true;
  // no token/credential is fabricated or stored. Only nativeauthorize must opt out.
  await page.addInitScript(identity => localStorage.setItem("caseops.session.context", JSON.stringify(identity)), mfaFixtureIdentity);
  await withMfaFixture(page, baseURL!, "expired-session", async fixture => {
    await openChallenge(page, testInfo);
    await page.waitForURL(url => url.pathname === "/sign-in");
    expect(new URL(page.url()).searchParams.get("next")).toBe(`/native/sign-in?${mfaFixtureQuery}`);
    await expect(page.getByText(mfaFixtureIdentity.user.email, { exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Connect app", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Open CaseOps", exact: true })).toHaveCount(0);
    expect(fixture.requests.filter(row => row.route === "/api/auth/native/authorize")).toHaveLength(1);
    expect(fixture.requests.filter(row => row.route === "/api/auth/refresh")).toEqual([]);
    expect(fixture.requests.every(row => row.markerVerified && !row.authorizationHeaderPresent)).toBe(true);
  });
});
