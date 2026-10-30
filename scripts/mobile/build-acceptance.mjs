import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { closeSync, constants, fstatSync, lstatSync, openSync, readSync, realpathSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { sourceSnapshot } from './source-snapshot.mjs';
import { binaryHash } from '../../apps/mobile/e2e/support.mjs';

const appRoot = fileURLToPath(new URL('../../apps/mobile/', import.meta.url));

/** Read the checked descriptor, with one excess byte detecting growth. */
export function readBuildInput(file, maxBytes, io = { openSync, closeSync, fstatSync, lstatSync, readSync }) {
  assert.ok(Number.isSafeInteger(maxBytes) && maxBytes > 0 && maxBytes <= 512 * 1024 * 1024, 'BUILD_INPUT_BOUND_REQUIRED');
  file = path.resolve(file);
  const fd = io.openSync(file, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0) | (constants.O_NONBLOCK ?? 0));
  try {
    const opened = io.fstatSync(fd, { bigint: true });
    const named = io.lstatSync(file, { bigint: true });
    const fields = ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs'];
    // Only the named Windows API's documented zero device value is portable.
    // Comparisons within either API still retain every metadata field.
    const same = (a, b, cross = false) => fields.every(key =>
      (cross && key === 'dev' && process.platform === 'win32' && b.dev === 0n) || a[key] === b[key]);
    assert.ok(opened.isFile() && named.isFile() && !named.isSymbolicLink() && opened.nlink === 1n
      && (typeof process.getuid !== 'function' || opened.uid === BigInt(process.getuid()))
      && opened.size > 0n && opened.size <= BigInt(maxBytes) && same(opened, named, true), 'OWNED_BOUNDED_BUILD_INPUT_REQUIRED');
    const namespace = () => {
      const canonical = realpathSync(file);
      assert.ok(same(opened, io.lstatSync(canonical, { bigint: true }), true), 'BUILD_INPUT_NAMESPACE_CHANGED');
      const rows = [canonical];
      for (let parent = path.dirname(canonical);;) {
        const value = io.lstatSync(parent, { bigint: true });
        assert.ok(value.isDirectory() && !value.isSymbolicLink() && rows.length <= 128, 'BUILD_INPUT_NAMESPACE_CHANGED');
        rows.push([parent, ...['dev', 'ino', 'mode', 'uid', 'gid'].map(key => String(value[key]))]);
        if (path.dirname(parent) === parent) break;
        parent = path.dirname(parent);
      }
      return rows;
    };
    const parents = namespace();
    const bytes = Buffer.alloc(Number(opened.size) + 1);
    let length = 0;
    while (length < bytes.length) {
      const count = io.readSync(fd, bytes, length, bytes.length - length, null);
      if (count === 0) break;
      length += count;
    }
    assert.ok(BigInt(length) === opened.size && same(opened, io.fstatSync(fd, { bigint: true }))
      && same(named, io.lstatSync(file, { bigint: true })), 'BUILD_INPUT_CHANGED');
    assert.deepEqual(namespace(), parents, 'BUILD_INPUT_NAMESPACE_CHANGED');
    return bytes.subarray(0, length);
  } finally { io.closeSync(fd); }
}
const require = createRequire(path.join(appRoot, 'package.json'));
const { getConfig } = require('@expo/config');
const { parse: parsePlist } = require('@expo/plist').default;
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
  const hash = createHash('sha256').update(readBuildInput(apk, 512 * 1024 * 1024)).digest('hex');
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
  assert.equal(createHash('sha256').update(readBuildInput(apk, 512 * 1024 * 1024)).digest('hex'), hash, 'APK_CHANGED_DURING_SDK_INSPECTION');
  return { ...resources, compiledSecurity, apkSha256: hash };
}

