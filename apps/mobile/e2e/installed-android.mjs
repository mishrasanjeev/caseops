import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { admitApplication } from './fixture-contract.mjs';

// noReset preserves the session data but also bypasses UiAutomator2's install
// path. Install once explicitly, then verify the device bytes on every boundary.
export function attestAndroidBinary(fixture, expectedHash, { install = false, command = execFileSync } = {}) {
  admitApplication(fixture, 'android');
  assert.match(fixture.udid || '', /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$/, 'EXACT_ANDROID_DEVICE_REQUIRED');
  assert.ok(path.isAbsolute(fixture.appPath || '') && fixture.appPath.endsWith('.apk'), 'ABSOLUTE_ANDROID_APK_REQUIRED');
  assert.match(expectedHash || '', /^[a-f0-9]{64}$/, 'EXPECTED_INSTALLED_APK_HASH_REQUIRED');
  const run = (args, timeout = 20000) => command('adb', ['-s', fixture.udid, ...args], {
    shell: false, windowsHide: true, encoding: 'utf8', timeout, maxBuffer: 65536,
  }).trim();
  if (install) {
    const result = run(['install', '-r', fixture.appPath], 120000);
    assert.match(result, /(?:^|\r?\n)Success$/, 'EXACT_ANDROID_APK_INSTALL_FAILED');
  }
  const paths = run(['shell', 'pm', 'path', fixture.appId]).split(/\r?\n/);
  assert.equal(paths.length, 1, 'SINGLE_INSTALLED_BASE_APK_REQUIRED');
  const match = /^package:(\/data\/app\/[A-Za-z0-9_~+=./-]+\/base\.apk)$/.exec(paths[0]);
  assert.ok(match && !match[1].split('/').includes('..'), 'EXACT_INSTALLED_APK_PATH_REQUIRED');
  const digest = run(['shell', 'sha256sum', match[1]]);
  assert.equal(digest, `${expectedHash}  ${match[1]}`, 'INSTALLED_ANDROID_APK_HASH_MISMATCH');
  return { type: 'installed_android_binary', appId: fixture.appId, udid: fixture.udid,
    installedApkSha256: expectedHash, explicitReplaceInstall: install, appDataCleared: false };
}
