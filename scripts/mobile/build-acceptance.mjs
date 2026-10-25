import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { readFileSync, statSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { sourceSnapshot } from './source-snapshot.mjs';
import { binaryHash } from '../../apps/mobile/e2e/support.mjs';

const appRoot = fileURLToPath(new URL('../../apps/mobile/', import.meta.url));
const require = createRequire(path.join(appRoot, 'package.json'));
const { getConfig } = require('@expo/config');
const { acceptanceSettings } = require(path.join(appRoot, 'plugins/with-local-acceptance.cjs'));

function boundedLines(value, limit) {
  assert.ok(typeof value === 'string' && Buffer.byteLength(value) <= limit && !value.includes('\0'), 'SDK_DUMP_SIZE_BOUND');
  const lines = value.split(/\r?\n/);
  assert.ok(lines.length <= 200000 && lines.every((line) => line.length <= 8192), 'SDK_DUMP_LINE_BOUND');
  return lines;
}

function safeZipPath(value, resource = false) {
  assert.ok(typeof value === 'string' && value.length > 0 && value.length <= 1024
    && !/[\\:%\x00-\x1f\x7f]/.test(value) && !value.startsWith('/'), 'UNSAFE_ZIP_PATH');
  const components = value.replace(/\/$/, '').split('/');
  assert.ok(components.every((part) => part && part !== '.' && part !== '..'), 'UNSAFE_ZIP_PATH');
  if (resource) assert.ok(value.length <= 256 && /^res\/[A-Za-z0-9_./-]+$/.test(value)
    && !value.endsWith('/'), 'UNSAFE_RESOURCE_ZIP_PATH');
  return value;
}

export function resolveAndroidAcceptanceResources(dump) {
  const wanted = new Map([['raw/caseops_local_acceptance_ca', 'ca'], ['xml/caseops_local_acceptance_network', 'network']]);
  const found = { ca: [], network: [] };
  const ids = new Map();
  let current;
  for (const line of boundedLines(dump, 16 * 1024 * 1024)) {
    const header = /^( *)resource (0x[0-9a-fA-F]{8}) (\S+)(.*)$/.exec(line);
    if (line.trimStart().startsWith('resource ')) assert.ok(header, 'SDK_RESOURCE_HEADER_INVALID');
    if (header) {
      const id = header[2].toLowerCase();
      ids.set(id, (ids.get(id) || 0) + 1);
      const key = wanted.get(header[3]);
      current = key ? { id, lines: [], indent: header[1].length } : null;
      if (key) {
        assert.equal(header[4], '', 'AMBIGUOUS_RESOURCE_HEADER');
        found[key].push(current);
      }
    } else if (current && line.trim()) {
      if (line.search(/\S/) <= current.indent) current = null;
      else current.lines.push(line.trim());
    }
  }
  const result = {};
  for (const key of ['ca', 'network']) {
    assert.equal(found[key].length, 1, 'MISSING_OR_DUPLICATE_ACCEPTANCE_RESOURCE');
    const item = found[key][0];
    assert.equal(ids.get(item.id), 1, 'DUPLICATE_ACCEPTANCE_RESOURCE_ID');
    assert.equal(item.lines.length, 1, 'RESOURCE_CONFIGURATION_MUST_BE_UNIQUE_DEFAULT');
    const file = /^\(\) \(file\) (\S+)(?: type=(XML))?$/.exec(item.lines[0]);
    assert.ok(file && (key !== 'network' || file[2] === 'XML'), 'RESOURCE_FILE_MAPPING_REQUIRED');
    result[key] = { id: item.id, path: safeZipPath(file[1], true) };
  }
  assert.notEqual(result.ca.path, result.network.path, 'RESOURCE_FILES_MUST_BE_DISTINCT');
  return result;
}

// AAPT's indented XML dump is a tree, not a collection of matching substrings.
function sdkXmlTree(dump) {
  const roots = [], stack = [];
  let count = 0;
  for (const line of boundedLines(dump, 4 * 1024 * 1024)) {
    if (!line.trim() || /^ *N: [\w-]+=\S+ \(line=\d+\)$/.test(line)) continue;
    const element = /^( *)E: ([\w.:-]+) \(line=\d+\)$/.exec(line);
    const attribute = /^( *)A: ([^\s(=]+)(?:\((0x[0-9a-fA-F]{8})\))?=(.+)$/.exec(line);
    const text = /^( *)T: '([^'\\]*)'$/.exec(line);
    const row = element || attribute || text;
    assert.ok(row, 'UNRECOGNIZED_SDK_XML_ROW');
    const indent = row[1].length;
    while (stack.length && stack.at(-1).indent >= indent) stack.pop();
    if (element) {
      assert.ok(++count <= 20000 && stack.length < 64, 'SDK_XML_TREE_BOUND');
      const node = { name: element[2], indent, attrs: new Map(), children: [], texts: [] };
      (stack.length ? stack.at(-1).children : roots).push(node);
      stack.push(node);
    } else {
      assert.ok(stack.length, 'SDK_XML_ROW_WITHOUT_ELEMENT');
      const owner = stack.at(-1);
      if (attribute) {
        assert.ok(!owner.attrs.has(attribute[2]), 'DUPLICATE_SDK_XML_ATTRIBUTE');
        owner.attrs.set(attribute[2], { id: attribute[3]?.toLowerCase(), raw: attribute[4] });
      } else owner.texts.push(text[2]);
    }
  }
  assert.equal(roots.length, 1, 'ONE_COMPILED_XML_ROOT_REQUIRED');
  return roots[0];
}