export function decodeIosSimulatorEntitlements(dump) {
  const lines = boundedLines(dump, 256 * 1024).filter((line) => line.trim());
  const headers = lines.flatMap((line, index) => line === '(__TEXT,__entitlements) section:' ? [index] : []);
  assert.equal(headers.length, 1, 'EMBEDDED_SIMULATOR_ENTITLEMENTS_REQUIRED');
  const chunks = [];
  let nextAddress, total = 0;
  for (const line of lines.slice(headers[0] + 1)) {
    const row = /^0x([0-9a-fA-F]+): ((?:[0-9a-fA-F]{2} ){0,15}[0-9a-fA-F]{2})\s*$/.exec(line);
    assert.ok(row, 'SIMULATOR_ENTITLEMENT_SECTION_INVALID');
    const address = Number.parseInt(row[1], 16);
    assert.ok(Number.isSafeInteger(address) && (nextAddress === undefined || address === nextAddress), 'SIMULATOR_ENTITLEMENT_SECTION_GAP');
    const bytes = Buffer.from(row[2].replaceAll(' ', ''), 'hex');
    total += bytes.length;
    assert.ok(total <= 65536, 'SIMULATOR_ENTITLEMENT_SECTION_BOUND');
    chunks.push(bytes);
    nextAddress = address + bytes.length;
  }
  const xml = Buffer.concat(chunks).toString('utf8').replace(/\0+$/, '');
  assert.ok(xml.length > 0 && !xml.includes('\0') && xml.trimStart().startsWith('<?xml'), 'EMBEDDED_SIMULATOR_ENTITLEMENTS_REQUIRED');
  return xml;
}

export function parseIosSimulatorEntitlements(dump) {
  const xml = decodeIosSimulatorEntitlements(dump);
  return { xml, entitlements: parsePlist(xml) };
}

export function verifyIosSimulatorSigning(appId, info, entitlements, metadata) {
  assert.equal(appId, 'ai.caseops.mobile.dev.simulatoracceptance', 'SIMULATOR_ACCEPTANCE_APP_REQUIRED');
  assert.equal(info.CFBundleIdentifier, appId, 'SIGNED_SIMULATOR_BUNDLE_ID_MISMATCH');
  assert.equal(info.DTPlatformName, 'iphonesimulator', 'SIMULATOR_BINARY_REQUIRED');
  assert.deepEqual(info.CFBundleSupportedPlatforms, ['iPhoneSimulator'], 'SIMULATOR_BINARY_REQUIRED');
  boundedLines(metadata, 1048576);
  assert.equal(metadata.split(/\r?\n/).filter((line) => line === `Identifier=${appId}`).length, 1, 'SIGNED_BUNDLE_IDENTIFIER_REQUIRED');
  assert.match(metadata, /^Signature=adhoc$/m, 'SIMULATOR_LOCAL_ADHOC_SIGNING_REQUIRED');
  assert.doesNotMatch(metadata, /linker-signed|Info\.plist=not bound|Sealed Resources=none/, 'COMPLETE_APP_SIGNATURE_REQUIRED');
  assert.match(metadata, /^Info\.plist entries=\d+$/m, 'SIGNED_INFO_PLIST_REQUIRED');
  assert.match(metadata, /^Sealed Resources version=\d+ /m, 'SIGNED_BUNDLE_RESOURCES_REQUIRED');
  const applicationIdentifier = entitlements['application-identifier'];
  const suffix = `.${appId}`;
  assert.ok(typeof applicationIdentifier === 'string' && applicationIdentifier.endsWith(suffix)
    && /^[A-Za-z0-9]+$/.test(applicationIdentifier.slice(0, -suffix.length)), 'EMBEDDED_APPLICATION_IDENTIFIER_REQUIRED');
  const declaredGroups = entitlements['keychain-access-groups'];
  if (Object.hasOwn(entitlements, 'keychain-access-groups')) {
    assert.ok(Array.isArray(declaredGroups) && declaredGroups.length <= 1
      && declaredGroups.every((group) => group === applicationIdentifier), 'EXACT_PRIVATE_KEYCHAIN_GROUP_REQUIRED');
  }
  const appGroups = entitlements['com.apple.security.application-groups'];
  if (Object.hasOwn(entitlements, 'com.apple.security.application-groups')) {
    assert.ok(Array.isArray(appGroups) && appGroups.length === 0, 'SIMULATOR_SHARED_KEYCHAIN_GROUP_FORBIDDEN');
  }
  // Apple's access-group list always includes the signed application identifier.
  // Without explicit Keychain groups it is the default, private access group:
  // https://developer.apple.com/documentation/security/ksecattraccessgroup
  return { applicationIdentifier, keychainAccessGroups: [applicationIdentifier],
    keychainGroupSource: declaredGroups?.length ? 'explicit-private-group' : 'application-identifier-default' };
}

