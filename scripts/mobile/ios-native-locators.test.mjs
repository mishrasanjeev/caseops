import assert from 'node:assert/strict';
import test from 'node:test';
import { absent, click, dispatchNativeClick, findQuery, home, input, IOS_SWIPE_SETTLE_MS, selector, swipe, visible } from '../../apps/mobile/e2e/native-ui.mjs';
import { freshNoteAbsent, scenarios, selectMatterActivity, selectMatterDraft, verifyIosCalendarRow } from '../../apps/mobile/e2e/journeys.mjs';

function element(id, { displayed = true, accessible = 'false', label = 'CaseOps', value = label } = {}) {
  return { elementId: id, isDisplayed: async () => displayed,
    getAttribute: async (key) => ({ accessible, label, value })[key] };
}
const driver = (...elements) => ({ $$: async () => elements });

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

test('native click resolves one exact element and sends one protocol command on Android and iOS', async () => {
  for (const platform of ['android', 'ios']) {
    const queries = [], dispatches = [], records = [];
    const target = { elementId: 'native-unit-element', isDisplayed: async () => true,
      click: () => assert.fail('ELEMENT_CLICK_REFETCH_PATH_FORBIDDEN') };
    const context = { platform, record: row => records.push(row), driver: {
      $$: async query => { queries.push(query); return [target]; },
      waitUntil: async (callback, options) => { assert.equal(options.timeout, 10000); assert.ok(await callback()); },
      elementClick: async id => dispatches.push(id),
    } };
    await click(context, 'id', 'files-upload');
    assert.deepEqual(queries, [selector(platform, 'id', 'files-upload')]);
    assert.deepEqual(dispatches, ['native-unit-element']);
    assert.deepEqual(records, [
      { type: 'native_ui_action', action: 'find', controlId: 'files-upload' },
      { type: 'native_ui_action', action: 'click', controlId: 'files-upload' },
    ]);
  }
});

test('stale-element and lost-ack native clicks preserve the original failure without refetch or replay', async () => {
  for (const platform of ['android', 'ios']) for (const message of ['stale element reference', 'socket lost after dispatch']) {
    const failure = new Error(message);
    let finds = 0, dispatches = 0, fallbackClicks = 0;
    const records = [];
    const context = { platform, record: row => records.push(row), driver: {
      $$: async () => { finds++; return [{ elementId: 'original-native-element', isDisplayed: async () => true,
        click: async () => { fallbackClicks++; } }]; },
      waitUntil: async callback => assert.ok(await callback()),
      elementClick: async id => { assert.equal(id, 'original-native-element'); dispatches++; throw failure; },
    } };
    await assert.rejects(click(context, 'id', 'files-upload'), error => error === failure);
    assert.deepEqual({ finds, dispatches, fallbackClicks }, { finds: 1, dispatches: 1, fallbackClicks: 0 });
    assert.equal(records.filter(({ action }) => action === 'click').length, 1);
  }
});

test('native click refuses absent or inexact element IDs and missing protocol support without fallback', async () => {
  let dispatches = 0, fallbacks = 0;
  const context = { platform: 'ios', driver: { elementClick: async () => { dispatches++; } } };
  for (const elementId of [undefined, null, 1, '', ' ', ' native-id', 'native-id ']) {
    await assert.rejects(dispatchNativeClick(context, { elementId, click: async () => { fallbacks++; } }, 'id', 'files-upload'),
      /NATIVE_CLICK_ELEMENT_ID_REQUIRED/);
  }
  await assert.rejects(dispatchNativeClick({ ...context, driver: {} },
    { elementId: 'native-id', click: async () => { fallbacks++; } }, 'id', 'files-upload'), /NATIVE_PROTOCOL_CLICK_REQUIRED/);
  assert.deepEqual({ dispatches, fallbacks }, { dispatches: 0, fallbacks: 0 });
});

test('ambiguous native controls remain rejected before any click dispatch', async () => {
  for (const platform of ['android', 'ios']) {
    let dispatches = 0, finds = 0;
    const context = { platform, driver: {
      $$: async () => { finds++; return ['one', 'two'].map(elementId => ({ elementId, isDisplayed: async () => true })); },
      waitUntil: async callback => callback(), elementClick: async () => { dispatches++; },
    } };
    await assert.rejects(click(context, 'id', 'files-upload'), /AMBIGUOUS_VISIBLE_NATIVE_LOCATOR/);
    assert.equal(finds, 1);
    assert.equal(dispatches, 0);
  }
});

test('measured native dispatch uses the given identity without locating it again', async () => {
  const dispatches = [], records = [];
  await dispatchNativeClick({ platform: 'ios', record: row => records.push(row), driver: {
    $$: () => assert.fail('MEASURED_CONTROL_REFETCH_FORBIDDEN'), elementClick: async id => dispatches.push(id),
  } }, { elementId: 'measured-upload', click: () => assert.fail('ELEMENT_CLICK_REFETCH_PATH_FORBIDDEN') }, 'id', 'files-upload');
  assert.deepEqual(dispatches, ['measured-upload']);
  assert.deepEqual(records, [{ type: 'native_ui_action', action: 'click', controlId: 'files-upload' }]);
});

