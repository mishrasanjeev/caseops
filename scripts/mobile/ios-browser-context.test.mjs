import assert from 'node:assert/strict';
import test from 'node:test';
import { authenticate, browserLogin } from '../../apps/mobile/e2e/browser-handoff.mjs';

const ORIGIN = 'https://127.0.0.1:3443';
const nativeUrl = (state = 's', platform = 'ios') => `${ORIGIN}/native/sign-in?${new URLSearchParams({
  code_challenge: 'c'.repeat(43), state: state.repeat(32), platform,
  redirect_uri: 'caseops://oauth/callback',
})}`;
const nativeContext = (id, url) => ({ id, url, title: 'CaseOps', bundleId: 'com.apple.SafariViewService' });
const NATIVE = { id: 'NATIVE_APP' };
const CANCEL = '-ios predicate string:type == "XCUIElementTypeButton" AND (label == "Cancel" OR name == "Cancel")';

function nativeProtocolDouble(driver) {
  const query = driver.$$.bind(driver), callbacks = new Map();
  let sequence = 0;
  driver.$$ = async (...args) => {
    const matches = await query(...args);
    for (const element of matches) if (typeof element.click === 'function') {
      element.elementId ??= `unit-native-${++sequence}`;
      callbacks.set(element.elementId, element.click.bind(element));
    }
    return matches;
  };
  driver.elementClick = async id => {
    assert.ok(callbacks.has(id), 'UNIT_RESOLVED_NATIVE_ID_REQUIRED');
    await callbacks.get(id)();
  };
  return driver;
}

function environment(t) {
  const values = {
    CASEOPS_MOBILE_CONTEXT_TEST_EMAIL: 'context-unit@example.invalid',
    CASEOPS_MOBILE_CONTEXT_TEST_PASSWORD: 'context-unit-password',
  };
  for (const [key, value] of Object.entries(values)) {
    const before = process.env[key];
    process.env[key] = value;
    t.after(() => { if (before === undefined) delete process.env[key]; else process.env[key] = before; });
  }
}

function browserDouble({ regularUrl = `${ORIGIN}/sign-in`, authorizationUrl = nativeUrl(), duplicateNative = false,
  before = [NATIVE], after, ready = [true], currentUrl, platform = 'ios', pageStates = {}, landingStage = 'landing' } = {}) {
  let stage = 'app', activeContext = 'NATIVE_APP', activeWindow = 'regular';
  let readinessPolls = 0, afterPolls = 0;
  const writes = [], clicks = [], reads = [], metadata = [], switches = [], waits = [], commands = [], foregroundReads = [];
  const pageReadCounts = {};
  const isNative = () => activeContext === 'NATIVE_APP';
  const element = (key, text = '', action = () => {}) => ({
    elementId: key,
    isDisplayed: async () => true, isEnabled: async () => true,
    getText: async () => text,
    setValue: async (value) => {
      writes.push({ key, value, window: activeWindow });
      assert.equal(activeWindow, 'authorization', 'CREDENTIALS_SENT_TO_UNRELATED_WINDOW');
    },
    click: async () => { clicks.push(key); action(); },
  });
  const driver = {
    switchContext: async (context) => {
      switches.push(context);
      assert.ok(['NATIVE_APP', 'WEBVIEW_authorization', 'WEBVIEW_duplicate', ...Object.keys(pageStates)].includes(context),
        'UNRELATED_BROWSER_CONTEXT_ATTACHED');
      activeContext = context;
      if (context !== 'NATIVE_APP') activeWindow = context === 'WEBVIEW_authorization' ? 'authorization' : context;
    },
    execute: async (command, args) => {
      if (typeof command === 'function') {
        assert.ok(!isNative(), 'FOREGROUND_PROOF_REQUIRES_SELECTED_PAGE');
        assert.match(command.toString(), /document\.visibilityState/);
        assert.match(command.toString(), /document\.hasFocus\(\)/);
        foregroundReads.push(activeContext);
        const states = pageStates[activeContext]?.foreground || [{ visibilityState: 'visible', hasFocus: true }];
        const count = pageReadCounts[activeContext] || 0;
        pageReadCounts[activeContext] = count + 1;
        return states[Math.min(count, states.length - 1)];
      }
      commands.push(command);
      assert.equal(command, 'mobile: getContexts');
      assert.deepEqual(args, { waitForWebviewMs: 0 });
      const entries = stage === 'app' ? before : after ? after[Math.min(afterPolls++, after.length - 1)] : [NATIVE,
        nativeContext('WEBVIEW_regular', regularUrl), nativeContext('WEBVIEW_blank', 'about:blank'),
        nativeContext('WEBVIEW_authorization', authorizationUrl),
        ...(duplicateNative ? [nativeContext('WEBVIEW_duplicate', nativeUrl('d'))] : [])];
      metadata.push({ stage, entries, readinessPolls });
      return entries;
    },
    getContexts: async () => {
      assert.equal(platform, 'android', 'IOS_STRING_CONTEXT_ENUMERATION_FORBIDDEN');
      return ['NATIVE_APP', 'WEBVIEW_authorization'];
    },
    getWindowHandles: async () => {
      assert.equal(platform, 'android', 'IOS_PROCESS_WINDOW_ENUMERATION_FORBIDDEN');
      return ['regular', 'authorization'];
    },
    switchToWindow: async (window) => {
      assert.equal(platform, 'android', 'IOS_PROCESS_WINDOW_SWITCH_FORBIDDEN');
      activeWindow = window;
    },
    getWindowHandle: async () => {
      assert.ok(!isNative());
      return activeWindow;
    },
    getUrl: async () => {
      reads.push(activeWindow);
      if (activeWindow === 'regular') return regularUrl;
      if (pageStates[activeContext]?.url) return pageStates[activeContext].url;
      if (activeContext === 'WEBVIEW_duplicate') return nativeUrl('d');
      if (currentUrl) return currentUrl;
      return stage === 'login'
        ? `${ORIGIN}/sign-in?${new URLSearchParams({ next: new URL(authorizationUrl).pathname + new URL(authorizationUrl).search })}`
        : authorizationUrl;
    },
    waitUntil: async (callback, options) => {
      waits.push(options);
      for (let attempt = 0; attempt < 4; attempt++) if (await callback()) return;
      assert.fail(options?.timeoutMsg || 'UNIT_WAIT_UNSATISFIED');
    },
    $$: async (query) => {
      if (query === CANCEL) assert.ok(isNative(), 'BROWSER_READINESS_REQUIRES_NATIVE_CONTEXT');
      if (isNative()) {
        if (query === (platform === 'ios' ? '~sign-in' : 'id=sign-in') && stage === 'app') return [element('sign-in', '', () => { stage = landingStage; })];
        if (query === CANCEL && stage !== 'app') {
          const readiness = ready[Math.min(readinessPolls++, ready.length - 1)];
          return readiness ? [{ ...element('cancel'), isEnabled: async () => readiness === true }] : [];
        }
        if (query === (platform === 'ios' ? '~account-open' : 'id=account-open') && stage === 'complete') return [element('account-open')];
        return [];
      }
      assert.equal(activeWindow, 'authorization', 'UNRELATED_BROWSER_DOM_TOUCHED');
      if (query === 'a[href^="/sign-in?next="]' && stage === 'landing') return [element('sign-in-link', '', () => { stage = 'login'; })];
      if (['#company-slug', 'form[aria-label="Sign in"] #company-slug', '#email', '#password'].includes(query) && stage === 'login') return [element(query === 'form[aria-label="Sign in"] #company-slug' ? '#company-slug' : query)];
      if (query === 'form[aria-label="Sign in"] button[type="submit"]' && stage === 'login') return [element('submit', '', () => { stage = 'connect'; })];
      if (query === 'main dl dd' && stage === 'connect') return [
        element('principal', 'Context Unit context-unit@example.invalid'),
        element('workspace', 'Unit Workspace / unit'),
      ];
      if (query === 'main button' && stage === 'connect') return [element('connect', 'Connect app', () => { stage = 'grant'; })];
      if (query === '#native-app-open' && stage === 'grant') return [element('app-open', 'Open CaseOps', () => { stage = 'complete'; })];
      return [];
    },
  };
  nativeProtocolDouble(driver);
  return { driver, writes, clicks, reads, metadata, switches, waits, commands, foregroundReads, context: { driver, platform, fixture: {
    principalLabel: 'Context Unit', workspaceLabel: 'Unit Workspace', auth: {
      mode: 'web-context', webOrigin: ORIGIN, companySlug: 'unit',
      emailEnv: 'CASEOPS_MOBILE_CONTEXT_TEST_EMAIL', passwordEnv: 'CASEOPS_MOBILE_CONTEXT_TEST_PASSWORD',
    },
  } } };
}