export function inspectIosSimulatorSigning(artifact, appId, directory) {
  assert.equal(process.platform, 'darwin', 'ACTUAL_MAC_SIGNING_INSPECTION_REQUIRED');
  assert.ok(path.isAbsolute(artifact) && path.isAbsolute(directory), 'ABSOLUTE_SIGNING_EVIDENCE_PATH_REQUIRED');
  const relative = path.relative(artifact, directory);
  assert.ok(relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative), 'SIGNING_EVIDENCE_MUST_STAY_OUTSIDE_APP');
  const initialHash = binaryHash(artifact), evidence = [];
  const run = (binary, args, name) => {
    const result = spawnSync(binary, args, { encoding: 'utf8', timeout: 20000, maxBuffer: 1048576 });
    const file = path.join(directory, name);
    const log = `${result.stdout || ''}${result.stderr || ''}`;
    writeFileSync(file, log, { flag: 'wx', mode: 0o600 });
    evidence.push({ path: file, sha256: createHash('sha256').update(log).digest('hex') });
    assert.ok(!result.error && result.status === 0, 'IOS_SIGNING_INSPECTION_FAILED_SEE_RETAINED_LOGS');
    return result;
  };
  run('/usr/bin/codesign', ['--verify', '--deep', '--strict', '--verbose=2', artifact], 'ios-signature-verify.log');
  const info = JSON.parse(run('/usr/bin/plutil', ['-convert', 'json', '-o', '-', path.join(artifact, 'Info.plist')], 'ios-signed-info.json').stdout);
  assert.ok(typeof info.CFBundleExecutable === 'string' && /^[A-Za-z0-9_.-]+$/.test(info.CFBundleExecutable), 'SIGNED_EXECUTABLE_NAME_REQUIRED');
  const executable = path.join(artifact, info.CFBundleExecutable);
  const metadataResult = run('/usr/bin/codesign', ['--display', '--verbose=4', artifact], 'ios-signature-metadata.log');
  const metadata = `${metadataResult.stdout || ''}${metadataResult.stderr || ''}`;
  run('/usr/bin/codesign', ['--display', '--entitlements', '-', '--xml', artifact], 'ios-signature-entitlements.log');
  const architectures = run('/usr/bin/xcrun', ['lipo', '-archs', executable], 'ios-signature-architectures.log').stdout.trim().split(/\s+/);
  assert.ok(architectures.length > 0 && architectures.length <= 2 && new Set(architectures).size === architectures.length
    && architectures.every((arch) => ['arm64', 'x86_64'].includes(arch)), 'SIMULATOR_ARCHITECTURES_REQUIRED');
  const slices = architectures.map((arch) => {
    // Xcode embeds Simulator entitlements in Mach-O __TEXT rather than necessarily
    // placing them in the code-signature entitlement blob. Inspect the executable.
    const dump = run('/usr/bin/xcrun', ['dyld_info', '-arch', arch, '-section_bytes', '__TEXT', '__entitlements', executable], `ios-entitlements-${arch}.log`).stdout;
    const { xml, entitlements } = parseIosSimulatorEntitlements(dump);
    const file = path.join(directory, `ios-entitlements-${arch}.plist`);
    writeFileSync(file, xml, { flag: 'wx', mode: 0o600 });
    evidence.push({ path: file, sha256: createHash('sha256').update(xml).digest('hex') });
    return { architecture: arch, ...verifyIosSimulatorSigning(appId, info, entitlements, metadata) };
  });
  for (const slice of slices) assert.deepEqual(slice.keychainAccessGroups, slices[0].keychainAccessGroups, 'SIMULATOR_ARCHITECTURE_ENTITLEMENTS_MISMATCH');
  assert.equal(binaryHash(artifact), initialHash, 'SIGNED_APP_CHANGED_DURING_INSPECTION');
  return { kind: 'ios-simulator-ad-hoc-signing', appId, strictVerified: true, signingIdentity: '-',
    applicationIdentifier: slices[0].applicationIdentifier, keychainAccessGroups: slices[0].keychainAccessGroups,
    keychainGroupSource: slices[0].keychainGroupSource,
    entitlementsLocation: 'Mach-O __TEXT,__entitlements', slices, evidence, artifactSha256: initialHash,
    distributionSigning: false, nativeExecution: 'not-run-by-signing-verifier' };
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
    privacyPolicy: exp.extra.privacyPolicy ?? null,
    publicCaSha256: settings.ca?.sha256 ?? null, devEnabled: false,
    nativeExecution: 'not-run-by-build-wrapper' };
}