function sdkValue(attribute) {
  assert.ok(attribute, 'REQUIRED_COMPILED_ATTRIBUTE_MISSING');
  if (/^@0x[0-9a-fA-F]{8}$/.test(attribute.raw)) return attribute.raw.toLowerCase();
  if (['true', 'false'].includes(attribute.raw)) return attribute.raw === 'true';
  const quoted = /^("(?:[^"\\]|\\.)*")(?: \(Raw: ("(?:[^"\\]|\\.)*")\))?$/.exec(attribute.raw);
  assert.ok(quoted, 'COMPILED_ATTRIBUTE_VALUE_INVALID');
  const value = JSON.parse(quoted[1]);
  if (quoted[2]) assert.equal(JSON.parse(quoted[2]), value, 'COMPILED_RAW_VALUE_MISMATCH');
  return value;
}

function shape(node, attrs, children) {
  assert.deepEqual([...node.attrs.keys()].sort(), [...attrs].sort(), 'UNEXPECTED_COMPILED_ATTRIBUTES');
  assert.equal(node.texts.length, 0, 'UNEXPECTED_COMPILED_TEXT');
  assert.ok([...node.attrs.values()].every((attr) => !attr.id), 'UNEXPECTED_NETWORK_ATTRIBUTE_RESOURCE_ID');
  assert.ok(node.children.every((item) => children.includes(item.name)), 'UNEXPECTED_COMPILED_ELEMENT');
}

