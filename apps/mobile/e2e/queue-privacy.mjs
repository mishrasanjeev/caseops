import assert from 'node:assert/strict';
import { setTimeout as pause } from 'node:timers/promises';
import { collectQP, decodeQueuePage, decodeAccountDeletionReceipt, expectedQueue, hash } from './queue-privacy-contract.mjs';
import { find, findQuery, read, visible, selector, dispatchNativeClick, nativeAction, home } from './native-ui.mjs';
import { traffic,delta,readOnlyTraffic } from './journeys.mjs';
import { displayDay } from '../src/domain/contracts.ts';
const event=(c,boundary,facts={})=>c.record({type:'queue_privacy_assertion',boundary,...facts});
const consume=c=>assert.ok(++c.nativeOperations<=160,'QP_NATIVE_CONTROL_BOUND');
const NATIVE_STATE_MS = 20000;
const ANDROID_SCROLL_LIMIT = 10;
const ANDROID_SCROLL_PERCENT = 0.65;
async function tap(c,id){consume(c);const e=await find(c,'id',id,{scroll:true});assert.equal(await e.isEnabled(),true);await dispatchNativeClick(c,e,'id',id);}
async function fact(c,id){consume(c);return read(c,'id',id,{scroll:true});}
async function wait(c,id,value){let terminal;await c.driver.waitUntil(async()=>{try{const e=await visible(c.driver,selector(c.platform,'id',id));return!!e&&(value===undefined||await e.getText()===value);}catch(e){terminal=e;return true;}},{timeout:NATIVE_STATE_MS,interval:200,timeoutMsg:'QP_NATIVE_STATE_REQUIRED'});if(terminal)throw terminal;}
async function absent(c,id){consume(c);assert.equal((await c.driver.$$(selector(c.platform,'id',id))).length,0,'QP_PRIVATE_OLD_CONTROL_REMAINS');}
async function control(c,name,args={}){assert.ok(++c.controlCalls<=24,'QP_CASE_CONTROL_BOUND');return c.controls[name]({caseId:c.caseId,...args});}
export function assertObservedStaleQueueCursor(records,{afterSequence,staleAfterSequence,anchorId}){
 assert.ok(Array.isArray(records)&&records.length<=100&&Number.isSafeInteger(afterSequence)&&afterSequence>=0
  &&Number.isSafeInteger(staleAfterSequence)&&staleAfterSequence>=afterSequence,'QP_NATIVE_CURSOR_WINDOW_REQUIRED');
 let previous=afterSequence;
 for(const row of records){
  assert.ok(Number.isSafeInteger(row.sequence)&&row.sequence>previous&&row.method==='GET'
   &&row.route==='/api/matter-work-queue','QP_NATIVE_CURSOR_RECORD_ORDER_REQUIRED');previous=row.sequence;
 }
 const pages=records.filter(row=>row.sequence<=staleAfterSequence&&row.status===200
  &&row.queryObservation?.ownership==='mine'&&row.queryObservation?.dates==='all'&&row.queryObservation?.cursorSha256===null);
 assert.equal(pages.length,1,'QP_EXACT_DELIVERED_NATIVE_PAGE_REQUIRED');
 const page=pages[0],response=page.responseObservation;
 assert.match(response?.nextCursorSha256??'',/^[a-f0-9]{64}$/,'QP_DELIVERED_NATIVE_CURSOR_REQUIRED');
 assert.equal(response.anchorIdSha256,hash(Buffer.from(anchorId)),'QP_DELIVERED_NATIVE_ANCHOR_REQUIRED');
 const requests=records.filter(row=>row.sequence>staleAfterSequence);
 assert.equal(requests.length,1,'QP_SINGLE_STALE_NATIVE_REQUEST_REQUIRED');
 const request=requests[0];assert.equal(request.status,409,'QP_STALE_NATIVE_REJECTION_REQUIRED');
 assert.equal(request.queryObservation?.ownership,'mine','QP_STALE_NATIVE_SCOPE_REQUIRED');
 assert.equal(request.queryObservation?.dates,'all','QP_STALE_NATIVE_SCOPE_REQUIRED');
 assert.equal(request.queryObservation?.cursorSha256,response.nextCursorSha256,'QP_DELIVERED_CURSOR_MUST_BE_SUBMITTED');
 return {nativePageSequence:page.sequence,staleRequestSequence:request.sequence,
  deliveredCursorSha256:response.nextCursorSha256,anchorIdSha256:response.anchorIdSha256};
}
export async function withQPAnchorRestoration(c,operation){
 const changed=await control(c,'changeAnchor',{action:'change'});
 assert.equal(changed.acknowledged,true);assert.equal(changed.id,c.fixture.qp.dataset.anchor.id);
 let restoreAttempted=false,bodyFailure;
 const restore=async()=>{
  assert.equal(restoreAttempted,false,'QP_ANCHOR_RESTORE_REPLAY_REFUSED');
  // Consume before dispatch: a lost restoration ACK must never be retried.
  restoreAttempted=true;const result=await control(c,'changeAnchor',{action:'restore'});
  assert.equal(result.acknowledged,true);assert.equal(result.id,changed.id);return result;
 };
 try{return await operation({changed,restore});}
 catch(error){bodyFailure=error;c.record?.({type:'qp_queue_body_failure',reason:'QP_QUEUE_BODY_FAILED'});throw error;}
 finally{
  if(!restoreAttempted)try{await restore();}catch(cleanupFailure){
   c.record?.({type:'qp_queue_restore_failure',reason:'QP_QUEUE_RESTORE_FAILED'});
   if(bodyFailure)throw new AggregateError([bodyFailure,cleanupFailure],'QP_QUEUE_BODY_AND_RESTORE_FAILED');
   throw cleanupFailure;
  }
 }
}
const queueSegments = {
  'Task ownership': ['Mine', 'Team', 'Unassigned'],
  'Task dates': ['All dates', 'Dated', 'Undated'],
};
function containsFrame(outer, inner) {
  const valid = (frame) => frame && [frame.x, frame.y, frame.width, frame.height].every(Number.isFinite) &&
    frame.width > 0 && frame.height > 0;
  return valid(outer) && valid(inner) && inner.x >= outer.x && inner.y >= outer.y &&
    inner.x + inner.width <= outer.x + outer.width && inner.y + inner.height <= outer.y + outer.height;
}

