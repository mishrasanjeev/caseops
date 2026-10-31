// Store-artifact contracts. Synthetic observations never establish signing.
import assert from 'node:assert/strict';
import { createHash, X509Certificate } from 'node:crypto';
import { inflateRawSync } from 'node:zlib';
import fs from 'node:fs';
import path from 'node:path';
import { checkDeadline, privateDirectory as rawPrivateDirectory, readInput as rawReadInput, writePrivate as rawWritePrivate } from './store-packaging-inputs.mjs';

export const ARTIFACT_LIMITS = Object.freeze({ compressed: 512 * 1024 * 1024,
  entries: 30000, expanded: 1024 * 1024 * 1024, member: 128 * 1024 * 1024 });
export const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
const exact = (a, b, code) => assert.deepEqual(a, b, code);
const own = (v, k) => Object.hasOwn(v, k);
export function safeMember(name) {
  assert.ok(typeof name === 'string' && name.length > 0 && Buffer.byteLength(name) <= 1024
    && !/[\\:\0\r\n]/.test(name) && !name.startsWith('/')
    && name.replace(/\/$/, '').split('/').every(p => p && p !== '.' && p !== '..'), 'STORE_ZIP_PATH_REFUSED');
  return name;
}
function crc32(bytes) {
  let n = 0xffffffff;
  for (const byte of bytes) { n ^= byte; for (let i = 0; i < 8; i++) n = (n >>> 1) ^ ((n & 1) ? 0xedb88320 : 0); }
  return (n ^ 0xffffffff) >>> 0;
}

// Consume only the retained, descriptor-verified archive. ZIP64/encryption and
// links are explicitly unsupported, rather than partially inspected.
export function inspectStoreZip(bytes, consume = () => {}) {
  assert.ok(Buffer.isBuffer(bytes) && bytes.length >= 22 && bytes.length <= ARTIFACT_LIMITS.compressed, 'STORE_ZIP_BOUND');
  let end = -1;
  for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 65557); i--) {
    if (bytes.readUInt32LE(i) === 0x06054b50 && i + 22 + bytes.readUInt16LE(i + 20) === bytes.length) { end = i; break; }
  }
  assert.ok(end >= 0, 'STORE_ZIP_DIRECTORY_REQUIRED');
  const count = bytes.readUInt16LE(end + 10), size = bytes.readUInt32LE(end + 12), start = bytes.readUInt32LE(end + 16);
  assert.ok(bytes.readUInt16LE(end + 4) === 0 && bytes.readUInt16LE(end + 6) === 0
    && count === bytes.readUInt16LE(end + 8) && count > 0 && count !== 65535
    && count <= ARTIFACT_LIMITS.entries && start + size === end, 'STORE_ZIP_DIRECTORY_REFUSED');
  let cursor = start, expanded = 0;
  const seen = new Set(), rows = [], ranges = [];
  for (let i = 0; i < count; i++) {
    assert.ok(cursor + 46 <= end && bytes.readUInt32LE(cursor) === 0x02014b50, 'STORE_ZIP_DIRECTORY_REFUSED');
    const flags = bytes.readUInt16LE(cursor + 8), method = bytes.readUInt16LE(cursor + 10);
    const crc = bytes.readUInt32LE(cursor + 16), packed = bytes.readUInt32LE(cursor + 20), length = bytes.readUInt32LE(cursor + 24);
    const n = bytes.readUInt16LE(cursor + 28), extra = bytes.readUInt16LE(cursor + 30), comment = bytes.readUInt16LE(cursor + 32);
    const mode = bytes.readUInt32LE(cursor + 38) >>> 16, local = bytes.readUInt32LE(cursor + 42);
    assert.ok(cursor + 46 + n + extra + comment <= end && n > 0 && n <= 1024 && !(flags & 1)
      && [0, 8].includes(method) && packed !== 0xffffffff && length !== 0xffffffff
      && length <= ARTIFACT_LIMITS.member && (expanded += length) <= ARTIFACT_LIMITS.expanded
      && bytes.readUInt16LE(cursor + 34) === 0 && [0, 0o100000, 0o040000].includes(mode & 0o170000)
      && !(mode & 0o7000), 'STORE_ZIP_MEMBER_REFUSED');
    let name;
    try { name = new TextDecoder('utf-8', { fatal: true }).decode(bytes.subarray(cursor + 46, cursor + 46 + n)); }
    catch { throw new Error('STORE_ZIP_NAME_ENCODING_REFUSED'); }
    safeMember(name); assert.ok(!seen.has(name), 'STORE_ZIP_DUPLICATE_REFUSED'); seen.add(name);
    assert.ok(local + 30 <= start && bytes.readUInt32LE(local) === 0x04034b50
      && bytes.readUInt16LE(local + 6) === flags && bytes.readUInt16LE(local + 8) === method, 'STORE_ZIP_LOCAL_HEADER_REFUSED');
    const localN = bytes.readUInt16LE(local + 26), localExtra = bytes.readUInt16LE(local + 28), data = local + 30 + localN + localExtra;
    assert.ok(localN === n && bytes.subarray(local + 30, local + 30 + localN).equals(bytes.subarray(cursor + 46, cursor + 46 + n))
      && data + packed <= start, 'STORE_ZIP_LOCAL_HEADER_REFUSED');
    if (!(flags & 8)) assert.ok(bytes.readUInt32LE(local + 14) === crc && bytes.readUInt32LE(local + 18) === packed
      && bytes.readUInt32LE(local + 22) === length, 'STORE_ZIP_LOCAL_EXTENT_REFUSED');
    ranges.push([local, data + packed]);
    const compressed = bytes.subarray(data, data + packed);
    const content = method === 0 ? compressed : inflateRawSync(compressed, { maxOutputLength: length + 1 });
    assert.ok(content.length === length && crc32(content) === crc && (!name.endsWith('/') || length === 0), 'STORE_ZIP_CONTENT_REFUSED');
    const row = { name, bytes: length, sha256: sha256(content), mode: mode & 0o777 };
    rows.push(row); consume(row, content);
    cursor += 46 + n + extra + comment;
  }
  assert.equal(cursor, end, 'STORE_ZIP_DIRECTORY_EXTENT_REFUSED');
  ranges.sort((a, b) => a[0] - b[0]);
  assert.ok(ranges.every((r, i) => i === 0 || r[0] >= ranges[i - 1][1]), 'STORE_ZIP_OVERLAP_REFUSED');
  return { archiveSha256: sha256(bytes), compressedBytes: bytes.length, expandedBytes: expanded, entries: rows };
}