export function verifyAndroidCompiledSecurity(resources, manifestDump, networkDump, hosts) {
  assert.ok(hosts.length > 0 && hosts.length <= 2 && new Set(hosts).size === hosts.length
    && hosts.every((host) => ['10.0.2.2', 'localhost', '127.0.0.1'].includes(host)), 'EXACT_LOCAL_HOSTS_REQUIRED');
  const manifest = sdkXmlTree(manifestDump);
  assert.equal(manifest.name, 'manifest', 'COMPILED_MANIFEST_REQUIRED');
  assert.equal(sdkValue(manifest.attrs.get('package')), 'ai.caseops.mobile.dev.localacceptance', 'COMPILED_QA_APP_ID_REQUIRED');
  const apps = manifest.children.filter((node) => node.name === 'application');
  assert.equal(apps.length, 1, 'ONE_COMPILED_APPLICATION_REQUIRED');
  const android = (name, id, optional = false) => {
    const attr = apps[0].attrs.get(`http://schemas.android.com/apk/res/android:${name}`);
    if (!attr && optional) return false;
    assert.equal(attr?.id, id, 'ANDROID_FRAMEWORK_ATTRIBUTE_ID_REQUIRED');
    return sdkValue(attr);
  };
  assert.equal(android('networkSecurityConfig', '0x01010527'), `@${resources.network.id}`, 'MANIFEST_NETWORK_POINTER_MISMATCH');
  assert.equal(android('allowBackup', '0x01010280'), false, 'COMPILED_BACKUP_MUST_BE_DISABLED');
  assert.equal(android('usesCleartextTraffic', '0x010104ec'), false, 'COMPILED_CLEARTEXT_MUST_BE_DISABLED');
  assert.equal(android('debuggable', '0x0101000f', true), false, 'COMPILED_DEBUGGABLE_MUST_BE_DISABLED');
  const network = sdkXmlTree(networkDump);
  assert.equal(network.name, 'network-security-config', 'COMPILED_NETWORK_ROOT_REQUIRED');
  shape(network, [], ['base-config', 'domain-config']);
  const bases = network.children.filter((node) => node.name === 'base-config');
  const domains = network.children.filter((node) => node.name === 'domain-config');
  assert.equal(bases.length, 1, 'ONE_BASE_CONFIG_REQUIRED');
  assert.equal(domains.length, 2, 'EXACT_DOMAIN_CONFIGS_REQUIRED');
  const source = (node) => {
    const anchors = node.children.filter((child) => child.name === 'trust-anchors');
    assert.equal(anchors.length, 1, 'ONE_TRUST_ANCHOR_SET_REQUIRED');
    shape(anchors[0], [], ['certificates']);
    assert.equal(anchors[0].children.length, 1, 'ONE_CERTIFICATE_SOURCE_REQUIRED');
    const cert = anchors[0].children[0];
    shape(cert, ['src'], []);
    return sdkValue(cert.attrs.get('src'));
  };
  shape(bases[0], ['cleartextTrafficPermitted'], ['trust-anchors']);
  assert.equal(sdkValue(bases[0].attrs.get('cleartextTrafficPermitted')), false, 'BASE_CLEARTEXT_FORBIDDEN');
  assert.equal(source(bases[0]), 'system', 'BASE_SYSTEM_TRUST_REQUIRED');
  const groups = new Map();
  for (const domain of domains) {
    shape(domain, ['cleartextTrafficPermitted'], ['domain', 'trust-anchors']);
    assert.equal(sdkValue(domain.attrs.get('cleartextTrafficPermitted')), false, 'DOMAIN_CLEARTEXT_FORBIDDEN');
    const trust = source(domain);
    assert.ok(!groups.has(trust), 'DUPLICATE_TRUST_DOMAIN_GROUP');
    const names = domain.children.filter((item) => item.name === 'domain').map((item) => {
      assert.deepEqual([...item.attrs.keys()], ['includeSubdomains'], 'EXACT_HOST_ATTRIBUTE_REQUIRED');
      assert.equal(sdkValue(item.attrs.get('includeSubdomains')), false, 'SUBDOMAIN_TRUST_FORBIDDEN');
      assert.equal(item.children.length, 0, 'DOMAIN_CHILDREN_FORBIDDEN');
      assert.equal(item.texts.length, 1, 'ONE_DOMAIN_NAME_REQUIRED');
      return item.texts[0];
    });
    groups.set(trust, names.sort());
  }
  assert.deepEqual(groups.get(`@${resources.ca.id}`), [...hosts].sort(), 'NETWORK_CA_POINTER_OR_HOST_MISMATCH');
  assert.deepEqual(groups.get('system'), ['localhost', 'ip6-localhost', '127.0.0.1', '[::1]']
    .filter((host) => !hosts.includes(host)).sort(), 'OTHER_LOOPBACK_SYSTEM_TRUST_REQUIRED');
  return { hosts: [...hosts].sort(), manifestNetworkReference: resources.network.id,
    networkCaReference: resources.ca.id, allowBackup: false, cleartextPermitted: false, debuggable: false };
}

