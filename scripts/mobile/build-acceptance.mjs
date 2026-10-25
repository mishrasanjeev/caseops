import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { sourceSnapshot } from './source-snapshot.mjs';
import { binaryHash } from '../../apps/mobile/e2e/support.mjs';

const appRoot = fileURLToPath(new URL('../../apps/mobile/', import.meta.url));
const require = createRequire(path.join(appRoot, 'package.json'));
const { getConfig } = require('@expo/config');
const { acceptanceSettings } = require(path.join(appRoot, 'plugins/with-local-acceptance.cjs'));

export function checkBuildConfig(platform) {
  const settings = acceptanceSettings(process.env);
  assert.equal(settings?.platform, platform, 'MATCHED_ACCEPTANCE_PROFILE_REQUIRED');
  const { exp } = getConfig(appRoot, { isPublicConfig: true });
  assert.equal(exp.extra.automatedTest, true, 'AUTOMATED_MARKER_REQUIRED');
  assert.equal(exp.extra.apiOrigin, settings.apiOrigin, 'API_ORIGIN_MISMATCH');
  assert.equal(exp.extra.webOrigin, settings.webOrigin, 'WEB_ORIGIN_MISMATCH');
  assert.equal(exp.updates.enabled, false, 'LOCAL_BUNDLE_ONLY_REQUIRED');
  if (platform === 'ios') assert.equal(exp.ios.bundleIdentifier, settings.iosBundleIdentifier, 'QA_BUNDLE_ID_REQUIRED');
  const source = sourceSnapshot();
  assert.equal(settings.releaseSha, source.sourceSha, 'CURRENT_SOURCE_SHA_REQUIRED');
  assert.equal(exp.extra.releaseSha, source.sourceSha, 'CURRENT_SOURCE_SHA_REQUIRED');
  return { ...source, profile: settings.profile, platform,
    appId: platform === 'android' ? settings.androidAppId : settings.iosBundleIdentifier,
    apiOrigin: settings.apiOrigin, webOrigin: settings.webOrigin, automatedTest: true,
    publicCaSha256: settings.ca?.sha256 ?? null, devEnabled: false,
    nativeExecution: 'not-run-by-build-wrapper' };
}

export function finishBuild(platform, before, artifact, embeddedConfig) {
  const after = checkBuildConfig(platform);
  assert.deepEqual(after, before, 'SOURCE_OR_CONFIGURATION_CHANGED_DURING_BUILD');
  assert.ok(path.isAbsolute(artifact), 'ABSOLUTE_ARTIFACT_REQUIRED');
  assert.equal(embeddedConfig.extra.automatedTest, true, 'EMBEDDED_MARKER_REQUIRED');
  assert.equal(embeddedConfig.extra.apiOrigin, after.apiOrigin, 'EMBEDDED_API_ORIGIN_MISMATCH');
  assert.equal(embeddedConfig.extra.webOrigin, after.webOrigin, 'EMBEDDED_WEB_ORIGIN_MISMATCH');
  assert.equal(embeddedConfig.extra.releaseSha, after.sourceSha, 'EMBEDDED_SOURCE_MISMATCH');
  if (platform === 'ios') assert.equal(embeddedConfig.ios.bundleIdentifier, after.appId, 'EMBEDDED_QA_BUNDLE_ID_REQUIRED');
  return { ...after, artifact, binaryHash: binaryHash(artifact),
    binaryHashKind: 'sha256-file-or-canonical-bundle-tree' };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [command, platform, beforeFile, artifact, configFile, outputFile] = process.argv.slice(2);
  assert.ok(['android', 'ios'].includes(platform), 'PLATFORM_REQUIRED');
  let result;
  if (command === 'check') result = checkBuildConfig(platform);
  else {
    assert.equal(command, 'finish', 'UNKNOWN_BUILD_COMMAND');
    result = finishBuild(platform, JSON.parse(readFileSync(beforeFile, 'utf8')),
      artifact, JSON.parse(readFileSync(configFile, 'utf8')));
  }
  const json = `${JSON.stringify(result, null, 2)}\n`;
  const destination = command === 'check' ? beforeFile : outputFile;
  if (destination) writeFileSync(destination, json, { flag: 'wx' });
  process.stdout.write(json);
}
