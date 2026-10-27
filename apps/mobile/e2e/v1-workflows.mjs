import assert from 'node:assert/strict';
import { openMatter, traffic, delta, readOnlyTraffic } from './journeys.mjs';
import { home, find, findQuery, visible, selector, dispatchNativeClick, input, read, expectText, swipe } from './native-ui.mjs';
import { readV1Reference, validateV1Fixture, validateV1MutationEvidence, v1Identity, v1Version,
  V1_CONTROL_CAPABILITIES, createV1CaseBudget, v1Hash } from './v1-workflows-contract.mjs';
import { validateV1InboxMutationEvidence } from './v1-workflows-contract.mjs';
import { collectV1, V1_BUDGETS } from './v1-workflows-inventory.mjs';

const event = (c, boundary, facts = {}) => c.record?.({ type: 'v1_assertion', boundary, ...facts });
const clone = value => structuredClone(value);
const rawCount = async (c, id) => (await c.driver.$$(selector(c.platform, 'id', id))).length;
const ui = async (c, id) => read(c, 'id', id, { scroll: true });
async function tap(c, id, options = { scroll: true }) {
  c.budget.control(); const element = await find(c, 'id', id, options);
  assert.equal(await element.isEnabled(), true, 'V1_CONTROL_DISABLED');
  await dispatchNativeClick(c, element, 'id', id);
}
export async function dispatchV1SaveOnce(c, key) {
  assert.ok(typeof key === 'string' && key.length > 0 && key.length <= 500, 'EXACT_V1_MUTATION_IDENTITY_REQUIRED');
  assert.equal(c.state.dispatched.has(key), false, 'WORK_MUTATION_REPLAY_REFUSED');
  c.state.dispatched.add(key);
  await tap(c, 'quick-save');
}
async function textTap(c, label) {
  c.budget.control(); const element = await find(c, 'text', label, { scroll: true });
  assert.equal(await element.isEnabled(), true, 'V1_CONTROL_DISABLED');
  await dispatchNativeClick(c, element);
}
const xpathText = value => value.includes("'") ? `concat(${value.split("'").map(part => `'${part}'`).join(',"\'",')})` : `'${value}'`;
async function scopedFact(c, scopeId, value) {
  assert.ok(typeof value === 'string' && value.length <= 8000); assert.match(scopeId, /^[a-z0-9-]{1,120}$/);
  const scope = c.platform === 'ios' ? `//*[@name=${xpathText(scopeId)}]` : `//*[@resource-id=${xpathText(scopeId)}]`;
  const query = c.platform === 'ios' ? `${scope}//*[@type='XCUIElementTypeStaticText' and (@label=${xpathText(value)} or @value=${xpathText(value)})]`
    : `${scope}//*[@text=${xpathText(value)}]`;
  const element = await findQuery(c, query, { scroll: true }); assert.equal(await element.getText(), value, 'EXACT_SCOPED_V1_FACT_REQUIRED');
}
async function scopedIdFact(c, scopeId, fieldId, value) {
  assert.match(scopeId, /^[a-z0-9-]{1,120}$/); assert.match(fieldId, /^[a-z0-9-]{1,120}$/); assert.equal(typeof value, 'string');
  const attr = c.platform === 'ios' ? 'name' : 'resource-id';
  const query = `//*[@${attr}=${xpathText(scopeId)}]//*[@${attr}=${xpathText(fieldId)}]`;
  const element = await findQuery(c, query, { scroll: true }); assert.equal(await element.getText(), value, 'EXACT_SCOPED_V1_VALUE_ID_REQUIRED');
}
async function scopedAction(c, scopeId, label) {
  const observed = c.fixture.v1.nativeSelectors; assert.equal(observed.observed, true); assert.equal(observed.udid, c.fixture.udid); assert.deepEqual(observed.buildReceipt, c.fixture.buildReceipt);
  let recipe = observed.scopedActions?.[`${scopeId}:${label}`];
  if (!recipe) {
    const pattern = observed.scopedActionPatterns?.recipientInbox;
    assert.ok(pattern && pattern.observed === true && pattern.scopePrefix === 'notification-' && scopeId.startsWith(pattern.scopePrefix), 'OBSERVED_SCOPED_NATIVE_ACTION_REQUIRED');
    assert.ok(['Open source record', 'Mark as read', 'Dismiss notification', 'Restore notification'].includes(label));
    assert.ok(typeof pattern.queryTemplate === 'string' && pattern.queryTemplate.length <= 500 && pattern.queryTemplate.includes('{LABEL_JSON}'));
    assert.ok(['type', 'class', 'className'].includes(pattern.typeAttribute) && typeof pattern.expectedType === 'string' && pattern.expectedType);
    recipe = { ...pattern, scopeId, label, query: pattern.queryTemplate.replaceAll('{LABEL_JSON}', JSON.stringify(label)) };
  }
  assert.ok(recipe && recipe.scopeId === scopeId && recipe.label === label, 'OBSERVED_SCOPED_NATIVE_ACTION_REQUIRED');
  assert.ok(['label', 'name', 'text'].includes(recipe.labelAttribute));
  assert.ok(typeof recipe.query === 'string' && recipe.query.startsWith(c.platform === 'ios' ? '-ios predicate string:' : 'android='));
  const scopes = await c.driver.$$(selector(c.platform, 'id', scopeId)); assert.equal(scopes.length, 1, 'UNIQUE_NATIVE_ACTION_SCOPE_REQUIRED');
  const element = await visible(scopes[0], recipe.query); assert.ok(element, 'EXACT_SCOPED_NATIVE_ACTION_REQUIRED');
  assert.equal(await element.getAttribute(recipe.labelAttribute), label); assert.equal(await element.isEnabled(), true);
  if (recipe.expectedType) assert.equal(await element.getAttribute(recipe.typeAttribute), recipe.expectedType);
  event(c, 'scoped-native-action-observed-before-one-dispatch', { scopeId, label, type: recipe.expectedType || 'observed-exact-recipe' });
  c.budget.control(); await dispatchNativeClick(c, element);
}
async function field(c, key, value) {
  assert.equal(typeof value, 'string', 'EXACT_SYNTHETIC_WORK_INPUT_REQUIRED');
  c.budget.control(); await input(c, 'id', `quick-${key}`, value, { scroll: true });
  const element = await find(c, 'id', `quick-${key}`);
  if (c.platform === 'ios') assert.equal(await element.getAttribute('value'), value, 'WORK_INPUT_VALUE_MISMATCH');
  else assert.equal(await element.getText(), value, 'WORK_INPUT_VALUE_MISMATCH');
}
async function fields(c, kind, values) {
  for (const [key, value] of Object.entries(values))
    if (!['status', 'priority', 'time_status', 'hearing_time', 'create_follow_up'].includes(key)) await field(c, key, value);
  if (values.status) await segment(c, kind === 'task' ? 'Task status' : 'Hearing status', values.status.replaceAll('_', ' '));
  if (values.priority) await segment(c, 'Priority', values.priority);
  if (values.time_status) {
    await segment(c, 'Published time', values.time_status.replaceAll('_', ' '));
    if (values.time_status === 'exact') await field(c, 'hearing_time', values.hearing_time);
  }
  if (values.create_follow_up) await segment(c, 'Create follow-up task on completion', values.create_follow_up);
}
async function waitId(c, id) {
  let element;
  await c.driver.waitUntil(async () => !!(element = await visible(c.driver, selector(c.platform, 'id', id))),
    { timeout: V1_BUDGETS.nativeTransitionMs, interval: V1_BUDGETS.pollMs, timeoutMsg: 'V1_NATIVE_TRANSITION_REQUIRED' });
  return element;
}
async function waitFact(c, id, expected) {
  await c.driver.waitUntil(async () => {
    const element = await visible(c.driver, selector(c.platform, 'id', id));
    return !!element && await element.getText() === expected;
  }, { timeout: V1_BUDGETS.nativeTransitionMs, interval: V1_BUDGETS.pollMs, timeoutMsg: 'EXACT_V1_VISIBLE_FACT_REQUIRED' });
}
async function control(c, capability, args) {
  assert.ok(V1_CONTROL_CAPABILITIES.includes(capability), 'REVIEWED_V1_CONTROL_REQUIRED'); c.budget.owner();
  assert.equal(typeof c.controls[capability], 'function', 'IMPLEMENTED_V1_CONTROL_REQUIRED');
  const result = await c.controls[capability]({ ...args, caseId: c.caseId });
  assert.equal(result.observed, true, 'ACTUAL_V1_CONTROL_RECEIPT_REQUIRED');
  assert.equal(result.sourceSha, c.fixture.binarySourceSha, 'CONTROL_SERVING_SOURCE_MISMATCH');
  assert.equal(result.runId, c.fixture.gatewayRunId, 'CONTROL_LEDGER_MISMATCH');
  assert.equal(result.noPaidMarker, 'no-paid-providers', 'CONTROL_PROVIDER_ISOLATION_REQUIRED');
  return result;
}
async function workspace(c, matter, actor = c.actor || 'member') {
  c.budget.read(); const result = await control(c, 'readWorkspace', { matterId: matter.id, actor });
  assert.equal(result.status, 200, 'CURRENT_ACTOR_WORKSPACE_REQUIRED');
  assert.equal(result.value.matter.id, matter.id); assert.equal(result.value.matter.company_id, c.fixture.companyId);
  return clone(result.value);
}
async function segment(c, group, label) {
  // Native/accessible segment implementations differ by measured width/font.
  // Consume an actual device/build-bound observation, never a guessed first match.
  const observed = c.fixture.v1.nativeSelectors;
  assert.equal(observed.observed, true, 'OBSERVED_V1_SEGMENTS_REQUIRED');
  assert.equal(observed.udid, c.fixture.udid); assert.deepEqual(observed.buildReceipt, c.fixture.buildReceipt);
  const recipe = observed.segments[group]?.[label];
  assert.ok(recipe && recipe.label === label && recipe.group === group, 'EXACT_OBSERVED_SEGMENT_REQUIRED');
  assert.ok(typeof recipe.query === 'string' && recipe.query.startsWith(c.platform === 'ios' ? '-ios predicate string:' : 'android='), 'TYPED_OBSERVED_SEGMENT_REQUIRED');
  const scope = recipe.scopeQuery ? await findQuery(c, recipe.scopeQuery, { scroll: true }) : c.driver;
  const element = await visible(scope, recipe.query); assert.ok(element, 'OBSERVED_SEGMENT_NOT_VISIBLE');
  assert.ok(['label', 'name', 'text'].includes(recipe.labelAttribute), 'OBSERVED_SEGMENT_LABEL_ATTRIBUTE_REQUIRED');
  assert.equal(await element.getAttribute(recipe.labelAttribute), label, 'ACTUAL_SEGMENT_LABEL_MISMATCH');
  c.budget.control(); await dispatchNativeClick(c, element);
  return { recipe, element };
}
async function selectedSegment(c, group, label) {
  const recipe = c.fixture.v1.nativeSelectors.segments[group]?.[label]; assert.ok(recipe);
  const scope = recipe.scopeQuery ? await findQuery(c, recipe.scopeQuery) : c.driver;
  const element = await visible(scope, recipe.query); assert.ok(element);
  const selected = await element.getAttribute(recipe.selectedAttribute);
  assert.equal(String(selected), recipe.selectedValue, 'RETAINED_SEGMENT_SELECTION_REQUIRED');
}
async function row(c, id, fields) {
  const element = await find(c, 'id', id, { scroll: true });
  if (c.platform === 'ios') {
    assert.equal(await element.getAttribute('type'), 'XCUIElementTypeButton');
    assert.ok([true, 'true'].includes(await element.getAttribute('accessible')));
    assert.equal(await element.getAttribute('label'), fields.join(', '));
    assert.equal(await element.getText(), fields.join(', '));
  } else for (const value of fields) assert.ok(await visible(element, selector(c.platform, 'text', value)), 'EXACT_V1_ROW_REQUIRED');
  return element;
}
/** A readonly RecordRow is a View, not an accessible edit Button. Fabric can
 * flatten that wrapper; require its unique identity and visible contained facts. */