export function verifyAndroidZipEvidence(resources, entries, caBytes, expectedSha256) {
  assert.match(expectedSha256, /^[a-f0-9]{64}$/, 'EXACT_CA_HASH_REQUIRED');
  assert.ok(Array.isArray(entries) && entries.length > 0 && entries.length <= 30000, 'APK_ZIP_ENTRY_BOUND');
  const byName = new Map();
  let total = 0;
  for (const entry of entries) {
    safeZipPath(entry.name);
    assert.ok(!byName.has(entry.name), 'DUPLICATE_APK_ZIP_ENTRY');
    assert.ok(Number.isSafeInteger(entry.length) && entry.length >= 0
      && (total += entry.length) <= 1024 * 1024 * 1024, 'APK_UNCOMPRESSED_SIZE_BOUND');
    byName.set(entry.name, entry);
  }
  const required = new Map([['AndroidManifest.xml', 4 * 1024 * 1024], ['assets/app.config', 1024 * 1024],
    ['assets/index.android.bundle', 32 * 1024 * 1024], [safeZipPath(resources.ca.path, true), 16384],
    [safeZipPath(resources.network.path, true), 1024 * 1024]]);
  assert.equal(required.size, 5, 'DISTINCT_APK_ENTRIES_REQUIRED');
  for (const [name, limit] of required) {
    assert.ok(byName.has(name) && byName.get(name).length > 0 && byName.get(name).length <= limit, 'REQUIRED_APK_ZIP_ENTRY_MISSING_OR_UNBOUNDED');
  }
  assert.ok(Buffer.isBuffer(caBytes) && caBytes.length > 0 && caBytes.length <= 16384, 'APK_CA_SIZE_BOUND');
  const actual = createHash('sha256').update(caBytes).digest('hex');
  assert.equal(actual, expectedSha256, 'APK_CA_HASH_MISMATCH');
  assert.equal(byName.get(resources.ca.path).length, caBytes.length, 'APK_CA_LENGTH_MISMATCH');
  return { publicCaSha256: actual, zipEntryCount: entries.length };
}

export function inspectAndroidAcceptanceResources(apk, sdk, before, directory) {
  assert.ok(statSync(apk).size <= 512 * 1024 * 1024, 'APK_FILE_SIZE_BOUND');
  const hash = binaryHash(apk);
  const run = (args, name) => {
    const result = spawnSync(sdk, args, { encoding: 'utf8', timeout: 20000, maxBuffer: 16 * 1024 * 1024, windowsHide: true });
    writeFileSync(path.join(directory, name), result.stdout || '', { flag: 'wx' });
    writeFileSync(path.join(directory, `${name}.stderr`), result.stderr || '', { flag: 'wx' });
    assert.ok(!result.error && result.status === 0, 'SDK_INSPECTION_FAILED_SEE_RETAINED_LOGS');
    return result.stdout;
  };
  const resources = resolveAndroidAcceptanceResources(run(['dump', 'resources', apk], 'apk-resources.log'));
  const manifest = run(['dump', 'xmltree', '--file', 'AndroidManifest.xml', apk], 'apk-manifest-tree.log');
  const network = run(['dump', 'xmltree', '--file', resources.network.path, apk], 'apk-network-tree.log');
  const hosts = [...new Set([before.apiOrigin, before.webOrigin].map((origin) => {
    const url = new URL(origin);
    assert.equal(url.protocol, 'https:', 'HTTPS_REQUIRED');
    return url.hostname;
  }))];
  const compiledSecurity = verifyAndroidCompiledSecurity(resources, manifest, network, hosts);
  assert.equal(binaryHash(apk), hash, 'APK_CHANGED_DURING_SDK_INSPECTION');
  return { ...resources, compiledSecurity, apkSha256: hash };
}

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