async function withinAndroidViewport(reason, operation) {
  const deadline = performance.now() + NATIVE_STATE_MS;
  let active = true, timer;
  const check = () => assert.ok(active && performance.now() < deadline, reason);
  const probe = async (command) => {
    check();
    const result = await command();
    check();
    return result;
  };
  try {
    return await Promise.race([
      operation(probe),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(reason)), NATIVE_STATE_MS); }),
    ]);
  } finally {
    active = false;
    clearTimeout(timer);
  }
}
const queueViewport = "//*[@resource-id='screen-work' or @resource-id='matter-task-queue']/ancestor::*[@class='android.widget.ScrollView'][1]";
async function androidScrollScope(c, screen, probe) {
  const query = screen === 'work' ? queueViewport : selector('android', 'id', 'account-screen');
  const scope = await visible(c.driver, query, probe);
  assert.ok(scope, 'QP_ANDROID_OWNED_SCROLL_VIEW_REQUIRED');
  assert.equal(await probe(() => scope.getAttribute('class')), 'android.widget.ScrollView', 'QP_ANDROID_OWNED_SCROLL_VIEW_REQUIRED');
  assert.equal(await probe(() => scope.getAttribute('package')), c.fixture.appId, 'QP_ANDROID_WRONG_SCROLL_PACKAGE');
  return scope;
}
async function androidScroll(c, scope, direction, probe) {
  const frame = await probe(() => c.driver.getElementRect(scope.elementId));
  const window = await probe(() => c.driver.getWindowRect());
  assert.ok(containsFrame(window, frame), 'QP_ANDROID_SCROLL_OUTSIDE_WINDOW');
  consume(c);
  const more = await probe(() => c.driver.execute('mobile: scrollGesture',
    { elementId: scope.elementId, direction, percent: ANDROID_SCROLL_PERCENT }));
  assert.equal(typeof more, 'boolean', 'QP_ANDROID_SCROLL_ACK_REQUIRED');
  return more;
}
async function revealAndroidWorkHeader(c, scope, probe) {
  for (let n = 0; n <= ANDROID_SCROLL_LIMIT; n++) {
    if (await visible(c.driver, selector('android', 'id', 'screen-work'), probe)) return;
    assert.ok(n < ANDROID_SCROLL_LIMIT, 'QP_ANDROID_WORK_HEADER_REQUIRED');
    if (!await androidScroll(c, scope, 'up', probe)) break;
  }
  assert.ok(await visible(c.driver, selector('android', 'id', 'screen-work'), probe), 'QP_ANDROID_WORK_HEADER_REQUIRED');
}

export async function waitForQPPrivacyControl(c, id, value) {
  if (c.platform !== 'android') return wait(c, id, value);
  return withinAndroidViewport('QP_NATIVE_STATE_REQUIRED', async (probe) => {
    const query = selector('android', 'id', id);
    const scope = await androidScrollScope(c, 'account', probe);
    let direction = 'up', gestures = 0, atBottom = false;
    for (;;) {
      const control = await visible(c.driver, query, probe);
      if (control) {
        assert.equal(await probe(() => control.getAttribute('package')), c.fixture.appId, 'QP_ANDROID_WRONG_PRIVACY_PACKAGE');
        if (value === undefined || await probe(() => control.getText()) === value) return;
      } else if (!atBottom && gestures < ANDROID_SCROLL_LIMIT) {
        gestures++;
        if (!await androidScroll(c, scope, direction, probe)) {
          if (direction === 'up') direction = 'down';
          else atBottom = true;
        }
        continue;
      }
      // A visible transient state can settle in place. Do not scroll it away.
      await probe(() => pause(200));
    }
  });
}

