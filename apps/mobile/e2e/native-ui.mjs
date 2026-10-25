import assert from 'node:assert/strict';

export function selector(platform, kind, value) {
  assert.ok(['android', 'ios'].includes(platform), 'NATIVE_PLATFORM_REQUIRED');
  assert.ok(typeof value === 'string' && value.length > 0 && value.length <= 4000, 'NATIVE_LOCATOR_VALUE_REQUIRED');
  if (kind === 'id') {
    assert.ok(/^[a-zA-Z0-9_.:-]{1,160}$/.test(value)
      || platform === 'android' && value.length <= 160 && /^[a-zA-Z][a-zA-Z0-9_.]*:id\/[a-zA-Z0-9_]+$/.test(value), 'INVALID_TEST_ID');
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

export function nativeAction(context, action, kind, value) {
  assert.ok(['find', 'click', 'read', 'input', 'absent', 'swipe', 'restart'].includes(action), 'SAFE_NATIVE_ACTION_REQUIRED');
  const event = { type: 'native_ui_action', action };
  if (kind === 'id') {
    selector(context.platform, kind, value);
    event.controlId = value;
  }
  context.record?.(event);
}

export async function visible(driver, query) {
  const matches = [];
  for (const element of await driver.$$(query)) if (await element.isDisplayed()) matches.push(element);
  assert.ok(matches.length <= 1, 'AMBIGUOUS_VISIBLE_NATIVE_LOCATOR');
  return matches[0];
}

export async function swipe(context, direction = 'down') {
  nativeAction(context, 'swipe');
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
  return findQuery(context, query, { scroll, controlId: kind === 'id' ? value : undefined });
}

export async function findQuery(context, query, { scroll = false, controlId } = {}) {
  nativeAction(context, 'find', controlId ? 'id' : undefined, controlId);
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

export async function click(context, kind, value, options) {
  const element = await find(context, kind, value, options);
  nativeAction(context, 'click', kind, value);
  await element.click();
}
export async function read(context, kind, value, options) {
  const element = await find(context, kind, value, options);
  nativeAction(context, 'read', kind, value);
  return element.getText();
}
export async function input(context, kind, value, text) {
  const element = await find(context, kind, value);
  nativeAction(context, 'input', kind, value);
  await element.setValue(text);
}
export async function expectText(context, text, options = { scroll: true }) { await find(context, 'text', text, options); }
export async function absent(context, kind, value) {
  nativeAction(context, 'absent', kind, value);
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
  nativeAction(context, 'restart');
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
