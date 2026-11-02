import assert from 'node:assert/strict';
import { click, dispatchNativeClick, find, read, selector, swipe, visible } from './native-ui.mjs';
import { firefoxLogin } from './firefox-handoff.mjs';
import { CONSENT_MFA_VERIFIED, fixtureMfaCode, mfaStage } from './mfa.mjs';
import { browserStep } from './browser-progress.mjs';

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

async function dom(context, key, css) {
  browserStep(context, key, 'find');
  const elements = await context.driver.$$(css);
  const displayed = [];
  for (const element of elements) if (await element.isDisplayed()) displayed.push(element);
  assert.equal(displayed.length, 1, 'BROWSER_CONTROL_NOT_UNIQUE');
  return displayed[0];
}
async function domFill(context, key, css, value) {
  const control = await dom(context, key, css);
  browserStep(context, key, 'fill');
  await control.setValue(typeof value === 'function' ? value() : value);
}
async function domPress(context, key, css) {
  const control = await dom(context, key, css);
  browserStep(context, key, 'click');
  await control.click();
}

async function iosAuthorizationContexts(context) {
  const { driver, fixture, platform } = context;
  browserStep(context, 'browser-context', 'read');
  // The pinned XCUITest metadata command identifies each page without attaching
  // its inspector. A context already represents one page; its process-wide
  // window list can include unrelated and retained authorization pages.
  const contexts = await driver.execute('mobile: getContexts', { waitForWebviewMs: 0 });
  assert.ok(Array.isArray(contexts) && contexts.length <= 8, 'SYSTEM_BROWSER_CONTEXT_BOUND');
  const candidates = [];
  for (const entry of contexts) {
    assert.ok(entry && typeof entry === 'object' && typeof entry.id === 'string', 'IOS_BROWSER_CONTEXT_METADATA_REQUIRED');
    if (entry.id === 'NATIVE_APP') continue;
    assert.equal(typeof entry.url, 'string', 'IOS_BROWSER_CONTEXT_METADATA_REQUIRED');
    const url = new URL(entry.url);
    const nativeLoginReturn = url.pathname === '/sign-in'
      && url.searchParams.getAll('next').some((next) => next.startsWith('/native/sign-in'));
    if (url.origin !== browserOrigin(fixture.auth.webOrigin)
      || !(url.pathname === '/native/sign-in' || nativeLoginReturn)) continue;
    // Validate even retained pages before ignoring their identities. A malformed
    // native-looking page must never become an ordinary unrelated browser tab.
    const identity = authorizationIdentity(url.href, fixture.auth.webOrigin, platform);
    if (!fixture.auth.context || entry.id === fixture.auth.context) candidates.push({ name: entry.id, identity });
  }
  return candidates;
}

async function attachIosBrowser(context, before) {
  const { driver, fixture, platform } = context;
  const inspect = async (candidate) => {
    browserStep(context, 'browser-context', 'switch-context');
    await driver.switchContext(candidate.name);
    assert.ok(await driver.getWindowHandle(), 'CURRENT_SYSTEM_BROWSER_WINDOW_REQUIRED');
    assert.ok(JSON.stringify(authorizationIdentity(await driver.getUrl(), fixture.auth.webOrigin, platform))
      === JSON.stringify(candidate.identity), 'BROWSER_CONTEXT_METADATA_CHANGED');
    browserStep(context, 'browser-context', 'read');
    const foreground = await driver.execute(() => ({ visibilityState: document.visibilityState, hasFocus: document.hasFocus() }));
    assert.ok(foreground && typeof foreground.visibilityState === 'string' && typeof foreground.hasFocus === 'boolean',
      'SYSTEM_BROWSER_FOREGROUND_PROOF_REQUIRED');
    return foreground.visibilityState === 'visible' && foreground.hasFocus;
  };
  let selected;
  browserStep(context, 'browser-context', 'wait');
  await driver.waitUntil(async () => {
    // waitUntil may retry a rejected inspection while still in that web page.
    // Every readiness read must therefore restore the native context first.
    await driver.switchContext('NATIVE_APP');
    // During ASWebAuthenticationSession's presentation transition the inspector
    // can report a retained page before the current sheet is ready. Stay native
    // until its exact Cancel button is visible and enabled.
    const cancel = await visible(driver, '-ios predicate string:type == "XCUIElementTypeButton" AND (label == "Cancel" OR name == "Cancel")');
    if (!cancel || !await cancel.isEnabled()) return false;
    const candidates = (await iosAuthorizationContexts(context))
      .filter(({ identity }) => !before.has(JSON.stringify(identity)));
    const foreground = [];
    // The metadata can retain a hidden authorization page which was absent
    // before presentation. Inspect only strictly validated native pages and
    // require both document visibility and focus for the current handoff.
    for (const candidate of candidates) if (await inspect(candidate)) foreground.push(candidate);
    assert.ok(foreground.length <= 1, 'AMBIGUOUS_SYSTEM_BROWSER');
    selected = foreground[0];
    return !!selected;
  }, { timeout: 20000, interval: 500, timeoutMsg: 'SYSTEM_BROWSER_CONTEXT_UNAVAILABLE' });
  assert.equal(await inspect(selected), true, 'SYSTEM_BROWSER_FOREGROUND_CHANGED');
}