test('an explicit known scroll direction reaches a control without changing the nine-swipe bound', async () => {
  const target = element('target'), moves = [];
  const context = { platform: 'android', driver: {
    $$: async () => moves.length >= 2 ? [target] : [],
    waitUntil: async condition => { if (!await condition()) throw new Error('NATIVE_CONTROL_NOT_VISIBLE'); },
    getWindowRect: async () => ({ width: 400, height: 800 }),
    performActions: async actions => { moves.push(actions[0].actions); }, releaseActions: async () => {},
  } };
  assert.equal(await findQuery(context, 'id=target', { scroll: true, scrollDirection: 'down' }), target);
  assert.equal(moves.length, 2);
  assert.ok(moves.every(actions => actions[0].y > actions[2].y));
  context.driver.$$ = async () => [];
  moves.length = 0;
  await assert.rejects(findQuery(context, 'id=missing', { scroll: true, scrollDirection: 'up' }), /NATIVE_CONTROL_NOT_VISIBLE/);
  assert.equal(moves.length, 9);
  assert.ok(moves.every(actions => actions[0].y < actions[2].y));
  await assert.rejects(findQuery(context, 'id=target', { scroll: true, scrollDirection: 'sideways' }), /VALID_NATIVE_SCROLL_DIRECTION_REQUIRED/);
});

test('iOS exact text resolves the one accessible leaf behind the actual Application and RN wrappers', async () => {
  const app = element('application', { value: null });
  const wrapper = element('wrapper');
  const leaf = element('leaf', { accessible: 'true' });
  for (const elements of [[app, wrapper, leaf], [leaf, wrapper, app]]) {
    assert.equal(await visible(driver(...elements), selector('ios', 'text', 'CaseOps')), leaf);
  }
});

test('iOS saved-note-ID text prefix also resolves identical RN wrapper and accessible leaf', async () => {
  const label = 'Saved note ID: saved-unit-id';
  const wrapper = element('wrapper', { label });
  const leaf = element('leaf', { accessible: true, label });
  assert.equal(await visible(driver(wrapper, leaf), '-ios predicate string:label BEGINSWITH "Saved note ID: "'), leaf);
});

test('a solitary visible inaccessible private label remains visible and fails the privacy absence assertion', async () => {
  const label = 'Retained private matter label';
  const wrapper = element('private-wrapper', { label });
  const one = driver(wrapper);
  assert.equal(await visible(one, selector('ios', 'text', label)), wrapper);
  await assert.rejects(() => absent({ driver: one, platform: 'ios' }, 'text', label), /PRIVATE_OR_FORBIDDEN_SURFACE_VISIBLE/);
});

test('two accessible iOS matches still fail rather than selecting the first', async () => {
  await assert.rejects(() => visible(driver(element('one', { accessible: 'true' }), element('two', { accessible: true })),
    selector('ios', 'text', 'CaseOps')), /AMBIGUOUS_VISIBLE_NATIVE_LOCATOR/);
});

test('unknown accessibility metadata cannot authorize iOS text disambiguation', async () => {
  await assert.rejects(() => visible(driver(element('one', { accessible: 'true' }), element('unknown', { accessible: null })),
    selector('ios', 'text', 'CaseOps')), /AMBIGUOUS_VISIBLE_NATIVE_LOCATOR/);
});

test('different labels or conflicting displayed values are not semantic duplicates', async () => {
  for (const other of [element('other', { label: 'Other label' }), element('other', { value: 'Conflicting value' })]) {
    await assert.rejects(() => visible(driver(element('leaf', { accessible: 'true' }), other),
      selector('ios', 'text', 'CaseOps')), /AMBIGUOUS_VISIBLE_NATIVE_LOCATOR/);
  }
});

test('iOS test IDs and Android text retain strict visible-match ambiguity', async () => {
  for (const query of [selector('ios', 'id', 'signed-out'), selector('android', 'text', 'CaseOps')]) {
    await assert.rejects(() => visible(driver(element('wrapper'), element('leaf', { accessible: 'true' })), query),
      /AMBIGUOUS_VISIBLE_NATIVE_LOCATOR/);
  }
});

test('a non-text iOS predicate cannot silently select an accessible match', async () => {
  await assert.rejects(() => visible(driver(element('wrapper'), element('leaf', { accessible: 'true' })),
    '-ios predicate string:TRUEPREDICATE'), /AMBIGUOUS_VISIBLE_NATIVE_LOCATOR/);
});

test('hidden duplicates do not hide a visible inaccessible label', async () => {
  const privateLabel = element('private-label');
  assert.equal(await visible(driver(element('hidden-leaf', { displayed: false, accessible: 'true' }), privateLabel),
    selector('ios', 'text', 'CaseOps')), privateLabel);
});

function homeDouble(platform, { active = true, headingVisible = false, rawCount = 1, baseCount = 1,
  baseId = 'home-marker', markerType = 'XCUIElementTypeStaticText', ancestorCount = 1,
  ancestorVisible = true, activateOnBack = true, frame = { x: 0, y: 125, width: 402, height: 656 } } = {}) {
  let backClicks = 0;
  const queries = [];
  const marker = { elementId: 'home-marker', isDisplayed: async () => active && headingVisible,
    getAttribute: async (key) => { assert.equal(key, 'type'); return markerType; } };
  const scroll = { elementId: 'owned-home-scroll', isDisplayed: async () => active && ancestorVisible,
    getAttribute: async (key) => { assert.equal(key, 'type'); return 'XCUIElementTypeScrollView'; } };
  return { queries, backClicks: () => backClicks, context: { platform, driver: nativeProtocolDouble({
    waitUntil: async (callback) => assert.ok(await callback()),
    $$: async (query) => {
      queries.push(query);
      if (query === selector(platform, 'id', 'tab-calendar')) return [{ isDisplayed: async () => true, click: async () => {} }];
      if (query === selector(platform, 'id', 'back')) return [{ isDisplayed: async () => true, click: async () => { backClicks++; if (activateOnBack) active = true; } }];
      if (query === selector(platform, 'id', 'screen-calendar')) return Array(rawCount).fill(marker);
      if (query === 'xpath://XCUIElementTypeStaticText[@name="screen-calendar"]') return Array(baseCount).fill({ elementId: baseId });
      if (query === 'xpath://XCUIElementTypeStaticText[@name="screen-calendar"]/ancestor::XCUIElementTypeScrollView') return Array(ancestorCount).fill(scroll);
      assert.fail('UNRELATED_VISIBLE_SCROLL_CANNOT_PROVE_HOME');
    },
    getElementRect: async (id) => { assert.equal(id, 'owned-home-scroll'); return frame; },
    getWindowRect: async () => ({ x: 0, y: 0, width: 402, height: 874 }),
  }) } };
}