function entryDouble(t, { state = 'link', linger = 0, delayedForm = 0, disabledForm = 0, failure, lostAck = false,
  missingId = false, missingProtocol = false, drift = false } = {}) {
  environment(t);
  let clock = 0;
  t.mock.method(Date, 'now', () => clock);
  const fake = browserDouble({ landingStage: ['form', 'form-and-link'].includes(state) ? 'login' : 'landing' });
  const query = fake.driver.$$.bind(fake.driver), protocol = fake.driver.elementClick.bind(fake.driver), url = fake.driver.getUrl.bind(fake.driver);
  const stats = { linkQueries: 0, formQueries: 0, entryDispatches: [], wrappedClicks: 0, callbackErrorsCaught: 0 };
  let cachedLink, remainingLinger = linger;
  fake.driver.getUrl = async () => drift && stats.entryDispatches.length ? nativeUrl('changed') : url();
  fake.driver.elementClick = async id => {
    if (id === 'sign-in' && missingProtocol) { await protocol(id); fake.driver.elementClick = undefined; return; }
    if (id === 'sign-in-link') {
      stats.entryDispatches.push(id);
      if (failure && !lostAck) throw failure;
      const result = await protocol(id);
      if (failure) throw failure;
      return result;
    }
    return protocol(id);
  };
  const wrapLink = (element, visible = true) => ({ ...element, ...(missingId ? { elementId: undefined } : {}),
    isDisplayed: async () => visible,
    click: async () => { stats.wrappedClicks++; throw new Error('WRAPPED_ENTRY_CLICK_FORBIDDEN'); } });
  fake.driver.$$ = async value => {
    if (value === 'a[href^="/sign-in?next="]') {
      stats.linkQueries++;
      const found = await query(value);
      cachedLink ??= found[0];
      if (state === 'none') return [];
      if (state === 'form-and-link') return [wrapLink({ elementId: 'unexpected-link', isEnabled: async () => true })];
      if (stats.entryDispatches.length && remainingLinger > 0) { remainingLinger--; return [wrapLink(cachedLink)]; }
      if (state === 'late-link' && stats.linkQueries === 1) return found.map(element => wrapLink(element, false));
      if (state === 'ambiguous') return [...found.map(element => wrapLink(element)), ...found.map(element => wrapLink({ ...element, elementId: element.elementId + '-other' }))];
      if (state === 'duplicate') return [...found.map(element => wrapLink(element)), ...found.map(element => wrapLink(element))];
      return found.map(element => wrapLink(element));
    }
    if (value === '#company-slug' || value === 'form[aria-label="Sign in"] #company-slug') {
      stats.formQueries++;
      if (failure && state === 'transport') throw failure;
      if (stats.formQueries <= delayedForm || state === 'none') return [];
      const found = await query(value);
      return found.map(element => ({ ...element, isEnabled: async () => stats.formQueries > disabledForm }));
    }
    return query(value);
  };
  fake.driver.waitUntil = async (condition, options) => {
    fake.waits.push(options);
    const end = clock + options.timeout;
    while (clock <= end) {
      try { if (await condition()) return; }
      catch { stats.callbackErrorsCaught++; } // Pinned WDIO normally retries rejected callbacks.
      if (clock === end) break;
      clock = Math.min(end, clock + options.interval);
    }
    throw new Error(options.timeoutMsg || 'UNIT_WAIT_UNSATISFIED');
  };
  return { ...fake, stats, elapsed: () => clock };
}

