import assert from 'node:assert/strict';
import { find, read, selector, visible } from './native-ui.mjs';
import { CONSENT_MFA_VERIFIED, fixtureMfaCode, mfaStage } from './mfa.mjs';
import { verifiedFile } from './evidence.mjs';
import { browserStep } from './browser-progress.mjs';

const REQUIRED = ['urlOpen', 'urlValue', 'companySlug', 'email', 'password', 'submit', 'principal', 'emailFact', 'workspace', 'connect', 'appOpen'];
export function validateFirefoxRecipe(auth) {
  const stage = mfaStage(auth);
  const recipe = auth.firefoxUi;
  assert.equal(recipe?.status, 'complete', 'FIREFOX_RECIPE_INCOMPLETE');
  assert.equal(recipe?.packageName, 'org.mozilla.firefox', 'DEDICATED_FIREFOX_REQUIRED');
  assert.equal(recipe.version, '158.0.2', 'REVIEWED_FIREFOX_VERSION_REQUIRED');
  assert.equal(recipe.signerSha256, 'A78B62A5165B4494B2FEAD9E76A280D22D937FEE6251AECE599446B2EA319B04', 'REVIEWED_FIREFOX_SIGNER_REQUIRED');
  assert.equal(recipe.caTrustedThroughSettings, true, 'NORMAL_FIREFOX_CA_TRUST_REQUIRED');
  const bytes = verifiedFile(recipe.locatorEvidencePath, recipe.locatorEvidenceSha256, 65536);
  const evidence = JSON.parse(bytes);
  assert.equal(evidence.kind, 'observed-native-firefox-locators', 'FIREFOX_OBSERVED_LOCATORS_REQUIRED');
  assert.equal(evidence.packageName, recipe.packageName, 'FIREFOX_LOCATOR_IDENTITY_MISMATCH');
  assert.equal(evidence.version, recipe.version, 'FIREFOX_LOCATOR_IDENTITY_MISMATCH');
  assert.deepEqual(evidence.locators, recipe.locators, 'FIREFOX_LOCATOR_IDENTITY_MISMATCH');
  assert.deepEqual(evidence.prepare || [], recipe.prepare || [], 'FIREFOX_PREPARATION_NOT_OBSERVED');
  assert.deepEqual(evidence.afterConnect || [], recipe.afterConnect || [], 'FIREFOX_APP_PROMPT_NOT_OBSERVED');
  assert.equal(evidence.urlCloseMode || 'locator', recipe.urlCloseMode || 'locator', 'FIREFOX_URL_DISMISSAL_NOT_OBSERVED');
  for (const key of REQUIRED) assert.ok(recipe.locators?.[key], 'FIREFOX_OBSERVED_LOCATORS_REQUIRED');
  assert.deepEqual(recipe.locators.appOpen, { kind: 'id', value: 'native-app-open' }, 'EXACT_NATIVE_APP_OPEN_CONTROL_REQUIRED');
  if (recipe.urlCloseMode === 'android-back') assert.equal(recipe.packageName, 'org.mozilla.firefox', 'DEDICATED_FIREFOX_REQUIRED');
  else { assert.ok(!recipe.urlCloseMode || recipe.urlCloseMode === 'locator', 'FIREFOX_URL_DISMISSAL_UNSUPPORTED'); assert.ok(recipe.locators.urlClose, 'FIREFOX_OBSERVED_LOCATORS_REQUIRED'); }
  if (auth.mfaRequired) for (const key of ['mfaCode', 'mfaSubmit']) assert.ok(recipe.locators[key], 'FIREFOX_MFA_LOCATORS_REQUIRED');
  if (stage === 'consent') {
    assert.deepEqual(recipe.locators.mfaCode, { kind: 'id', value: 'native-mfa-code' }, 'EXACT_NATIVE_CONSENT_MFA_FIELD_REQUIRED');
    assert.ok(['text', 'buttonText'].includes(recipe.locators.mfaSubmit.kind), 'EXACT_NATIVE_MFA_VERIFY_CONTROL_REQUIRED');
    assert.equal(recipe.locators.mfaSubmit.value, 'Verify code', 'EXACT_NATIVE_MFA_VERIFY_CONTROL_REQUIRED');
    assert.deepEqual(recipe.locators.mfaVerified, { kind: 'text', value: CONSENT_MFA_VERIFIED }, 'EXACT_NATIVE_MFA_VERIFIED_NOTICE_REQUIRED');
  }
  for (const locator of [...Object.values(recipe.locators), ...(recipe.prepare || []), ...(recipe.afterConnect || [])]) {
    assert.ok(['id', 'text', 'label', 'buttonText'].includes(locator.kind), 'SAFE_FIREFOX_LOCATOR_REQUIRED');
    assert.ok(!/certificate|advanced|accept.*risk|proceed.*unsafe|continue.*site|risk.*continue/i.test(locator.value), 'TLS_WARNING_ACTION_FORBIDDEN');
    selector('android', locator.kind, locator.value);
  }
  assert.ok((recipe.prepare?.length || 0) <= 3 && (recipe.afterConnect?.length || 0) <= 2, 'FIREFOX_UI_ACTION_BOUND');
  return recipe;
}

