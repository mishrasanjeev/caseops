import assert from 'node:assert/strict';
import { click, find, read, selector, visible } from './native-ui.mjs';
import { firefoxLogin } from './firefox-handoff.mjs';
import { fixtureMfaCode } from './mfa.mjs';

export function browserOrigin(value) {
  const url = new URL(value);
  assert.ok(['127.0.0.1', 'localhost', '[::1]', '10.0.2.2'].includes(url.hostname), 'ISOLATED_BROWSER_ORIGIN_REQUIRED');
  assert.equal(url.protocol, 'https:', 'REAL_TLS_BROWSER_REQUIRED');
  assert.ok(url.pathname === '/' && !url.username && !url.password && !url.search && !url.hash, 'CLEAN_BROWSER_ORIGIN_REQUIRED');
  return url.origin;
}

export function authorizationIdentity(value, origin, platform) {
  const url = new URL(value);
  assert.equal(url.origin, browserOrigin(origin), 'UNSAFE_BROWSER_ORIGIN');
  assert.ok(!url.hash && !url.username && !url.password, 'UNSAFE_BROWSER_LOCATION');
  if (url.pathname === '/sign-in') {
    assert.deepEqual([...url.searchParams.keys()], ['next'], 'UNEXPECTED_BROWSER_LOGIN_QUERY');
    const next = url.searchParams.get('next');
    assert.ok(next?.startsWith('/native/sign-in?'), 'NATIVE_LOGIN_RETURN_REQUIRED');
    return authorizationIdentity(new URL(next, url.origin).href, origin, platform);
  }
  assert.equal(url.pathname, '/native/sign-in', 'UNEXPECTED_BROWSER_AUTH_PAGE');
  const keys = ['code_challenge', 'state', 'platform', 'redirect_uri'];
  assert.deepEqual([...url.searchParams.keys()].sort(), [...keys].sort(), 'INVALID_BROWSER_PKCE_QUERY');
  for (const key of keys) assert.equal(url.searchParams.getAll(key).length, 1, 'DUPLICATE_BROWSER_PKCE_PARAMETER');
  assert.match(url.searchParams.get('code_challenge'), /^[A-Za-z0-9_-]{43}$/, 'INVALID_BROWSER_PKCE_CHALLENGE');
  assert.match(url.searchParams.get('state'), /^[A-Za-z0-9._~-]{16,256}$/, 'INVALID_BROWSER_PKCE_STATE');
  assert.equal(url.searchParams.get('platform'), platform, 'WRONG_BROWSER_PLATFORM');
  assert.equal(url.searchParams.get('redirect_uri'), 'caseops://oauth/callback', 'WRONG_BROWSER_CALLBACK');
  return Object.fromEntries(keys.map((key) => [key, url.searchParams.get(key)]));
}

export function loginCredentials(auth, environment = process.env) {
  for (const key of ['emailEnv', 'passwordEnv']) assert.match(auth?.[key] || '', /^CASEOPS_MOBILE_[A-Z0-9_]+$/, 'CREDENTIAL_ENV_NAME_REQUIRED');
  const email = environment[auth.emailEnv], password = environment[auth.passwordEnv];
  assert.ok(email && password && email.length <= 320 && password.length <= 1024, 'BROWSER_CREDENTIALS_MISSING');
  assert.match(auth.companySlug, /^[a-z0-9-]{2,80}$/, 'FIXTURE_WORKSPACE_SLUG_REQUIRED');
  return { email, password, companySlug: auth.companySlug };
}

async function dom(driver, css) {
  const elements = await driver.$$(css);
  const displayed = [];
  for (const element of elements) if (await element.isDisplayed()) displayed.push(element);
  assert.equal(displayed.length, 1, 'BROWSER_CONTROL_NOT_UNIQUE');
  return displayed[0];
}

async function attachBrowser(context) {
  const { driver, fixture, platform } = context;
  let selected;
  await driver.waitUntil(async () => {
    const candidates = [];
    const contexts = await driver.getContexts();
    assert.ok(contexts.length <= 8, 'SYSTEM_BROWSER_CONTEXT_BOUND');
    for (const entry of contexts) {
      const name = typeof entry === 'string' ? entry : entry.id;
      if (!name || name === 'NATIVE_APP' || (fixture.auth.context && name !== fixture.auth.context)) continue;
      await driver.switchContext(name);
      // Inspect only location, never cookies, storage, source HTML or callback codes.
      const handles = await driver.getWindowHandles();
      assert.ok(handles.length <= 8, 'SYSTEM_BROWSER_WINDOW_BOUND');
      for (const handle of handles) {
        await driver.switchToWindow(handle);
        const url = new URL(await driver.getUrl());
        if (url.origin === browserOrigin(fixture.auth.webOrigin) && ['/native/sign-in', '/sign-in'].includes(url.pathname)) {
          authorizationIdentity(url.href, fixture.auth.webOrigin, platform);
          candidates.push({ name, handle });
        }
      }
    }
    assert.ok(candidates.length <= 1, 'AMBIGUOUS_SYSTEM_BROWSER');
    selected = candidates[0];
    if (!selected) await driver.switchContext('NATIVE_APP');
    return !!selected;
  }, { timeout: 20000, interval: 500, timeoutMsg: 'SYSTEM_BROWSER_CONTEXT_UNAVAILABLE' });
  await driver.switchContext(selected.name);
  await driver.switchToWindow(selected.handle);
}