export function certificateIdentity(der, now = Date.now()) {
  const cert = new X509Certificate(der);
  assert.ok(Date.parse(cert.validFrom) <= now && now < Date.parse(cert.validTo), 'STORE_CERTIFICATE_EXPIRED_OR_NOT_YET_VALID');
  return { sha1: cert.fingerprint.replaceAll(':', '').toLowerCase(), sha256: cert.fingerprint256.replaceAll(':', '').toLowerCase() };
}
export function verifyEmbeddedAttestation(value, expected) {
  exact(value, expected, 'STORE_EMBEDDED_SOURCE_POLICY_NOTICES_MISMATCH');
  return { sourceSha: expected.source.sourceSha, sourceFingerprint: expected.source.sourceFingerprint,
    linkSha256: expected.nativeLinks.sha256, buildSha256: expected.storeBuild.sha256,
    notices: expected.notices.map(n => ({ name: n.name, sha256: n.sha256 })) };
}
export function verifyIosDistribution(observed, expected) {
  const { info, entitlements: e, profile: p } = observed;
  assert.equal(observed.strictSignatureExit, 0, 'STORE_IOS_SIGNATURE_REFUSED');
  assert.equal(observed.certificate.sha1, expected.signing.certificateSha1, 'STORE_IOS_CERTIFICATE_MISMATCH');
  assert.equal(observed.certificate.sha256, expected.signing.certificateSha256, 'STORE_IOS_CERTIFICATE_MISMATCH');
  assert.equal(info.CFBundleIdentifier, expected.appId, 'STORE_IOS_ID_MISMATCH');
  assert.equal(info.CFBundleShortVersionString, expected.version, 'STORE_IOS_VERSION_MISMATCH');
  assert.equal(info.CFBundleVersion, expected.iosBuildNumber, 'STORE_IOS_BUILD_MISMATCH');
  assert.equal(info.CaseOpsPrivacyPolicyURL, expected.privacyPolicy.url, 'STORE_IOS_PRIVACY_URL_MISMATCH');
  assert.equal(info.CaseOpsPrivacyPolicyVersion, expected.privacyPolicy.version, 'STORE_IOS_PRIVACY_VERSION_MISMATCH');
  assert.equal(info.CaseOpsPrivacyPolicySHA256, expected.privacyPolicy.sha256, 'STORE_IOS_PRIVACY_DIGEST_MISMATCH');
  assert.equal(info.DTPlatformName, 'iphoneos', 'STORE_IOS_DEVICE_ARTIFACT_REQUIRED');
  exact(info.CFBundleSupportedPlatforms, ['iPhoneOS'], 'STORE_IOS_DEVICE_ARTIFACT_REQUIRED');
  exact(observed.architectures, expected.iosArchitectures, 'STORE_IOS_DEVICE_ARCHITECTURE_REQUIRED');
  assert.match(info.MinimumOSVersion || '', /^\d{1,2}\.\d{1,2}(?:\.\d{1,2})?$/, 'STORE_IOS_MINIMUM_OS_REFUSED');
  assert.ok(Number.parseFloat(info.MinimumOSVersion) >= 17.4, 'STORE_IOS_MINIMUM_OS_REFUSED');
  assert.equal(p.UUID, expected.signing.provisioningProfileUuid, 'STORE_IOS_PROFILE_MISMATCH');
  exact(p.TeamIdentifier, [expected.signing.teamId], 'STORE_IOS_TEAM_MISMATCH');
  exact(p.ApplicationIdentifierPrefix, [expected.signing.applicationIdentifierPrefix], 'STORE_IOS_PREFIX_MISMATCH');
  assert.ok(Date.parse(p.ExpirationDate) > expected.now && !own(p, 'ProvisionedDevices') && p.ProvisionsAllDevices !== true,
    'STORE_IOS_APP_STORE_PROFILE_REQUIRED');
  const applicationId = expected.signing.applicationIdentifierPrefix + '.' + expected.appId;
  assert.equal(e['application-identifier'], applicationId, 'STORE_IOS_ENTITLEMENT_ID_MISMATCH');
  assert.equal(p.Entitlements['application-identifier'], applicationId, 'STORE_IOS_PROFILE_ID_MISMATCH');
  assert.equal(e['com.apple.developer.team-identifier'], expected.signing.teamId, 'STORE_IOS_TEAM_MISMATCH');
  assert.equal(e['get-task-allow'], false, 'STORE_IOS_DEBUG_ENTITLEMENT_FORBIDDEN');
  assert.equal(p.Entitlements['get-task-allow'], false, 'STORE_IOS_DEBUG_PROFILE_FORBIDDEN');
  exact(e['com.apple.developer.associated-domains'], expected.associatedDomains, 'STORE_IOS_ASSOCIATED_DOMAINS_MISMATCH');
  if (own(e, 'keychain-access-groups')) exact(e['keychain-access-groups'], [applicationId], 'STORE_IOS_KEYCHAIN_SCOPE_MISMATCH');
  assert.ok(!e['com.apple.security.application-groups']?.length, 'STORE_IOS_SHARED_GROUP_FORBIDDEN');
  assert.ok(observed.profileCertificateSha256.includes(expected.signing.certificateSha256), 'STORE_IOS_PROFILE_CERTIFICATE_MISMATCH');
  return verifyEmbeddedAttestation(observed.attestation, expected.attestation);
}
export function verifyAndroidDistribution(observed, expected) {
  assert.equal(observed.bundletoolValidationExit, 0, 'STORE_AAB_VALIDATION_REFUSED');
  assert.equal(observed.jarSignatureExit, 0, 'STORE_AAB_JAR_SIGNATURE_REFUSED');
  assert.equal(observed.signerCount, 1, 'STORE_AAB_ONE_SIGNER_REQUIRED');
  assert.equal(observed.certificate.sha256, expected.signing.uploadCertificateSha256, 'STORE_AAB_UPLOAD_CERTIFICATE_MISMATCH');
  assert.equal(observed.packageName, expected.appId, 'STORE_AAB_ID_MISMATCH');
  assert.equal(observed.versionName, expected.version, 'STORE_AAB_VERSION_MISMATCH');
  assert.equal(observed.versionCode, expected.androidVersionCode, 'STORE_AAB_VERSION_CODE_MISMATCH');
  exact(observed.privacyPolicy, expected.privacyPolicy, 'STORE_AAB_PRIVACY_POLICY_MISMATCH');
  assert.ok(Number.isSafeInteger(observed.targetSdk) && observed.targetSdk >= 36, 'STORE_AAB_TARGET_REQUIRED');
  assert.equal(observed.debuggable, false, 'STORE_AAB_DEBUGGABLE_FORBIDDEN');
  assert.equal(observed.cleartextPermitted, false, 'STORE_AAB_CLEARTEXT_FORBIDDEN');
  assert.equal(observed.networkSecurityConfigurationAbsent, true, 'STORE_AAB_CUSTOM_NETWORK_POLICY_UNREVIEWED');
  assert.equal(observed.allowBackup, false, 'STORE_AAB_BACKUP_FORBIDDEN');
  exact([...new Set(observed.nativeLibraries.map(row => row.abi))].sort(), [...expected.androidAbis].sort(), 'STORE_AAB_ABI_MISMATCH');
  assert.ok(observed.nativeLibraries.length > 0 && observed.nativeLibraries.every(row =>
    row.loadAlignments.length > 0 && row.loadAlignments.every(n => Number.isSafeInteger(n)
      && n >= (['arm64-v8a', 'x86_64'].includes(row.abi) ? 16384 : 4096))), 'STORE_AAB_16K_ABI_REQUIRED');
  return verifyEmbeddedAttestation(observed.attestation, expected.attestation);
}

