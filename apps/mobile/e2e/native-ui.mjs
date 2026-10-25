import assert from 'node:assert/strict';

export function selector(platform, kind, value) {
  assert.ok(['android', 'ios'].includes(platform), 'NATIVE_PLATFORM_REQUIRED');
  assert.ok(typeof value === 'string' && value.length > 0 && value.length <= 4000, 'NATIVE_LOCATOR_VALUE_REQUIRED');
  if (kind === 'id') {
    assert.match(value, /^[a-zA-Z0-9_.:-]{1,160}$/, 'INVALID_TEST_ID');
    return platform === 'android' ? `id=${value}` : `~${value}`;
  }
  if (kind === 'label') return `~${value}`;
  if (kind === 'buttonText') {
    assert.equal(platform, 'android', 'ANDROID_BUTTON_LOCATOR_REQUIRED');
    return `android=new UiSelector().className("android.widget.Button").text(${JSON.stringify(value)})`;
  }
  assert.equal(kind, 'text', 'NATIVE_LOCATOR_KIND_REQUIRED');
  return platform === 'android'
    ? `android=new UiSelector().text(${JSON.stringify(value)})`
    : `-ios predicate string:label == ${JSON.stringify(value)} OR value == ${JSON.stringify(value)}`;
}

export async function visible(driver, query) {
  const matches = [];
  for (const element of await driver.$$(query)) if (await element.isDisplayed()) matches.push(element);
  assert.ok(matches.length <= 1, 'AMBIGUOUS_VISIBLE_NATIVE_LOCATOR');
  return matches[0];
}

export async function swipe(context, direction = 'down') {
  const { width, height } = await context.driver.getWindowRect();
  const x = Math.round(width * 0.5);
  const top = Math.round(height * 0.28), bottom = Math.round(height * 0.72);
  await context.driver.performActions([{ type: 'pointer', id: 'native-scroll', parameters: { pointerType: 'touch' }, actions: [
    { type: 'pointerMove', duration: 0, x, y: direction === 'down' ? bottom : top },
    { type: 'pointerDown', button: 0 },
    { type: 'pointerMove', duration: 350, x, y: direction === 'down' ? top : bottom },
    { type: 'pointerUp', button: 0 },
  ] }]);
  await context.driver.releaseActions();
}

export async function find(context, kind, value, { scroll = false } = {}) {
  const query = selector(context.platform, kind, value);
  return findQuery(context, query, { scroll });
}

export async function findQuery(context, query, { scroll = false } = {}) {
  let element;
  for (let attempt = 0; attempt <= (scroll ? 9 : 0); attempt++) {
    try {
      await context.driver.waitUntil(async () => !!(element = await visible(context.driver, query)),
        { timeout: scroll ? 1500 : 10000, interval: 150, timeoutMsg: 'NATIVE_CONTROL_NOT_VISIBLE' });
      return element;
    } catch (error) {
      if (error?.message?.includes('AMBIGUOUS_VISIBLE_NATIVE_LOCATOR')) throw error;
      if (!scroll || attempt === 9) throw new Error('NATIVE_CONTROL_NOT_VISIBLE');
      // A prior assertion may have ended below the next control. Sweep up before down.
      await swipe(context, attempt < 3 ? 'up' : 'down');
    }
  }
}

export async function click(context, kind, value, options) { await (await find(context, kind, value, options)).click(); }
export async function read(context, kind, value, options) { return (await find(context, kind, value, options)).getText(); }
export async function input(context, kind, value, text) { await (await find(context, kind, value)).setValue(text); }
export async function expectText(context, text, options = { scroll: true }) { await find(context, 'text', text, options); }
export async function absent(context, kind, value) {
  assert.equal(await visible(context.driver, selector(context.platform, kind, value)), undefined, 'PRIVATE_OR_FORBIDDEN_SURFACE_VISIBLE');
}
export async function home(context, tab) {
  await click(context, 'id', `tab-${tab}`);
  for (let depth = 0; depth <= 4; depth++) {
    if (await visible(context.driver, selector(context.platform, 'id', `screen-${tab}`))) return;
    assert.ok(depth < 4, 'NATIVE_HOME_STACK_BOUND');
    await click(context, 'id', 'back');
  }
}
export async function restart(context) {
  await context.driver.terminateApp(context.fixture.appId);
  await context.driver.activateApp(context.fixture.appId);
  await context.driver.switchContext('NATIVE_APP');
}

export async function backgroundAndResume(context) {
  const { driver, platform, fixture: { appId } } = context;
  assert.equal(await driver.queryAppState(appId), 4, 'HOME_REQUIRES_FOREGROUND_APP');
  if (platform === 'android') {
    assert.equal(await driver.getCurrentPackage(), appId, 'HOME_REQUIRES_EXACT_APP_PACKAGE');
    await driver.pressKeyCode(3);
  } else {
    assert.equal(platform, 'ios', 'NATIVE_PLATFORM_REQUIRED');
    await driver.execute('mobile: pressButton', { name: 'home' });
  }
  let backgroundState;
  await driver.waitUntil(async () => {
    backgroundState = await driver.queryAppState(appId);
    const leftPackage = platform !== 'android' || await driver.getCurrentPackage() !== appId;
    return leftPackage && (platform === 'android' ? backgroundState === 3 : [2, 3].includes(backgroundState));
  }, { timeout: 10000, interval: 150, timeoutMsg: 'HOME_DID_NOT_BACKGROUND_RUNNING_APP' });
  context.record?.({ type: 'native_home_observed', platform, leftApp: true, backgroundState });
  await driver.activateApp(appId);
  await driver.switchContext('NATIVE_APP');
  await driver.waitUntil(async () => await driver.queryAppState(appId) === 4
    && (platform !== 'android' || await driver.getCurrentPackage() === appId),
  { timeout: 10000, interval: 150, timeoutMsg: 'HOME_RESUME_DID_NOT_FOREGROUND_EXACT_APP' });
}