test('iOS resolves a login link that appears after the initial read before any credentials', async t => {
  const f = entryDouble(t, { state: 'late-link' });
  await browserLogin(f.context);
  assert.ok(f.stats.linkQueries >= 2);
  assert.deepEqual(f.stats.entryDispatches, ['sign-in-link']); assert.equal(f.stats.wrappedClicks, 0);
  assert.deepEqual(f.writes.map(row => row.key), ['#company-slug', '#email', '#password']);
  assert.ok(f.elapsed() <= 10000);
});
test('iOS immediate exact form does not navigate an entry link', async t => {
  const f = entryDouble(t, { state: 'form' }); await browserLogin(f.context);
  assert.deepEqual(f.stats.entryDispatches, []); assert.equal(f.stats.wrappedClicks, 0); assert.equal(f.writes.length, 3);
});
test('iOS waits for a delayed enabled exact form anchor within the original entry budget', async t => {
  const f = entryDouble(t, { state: 'form', delayedForm: 2, disabledForm: 4 }); await browserLogin(f.context);
  assert.ok(f.stats.formQueries >= 5); assert.deepEqual(f.stats.entryDispatches, []); assert.equal(f.writes.length, 3);
  const policy = f.waits.find(row => row.timeoutMsg === 'REAL_BROWSER_LOGIN_FORM_REQUIRED');
  assert.deepEqual(policy, { timeout: 10000, interval: 200, timeoutMsg: 'REAL_BROWSER_LOGIN_FORM_REQUIRED' });
});
test('iOS refuses distinct or duplicate visible entry matches before navigation or credentials', async t => {
  for (const state of ['ambiguous', 'duplicate']) {
    const f = entryDouble(t, { state });
    await assert.rejects(browserLogin(f.context), /AMBIGUOUS_IOS_BROWSER_ENTRY_STATE/);
    assert.deepEqual(f.stats.entryDispatches, []); assert.equal(f.stats.wrappedClicks, 0); assert.equal(f.writes.length, 0);
    assert.equal(f.stats.callbackErrorsCaught, 0);
  }
});
test('iOS refuses simultaneous form and unclicked entry-link states', async t => {
  const f = entryDouble(t, { state: 'form-and-link' });
  await assert.rejects(browserLogin(f.context), /AMBIGUOUS_IOS_BROWSER_ENTRY_STATE/);
  assert.deepEqual(f.stats.entryDispatches, []); assert.equal(f.writes.length, 0);
});
test('iOS waits for a clicked entry link to disappear without dispatching it again', async t => {
  const f = entryDouble(t, { linger: 3 }); await browserLogin(f.context);
  assert.deepEqual(f.stats.entryDispatches, ['sign-in-link']); assert.equal(f.stats.wrappedClicks, 0); assert.equal(f.writes.length, 3);
  assert.ok(f.elapsed() >= 600 && f.elapsed() <= 10000);
});
test('iOS retained entry and absent form both stop under one original ten-second deadline', async t => {
  for (const options of [{ linger: Infinity }, { state: 'none' }]) {
    const f = entryDouble(t, options);
    await assert.rejects(browserLogin(f.context), /REAL_BROWSER_LOGIN_FORM_REQUIRED/);
    assert.equal(f.elapsed(), 10000); assert.ok(f.stats.entryDispatches.length <= 1); assert.equal(f.writes.length, 0);
    assert.ok(f.waits.filter(row => row.timeoutMsg === 'REAL_BROWSER_LOGIN_FORM_REQUIRED').every(row => row.timeout <= 10000 && row.interval === 200));
  }
});
test('iOS entry navigation must retain the full PKCE identity before credential writes', async t => {
  const f = entryDouble(t, { drift: true });
  await assert.rejects(browserLogin(f.context), /BROWSER_HANDOFF_CHANGED/);
  assert.deepEqual(f.stats.entryDispatches, ['sign-in-link']); assert.equal(f.writes.length, 0); assert.equal(f.stats.callbackErrorsCaught, 0);
});
test('iOS entry read transport failures remain terminal despite waitUntil callback retry behavior', async t => {
  const failure = Object.assign(new Error('UNIT_READ_FAILURE'), { code: 'ECONNRESET' });
  const f = entryDouble(t, { state: 'transport', failure });
  await assert.rejects(browserLogin(f.context), error => error === failure);
  assert.equal(f.stats.formQueries, 1); assert.equal(f.stats.callbackErrorsCaught, 0); assert.equal(f.writes.length, 0);
});
test('iOS entry stale and lost acknowledgements keep one original-ID raw dispatch and zero wrapped clicks', async t => {
  for (const [name, lostAck] of [['stale element reference', false], ['unknown error', true]]) {
    const failure = Object.assign(new Error('UNIT_ENTRY_CLICK_FAILURE'), { name });
    const f = entryDouble(t, { failure, lostAck });
    await assert.rejects(browserLogin(f.context), error => error === failure);
    assert.deepEqual(f.stats.entryDispatches, ['sign-in-link']); assert.equal(f.stats.wrappedClicks, 0); assert.equal(f.writes.length, 0);
  }
});
test('iOS entry click refuses a missing resolved identity or protocol method without a fallback', async t => {
  for (const options of [{ missingId: true }, { missingProtocol: true }]) {
    const f = entryDouble(t, options);
    await assert.rejects(browserLogin(f.context), /IOS_ENTRY_(ELEMENT_ID|PROTOCOL_CLICK)_REQUIRED/);
    assert.deepEqual(f.stats.entryDispatches, []); assert.equal(f.stats.wrappedClicks, 0); assert.equal(f.writes.length, 0);
  }
});