export function elfLoadAlignments(bytes) {
  assert.ok(bytes.length >= 52 && bytes.subarray(0, 4).equals(Buffer.from([127, 69, 76, 70]))
    && [1, 2].includes(bytes[4]) && bytes[5] === 1, 'STORE_ELF_HEADER_REFUSED');
  const wide = bytes[4] === 2;
  const offset = wide ? Number(bytes.readBigUInt64LE(32)) : bytes.readUInt32LE(28);
  const size = bytes.readUInt16LE(wide ? 54 : 42), count = bytes.readUInt16LE(wide ? 56 : 44);
  assert.ok(Number.isSafeInteger(offset) && offset > 0 && count > 0 && count <= 256
    && size >= (wide ? 56 : 32) && offset + count * size <= bytes.length, 'STORE_ELF_PROGRAM_HEADERS_REFUSED');
  const values = [];
  for (let i = 0; i < count; i++) {
    const at = offset + i * size;
    if (bytes.readUInt32LE(at) === 1) {
      const n = wide ? Number(bytes.readBigUInt64LE(at + 48)) : bytes.readUInt32LE(at + 28);
      assert.ok(Number.isSafeInteger(n) && n > 0 && Number.isInteger(Math.log2(n)), 'STORE_ELF_ALIGNMENT_REFUSED'); values.push(n);
    }
  }
  assert.ok(values.length > 0, 'STORE_ELF_LOAD_REQUIRED'); return values;
}
export const PLIST_JSON_PROGRAM = String.raw`import base64,datetime,json,plistlib,sys
b=sys.stdin.buffer.read(1048577)
if not 0<len(b)<=1048576: raise ValueError('PLIST_BOUND')
def default(v):
 if isinstance(v,bytes): return {'base64':base64.b64encode(v).decode('ascii')}
 if isinstance(v,datetime.datetime): return v.replace(tzinfo=datetime.timezone.utc).isoformat().replace('+00:00','Z')
 raise TypeError('PLIST_TYPE')
sys.stdout.write(json.dumps(plistlib.loads(b),default=default,separators=(',',':')))
`;
export const EMBED_PROGRAM = String.raw`import hashlib,json,os,pathlib,plistlib,stat,sys
platform,root,attestation,backup=sys.argv[1:]
root=pathlib.Path(root);a=pathlib.Path(attestation)
fields=('st_dev','st_ino','st_mode','st_uid','st_gid','st_nlink','st_size','st_mtime_ns','st_ctime_ns')
frame=lambda s:tuple(getattr(s,k) for k in fields)
def names(p):
 result=[]
 for d in p.parents:
  s=d.lstat()
  if not stat.S_ISDIR(s.st_mode) or stat.S_ISLNK(s.st_mode):raise ValueError('NATIVE_NAMESPACE')
  result.append((str(d),tuple(getattr(s,k) for k in fields[:5])))
 return result
def checked(p,limit,writable=False):
 fd=os.open(p,(os.O_RDWR if writable else os.O_RDONLY)|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
 try:
  s=os.fstat(fd);canonical=p.resolve();parents=names(canonical)
  if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_nlink!=1 or not 0<s.st_size<=limit or frame(s)!=frame(p.lstat()) or frame(s)!=frame(canonical.lstat()):raise ValueError('NATIVE_FILE_IDENTITY')
  b=bytearray()
  while len(b)<=s.st_size:
   part=os.read(fd,min(65536,s.st_size+1-len(b)))
   if not part:break
   b.extend(part)
  if len(b)!=s.st_size or frame(s)!=frame(os.fstat(fd)) or frame(s)!=frame(p.lstat()) or p.resolve()!=canonical or names(canonical)!=parents:raise ValueError('NATIVE_FILE_CHANGED')
  return fd,s,bytes(b)
 except BaseException:
  os.close(fd);raise
def write_new(p,b):
 fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
 try:
  n=0
  while n<len(b):
   v=os.write(fd,b[n:])
   if v<=0:raise OSError('NATIVE_WRITE_NO_PROGRESS')
   n+=v
  os.fsync(fd)
 finally:os.close(fd)
if root.resolve()!=root: raise ValueError('CANONICAL_NATIVE_ROOT')
fd,_,raw=checked(a,262144)
os.close(fd)
value=json.loads(raw)
if platform=='ios':
 p=root/'ios/CaseOps/Info.plist'
 fd,s,old=checked(p,1048576,True)
 try:
  write_new(pathlib.Path(backup),old)
  document=plistlib.loads(old)
  if 'CaseOpsStoreAttestation' in document: raise ValueError('ATTESTATION_ALREADY_PRESENT')
  document['CaseOpsStoreAttestation']=value
  body=plistlib.dumps(document,fmt=plistlib.FMT_XML,sort_keys=False)
  if len(body)>2097152 or frame(s)!=frame(os.fstat(fd)) or frame(s)!=frame(p.lstat()) or p.resolve()!=p:raise ValueError('PLIST_CHANGED_BEFORE_WRITE')
  os.lseek(fd,0,0);n=0
  while n<len(body):
   v=os.write(fd,body[n:])
   if v<=0: raise OSError('PLIST_WRITE_NO_PROGRESS')
   n+=v
  os.ftruncate(fd,len(body));os.fsync(fd)
  if frame(os.fstat(fd))!=frame(p.lstat()) or p.resolve()!=p:raise ValueError('PLIST_CHANGED_AFTER_WRITE')
 finally: os.close(fd)
elif platform=='android':
 p=root/'android/app/src/main/assets/caseops-store-attestation.json'
 parent=root
 for part in ('android','app','src','main','assets'):
  parent=parent/part
  if not parent.exists():os.mkdir(parent,0o700)
  s=parent.lstat()
  if parent.resolve()!=parent or not stat.S_ISDIR(s.st_mode) or stat.S_ISLNK(s.st_mode) or s.st_uid!=os.getuid():raise ValueError('ASSET_PARENT')
 write_new(p,raw)
else: raise ValueError('PLATFORM')
print(json.dumps({'embedded':True,'sha256':hashlib.sha256(raw).hexdigest()}))
`;