async function attachBrowser(context, before) {
  const { driver, fixture, platform } = context;
  if (platform === 'ios') return attachIosBrowser(context, before);
  let selected;
  browserStep(context, 'browser-context', 'wait');
  await driver.waitUntil(async () => {
    const candidates = [];
    const contexts = await driver.getContexts();
    assert.ok(contexts.length <= 8, 'SYSTEM_BROWSER_CONTEXT_BOUND');
    for (const entry of contexts) {
      const name = typeof entry === 'string' ? entry : entry.id;
      if (!name || name === 'NATIVE_APP' || (fixture.auth.context && name !== fixture.auth.context)) continue;
      browserStep(context, 'browser-context', 'switch-context');
      await driver.switchContext(name);
      // Inspect only location, never cookies, storage, source HTML or callback codes.
      const handles = await driver.getWindowHandles();
      assert.ok(handles.length <= 8, 'SYSTEM_BROWSER_WINDOW_BOUND');
      for (const handle of handles) {
        await driver.switchToWindow(handle);
        const url = new URL(await driver.getUrl());
        const nativeLoginReturn = url.pathname === '/sign-in'
          && url.searchParams.getAll('next').some((next) => next.startsWith('/native/sign-in'));
        // A prior ordinary Safari login tab is not this app's authorization
        // session. Native-looking return URLs still undergo the strict query,
        // PKCE, callback and platform checks below before any credential write.
        if (url.origin === browserOrigin(fixture.auth.webOrigin)
          && (url.pathname === '/native/sign-in' || nativeLoginReturn)) {
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

async function resolveIosBrowserEntry(context, handoff) {
  const { driver, fixture, platform } = context;
  const deadline = Date.now() + 10000;
  let attempted = false;
  browserStep(context, 'companySlug', 'wait');
  for (;;) {
    assert.ok(Date.now() < deadline, 'REAL_BROWSER_LOGIN_FORM_REQUIRED');
    let ready, terminal;
    await driver.waitUntil(async () => {
      try {
        assert.deepEqual(authorizationIdentity(await driver.getUrl(), fixture.auth.webOrigin, platform), handoff, 'BROWSER_HANDOFF_CHANGED');
        const anchors = await driver.$$('form[aria-label="Sign in"] #company-slug');
        assert.ok(anchors.length <= 1, 'AMBIGUOUS_IOS_BROWSER_ENTRY_STATE');
        const form = anchors[0] && await anchors[0].isDisplayed() ? anchors[0] : undefined;
        const entries = [];
        for (const control of await driver.$$('a[href^="/sign-in?next="]')) if (await control.isDisplayed()) entries.push(control);
        assert.ok(entries.length <= 1, 'AMBIGUOUS_IOS_BROWSER_ENTRY_STATE');
        assert.ok(Date.now() <= deadline, 'REAL_BROWSER_LOGIN_FORM_REQUIRED');
        // A clicked link can linger while navigation settles. Preserve the
        // original shared deadline and never dispatch that navigation again.
        if (attempted && entries.length) return false;
        assert.ok(!form || entries.length === 0, 'AMBIGUOUS_IOS_BROWSER_ENTRY_STATE');
        if (form && await form.isEnabled()) { ready = { form: true }; return true; }
        if (!attempted && entries.length && await entries[0].isEnabled()) { ready = { control: entries[0] }; return true; }
        return false;
      } catch (error) {
        // waitUntil retries callback rejections. Carry observed ambiguity,
        // PKCE drift and transport failures out without polling them again.
        terminal = error; return true;
      }
    }, { timeout: Math.max(1, deadline - Date.now()), interval: 200, timeoutMsg: 'REAL_BROWSER_LOGIN_FORM_REQUIRED' });
    if (terminal) throw terminal;
    assert.ok(ready && Date.now() <= deadline, 'REAL_BROWSER_LOGIN_FORM_REQUIRED');
    if (ready.form) return;
    const id = ready.control?.elementId;
    assert.ok(typeof id === 'string' && id.length > 0 && id.trim() === id, 'IOS_ENTRY_ELEMENT_ID_REQUIRED');
    assert.equal(typeof driver.elementClick, 'function', 'IOS_ENTRY_PROTOCOL_CLICK_REQUIRED');
    assert.ok(!attempted && Date.now() < deadline, 'REAL_BROWSER_LOGIN_FORM_REQUIRED');
    attempted = true;
    browserStep(context, 'useAnotherAccount', 'click');
    // Keep this mutation outside polling; element.click() may refetch/replay.
    await driver.elementClick(id);
  }
}

export async function browserLogin(context) {
  const { driver, fixture, platform } = context;
  const stage = mfaStage(fixture.auth);
  const credentials = loginCredentials(fixture.auth);
  browserOrigin(fixture.auth.webOrigin);
  // App.tsx creates a fresh verifier/challenge and state for every sign-in
  // attempt. Keep prior valid identities only in memory, never in run evidence.
  const before = platform === 'ios' && fixture.auth.mode !== 'native-firefox'
    ? new Set((await iosAuthorizationContexts(context)).map(({ identity }) => JSON.stringify(identity))) : undefined;
  browserStep(context, 'sign-in', 'click');
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
      browserStep(context, 'ios-consent', 'wait');
      await driver.waitUntil(async () => {
        try { await driver.getAlertText(); return true; }
        catch (error) { if (error.name === 'no such alert' || /no such alert|no alert/i.test(error.message)) return false; throw error; }
      }, { timeout: 5000, interval: 200 });
      const buttons = await driver.execute('mobile: alert', { action: 'getButtons' });
      assert.ok(buttons.includes('Continue'), 'IOS_AUTH_CONSENT_NOT_RECOGNIZED');
      browserStep(context, 'ios-consent', 'click');
      await driver.execute('mobile: alert', { action: 'accept', buttonLabel: 'Continue' });
    }
    await attachBrowser(context, before);
    browserStep(context, 'handoff', 'read');
    handoff = authorizationIdentity(await driver.getUrl(), fixture.auth.webOrigin, platform);
    if (platform === 'ios') await resolveIosBrowserEntry(context, handoff);
    else {
      const another = await driver.$$('a[href^="/sign-in?next="]');
      for (const element of another) if (await element.isDisplayed()) {
        browserStep(context, 'useAnotherAccount', 'click');
        await element.click();
      }
      browserStep(context, 'companySlug', 'wait');
      await driver.waitUntil(async () => (await driver.$$('#company-slug')).length === 1,
        { timeout: 10000, interval: 200, timeoutMsg: 'REAL_BROWSER_LOGIN_FORM_REQUIRED' });
    }
    assert.deepEqual(authorizationIdentity(await driver.getUrl(), fixture.auth.webOrigin, platform), handoff, 'BROWSER_HANDOFF_CHANGED');
    await domFill(context, 'companySlug', '#company-slug', credentials.companySlug);
    await domFill(context, 'email', '#email', credentials.email);
    await domFill(context, 'password', '#password', credentials.password);
    await domPress(context, 'submit', 'form[aria-label="Sign in"] button[type="submit"]');
    browserStep(context, 'login-result', 'wait');
    await driver.waitUntil(async () => (await driver.$$('#mfa-code')).length === 1 || (await driver.$$('main dl dd')).length === 2,
      { timeout: 15000, interval: 250, timeoutMsg: 'BROWSER_LOGIN_NOT_ACKNOWLEDGED' });
    const loginChallenge = (await driver.$$('#mfa-code')).length === 1;
    assert.equal(loginChallenge, stage === 'login', 'BROWSER_LOGIN_MFA_STAGE_MISMATCH');
    if (stage === 'login') {
      assert.deepEqual(authorizationIdentity(await driver.getUrl(), fixture.auth.webOrigin, platform), handoff, 'BROWSER_HANDOFF_CHANGED');
      await domFill(context, 'mfaCode', '#mfa-code', () => fixtureMfaCode(fixture.auth));
      await domPress(context, 'mfaSubmit', 'form[aria-label="MFA challenge"] button[type="submit"]');
    }
    browserStep(context, 'identity', 'wait');
    await driver.waitUntil(async () => {
      const current = new URL(await driver.getUrl());
      assert.equal(current.origin, browserOrigin(fixture.auth.webOrigin), 'UNSAFE_BROWSER_ORIGIN');
      return current.pathname === '/native/sign-in' && (await driver.$$('main dl dd')).length === 2;
    }, { timeout: 15000, interval: 250, timeoutMsg: 'BROWSER_LOGIN_OR_MFA_NOT_COMPLETED' });
    const verifyIdentity = async () => {
      browserStep(context, 'handoff', 'check');
      assert.deepEqual(authorizationIdentity(await driver.getUrl(), fixture.auth.webOrigin, platform), handoff, 'BROWSER_HANDOFF_CHANGED');
      const facts = await driver.$$('main dl dd');
      assert.equal(facts.length, 2, 'BROWSER_IDENTITY_FACTS_REQUIRED');
      const normalize = (text) => text.replace(/\s+/g, ' ').trim();
      browserStep(context, 'principal', 'read');
      assert.equal(normalize(await facts[0].getText()), normalize(`${fixture.principalLabel} ${credentials.email}`), 'WRONG_BROWSER_PRINCIPAL');
      browserStep(context, 'workspace', 'read');
      assert.equal(normalize(await facts[1].getText()), normalize(`${fixture.workspaceLabel} / ${credentials.companySlug}`), 'WRONG_BROWSER_WORKSPACE');
    };
    const connectExplicitly = async () => {
      const connect = await dom(context, 'connect', 'main button');
      browserStep(context, 'connect', 'read');
      assert.equal((await connect.getText()).trim(), 'Connect app', 'REAL_CONNECT_CONTROL_REQUIRED');
      assert.equal(await connect.isEnabled(), true, 'CONNECT_CONTROL_DISABLED');
      browserStep(context, 'connect', 'click');
      await connect.click();
    };
    await verifyIdentity();
    await connectExplicitly();
    if (stage === 'consent') {
      // Only the typed native_mfa_required recovery renders this known form.
      browserStep(context, 'mfaCode', 'wait');
      await driver.waitUntil(async () => (await driver.$$('#native-mfa-code')).length === 1,
        { timeout: 10000, interval: 200, timeoutMsg: 'NATIVE_CONSENT_MFA_CHALLENGE_REQUIRED' });
      assert.deepEqual(authorizationIdentity(await driver.getUrl(), fixture.auth.webOrigin, platform), handoff, 'BROWSER_HANDOFF_CHANGED');
      await domFill(context, 'mfaCode', '#native-mfa-code', () => fixtureMfaCode(fixture.auth));
      const verify = await dom(context, 'mfaSubmit', 'form:has(#native-mfa-code) button[type="submit"]');
      browserStep(context, 'mfaSubmit', 'read');
      assert.equal((await verify.getText()).trim(), 'Verify code', 'REAL_NATIVE_MFA_VERIFY_CONTROL_REQUIRED');
      browserStep(context, 'mfaSubmit', 'click');
      await verify.click();
      browserStep(context, 'mfaVerified', 'wait');
      await driver.waitUntil(async () => (await driver.$$('#native-mfa-code')).length === 0
        && (await driver.$$('main dl dd')).length === 2 && (await driver.$$('main button')).length === 1,
      { timeout: 15000, interval: 200, timeoutMsg: 'NATIVE_CONSENT_MFA_NOT_COMPLETED' });
      const verified = await dom(context, 'mfaVerified', 'main [role="status"]');
      browserStep(context, 'mfaVerified', 'read');
      assert.equal((await verified.getText()).trim(), CONSENT_MFA_VERIFIED,
        'NATIVE_CONSENT_MFA_VERIFIED_NOTICE_REQUIRED');
      await verifyIdentity();
      await connectExplicitly();
    }
    browserStep(context, 'appOpen', 'wait');
    await driver.waitUntil(async () => !!await visible(driver, '#native-app-open'),
      { timeout: 10000, interval: 200, timeoutMsg: 'NATIVE_APP_OPEN_CONTROL_NOT_VISIBLE' });
    const appOpen = await dom(context, 'appOpen', '#native-app-open');
    browserStep(context, 'appOpen', 'read');
    assert.equal((await appOpen.getText()).trim(), 'Open CaseOps', 'REAL_NATIVE_APP_OPEN_CONTROL_REQUIRED');
    browserStep(context, 'appOpen', 'check');
    assert.equal(await appOpen.isEnabled(), true, 'NATIVE_APP_OPEN_CONTROL_DISABLED');
    browserStep(context, 'appOpen', 'click');
    await appOpen.click();
  } finally {
    browserStep(context, 'native-return', 'switch-context');
    await driver.switchContext('NATIVE_APP');
  }
  browserStep(context, 'native-return', 'wait');
  await find(context, 'id', 'account-open');
  context.record?.({ type: 'assertion', boundary: 'system-browser-ui-pkce-completed', platform });
}

async function waitForSessionReady(context, { signedOutOnly = false } = {}) {
  const { driver, platform } = context;
  await driver.waitUntil(async () => {
    if (await visible(driver, selector(platform, 'id', 'session-loading'))) return false;
    const account = await visible(driver, selector(platform, 'id', 'account-open'));
    if (account) return !signedOutOnly && await account.isEnabled();
    const signIn = await visible(driver, selector(platform, 'id', 'sign-in'));
    return !!signIn && await signIn.isEnabled()
      && !!await visible(driver, selector(platform, 'id', 'signed-out'));
  }, { timeout: 20000, interval: 200, timeoutMsg: 'NATIVE_SESSION_NOT_READY' });
}

async function settleIosFreshAccount(context) {
  const { driver, fixture } = context;
  let signOut, identityFailure, identityVerified = false, scrolls = 0;
  await driver.waitUntil(async () => {
    signOut = undefined;
    if (await visible(driver, '~session-loading')) return false;
    const signedOut = await visible(driver, '~signed-out');
    const signIn = await visible(driver, '~sign-in');
    // Automatic session expiry can finish while Account is opening. Its
    // completed signed-out state needs a new browser/MFA journey, not another
    // attempt to locate or invoke the former account's sign-out control.
    if (signedOut || signIn) return !!signedOut && !!signIn && await signIn.isEnabled();
    const principal = await visible(driver, '~account-principal');
    const workspace = await visible(driver, '~account-workspace');
    if (principal && workspace) {
      if (await principal.getText() !== fixture.principalLabel) { identityFailure = 'WRONG_PRINCIPAL'; return true; }
      if (await workspace.getText() !== fixture.workspaceLabel) { identityFailure = 'WRONG_WORKSPACE'; return true; }
      identityVerified = true;
    }
    if (!identityVerified) return false;
    signOut = await visible(driver, '~sign-out');
    if (signOut && await signOut.isEnabled()) return true;
    if (scrolls < 9) { scrolls++; await swipe(context, 'down'); }
    return false;
  }, { timeout: 20000, interval: 200, timeoutMsg: 'NATIVE_FRESH_ACCOUNT_NOT_READY' });
  // WebDriver waitUntil retries callback rejections. Carry an observed wrong
  // identity out as a terminal result so a later expiry cannot erase it.
  if (identityFailure) throw new Error(identityFailure);
  context.record?.({ type: 'assertion', boundary: 'native-fresh-authentication-settled',
    state: signOut ? 'verified-account' : 'automatic-sign-out' });
  return signOut;
}

export async function authenticate(context, { fresh = false } = {}) {
  const { driver, fixture, platform } = context;
  await driver.switchContext('NATIVE_APP');
  await waitForSessionReady(context);
  if (fresh && await visible(driver, selector(platform, 'id', 'account-open'))) {
    await click(context, 'id', 'account-open');
    if (platform === 'ios') {
      const signOut = await settleIosFreshAccount(context);
      if (signOut) {
        await dispatchNativeClick(context, signOut, 'id', 'sign-out');
        await find(context, 'id', 'signed-out');
      }
    } else {
      await click(context, 'id', 'sign-out', { scroll: true });
      await find(context, 'id', 'signed-out');
    }
    await waitForSessionReady(context, { signedOutOnly: true });
  }
  if (!await visible(driver, selector(platform, 'id', 'account-open'))) await browserLogin(context);
  await click(context, 'id', 'account-open');
  assert.equal(await read(context, 'id', 'account-principal'), fixture.principalLabel, 'WRONG_PRINCIPAL');
  assert.equal(await read(context, 'id', 'account-workspace'), fixture.workspaceLabel, 'WRONG_WORKSPACE');
  await click(context, 'id', 'back');
}
