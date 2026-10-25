import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { admitApplication } from './fixture-contract.mjs';

// noReset preserves the session data but also bypasses UiAutomator2's install
// path. Replace missing/stale bytes explicitly; an already identical APK needs
// no reinstall. Every boundary still verifies actual device bytes.
export function attestAndroidBinary(fixture, expectedHash, { install = false, command = execFileSync } = {}) {
  admitApplication(fixture, 'android');
  assert.match(fixture.udid || '', /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$/, 'EXACT_ANDROID_DEVICE_REQUIRED');
  assert.ok(path.isAbsolute(fixture.appPath || '') && fixture.appPath.endsWith('.apk'), 'ABSOLUTE_ANDROID_APK_REQUIRED');
  assert.match(expectedHash || '', /^[a-f0-9]{64}$/, 'EXPECTED_INSTALLED_APK_HASH_REQUIRED');
  const run = (args, timeout = 20000) => command('adb', ['-s', fixture.udid, ...args], {
    shell: false, windowsHide: true, encoding: 'utf8', timeout, maxBuffer: 65536,
  }).trim();
  const readInstalled = () => {
    const packageOutput = run(['shell', 'pm', 'list', 'packages', fixture.appId]);
    const packages = packageOutput ? packageOutput.split(/\r?\n/) : [];
    assert.ok(packages.length <= 8 && packages.every(value => /^package:[A-Za-z0-9_.]+$/.test(value)),
      'BOUNDED_INSTALLED_PACKAGE_RESPONSE_REQUIRED');
    if (!packages.includes(`package:${fixture.appId}`)) return null;
    const output = run(['shell', 'pm', 'path', fixture.appId]);
    assert.ok(output, 'PRESENT_INSTALLED_PACKAGE_PATH_REQUIRED');
    const paths = output.split(/\r?\n/);
    assert.equal(paths.length, 1, 'SINGLE_INSTALLED_BASE_APK_REQUIRED');
    const match = /^package:(\/data\/app\/[A-Za-z0-9_~+=./-]+\/base\.apk)$/.exec(paths[0]);
    assert.ok(match && !match[1].split('/').includes('..'), 'EXACT_INSTALLED_APK_PATH_REQUIRED');
    const digest = run(['shell', 'sha256sum', match[1]]);
    assert.ok(/^[a-f0-9]{64}$/.test(digest.slice(0, 64)) && digest.slice(64) === `  ${match[1]}`,
      'EXACT_INSTALLED_APK_DIGEST_REQUIRED');
    return digest.slice(0, 64);
  };
  let observed = readInstalled(), replaced = false;
  if (install && observed !== expectedHash) {
    const result = run(['install', '-r', fixture.appPath], 120000);
    assert.match(result, /(?:^|\r?\n)Success$/, 'EXACT_ANDROID_APK_INSTALL_FAILED');
    replaced = true;
    observed = readInstalled();
  }
  assert.equal(observed, expectedHash, 'INSTALLED_ANDROID_APK_HASH_MISMATCH');
  return { type: 'installed_android_binary', appId: fixture.appId, udid: fixture.udid,
    installedApkSha256: observed, explicitReplaceInstall: replaced, appDataCleared: false };
}