export async function assertQPPrivacyControlsAbsent(c, ids) {
  if (c.platform !== 'android') {
    for (const id of ids) await absent(c, id);
    return;
  }
  return withinAndroidViewport('QP_NATIVE_STATE_REQUIRED', async (probe) => {
    const scope = await androidScrollScope(c, 'account', probe);
    const edge = async (direction, observe) => {
      for (let n = 0; n <= ANDROID_SCROLL_LIMIT; n++) {
        if (observe) await observe();
        if (n === ANDROID_SCROLL_LIMIT) break;
        if (!await androidScroll(c, scope, direction, probe)) {
          if (observe) await observe();
          return;
        }
      }
      throw Error('QP_ANDROID_PRIVACY_EDGE_NOT_REACHED');
    };
    const observedAbsent = async () => {
      for (const id of ids) {
        const matches = await probe(() => c.driver.$$(selector('android', 'id', id)));
        assert.equal(matches.length, 0, 'QP_PRIVATE_OLD_CONTROL_REMAINS');
      }
    };
    for (const id of ids) { selector('android', 'id', id); consume(c); }
    await edge('up');
    await edge('down', observedAbsent);
    // Leave the viewport on the account request section for the next action.
    for (let n = 0; n <= ANDROID_SCROLL_LIMIT; n++) {
      if (await visible(c.driver, selector('android', 'id', 'privacy-request-state'), probe)) return;
      if (n === ANDROID_SCROLL_LIMIT) break;
      if (!await androidScroll(c, scope, 'up', probe)) {
        if (await visible(c.driver, selector('android', 'id', 'privacy-request-state'), probe)) return;
        break;
      }
    }
    throw Error('QP_NATIVE_STATE_REQUIRED');
  });
}

export async function resolveAndroidComposeQueueSegment(c, group, label, probe = operation => operation()) {
  assert.equal(c.platform, 'android');
  assert.ok(Object.hasOwn(queueSegments, group) && queueSegments[group].includes(label), 'QP_ANDROID_QUEUE_LABEL_REQUIRED');
  const { driver } = c;
  const work = await visible(driver, selector('android', 'id', 'screen-work'), probe);
  const queue = await visible(driver, selector('android', 'id', 'matter-task-queue'), probe);
  assert.ok(work && queue, 'QP_ANDROID_WORK_QUEUE_REQUIRED');
  // Compose puts the exact label on a noninteractive TextView and its radio
  // semantics on the direct parent. The RN queue marker is flattened beside it.
  const labelQuery = `//*[@class='android.widget.TextView' and @text='${label}']`;
  const leaves = await probe(() => driver.$$(labelQuery));
  const parents = await probe(() => driver.$$(`${labelQuery}/parent::*`));
  assert.equal(leaves.length, 1, 'QP_ANDROID_EXACT_QUEUE_LABEL_REQUIRED');
  assert.equal(parents.length, 1, 'QP_ANDROID_EXACT_QUEUE_PARENT_REQUIRED');
  const [leaf] = leaves, [parent] = parents;
  assert.equal(await probe(() => leaf.isDisplayed()), true, 'QP_ANDROID_QUEUE_LABEL_NOT_VISIBLE');
  assert.equal(await probe(() => parent.isDisplayed()), true, 'QP_ANDROID_QUEUE_PARENT_NOT_VISIBLE');
  assert.equal(await probe(() => parent.isEnabled()), true, 'QP_ANDROID_QUEUE_PARENT_DISABLED');
  assert.equal(await probe(() => parent.getAttribute('package')), c.fixture.appId, 'QP_ANDROID_QUEUE_PARENT_WRONG_PACKAGE');
  assert.equal(await probe(() => parent.getAttribute('checkable')), 'true', 'QP_ANDROID_QUEUE_RADIO_REQUIRED');
  const queueFrame = await probe(() => driver.getElementRect(queue.elementId));
  const parentFrame = await probe(() => driver.getElementRect(parent.elementId));
  const labelFrame = await probe(() => driver.getElementRect(leaf.elementId));
  assert.ok(containsFrame(queueFrame, parentFrame) && containsFrame(parentFrame, labelFrame), 'QP_ANDROID_QUEUE_PARENT_OUTSIDE_SCOPE');
  const checked = await probe(() => parent.getAttribute('checked'));
  assert.ok(['true', 'false'].includes(checked), 'QP_ANDROID_QUEUE_CHECKED_STATE_REQUIRED');
  const selected = checked === 'true';
  assert.equal(await probe(() => parent.getAttribute('clickable')), selected ? 'false' : 'true', 'QP_ANDROID_QUEUE_PARENT_CLICKABILITY');
  if (c.queueViewportDiagnostics === true) c.record({ type: 'qp_android_queue_segment', group, label, selected });
  return { parent, selected };
}