export function finishBuild(platform, before, artifact, embeddedConfig, androidSecurity) {
  const after = checkBuildConfig(platform);
  assert.deepEqual(after, before, 'SOURCE_OR_CONFIGURATION_CHANGED_DURING_BUILD');
  assert.ok(path.isAbsolute(artifact), 'ABSOLUTE_ARTIFACT_REQUIRED');
  assert.equal(embeddedConfig.extra.automatedTest, true, 'EMBEDDED_MARKER_REQUIRED');
  assert.equal(embeddedConfig.extra.apiOrigin, after.apiOrigin, 'EMBEDDED_API_ORIGIN_MISMATCH');
  assert.equal(embeddedConfig.extra.webOrigin, after.webOrigin, 'EMBEDDED_WEB_ORIGIN_MISMATCH');
  assert.equal(embeddedConfig.extra.releaseSha, after.sourceSha, 'EMBEDDED_SOURCE_MISMATCH');
  if (platform === 'ios') assert.equal(embeddedConfig.ios.bundleIdentifier, after.appId, 'EMBEDDED_QA_BUNDLE_ID_REQUIRED');
  const hash = binaryHash(artifact);
  if (platform === 'android' && androidSecurity) {
    assert.equal(androidSecurity.kind, 'compiled-android-acceptance-security', 'COMPILED_ANDROID_SECURITY_PROOF_REQUIRED');
    assert.equal(androidSecurity.apkSha256, hash, 'ANDROID_SECURITY_ARTIFACT_MISMATCH');
    assert.equal(androidSecurity.publicCaSha256, before.publicCaSha256, 'ANDROID_SECURITY_CA_MISMATCH');
  }
  return { ...after, artifact, binaryHash: hash, ...(androidSecurity ? { androidSecurity } : {}),
    binaryHashKind: 'sha256-file-or-canonical-bundle-tree' };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [command, ...args] = process.argv.slice(2);
  const readJson = (file) => {
    assert.ok(statSync(file).size <= 16 * 1024 * 1024, 'BUILD_JSON_SIZE_BOUND');
    return JSON.parse(readFileSync(file, 'utf8'));
  };
  if (command === 'android-resources' || command === 'android-zip') {
    let result, output;
    if (command === 'android-resources') {
      assert.equal(args.length, 5, 'ANDROID_RESOURCE_ARGUMENTS_REQUIRED');
      const [before, apk, sdk, directory, destination] = args;
      result = inspectAndroidAcceptanceResources(apk, sdk, readJson(before), directory);
      output = destination;
    } else {
      assert.equal(args.length, 6, 'ANDROID_ZIP_ARGUMENTS_REQUIRED');
      const [planFile, inventory, caFile, before, apk, destination] = args;
      const plan = readJson(planFile);
      assert.ok(statSync(caFile).size <= 16384, 'APK_CA_SIZE_BOUND');
      assert.equal(binaryHash(apk), plan.apkSha256, 'APK_CHANGED_DURING_ZIP_INSPECTION');
      result = { ...plan, ...verifyAndroidZipEvidence(plan, readJson(inventory), readFileSync(caFile), readJson(before).publicCaSha256),
        kind: 'compiled-android-acceptance-security', nativeExecution: 'not-run-by-verifier' };
      output = destination;
    }
    const json = `${JSON.stringify(result, null, 2)}\n`;
    writeFileSync(output, json, { flag: 'wx' });
    process.stdout.write(json);
    process.exit(0);
  }
  const [platform, beforeFile, artifact, configFile, outputFile, androidProofFile] = args;
  assert.ok(['android', 'ios'].includes(platform), 'PLATFORM_REQUIRED');
  let result;
  if (command === 'check') result = checkBuildConfig(platform);
  else {
    assert.equal(command, 'finish', 'UNKNOWN_BUILD_COMMAND');
    if (platform === 'android') assert.ok(androidProofFile, 'COMPILED_ANDROID_SECURITY_PROOF_REQUIRED');
    result = finishBuild(platform, JSON.parse(readFileSync(beforeFile, 'utf8')),
      artifact, JSON.parse(readFileSync(configFile, 'utf8')), androidProofFile ? readJson(androidProofFile) : undefined);
  }
  const json = `${JSON.stringify(result, null, 2)}\n`;
  const destination = command === 'check' ? beforeFile : outputFile;
  if (destination) writeFileSync(destination, json, { flag: 'wx' });
  process.stdout.write(json);
}