test('iOS home preserves the visible-heading fast path without ancestry queries', async () => {
  const fake = homeDouble('ios', { headingVisible: true });
  await home(fake.context, 'calendar');
  assert.deepEqual(fake.queries, ['~tab-calendar', '~screen-calendar']);
  assert.equal(fake.backClicks(), 0);
});

test('a scrolled active iOS Calendar is proved by its exact marker own visible ScrollView without an extra Back', async () => {
  const fake = homeDouble('ios');
  await home(fake.context, 'calendar');
  assert.equal(fake.backClicks(), 0);
  assert.ok(fake.queries.includes('xpath://XCUIElementTypeStaticText[@name="screen-calendar"]/ancestor::XCUIElementTypeScrollView'));
});

test('an inactive iOS pane does not pass until the original Back loop reveals its own ScrollView', async () => {
  const fake = homeDouble('ios', { active: false });
  await home(fake.context, 'calendar');
  assert.equal(fake.backClicks(), 1);
});

test('mere screen-marker presence or unrelated visible content cannot bypass the four-Back home bound', async () => {
  for (const options of [{ active: false, activateOnBack: false }, { ancestorVisible: false }, { ancestorCount: 0 }, { baseCount: 0 }, { rawCount: 0 }]) {
    const fake = homeDouble('ios', options);
    await assert.rejects(() => home(fake.context, 'calendar'), /NATIVE_HOME_STACK_BOUND/);
    assert.equal(fake.backClicks(), 4);
  }
});

test('iOS scrolled-home proof refuses duplicate IDs, changed typed base, ambiguous ancestry, wrong marker type and invalid frames', async () => {
  for (const options of [{ rawCount: 2 }, { baseCount: 2 }, { baseId: 'unrelated-marker' }, { markerType: 'XCUIElementTypeOther' },
    { ancestorCount: 2 }, { ancestorCount: 9 }, { frame: null }, { frame: { x: 0, y: NaN, width: 402, height: 656 } },
    { frame: { x: 0, y: 125, width: 402, height: 900 } }]) {
    const fake = homeDouble('ios', options);
    await assert.rejects(() => home(fake.context, 'calendar'), /HOME_SCREEN_/);
    assert.equal(fake.backClicks(), 0);
  }
});

test('Android home retains its visible-heading and original Back proof without iOS hierarchy queries', async () => {
  const fake = homeDouble('android', { active: false, headingVisible: true });
  await home(fake.context, 'calendar');
  assert.equal(fake.backClicks(), 1);
  assert.ok(fake.queries.every((query) => !query.startsWith('xpath:')));
});

test('input forwards optional bounded scroll discovery while preserving its default lookup budget and exact value', async () => {
  for (const scroll of [false, true]) {
    let moved = !scroll;
    const waits = [], writes = [], gestures = [];
    const context = { platform: 'android', driver: {
      waitUntil: async (callback, options) => { waits.push(options); assert.ok(await callback()); },
      $$: async (query) => { assert.equal(query, 'id=calendar-date-input'); return moved ? [{ isDisplayed: async () => true,
        setValue: async (value) => writes.push(value) }] : []; },
      getWindowRect: async () => ({ width: 402, height: 874 }),
      performActions: async (actions) => { gestures.push(actions); moved = true; }, releaseActions: async () => {},
    } };
    await input(context, 'id', 'calendar-date-input', '2026-10-25', scroll ? { scroll: true } : undefined);
    assert.deepEqual(writes, ['2026-10-25']);
    assert.equal(gestures.length, scroll ? 1 : 0);
    assert.ok(waits.every(({ timeout, interval }) => timeout === (scroll ? 1500 : 10000) && interval === 150));
  }
});

const workLabel = 'Seeded task, MAT-001 · Seeded matter, task · 25 Oct 2026 · open';
function workDouble(platform, { label = workLabel, text = workLabel, type = 'XCUIElementTypeButton',
  accessible = 'true', duplicates = false } = {}) {
  const item = { kind: 'task', id: 'seeded-task', title: 'Seeded task',
    matter: { identityLabel: 'MAT-001', title: 'Seeded matter' }, metaLabel: 'task · 25 Oct 2026 · open' };
  let rowClicks = 0;
  const childQueries = [];
  const shown = { isDisplayed: async () => true, click: async () => {} };
  const row = { ...shown, click: async () => { rowClicks++; }, getText: async () => text,
    getAttribute: async (key) => {
      assert.equal(platform, 'ios', 'ANDROID_ROW_ATTRIBUTES_MUST_NOT_REPLACE_CHILD_CHECKS');
      return { label, type, accessible }[key];
    },
    $$: async (query) => {
      assert.equal(platform, 'android', 'IOS_GROUPED_ROW_DESCENDANTS_MUST_NOT_BE_QUERIED');
      childQueries.push(query);
      return [shown];
    } };
  const context = { platform, fixture: { today: item }, driver: {
    waitUntil: async (callback) => assert.ok(await callback(), 'UNIT_CONTROL_NOT_VISIBLE'),
    $$: async (query) => {
      if (query === selector(platform, 'id', 'today-item-task-seeded-task')) return duplicates ? [row, row] : [row];
      if (query === selector(platform, 'id', 'matter-code')) return [{ ...shown, getText: async () => 'MAT-001' }];
      if ([selector(platform, 'id', 'tab-today'), selector(platform, 'id', 'screen-today'),
        selector(platform, 'text', 'Seeded matter')].includes(query)) return [shown];
      assert.fail('UNEXPECTED_ROW_QUERY');
    },
  } };
  nativeProtocolDouble(context.driver);
  return { context, childQueries, rowClicks: () => rowClicks };
}