export async function selectQueueSegment(c, group, label) {
 const observed=c.fixture.qp.nativeSelectors;assert.equal(observed.observed,true);assert.equal(observed.udid,c.fixture.udid);assert.deepEqual(observed.buildReceipt,c.fixture.buildReceipt);
 const r=observed.segments[group]?.[label];assert.ok(r&&r.group===group&&r.label===label);
 if (r.kind === 'android-compose-parent') {
   assert.equal(typeof r.selectedAtObservation, 'boolean', 'QP_ANDROID_QUEUE_OBSERVED_STATE_REQUIRED');
   const { parent, selected } = await withinAndroidViewport('QP_ANDROID_WORK_HEADER_REQUIRED', async (probe) => {
     if (!await visible(c.driver, selector('android', 'id', 'screen-work'), probe)) {
       const scope = await androidScrollScope(c, 'work', probe);
       await revealAndroidWorkHeader(c, scope, probe);
     }
     return resolveAndroidComposeQueueSegment(c, group, label, probe);
   });
   assert.equal(selected, false, 'QP_ANDROID_QUEUE_TRANSITION_ALREADY_SELECTED');
   consume(c);
   await dispatchNativeClick(c, parent);
   return;
 }
 assert.ok(r.query.startsWith(c.platform==='ios'?'-ios predicate string:':'android='));
 const scope=r.scopeQuery?await findQuery(c,r.scopeQuery,{scroll:true}):c.driver,e=await visible(scope,r.query);assert.ok(e);assert.equal(await e.getAttribute(r.labelAttribute),label);consume(c);await dispatchNativeClick(c,e);
}
export const QP_ANDROID_QUEUE_RESPONSE_ATTRIBUTES = 'displayed,attribute/resource-id,attribute/package';
export async function configureQPAndroidQueueRows(driver, record) {
  const prior = await driver.getSettings();
  assert.equal(typeof prior.shouldUseCompactResponses, 'boolean', 'QP_ANDROID_BATCH_SETTINGS_REQUIRED');
  assert.ok(typeof prior.elementResponseAttributes === 'string' && prior.elementResponseAttributes.length <= 256,
    'QP_ANDROID_BATCH_SETTINGS_REQUIRED');
  assert.equal(prior.waitForIdleTimeout,500,'QP_ANDROID_ORIGINAL_IDLE_SETTING_REQUIRED');
  const original = { shouldUseCompactResponses: prior.shouldUseCompactResponses, elementResponseAttributes: prior.elementResponseAttributes };
  let restorationAttempted = false;
  const restore = async () => {
    assert.equal(restorationAttempted, false, 'QP_ANDROID_BATCH_RESTORATION_REPLAY_REFUSED');
    restorationAttempted = true;
    await driver.updateSettings(original);
    const actual = await driver.getSettings();
    for (const [key, value] of Object.entries(original)) assert.equal(actual[key], value, 'QP_ANDROID_BATCH_RESTORATION_REQUIRED');
    record?.({ type: 'qp_android_queue_response_settings', state: 'restored' });
  };
  try {
    await driver.updateSettings({ shouldUseCompactResponses: false, elementResponseAttributes: QP_ANDROID_QUEUE_RESPONSE_ATTRIBUTES });
    const actual = await driver.getSettings();
    assert.equal(actual.shouldUseCompactResponses, false, 'QP_ANDROID_BATCH_SETTINGS_REQUIRED');
    assert.equal(actual.elementResponseAttributes, QP_ANDROID_QUEUE_RESPONSE_ATTRIBUTES, 'QP_ANDROID_BATCH_SETTINGS_REQUIRED');
    assert.equal(actual.waitForIdleTimeout,500,'QP_ANDROID_BATCH_SETTINGS_REQUIRED');
    record?.({ type: 'qp_android_queue_response_settings', state: 'configured', attributes: QP_ANDROID_QUEUE_RESPONSE_ATTRIBUTES, waitForIdleTimeout:500 });
  } catch (error) {
    try { await restore(); } catch (cleanup) { const combined=new AggregateError([error, cleanup], 'QP_ANDROID_BATCH_SETUP_AND_RESTORATION_FAILED');combined.code='QP_ANDROID_QUEUE_SETTINGS_CLEANUP_UNCERTAIN';throw combined; }
    throw error;
  }
  return restore;
}

export async function withQPAndroidQueueRows(c, operation) {
  assert.equal(c.platform,'android');
  let restore;
  try { restore=await configureQPAndroidQueueRows(c.driver,c.record); }
  catch(error) { if(error.code==='QP_ANDROID_QUEUE_SETTINGS_CLEANUP_UNCERTAIN')c.nativeSettingsCleanupUncertain=true;throw error; }
  let original;
  try { return await operation(); }
  catch(error) { original=error;throw error; }
  finally {
    try { await restore(); }
    catch(cleanup) {
      c.nativeSettingsCleanupUncertain=true;
      const combined=new AggregateError(original?[original,cleanup]:[cleanup],'QP_ANDROID_QUEUE_SETTINGS_CLEANUP_UNCERTAIN');
      combined.code='QP_ANDROID_QUEUE_SETTINGS_CLEANUP_UNCERTAIN';throw combined;
    }
  }
}