export async function readOnlyV1Row(c, id, facts) {
  assert.ok(Array.isArray(facts) && facts.length === 3 && facts.every(value => typeof value === 'string' && value));
  const valid = r => r && ['x', 'y', 'width', 'height'].every(key => Number.isFinite(r[key])) && r.width > 0 && r.height > 0;
  const contains = (outer, inner) => outer.x <= inner.x && outer.y <= inner.y && outer.x + outer.width >= inner.x + inner.width && outer.y + outer.height >= inner.y + inner.height;
  for (let attempt = 0; attempt <= V1_BUDGETS.maxScrolls; attempt++) {
    const matches = await c.driver.$$(selector(c.platform, 'id', id));
    assert.equal(matches.length, 1, 'UNIQUE_READONLY_WORK_ROW_REQUIRED');
    const element = matches[0];
    assert.ok(typeof element.elementId === 'string' && element.elementId, 'READONLY_WORK_ROW_ID_REQUIRED');
    const rect = await c.driver.getElementRect(element.elementId), window = await c.driver.getWindowRect();
    const ancestors = await element.$$(c.platform === 'ios' ? 'xpath=ancestor::XCUIElementTypeScrollView' : 'xpath=ancestor::*[@scrollable="true"]');
    const mounted = [];
    for (const ancestor of ancestors) if (await ancestor.isDisplayed()) mounted.push(ancestor);
    assert.equal(mounted.length, 1, 'EXACT_READONLY_ROW_SCROLL_ANCESTOR_REQUIRED');
    const viewport = await c.driver.getElementRect(mounted[0].elementId);
    assert.ok(valid(rect) && valid(window) && valid(viewport) && contains(window, viewport), 'READONLY_ROW_VISIBLE_GEOMETRY_REQUIRED');
    if (!contains(viewport, rect)) {
      assert.ok(attempt < V1_BUDGETS.maxScrolls && rect.height <= viewport.height, 'READONLY_ROW_VISIBLE_GEOMETRY_REQUIRED');
      c.budget.control(); await swipe(c, rect.y < viewport.y ? 'up' : 'down'); continue;
    }
    if (c.platform === 'ios') assert.notEqual(await element.getAttribute('type'), 'XCUIElementTypeButton', 'READONLY_ROW_MUST_NOT_OFFER_EDIT_ACTION');
    else assert.ok([false, 'false'].includes(await element.getAttribute('clickable')), 'READONLY_ROW_MUST_NOT_OFFER_EDIT_ACTION');
    for (const value of facts) {
      const leaf = await visible(element, selector(c.platform, 'text', value)); assert.ok(leaf, 'EXACT_READONLY_ROW_FACT_REQUIRED');
      assert.equal(await leaf.getText(), value); const frame = await c.driver.getElementRect(leaf.elementId);
      assert.ok(valid(frame) && contains(rect, frame), 'READONLY_ROW_FACT_OUTSIDE_IDENTITY');
    }
    return element;
  }
  throw Error('READONLY_ROW_VISIBLE_GEOMETRY_REQUIRED');
}
async function sourceFacts(c, source, kind) {
  await waitFact(c, 'source-id', source.id);
  assert.equal(await ui(c, 'source-kind'), kind);
  assert.equal(await ui(c, 'source-status'), source.status);
  assert.equal(await ui(c, 'source-updated'), source.updated_at);
  assert.ok(await visible(c.driver, selector(c.platform, 'id', 'source-read-only')));
}
async function sources(c, kind = 'Contracts') {
  await tap(c, 'account-open', { scroll: false });
  assert.equal(await ui(c, 'account-principal'), c.fixture.principalLabel);
  assert.equal(await ui(c, 'account-workspace'), c.fixture.workspaceLabel);
  await tap(c, 'account-ip-records'); await segment(c, 'Source type', kind);
  assert.equal(await ui(c, 'source-page'), 'Page 1');
}
async function contractDetail(c, record) {
  const rows = c.fixture.v1.records.contracts.rows;
  const expected = rows.find(x => x.id === record.id); assert.ok(expected, 'BOUND_CONTRACT_ROW_REQUIRED');
  const element = await row(c, `source-row-contract-${record.id}`, expected.fields);
  c.budget.control(); await dispatchNativeClick(c, element, 'id', `source-row-contract-${record.id}`);
  await sourceFacts(c, record, 'Contract');
  assert.equal(await ui(c, 'source-contract-code'), record.contract_code);
}
async function reloadSource(c, record, kind) {
  const before = await traffic(c); await tap(c, 'source-detail-reload'); await sourceFacts(c, record, kind);
  const requests = delta(before, await traffic(c));
  const route = kind === 'Contract' ? `/api/contracts/${record.id}` : `/api/ip/dockets/${record.id}/summary`;
  assert.equal(requests.filter(x => x.method === 'GET' && x.route === route && x.status === 200).length, 1, 'ONE_CURRENT_SOURCE_RELOAD_REQUIRED');
  readOnlyTraffic(requests);
}
async function openWork(c, target, kind, existing) {
  await openMatter(c, target.matter); await segment(c, 'Matter view', 'Work');
  if (existing) {
    const record = existing, fields = target.rowFacts[kind][record.id]; assert.ok(fields);
    const element = await row(c, `${kind}-${record.id}`, fields); c.budget.control(); await dispatchNativeClick(c, element, 'id', `${kind}-${record.id}`);
  } else await tap(c, `quick-${kind}-add`);
  await waitId(c, 'quick-work-editor');
}
async function outcome(c, allowed) {
  let result, ambiguous = false;
  await c.driver.waitUntil(async () => {
    const matches = [];
    for (const state of ['confirmed', 'acknowledged', 'rejected', 'unknown', 'superseded'])
      if (await visible(c.driver, selector(c.platform, 'id', `quick-${state}`))) matches.push(state);
    if (matches.length > 1) { ambiguous = true; return true; }
    if (matches[0] === 'acknowledged' && !allowed.includes('acknowledged')) return false;
    if (matches.length) { result = matches[0]; return true; } return false;
  }, { timeout: V1_BUDGETS.persistedReadMs, interval: V1_BUDGETS.pollMs, timeoutMsg: 'NATIVE_WORK_OUTCOME_REQUIRED' });
  assert.equal(ambiguous, false, 'AMBIGUOUS_WORK_OUTCOME');
  assert.ok(allowed.includes(result), 'UNEXPECTED_NATIVE_WORK_OUTCOME'); return result;
}
async function saveOnce(c, { target, kind, body, before, allowed = ['confirmed'] }) {
  const route = `/api/matters/${target.matter.id}/${kind === 'task' ? 'tasks' : 'hearings'}${target.recordId ? `/${target.recordId}` : ''}`;
  const key = `${c.caseId}:${route}:${target.transitionIndex ?? 'only'}`; await dispatchV1SaveOnce(c, key); const state = await outcome(c, allowed);
  const traces = await control(c, 'readNativeRequest', { afterSequence: before.lastSequence, method: target.recordId ? 'PATCH' : 'POST', route });
  const acknowledged = validateV1MutationEvidence(traces.requests, delta(before, await traffic(c)), { method: target.recordId ? 'PATCH' : 'POST', route, body, expectedStatus: [200] });
  const after = await workspace(c, target.matter), list = kind === 'task' ? 'tasks' : 'hearings';
  const id = acknowledged.responseObservation?.id; v1Identity(id); assert.equal(acknowledged.responseObservation.matter_id, target.matter.id);
  if (target.recordId) assert.equal(id, target.recordId);
  const matches = after[list].filter(x => x.id === id); assert.equal(matches.length, 1, 'EXACT_PERSISTED_WORK_UUID_REQUIRED');
  assert.equal(matches[0].matter_id, target.matter.id);
  await expectText(c, `Acknowledged ID: ${id}`);
  const version = kind === 'task' ? matches[0].updated_at : matches[0].record_version; v1Version(version, kind);
  assert.equal(acknowledged.responseObservation.version, version, 'ACKNOWLEDGEMENT_PERSISTED_VERSION_MISMATCH');
  const observation = { caseId: c.caseId, kind, id, before: target.beforeRecord ? clone(target.beforeRecord) : null, after: clone(matches[0]), requestId: acknowledged.requestId };
  c.state.versions.push(observation);
  c.record?.({ type: 'v1_work_record_observation', ...observation });
  event(c, 'native-work-one-acknowledged-and-reloaded', { kind, id, matterId: target.matter.id, requestId: acknowledged.requestId, version, outcome: state });
  return { id, record: matches[0], workspace: after, acknowledgement: acknowledged };
}
const targetAt = (c, index) => c.fixture.v1.records.work.targets[index];
export async function closeRejectedV1Editor(c, retainedDirtyFields) {
  assert.equal(typeof retainedDirtyFields, 'boolean');
  await tap(c, 'quick-close');
  if (retainedDirtyFields) await textTap(c, 'Leave editor');
  else assert.equal((await c.driver.$$(selector(c.platform, 'text', 'Leave editor'))).length, 0, 'PURGED_EDITOR_MUST_NOT_RETAIN_DIRTY_CONFIRMATION');
  assert.equal(await rawCount(c, 'quick-work-editor'), 0, 'REJECTED_EDITOR_CLOSE_REQUIRED');
}

