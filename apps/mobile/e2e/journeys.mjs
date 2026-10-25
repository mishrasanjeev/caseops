import assert from 'node:assert/strict';
import { authenticate } from './browser-handoff.mjs';
import { FixtureUnavailable, ownerControl, SEARCH_KINDS } from './fixture-contract.mjs';
import { absent, backgroundAndResume, click, expectText, find, findQuery, home, input, read, restart, selector, visible } from './native-ui.mjs';
import { localJson } from './support.mjs';
import { validateTraffic } from './traffic.mjs';
import { validateAuthorizationTraffic } from './mfa.mjs';
import { configuredSessionDeleteAdmission, proveCurrentSessionDeletion } from './session-admission.mjs';

export { authenticate };
export async function traffic(context) {
  const state = await localJson(`${context.fixture.gatewayUrl}/__caseops_e2e/status`);
  if (context.gatewayBaseline) return validateTraffic(state, context.gatewayBaseline);
  assert.equal(state.runId, context.fixture.gatewayRunId, 'WRONG_GATEWAY_RUN');
  assert.equal(state.overflow, false, 'GATEWAY_EVIDENCE_OVERFLOW');
  assert.equal(state.markerRejected, 0, 'NATIVE_OR_BROWSER_MARKER_MISSING');
  assert.equal(state.routeRejected, 0, 'UNADMITTED_NATIVE_OR_BROWSER_ROUTE');
  assert.ok(Number.isSafeInteger(state.lastSequence) && state.lastSequence >= 0 && state.lastSequence <= 500, 'BOUNDED_REQUEST_LEDGER_REQUIRED');
  assert.equal(state.requests.length, state.lastSequence, 'REQUEST_LEDGER_INCOMPLETE');
  for (let index = 0; index < state.requests.length; index++) {
    assert.equal(state.requests[index].sequence, index + 1, 'REQUEST_LEDGER_SEQUENCE_MISMATCH');
    if ('nativeMarker' in state.requests[index]) assert.equal(state.requests[index].nativeMarker, true, 'APP_REQUEST_MARKER_NOT_PRESENT');
  }
  return state;
}
export function delta(before, after) {
  assert.equal(before.runId, after.runId, 'GATEWAY_RUN_CHANGED');
  assert.ok(after.lastSequence >= before.lastSequence, 'GATEWAY_LEDGER_RESET');
  assert.deepEqual(after.requests.slice(0, before.requests.length).map(({ sequence, method, route }) => ({ sequence, method, route })),
    before.requests.map(({ sequence, method, route }) => ({ sequence, method, route })), 'GATEWAY_HISTORY_CHANGED');
  return after.requests.filter((request) => request.sequence > before.lastSequence);
}
export function requestCount(requests, method, route) { return requests.filter((row) => row.method === method && row.route === route).length; }
function successfulRead(requests, route) { assert.ok(requests.some((row) => row.method === 'GET' && row.route === route && row.status === 200), 'AUTHORITATIVE_REREAD_MISSING'); }
function noNotePost(requests, matterId) { assert.equal(requestCount(requests, 'POST', `/api/matters/${matterId}/notes`), 0, 'UNEXPECTED_NOTE_SUBMIT'); }
export function readOnlyTraffic(requests) {
  assert.ok(requests.some((row) => row.method === 'GET'), 'READ_ONLY_READ_MISSING');
  assert.equal(requests.filter((row) => !['GET', 'HEAD', 'OPTIONS'].includes(row.method)
    && !(row.method === 'POST' && row.route === '/api/auth/native/refresh')).length, 0, 'FORMAL_OR_GENERATION_MUTATION_FROM_READ_ONLY_VIEW');
}