export async function withQPAndroidQueuePageIdle(c, operation) {
  assert.equal(c.platform,'android');
  const prior=await c.driver.getSettings();
  assert.equal(prior.waitForIdleTimeout,500,'QP_ANDROID_ORIGINAL_IDLE_SETTING_REQUIRED');
  let restorationAttempted=false,original;
  const restore=async()=>{
    assert.equal(restorationAttempted,false,'QP_ANDROID_PAGE_IDLE_RESTORATION_REPLAY_REFUSED');
    restorationAttempted=true;
    await c.driver.updateSettings({waitForIdleTimeout:500});
    assert.equal((await c.driver.getSettings()).waitForIdleTimeout,500,'QP_ANDROID_PAGE_IDLE_RESTORATION_REQUIRED');
    if(c.queueViewportDiagnostics===true)c.record?.({type:'qp_android_queue_page_idle',state:'restored',waitForIdleTimeout:500});
  };
  try {
    await c.driver.updateSettings({waitForIdleTimeout:0});
    assert.equal((await c.driver.getSettings()).waitForIdleTimeout,0,'QP_ANDROID_PAGE_IDLE_SETTING_REQUIRED');
    if(c.queueViewportDiagnostics===true)c.record?.({type:'qp_android_queue_page_idle',state:'configured',waitForIdleTimeout:0});
    return await operation();
  } catch(error) {original=error;throw error;}
  finally {
    try {await restore();}
    catch(cleanup) {
      c.nativeSettingsCleanupUncertain=true;
      const combined=new AggregateError(original?[original,cleanup]:[cleanup],'QP_ANDROID_PAGE_IDLE_CLEANUP_UNCERTAIN');
      combined.code='QP_ANDROID_QUEUE_SETTINGS_CLEANUP_UNCERTAIN';throw combined;
    }
  }
}

export async function readQPAndroidQueueRows(c, probe = operation => operation()) {
  // UiAutomator2's documented noncompact find response obtains these exact
  // attributes from the same native elements. It avoids three further RPCs per
  // row while retaining every package, visibility, identity and order guard.
  const elements = await probe(() => c.driver.findElements('xpath', "//*[starts-with(@resource-id, 'queue-task-')]"));
  assert.ok(Array.isArray(elements) && elements.length <= 64, 'QP_NATIVE_ROW_BOUND');
  const ids = [], handles = new Set(), key = 'element-6066-11e4-a52e-4f735466cecf';
  const fields = new Set([key, 'ELEMENT', 'displayed', 'attribute/resource-id', 'attribute/package']);
  for (const element of elements) {
    assert.ok(element && typeof element === 'object' && !Array.isArray(element) && Object.keys(element).every(name => fields.has(name)), 'QP_ANDROID_BATCH_ROW_SHAPE_REQUIRED');
    assert.match(element[key] || '', /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/, 'QP_ANDROID_BATCH_NATIVE_HANDLE_REQUIRED');
    assert.ok(!handles.has(element[key]), 'QP_ANDROID_BATCH_DUPLICATE_NATIVE_HANDLE'); handles.add(element[key]);
    if (Object.hasOwn(element, 'ELEMENT')) assert.equal(element.ELEMENT, element[key], 'QP_ANDROID_BATCH_NATIVE_HANDLE_CHANGED');
    const id = element['attribute/resource-id'];
    assert.ok(typeof id === 'string' && id.length <= 160, 'QP_ANDROID_BATCH_ROW_ID_REQUIRED');
    if (!/^queue-task-[a-f0-9-]{36}$/.test(id)) continue;
    assert.equal(element['attribute/package'], c.fixture.appId, 'QP_ANDROID_WRONG_ROW_PACKAGE');
    assert.equal(element.displayed, 'true', 'QP_ANDROID_ROW_NOT_VISIBLE');
    ids.push(id.slice(11));
  }
  assert.deepEqual(ids, [...new Set(ids)], 'QP_DUPLICATE_NATIVE_ROW');
  assert.ok(ids.every(id => c.fixture.qp.dataset.tasks.some(t => t.id === id && t.role !== 'excluded')),
    'QP_UNAUTHORIZED_OR_UNBOUND_NATIVE_ROW');
  return ids;
}

// Android's accessibility tree exposes one viewport. The entire server page
// must be reached through overlapping, ordered viewports, including its footer.
function extendQPAndroidQueueOrder(expected, seen, sample) {
  const first = sample.length ? expected.indexOf(sample[0]) : -1;
  assert.ok(first >= 0 && (seen.end === 0 ? first === 0 : first >= seen.start && first < seen.end),
    'QP_EXACT_NATIVE_PAGE_IDENTITIES');
  assert.deepEqual(sample, expected.slice(first, first + sample.length), 'QP_EXACT_NATIVE_PAGE_IDENTITIES');
  return { start: first, end: Math.max(seen.end, first + sample.length) };
}