test('NATIVE-03 proves the complete ordered iOS accessible row label and text without querying grouped descendants', async () => {
  for (const accessible of [true, 'true']) {
    const fake = workDouble('ios', { accessible });
    await scenarios.find(({ id }) => id === 'NATIVE-03').run(fake.context);
    assert.equal(fake.rowClicks(), 1);
    assert.deepEqual(fake.childQueries, []);
  }
});

test('iOS work row verification rejects every wrong field, field order, text, role or accessibility state before opening', async () => {
  for (const patch of [{ label: 'Other task, MAT-001 · Seeded matter, task · 25 Oct 2026 · open' },
    { label: 'Seeded task, OTHER · Seeded matter, task · 25 Oct 2026 · open' },
    { label: 'Seeded task, MAT-001 · Other matter, task · 25 Oct 2026 · open' },
    { label: 'Seeded task, MAT-001 · Seeded matter, task · 25 Oct 2026 · closed' },
    { label: 'MAT-001 · Seeded matter, Seeded task, task · 25 Oct 2026 · open' },
    { text: 'Seeded task' }, { type: 'XCUIElementTypeStaticText' }, { accessible: 'false' }, { accessible: null }]) {
    const fake = workDouble('ios', patch);
    await assert.rejects(() => scenarios.find(({ id }) => id === 'NATIVE-03').run(fake.context), /SEEDED_WORK_ROW_/);
    assert.equal(fake.rowClicks(), 0);
  }
});

test('work row IDs retain strict uniqueness and Android retains all three scoped text assertions', async () => {
  const ambiguous = workDouble('ios', { duplicates: true });
  await assert.rejects(() => scenarios.find(({ id }) => id === 'NATIVE-03').run(ambiguous.context), /AMBIGUOUS_VISIBLE_NATIVE_LOCATOR/);
  assert.equal(ambiguous.rowClicks(), 0);
  const android = workDouble('android');
  await scenarios.find(({ id }) => id === 'NATIVE-03').run(android.context);
  assert.deepEqual(android.childQueries, ['Seeded task', 'MAT-001 · Seeded matter', 'task · 25 Oct 2026 · open']
    .map((text) => selector('android', 'text', text)));
});

const calendarLabel = 'Recorded hearing, MAT-001 · Seeded matter, 25 Oct 2026 · hearing · 10:30 Asia/Kolkata';
function calendarRowDouble({ label = calendarLabel, text = calendarLabel, type = 'XCUIElementTypeButton',
  accessible = 'true', count = 1 } = {}) {
  const queries = [];
  const row = { isDisplayed: async () => true, getText: async () => text,
    getAttribute: async (key) => ({ label, type, accessible })[key],
    $$: async () => assert.fail('GROUPED_CALENDAR_DESCENDANTS_MUST_NOT_BE_QUERIED') };
  return { queries, row, event: { eventId: 'opaque:v3-event-42', hearingId: 'unrelated-hearing', title: 'Recorded hearing',
    matter: { identityLabel: 'MAT-001', title: 'Seeded matter' }, metaLabel: '25 Oct 2026 · hearing · 10:30 Asia/Kolkata' },
  context: { platform: 'ios', driver: {
    waitUntil: async (callback) => assert.ok(await callback()),
    $$: async (query) => { queries.push(query); assert.equal(query, '~event-opaque:v3-event-42'); return Array(count).fill(row); },
  } } };
}

test('iOS Calendar binds the opaque event ID and complete ordered accessible aggregate without descendant queries', async () => {
  const fake = calendarRowDouble();
  assert.equal(await verifyIosCalendarRow(fake.context, fake.event), fake.row);
  assert.deepEqual(fake.queries, ['~event-opaque:v3-event-42']);
});

test('iOS Calendar rejects wrong event fields, order, text, role, accessibility or duplicate IDs', async () => {
  for (const options of [{ label: 'Other hearing, MAT-001 · Seeded matter, 25 Oct 2026 · hearing · 10:30 Asia/Kolkata' },
    { label: 'Recorded hearing, OTHER · Seeded matter, 25 Oct 2026 · hearing · 10:30 Asia/Kolkata' },
    { label: 'Recorded hearing, MAT-001 · Other matter, 25 Oct 2026 · hearing · 10:30 Asia/Kolkata' },
    { label: 'Recorded hearing, MAT-001 · Seeded matter, 26 Oct 2026 · hearing · 10:30 Asia/Kolkata' },
    { label: 'MAT-001 · Seeded matter, Recorded hearing, 25 Oct 2026 · hearing · 10:30 Asia/Kolkata' },
    { text: 'Recorded hearing' }, { type: 'XCUIElementTypeStaticText' }, { accessible: false }, { accessible: null }, { count: 2 }]) {
    const fake = calendarRowDouble(options);
    await assert.rejects(() => verifyIosCalendarRow(fake.context, fake.event), /SEEDED_CALENDAR_ROW_|AMBIGUOUS_VISIBLE_NATIVE_LOCATOR/);
  }
});

test('a missing Calendar event ID cannot be derived from its hearing identity or visible title', async () => {
  const fake = calendarRowDouble();
  delete fake.event.eventId;
  await assert.rejects(() => verifyIosCalendarRow(fake.context, fake.event), /SEEDED_CALENDAR_EVENT_ID_REQUIRED/);
  assert.deepEqual(fake.queries, []);
});