test('iOS native browser login ignores the earlier ordinary Safari TLS-smoke sign-in tab', async (t) => {
  environment(t);
  const fake = browserDouble();
  await browserLogin(fake.context);
  assert.deepEqual(fake.writes.map(({ key }) => key), ['#company-slug', '#email', '#password']);
  assert.ok(fake.writes.every(({ window }) => window === 'authorization'));
  assert.deepEqual(fake.clicks, ['sign-in', 'sign-in-link', 'submit', 'connect', 'app-open']);
  assert.deepEqual(fake.switches.filter((name) => name !== 'NATIVE_APP'), ['WEBVIEW_authorization', 'WEBVIEW_authorization']);
  assert.equal(fake.reads.includes('regular'), false);
  assert.equal(fake.metadata[1].entries.some(({ id }) => id === 'WEBVIEW_regular'), true);
});

test('ordinary sign-in return paths remain unrelated to native authorization', async (t) => {
  environment(t);
  for (const next of ['/app', '/settings', '/portal/sign-in']) {
    const fake = browserDouble({ regularUrl: `${ORIGIN}/sign-in?${new URLSearchParams({ next })}` });
    await browserLogin(fake.context);
    assert.ok(fake.writes.every(({ window }) => window === 'authorization'));
  }
});

test('iOS waits for the native browser Cancel control to be visible and enabled before reading post-click metadata', async (t) => {
  environment(t);
  const fake = browserDouble({ ready: [false, 'disabled', true] });
  await browserLogin(fake.context);
  assert.equal(fake.metadata.filter(({ stage }) => stage !== 'app').length, 1);
  assert.equal(fake.metadata[1].readinessPolls, 3);
  assert.deepEqual(fake.switches.filter((name) => name !== 'NATIVE_APP'), ['WEBVIEW_authorization', 'WEBVIEW_authorization']);
  const attachWait = fake.waits.find(({ timeoutMsg }) => timeoutMsg === 'SYSTEM_BROWSER_CONTEXT_UNAVAILABLE');
  assert.deepEqual(attachWait, { timeout: 20000, interval: 500, timeoutMsg: 'SYSTEM_BROWSER_CONTEXT_UNAVAILABLE' });
});

test('an authentication sheet that never becomes ready causes no post-click metadata read or browser attachment', async (t) => {
  environment(t);
  for (const ready of [[false], ['disabled']]) {
    const fake = browserDouble({ ready });
    await assert.rejects(() => browserLogin(fake.context), /SYSTEM_BROWSER_CONTEXT_UNAVAILABLE/);
    assert.equal(fake.metadata.length, 1);
    assert.equal(fake.metadata[0].stage, 'app');
    assert.ok(fake.switches.every((name) => name === 'NATIVE_APP'));
    assert.deepEqual(fake.writes, []);
  }
});

test('a retained authorization identity is never attached while the fresh attempt can reuse its context ID', async (t) => {
  environment(t);
  const old = nativeContext('WEBVIEW_authorization', nativeUrl('o'));
  const retained = nativeContext('WEBVIEW_retained', old.url);
  const fake = browserDouble({ before: [NATIVE, old], after: [[NATIVE, retained],
    [NATIVE, retained, nativeContext('WEBVIEW_authorization', nativeUrl())]] });
  await browserLogin(fake.context);
  assert.equal(fake.metadata.filter(({ stage }) => stage !== 'app').length, 2);
  assert.deepEqual(fake.switches.filter((name) => name !== 'NATIVE_APP'), ['WEBVIEW_authorization', 'WEBVIEW_authorization']);
  assert.deepEqual(fake.writes.map(({ key }) => key), ['#company-slug', '#email', '#password']);
});

test('only retained authorization identities time out without attaching or entering credentials', async (t) => {
  environment(t);
  const old = nativeContext('WEBVIEW_retained', nativeUrl('o'));
  const fake = browserDouble({ before: [NATIVE, old], after: [[NATIVE, old]] });
  await assert.rejects(() => browserLogin(fake.context), /SYSTEM_BROWSER_CONTEXT_UNAVAILABLE/);
  assert.ok(fake.switches.length > 0 && fake.switches.every((name) => name === 'NATIVE_APP'));
  assert.deepEqual(fake.foregroundReads, []);
  assert.deepEqual(fake.writes, []);
});