export function finishBuild(platform, before, artifact, embeddedConfig, nativeSecurity) {
  const after = checkBuildConfig(platform);
  assert.deepEqual(after, before, 'SOURCE_OR_CONFIGURATION_CHANGED_DURING_BUILD');
  assert.ok(path.isAbsolute(artifact), 'ABSOLUTE_ARTIFACT_REQUIRED');
  assert.equal(embeddedConfig.extra.automatedTest, true, 'EMBEDDED_MARKER_REQUIRED');
  assert.equal(embeddedConfig.extra.apiOrigin, after.apiOrigin, 'EMBEDDED_API_ORIGIN_MISMATCH');
  assert.equal(embeddedConfig.extra.webOrigin, after.webOrigin, 'EMBEDDED_WEB_ORIGIN_MISMATCH');
  assert.equal(embeddedConfig.extra.releaseSha, after.sourceSha, 'EMBEDDED_SOURCE_MISMATCH');
  assert.deepEqual(embeddedConfig.extra.privacyPolicy ?? null, after.privacyPolicy, 'EMBEDDED_PRIVACY_POLICY_MISMATCH');
  if (platform === 'ios') assert.equal(embeddedConfig.ios.bundleIdentifier, after.appId, 'EMBEDDED_QA_BUNDLE_ID_REQUIRED');
  const hash = platform === 'android'
    ? createHash('sha256').update(readBuildInput(artifact, 512 * 1024 * 1024)).digest('hex')
    : binaryHash(artifact);
  if (platform === 'android' && nativeSecurity) {
    assert.equal(nativeSecurity.kind, 'compiled-android-acceptance-security', 'COMPILED_ANDROID_SECURITY_PROOF_REQUIRED');
    assert.equal(nativeSecurity.apkSha256, hash, 'ANDROID_SECURITY_ARTIFACT_MISMATCH');
    assert.equal(nativeSecurity.publicCaSha256, before.publicCaSha256, 'ANDROID_SECURITY_CA_MISMATCH');
  }
  if (platform === 'ios') {
    assert.equal(nativeSecurity?.kind, 'ios-simulator-ad-hoc-signing', 'IOS_SIMULATOR_SIGNING_PROOF_REQUIRED');
    assert.equal(nativeSecurity.appId, before.appId, 'SIGNED_SIMULATOR_BUNDLE_ID_MISMATCH');
    assert.equal(nativeSecurity.strictVerified, true, 'STRICT_SIMULATOR_SIGNATURE_REQUIRED');
    assert.equal(nativeSecurity.artifactSha256, hash, 'IOS_SIGNING_ARTIFACT_MISMATCH');
  }
  return { ...after, artifact, binaryHash: hash, ...(nativeSecurity ? { [platform === 'android' ? 'androidSecurity' : 'iosSigning']: nativeSecurity } : {}),
    binaryHashKind: 'sha256-file-or-canonical-bundle-tree' };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [command, ...args] = process.argv.slice(2);
  const readJson = (file) => JSON.parse(readBuildInput(file, 16 * 1024 * 1024).toString('utf8'));
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
      assert.equal(createHash('sha256').update(readBuildInput(apk, 512 * 1024 * 1024)).digest('hex'), plan.apkSha256, 'APK_CHANGED_DURING_ZIP_INSPECTION');
      result = { ...plan, ...verifyAndroidZipEvidence(plan, readJson(inventory), readBuildInput(caFile, 16384), readJson(before).publicCaSha256),
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
    const before = readJson(beforeFile);
    const nativeSecurity = platform === 'ios' ? inspectIosSimulatorSigning(artifact, before.appId, path.dirname(outputFile))
      : androidProofFile ? readJson(androidProofFile) : undefined;
    result = finishBuild(platform, before, artifact, readJson(configFile), nativeSecurity);
  }
  const json = `${JSON.stringify(result, null, 2)}\n`;
  const destination = command === 'check' ? beforeFile : outputFile;
  if (destination) writeFileSync(destination, json, { flag: 'wx' });
  process.stdout.write(json);
}
