import assert from 'node:assert/strict';
import { find, read, selector, visible } from './native-ui.mjs';
import { fixtureMfaCode } from './mfa.mjs';
import { verifiedFile } from './evidence.mjs';

const REQUIRED = ['urlOpen', 'urlValue', 'companySlug', 'email', 'password', 'submit', 'principal', 'emailFact', 'workspace', 'connect'];
export function validateFirefoxRecipe(auth) {
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
  if (recipe.urlCloseMode === 'android-back') assert.equal(recipe.packageName, 'org.mozilla.firefox', 'DEDICATED_FIREFOX_REQUIRED');
  else { assert.ok(!recipe.urlCloseMode || recipe.urlCloseMode === 'locator', 'FIREFOX_URL_DISMISSAL_UNSUPPORTED'); assert.ok(recipe.locators.urlClose, 'FIREFOX_OBSERVED_LOCATORS_REQUIRED'); }
  if (auth.mfaRequired) for (const key of ['mfaCode', 'mfaSubmit']) assert.ok(recipe.locators[key], 'FIREFOX_MFA_LOCATORS_REQUIRED');
  for (const locator of [...Object.values(recipe.locators), ...(recipe.prepare || []), ...(recipe.afterConnect || [])]) {
    assert.ok(['id', 'text', 'label', 'buttonText'].includes(locator.kind), 'SAFE_FIREFOX_LOCATOR_REQUIRED');
    assert.ok(!/certificate|advanced|accept.*risk|proceed.*unsafe|continue.*site|risk.*continue/i.test(locator.value), 'TLS_WARNING_ACTION_FORBIDDEN');
    selector('android', locator.kind, locator.value);
  }
  assert.ok((recipe.prepare?.length || 0) <= 3 && (recipe.afterConnect?.length || 0) <= 2, 'FIREFOX_UI_ACTION_BOUND');
  return recipe;
}

async function locate(context, locator) { return find(context, locator.kind, locator.value, { scroll: true }); }
async function press(context, locator) { await (await locate(context, locator)).click(); }
async function location(context, recipe) {
  assert.equal(await context.driver.getCurrentPackage(), recipe.packageName, 'WRONG_SYSTEM_BROWSER_PACKAGE');
  await press(context, recipe.locators.urlOpen);
  try { return await read(context, recipe.locators.urlValue.kind, recipe.locators.urlValue.value); }
  finally {
    if (recipe.urlCloseMode === 'android-back') {
      const query = selector(context.platform, recipe.locators.urlValue.kind, recipe.locators.urlValue.value);
      for (let count = 0; count < 2 && await visible(context.driver, query); count++) await context.driver.pressKeyCode(4);
      assert.equal(await visible(context.driver, query), undefined, 'FIREFOX_URL_EDITOR_NOT_DISMISSED');
      await locate(context, recipe.locators.urlOpen);
    } else await press(context, recipe.locators.urlClose);
  }
}

// This drives Firefox's real Android accessibility tree. Recipes come from the
// parent's observed, secret-free UI inspection; no XPath/index or webview fiction.
export async function firefoxLogin(context, credentials, authorizationIdentity) {
  assert.equal(context.platform, 'android', 'FIREFOX_ANDROID_ONLY');
  const recipe = validateFirefoxRecipe(context.fixture.auth);
  const { driver, fixture, platform } = context;
  await driver.switchContext('NATIVE_APP');
  await driver.waitUntil(async () => await driver.getCurrentPackage() === recipe.packageName,
    { timeout: 15000, interval: 250, timeoutMsg: 'FIREFOX_CUSTOM_TAB_NOT_OPENED' });
  for (const locator of recipe.prepare || []) await press(context, locator);
  const handoff = authorizationIdentity(await location(context, recipe), fixture.auth.webOrigin, platform);
  for (const key of ['useAnotherAccount', 'signInLink']) {
    const locator = recipe.locators[key];
    if (locator && await visible(driver, selector(platform, locator.kind, locator.value))) await press(context, locator);
  }
  assert.deepEqual(authorizationIdentity(await location(context, recipe), fixture.auth.webOrigin, platform), handoff, 'BROWSER_HANDOFF_CHANGED');
  for (const [key, value] of Object.entries({ companySlug: credentials.companySlug, email: credentials.email, password: credentials.password })) {
    await (await locate(context, recipe.locators[key])).setValue(value);
  }
  await press(context, recipe.locators.submit);
  if (fixture.auth.mfaRequired) {
    await (await locate(context, recipe.locators.mfaCode)).setValue(fixtureMfaCode(fixture.auth));
    await press(context, recipe.locators.mfaSubmit);
  }
  await locate(context, recipe.locators.connect);
  assert.deepEqual(authorizationIdentity(await location(context, recipe), fixture.auth.webOrigin, platform), handoff, 'BROWSER_HANDOFF_CHANGED');
  for (const [key, expected] of Object.entries({ principal: fixture.principalLabel, emailFact: credentials.email,
    workspace: `${fixture.workspaceLabel} / ${credentials.companySlug}` })) {
    assert.equal((await (await locate(context, recipe.locators[key])).getText()).replace(/\s+/g, ' ').trim(), expected, 'WRONG_BROWSER_PRINCIPAL_OR_WORKSPACE');
  }
  assert.equal((await (await locate(context, recipe.locators.connect)).getText()).trim(), 'Connect app', 'REAL_CONNECT_CONTROL_REQUIRED');
  await press(context, recipe.locators.connect);
  for (const locator of recipe.afterConnect || []) await press(context, locator);
  await find(context, 'id', 'account-open');
}