export async function openMatter(context, matter = context.fixture.matter, search = matter.search || matter.searches[0].value) {
  await home(context, 'matters');
  await input(context, 'id', 'matter-search', search);
  await click(context, 'id', 'matter-search-submit');
  await click(context, 'id', `matter-row-${matter.id}`, { scroll: true });
  assert.equal(await read(context, 'id', 'matter-code'), matter.identityLabel, 'WRONG_MATTER');
  await expectText(context, matter.title);
}
async function reloadMatter(context, matter) {
  const before = await traffic(context);
  await click(context, 'id', 'matter-reload', { scroll: true });
  // Reload replaces content with loading, so a retained pre-click text is not evidence.
  await context.driver.waitUntil(async () => {
    const requests = delta(before, await traffic(context));
    return requests.some((row) => row.method === 'GET' && row.route === `/api/matters/${matter.id}/workspace` && row.status === 200);
  }, { timeout: 10000, interval: 200, timeoutMsg: 'MATTER_RELOAD_READ_MISSING' });
  await restart(context);
  await authenticate(context);
  await openMatter(context, matter);
  assert.equal(await read(context, 'id', 'matter-code'), matter.identityLabel, 'RELOADED_MATTER_IDENTITY_MISMATCH');
}
async function editor(context, matter = context.fixture.matter) {
  await openMatter(context, matter);
  await click(context, 'id', 'note-add', { scroll: true });
  await find(context, 'id', 'note-input');
}
export async function discard(context, action = 'leave') {
  assert.ok(['stay', 'leave'].includes(action), 'EXACT_NOTE_DISCARD_ACTION_REQUIRED');
  await click(context, 'id', 'back');
  if (context.platform === 'android') {
    assert.equal(await read(context, 'id', `${context.fixture.appId}:id/alert_title`), 'Discard unsaved note?', 'WRONG_NOTE_DISCARD_DIALOG');
    assert.equal(await read(context, 'id', 'android:id/button2'), 'STAY', 'WRONG_NOTE_DISCARD_STAY_BUTTON');
    assert.equal(await read(context, 'id', 'android:id/button1'), 'LEAVE EDITOR', 'WRONG_NOTE_DISCARD_LEAVE_BUTTON');
    await click(context, 'id', action === 'stay' ? 'android:id/button2' : 'android:id/button1');
  } else {
    assert.equal(context.platform, 'ios', 'NATIVE_PLATFORM_REQUIRED');
    await expectText(context, 'Discard unsaved note?', { scroll: false });
    await find(context, 'text', 'Stay');
    await find(context, 'text', 'Leave editor');
    await click(context, 'text', action === 'stay' ? 'Stay' : 'Leave editor');
  }
}
async function row(context, item) {
  const element = await find(context, 'id', `today-item-${item.kind}-${item.id}`, { scroll: true });
  for (const text of [item.title, `${item.matter.identityLabel} \u00b7 ${item.matter.title}`, item.metaLabel]) {
    assert.ok(await visible(element, selector(context.platform, 'text', text)), 'SEEDED_WORK_ROW_VALUE_MISMATCH');
  }
  return element;
}
async function freshNoteAbsent(context) {
  assert.equal(await (await find(context, 'id', 'note-input')).getText(), '', 'MEMORY_ONLY_NOTE_RESTORED');
}
function seeded(context, key) {
  if (!context.fixture[key]) throw new FixtureUnavailable('REQUIRED_NEGATIVE_SEED_UNAVAILABLE');
  return context.fixture[key];
}

export async function verifySavedNote(context, savedId, phase) {
  assert.match(savedId || '', /^[a-zA-Z0-9_-]{1,100}$/, 'ACKNOWLEDGED_NOTE_ID_REQUIRED');
  assert.ok(['ack', 'restart'].includes(phase), 'SAVED_NOTE_VERIFICATION_PHASE_REQUIRED');
  await absent(context, 'id', 'note-input');
  assert.equal(await read(context, 'id', 'matter-code'), context.fixture.matter.identityLabel, 'WRONG_MATTER');
  await find(context, 'id', `note-${savedId}`, { scroll: true });
  assert.equal(await read(context, 'id', `note-body-${savedId}`, { scroll: true }), context.noteText,
    phase === 'ack' ? 'NOTE_ACK_BODY_MISMATCH' : 'NOTE_RESTART_ID_OR_BODY_MISMATCH');
}