test('a hidden retained grant page absent from the baseline cannot replace the visible current authorization page', async (t) => {
  environment(t);
  const old = nativeContext('WEBVIEW_retained', nativeUrl('o'));
  const fake = browserDouble({ after: [[NATIVE, old, nativeContext('WEBVIEW_blank', 'about:blank')],
    [NATIVE, old, nativeContext('WEBVIEW_authorization', nativeUrl())]], pageStates: {
    WEBVIEW_retained: { url: old.url, foreground: [{ visibilityState: 'hidden', hasFocus: false }] },
  } });
  const events = [];
  fake.context.record = (event) => events.push(event);
  await browserLogin(fake.context);
  assert.equal(fake.metadata[0].entries.length, 1, 'HIDDEN_RETAINED_PAGE_MUST_BE_ABSENT_BEFORE_CLICK');
  assert.deepEqual(fake.foregroundReads, ['WEBVIEW_retained', 'WEBVIEW_retained', 'WEBVIEW_authorization', 'WEBVIEW_authorization']);
  assert.ok(fake.writes.every(({ window }) => window === 'authorization'));
  assert.equal(fake.switches.includes('WEBVIEW_blank'), false);
  assert.ok(events.every((event) => !JSON.stringify(event).includes('code_challenge') && !JSON.stringify(event).includes(nativeUrl())));
});

test('visibility and focus are both required for a fresh page before any credential entry', async (t) => {
  environment(t);
  for (const foreground of [{ visibilityState: 'hidden', hasFocus: false },
    { visibilityState: 'hidden', hasFocus: true }, { visibilityState: 'visible', hasFocus: false }]) {
    const fake = browserDouble({ pageStates: { WEBVIEW_authorization: { foreground: [foreground] } } });
    await assert.rejects(() => browserLogin(fake.context), /SYSTEM_BROWSER_CONTEXT_UNAVAILABLE/);
    assert.deepEqual(fake.writes, []);
    assert.equal(fake.clicks.includes('connect'), false);
  }
});

test('a hidden page can become foreground on a later native readiness poll without reading native controls in WebView context', async (t) => {
  environment(t);
  const fake = browserDouble({ pageStates: { WEBVIEW_authorization: { foreground: [
    { visibilityState: 'hidden', hasFocus: false }, { visibilityState: 'visible', hasFocus: true },
  ] } } });
  await browserLogin(fake.context);
  assert.deepEqual(fake.switches, ['NATIVE_APP', 'WEBVIEW_authorization', 'NATIVE_APP',
    'WEBVIEW_authorization', 'WEBVIEW_authorization', 'NATIVE_APP']);
  assert.deepEqual(fake.writes.map(({ key }) => key), ['#company-slug', '#email', '#password']);
});

test('a retried URL inspection error preserves its cause and restores native context before every readiness read', async (t) => {
  environment(t);
  const fake = browserDouble({ currentUrl: nativeUrl('d'), pageStates: { WEBVIEW_authorization: {
    foreground: [{ visibilityState: 'hidden', hasFocus: false }],
  } } });
  const waitUntil = fake.driver.waitUntil;
  const failures = [];
  fake.driver.waitUntil = async (callback, options) => {
    if (options.timeoutMsg !== 'SYSTEM_BROWSER_CONTEXT_UNAVAILABLE') return waitUntil(callback, options);
    for (let attempt = 0; attempt < 3; attempt++) {
      try { if (await callback()) return; } catch (error) { failures.push(error); }
    }
    throw failures.at(-1);
  };
  await assert.rejects(() => browserLogin(fake.context), /BROWSER_CONTEXT_METADATA_CHANGED/);
  assert.equal(failures.length, 3);
  assert.ok(failures.every((error) => error.message === 'BROWSER_CONTEXT_METADATA_CHANGED'));
  assert.deepEqual(fake.foregroundReads, []);
  assert.deepEqual(fake.writes, []);
});

test('foreground evidence is checked again after selecting the unique current authorization page', async (t) => {
  environment(t);
  const fake = browserDouble({ pageStates: { WEBVIEW_authorization: { foreground: [
    { visibilityState: 'visible', hasFocus: true }, { visibilityState: 'hidden', hasFocus: false },
  ] } } });
  await assert.rejects(() => browserLogin(fake.context), /SYSTEM_BROWSER_FOREGROUND_CHANGED/);
  assert.deepEqual(fake.writes, []);
});

test('malformed foreground evidence cannot authorize credential entry', async (t) => {
  environment(t);
  const fake = browserDouble({ pageStates: { WEBVIEW_authorization: {
    foreground: [{ visibilityState: 'visible', hasFocus: 'true' }],
  } } });
  await assert.rejects(() => browserLogin(fake.context), /SYSTEM_BROWSER_FOREGROUND_PROOF_REQUIRED/);
  assert.deepEqual(fake.writes, []);
});

test('a malformed baseline authorization page is rejected before the app starts another attempt', async (t) => {
  environment(t);
  const fake = browserDouble({ before: [NATIVE, nativeContext('WEBVIEW_retained', `${ORIGIN}/native/sign-in?platform=ios`)] });
  await assert.rejects(() => browserLogin(fake.context), /INVALID_BROWSER_PKCE_QUERY/);
  assert.deepEqual(fake.clicks, []);
  assert.deepEqual(fake.switches, []);
  assert.deepEqual(fake.writes, []);
});