function draftRowDouble({ label = 'Seeded draft, in_review · Read-only', text = label,
  type = 'XCUIElementTypeButton', accessible = 'true', enabled = true, count = 1, containers = 1 } = {}) {
  let clicks = 0, releases = 0;
  const queries = [], waits = [], gestures = [];
  const draft = { title: 'Seeded draft', statusLabel: 'in_review · Read-only' };
  const button = { elementId: 'resolved-draft-row', isDisplayed: async () => true, isEnabled: async () => enabled, getText: async () => text,
    getAttribute: async (key) => ({ label, type, accessible })[key], click: async () => assert.fail('SCOPED_DRAFT_ELEMENT_CLICK_FORBIDDEN'),
    $$: async () => assert.fail('GROUPED_DRAFT_DESCENDANTS_MUST_NOT_BE_QUERIED') };
  const container = { elementId: 'draft-scroll', isDisplayed: async () => true,
    getAttribute: async (key) => { assert.equal(key, 'type'); return 'XCUIElementTypeScrollView'; }, $$: async (query) => {
    queries.push(['scoped', query]);
    assert.equal(query, '-ios predicate string:type == "XCUIElementTypeButton" AND label == "Seeded draft, in_review · Read-only"');
    return Array(count).fill(button);
  } };
  return { draft, queries, waits, gestures, clicks: () => clicks, releases: () => releases, context: { platform: 'ios', driver: {
    elementClick: async id => { assert.equal(id, 'resolved-draft-row'); clicks++; },
    waitUntil: async (callback, options) => { waits.push(options); assert.ok(await callback(), options?.timeoutMsg); },
    $$: async (query) => {
      queries.push(['global', query]);
      if (query === '-ios predicate string:type == "XCUIElementTypeKeyboard"') return [];
      if (query === '-ios predicate string:type == "XCUIElementTypeScrollView"') return [container];
      if (query === '-ios predicate string:type == "XCUIElementTypeTextView" OR type == "XCUIElementTypeTextField" OR type == "XCUIElementTypeSecureTextField"') return [];
      assert.equal(query, '~matter-detail', 'DRAFT_MUST_NOT_USE_GLOBAL_TITLE_OR_BUTTON_LOOKUP');
      return Array(containers).fill(container);
    },
    getWindowRect: async () => ({ x: 0, y: 0, width: 402, height: 874 }),
    getElementRect: async (id) => { assert.equal(id, 'draft-scroll'); return { x: 0, y: 125, width: 402, height: 715 }; },
    performActions: async (actions) => gestures.push(actions), releaseActions: async () => { releases++; },
  } } };
}

test('iOS matter draft selection is scoped to the actual Matter detail and exact two-field accessible Button', async () => {
  const fake = draftRowDouble();
  await selectMatterDraft(fake.context, fake.draft);
  assert.equal(fake.clicks(), 1);
  assert.deepEqual(fake.queries.map(([scope]) => scope), ['global', 'scoped']);
  assert.deepEqual(fake.gestures, []);
});

test('iOS draft selection rejects wrong title/status/text/role, inaccessible or disabled rows and ambiguous scopes', async () => {
  for (const options of [{ label: 'Other draft, in_review · Read-only' }, { label: 'Seeded draft, approved · Read-only' },
    { label: 'in_review · Read-only, Seeded draft' }, { text: 'Seeded draft' }, { type: 'XCUIElementTypeStaticText' },
    { accessible: false }, { accessible: null }, { enabled: false }, { count: 2 }, { containers: 2 }]) {
    const fake = draftRowDouble(options);
    await assert.rejects(() => selectMatterDraft(fake.context, fake.draft), /SEEDED_DRAFT_ROW_|AMBIGUOUS_VISIBLE_NATIVE_LOCATOR/);
    assert.equal(fake.clicks(), 0);
  }
});

test('a missing scoped draft retains ten finite reads and the original three-up/six-down sweep without global fallback', async () => {
  const fake = draftRowDouble({ count: 0 });
  await assert.rejects(() => selectMatterDraft(fake.context, fake.draft), /SEEDED_DRAFT_ROW_UNAVAILABLE/);
  assert.equal(fake.clicks(), 0);
  assert.equal(fake.gestures.length, 9);
  assert.equal(fake.releases(), 9);
  const waits = fake.waits.filter(({ timeoutMsg }) => timeoutMsg === 'SEEDED_DRAFT_ROW_UNAVAILABLE');
  assert.equal(waits.length, 10);
  assert.ok(waits.every(({ timeout, interval }) => timeout === 1500 && interval === 150));
  assert.ok(fake.gestures.slice(0, 3).every((actions) => actions[0].actions[0].y === 245));
  assert.ok(fake.gestures.slice(3).every((actions) => actions[0].actions[0].y === 629));
});

test('Android matter draft selection retains the exact title leaf lookup', async () => {
  const queries = [];
  let clicks = 0;
  await selectMatterDraft({ platform: 'android', driver: nativeProtocolDouble({
    waitUntil: async (callback) => assert.ok(await callback()),
    $$: async (query) => { queries.push(query); return [{ isDisplayed: async () => true, click: async () => { clicks++; } }]; },
  }) }, { title: 'Seeded draft', statusLabel: 'in_review · Read-only' });
  assert.deepEqual(queries, [selector('android', 'text', 'Seeded draft')]);
  assert.equal(clicks, 1);
});

