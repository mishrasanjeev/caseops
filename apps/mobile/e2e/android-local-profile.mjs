import assert from 'node:assert/strict';

// These are complete reviewed profiles, not interchangeable port defaults.
// The second profile's Appium/system ports are selected policy values; actual
// listener, emulator, installed app and session evidence is still required.
const profiles = Object.freeze({
  'emulator-5584': Object.freeze({ udid: 'emulator-5584', adbPort: 5038,
    appiumUrl: 'http://127.0.0.1:4725', systemPort: 8202,
    avdName: 'CaseOps_Pixel9_API36_arm64', requiresAvdName: false }),
  'emulator-5580': Object.freeze({ udid: 'emulator-5580', adbPort: 5040,
    appiumUrl: 'http://127.0.0.1:4727', systemPort: 8204,
    avdName: 'CaseOps_PR558_16K_20261028_03', requiresAvdName: true }),
});

export function androidLocalProfile(udid, code = 'REVIEWED_ANDROID_LOCAL_PROFILE_REQUIRED') {
  assert.ok(typeof udid === 'string' && Object.hasOwn(profiles, udid), code);
  return profiles[udid];
}