test('malformed native authorization login tabs still fail before any credential entry', async (t) => {
  environment(t);
  const urls = [
    `${ORIGIN}/native/sign-in`,
    `${ORIGIN}/native/sign-in?platform=ios`,
    `${ORIGIN}/sign-in?${new URLSearchParams({ next: '/native/sign-in?platform=ios' })}`,
    `${ORIGIN}/sign-in?next=/native/sign-in?platform=ios&unexpected=1`,
    `${ORIGIN}/sign-in?next=/native/sign-in?platform=ios&next=/app`,
  ];
  for (const regularUrl of urls) {
    const fake = browserDouble({ regularUrl });
    await assert.rejects(() => browserLogin(fake.context));
    assert.deepEqual(fake.writes, []);
    assert.ok(fake.switches.every((name) => name === 'NATIVE_APP'));
    assert.equal(fake.clicks.includes('connect'), false);
  }
});

test('two fresh foreground native authorization page contexts remain ambiguous before any credential entry', async (t) => {
  environment(t);
  const fake = browserDouble({ duplicateNative: true });
  await assert.rejects(() => browserLogin(fake.context), /AMBIGUOUS_SYSTEM_BROWSER/);
  assert.deepEqual(fake.switches.filter((name) => name !== 'NATIVE_APP'), ['WEBVIEW_authorization', 'WEBVIEW_duplicate']);
  assert.deepEqual(fake.writes, []);
});

test('duplicate fresh page identities remain ambiguous instead of deduplicating to a guessed context', async (t) => {
  environment(t);
  const fake = browserDouble({ after: [[NATIVE, nativeContext('WEBVIEW_authorization', nativeUrl()),
    nativeContext('WEBVIEW_duplicate', nativeUrl())]], pageStates: { WEBVIEW_duplicate: { url: nativeUrl() } } });
  await assert.rejects(() => browserLogin(fake.context), /AMBIGUOUS_SYSTEM_BROWSER/);
  assert.deepEqual(fake.switches.filter((name) => name !== 'NATIVE_APP'), ['WEBVIEW_authorization', 'WEBVIEW_duplicate']);
  assert.deepEqual(fake.writes, []);
});

test('the selected page current URL must retain the complete metadata authorization identity before any credential entry', async (t) => {
  environment(t);
  for (const field of ['code_challenge', 'state', 'platform', 'redirect_uri']) {
    const drift = new URL(nativeUrl());
    drift.searchParams.set(field, { code_challenge: 'd'.repeat(43), state: 'd'.repeat(32),
      platform: 'android', redirect_uri: 'caseops://other/callback' }[field]);
    const fake = browserDouble({ currentUrl: drift.href });
    await assert.rejects(() => browserLogin(fake.context), /BROWSER_CONTEXT_METADATA_CHANGED|WRONG_BROWSER_PLATFORM|WRONG_BROWSER_CALLBACK/);
    assert.deepEqual(fake.switches.filter((name) => name !== 'NATIVE_APP'), ['WEBVIEW_authorization']);
    assert.deepEqual(fake.foregroundReads, []);
    assert.deepEqual(fake.writes, []);
  }
});

test('iOS refuses missing page metadata and preserves the eight-context bound', async (t) => {
  environment(t);
  for (const entries of [['NATIVE_APP', 'WEBVIEW_authorization'],
    [NATIVE, { id: 'WEBVIEW_authorization' }],
    [NATIVE, ...Array.from({ length: 8 }, (_, n) => nativeContext(`WEBVIEW_${n}`, 'about:blank'))]]) {
    const fake = browserDouble({ after: [entries] });
    await assert.rejects(() => browserLogin(fake.context), /IOS_BROWSER_CONTEXT_METADATA_REQUIRED|SYSTEM_BROWSER_CONTEXT_BOUND/);
    assert.ok(fake.switches.every((name) => name === 'NATIVE_APP'));
    assert.deepEqual(fake.writes, []);
  }
});

test('Android retains its existing context and window attachment path', async (t) => {
  environment(t);
  const fake = browserDouble({ platform: 'android', authorizationUrl: nativeUrl('s', 'android') });
  await browserLogin(fake.context);
  assert.deepEqual(fake.metadata, []);
  assert.equal(fake.commands.includes('mobile: getContexts'), false);
  assert.ok(fake.reads.includes('regular'));
  assert.deepEqual(fake.writes.map(({ key }) => key), ['#company-slug', '#email', '#password']);
});

test('a wrong native platform remains rejected before credential entry', async (t) => {
  environment(t);
  const wrongPlatform = new URL(nativeUrl());
  wrongPlatform.searchParams.set('platform', 'android');
  const fake = browserDouble({ authorizationUrl: wrongPlatform.href });
  await assert.rejects(() => browserLogin(fake.context), /WRONG_BROWSER_PLATFORM/);
  assert.deepEqual(fake.writes, []);
});

test('iOS consent polling recognizes the standard WebDriver no-such-alert name before the real alert appears', async (t) => {
  environment(t);
  const fake = browserDouble();
  fake.context.fixture.auth.iosConsent = true;
  let polls = 0, accepted = 0;
  fake.driver.getAlertText = async () => {
    if (++polls === 1) throw Object.assign(new Error('An attempt was made to operate on a modal dialog when one was not open'), { name: 'no such alert' });
    return 'CaseOps wants to use the local fixture to sign in.';
  };
  const execute = fake.driver.execute;
  fake.driver.execute = async (command, args) => {
    if (command === 'mobile: getContexts' || typeof command === 'function') return execute(command, args);
    assert.equal(command, 'mobile: alert');
    if (args.action === 'getButtons') return ['Cancel', 'Continue'];
    assert.deepEqual(args, { action: 'accept', buttonLabel: 'Continue' });
    accepted++;
  };
  fake.driver.waitUntil = async (callback) => {
    for (let attempt = 0; attempt < 3; attempt++) if (await callback()) return;
    assert.fail('UNIT_WAIT_UNSATISFIED');
  };
  await browserLogin(fake.context);
  assert.equal(polls, 2);
  assert.equal(accepted, 1);
  assert.ok(fake.writes.every(({ window }) => window === 'authorization'));
});