export async function browserLogin(context) {
  const { driver, fixture, platform } = context;
  const credentials = loginCredentials(fixture.auth);
  browserOrigin(fixture.auth.webOrigin);
  await click(context, 'id', 'sign-in');
  if (fixture.auth.mode === 'native-firefox') {
    await firefoxLogin(context, credentials, authorizationIdentity);
    context.record?.({ type: 'assertion', boundary: 'system-browser-ui-pkce-completed', platform, browser: 'firefox-native' });
    return;
  }
  let handoff;
  try {
    // iOS's ASWebAuthenticationSession consent is opt-in and exact, not accept-any-alert.
    if (platform === 'ios' && fixture.auth.iosConsent === true) {
      await driver.waitUntil(async () => {
        try { await driver.getAlertText(); return true; }
        catch (error) { if (/no such alert|no alert/i.test(error.message)) return false; throw error; }
      }, { timeout: 5000, interval: 200 });
      const buttons = await driver.execute('mobile: alert', { action: 'getButtons' });
      assert.ok(buttons.includes('Continue'), 'IOS_AUTH_CONSENT_NOT_RECOGNIZED');
      await driver.execute('mobile: alert', { action: 'accept', buttonLabel: 'Continue' });
    }
    await attachBrowser(context);
    handoff = authorizationIdentity(await driver.getUrl(), fixture.auth.webOrigin, platform);
    const another = await driver.$$('a[href^="/sign-in?next="]');
    for (const element of another) if (await element.isDisplayed()) await element.click();
    await driver.waitUntil(async () => (await driver.$$('#company-slug')).length === 1,
      { timeout: 10000, interval: 200, timeoutMsg: 'REAL_BROWSER_LOGIN_FORM_REQUIRED' });
    assert.deepEqual(authorizationIdentity(await driver.getUrl(), fixture.auth.webOrigin, platform), handoff, 'BROWSER_HANDOFF_CHANGED');
    await (await dom(driver, '#company-slug')).setValue(credentials.companySlug);
    await (await dom(driver, '#email')).setValue(credentials.email);
    await (await dom(driver, '#password')).setValue(credentials.password);
    await (await dom(driver, 'form[aria-label="Sign in"] button[type="submit"]')).click();
    await driver.waitUntil(async () => (await driver.$$('#mfa-code')).length === 1 || (await driver.$$('main dl dd')).length === 2,
      { timeout: 15000, interval: 250, timeoutMsg: 'BROWSER_LOGIN_NOT_ACKNOWLEDGED' });
    if ((await driver.$$('#mfa-code')).length === 1) {
      assert.deepEqual(authorizationIdentity(await driver.getUrl(), fixture.auth.webOrigin, platform), handoff, 'BROWSER_HANDOFF_CHANGED');
      await (await dom(driver, '#mfa-code')).setValue(fixtureMfaCode(fixture.auth));
      await (await dom(driver, 'form[aria-label="MFA challenge"] button[type="submit"]')).click();
    } else assert.notEqual(fixture.auth.mfaRequired, true, 'REQUIRED_BROWSER_MFA_NOT_EXERCISED');
    await driver.waitUntil(async () => {
      const current = new URL(await driver.getUrl());
      assert.equal(current.origin, browserOrigin(fixture.auth.webOrigin), 'UNSAFE_BROWSER_ORIGIN');
      return current.pathname === '/native/sign-in' && (await driver.$$('main dl dd')).length === 2;
    }, { timeout: 15000, interval: 250, timeoutMsg: 'BROWSER_LOGIN_OR_MFA_NOT_COMPLETED' });
    assert.deepEqual(authorizationIdentity(await driver.getUrl(), fixture.auth.webOrigin, platform), handoff, 'BROWSER_HANDOFF_CHANGED');
    const facts = await driver.$$('main dl dd');
    const normalize = (text) => text.replace(/\s+/g, ' ').trim();
    assert.equal(normalize(await facts[0].getText()), normalize(`${fixture.principalLabel} ${credentials.email}`), 'WRONG_BROWSER_PRINCIPAL');
    assert.equal(normalize(await facts[1].getText()), normalize(`${fixture.workspaceLabel} / ${credentials.companySlug}`), 'WRONG_BROWSER_WORKSPACE');
    const connect = await dom(driver, 'main button');
    assert.equal((await connect.getText()).trim(), 'Connect app', 'REAL_CONNECT_CONTROL_REQUIRED');
    await connect.click();
  } finally {
    await driver.switchContext('NATIVE_APP');
  }
  await find(context, 'id', 'account-open');
  context.record?.({ type: 'assertion', boundary: 'system-browser-ui-pkce-completed', platform });
}

export async function authenticate(context, { fresh = false } = {}) {
  const { driver, fixture, platform } = context;
  await driver.switchContext('NATIVE_APP');
  await driver.waitUntil(async () => !!(await visible(driver, selector(platform, 'id', 'account-open')))
    || !!(await visible(driver, selector(platform, 'id', 'sign-in'))),
  { timeout: 20000, interval: 200, timeoutMsg: 'NATIVE_SESSION_NOT_READY' });
  if (fresh && await visible(driver, selector(platform, 'id', 'account-open'))) {
    await click(context, 'id', 'account-open');
    await click(context, 'id', 'sign-out', { scroll: true });
    await find(context, 'id', 'signed-out');
  }
  if (!await visible(driver, selector(platform, 'id', 'account-open'))) await browserLogin(context);
  await click(context, 'id', 'account-open');
  assert.equal(await read(context, 'id', 'account-principal'), fixture.principalLabel, 'WRONG_PRINCIPAL');
  assert.equal(await read(context, 'id', 'account-workspace'), fixture.workspaceLabel, 'WRONG_WORKSPACE');
  await click(context, 'id', 'back');
}