test('both Calendar journeys bind their first date entry to the actual stable input ID on Android and iOS', async () => {
  for (const platform of ['android', 'ios']) for (const id of ['NATIVE-10', 'NATIVE-11']) {
    const stop = new Error('UNIT_STOP_BEFORE_CALENDAR_REQUEST');
    const queries = [], values = [], waits = [];
    const shown = { isDisplayed: async () => true, click: async () => {} };
    const context = { platform, fixture: { calendar: { day: '2026-10-25' } }, driver: {
      waitUntil: async (callback, options) => { waits.push(options); assert.ok(await callback()); },
      $$: async (query) => {
        queries.push(query);
        if (query === selector(platform, 'id', 'calendar-date-input')) return [{ ...shown,
          setValue: async (value) => { values.push(value); throw stop; } }];
        if ([selector(platform, 'id', 'tab-calendar'), selector(platform, 'id', 'screen-calendar')].includes(query)) return [shown];
        assert.fail('CALENDAR_ALIAS_OR_UNRELATED_CONTROL_QUERIED');
      },
    } };
    nativeProtocolDouble(context.driver);
    await assert.rejects(() => scenarios.find((scenario) => scenario.id === id).run(context), (error) => error === stop);
    assert.deepEqual(values, ['2026-10-25']);
    assert.equal(waits.at(-1).timeout, 1500, 'CALENDAR_INPUT_MUST_ADMIT_BOUNDED_SCROLL_DISCOVERY');
    assert.equal(queries.includes(selector(platform, 'label', 'Agenda date, YYYY-MM-DD')), false);
  }
});

const matterView = '-ios predicate string:type == "XCUIElementTypeSegmentedControl" AND label == "Matter view"';
const activityButton = '-ios predicate string:type == "XCUIElementTypeButton" AND label == "Activity"';
function activityDouble({ parentCount = 1, buttonCount = 1, enabled = true, label = 'Activity',
  type = 'XCUIElementTypeButton', parentType = 'XCUIElementTypeSegmentedControl', parentLabel = 'Matter view' } = {}) {
  let clicked = 0;
  const queries = [];
  const button = { elementId: 'resolved-activity-button', isDisplayed: async () => true, isEnabled: async () => enabled,
    getAttribute: async (key) => ({ label, type })[key],
    getText: async () => assert.fail('IOS_SEGMENT_SELECTION_VALUE_IS_NOT_ITS_LABEL'), click: async () => assert.fail('SCOPED_ACTIVITY_ELEMENT_CLICK_FORBIDDEN') };
  const parent = { isDisplayed: async () => true,
    getAttribute: async (key) => ({ label: parentLabel, type: parentType })[key],
    $$: async (query) => { queries.push(query); assert.equal(query, activityButton); return Array(buttonCount).fill(button); } };
  return { clicked: () => clicked, queries, context: { platform: 'ios', driver: {
    elementClick: async id => { assert.equal(id, 'resolved-activity-button'); clicked++; },
    waitUntil: async (callback) => assert.ok(await callback()),
    $$: async (query) => { queries.push(query); assert.equal(query, matterView); return Array(parentCount).fill(parent); },
  } } };
}

test('Activity selection uses the unique exact native segmented-control scope and button label', async () => {
  const fake = activityDouble();
  await selectMatterActivity(fake.context);
  assert.equal(fake.clicked(), 1);
  assert.deepEqual(fake.queries, [matterView, activityButton]);
});

test('Activity selection refuses ambiguous, disabled, missing, drifted or incorrectly typed native controls', async () => {
  for (const patch of [{ parentCount: 2 }, { buttonCount: 2 }, { buttonCount: 0 }, { enabled: false },
    { label: 'Other activity' }, { type: 'XCUIElementTypeStaticText' }, { parentType: 'XCUIElementTypeOther' }, { parentLabel: 'Unrelated view' }]) {
    const fake = activityDouble(patch);
    await assert.rejects(() => selectMatterActivity(fake.context), /AMBIGUOUS_VISIBLE_NATIVE_LOCATOR|MATTER_/);
    assert.equal(fake.clicked(), 0);
  }
});

test('Android Activity navigation retains its exact ID', async () => {
  let clicked = 0;
  const queries = [];
  await selectMatterActivity({ platform: 'android', driver: nativeProtocolDouble({
    waitUntil: async (callback) => assert.ok(await callback()),
    $$: async (query) => { queries.push(query); return [{ isDisplayed: async () => true, click: async () => { clicked++; } }]; },
  }) });
  assert.deepEqual(queries, ['id=matter-activity']);
  assert.equal(clicked, 1);
});

test('empty iOS note proof reads only a verified TextView raw value, never its label-fallback text', async () => {
  for (const value of [null, '']) {
    await freshNoteAbsent({ platform: 'ios', driver: {
      waitUntil: async (callback) => assert.ok(await callback()),
      $$: async (query) => {
        assert.equal(query, '~note-input');
        return [{ isDisplayed: async () => true,
          getAttribute: async (key) => ({ type: 'XCUIElementTypeTextView', value })[key],
          getText: async () => assert.fail('EMPTY_IOS_TEXT_WOULD_FALL_BACK_TO_INTERNAL_NOTE_LABEL') }];
      },
    } });
  }
});

test('iOS note absence rejects private text, whitespace, unknown values and a wrong native input type', async () => {
  for (const [type, value] of [['XCUIElementTypeTextView', 'Retained unsaved unit text'], ['XCUIElementTypeTextView', ' '],
    ['XCUIElementTypeTextView', 'Internal note'], ['XCUIElementTypeTextView', undefined], ['XCUIElementTypeTextView', false],
    ['XCUIElementTypeTextView', 0], ['XCUIElementTypeStaticText', null]]) {
    await assert.rejects(() => freshNoteAbsent({ platform: 'ios', driver: {
      waitUntil: async (callback) => assert.ok(await callback()),
      $$: async () => [{ isDisplayed: async () => true, getAttribute: async (key) => ({ type, value })[key] }],
    } }), /MEMORY_ONLY_NOTE_RESTORED|NOTE_INPUT_TEXT_VIEW_REQUIRED/);
  }
});