test('an unrelated WebDriver alert transport failure is not treated as an absent alert', async (t) => {
  environment(t);
  const fake = browserDouble();
  fake.context.fixture.auth.iosConsent = true;
  fake.driver.getAlertText = async () => { throw Object.assign(new Error('The native transport disappeared'), { name: 'invalid session id' }); };
  await assert.rejects(() => browserLogin(fake.context), /native transport disappeared/);
  assert.deepEqual(fake.writes, []);
  assert.equal(fake.clicks.includes('connect'), false);
});

const FRESH_BROWSER_BOUNDARY = 'OFFLINE_FRESH_BROWSER_LOGIN_ADMITTED';
function freshAccountDouble({ expiresWhileOpening = false, expiresAfterScroll = false, loadingUntil = 0, readyAt = 0,
  principal = 'Context Unit', workspace = 'Unit Workspace', missingSignOut = false, signOutDisabled = false,
  signOutFailure } = {}) {
  let state = 'home', time = 0;
  const clicks = [], reads = [], waits = [], gestures = [], events = [], browserAdmissions = [], callbackRejections = [];
  const protocolClicks = [];
  let signOutElementClicks = 0, signOutLookups = 0;
  const control = (id, text = '') => ({
    elementId: id === 'sign-out' ? 'original-sign-out-element' : id,
    isDisplayed: async () => true,
    isEnabled: async () => id === 'sign-out' ? !signOutDisabled : id !== 'sign-in' || time >= readyAt,
    getText: async () => { reads.push({ id, time }); return text; },
    getAttribute: async (key) => key === 'type' ? 'XCUIElementTypeScrollView' : id,
    click: async () => {
      if (id === 'sign-out') { signOutElementClicks++; assert.fail('NATIVE_SIGN_OUT_ELEMENT_CLICK_FORBIDDEN'); }
      clicks.push({ id, time });
      if (id === 'account-open') state = expiresWhileOpening ? 'signed-out' : 'account';
      else if (id === 'sign-out') state = 'signed-out';
      else if (id === 'sign-in') throw new Error(FRESH_BROWSER_BOUNDARY);
      else assert.fail('UNEXPECTED_OFFLINE_NATIVE_CLICK');
    },
  });
  const driver = {
    switchContext: async (name) => assert.equal(name, 'NATIVE_APP'),
    waitUntil: async (callback, options) => {
      const start = time;
      waits.push(options);
      while (true) {
        // The actual WDIO wait retries rejected predicates. Wrong identity
        // must therefore become a terminal result outside the predicate.
        try { if (await callback()) return; } catch (error) { callbackRejections.push(error.message); }
        if (time - start >= options.timeout) throw new Error(options.timeoutMsg);
        time += options.interval;
      }
    },
    execute: async (command, args) => {
      assert.equal(command, 'mobile: getContexts');
      assert.deepEqual(args, { waitForWebviewMs: 0 });
      browserAdmissions.push(time);
      return [NATIVE];
    },
    getWindowRect: async () => ({ x: 0, y: 0, width: 402, height: 874 }),
    getElementRect: async (id) => {
      assert.equal(id, 'scroll');
      return { x: 0, y: 62, width: 402, height: 778 };
    },
    performActions: async () => { gestures.push(time); if (expiresAfterScroll) state = 'signed-out'; },
    releaseActions: async () => {},
    $$: async (query) => {
      if (query === '-ios predicate string:type == "XCUIElementTypeScrollView"') return [control('scroll')];
      if (query.startsWith('-ios predicate string:')) return [];
      assert.ok(query.startsWith('~'), 'ONLY_OBSERVED_NATIVE_IDS_ALLOWED');
      const id = query.slice(1);
      if (id === 'session-loading' && state === 'signed-out' && time < loadingUntil) return [control(id)];
      if (state === 'home' && id === 'account-open') return [control(id)];
      if (state === 'signed-out' && ['signed-out', 'sign-in'].includes(id)) return [control(id)];
      if (state === 'account') {
        if (id === 'account-principal') return [control(id, principal)];
        if (id === 'account-workspace') return [control(id, workspace)];
        if (id === 'sign-out') { signOutLookups++; if (!missingSignOut) return [control(id)]; }
      }
      return [];
    },
  };
  nativeProtocolDouble(driver);
  const protocolClick = driver.elementClick;
  driver.elementClick = async id => {
    protocolClicks.push(id);
    if (id === 'original-sign-out-element') {
      if (signOutFailure) throw signOutFailure;
      clicks.push({ id: 'sign-out', time }); state = 'signed-out';
    } else await protocolClick(id);
  };
  return { clicks, reads, waits, gestures, events, browserAdmissions, callbackRejections, now: () => time,
    protocolClicks, signOutElementClicks: () => signOutElementClicks, signOutLookups: () => signOutLookups,
    context: { driver, platform: 'ios', record: (event) => events.push(event), fixture: {
      principalLabel: 'Context Unit', workspaceLabel: 'Unit Workspace', auth: {
        mode: 'web-context', webOrigin: ORIGIN, companySlug: 'unit', mfaRequired: true, mfaStage: 'consent',
        emailEnv: 'CASEOPS_MOBILE_CONTEXT_TEST_EMAIL', passwordEnv: 'CASEOPS_MOBILE_CONTEXT_TEST_PASSWORD',
      },
    } } };
}

