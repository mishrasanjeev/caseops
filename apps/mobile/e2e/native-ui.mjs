import assert from 'node:assert/strict';

export const IOS_SWIPE_SETTLE_MS = 300;
export const IOS_KEYBOARD_READY_MS = 5000;
export const IOS_FIRST_KEY_SETTLE_MS = 1000;
const IOS_KEYBOARD = '-ios predicate string:type == "XCUIElementTypeKeyboard"';

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
  const iosText = query.startsWith('-ios predicate string:label == ')
    || query.startsWith('-ios predicate string:label BEGINSWITH ');
  if (matches.length > 1 && iosText && matches.every((element) => typeof element.getAttribute === 'function')) {
    // RN can expose a visible inaccessible wrapper and the accessible text
    // leaf with identical content. Keep a solitary inaccessible match visible:
    // privacy absence checks must never discard a still-rendered private label.
    const facts = [];
    for (const element of matches) {
      const raw = await element.getAttribute('accessible');
      facts.push({ element, accessible: raw === true || raw === 'true' ? true : raw === false || raw === 'false' ? false : null,
        label: await element.getAttribute('label'), value: await element.getAttribute('value') });
    }
    const accessible = facts.filter((fact) => fact.accessible === true);
    if (accessible.length === 1 && facts.every((fact) => fact.accessible !== null)) {
      const leaf = accessible[0], value = leaf.value ?? leaf.label;
      if (typeof leaf.label === 'string' && leaf.label.length > 0
        && facts.every((fact) => fact.label === leaf.label && (fact.value == null || fact.value === value))) {
        return leaf.element;
      }
    }
  }
  assert.ok(matches.length <= 1, 'AMBIGUOUS_VISIBLE_NATIVE_LOCATOR');
  return matches[0];
}

export async function swipe(context, direction = 'down') {
  nativeAction(context, 'swipe');
  const window = await context.driver.getWindowRect();
  const { width, height } = window;
  let x = Math.round(width * 0.5);
  let top = Math.round(height * 0.28);
  let bottom = Math.round(height * 0.72);
  if (context.platform === 'ios') {
    const valid = (rect) => rect && [rect.x, rect.y, rect.width, rect.height].every(Number.isFinite)
      && rect.width > 0 && rect.height > 0;
    const contains = (outer, inner) => inner.x >= outer.x && inner.y >= outer.y
      && inner.x + inner.width <= outer.x + outer.width && inner.y + inner.height <= outer.y + outer.height;
    assert.ok(valid(window), 'NATIVE_SCROLL_GEOMETRY_REQUIRED');
    const readRect = async (element, boundary = 'NATIVE_SCROLL_GEOMETRY_REQUIRED') => {
      const rect = await context.driver.getElementRect(element.elementId);
      assert.ok(valid(rect) && contains(window, rect), boundary);
      return rect;
    };
    const scrollView = await visible(context.driver, '-ios predicate string:type == "XCUIElementTypeScrollView"');
    assert.ok(scrollView, 'NATIVE_SCROLL_VIEW_REQUIRED');
    assert.equal(await scrollView.getAttribute('type'), 'XCUIElementTypeScrollView', 'NATIVE_SCROLL_VIEW_REQUIRED');
    const scroll = await readRect(scrollView);
    // The content's measured left gutter avoids nested TextInputs and SwiftUI
    // controls that can consume a center drag without moving the outer view.
    x = scroll.x + 8;
    top = Math.max(top, Math.ceil(scroll.y + 12));
    bottom = Math.min(bottom, Math.floor(scroll.y + scroll.height - 12));
    const occlusions = [];
    const keyboard = await visible(context.driver, '-ios predicate string:type == "XCUIElementTypeKeyboard"');
    if (keyboard) {
      assert.equal(await keyboard.getAttribute('type'), 'XCUIElementTypeKeyboard', 'NATIVE_KEYBOARD_TYPE_REQUIRED');
      const plane = await readRect(keyboard, 'NATIVE_KEYBOARD_GEOMETRY_REQUIRED');
      // A fixed, typed ancestry lookup is needed because the keyboard's
      // predictive container extends above its reported key-plane rectangle.
      const bases = await context.driver.$$('xpath://XCUIElementTypeKeyboard');
      assert.ok(bases.length === 1 && bases[0].elementId === keyboard.elementId, 'NATIVE_KEYBOARD_ANCESTRY_REQUIRED');
      const ancestors = await context.driver.$$('xpath://XCUIElementTypeKeyboard/ancestor::*');
      assert.ok(ancestors.length > 0 && ancestors.length <= 12, 'NATIVE_KEYBOARD_ANCESTRY_REQUIRED');
      occlusions.push(plane);
      for (const ancestor of ancestors) if (await ancestor.isDisplayed()) {
        assert.ok(typeof await ancestor.getAttribute('type') === 'string', 'NATIVE_KEYBOARD_ANCESTRY_REQUIRED');
        const rect = await readRect(ancestor, 'NATIVE_KEYBOARD_GEOMETRY_REQUIRED');
        assert.ok(contains(rect, plane), 'NATIVE_KEYBOARD_ANCESTRY_REQUIRED');
        // Application/Window/root frames cover the whole viewport and do not
        // describe the localized keyboard obstruction.
        if (!contains(rect, window)) occlusions.push(rect);
      }
      bottom = Math.floor((top + Math.min(bottom, plane.y - 12)) / 2);
    }
    assert.ok(bottom - top >= 44, 'SAFE_NATIVE_SCROLL_SPAN_REQUIRED');
    assert.ok(x > scroll.x && x < scroll.x + Math.min(20, scroll.width)
      && top > scroll.y && bottom < scroll.y + scroll.height, 'SAFE_NATIVE_SCROLL_GUTTER_REQUIRED');
    assert.ok(occlusions.every((rect) => top < rect.y && bottom < rect.y), 'NATIVE_KEYBOARD_CONTAINER_OCCLUSION');
    const inputs = await context.driver.$$(
      '-ios predicate string:type == "XCUIElementTypeTextView" OR type == "XCUIElementTypeTextField" OR type == "XCUIElementTypeSecureTextField"');
    assert.ok(inputs.length <= 8, 'NATIVE_INPUT_GEOMETRY_BOUND');
    for (const input of inputs) if (await input.isDisplayed()) {
      assert.ok(['XCUIElementTypeTextView', 'XCUIElementTypeTextField', 'XCUIElementTypeSecureTextField']
        .includes(await input.getAttribute('type')), 'NATIVE_INPUT_GEOMETRY_REQUIRED');
      const rect = await context.driver.getElementRect(input.elementId);
      assert.ok(valid(rect), 'NATIVE_INPUT_GEOMETRY_REQUIRED');
      assert.ok(x < rect.x || x >= rect.x + rect.width, 'NATIVE_SCROLL_GUTTER_INTERSECTS_INPUT');
    }
  }
  await context.driver.performActions([{ type: 'pointer', id: 'native-scroll', parameters: { pointerType: 'touch' }, actions: [
    { type: 'pointerMove', duration: 0, x, y: direction === 'down' ? bottom : top },
    { type: 'pointerDown', button: 0 },
    { type: 'pointerMove', duration: 350, x, y: direction === 'down' ? top : bottom },
    // Lifting a moving finger flings an iOS ScrollView: a short page jumps to
    // its end and carries a row just below the fold under the fixed header, so
    // no gesture ever leaves it visible. Hold still before lifting.
    ...(context.platform === 'ios' ? [{ type: 'pause', duration: IOS_SWIPE_SETTLE_MS }] : []),
    { type: 'pointerUp', button: 0 },
  ] }]);
  await context.driver.releaseActions();
}

