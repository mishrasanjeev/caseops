import assert from 'node:assert/strict';
import {find, dispatchNativeClick} from '../../apps/mobile/e2e/native-ui.mjs';

// Setup for a fresh synthetic actor, before freezing Core/Files traffic. This
// uses the real native control and authenticated API; browser credentials do
// not authorize the native-only policy endpoint.
export async function acceptNativeWorkspaceRules(context) {
  assert.equal(context.fixture.environment, 'docker-integration');
  assert.equal(context.fixture.syntheticDataOnly, true);
  const button = await find(context, 'id', 'workspace-use-accept');
  const frame = await context.driver.getElementRect(button.elementId);
  const viewport = await context.driver.getWindowRect();
  assert.ok([frame.x, frame.y, frame.width, frame.height, viewport.x, viewport.y,
    viewport.width, viewport.height].every(Number.isFinite), 'CONDUCT_CONTROL_GEOMETRY_REQUIRED');
  assert.ok(frame.width >= 44 && frame.height >= 44 && frame.x >= viewport.x && frame.y >= viewport.y
    && frame.x + frame.width <= viewport.x + viewport.width
    && frame.y + frame.height <= viewport.y + viewport.height, 'CONDUCT_CONTROL_OUTSIDE_VIEWPORT');
  if (context.platform === 'ios') {
    const hittable = await button.getAttribute('hittable');
    assert.ok(hittable === true || hittable === 'true', 'CONDUCT_CONTROL_NOT_HITTABLE');
  }
  // The single protocol command must never be replayed after a lost or stale
  // acknowledgement. A failed postcondition is incomplete setup, not a retry.
  await dispatchNativeClick(context, button, 'id', 'workspace-use-accept');
  await find(context, 'id', 'note-input');
  context.record?.({type: 'workspace_conduct_setup', nativeControlActivated: true,
    noteEditorObserved: true, fullCaseCredit: 0, automaticRetry: false});
  return {nativeControlActivated: true, noteEditorObserved: true, frame,
    fullCaseCredit: 0, automaticRetry: false};
}
