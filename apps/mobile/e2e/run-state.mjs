import assert from 'node:assert/strict';
import { FixtureUnavailable } from './fixture-contract.mjs';

export function authenticationGate(record) {
  let failed = false;
  return {
    assertSetup() {
      if (failed) throw new FixtureUnavailable('INITIAL_BROWSER_AUTHENTICATION_FAILED');
    },
    failInitial(scenario, phase) {
      assert.ok(['setup', 'call'].includes(phase), 'AUTH_FAILURE_PHASE_REQUIRED');
      if (scenario.id !== 'NATIVE-01' || failed) return;
      failed = true;
      record({ type: 'auth_prerequisite_failed', scenario: 'NATIVE-01', phase, reason: 'INITIAL_BROWSER_AUTHENTICATION_FAILED' });
    },
  };
}

export function appiumSessionEvent(sessionId, state) {
  assert.match(sessionId || '', /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i, 'APPIUM_SESSION_UUID_REQUIRED');
  assert.ok(['created', 'deleted', 'cleanup-failed'].includes(state), 'APPIUM_SESSION_STATE_REQUIRED');
  return { type: 'appium_session', sessionId, state };
}

export async function configureNativeDriver(driver, platform, record) {
  assert.ok(['android', 'ios'].includes(platform), 'NATIVE_PLATFORM_REQUIRED');
  if (platform === 'ios') return;
  await driver.updateSettings({ disableIdLocatorAutocompletion: true });
  const settings = await driver.getSettings();
  const value = settings?.disableIdLocatorAutocompletion;
  record({ type: 'native_driver_settings', disableIdLocatorAutocompletion: typeof value === 'boolean' ? value : null });
  assert.equal(value, true, 'EXACT_ANDROID_RESOURCE_ID_SETTING_REQUIRED');
}