export const v1WorkflowScenarios = Object.freeze([
  { id: 'SOURCE-01', freshAuthentication: true, run: async c => {
    const spec = c.fixture.v1.records.calendar;
    for (const source of spec.sources) {
      await home(c, 'calendar'); await input(c, 'id', 'calendar-date-input', spec.day); await tap(c, 'calendar-go-date'); await waitFact(c, 'calendar-selected-day', spec.dayLabel);
      await tap(c, 'next-week'); await waitFact(c, 'calendar-selected-day', spec.nextWeekLabel);
      await tap(c, 'previous-week'); await waitFact(c, 'calendar-selected-day', spec.dayLabel); await segment(c, 'Event type', 'Deadlines');
      const element = await row(c, `event-${source.event.id}`, source.rowFields), before = await traffic(c);
      c.budget.control(); await dispatchNativeClick(c, element, 'id', `event-${source.event.id}`);
      await sourceFacts(c, source.docket, `IP docket · ${source.docket.record_type}`);
      const observed = await control(c, 'readSource', { kind: 'ip_docket', id: source.docket.id }); assert.deepEqual(observed.value, source.docket);
      const requests = delta(before, await traffic(c)); readOnlyTraffic(requests);
      assert.ok(requests.some(x => x.method === 'GET' && x.route === `/api/ip/dockets/${source.docket.id}/summary` && x.status === 200));
      assert.equal(requests.some(x => x.route.startsWith('/api/matters/')), false, 'IP_DOCKET_MUST_NOT_BECOME_MATTER_LOOKUP');
      await tap(c, 'back', { scroll: false }); await waitFact(c, 'calendar-selected-day', spec.dayLabel); await selectedSegment(c, 'Event type', 'Deadlines');
      event(c, 'calendar-exact-source-and-retained-controls', { family: source.family, docketId: source.docket.id, recordType: source.docket.record_type });
    }
  } },
  { id: 'SOURCE-02', run: async c => {
    const spec = c.fixture.v1.records.contracts, beforeJourney = await traffic(c); await sources(c);
    for (const [index, page] of spec.pages.entries()) {
      assert.equal(await ui(c, 'source-page'), `Page ${index + 1}`);
      const witness = page.contracts.at(-1), expected = spec.rows.find(x => x.id === witness.id); await row(c, `source-row-contract-${witness.id}`, expected.fields);
      const before = await traffic(c);
      if (index === 0) { await tap(c, 'source-next-page'); assert.equal(await ui(c, 'source-page'), 'Page 2');
        const trace = await control(c, 'readNativeRequest', { afterSequence: before.lastSequence, method: 'GET', route: '/api/contracts/' });
        assert.equal(trace.requests.length, 1); assert.equal(trace.requests[0].queryObservation?.cursorSha256, v1Hash(Buffer.from(page.next_cursor)));
      }
    }
    const detail = spec.pages[1].contracts[0]; await contractDetail(c, detail); await reloadSource(c, detail, 'Contract');
    const actual = await control(c, 'readSource', { kind: 'contract', id: detail.id }); assert.deepEqual(actual.value, detail);
    await tap(c, 'back', { scroll: false }); assert.equal(await ui(c, 'source-page'), 'Page 2'); await tap(c, 'source-first-page'); assert.equal(await ui(c, 'source-page'), 'Page 1');
    await segment(c, 'Source type', 'Trademarks'); await segment(c, 'Source type', 'Contracts'); assert.equal(await ui(c, 'source-page'), 'Page 1');
    event(c, 'contract-cursor-detail-reload-and-type-return', { id: detail.id, pages: 2 });
    readOnlyTraffic(delta(beforeJourney, await traffic(c)));
  } },
  { id: 'SOURCE-03', run: async c => {
    const spec = c.fixture.v1.records.contracts, beforeJourney = await traffic(c); await sources(c);
    for (const record of [spec.nullable, spec.minorUnit]) {
      if (!spec.pages[0].contracts.some(x => x.id === record.id)) await tap(c, 'source-next-page');
      await contractDetail(c, record);
      assert.equal(await ui(c, 'source-value'), record.id === spec.nullable.id ? 'Not recorded' : 'INR 1 minor unit');
      if (record.id === spec.nullable.id) for (const id of ['source-effective-date', 'source-expiry-date', 'source-renewal-date']) assert.equal(await ui(c, id), 'Not recorded');
      assert.equal(await ui(c, 'source-verification'), 'Not supplied by the contract API');
      await reloadSource(c, record, 'Contract'); await tap(c, 'back', { scroll: false });
      if (!spec.pages[0].contracts.some(x => x.id === record.id)) await tap(c, 'source-first-page');
    }
    await home(c, 'calendar'); const source = c.fixture.v1.records.calendar.sources[0];
    await input(c, 'id', 'calendar-date-input', c.fixture.v1.records.calendar.day); await tap(c, 'calendar-go-date');
    const element = await row(c, `event-${source.event.id}`, source.rowFields); await dispatchNativeClick(c, element);
    await sourceFacts(c, source.docket, `IP docket · ${source.docket.record_type}`);
    assert.equal(await ui(c, 'source-provenance'), 'Current docket metadata. This summary does not supply application, renewal or verification dates; no dates are inferred from the Calendar event.');
    for (const id of ['source-application-date', 'source-renewal-date']) assert.equal(await rawCount(c, id), 0, 'GENERIC_IP_DATE_MUST_NOT_BE_INVENTED');
    readOnlyTraffic(delta(beforeJourney, await traffic(c)));
  } },
  { id: 'SOURCE-04', run: async c => {
    const spec = c.fixture.v1.records.access;
    for (const fault of spec.faults) {
      const beforeJourney = await traffic(c);
      let source, kind;
      if (['readiness-revoked', 'grant-revoked'].includes(fault.mode)) {
        const ip = spec.ip; source = ip.docket; kind = `IP docket · ${source.record_type}`;
        await home(c, 'calendar'); await input(c, 'id', 'calendar-date-input', c.fixture.v1.records.calendar.day); await tap(c, 'calendar-go-date');
        const element = await row(c, `event-${ip.event.id}`, ip.rowFields); await dispatchNativeClick(c, element); await sourceFacts(c, source, kind);
      } else { source = spec.contract; kind = 'Contract'; await sources(c); await contractDetail(c, source); }
      const policyChange = ['readiness-revoked', 'grant-revoked'].includes(fault.mode);
      const arm = await control(c, policyChange ? 'applyIpPolicy' : 'armSourceFault', fault);
      await tap(c, 'source-detail-reload'); await waitId(c, fault.expectedRoot);
      await expectText(c, fault.expectedTitle);
      for (const id of ['source-id', 'source-status', 'source-read-only']) assert.equal(await rawCount(c, id), 0, 'STALE_READY_SOURCE_MUST_BE_UNMOUNTED');
      const receipt = await control(c, 'readControlReceipt', { id: arm.id }); assert.equal(receipt.consumed, true); assert.equal(receipt.nativeMutationCount, 0);
      if (policyChange) {
        await control(c, 'applyIpPolicy', { operation: 'restore-owned-source-state', restoration: arm.restoration });
        const restored = await control(c, 'readSource', { kind: 'ip_docket', id: source.id });
        assert.equal(restored.status, 200); assert.equal(restored.value.id, source.id); assert.equal(restored.value.record_type, source.record_type);
        source = restored.value;
      }
      await tap(c, fault.expectedRoot === 'source-unavailable' ? 'source-detail-reload' : 'source-error-reload'); await sourceFacts(c, source, kind);
      readOnlyTraffic(delta(beforeJourney, await traffic(c)));
      event(c, 'source-explicit-failure-and-authorized-reload', { mode: fault.mode, sourceId: source.id });
    }
  } },
  { id: 'SOURCE-05', freshAuthentication: true, run: async c => {
    const first = c.fixture, second = readV1Reference(first.v1.records.secondCompany.fixtureEvidence);
    await sources(c); await tap(c, 'source-next-page'); assert.equal(await ui(c, 'source-page'), 'Page 2'); await contractDetail(c, first.v1.records.contracts.pages[1].contracts[0]);
    await tap(c, 'account-open', { scroll: false }); assert.equal(await ui(c, 'account-principal'), first.principalLabel); assert.equal(await ui(c, 'account-workspace'), first.workspaceLabel);
    const beforeLogout = await traffic(c); await tap(c, 'sign-out'); await waitId(c, 'signed-out');
    assert.equal(delta(beforeLogout, await traffic(c)).filter(row => row.method === 'POST' && row.route === '/api/auth/native/logout' && row.status === 204).length, 1, 'ONE_NATIVE_LOGOUT_ACK_REQUIRED');
    for (const id of ['source-detail', 'source-page', 'source-id']) assert.equal(await rawCount(c, id), 0);
    const other = { ...c, fixture: second }; await c.authenticate(second, { fresh: true }); c.state.activeFixture = second;
    await sources(other); assert.equal(await ui(other, 'source-page'), 'Page 1');
    for (const record of first.v1.records.contracts.pages.flatMap(x => x.contracts)) assert.equal(await rawCount(other, `source-row-contract-${record.id}`), 0);
    const foreign = await control(c, 'readSource', { actor: 'second-company', kind: 'contract', id: first.v1.records.contracts.pages[0].contracts[0].id }); assert.equal(foreign.status, 404);
    c.state.activeFixture = second; event(c, 'normal-company-change-purges-source-and-cursor', { firstCompanyId: first.companyId, secondCompanyId: second.companyId });
  } },
  { id: 'SOURCE-06', freshAuthentication: true, run: async c => {
    const spec = c.fixture.v1.records.access.wall, beforeJourney = await traffic(c);
    const current = await control(c, 'readSource', { kind: 'ip_docket', id: spec.docket.id }); assert.equal(current.status, 200);
    assert.equal(current.value.matter_id, spec.linkedMatter.id, 'ACTUAL_WALL_LINK_LINEAGE_REQUIRED');
    await home(c, 'calendar'); await input(c, 'id', 'calendar-date-input', c.fixture.v1.records.calendar.day); await tap(c, 'calendar-go-date');
    const element = await row(c, `event-${spec.event.id}`, spec.rowFields); await dispatchNativeClick(c, element);
    await sourceFacts(c, current.value, `IP docket · ${current.value.record_type}`);
    const wall = await control(c, 'applyIpPolicy', { operation: 'add-owned-wall', docketId: spec.docket.id, subjectMembershipId: spec.subjectMembershipId });
    await tap(c, 'source-detail-reload'); await waitId(c, 'source-unavailable');
    for (const id of ['source-id', 'source-status', 'source-read-only']) assert.equal(await rawCount(c, id), 0, 'WALLED_SOURCE_CONTENT_MUST_BE_UNMOUNTED');
    const denied = await control(c, 'readSource', { kind: 'ip_docket', id: spec.docket.id }); assert.ok([403, 404].includes(denied.status));
    const linked = await workspace(c, spec.linkedMatter); assert.equal(linked.matter.id, spec.linkedMatter.id);
    const receipt = await control(c, 'readControlReceipt', { id: wall.id }); assert.equal(receipt.consumed, true); assert.equal(receipt.nativeMutationCount, 0);
    await control(c, 'applyIpPolicy', { operation: 'restore-owned-source-state', restoration: wall.restoration });
    const restored = await control(c, 'readSource', { kind: 'ip_docket', id: spec.docket.id }); assert.equal(restored.status, 200);
    assert.equal(restored.value.id, current.value.id); assert.equal(restored.value.matter_id, spec.linkedMatter.id); assert.equal(restored.value.record_type, current.value.record_type);
    await tap(c, 'source-detail-reload'); await sourceFacts(c, restored.value, `IP docket · ${restored.value.record_type}`);
    readOnlyTraffic(delta(beforeJourney, await traffic(c)));
    event(c, 'ethical-wall-clears-cache-linked-matter-does-not-bypass-and-explicit-restoration', { docketId: spec.docket.id, matterId: spec.linkedMatter.id });
  } },
  { id: 'SOURCE-07', run: async c => {
    const spec = c.fixture.v1.records.obligations, parent = c.fixture.v1.records.contracts.pages.flatMap(page => page.contracts).find(record => record.id === spec.contractId);
    assert.ok(parent); const before = await traffic(c); await sources(c);
    if (!c.fixture.v1.records.contracts.pages[0].contracts.some(record => record.id === parent.id)) await tap(c, 'source-next-page');
    await contractDetail(c, parent); await tap(c, 'source-open-obligations');
    for (const [index, page] of spec.pages.entries()) {
      await waitFact(c, 'obligation-page', `Page ${index + 1}`);
      const witness = page.obligations.at(-1), element = await row(c, `obligation-row-${witness.id}`, spec.rowFacts[witness.id]);
      await dispatchNativeClick(c, element, 'id', `obligation-row-${witness.id}`);
      for (const [id, value] of Object.entries(spec.detailFacts[witness.id])) await scopedIdFact(c, `obligation-detail-${witness.id}`, id, value);
      const actual = await control(c, 'readObligations', { contractId: spec.contractId, after: index ? spec.pages[0].next_after : null }); assert.deepEqual(actual.value, page);
      if (index === 0) await tap(c, 'obligations-next');
    }
    await tap(c, 'obligations-first'); await waitFact(c, 'obligation-page', 'Page 1'); await tap(c, 'obligations-reload'); await waitFact(c, 'obligation-page', 'Page 1');
    let selectedPage = 0;
    for (const record of [spec.nullable, spec.assigned]) {
      const page = spec.pages.findIndex(value => value.obligations.some(item => item.id === record.id));
      if (page !== selectedPage) { await tap(c, page === 0 ? 'obligations-first' : 'obligations-next'); await waitFact(c, 'obligation-page', `Page ${page + 1}`); selectedPage = page; }
      const element = await row(c, `obligation-row-${record.id}`, spec.rowFacts[record.id]); await dispatchNativeClick(c, element, 'id', `obligation-row-${record.id}`);
      for (const [id, value] of Object.entries(spec.detailFacts[record.id])) await scopedIdFact(c, `obligation-detail-${record.id}`, id, value);
    }
    if (spec.retainedPreview) {
      const preview = spec.retainedPreview; assert.equal(preview.observed, true);
      const page = spec.pages.findIndex(value => value.obligations.some(record => record.id === preview.record.id));
      if (page !== selectedPage) { await tap(c, page === 0 ? 'obligations-first' : 'obligations-next'); await waitFact(c, 'obligation-page', `Page ${page + 1}`); selectedPage = page; }
      const element = await row(c, `obligation-row-${preview.record.id}`, spec.rowFacts[preview.record.id]); await dispatchNativeClick(c, element);
      await scopedFact(c, `obligation-detail-${preview.record.id}`, 'Description preview · first 4,000 characters');
      await scopedIdFact(c, `obligation-detail-${preview.record.id}`, 'obligation-description', preview.record.description);
      event(c, 'retained-long-obligation-preview', { id: preview.record.id, observed: true, evidence: preview.evidence });
    } else event(c, 'retained-long-obligation-preview', { observed: false, status: 'unverified', reason: 'NO_REVIEWED_RETAINED_LONG_SOURCE' });
    await tap(c, 'obligations-close'); assert.equal(await rawCount(c, 'source-obligations'), 0); await tap(c, 'source-open-obligations'); await waitFact(c, 'obligation-page', 'Page 1');
    assert.deepEqual((await control(c, 'readObligations', { contractId: spec.contractId, after: null })).value, spec.pages[0]);
    await tap(c, 'obligations-close'); readOnlyTraffic(delta(before, await traffic(c)));
    event(c, 'obligation-exact-parent-cursor-null-owner-date-detail-reload-close', { contractId: spec.contractId, pages: 2, records: 11 });
  } },
  { id: 'WORK-01', freshAuthentication: true, run: async c => {
    const target = targetAt(c, 0), beforeWorkspace = await workspace(c, target.matter); await openWork(c, target, 'task');
    await fields(c, 'task', target.create.fields);
    const before = await traffic(c), result = await saveOnce(c, { target, kind: 'task', body: { ...target.create.body, expected_lifecycle_version: beforeWorkspace.matter.lifecycle_version }, before });
    assert.equal(beforeWorkspace.tasks.some(x => x.id === result.id), false); assert.equal(result.record.title, target.create.fields.title); assert.equal(result.record.owner_membership_id, null);
    assert.deepEqual(result.workspace.tasks.filter(row => !beforeWorkspace.tasks.some(old => old.id === row.id)).map(row => row.id), [result.id]);
    await tap(c, 'quick-close'); await tap(c, 'matter-reload'); const reloaded = await workspace(c, target.matter); assert.deepEqual(reloaded.tasks.find(x => x.id === result.id), result.record);
    c.state.createdTask = result.record;
  } },
  { id: 'WORK-02', run: async c => {
    const target = targetAt(c, 1), original = clone(target.task); await openWork(c, target, 'task', original);
    await field(c, 'due_on', ''); await segment(c, 'Task status', 'completed'); const before = await traffic(c), snapshot = await workspace(c, target.matter);
    const result = await saveOnce(c, { target: { ...target, recordId: original.id, beforeRecord: original }, kind: 'task', body: { due_on: null, status: 'completed', expected_lifecycle_version: snapshot.matter.lifecycle_version, expected_updated_at: original.updated_at }, before });
    assert.equal(result.record.status, 'completed'); assert.equal(result.record.due_on, null); assert.notEqual(result.record.updated_at, original.updated_at);
    for (const key of ['id', 'matter_id', 'title', 'description', 'priority', 'owner_membership_id']) assert.deepEqual(result.record[key], original[key]);
    const frozenBefore = clone(original); await tap(c, 'quick-reload'); assert.deepEqual(original, frozenBefore); await tap(c, 'quick-close');
    const after = await workspace(c, target.matter); assert.deepEqual(after.tasks.find(x => x.id === original.id), result.record);
    event(c, 'task-dirty-completion-null-clear-and-retained-observations', { id: original.id, previousVersion: original.updated_at, currentVersion: result.record.updated_at });
  } },
  { id: 'WORK-03', run: async c => {
    const target = targetAt(c, 2), snapshot = await workspace(c, target.matter); await openWork(c, target, 'hearing');
    await fields(c, 'hearing', target.create.fields);
    const before = await traffic(c), result = await saveOnce(c, { target, kind: 'hearing', body: { ...target.create.body, expected_lifecycle_version: snapshot.matter.lifecycle_version }, before });
    assert.deepEqual(result.record.reminder_policy.channels, []); assert.equal(result.record.reminder_policy.critical, false);
    assert.deepEqual(result.workspace.hearings.filter(row => !snapshot.hearings.some(old => old.id === row.id)).map(row => row.id), [result.id]);
    assert.deepEqual(result.workspace.tasks, snapshot.tasks, 'HEARING_CREATION_MUST_NOT_MANUFACTURE_TASKS');
    for (const key of ['hearing_on', 'hearing_time', 'timezone', 'time_status']) assert.equal(result.record[key], target.create.body[key]);
    const notifications = await control(c, 'readNotificationState', { hearingId: result.id }); assert.equal(notifications.outboxCount, 0); assert.equal(notifications.providerAttempts, 0);
    await tap(c, 'quick-close'); c.state.createdHearing = result.record;
  } },
  { id: 'WORK-04', freshAuthentication: true, run: async c => {
    const target = targetAt(c, 3); let current = clone(target.hearing);
    for (const [index, transition] of target.transitions.entries()) {
      await openWork(c, { ...target, rowFacts: transition.rowFacts }, 'hearing', current);
      await fields(c, 'hearing', transition.fields);
      const snapshot = await workspace(c, target.matter), before = await traffic(c);
      const result = await saveOnce(c, { target: { ...target, recordId: current.id, beforeRecord: current, transitionIndex: index }, kind: 'hearing', body: { ...transition.body, expected_lifecycle_version: snapshot.matter.lifecycle_version, expected_record_version: current.record_version }, before });
      assert.notEqual(result.record.record_version, current.record_version); for (const [key, value] of Object.entries(transition.expected)) assert.deepEqual(result.record[key], value);
      if (transition.body.status === 'completed') {
        const added = result.workspace.tasks.filter(x => !snapshot.tasks.some(old => old.id === x.id));
        assert.equal(added.length, transition.body.create_follow_up ? 1 : 0);
        if (added.length) { v1Identity(added[0].id); assert.equal(added[0].matter_id, target.matter.id); assert.equal(added[0].title, transition.followUp.title); assert.equal(added[0].status, 'todo'); }
      }
      current = clone(result.record); await tap(c, 'quick-close');
    }
    assert.equal(c.state.versions.filter(x => x.id === current.id).length, 2, 'BOTH_HEARING_TRANSITIONS_REQUIRED');
  } },
  { id: 'WORK-05', run: async c => {
    const target = targetAt(c, 4);
    for (const race of target.races) {
      const prior = await workspace(c, race.matter); assert.deepEqual(prior.tasks.find(row => row.id === race.task.id), race.task);
      await openWork(c, race, 'task', race.task); await field(c, 'title', race.attemptedTitle);
      const before = await traffic(c), barrier = await control(c, 'armWorkBarrier', { method: 'PATCH', route: `/api/matters/${race.matter.id}/tasks/${race.task.id}`, point: 'before-upstream-mutation', maxUses: 1 });
      const key = `${c.caseId}:${race.task.id}`; await dispatchV1SaveOnce(c, key);
      const reached = await control(c, 'readControlReceipt', { id: barrier.id, waitFor: 'reached' }); assert.equal(reached.reached, true);
      const changed = await control(c, race.kind === 'parent' ? 'changeMatterLifecycle' : 'changeChild', race.change); assert.equal(changed.completed, true);
      assert.equal(changed.workspace.matter.id, race.matter.id); assert.equal(changed.workspace.matter.company_id, c.fixture.companyId);
      await control(c, 'releaseWorkBarrier', { id: barrier.id }); await outcome(c, ['rejected']);
      const trace = await control(c, 'readNativeRequest', { afterSequence: before.lastSequence, method: 'PATCH', route: `/api/matters/${race.matter.id}/tasks/${race.task.id}` });
      validateV1MutationEvidence(trace.requests, delta(before, await traffic(c)), { method: 'PATCH', route: `/api/matters/${race.matter.id}/tasks/${race.task.id}`,
        body: { title: race.attemptedTitle, expected_lifecycle_version: prior.matter.lifecycle_version, expected_updated_at: race.task.updated_at }, expectedStatus: [409] });
      const actual = await workspace(c, race.matter); assert.notEqual(actual.tasks.find(x => x.id === race.task.id)?.title, race.attemptedTitle);
      assert.deepEqual(actual.tasks.find(row => row.id === race.task.id), changed.workspace.tasks.find(row => row.id === race.task.id), 'REJECTED_NATIVE_SAVE_MUST_PRESERVE_OWNER_ACKNOWLEDGED_RECORD');
      const receipt = await control(c, 'readControlReceipt', { id: barrier.id }); assert.equal(receipt.requestsForwarded, 1); assert.equal(receipt.nativeMutationCommitted, false);
      await tap(c, 'quick-reload');
      if (race.expectedCanStartNewRequest) await waitId(c, 'quick-new-request');
      else { await expectText(c, 'Current access or record state no longer permits editing. The prior save outcome is unchanged.'); assert.equal(await rawCount(c, 'quick-new-request'), 0);
        await waitId(c, 'quick-content-unavailable'); for (const id of ['quick-title', 'quick-description', 'quick-due_on']) assert.equal(await rawCount(c, id), 0); }
      assert.equal(await ui(c, 'quick-attempt-history'), 'Earlier attempt outcomes retained in this editor: rejected. Starting a new request does not replay or erase them.');
      await closeRejectedV1Editor(c, race.expectedCanStartNewRequest);
      event(c, 'work-stale-parent-or-child-refused-once', { kind: race.kind, id: race.task.id });
    }
  } },
  { id: 'WORK-06', run: async c => {
    const target = targetAt(c, 5), prior = await workspace(c, target.matter); await openWork(c, target, 'task'); await fields(c, 'task', target.create.fields);
    const before = await traffic(c), arm = await control(c, 'armUnknownResponse', { method: 'POST', route: `/api/matters/${target.matter.id}/tasks`, mode: 'drop-after-successful-upstream-ack', maxUses: 1 });
    const key = `${c.caseId}:creation`; await dispatchV1SaveOnce(c, key); await outcome(c, ['unknown']);
    assert.equal(await rawCount(c, 'quick-save'), 0); assert.equal(await rawCount(c, 'quick-new-request'), 0);
    await tap(c, 'quick-close'); await textTap(c, 'Stay'); await waitId(c, 'quick-unknown'); await tap(c, 'quick-reload'); await waitId(c, 'quick-unknown');
    assert.equal(await rawCount(c, 'quick-new-request'), 0, 'UNKNOWN_CREATION_MUST_NOT_REARM');
    const receipt = await control(c, 'readControlReceipt', { id: arm.id }); assert.equal(receipt.requestsForwarded, 1); assert.equal(receipt.upstreamStatus, 200); assert.equal(receipt.clientResponseWithheld, true); v1Identity(receipt.acknowledgedId);
    const trace = await control(c, 'readNativeRequest', { afterSequence: before.lastSequence, method: 'POST', route: `/api/matters/${target.matter.id}/tasks` });
    validateV1MutationEvidence(trace.requests, delta(before, await traffic(c)), { method: 'POST', route: `/api/matters/${target.matter.id}/tasks`,
      body: { ...target.create.body, expected_lifecycle_version: prior.matter.lifecycle_version }, expectedStatus: [200] });
    const current = await workspace(c, target.matter), created = current.tasks.filter(x => x.id === receipt.acknowledgedId); assert.equal(created.length, 1); assert.equal(created[0].title, target.create.fields.title);
    assert.deepEqual(current.tasks.filter(row => !prior.tasks.some(old => old.id === row.id)).map(row => row.id), [receipt.acknowledgedId]);
    await tap(c, 'quick-close'); await textTap(c, 'Leave editor');
    const finalTrace = await control(c, 'readNativeRequest', { afterSequence: before.lastSequence, method: 'POST', route: `/api/matters/${target.matter.id}/tasks` }); assert.equal(finalTrace.requests.filter(x => x.method === 'POST').length, 1);
    event(c, 'unknown-creation-stay-reload-leave-no-replay', { acknowledgedId: receipt.acknowledgedId, requestsForwarded: 1 });
  } },
  { id: 'WORK-07', actor: 'second-company', freshAuthentication: true, run: async c => {
    const spec = c.fixture.v1.records.policy.readOnly, second = c.state.activeFixture;
    const other = { ...c, fixture: second, actor: 'second-company' }, before = await traffic(c);
    const actor = await control(c, 'readCurrentActor', { actor: 'second-company' });
    assert.equal(actor.value.membershipId, second.membershipId); assert.equal(actor.value.companyId, second.companyId);
    assert.equal(actor.value.role, 'viewer'); assert.equal(actor.value.capabilities.includes('matters:write'), false);
    const initial = await workspace(other, spec.matter); assert.equal(initial.matter.id, spec.matter.id);
    await openMatter(other, spec.matter); await segment(other, 'Matter view', 'Work');
    for (const [kind, record] of [['task', spec.task], ['hearing', spec.hearing]]) {
      const element = await readOnlyV1Row(other, `${kind}-${record.id}`, spec.rowFacts[kind][record.id]);
      other.budget.control(); await dispatchNativeClick(other, element, 'id', `${kind}-${record.id}`);
      assert.equal(await rawCount(other, 'quick-work-editor'), 0, 'VIEWER_ROW_MUST_NOT_OPEN_EDITOR');
    }
    for (const id of ['quick-task-add', 'quick-hearing-add', 'quick-save', 'quick-work-editor']) assert.equal(await rawCount(other, id), 0);
    await expectText(other, 'Work is read-only for this account or Matter lifecycle.');
    await tap(other, 'matter-reload'); const reloaded = await workspace(other, spec.matter); assert.deepEqual(reloaded, initial);
    readOnlyTraffic(delta(before, await traffic(other)));
    event(c, 'normal-viewer-exact-actor-readonly-rows-no-editor-and-reload', { membershipId: second.membershipId, matterId: spec.matter.id });
  } },
  { id: 'WORK-08', freshAuthentication: true, run: async c => {
    const spec = c.fixture.v1.records.policy.revokedWork, prior = await workspace(c, spec.matter);
    assert.deepEqual(prior.tasks.find(record => record.id === spec.task.id), spec.task);
    await openWork(c, spec, 'task', spec.task); await fields(c, 'task', spec.fields);
    const route = `/api/matters/${spec.matter.id}/tasks/${spec.task.id}`, before = await traffic(c);
    const barrier = await control(c, 'armWorkBarrier', { method: 'PATCH', route, point: 'before-upstream-mutation', maxUses: 1 });
    await dispatchV1SaveOnce(c, `${c.caseId}:${spec.task.id}`);
    assert.equal((await control(c, 'readControlReceipt', { id: barrier.id, waitFor: 'reached' })).reached, true);
    const revoked = await control(c, 'changeMatterAccess', { operation: 'revoke-owned-grant', matterId: spec.matter.id, grantId: spec.grantId, subjectMembershipId: spec.subjectMembershipId });
    assert.equal(revoked.completed, true);
    assert.equal(revoked.workspace.matter.id, spec.matter.id); assert.equal(revoked.workspace.matter.company_id, c.fixture.companyId);
    assert.equal(revoked.workspace.matter.lifecycle_version, prior.matter.lifecycle_version);
    assert.deepEqual(revoked.workspace.tasks, prior.tasks); assert.deepEqual(revoked.workspace.hearings, prior.hearings);
    const denied = await control(c, 'readWorkspace', { actor: 'member', matterId: spec.matter.id }); assert.ok([403, 404].includes(denied.status));
    await control(c, 'releaseWorkBarrier', { id: barrier.id }); await outcome(c, ['rejected']); await waitId(c, 'quick-content-unavailable');
    for (const id of ['quick-title', 'quick-description', 'quick-due_on', 'quick-save', 'quick-new-request']) assert.equal(await rawCount(c, id), 0, 'REVOKED_PRIVATE_EDITOR_CONTENT_MUST_BE_UNMOUNTED');
    assert.ok(!await visible(c.driver, selector(c.platform, 'text', spec.task.title)), 'REVOKED_PRIVATE_TITLE_MUST_BE_CLEARED');
    const trace = await control(c, 'readNativeRequest', { afterSequence: before.lastSequence, method: 'PATCH', route });
    validateV1MutationEvidence(trace.requests, delta(before, await traffic(c)), { method: 'PATCH', route,
      body: { ...spec.body, expected_lifecycle_version: prior.matter.lifecycle_version, expected_updated_at: spec.task.updated_at }, expectedStatus: [403] });
    const unchanged = await workspace(c, spec.matter, 'owner'); assert.deepEqual(unchanged, revoked.workspace, 'REVOKED_SAVE_MUST_PRESERVE_OWNER_ACKNOWLEDGED_WORKSPACE');
    const receipt = await control(c, 'readControlReceipt', { id: barrier.id }); assert.equal(receipt.requestsForwarded, 1); assert.equal(receipt.nativeMutationCommitted, false);
    const restored = await control(c, 'changeMatterAccess', { operation: 'restore-owned-grant', restoration: revoked.restoration });
    assert.equal(restored.completed, true); assert.equal(restored.workspace.matter.id, spec.matter.id);
    assert.deepEqual(restored.workspace.tasks, prior.tasks); assert.deepEqual(restored.workspace.hearings, prior.hearings);
    await tap(c, 'quick-close'); assert.equal(await rawCount(c, 'quick-work-editor'), 0);
    await openMatter(c, spec.matter); await segment(c, 'Matter view', 'Work');
    const reloaded = await workspace(c, spec.matter); assert.deepEqual(reloaded.tasks, prior.tasks); assert.deepEqual(reloaded.hearings, prior.hearings);
    assert.equal(reloaded.matter.lifecycle_version, prior.matter.lifecycle_version);
    const finalTrace = await control(c, 'readNativeRequest', { afterSequence: before.lastSequence, method: 'PATCH', route }); assert.equal(finalTrace.requests.filter(record => record.method === 'PATCH').length, 1);
    event(c, 'grant-revoked-after-preflight-one403-no-commit-private-purge-explicit-restoration', { taskId: spec.task.id, matterId: spec.matter.id });
  } },
  { id: 'COUNSEL-01', freshAuthentication: true, run: async c => {
    const spec = c.fixture.v1.records.counsel, before = await traffic(c); await openMatter(c, spec.matter); await tap(c, 'matter-counsel');
    await waitFact(c, 'counsel-matter-code', spec.matter.identityLabel); await waitFact(c, 'counsel-matter-title', spec.matter.title);
    assert.equal(await ui(c, 'counsel-read-only'), 'Read-only Matter context. Totals cover the two selected pages.');
    const states = [{ assignmentAfter: null, spendAfter: null }, { assignmentAfter: spec.pages[0].assignment_next_after, spendAfter: null },
      { assignmentAfter: spec.pages[0].assignment_next_after, spendAfter: spec.pages[0].spend_next_after }];
    for (const [index, page] of spec.pages.entries()) {
      assert.deepEqual((await control(c, 'readCounsel', { matterId: spec.matter.id, ...states[index] })).value, page);
      if (index === 0) { await tap(c, 'counsel-assignment-next'); await waitFact(c, 'counsel-assignment-page', 'Assignments page 2'); }
      if (index === 1) { await segment(c, 'Counsel view', 'Spend'); await tap(c, 'counsel-spend-next'); await waitFact(c, 'counsel-spend-page', 'Spend page 2'); }
    }
    const final = spec.pages[2], spend = final.spend_records[0];
    const spending = await row(c, `counsel-spend-row-${spend.id}`, spec.rowFacts.spend[spend.id]); await dispatchNativeClick(c, spending);
    for (const [id, value] of Object.entries(spec.detailFacts.spend[spend.id])) await scopedIdFact(c, `counsel-spend-${spend.id}`, id, value);
    await tap(c, 'counsel-detail-back'); await segment(c, 'Counsel view', 'Assignments');
    const assignment = final.assignments[0], assigned = await row(c, `counsel-assignment-row-${assignment.id}`, spec.rowFacts.assignment[assignment.id]); await dispatchNativeClick(c, assigned);
    for (const [id, value] of Object.entries(spec.detailFacts.assignment[assignment.id])) await scopedIdFact(c, `counsel-assignment-${assignment.id}`, id, value);
    for (const fact of spec.moneyFacts) if (fact.recordId === assignment.id) await scopedIdFact(c, `counsel-assignment-${assignment.id}`, fact.fieldId, fact.expectedLabel);
    await tap(c, 'counsel-detail-back'); await segment(c, 'Counsel view', 'Page totals');
    await waitFact(c, 'counsel-totals-scope', 'Totals for assignments page 2 and spend page 2');
    for (const [index, currency] of final.currencies.entries()) {
      const element = await row(c, `counsel-currency-${index}`, spec.currencyRows[currency.currency]); await dispatchNativeClick(c, element);
      for (const [id, value] of Object.entries(spec.totalFacts[currency.currency])) await scopedIdFact(c, 'counsel-currency-detail', id, value);
      await tap(c, 'counsel-detail-back');
    }
    await tap(c, 'counsel-reload'); await waitFact(c, 'counsel-totals-scope', 'Totals for assignments page 2 and spend page 2');
    assert.deepEqual((await control(c, 'readCounsel', { matterId: spec.matter.id, ...states[2] })).value, final);
    readOnlyTraffic(delta(before, await traffic(c))); event(c, 'counsel-independent-cursors-page-totals-minor-units-and-reload', { matterId: spec.matter.id, assignmentPages: 2, spendPages: 2 });
  } },
  { id: 'INBOX-01', run: async c => {
    const spec = c.fixture.v1.records.inbox, beforeJourney = await traffic(c);
    const actor = await control(c, 'readCurrentActor', { actor: 'member' }); assert.equal(actor.value.membershipId, spec.membershipId); assert.equal(actor.value.companyId, spec.companyId);
    await textTap(c, 'Notifications'); await waitId(c, 'screen-inbox'); await segment(c, 'Notification view', 'Active');
    const scope = `notification-${spec.notification.id}`;
    await scopedFact(c, scope, spec.notification.title); await scopedAction(c, scope, 'Open source record');
    await waitFact(c, 'matter-code', spec.matter.identityLabel); await expectText(c, spec.matter.title); await tap(c, 'back', { scroll: false }); await waitId(c, 'screen-inbox');
    let prior = clone(spec.notification);
    for (const state of spec.transitions) {
      await scopedFact(c, scope, spec.statusRows[prior.status]);
      const before = await traffic(c), key = `${c.caseId}:${prior.id}:${state}`; assert.equal(c.state.dispatched.has(key), false, 'INBOX_MUTATION_REPLAY_REFUSED'); c.state.dispatched.add(key);
      await scopedAction(c, scope, state === 'read' ? 'Mark as read' : state === 'dismissed' ? 'Dismiss notification' : 'Restore notification');
      if (state === 'dismissed') await segment(c, 'Notification view', 'Dismissed');
      if (state === 'unread') await segment(c, 'Notification view', 'Active');
      await scopedFact(c, scope, spec.statusRows[state]);
      const route = `/api/recipient-inbox/${prior.id}`, trace = await control(c, 'readNativeRequest', { afterSequence: before.lastSequence, method: 'PATCH', route });
      const ack = validateV1InboxMutationEvidence(trace.requests, delta(before, await traffic(c)), { id: prior.id, body: { status: state, expected_status: prior.status }, target: prior.target });
      const current = await control(c, 'readInbox', { actor: 'member', view: state === 'dismissed' ? 'dismissed' : 'active', cursor: null });
      const matches = current.value.items.filter(record => record.id === prior.id); assert.equal(matches.length, 1); const next = matches[0];
      assert.equal(next.status, state); for (const field of ['id', 'title', 'body', 'created_at', 'target', 'target_label']) assert.deepEqual(next[field], prior[field]);
      event(c, 'inbox-one-native-status-transition-and-readback', { id: prior.id, before: prior.status, after: next.status, requestId: ack.requestId }); prior = clone(next);
    }
    await textTap(c, 'Reload notifications'); await scopedFact(c, scope, spec.statusRows.unread);
    const writes = delta(beforeJourney, await traffic(c)).filter(record => !['GET', 'HEAD', 'OPTIONS'].includes(record.method) && !(record.method === 'POST' && record.route === '/api/auth/native/refresh'));
    assert.equal(writes.length, 3); assert.ok(writes.every(record => record.method === 'PATCH' && record.route === `/api/recipient-inbox/${prior.id}` && record.status === 200));
    assert.equal(spec.externalCalls, 0); assert.equal(spec.manualReceiptInsertion, false);
    event(c, 'delivered-inbox-source-read-dismiss-restore-reload-no-replay', { notificationId: prior.id, deliveryEvidence: spec.deliveryEvidence });
  } },
].map(value => Object.freeze(value)));

export function collectV1Workflows(platform) { return collectV1(platform, v1WorkflowScenarios); }
export function prepareV1Context(context) {
  validateV1Fixture(context.fixture, context.platform);
  assert.ok(context.driver && context.controls && context.state, 'ACTUAL_V1_CONTEXT_REQUIRED');
  const budget = createV1CaseBudget();
  return { ...context, budget, record: value => {
    // Shared openMatter/home/browser-native helpers also emit this canonical
    // event. Charge their actions rather than count only this module's taps.
    if (value.type === 'native_ui_action') budget.control();
    context.record?.(value);
  } };
}