test('Android empty-note proof retains its existing exact text contract', async () => {
  for (const text of ['', 'Retained unit text']) {
    const context = { platform: 'android', driver: {
      waitUntil: async (callback) => assert.ok(await callback()),
      $$: async (query) => { assert.equal(query, 'id=note-input'); return [{ isDisplayed: async () => true, getText: async () => text }]; },
    } };
    if (text === '') await freshNoteAbsent(context);
    else await assert.rejects(() => freshNoteAbsent(context), /MEMORY_ONLY_NOTE_RESTORED/);
  }
});

function swipeDouble(platform, { count = 1, displayed = true, type = 'XCUIElementTypeKeyboard',
  rect = { x: 0, y: 583, width: 402, height: 233 }, baseId = 'unit-keyboard', scrollCount = 1,
  scrollRect = { x: 0, y: 125, width: 402, height: 715 }, scrollType = 'XCUIElementTypeScrollView',
  ancestors = [
    { type: 'XCUIElementTypeApplication', rect: { x: 0, y: 0, width: 402, height: 874 } },
    { type: 'XCUIElementTypeWindow', rect: { x: 0, y: 0, width: 402, height: 874 } },
    { type: 'XCUIElementTypeOther', rect: { x: 0, y: 0, width: 402, height: 874 } },
    { type: 'XCUIElementTypeOther', rect: { x: 0, y: 566, width: 402, height: 308 } },
    { type: 'XCUIElementTypeOther', rect: { x: 0, y: 583, width: 402, height: 233 } },
  ], inputs = [{ type: 'XCUIElementTypeTextView', rect: { x: 21, y: 331, width: 360, height: 199 } }] } = {}) {
  const actions = [], queries = [];
  let releases = 0;
  const rectangles = new Map([['unit-keyboard', rect], ['unit-scroll', scrollRect]]);
  const geometryElement = (id, fact) => {
    rectangles.set(id, fact.rect);
    return { elementId: id, isDisplayed: async () => fact.displayed !== false,
      getAttribute: async (key) => { assert.equal(key, 'type', 'SCROLL_MUST_NOT_READ_PRIVATE_INPUT_VALUES'); return fact.type; } };
  };
  const ancestorElements = ancestors.map((fact, i) => geometryElement(`unit-ancestor-${i}`, fact));
  const inputElements = inputs.map((fact, i) => geometryElement(`unit-input-${i}`, fact));
  return { actions, queries, releases: () => releases, context: { platform, driver: {
    getWindowRect: async () => ({ x: 0, y: 0, width: 402, height: 874 }),
    $$: async (query) => {
      queries.push(query);
      assert.equal(platform, 'ios', 'ANDROID_KEYBOARD_BEHAVIOR_MUST_REMAIN_UNCHANGED');
      if (query === '-ios predicate string:type == "XCUIElementTypeKeyboard"') return Array.from({ length: count }, () => ({ elementId: 'unit-keyboard',
        isDisplayed: async () => displayed, getAttribute: async () => type }));
      if (query === '-ios predicate string:type == "XCUIElementTypeScrollView"') return Array.from({ length: scrollCount }, () => ({
        elementId: 'unit-scroll', isDisplayed: async () => true, getAttribute: async () => scrollType }));
      if (query === 'xpath://XCUIElementTypeKeyboard') return [{ elementId: baseId }];
      if (query === 'xpath://XCUIElementTypeKeyboard/ancestor::*') return ancestorElements;
      if (query === '-ios predicate string:type == "XCUIElementTypeTextView" OR type == "XCUIElementTypeTextField" OR type == "XCUIElementTypeSecureTextField"') return inputElements;
      assert.fail('UNRELATED_SCROLL_GEOMETRY_QUERY');
    },
    getElementRect: async (id) => { assert.ok(rectangles.has(id)); return rectangles.get(id); },
    performActions: async (action) => actions.push(action), releaseActions: async () => { releases++; },
  } } };
}

test('iOS keyboard swipe uses the proven outer gutter and stays above its predictive container and away from nested text input', async () => {
  for (const direction of ['down', 'up']) {
    const fake = swipeDouble('ios');
    await swipe(fake.context, direction);
    const actions = fake.actions[0][0].actions;
    assert.deepEqual(actions[0], { type: 'pointerMove', duration: 0, x: 8, y: direction === 'down' ? 408 : 245 });
    assert.deepEqual(actions[2], { type: 'pointerMove', duration: 350, x: 8, y: direction === 'down' ? 245 : 408 });
    assert.ok(actions[0].y < 566 && actions[2].y < 566, 'POINT_MUST_AVOID_CONTAINER_ABOVE_KEYPLANE_583');
    assert.ok(actions[0].x < 21 && actions[2].x < 21, 'POINT_MUST_AVOID_VISIBLE_MULTILINE_CHILD');
    assert.equal(fake.releases(), 1);
  }
});

test('iOS swipe holds still before lifting so momentum cannot carry a short page past a row', async () => {
  const fake = swipeDouble('ios', { count: 0 });
  await swipe(fake.context);
  assert.equal(IOS_SWIPE_SETTLE_MS, 300);
  assert.deepEqual(fake.actions[0][0].actions.map(({ type }) => type), ['pointerMove', 'pointerDown', 'pointerMove', 'pause', 'pointerUp']);
  assert.deepEqual(fake.actions[0][0].actions[3], { type: 'pause', duration: 300 });
});