export async function androidQueuePage(c, page) {
  // Keep the original independent queue-ready and exact-page deadlines. A
  // page transition can leave the viewport at the old page's footer.
  const scope = await withinAndroidViewport('QP_NATIVE_STATE_REQUIRED', async (probe) => {
    while (!await visible(c.driver, selector('android', 'id', 'matter-task-queue'), probe)) {
      await probe(() => pause(200));
    }
    const view = await androidScrollScope(c, 'work', probe);
    await revealAndroidWorkHeader(c, view, probe);
    return view;
  });
  // The read/scroll walk may avoid implicit idle waits. Restore the normal
  // input barrier before any following radio, pagination or task-detail tap.
  return withQPAndroidQueuePageIdle(c,()=>withinAndroidViewport('QP_EXACT_NATIVE_PAGE_IDENTITIES', async (probe) => {
    const expected = page.items.map(row => row.id);
    const matches = (actual, prefix) => actual.length === prefix.length && actual.every((id, i) => id === prefix[i]);
    const empty = () => visible(c.driver, selector('android', 'text', 'No matching tasks'), probe);
    const footer = id => visible(c.driver, selector('android', 'id', id), probe);
    let previousSample;
    const trace = (sample, stage, step) => {
      if (c.queueViewportDiagnostics !== true) return;
      const sampleSha256 = hash(Buffer.from(JSON.stringify(sample)));
      if (stage === 'prefix' && sampleSha256 === previousSample) return;
      previousSample = sampleSha256;
      c.record({ type: 'qp_android_queue_viewport', stage, step,
        expectedCount: expected.length, expectedPageSha256: hash(Buffer.from(JSON.stringify(expected))),
        sampleSha256, sampleRanks: sample.map(id => expected.indexOf(id)) });
    };
    let sample;
    for (;;) {
      sample = await readQPAndroidQueueRows(c, probe);
      trace(sample, 'prefix', 0);
      if (expected.length ? sample.length && matches(sample, expected.slice(0, sample.length)) : !sample.length && await empty()) break;
      await probe(() => pause(200));
    }
    let seen = { start: 0, end: 0 }, more = true;
    for (let n = 0; n <= ANDROID_SCROLL_LIMIT; n++) {
      if (expected.length) seen = extendQPAndroidQueueOrder(expected, seen, sample);
      else assert.equal(sample.length, 0, 'QP_EXACT_NATIVE_PAGE_IDENTITIES');
      if (!more || n === ANDROID_SCROLL_LIMIT) break;
      more = await androidScroll(c, scope, 'down', probe);
      sample = await readQPAndroidQueueRows(c, probe);
      trace(sample, 'scroll', n + 1);
    }
    assert.equal(more, false, 'QP_ANDROID_QUEUE_FOOTER_NOT_REACHED');
    assert.equal(seen.end, expected.length, 'QP_EXACT_NATIVE_PAGE_IDENTITIES');
    const first = await footer('queue-first');
    assert.ok(first, 'QP_ANDROID_QUEUE_FOOTER_NOT_REACHED');
    assert.equal(await probe(() => first.getAttribute('package')), c.fixture.appId, 'QP_ANDROID_WRONG_FOOTER_PACKAGE');
    const next = await probe(() => c.driver.$$(selector('android', 'id', 'queue-next')));
    assert.equal(next.length, page.next_cursor ? 1 : 0, 'QP_ANDROID_QUEUE_NEXT_MISMATCH');
    if (next.length) {
      assert.equal(await probe(() => next[0].isDisplayed()), true, 'QP_ANDROID_QUEUE_NEXT_NOT_VISIBLE');
      assert.equal(await probe(() => next[0].getAttribute('package')), c.fixture.appId, 'QP_ANDROID_WRONG_FOOTER_PACKAGE');
    }
  }));
}

export async function tapQPQueueTask(c, id) {
  if (c.platform === 'android') {
    await withinAndroidViewport('QP_ANDROID_WORK_HEADER_REQUIRED', async (probe) => {
      const scope = await androidScrollScope(c, 'work', probe);
      await revealAndroidWorkHeader(c, scope, probe);
    });
    consume(c);
    const key='queue-task-'+id,element=await find(c,'id',key,{scroll:true});
    assert.equal(await element.isEnabled(),true);
    assert.equal(await element.getAttribute('resource-id'),key,'QP_ANDROID_EXACT_TASK_ROW_REQUIRED');
    assert.equal(await element.getAttribute('package'),c.fixture.appId,'QP_ANDROID_WRONG_ROW_PACKAGE');
    assert.equal(await element.getAttribute('class'),'android.widget.Button','QP_ANDROID_TASK_BUTTON_REQUIRED');
    assert.equal(await element.getAttribute('clickable'),'true','QP_ANDROID_TASK_BUTTON_REQUIRED');
    const frame=await c.driver.getElementRect(element.elementId),window=await c.driver.getWindowRect();
    assert.ok(containsFrame(window,frame),'QP_ANDROID_TASK_BUTTON_OUTSIDE_WINDOW');
    nativeAction(c,'click','id',key);
    // UiAutomator2 documents this primary gesture for native tap failures.
    // One protocol command only; an unknown acknowledgement is never replayed.
    await c.driver.execute('mobile: clickGesture',{elementId:element.elementId});
    return;
  }
  await tap(c, 'queue-task-' + id);
}