export async function find(context, kind, value, { scroll = false, scrollDirection } = {}) {
  const query = selector(context.platform, kind, value);
  return findQuery(context, query, { scroll, scrollDirection, controlId: kind === 'id' ? value : undefined });
}

export async function findQuery(context, query, { scroll = false, scrollDirection, controlId } = {}) {
  assert.ok(scrollDirection === undefined || scroll && ['up', 'down'].includes(scrollDirection), 'VALID_NATIVE_SCROLL_DIRECTION_REQUIRED');
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
      await swipe(context, scrollDirection || (attempt < 3 ? 'up' : 'down'));
    }
  }
}

export async function click(context, kind, value, options) {
  const element = await find(context, kind, value, options);
  await dispatchNativeClick(context, element, kind, value);
}
export async function dispatchNativeClick(context, element, kind, value) {
  const id = element?.elementId;
  assert.ok(typeof id === 'string' && id.length > 0 && id.trim() === id, 'NATIVE_CLICK_ELEMENT_ID_REQUIRED');
  assert.equal(typeof context.driver.elementClick, 'function', 'NATIVE_PROTOCOL_CLICK_REQUIRED');
  nativeAction(context, 'click', kind, value);
  // Element.click() may refetch a stale element and replay its action. A native
  // mutation must retain the resolved identity and dispatch exactly once.
  await context.driver.elementClick(id);
}
export async function read(context, kind, value, options) {
  const element = await find(context, kind, value, options);
  nativeAction(context, 'read', kind, value);
  return element.getText();
}
export async function input(context, kind, value, text, options) {
  const element = await find(context, kind, value, options);
  nativeAction(context, 'input', kind, value);
  if (context.platform !== 'ios') {
    await element.setValue(text);
    return;
  }
  // XCUITest types as soon as focus is requested, and the keyboard relays out
  // after its first keystroke; keys sent during either transition are dropped
  // ("MOBILE-LOCAL-001" reached the API as q=M-LOCAL-001). Focus, wait for the
  // keyboard, type the first character and let the keyboard settle before the
  // rest, then refuse a field whose text differs rather than act on it.
  await dispatchNativeClick(context, element, kind, value);
  await context.driver.waitUntil(async () => !!await visible(context.driver, IOS_KEYBOARD),
    { timeout: IOS_KEYBOARD_READY_MS, interval: 150, timeoutMsg: 'NATIVE_KEYBOARD_NOT_READY' });
  await element.clearValue();
  // An empty field reports its placeholder as value; clearing is the whole entry.
  if (!text) return;
  await element.addValue(text.slice(0, 1));
  await context.driver.waitUntil(async () => await element.getAttribute('value') === text.slice(0, 1),
    { timeout: IOS_KEYBOARD_READY_MS, interval: 150, timeoutMsg: 'NATIVE_INPUT_FIRST_KEY_NOT_ACCEPTED' });
  await context.driver.pause(IOS_FIRST_KEY_SETTLE_MS);
  if (text.length > 1) await element.addValue(text.slice(1));
  assert.equal(await element.getAttribute('value'), text, 'NATIVE_INPUT_VALUE_MISMATCH');
}
export async function expectText(context, text, options = { scroll: true }) { await find(context, 'text', text, options); }
export async function absent(context, kind, value) {
  nativeAction(context, 'absent', kind, value);
  assert.equal(await visible(context.driver, selector(context.platform, kind, value)), undefined, 'PRIVATE_OR_FORBIDDEN_SURFACE_VISIBLE');
}
async function iosHomeScrollVisible(driver, tab) {
  assert.ok(['today', 'matters', 'calendar', 'work'].includes(tab), 'NATIVE_HOME_TAB_REQUIRED');
  const id = `screen-${tab}`;
  const markers = await driver.$$(selector('ios', 'id', id));
  assert.ok(markers.length <= 1, 'HOME_SCREEN_ID_NOT_UNIQUE');
  if (!markers.length) return false;
  const marker = markers[0];
  assert.equal(await marker.getAttribute('type'), 'XCUIElementTypeStaticText', 'HOME_SCREEN_MARKER_TYPE_REQUIRED');
  assert.ok(typeof marker.elementId === 'string' && marker.elementId.length > 0, 'HOME_SCREEN_MARKER_ID_REQUIRED');
  // Bind ancestry to the exact screen marker. Presence alone could describe an
  // inactive pane; an unrelated visible ScrollView cannot establish this route.
  const base = `xpath://XCUIElementTypeStaticText[@name="${id}"]`;
  const bases = await driver.$$(base);
  assert.ok(bases.length <= 1, 'HOME_SCREEN_ID_NOT_UNIQUE');
  if (!bases.length) return false;
  assert.equal(bases[0].elementId, marker.elementId, 'HOME_SCREEN_MARKER_CHANGED');
  const ancestors = await driver.$$(`${base}/ancestor::XCUIElementTypeScrollView`);
  assert.ok(ancestors.length <= 8, 'HOME_SCREEN_SCROLL_ANCESTRY_BOUND');
  const displayed = [];
  for (const ancestor of ancestors) if (await ancestor.isDisplayed()) displayed.push(ancestor);
  assert.ok(displayed.length <= 1, 'HOME_SCREEN_SCROLL_NOT_UNIQUE');
  if (!displayed.length) return false;
  const scroll = displayed[0];
  assert.equal(await scroll.getAttribute('type'), 'XCUIElementTypeScrollView', 'HOME_SCREEN_SCROLL_TYPE_REQUIRED');
  const frame = await driver.getElementRect(scroll.elementId), window = await driver.getWindowRect();
  const valid = (rect) => rect && [rect.x, rect.y, rect.width, rect.height].every(Number.isFinite)
    && rect.width > 0 && rect.height > 0;
  assert.ok(valid(frame) && valid(window) && frame.x >= window.x && frame.y >= window.y
    && frame.x + frame.width <= window.x + window.width && frame.y + frame.height <= window.y + window.height,
  'HOME_SCREEN_SCROLL_FRAME_REQUIRED');
  return true;
}
export async function home(context, tab) {
  await click(context, 'id', `tab-${tab}`);
  for (let depth = 0; depth <= 4; depth++) {
    if (await homeOrBack(context, tab) === 'home') return;
    assert.ok(depth < 4, 'NATIVE_HOME_STACK_BOUND');
    await click(context, 'id', 'back');
  }
}
// A Back transition can briefly show neither the home marker nor a further
// Back. Settle on one of them under the normal lookup bound; requiring another
// Back immediately failed Android NATIVE-08 once the list had already arrived.
async function homeOrBack(context, tab) {
  let state, terminal;
  await context.driver.waitUntil(async () => {
    try {
      if (await visible(context.driver, selector(context.platform, 'id', `screen-${tab}`))) state = 'home';
      else if (context.platform === 'ios' && await iosHomeScrollVisible(context.driver, tab)) state = 'home';
      else if (await visible(context.driver, selector(context.platform, 'id', 'back'))) state = 'back';
      return !!state;
    } catch (error) {
      // Leave the polling loop; preserve ambiguity/proof refusals unchanged.
      terminal = error; return true;
    }
  }, { timeout: 10000, interval: 150, timeoutMsg: 'NATIVE_HOME_STATE_NOT_READY' });
  if (terminal) throw terminal;
  return state;
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