test('iOS fresh authentication accepts authoritative automatic expiry while Account opens and waits for enabled sign-in', async (t) => {
  environment(t);
  const fake = freshAccountDouble({ expiresWhileOpening: true, loadingUntil: 400, readyAt: 800 });
  await assert.rejects(authenticate(fake.context, { fresh: true }), new RegExp(FRESH_BROWSER_BOUNDARY));
  assert.deepEqual(fake.clicks, [{ id: 'account-open', time: 0 }, { id: 'sign-in', time: 800 }]);
  assert.deepEqual(fake.browserAdmissions, [800]);
  assert.deepEqual(fake.gestures, []);
  assert.deepEqual(fake.reads, []);
  assert.deepEqual(fake.waits.find(({ timeoutMsg }) => timeoutMsg === 'NATIVE_FRESH_ACCOUNT_NOT_READY'),
    { timeout: 20000, interval: 200, timeoutMsg: 'NATIVE_FRESH_ACCOUNT_NOT_READY' });
  assert.equal(fake.events.find(({ boundary }) => boundary === 'native-fresh-authentication-settled').state, 'automatic-sign-out');
  assert.equal(fake.protocolClicks.includes('original-sign-out-element'), false);
  assert.equal(fake.signOutElementClicks(), 0);
  assert.equal(fake.signOutLookups(), 0);
});

test('iOS normal fresh authentication verifies both exact identities before one sign-out and one real browser admission', async (t) => {
  environment(t);
  const fake = freshAccountDouble();
  await assert.rejects(authenticate(fake.context, { fresh: true }), new RegExp(FRESH_BROWSER_BOUNDARY));
  assert.deepEqual(fake.reads.map(({ id }) => id), ['account-principal', 'account-workspace']);
  assert.deepEqual(fake.clicks.map(({ id }) => id), ['account-open', 'sign-out', 'sign-in']);
  assert.equal(fake.browserAdmissions.length, 1);
  assert.equal(fake.events.find(({ boundary }) => boundary === 'native-fresh-authentication-settled').state, 'verified-account');
  assert.equal(fake.protocolClicks.filter(id => id === 'original-sign-out-element').length, 1);
  assert.equal(fake.signOutElementClicks(), 0);
  assert.equal(fake.signOutLookups(), 1);
});

test('verified iOS fresh sign-out preserves stale or lost-ack failure after one original-ID protocol dispatch', async (t) => {
  environment(t);
  for (const message of ['stale element reference', 'socket lost after native logout dispatch']) {
    const failure = new Error(message), fake = freshAccountDouble({ signOutFailure: failure });
    await assert.rejects(authenticate(fake.context, { fresh: true }), error => error === failure);
    assert.deepEqual(fake.protocolClicks, ['account-open', 'original-sign-out-element']);
    assert.equal(fake.signOutLookups(), 1);
    assert.equal(fake.signOutElementClicks(), 0);
    assert.deepEqual(fake.browserAdmissions, []);
    assert.deepEqual(fake.gestures, []);
    assert.equal(fake.events.filter(({ type, action, controlId }) => type === 'native_ui_action'
      && action === 'click' && controlId === 'sign-out').length, 1);
  }
});

test('iOS fresh authentication rejects a wrong principal or workspace before sign-out or browser admission', async (t) => {
  environment(t);
  for (const [options, reason] of [[{ principal: 'Another Principal' }, 'WRONG_PRINCIPAL'],
    [{ workspace: 'Another Workspace' }, 'WRONG_WORKSPACE']]) {
    const fake = freshAccountDouble(options);
    await assert.rejects(authenticate(fake.context, { fresh: true }), new RegExp(reason));
    assert.deepEqual(fake.clicks.map(({ id }) => id), ['account-open']);
    assert.deepEqual(fake.browserAdmissions, []);
    assert.deepEqual(fake.gestures, []);
    assert.deepEqual(fake.callbackRejections, []);
  }
});

test('iOS automatic expiry with permanently disabled sign-in remains blocked at the original twenty-second deadline', async (t) => {
  environment(t);
  const fake = freshAccountDouble({ expiresWhileOpening: true, readyAt: Infinity });
  await assert.rejects(authenticate(fake.context, { fresh: true }), /NATIVE_FRESH_ACCOUNT_NOT_READY/);
  assert.equal(fake.now(), 20000);
  assert.deepEqual(fake.clicks.map(({ id }) => id), ['account-open']);
  assert.deepEqual(fake.browserAdmissions, []);
  assert.deepEqual(fake.gestures, []);
});

test('iOS account-footer discovery retains nine-scroll bound and never clicks a stale disabled sign-out after expiry', async (t) => {
  environment(t);
  const missing = freshAccountDouble({ missingSignOut: true });
  await assert.rejects(authenticate(missing.context, { fresh: true }), /NATIVE_FRESH_ACCOUNT_NOT_READY/);
  assert.equal(missing.gestures.length, 9);
  assert.equal(missing.now(), 20000);
  assert.deepEqual(missing.clicks.map(({ id }) => id), ['account-open']);
  assert.deepEqual(missing.browserAdmissions, []);
  const expired = freshAccountDouble({ signOutDisabled: true, expiresAfterScroll: true });
  await assert.rejects(authenticate(expired.context, { fresh: true }), new RegExp(FRESH_BROWSER_BOUNDARY));
  assert.equal(expired.gestures.length, 1);
  assert.deepEqual(expired.clicks.map(({ id }) => id), ['account-open', 'sign-in']);
  assert.equal(expired.browserAdmissions.length, 1);
});