async function rows(c,page){
 if (c.platform === 'android') { consume(c); return androidQueuePage(c, page); }
 await wait(c,'matter-task-queue');consume(c);
 const attribute=c.platform==='ios'?'name':'resource-id';let terminal;
 await c.driver.waitUntil(async()=>{try{
  const elements=await c.driver.$$(`//*[starts-with(@${attribute}, 'queue-task-')]`);assert.ok(elements.length<=64);
  const ids=[];for(const e of elements){const id=await e.getAttribute(attribute);if(/^queue-task-[a-f0-9-]{36}$/.test(id))ids.push(id.slice(11));}
  assert.deepEqual(ids,[...new Set(ids)],'QP_DUPLICATE_NATIVE_ROW');
  assert.ok(ids.every(id=>c.fixture.qp.dataset.tasks.some(t=>t.id===id&&t.role!=='excluded')),'QP_UNAUTHORIZED_OR_UNBOUND_NATIVE_ROW');
  return JSON.stringify(ids)===JSON.stringify(page.items.map(x=>x.id));
 }catch(error){terminal=error;return true;}},{timeout:20000,interval:200,timeoutMsg:'QP_EXACT_NATIVE_PAGE_IDENTITIES'});if(terminal)throw terminal;
 assert.equal((await c.driver.$$(selector(c.platform,'id','queue-next'))).length,page.next_cursor?1:0);
}
async function queue(c,ownership,dates,cursor=null){
 assert.ok(++c.authoritativeReads<=24);const r=await control(c,'readQueue',{ownership,dates,...(cursor?{cursor}:{})});assert.equal(r.status,200);
 return decodeQueuePage(r.value,{ownership,dates},c.fixture.membershipId);
}
async function taskFacts(c,item){
 const values={'queue-task-title':item.title,'queue-task-id':item.id,'queue-task-matter':`${item.matter.matter_code} · ${item.matter.title}`,
 'queue-task-status':item.status.replaceAll('_',' '),'queue-task-priority':item.priority,'queue-task-due':item.due_on?displayDay(item.due_on):'No due date recorded','queue-task-assignment':'Assigned to you',
 'queue-task-created':item.created_at,'queue-task-updated':item.updated_at,'queue-task-lifecycle':String(item.matter.lifecycle_version)};
 for(const[id,value]of Object.entries(values))assert.equal(await fact(c,id),value,'QP_EXACT_TASK_FACT');
}
async function selectQueue(c,ownership,dates){
 if(c.selected.ownership!==ownership){await selectQueueSegment(c,'Task ownership',{mine:'Mine',team:'Team',unassigned:'Unassigned'}[ownership]);c.selected.ownership=ownership;}
 if(c.selected.dates!==dates){await selectQueueSegment(c,'Task dates',{all:'All dates',dated:'Dated',undated:'Undated'}[dates]);c.selected.dates=dates;}
 const page=await queue(c,ownership,dates);await rows(c,page);return page;
}
async function ownPrivacy(c,actor='member'){assert.ok(++c.authoritativeReads<=24);const r=await control(c,'readOwnPrivacy',{actor});assert.equal(r.status,200);return r.value.request===null?null:decodeAccountDeletionReceipt(r.value.request);}
async function completedNativeRead(c,afterSequence){
 const deadline=Date.now()+20000;for(let attempt=0;attempt<4;attempt++){
  assert.ok(Date.now()<deadline);assert.ok(++c.controlCalls<=24);const result=await c.controls.readNativeRequest({caseId:c.caseId,method:'GET',route:'/api/account/deletion-requests',afterSequence},{deadline});
  assert.ok(result.requests.length<=1,'QP_RELOAD_REPLAY');if(result.requests.length){assert.equal(result.requests[0].status,200);return result.requests[0];}
  if(attempt<3)await new Promise(r=>setTimeout(r,Math.min(200,Math.max(0,deadline-Date.now()))));
 }throw Error('QP_EXPLICIT_NATIVE_RELOAD_NOT_COMPLETED');
}
async function receiptFacts(c,r){for(const[id,value]of Object.entries({'privacy-request-id':r.id,'privacy-request-operation':r.operation_id,
 'privacy-request-requested-at':r.requested_at,'privacy-request-status':'Received','privacy-request-not-completed':'Not completed'}))assert.equal(await fact(c,id),value);}