async function signedOutSurface(context) {
  await find(context, 'id', 'signed-out');
  assert.equal(await (await find(context, 'id', 'sign-in')).isEnabled(), true, 'SIGNED_OUT_SIGN_IN_NOT_USABLE');
  for (const id of ['session-loading', 'account-open', 'account-screen', 'account-principal', 'matter-code',
    'note-input', 'note-confirmed', 'screen-today', 'screen-matters', 'screen-calendar', 'screen-work',
    'tab-today', 'tab-matters', 'tab-calendar', 'tab-work']) await absent(context, 'id', id);
  for (const label of [context.fixture.principalLabel, context.fixture.workspaceLabel, context.fixture.matter.title,
    context.fixture.matter.identityLabel]) await absent(context, 'text', label);
}

export async function prepareScenario(context, scenario, completedCases) {
  if (scenario.signedOutAfter) {
    if (!completedCases.has(scenario.signedOutAfter)) throw new FixtureUnavailable('PREREQUISITE_SCENARIO_NOT_PASSED');
    await signedOutSurface(context);
  } else if (!scenario.authenticateInCall) {
    if (scenario.freshAuthenticationInSetup) {
      context.record?.({ type: 'native_authentication_boundary', scenario: scenario.id, state: 'started' });
      const before = await traffic(context);
      await authenticate(context, { fresh: true });
      const requests = delta(before, await traffic(context));
      validateAuthorizationTraffic(requests, context.fixture.auth, { single: true });
      noNotePostRetried(requests);
      context.record?.({ type: 'native_authentication_boundary', scenario: scenario.id, state: 'passed' });
    } else await authenticate(context);
  }
}

export function noNotePostRetried(requests) {
  assert.equal(requests.filter(({ method, route }) => method === 'POST' && /^\/api\/matters\/[^/]+\/notes$/.test(route)).length,
    0, 'NOTE_POST_DURING_CASE_RECOVERY');
}

export function signedOutResumeTraffic(requests) {
  assert.equal(requests.filter((request) => request.route.startsWith('/api/auth/')).length, 0, 'SIGNED_OUT_RESUME_ATTEMPTED_AUTHENTICATION');
}