const decoded = result => {
  assert.ok(Buffer.isBuffer(result.stdout), 'STORE_TOOL_OUTPUT_REQUIRED');
  try { return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(result.stdout)); }
  catch { throw new Error('STORE_TOOL_JSON_REFUSED'); }
};
export async function inspectDistributionArtifact({ platform, artifact, output, expected, tools, signingCopy, deadline }, invoke) {
  const readInput = (file, options) => rawReadInput(file, { ...options, deadline });
  const privateDirectory = (file, options) => rawPrivateDirectory(file, { ...options, deadline });
  const writePrivate = (file, bytes) => rawWritePrivate(file, bytes, { deadline });
  checkDeadline(deadline);
  privateDirectory(output);
  const retained = readInput(artifact, { maxBytes: ARTIFACT_LIMITS.compressed });
  const work = path.join(output, 'artifact-inspection'); privateDirectory(work, { existing: false });
  let attestation, app, nativeLibraries = [];
  const inventory = inspectStoreZip(retained.bytes, (row, bytes) => {
    checkDeadline(deadline);
    if (platform === 'ios' && row.name === 'Payload/') return;
    if (platform === 'ios' && row.name.startsWith('Payload/')) {
      const candidate = row.name.split('/').slice(0, 2).join('/');
      assert.match(candidate, /^Payload\/[A-Za-z0-9._ -]+\.app$/, 'STORE_ONE_IOS_APP_REQUIRED');
      if (app) assert.equal(candidate, app, 'STORE_ONE_IOS_APP_REQUIRED'); else app = candidate;
      const destination = path.join(work, row.name);
      if (row.name.endsWith('/')) { fs.mkdirSync(destination, { recursive: true, mode: 0o700 }); return; }
      fs.mkdirSync(path.dirname(destination), { recursive: true, mode: 0o700 });
      writePrivate(destination, bytes); if (row.mode & 0o111) fs.chmodSync(destination, 0o700);
    }
    if (platform === 'android') {
      if (row.name === 'base/assets/caseops-store-attestation.json') {
        try { attestation = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); }
        catch { throw new Error('STORE_ATTESTATION_JSON_REFUSED'); }
      }
      const match = /^base\/lib\/([^/]+)\/[^/]+\.so$/.exec(row.name);
      if (match) nativeLibraries.push({ name: row.name, abi: match[1], loadAlignments: elfLoadAlignments(bytes) });
    }
  });
  const call = (role, args, input) => invoke({ role: 'inspect', tool: role, args, cwd: output, timeoutMs: 30000, capture: true, input });
  const plist = async bytes => decoded(await call('python', ['-c', PLIST_JSON_PROGRAM], bytes));
  let observation;
  if (platform === 'ios') {
    assert.ok(app, 'STORE_IOS_PAYLOAD_REQUIRED');
    app = path.join(work, app);
    const signature = await call('codesign', ['--verify', '--deep', '--strict', '--verbose=2', app]);
    const info = await plist(readInput(path.join(app, 'Info.plist')).bytes);
    assert.match(info.CFBundleExecutable || '', /^[A-Za-z0-9._-]+$/, 'STORE_EXECUTABLE_NAME_REFUSED');
    const entitlements = await plist((await call('codesign', ['--display', '--entitlements', '-', '--xml', app])).stdout);
    const profile = await plist((await call('security', ['cms', '-D'], readInput(path.join(app, 'embedded.mobileprovision'), { maxBytes: 1048576 }).bytes)).stdout);
    const prefix = path.join(work, 'signing-certificate-');
    await call('codesign', ['--display', '--extract-certificates', prefix, app]);
    const certificate = certificateIdentity(readInput(prefix + '0', { maxBytes: 16384 }).bytes, expected.now);
    const architectures = (await call('xcrun', ['lipo', '-archs', path.join(app, info.CFBundleExecutable)])).stdout.toString().trim().split(/\s+/).sort();
    observation = { strictSignatureExit: signature.exitCode, info, entitlements, profile, certificate, architectures,
      profileCertificateSha256: profile.DeveloperCertificates.map(c => new X509Certificate(Buffer.from(c.base64, 'base64')).fingerprint256.replaceAll(':', '').toLowerCase()),
      attestation: info.CaseOpsStoreAttestation };
    verifyIosDistribution(observation, expected);
  } else {
    const bundle = async args => call('java', ['-jar', tools.bundletool.path, ...args]);
    const validation = await bundle(['validate', '--bundle=' + artifact]);
    const signature = await call('jarsigner', ['-verify', '-strict', '-keystore', signingCopy,
      '-storepass:env', 'CASEOPS_UPLOAD_STORE_PASSWORD', artifact, expected.signing.uploadKeyAlias]);
    assert.match(signature.stdout.toString(), /jar verified\./, 'STORE_JAR_VERIFICATION_OUTPUT_REQUIRED');
    const verifierSource = readInput(tools.jarVerifier.path, { sha256: tools.jarVerifier.sha256, maxBytes: 32768 }).bytes;
    const verifiedJar = decoded(await invoke({ role: 'inspect', tool: 'java',
      args: ['--source', '17', '@CASEOPS_VERIFIED_SOURCE_FD@', artifact, expected.signing.uploadCertificateSha256],
      sourceInput: verifierSource, cwd: output, timeoutMs: 30000, capture: true }));
    assert.equal(verifiedJar.signerCount, 1, 'STORE_AAB_ONE_SIGNER_REQUIRED');
    const certificate = certificateIdentity(Buffer.from(verifiedJar.certificateBase64, 'base64'), expected.now);
    const field = async xpath => (await bundle(['dump', 'manifest', '--bundle=' + artifact, '--module=base', '--xpath=' + xpath])).stdout.toString().trim();
    const boolean = (value, fallback) => { assert.ok(['true', 'false', ''].includes(value), 'STORE_MANIFEST_BOOLEAN_REFUSED'); return value ? value === 'true' : fallback; };
    const integer = value => { assert.match(value, /^[1-9][0-9]{0,9}$/, 'STORE_MANIFEST_INTEGER_REFUSED'); return Number(value); };
    observation = { bundletoolValidationExit: validation.exitCode, jarSignatureExit: signature.exitCode,
      signerCount: verifiedJar.signerCount, certificate, packageName: await field('/manifest/@package'),
      versionName: await field('/manifest/@android:versionName'), versionCode: integer(await field('/manifest/@android:versionCode')),
      targetSdk: integer(await field('/manifest/uses-sdk/@android:targetSdkVersion')),
      privacyPolicy: { url: await field("/manifest/application/meta-data[@android:name='ai.caseops.mobile.PRIVACY_POLICY_URL']/@android:value"),
        version: await field("/manifest/application/meta-data[@android:name='ai.caseops.mobile.PRIVACY_POLICY_VERSION']/@android:value"),
        sha256: await field("/manifest/application/meta-data[@android:name='ai.caseops.mobile.PRIVACY_POLICY_SHA256']/@android:value") },
      debuggable: boolean(await field('/manifest/application/@android:debuggable'), false),
      cleartextPermitted: boolean(await field('/manifest/application/@android:usesCleartextTraffic'), false),
      allowBackup: boolean(await field('/manifest/application/@android:allowBackup'), true),
      networkSecurityConfigurationAbsent: (await field('/manifest/application/@android:networkSecurityConfig')) === '', nativeLibraries, attestation };
    verifyAndroidDistribution(observation, expected);
  }
  assert.equal(readInput(artifact, { maxBytes: ARTIFACT_LIMITS.compressed }).sha256, retained.sha256, 'STORE_ARTIFACT_CHANGED_DURING_INSPECTION');
  return { artifactSha256: retained.sha256, artifactBytes: retained.bytes.length, zipEntryCount: inventory.entries.length,
    expandedBytes: inventory.expandedBytes, embedded: verifyEmbeddedAttestation(observation.attestation, expected.attestation),
    platform, distributionSigningVerified: true, observedCertificate: observation.certificate };
}