export const queuePrivacyScenarios=Object.freeze([
 {id:'QUEUE-01',run:async c=>{
  const before=await traffic(c);await home(c,'work');await wait(c,'matter-task-queue');c.selected={ownership:'mine',dates:'all'};
  const page=await queue(c,'mine','all');assert.equal(page.items.length,25);assert.ok(page.next_cursor);await rows(c,page);
  await tap(c,'queue-next');const second=await queue(c,'mine','all',page.next_cursor);assert.equal(second.items.length,2);assert.equal(second.next_cursor,null);await rows(c,second);
  await tapQPQueueTask(c,second.items[1].id);await wait(c,'queue-task-detail');await taskFacts(c,second.items[1]);await tap(c,'queue-back');await rows(c,second);
  await tap(c,'queue-first');await rows(c,page);
  for(const ownership of['mine','team','unassigned'])for(const dates of['all','dated','undated']){
   if(ownership==='mine'&&dates==='all')continue;const actual=await selectQueue(c,ownership,dates);
   assert.deepEqual(actual.items.map(x=>x.id),expectedQueue(c.fixture.qp.dataset.tasks,ownership,dates,c.fixture.membershipId,c.fixture.qp.dataset.teamPeerId).slice(0,25).map(x=>x.id));
   if(ownership==='team')assert.match(await fact(c,'queue-ownership-meaning'),/Your own and unassigned tasks are excluded/);
  }
  const selectionBefore=await traffic(c);
  const current=await selectQueue(c,'mine','all');assert.equal(current.items.at(-1).id,c.fixture.qp.dataset.anchor.id);
  const changed=await withQPAnchorRestoration(c,async({changed,restore})=>{
   const staleBefore=await traffic(c);await tap(c,'queue-next');await wait(c,'queue-stale');await absent(c,'queue-next');await absent(c,'queue-task-detail');
   const requests=(await control(c,'readNativeRequest',{method:'GET',route:'/api/matter-work-queue',afterSequence:selectionBefore.lastSequence})).requests;
   const proof=assertObservedStaleQueueCursor(requests,{afterSequence:selectionBefore.lastSequence,
    staleAfterSequence:staleBefore.lastSequence,anchorId:current.items.at(-1).id});
   event(c,'delivered-native-cursor-rejected',proof);
   await tap(c,'queue-first');const fresh=await queue(c,'mine','all');await rows(c,fresh);assert.notEqual(fresh.items.at(-1).id,current.items.at(-1).id);
   const restored=await restore();
   await tap(c,'queue-first');const reloaded=await queue(c,'mine','all');await rows(c,reloaded);assert.deepEqual(reloaded.items.map(x=>x.id),page.items.map(x=>x.id));
   assert.equal(reloaded.items.at(-1).due_on,page.items.at(-1).due_on);assert.equal(reloaded.items.at(-1).updated_at,restored.updatedAt);assert.notEqual(restored.updatedAt,page.items.at(-1).updated_at);
   return changed;
  });
  await tapQPQueueTask(c,page.items[0].id);await wait(c,'queue-task-detail');await tap(c,'queue-open-matter');await wait(c,'matter-detail');assert.equal(await fact(c,'matter-code'),page.items[0].matter.matter_code);
  await home(c,'work');await wait(c,'matter-task-queue');await absent(c,'queue-task-detail');
  const native=await control(c,'readNativeRequest',{method:'POST',route:'/api/account/deletion-requests',afterSequence:before.lastSequence});assert.equal(native.requests.length,0);
  readOnlyTraffic(delta(before,await traffic(c)));event(c,'queue-complete',{firstPageIds:page.items.map(x=>x.id),secondPageIds:second.items.map(x=>x.id),anchor:changed.id,restored:true,staleRejected:true,nativeBusinessWrites:0});
 }},
 {id:'PRIVACY-01',run:async c=>{
  const before=await traffic(c);await tap(c,'account-open');await waitForQPPrivacyControl(c,'privacy-request-state','No received request is recorded');assert.equal(await ownPrivacy(c),null);
  await tap(c,'privacy-request-start');await waitForQPPrivacyControl(c,'privacy-request-confirmation');await tap(c,'privacy-request-cancel');await waitForQPPrivacyControl(c,'privacy-request-state','No received request is recorded');
  const noPost=await control(c,'readNativeRequest',{method:'POST',route:'/api/account/deletion-requests',afterSequence:before.lastSequence});assert.equal(noPost.requests.length,0);
  const arm=await control(c,'armPrivacyAckLoss');await tap(c,'privacy-request-start');await tap(c,'privacy-request-confirm');
  await waitForQPPrivacyControl(c,'privacy-request-state','Acknowledgement unconfirmed');await assertQPPrivacyControlsAbsent(c,['privacy-request-start','privacy-request-confirm']);
  // UI Unknown follows the gateway's completed successful-upstream record, so
  // this is one explicit read, never a hidden20-iteration receipt poll.
  const ack=await control(c,'readControlReceipt',{id:arm.id});assert.equal(ack.requestsForwarded,1);assert.equal(ack.upstreamAcknowledged,true);assert.equal(ack.upstreamStatus,202);
  const receipt=decodeAccountDeletionReceipt(ack.responseObservation);assert.deepEqual(await ownPrivacy(c),receipt);
  const reloadBefore=await traffic(c);await tap(c,'privacy-request-reload');await completedNativeRead(c,reloadBefore.lastSequence);await waitForQPPrivacyControl(c,'privacy-request-state','Request received');await receiptFacts(c,receipt);assert.deepEqual(await ownPrivacy(c),receipt);
  await tap(c,'back');const revisitBefore=await traffic(c);await tap(c,'account-open');await completedNativeRead(c,revisitBefore.lastSequence);await waitForQPPrivacyControl(c,'privacy-request-state','Request received');await receiptFacts(c,receipt);await assertQPPrivacyControlsAbsent(c,['privacy-request-start']);
  const posts=(await control(c,'readNativeRequest',{method:'POST',route:'/api/account/deletion-requests',afterSequence:before.lastSequence})).requests;
  assert.equal(posts.length,1);assert.equal(posts[0].status,202);assert.deepEqual(posts[0].bodyObservation.keys,['confirmation','operation_id']);assert.deepEqual(posts[0].responseObservation,receipt);
  await c.switchActor('second-company');await tap(c,'account-open');await waitForQPPrivacyControl(c,'privacy-request-state','No received request is recorded');await assertQPPrivacyControlsAbsent(c,['privacy-request-receipt']);assert.equal(await ownPrivacy(c,'second-company'),null);
  event(c,'privacy-complete',{receipt,onePost:true,unknownAcknowledgementReconciledByGet:true,otherUserReceiptAbsent:true,deletionCompleted:false});
 }},
]);
export const collectQueuePrivacy=platform=>collectQP(platform,queuePrivacyScenarios);
