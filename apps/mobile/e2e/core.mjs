import assert from 'node:assert/strict';
import { byTestId, localJson } from './support.mjs';

async function click(context, id) { await (await byTestId(context.driver, context.platform, id)).click(); }
async function text(context, id) { return (await byTestId(context.driver, context.platform, id)).getText(); }

export async function authenticate(context) {
  const { fixture } = context;
  const loggedIn = await context.driver.$(context.platform === 'android' ? 'id=account-open' : '~account-open');
  if (!await loggedIn.isDisplayed()) {
    await click(context, 'sign-in');
    // The real system-browser handoff must complete. No native password or token shortcut.
    await loggedIn.waitForDisplayed({ timeout: 60000 });
  }
  await click(context, 'account-open');
  assert.equal(await text(context, fixture.ids.principal), fixture.principalLabel, 'WRONG_PRINCIPAL');
  assert.equal(await text(context, fixture.ids.workspace), fixture.workspaceLabel, 'WRONG_WORKSPACE');
  await click(context, fixture.ids.accountClose);
}

async function openMatter(context) {
  await click(context, 'tab-matters');
  for (let backCount = 0; ; backCount++) {
    const search = await context.driver.$(context.platform === 'android' ? 'id=matter-search' : '~matter-search');
    if (await search.isDisplayed()) break;
    assert.ok(backCount < 4, 'MATTER_SEARCH_UNREACHABLE');
    const back = await context.driver.$(context.platform === 'android' ? 'id=back' : '~back');
    assert.ok(await back.isDisplayed(), 'MATTER_SEARCH_BACK_UNAVAILABLE');
    await back.click();
  }
  await (await byTestId(context.driver, context.platform, 'matter-search')).setValue(context.fixture.matter.search);
  await click(context, context.fixture.ids.searchSubmit);
  await click(context, `matter-row-${context.fixture.matter.id}`);
  assert.equal(await text(context, context.fixture.ids.matterIdentity), context.fixture.matter.identityLabel, 'WRONG_MATTER');
}

export const scenarios = [
  { id: 'CORE-01', run: async (context) => { await authenticate(context); } },
  { id: 'CORE-02', run: async (context) => {
    for (const destination of ['today', 'matters', 'calendar', 'work']) {
      await click(context, `tab-${destination}`);
      await byTestId(context.driver, context.platform, context.fixture.ids.screens[destination]);
    }
  } },
  { id: 'CORE-03', run: openMatter },
  { id: 'CORE-04', run: async (context) => {
    const before = await localJson(`${context.fixture.gatewayUrl}/__caseops_e2e/status`);
    await openMatter(context);
    if (context.fixture.ids.noteOpen) await click(context, context.fixture.ids.noteOpen);
    await (await byTestId(context.driver, context.platform, 'note-input')).setValue(context.noteText);
    await click(context, 'note-save');
    await byTestId(context.driver, context.platform, context.fixture.ids.noteAcknowledgement);
    await click(context, context.fixture.ids.noteReturn);
    assert.equal(await text(context, context.fixture.ids.savedNote), context.noteText, 'NOTE_ACK_MISSING');
    await context.driver.terminateApp(context.fixture.appId);
    await context.driver.activateApp(context.fixture.appId);
    await authenticate(context);
    await openMatter(context);
    if (context.fixture.ids.activityOpen) await click(context, context.fixture.ids.activityOpen);
    assert.equal(await text(context, context.fixture.ids.savedNote), context.noteText, 'NOTE_RELOAD_MISMATCH');
    const after = await localJson(`${context.fixture.gatewayUrl}/__caseops_e2e/status`);
    const requests = after.requests.filter((request) => request.sequence > before.lastSequence);
    assert.equal(requests.filter((request) => request.method === 'POST' && request.route === context.fixture.noteRoute).length, 1, 'NOTE_NOT_SUBMITTED_EXACTLY_ONCE');
    assert.ok(requests.some((request) => request.method === 'GET' && request.route === context.fixture.matterReloadRoute), 'AUTHORITATIVE_REREAD_MISSING');
  } },
  { id: 'CORE-06', run: async (context) => {
    const status = await localJson(`${context.fixture.gatewayUrl}/__caseops_e2e/status`);
    assert.ok(status.accepted > 0 && status.requests.some((request) => request.route !== '/api/build'), 'NO_NATIVE_REQUESTS_OBSERVED');
    assert.equal(status.markerRejected, 0, 'NATIVE_MARKER_MISSING');
    assert.equal(status.routeRejected, 0, 'UNADMITTED_NATIVE_ROUTE');
    assert.equal(status.overflow, false, 'GATEWAY_EVIDENCE_OVERFLOW');
  } },
  { id: 'CORE-05', run: async (context) => {
    await openMatter(context);
    await click(context, 'account-open');
    await click(context, 'sign-out');
    await byTestId(context.driver, context.platform, context.fixture.ids.signedOut);
    const row = await context.driver.$(context.platform === 'android' ? `id=matter-row-${context.fixture.matter.id}` : `~matter-row-${context.fixture.matter.id}`);
    assert.equal(await row.isDisplayed(), false, 'PRIVATE_SURFACE_AFTER_LOGOUT');
    await context.driver.terminateApp(context.fixture.appId);
    await context.driver.activateApp(context.fixture.appId);
    await byTestId(context.driver, context.platform, context.fixture.ids.signedOut);
  } },
];