export const scenarios = [
  { id: 'NATIVE-01', authenticateInCall: true, run: async (context) => {
    const before = await traffic(context);
    await authenticate(context, { fresh: true });
    const requests = delta(before, await traffic(context));
    validateAuthorizationTraffic(requests, context.fixture.auth, { single: true });
  } },
  { id: 'NATIVE-02', run: async (context) => { for (const tab of ['today', 'matters', 'calendar', 'work']) await home(context, tab); } },
  { id: 'NATIVE-03', run: async (context) => {
    await home(context, 'today');
    await (await row(context, context.fixture.today)).click();
    assert.equal(await read(context, 'id', 'matter-code'), context.fixture.today.matter.identityLabel, 'TODAY_WRONG_SOURCE');
    await expectText(context, context.fixture.today.matter.title);
  } },
  ...SEARCH_KINDS.map((kind, index) => ({ id: `NATIVE-${String(index + 4).padStart(2, '0')}`, run: async (context) => {
    const search = context.fixture.matter.searches.find((item) => item.kind === kind);
    assert.ok(search, 'SUPPORTED_IDENTIFIER_FIXTURE_MISSING');
    await openMatter(context, context.fixture.matter, search.value);
    await expectText(context, search.value);
    await reloadMatter(context, context.fixture.matter);
    await expectText(context, search.value);
  } })),
  { id: 'NATIVE-09', run: async (context) => {
    const before = await traffic(context);
    await editor(context);
    await input(context, 'id', 'note-input', context.noteText);
    await click(context, 'id', 'note-save', { scroll: true });
    await expectText(context, 'Note saved and reloaded');
    await find(context, 'id', 'note-confirmed', { scroll: true });
    // Capture only the server-owned synthetic note ID, never an auth credential.
    const prefix = context.platform === 'android'
      ? 'android=new UiSelector().textStartsWith("Saved note ID: ")'
      : '-ios predicate string:label BEGINSWITH "Saved note ID: "';
    const saved = await findQuery(context, prefix, { scroll: true });
    const savedId = /^Saved note ID: ([a-zA-Z0-9_-]{1,100})$/.exec(await saved.getText())?.[1];
    assert.ok(savedId, 'ACKNOWLEDGED_NOTE_ID_REQUIRED');
    await click(context, 'id', 'note-return', { scroll: true });
    await verifySavedNote(context, savedId, 'ack');
    await restart(context);
    await authenticate(context);
    await openMatter(context);
    await click(context, 'id', 'matter-activity');
    await verifySavedNote(context, savedId, 'restart');
    const requests = delta(before, await traffic(context));
    assert.equal(requestCount(requests, 'POST', context.fixture.noteRoute), 1, 'NOTE_NOT_SUBMITTED_EXACTLY_ONCE');
    assert.ok(requests.some((request) => request.method === 'POST' && request.route === context.fixture.noteRoute && [200, 201].includes(request.status)), 'NOTE_POST_NOT_ACKNOWLEDGED');
    successfulRead(requests, context.fixture.matterReloadRoute);
  } },
  { id: 'NATIVE-10', run: async (context) => {
    const event = context.fixture.calendar;
    await home(context, 'calendar');
    await input(context, 'label', 'Agenda date, YYYY-MM-DD', event.day);
    await click(context, 'id', 'calendar-go-date');
    await expectText(context, event.dayLabel);
    await expectText(context, event.title);
    await expectText(context, event.metaLabel);
    const before = await traffic(context);
    await click(context, 'id', 'reload', { scroll: true });
    await context.driver.waitUntil(async () => delta(before, await traffic(context)).some((item) => item.method === 'GET' && item.route === '/api/calendar/events' && item.status === 200),
      { timeout: 10000, interval: 200, timeoutMsg: 'AGENDA_REREAD_MISSING' });
    await expectText(context, event.title);
    await expectText(context, event.metaLabel);
    assert.match(event.eventId || '', /^[A-Za-z0-9_:.-]{1,160}$/, 'SEEDED_CALENDAR_EVENT_ID_REQUIRED');
    await click(context, 'id', `event-${event.eventId}`, { scroll: true });
    assert.equal(await read(context, 'id', 'matter-code'), event.matter.identityLabel, 'AGENDA_WRONG_SOURCE');
    await expectText(context, event.matter.title);
    await expectText(context, event.nextHearingLabel);
  } },
  { id: 'NATIVE-11', run: async (context) => {
    await home(context, 'calendar');
    const event = context.fixture.calendar;
    await input(context, 'label', 'Agenda date, YYYY-MM-DD', event.day);
    await click(context, 'id', 'calendar-go-date');
    await expectText(context, event.dayLabel);
    await expectText(context, event.title);
    const before = await traffic(context);
    await input(context, 'label', 'Agenda date, YYYY-MM-DD', '2026-02-30');
    await click(context, 'id', 'calendar-go-date');
    await expectText(context, 'Enter a valid date as YYYY-MM-DD.');
    await expectText(context, event.dayLabel);
    assert.equal(requestCount(delta(before, await traffic(context)), 'GET', '/api/calendar/events'), 0, 'INVALID_DATE_FETCHED');
  } },
  { id: 'NATIVE-12', run: async (context) => {
    const before = await traffic(context), { task, draft } = context.fixture.work;
    await home(context, 'work');
    await (await row(context, task)).click();
    assert.equal(await read(context, 'id', 'matter-code'), task.matter.identityLabel, 'WORK_WRONG_SOURCE');
    await expectText(context, task.title);
    if (draft.entry === 'reviews') {
      await home(context, 'work');
      await click(context, 'text', 'Reviews');
      await (await row(context, draft)).click();
    } else {
      assert.equal(draft.matter.id, task.matter.id, 'DRAFT_TASK_SOURCE_MISMATCH');
      await click(context, 'text', draft.title, { scroll: true });
    }
    const facts = [draft.title, draft.statusLabel, draft.revisionLabel, draft.body, draft.verifiedCitationCountLabel,
      ...(draft.citations.length ? draft.citations : ['No citations supplied for this version.'])];
    for (const text of facts) await expectText(context, text);
    const mark = await traffic(context);
    await click(context, 'text', 'Reload current version', { scroll: true });
    const route = `/api/matters/${draft.matter.id}/drafts/${draft.id}`;
    await context.driver.waitUntil(async () => delta(mark, await traffic(context)).some((request) => request.route === route && request.status === 200),
      { timeout: 10000, interval: 200, timeoutMsg: 'CURRENT_DRAFT_REREAD_MISSING' });
    for (const text of facts) await expectText(context, text);
    for (const text of ['Approve', 'Finalize', 'Request changes', 'Generate']) await absent(context, 'text', text);
    readOnlyTraffic(delta(before, await traffic(context)));
  } },
  { id: 'NATIVE-13', freshAuthenticationInSetup: true, run: async (context) => {
    await editor(context);
    const before = await traffic(context);
    await input(context, 'id', 'note-input', 'x');
    assert.equal(await (await find(context, 'id', 'note-save', { scroll: true })).isEnabled(), false, 'SHORT_NOTE_SAVE_ENABLED');
    await input(context, 'id', 'note-input', context.noteText);
    assert.equal(await (await find(context, 'id', 'note-save', { scroll: true })).isEnabled(), true, 'VALID_NOTE_SAVE_DISABLED');
    await discard(context);
    noNotePost(delta(before, await traffic(context)), context.fixture.matter.id);
  } },
  { id: 'NATIVE-14', run: async (context) => {
    await editor(context);
    const before = await traffic(context);
    await input(context, 'id', 'note-input', context.noteText);
    await discard(context, 'stay');
    assert.equal(await read(context, 'id', 'note-input'), context.noteText, 'STAY_LOST_UNSAVED_NOTE');
    await discard(context);
    await find(context, 'id', 'matter-code');
    await click(context, 'id', 'note-add', { scroll: true });
    await freshNoteAbsent(context);
    await click(context, 'id', 'back');
    noNotePost(delta(before, await traffic(context)), context.fixture.matter.id);
  } },
  { id: 'NATIVE-15', run: async (context) => {
    await openMatter(context);
    const before = await traffic(context);
    await restart(context);
    // Do not authenticate here: an unexpected browser re-login must fail this case.
    await find(context, 'id', 'account-open');
    await openMatter(context);
    const requests = delta(before, await traffic(context));
    assert.equal(requestCount(requests, 'POST', '/api/auth/native/refresh'), 1, 'RESTART_REFRESH_NOT_ONCE');
    assert.ok(requests.some((item) => item.route === '/api/auth/native/refresh' && item.status === 200), 'RESTART_REFRESH_NOT_ACKNOWLEDGED');
    assert.equal(requestCount(requests, 'POST', '/api/auth/native/token'), 0, 'RESTART_USED_FRESH_LOGIN');
    successfulRead(requests, '/api/auth/me');
    successfulRead(requests, context.fixture.matterReloadRoute);
  } },
  { id: 'NATIVE-16', run: async (context) => {
    await editor(context);
    const before = await traffic(context);
    await input(context, 'id', 'note-input', context.noteText);
    await restart(context);
    await find(context, 'id', 'account-open');
    await editor(context);
    await freshNoteAbsent(context);
    await click(context, 'id', 'back');
    noNotePost(delta(before, await traffic(context)), context.fixture.matter.id);
  } },
  { id: 'NATIVE-17', run: async (context) => {
    const matter = seeded(context, 'lifecycleMatter');
    if (!context.owner?.capabilities.includes('readMatterState')) throw new FixtureUnavailable('FIXTURE_OWNER_CAPABILITY_UNAVAILABLE');
    const baseline = await ownerControl(context, 'readMatterState', matter.id);
    assert.ok(['intake', 'active', 'on_hold'].includes(baseline.status), 'ACTIVE_DESTRUCTIVE_FIXTURE_REQUIRED');
    assert.equal(baseline.isActive, true, 'ACTIVE_DESTRUCTIVE_FIXTURE_REQUIRED');
    assert.ok(Array.isArray(baseline.noteIds) && Number.isSafeInteger(baseline.lifecycleVersion), 'PERSISTED_LIFECYCLE_BASELINE_REQUIRED');
    await editor(context, matter);
    await input(context, 'id', 'note-input', context.noteText);
    const before = await traffic(context);
    const disposed = await ownerControl(context, 'disposeMatter', matter.id);
    assert.equal(disposed.status, 'disposed', 'OWNER_DISPOSAL_NOT_ACKNOWLEDGED');
    assert.equal(disposed.isActive, false, 'OWNER_DISPOSAL_NOT_TERMINAL');
    assert.equal(disposed.lifecycleVersion, baseline.lifecycleVersion + 1, 'OWNER_DISPOSAL_VERSION_MISMATCH');
    assert.deepEqual(disposed.noteIds, baseline.noteIds, 'OWNER_DISPOSAL_CHANGED_NOTES');
    await click(context, 'id', 'note-save', { scroll: true });
    assert.equal(await read(context, 'id', 'note-outcome', { scroll: true }), 'Note not accepted', 'STALE_NOTE_NOT_REJECTED');
    await expectText(context, 'The matter lifecycle has changed. Close this editor and reload the matter. The note was not sent.');
    const retained = await ownerControl(context, 'readMatterState', matter.id);
    assert.equal(retained.status, 'disposed', 'NATIVE_NOTE_REACTIVATED_MATTER');
    assert.equal(retained.isActive, false, 'NATIVE_NOTE_REACTIVATED_MATTER');
    assert.equal(retained.lifecycleVersion, disposed.lifecycleVersion, 'NATIVE_NOTE_CHANGED_LIFECYCLE');
    assert.deepEqual(retained.noteIds, disposed.noteIds, 'DISPOSED_NOTE_PERSISTED');
    noNotePost(delta(before, await traffic(context)), matter.id);
    await restart(context);
    const final = await ownerControl(context, 'readMatterState', matter.id);
    assert.deepEqual(final, retained, 'DISPOSED_STATE_CHANGED_AFTER_RESTART');
  } },
  { id: 'NATIVE-18', run: async (context) => {
    const matter = seeded(context, 'accessMatter');
    if (!context.owner?.capabilities.includes('readNoteState')) throw new FixtureUnavailable('FIXTURE_OWNER_CAPABILITY_UNAVAILABLE');
    await openMatter(context, matter);
    const baseline = await ownerControl(context, 'readNoteState', matter.id);
    assert.ok(Array.isArray(baseline.noteIds), 'PERSISTED_NOTE_BASELINE_REQUIRED');
    const revoked = await ownerControl(context, 'revokeMatterAccess', matter.id);
    assert.equal(revoked.accessAllowed, false, 'OWNER_ACCESS_REVOCATION_NOT_ACKNOWLEDGED');
    const before = await traffic(context);
    await click(context, 'id', 'matter-reload', { scroll: true });
    await expectText(context, 'Not available to this account');
    for (const label of [matter.identityLabel, matter.title]) await absent(context, 'text', label);
    await absent(context, 'id', 'note-add');
    const requests = delta(before, await traffic(context));
    assert.ok(requests.some((request) => request.route === `/api/matters/${matter.id}/workspace` && [403, 404].includes(request.status)), 'REVOKED_WORKSPACE_NOT_DENIED');
    const after = await ownerControl(context, 'readNoteState', matter.id);
    assert.deepEqual(after.noteIds, baseline.noteIds, 'REVOKED_NOTE_STATE_CHANGED');
  } },
  { id: 'NATIVE-19', run: async (context) => {
    const matter = seeded(context, 'foreignMatter');
    await home(context, 'matters');
    await input(context, 'id', 'matter-search', matter.search);
    const before = await traffic(context);
    await click(context, 'id', 'matter-search-submit');
    await expectText(context, 'No matching matters');
    await absent(context, 'id', `matter-row-${matter.id}`);
    const searchInput = await find(context, 'id', 'matter-search');
    assert.ok(searchInput.elementId, 'NATIVE_SEARCH_ELEMENT_ID_REQUIRED');
    for (const label of [matter.identityLabel, matter.title]) {
      for (const element of await context.driver.$$(selector(context.platform, 'text', label))) {
        if (await element.isDisplayed()) assert.equal(element.elementId, searchInput.elementId, 'FOREIGN_RECORD_LABEL_VISIBLE');
      }
    }
    successfulRead(delta(before, await traffic(context)), '/api/matters/');
  } },
  { id: 'NATIVE-20', run: async (context) => {
    if (!context.fixture.nativeSessionDeleteAdmission) throw new FixtureUnavailable('NATIVE_SESSION_DELETE_ADMISSION_REQUIRED');
    const admission = configuredSessionDeleteAdmission(context.fixture);
    const before = await traffic(context);
    await click(context, 'id', 'account-open');
    await find(context, 'id', 'account-session-current', { scroll: true });
    await click(context, 'id', 'account-session-current-revoke', { scroll: true });
    await find(context, 'id', 'account-session-confirmation');
    await click(context, 'id', 'account-session-cancel');
    await absent(context, 'id', 'account-session-confirmation');
    assert.equal(delta(before, await traffic(context)).filter((request) => request.method === 'DELETE').length, 0, 'CANCEL_REVOKED_DEVICE_SESSION');
    await click(context, 'id', 'account-session-current-revoke', { scroll: true });
    await find(context, 'id', 'account-session-confirmation');
    await click(context, 'id', 'account-session-confirm');
    await find(context, 'id', 'signed-out');
    await restart(context);
    await find(context, 'id', 'signed-out');
    await absent(context, 'id', 'account-open');
    await absent(context, 'id', 'matter-code');
    const requests = delta(before, await traffic(context));
    const revocations = requests.filter((request) => request.method === 'DELETE');
    assert.equal(revocations.length, 1, 'DEVICE_REVOCATION_NOT_EXACTLY_ONCE');
    assert.match(revocations[0].route, /^\/api\/auth\/native\/sessions\/[a-zA-Z0-9_-]{1,100}$/, 'EXACT_NATIVE_DEVICE_REVOCATION_REQUIRED');
    const proof = proveCurrentSessionDeletion(before, await traffic(context), admission);
    context.record?.({ type: 'assertion', boundary: 'current-native-session-delete-admission', ...proof });
    assert.equal(requestCount(requests, 'POST', '/api/auth/native/refresh'), 0, 'REVOKED_DEVICE_REFRESH_RESTORED');
  } },
  { id: 'NATIVE-21', expectedAuthenticationCycles: 3, run: async (context) => {
    const state = await traffic(context);
    const requests = state.requests.filter((row) => row.sequence > (context.gatewayBaseline?.lastSequence || 0));
    assert.ok(requests.some((row) => row.route === '/api/me/today' && row.status === 200), 'MEANINGFUL_NATIVE_TRAFFIC_MISSING');
    assert.ok(requests.some((row) => row.route === '/api/auth/native/authorize' && row.status === 200), 'SYSTEM_BROWSER_TRAFFIC_NOT_IN_LEDGER');
    validateAuthorizationTraffic(requests, context.fixture.auth, { cycles: 3 });
  } },
  { id: 'NATIVE-22', run: async (context) => {
    await openMatter(context);
    const before = await traffic(context);
    await click(context, 'id', 'account-open');
    await click(context, 'id', 'sign-out', { scroll: true });
    await find(context, 'id', 'signed-out');
    await absent(context, 'id', 'matter-code');
    await absent(context, 'id', 'account-principal');
    await restart(context);
    await find(context, 'id', 'signed-out');
    await absent(context, 'id', 'account-open');
    const requests = delta(before, await traffic(context));
    assert.equal(requestCount(requests, 'POST', '/api/auth/native/logout'), 1, 'LOGOUT_NOT_ONCE');
    assert.ok(requests.some((request) => request.route === '/api/auth/native/logout' && [200, 204].includes(request.status)), 'LOGOUT_NOT_ACKNOWLEDGED');
    assert.equal(requestCount(requests, 'POST', '/api/auth/native/refresh'), 0, 'LOGOUT_RESTORED_DEVICE_SESSION');
  } },
  { id: 'NATIVE-23', signedOutAfter: 'NATIVE-22', run: async (context) => {
    await signedOutSurface(context);
    const before = await traffic(context);
    await backgroundAndResume(context);
    await signedOutSurface(context);
    signedOutResumeTraffic(delta(before, await traffic(context)));
  } },
];