test('Android retains its original center swipe without any iOS geometry query', async () => {
  const fake = swipeDouble('android');
  await swipe(fake.context);
  assert.deepEqual(fake.actions[0][0].actions[0], { type: 'pointerMove', duration: 0, x: 201, y: 629 });
  assert.equal(fake.actions[0][0].actions[2].y, 245);
  assert.deepEqual(fake.actions[0][0].actions.map(({ type }) => type), ['pointerMove', 'pointerDown', 'pointerMove', 'pointerUp']);
  assert.deepEqual(fake.queries, []);
});

test('iOS without a visible keyboard uses the outer gutter without keyboard ancestry reads', async () => {
  for (const options of [{ count: 0 }, { displayed: false }]) {
    const fake = swipeDouble('ios', options);
    await swipe(fake.context);
    assert.deepEqual(fake.actions[0][0].actions[0], { type: 'pointerMove', duration: 0, x: 8, y: 629 });
    assert.equal(fake.actions[0][0].actions[2].y, 245);
    assert.ok(fake.queries.every((query) => !query.startsWith('xpath:')));
  }
});

test('iOS no-keyboard gutter clamps both gesture ends inside the measured outer ScrollView', async () => {
  const fake = swipeDouble('ios', { count: 0, scrollRect: { x: 0, y: 300, width: 402, height: 300 } });
  await swipe(fake.context);
  assert.deepEqual(fake.actions[0][0].actions[0], { type: 'pointerMove', duration: 0, x: 8, y: 588 });
  assert.deepEqual(fake.actions[0][0].actions[2], { type: 'pointerMove', duration: 350, x: 8, y: 312 });
});

test('iOS no-keyboard scroll ambiguity, unknown frames, too-small spans and an input over the gutter reject without touching', async () => {
  for (const options of [{ scrollCount: 0 }, { scrollCount: 2 }, { scrollType: 'XCUIElementTypeOther' }, { scrollRect: null },
    { scrollRect: { x: 0, y: NaN, width: 402, height: 300 } }, { scrollRect: { x: 0, y: 300, width: 402, height: 40 } },
    { inputs: [{ type: 'XCUIElementTypeTextView', rect: { x: 0, y: 331, width: 402, height: 199 } }] }]) {
    const fake = swipeDouble('ios', { ...options, count: 0 });
    await assert.rejects(() => swipe(fake.context), /AMBIGUOUS_VISIBLE_NATIVE_LOCATOR|NATIVE_SCROLL_|SAFE_NATIVE_SCROLL_/);
    assert.deepEqual(fake.actions, []);
  }
});

test('ambiguous, wrong-type, unknown, out-of-window or too-small keyboard geometry permits no gesture', async () => {
  for (const options of [{ count: 2 }, { type: 'XCUIElementTypeOther' }, { rect: null }, { rect: {} },
    { rect: { x: 0, y: NaN, width: 402, height: 233 } }, { rect: { x: -1, y: 583, width: 402, height: 233 } },
    { rect: { x: 0, y: 583, width: 402, height: -1 } }, { rect: { x: 0, y: 583, width: 500, height: 233 } },
    { rect: { x: 0, y: 800, width: 402, height: 233 } }, { rect: { x: 0, y: 300, width: 402, height: 233 } }]) {
    const fake = swipeDouble('ios', options);
    await assert.rejects(() => swipe(fake.context), /AMBIGUOUS_VISIBLE_NATIVE_LOCATOR|NATIVE_KEYBOARD_|SAFE_NATIVE_SCROLL_SPAN_REQUIRED/);
    assert.deepEqual(fake.actions, []);
    assert.equal(fake.releases(), 0);
  }
});

test('keyboard gutter rejects unknown or ambiguous outer scroll and keyboard ancestry before any touch', async () => {
  for (const options of [{ scrollCount: 0 }, { scrollCount: 2 }, { scrollType: 'XCUIElementTypeOther' }, { scrollRect: null },
    { scrollRect: { x: 0, y: 300, width: 402, height: 40 } }, { baseId: 'changed-keyboard' }, { ancestors: [] },
    { ancestors: Array.from({ length: 13 }, () => ({ type: 'XCUIElementTypeOther', rect: { x: 0, y: 0, width: 402, height: 874 } })) },
    { ancestors: [{ type: 'XCUIElementTypeOther', rect: null }] },
    { ancestors: [{ type: 'XCUIElementTypeOther', rect: { x: 0, y: 380, width: 402, height: 494 } }] }]) {
    const fake = swipeDouble('ios', options);
    await assert.rejects(() => swipe(fake.context), /AMBIGUOUS_VISIBLE_NATIVE_LOCATOR|NATIVE_SCROLL_|NATIVE_KEYBOARD_|SAFE_NATIVE_SCROLL_/);
    assert.deepEqual(fake.actions, []);
  }
});

test('a visible input covering the measured gutter or unknown input geometry forbids the gesture without reading its text', async () => {
  for (const inputs of [[{ type: 'XCUIElementTypeTextView', rect: { x: 0, y: 331, width: 402, height: 199 } }],
    [{ type: 'XCUIElementTypeTextField', rect: null }], [{ type: 'XCUIElementTypeOther', rect: { x: 21, y: 331, width: 360, height: 199 } }],
    Array.from({ length: 9 }, () => ({ type: 'XCUIElementTypeTextView', rect: { x: 21, y: 331, width: 360, height: 199 } }))]) {
    const fake = swipeDouble('ios', { inputs });
    await assert.rejects(() => swipe(fake.context), /NATIVE_SCROLL_GUTTER_INTERSECTS_INPUT|NATIVE_INPUT_GEOMETRY_/);
    assert.deepEqual(fake.actions, []);
  }
});
