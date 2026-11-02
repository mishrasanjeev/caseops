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

// USB mode selects one reviewed transport tuple. Runtime USB, APK, backend,
// reverse-port and Appium evidence are still required independently.
export function androidLocalProfile(udid, code = 'REVIEWED_ANDROID_LOCAL_PROFILE_REQUIRED', mode) {
  assert.ok(mode === undefined || mode === 'emulator' || mode === 'usb-reverse', code);
  if (mode === 'usb-reverse') {
    assert.ok(typeof udid === 'string' && /^[A-Za-z0-9][A-Za-z0-9_-]{3,63}$/.test(udid)
      && !/^emulator-/i.test(udid) && !/^(unknown|offline|unauthorized|constructor)$/i.test(udid), code);
    return Object.freeze({ udid, adbPort: 5042, appiumUrl: 'http://127.0.0.1:4729', systemPort: 8206,
      transportMode: 'usb-reverse', deviceKind: 'physical', requiresAvdName: false });
  }
  assert.ok(typeof udid === 'string' && Object.hasOwn(profiles, udid), code);
  return profiles[udid];
}

export function validateUsbReverseOrigins(apiOrigin, webOrigin) {
  for (const value of [apiOrigin, webOrigin]) {
    assert.ok(typeof value === 'string' && value.length <= 512, 'ANDROID_TRANSPORT_USB_ORIGIN_REQUIRED');
    let uri;
    try { uri = new URL(value); } catch { assert.fail('ANDROID_TRANSPORT_USB_ORIGIN_REQUIRED'); }
    assert.ok(uri.protocol === 'https:' && uri.hostname === '127.0.0.1' && uri.origin === value
      && !uri.username && !uri.password && !uri.search && !uri.hash && uri.pathname === '/'
      && /^[0-9]{4,5}$/.test(uri.port) && Number(uri.port) >= 1024 && Number(uri.port) <= 65535,
    'ANDROID_TRANSPORT_USB_ORIGIN_REQUIRED');
  }
  assert.notEqual(apiOrigin, webOrigin, 'ANDROID_TRANSPORT_DISTINCT_USB_ORIGINS_REQUIRED');
}