async function locate(context, key, locator = context.fixture.auth.firefoxUi.locators[key]) {
  browserStep(context, key, 'find');
  // These request-backed states must settle before any gesture can refresh the page.
  return find(context, locator.kind, locator.value, { scroll: !['mfaCode', 'mfaVerified', 'appOpen'].includes(key) });
}
async function press(context, key, locator) {
  const control = await locate(context, key, locator);
  browserStep(context, key, 'click');
  await control.click();
}
async function fill(context, key, value) {
  const control = await locate(context, key);
  browserStep(context, key, 'fill');
  await control.setValue(typeof value === 'function' ? value() : value);
}
async function text(context, key) {
  const control = await locate(context, key);
  browserStep(context, key, 'read');
  return control.getText();
}
async function location(context, recipe) {
  browserStep(context, 'firefox-context', 'check');
  assert.equal(await context.driver.getCurrentPackage(), recipe.packageName, 'WRONG_SYSTEM_BROWSER_PACKAGE');
  await press(context, 'urlOpen');
  try {
    browserStep(context, 'urlValue', 'read');
    return await read(context, recipe.locators.urlValue.kind, recipe.locators.urlValue.value);
  }
  finally {
    if (recipe.urlCloseMode === 'android-back') {
      const query = selector(context.platform, recipe.locators.urlValue.kind, recipe.locators.urlValue.value);
      const editorVisible = async () => { browserStep(context, 'urlEditor', 'check'); return visible(context.driver, query); };
      for (let count = 0; count < 2 && await editorVisible(); count++) {
        browserStep(context, 'urlEditor', 'dismiss');
        await context.driver.pressKeyCode(4);
      }
      browserStep(context, 'urlEditor', 'check');
      assert.equal(await visible(context.driver, query), undefined, 'FIREFOX_URL_EDITOR_NOT_DISMISSED');
      await locate(context, 'urlOpen');
    } else await press(context, 'urlClose');
  }
}

// This drives Firefox's real Android accessibility tree. Recipes come from the
// parent's observed, secret-free UI inspection; no XPath/index or webview fiction.
export async function firefoxLogin(context, credentials, authorizationIdentity) {
  assert.equal(context.platform, 'android', 'FIREFOX_ANDROID_ONLY');
  const recipe = validateFirefoxRecipe(context.fixture.auth);
  const { driver, fixture, platform } = context;
  const stage = mfaStage(fixture.auth);
  browserStep(context, 'firefox-context', 'switch-context');
  await driver.switchContext('NATIVE_APP');
  browserStep(context, 'firefox-context', 'wait');
  await driver.waitUntil(async () => await driver.getCurrentPackage() === recipe.packageName,
    { timeout: 15000, interval: 250, timeoutMsg: 'FIREFOX_CUSTOM_TAB_NOT_OPENED' });
  for (const [index, locator] of (recipe.prepare || []).entries()) await press(context, `prepare-${index}`, locator);
  browserStep(context, 'handoff', 'check');
  const handoff = authorizationIdentity(await location(context, recipe), fixture.auth.webOrigin, platform);
  for (const key of ['useAnotherAccount', 'signInLink']) {
    const locator = recipe.locators[key];
    if (locator) {
      browserStep(context, key, 'check');
      if (await visible(driver, selector(platform, locator.kind, locator.value))) await press(context, key);
    }
  }
  assert.deepEqual(authorizationIdentity(await location(context, recipe), fixture.auth.webOrigin, platform), handoff, 'BROWSER_HANDOFF_CHANGED');
  for (const [key, value] of Object.entries({ companySlug: credentials.companySlug, email: credentials.email, password: credentials.password })) {
    await fill(context, key, value);
  }
  await press(context, 'submit');
  if (stage === 'login') {
    await fill(context, 'mfaCode', () => fixtureMfaCode(fixture.auth));
    await press(context, 'mfaSubmit');
  }
  const verifyIdentity = async () => {
    browserStep(context, 'identity', 'check');
    await locate(context, 'connect');
    assert.deepEqual(authorizationIdentity(await location(context, recipe), fixture.auth.webOrigin, platform), handoff, 'BROWSER_HANDOFF_CHANGED');
    for (const [key, expected] of Object.entries({ principal: fixture.principalLabel, emailFact: credentials.email,
      workspace: `${fixture.workspaceLabel} / ${credentials.companySlug}` })) {
      assert.equal((await text(context, key)).replace(/\s+/g, ' ').trim(), expected, 'WRONG_BROWSER_PRINCIPAL_OR_WORKSPACE');
    }
    assert.equal((await text(context, 'connect')).trim(), 'Connect app', 'REAL_CONNECT_CONTROL_REQUIRED');
  };
  await verifyIdentity();
  await press(context, 'connect');
  if (stage === 'consent') {
    await locate(context, 'mfaCode');
    assert.deepEqual(authorizationIdentity(await location(context, recipe), fixture.auth.webOrigin, platform), handoff, 'BROWSER_HANDOFF_CHANGED');
    await fill(context, 'mfaCode', () => fixtureMfaCode(fixture.auth));
    assert.equal((await text(context, 'mfaSubmit')).trim(), 'Verify code', 'REAL_NATIVE_MFA_VERIFY_CONTROL_REQUIRED');
    await press(context, 'mfaSubmit');
    await locate(context, 'mfaVerified');
    await verifyIdentity();
    assert.equal(await visible(driver, selector(platform, recipe.locators.mfaCode.kind, recipe.locators.mfaCode.value)), undefined,
      'NATIVE_CONSENT_MFA_NOT_COMPLETED');
    await press(context, 'connect');
  }
  const appOpen = await locate(context, 'appOpen');
  browserStep(context, 'appOpen', 'read');
  assert.equal((await appOpen.getText()).trim(), 'Open CaseOps', 'REAL_NATIVE_APP_OPEN_CONTROL_REQUIRED');
  browserStep(context, 'appOpen', 'check');
  assert.equal(await appOpen.isEnabled(), true, 'NATIVE_APP_OPEN_CONTROL_DISABLED');
  browserStep(context, 'appOpen', 'click');
  await appOpen.click();
  for (const [index, locator] of (recipe.afterConnect || []).entries()) await press(context, `afterConnect-${index}`, locator);
  browserStep(context, 'native-return', 'wait');
  await find(context, 'id', 'account-open');
}
