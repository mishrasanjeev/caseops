import { execFileSync } from 'node:child_process';
import { createHash, randomBytes } from 'node:crypto';
import path from 'node:path';
import { verifiedFile } from '../../apps/mobile/e2e/evidence.mjs';
import { androidLocalProfile } from '../../apps/mobile/e2e/android-local-profile.mjs';

export const OBSERVER_SOURCE_INPUTS = Object.freeze(['scripts/mobile/android-qa-observer.mjs','scripts/mobile/android-observer-manifest.py','apps/mobile/plugins/qa-observer.cjs','apps/mobile/plugins/with-local-acceptance.cjs','apps/mobile/qa-observer/QaPrivacyReader.java','apps/mobile/qa-observer/QaPrivacyService.java','apps/mobile/qa-observer/QaLifecycleWitness.java','apps/mobile/qa-observer/sidecar/AndroidManifest.xml','apps/mobile/qa-observer/sidecar/ObserverInstrumentation.java']);
export const QA_APP = 'ai.caseops.mobile.dev.localacceptance';
export const QA_OBSERVER_APP = 'ai.caseops.qa.privacyobserver';
export const QA_OBSERVER_DOMAIN = 'qa-main-preserved-observer-running';
const sha = b => createHash('sha256').update(b).digest('hex');
const need = (ok, code) => { if (!ok) throw new Error(code); };
const exact = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const quote = v => `'${String(v).replaceAll("'", "'\"'\"'")}'`;
const text = b => new TextDecoder('utf-8', { fatal: true }).decode(b);
const has = (o, k) => Object.hasOwn(o, k);
const scalar = (o, k, fallback = 0) => has(o, k) ? o[k] : fallback;

// AOSP android16-release instrumentation_data.proto and Instrument.ProtoStatusReporter.
// ProtoOutputStream omits scalar zero: only the typed sequence/result/status
// fields below admit that precise protobuf default. No logcat/text reporter.
function varint(b, state) {
  let n = 0n, shift = 0n;
  for (let i = 0; i < 10; i++) {
    need(state.i < b.length, 'QA_OBSERVER_PROTO_TRUNCATED'); const v = b[state.i++];
    n |= BigInt(v & 127) << shift;
    if (!(v & 128)) { need(n <= BigInt(Number.MAX_SAFE_INTEGER) && (i === 0 || v !== 0), 'QA_OBSERVER_PROTO_INTEGER'); return Number(n); }
    shift += 7n;
  }
  throw new Error('QA_OBSERVER_PROTO_INTEGER');
}
function fields(b, allowed, repeat = []) {
  const result = Object.create(null), state = { i: 0 };
  while (state.i < b.length) {
    const tag = varint(b, state), key = tag >>> 3, wire = tag & 7;
    need(has(allowed, key) && allowed[key] === wire, 'QA_OBSERVER_PROTO_FIELD');
    let value;
    if (wire === 0) value = varint(b, state);
    else { const size = varint(b, state); need(size <= b.length - state.i, 'QA_OBSERVER_PROTO_TRUNCATED'); value = b.subarray(state.i, state.i + size); state.i += size; }
    if (repeat.includes(key)) (result[key] ??= []).push(value);
    else { need(!has(result, key), 'QA_OBSERVER_PROTO_DUPLICATE'); result[key] = value; }
  }
  return result;
}
function bundle(raw, expected, optional = false) {
  const parsed = fields(raw, { 1: 2 }, [1]), out = Object.create(null);
  for (const value of parsed[1] ?? []) {
    const e = fields(value, { 1: 2, 2: 2, 3: 0, 8: 2 }); need(e[1], 'QA_OBSERVER_PROTO_KEY'); const key = text(e[1]);
    need(has(expected, key) && !has(out, key), 'QA_OBSERVER_PROTO_BUNDLE_KEY');
    const present = [2, 3, 8].filter(k => has(e, k));
    if (!present.length) { need(expected[key] === 'integer', 'QA_OBSERVER_PROTO_MISSING_VALUE'); out[key] = 0; }
    else { need(present.length === 1, 'QA_OBSERVER_PROTO_VALUE_DUPLICATE'); const k = present[0];
      need(k === ({ string: 2, integer: 3, bytes: 8 })[expected[key]], 'QA_OBSERVER_PROTO_VALUE_TYPE');
      out[key] = k === 2 ? text(e[k]) : k === 3 ? (e[k] & 1 ? -(e[k] + 1) / 2 : e[k] / 2) : e[k]; }
  }
  need(optional || Object.keys(out).length === Object.keys(expected).length, 'QA_OBSERVER_PROTO_BUNDLE_INCOMPLETE'); return out;
}
export function decodeObserverInstrumentation(raw, id) {
  need(Buffer.isBuffer(raw) && raw.length > 0 && raw.length <= 67108864, 'QA_OBSERVER_WIRE_BOUND');
  const session = fields(raw, { 1: 2, 2: 2 }, [1]); need(session[2] && (session[1]?.length ?? 0) <= 2048, 'QA_OBSERVER_PROTO_SESSION');
  const end = fields(session[2], { 1: 0, 2: 2, 3: 0, 4: 2 });
  if (scalar(end,1) === 0 && scalar(end,3) !== 0 && end[4]) {
    const failure=bundle(end[4],{'caseops.complete':'string','caseops.error':'string','caseops.cleanupFailure':'string','caseops.packageStoppedBefore':'string','caseops.packageStoppedAfter':'string','caseops.leaseClosed':'string','caseops.packetSha256':'string','caseops.chunkCount':'integer','caseops.requestId':'string','caseops.sidecarIdentityBytes':'integer'},true);
    need(failure['caseops.complete']==='false'&&/^QA_(?:OBSERVER|SIDECAR)_[A-Z0-9_]+$/.test(failure['caseops.error']??''),'QA_OBSERVER_NATIVE_FAILURE_SCHEMA');
    const primary=new Error(failure['caseops.error']);
    if(failure['caseops.cleanupFailure']!==undefined){need(/^QA_SIDECAR_[A-Z0-9_]+$/.test(failure['caseops.cleanupFailure']),'QA_OBSERVER_NATIVE_FAILURE_SCHEMA');throw new AggregateError([primary,new Error(failure['caseops.cleanupFailure'])],'QA_OBSERVER_NATIVE_BODY_AND_CLEANUP_FAILED');}throw primary;
  }
  need(session[1]?.length>0,'QA_OBSERVER_PROTO_SESSION');
  const chunks = [];
  for (const status of session[1]) {
    const s = fields(status, { 3: 0, 4: 2 }); need(scalar(s, 3) === 0 && s[4], 'QA_OBSERVER_PROTO_STATUS');
    const b = bundle(s[4], { 'caseops.requestId': 'string', 'caseops.sequence': 'integer', 'caseops.chunk': 'bytes' });
    need(b['caseops.requestId'] === id && b['caseops.sequence'] === chunks.length && b['caseops.chunk'].length > 0 && b['caseops.chunk'].length <= 32768, 'QA_OBSERVER_CHUNK_IDENTITY'); chunks.push(b['caseops.chunk']);
  }
  const s = fields(session[2], { 1: 0, 2: 2, 3: 0, 4: 2 }); need(scalar(s, 1) === 0 && scalar(s, 3) === 0 && !s[2] && s[4], 'QA_OBSERVER_PROTO_FINISHED');
  const final = bundle(s[4], { 'caseops.requestId': 'string', 'caseops.packetSha256': 'string', 'caseops.chunkCount': 'integer', 'caseops.complete': 'string', 'caseops.leaseClosed': 'string', 'caseops.packageStoppedBefore': 'string', 'caseops.packageStoppedAfter': 'string', 'caseops.sidecarIdentityBytes': 'integer' });
  need(final['caseops.requestId'] === id && final['caseops.chunkCount'] === chunks.length && final['caseops.complete'] === 'true' && final['caseops.leaseClosed'] === 'true' && /^[a-f0-9]{64}$/.test(final['caseops.packetSha256']) && ['true', 'false'].includes(final['caseops.packageStoppedBefore']) && ['true', 'false'].includes(final['caseops.packageStoppedAfter']), 'QA_OBSERVER_FINAL_RECEIPT');
  need(Number.isSafeInteger(final['caseops.sidecarIdentityBytes']) && final['caseops.sidecarIdentityBytes']>=0 && final['caseops.sidecarIdentityBytes']<=32768, 'QA_OBSERVER_SIDECAR_IDENTITY_BOUND');
  const packet = Buffer.concat(chunks);
  try { need(sha(packet) === final['caseops.packetSha256'], 'QA_OBSERVER_PACKET_HASH');
    return { packet, packageStoppedBefore: final['caseops.packageStoppedBefore'] === 'true', packageStoppedAfter: final['caseops.packageStoppedAfter'] === 'true', leaseClosed: true, sidecarIdentityBytes: final['caseops.sidecarIdentityBytes'] };
  } catch (error) { packet.fill(0); throw error; }
}
function frame(value, uid, kind) {
  need(Array.isArray(value) && value.length === 9 && value.every(v => typeof v === 'string' && /^-?\d+$/.test(v)), 'QA_OBSERVER_METADATA_FRAME');
  const mode = Number(value[2]); need(Number.isSafeInteger(mode) && (mode & 61440) === (kind === 'directory' ? 16384 : 32768) && Number(value[3]) === uid && BigInt(value[6]) >= 0n, 'QA_OBSERVER_METADATA_OWNER_TYPE');
  if (kind === 'file') need(value[5] === '1', 'QA_OBSERVER_METADATA_SINGLE_LINK');
}
function namespace(rows, target, owned, uid) {
  need(Array.isArray(rows) && rows.length > 0 && rows.length <= 64, 'QA_OBSERVER_NAMESPACE'); let parent = path.posix.dirname(target);
  for (const row of rows) {
    need(row.path === parent && row.owned === (parent === owned || parent.startsWith(`${owned}/`)), 'QA_OBSERVER_NAMESPACE_PATH');
    if (row.frame === null) need(row.owned && parent !== owned, 'QA_OBSERVER_NAMESPACE_ABSENCE');
    else if (row.owned) frame(row.frame, uid, 'directory');
    else need(Array.isArray(row.frame) && row.frame.length === 5 && row.frame.every(v => typeof v === 'string' && /^\d+$/.test(v)) && (Number(row.frame[2]) & 61440) === 16384, 'QA_OBSERVER_NAMESPACE_FRAME');
    need(parent !== '/' || row === rows.at(-1), 'QA_OBSERVER_NAMESPACE_ROOT'); parent = path.posix.dirname(parent);
  }
  need(rows.at(-1).path === '/', 'QA_OBSERVER_NAMESPACE_ROOT');
}
export function validateObserverPacket(packet, request, descriptor, consume) {
  need(packet.length >= 12 && packet.subarray(0, 8).equals(Buffer.from('CPQAOBS1')), 'QA_OBSERVER_PACKET_MAGIC');
  const size = packet.readUInt32BE(8); need(size > 0 && size <= 16777216 && size <= packet.length - 12, 'QA_OBSERVER_HEADER_BOUND');
  let m; try { m = JSON.parse(text(packet.subarray(12, 12 + size))); } catch { throw new Error('QA_OBSERVER_HEADER_JSON'); }
  for (const k of ['requestId', 'operation', 'sourceSha', 'targetApkSha256', 'observerApkSha256', 'signerSha256']) need(m[k] === request[k], 'QA_OBSERVER_HEADER_IDENTITY');
  need(m.schemaVersion === 1 && m.kind === 'caseops-qa-observer-composite' && m.complete === true && m.packageUid === descriptor.packageUid && m.callerUid === descriptor.observerUid && Number.isSafeInteger(m.callerPid) && m.callerPid > 0 && Number.isSafeInteger(m.observerPid) && m.observerPid > 0 && m.observerPid !== m.callerPid && m.observerProcess === `${QA_APP}:privacyobserver` && m.applicationClass === 'android.app.Application', 'QA_OBSERVER_ACTUAL_ACCESS_IDENTITY');
  need(exact(m.mainBefore, request.mainExpected) && exact(m.mainAfter, request.mainExpected) && exact(m.mainExpected, request.mainExpected) && m.lifecycleSequenceBefore === m.lifecycleSequenceAfter && Number.isSafeInteger(m.lifecycleSequenceBefore) && m.lifecycleSequenceBefore >= 0 && Number.isSafeInteger(m.sidecarStartElapsed) && m.sidecarStartElapsed >= 0 && Number.isSafeInteger(m.lastMainCreatedElapsed) && (request.mainExpected.present || m.lastMainCreatedElapsed < m.sidecarStartElapsed), 'QA_OBSERVER_MAIN_LIFECYCLE_CHANGED');
  need(m.providerOriginalsRead === false && m.deviceFilesDeleted === false && m.appRestarted === false && m.fullPackageForceStoppedStateCertified === false && Number.isSafeInteger(m.fdsOpened) && m.fdsOpened === m.fdsClosed, 'QA_OBSERVER_SIDE_EFFECT_OR_CLOSURE');
  const camera = request.operation === 'camera-snapshot';
  need(Number.isSafeInteger(m.entries) && m.entries > 0 && m.entries <= (camera ? 512 : 8192) && Number.isSafeInteger(m.privateBytesRead) && m.privateBytesRead >= 0 && Number.isSafeInteger(m.identityBytesRead) && m.identityBytesRead >= 0 && m.privateBytesRead + m.identityBytesRead <= 67108864, 'QA_OBSERVER_SCAN_BOUND');
  need(m.appData?.path === `/data/user/0/${QA_APP}`, 'QA_OBSERVER_DATA_ROOT'); frame(m.appData.frame, m.packageUid, 'directory');
  const allowedRoots = request.operation === 'attest' ? [] : camera ? [['camera', `${m.appData.path}/cache/ImagePicker`, 1]] : [['app-data', m.appData.path, 16], ['external-app-data', `/storage/emulated/0/Android/data/${QA_APP}`, 16]];
  need(Array.isArray(m.inventories) && m.inventories.length === allowedRoots.length && Array.isArray(m.records), 'QA_OBSERVER_COMPLETE_ROOTS');
  if (m.externalAppData !== null) { need(m.externalAppData?.path === `/storage/emulated/0/Android/data/${QA_APP}`, 'QA_OBSERVER_EXTERNAL_ROOT'); frame(m.externalAppData.frame, m.packageUid, 'directory'); }
  const union = new Set();
  for (let i = 0; i < allowedRoots.length; i++) {
    const [name, root, depth] = allowedRoots[i], inv = m.inventories[i];
    need(inv.name === name && inv.root === root && Array.isArray(inv.initial) && exact(inv.initial, inv.final) && inv.initial.length === new Set(inv.initial).size && exact(inv.initial, [...inv.initial].sort()), 'QA_OBSERVER_COMPLETE_UNIQUE_INVENTORY');
    if (name === 'app-data') need(inv.initial.includes(root), 'QA_OBSERVER_ROOT_PRESENT');
    else need(inv.initial.length === 0 || inv.initial.includes(root), 'QA_OBSERVER_ROOT_PRESENT');
    namespace(inv.namespaceBefore, root, m.appData.path, m.packageUid); need(exact(inv.namespaceBefore, inv.namespaceAfter), 'QA_OBSERVER_NAMESPACE_CHANGED');
    for (const file of inv.initial) { need(typeof file === 'string' && (file === root || file.startsWith(`${root}/`)) && path.posix.normalize(file) === file && !/[\x00-\x1f\x7f\\]/.test(file) && (file === root || file.slice(root.length + 1).split('/').length <= depth) && !union.has(file), 'QA_OBSERVER_PATH_SCOPE'); union.add(file); }
  }
  for(const inv of m.inventories)for(const file of inv.initial)need(file===inv.root||union.has(path.posix.dirname(file)), 'QA_OBSERVER_PARENT_MEMBERSHIP');
  need(m.records.length === union.size && new Set(m.records.map(r => r.path)).size === union.size && m.records.every(r => union.has(r.path)), 'QA_OBSERVER_RECORD_UNION');
  let offset = 12 + size, bodyIndex = 0, privateBytes = 0;
  const files = [], identities = new Set();
  for (const row of m.records) {
    need(['file', 'directory'].includes(row.kind) && row.canonical === row.path, 'QA_OBSERVER_RECORD_KIND'); frame(row.before, m.packageUid, row.kind); need(exact(row.before, row.after), 'QA_OBSERVER_FINAL_METADATA'); const inode = `${row.before[0]}:${row.before[1]}`;need(!identities.has(inode),'QA_OBSERVER_ALIASED_INODE');identities.add(inode);
    if (row.kind === 'directory') { need(row.opened === null, 'QA_OBSERVER_DIRECTORY_BODY'); continue; }
    const f = row.opened, n = Number(row.before[6]); need(Number.isSafeInteger(n) && n >= 0 && n <= (camera ? 52428800 : 8388608) && f?.bodyIndex === bodyIndex++ && f.length === n && f.fdClosed === true && ['pathBefore', 'fdBefore', 'fdAfter', 'pathAfter'].every(k => exact(f[k], row.before)), 'QA_OBSERVER_FD_FRAME');
    const root = m.inventories.find(inv => inv.initial.includes(row.path)).root; namespace(f.namespaceBefore, row.path, root, m.packageUid); need(exact(f.namespaceBefore, f.namespaceAfter), 'QA_OBSERVER_FD_NAMESPACE');
    need(offset + n <= packet.length, 'QA_OBSERVER_BODY_TRUNCATED'); const body = packet.subarray(offset, offset + n); offset += n; privateBytes += n;
    if (camera) need(/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\.(?:jpg|jpeg|png)$/i.test(path.posix.basename(row.path)), 'QA_OBSERVER_CAMERA_NAME');
    files.push({ path: row.path, bytes: body, sha256: sha(body), sizeBytes: n });
  }
  need(offset === packet.length && privateBytes === m.privateBytesRead && files.length <= (camera ? 128 : 4096), 'QA_OBSERVER_BODY_RECONCILIATION');
  return consume({ metadata: m, files });
}
export function observerConfiguration(ref, udid) {
  need(ref && typeof ref.path === 'string' && /^[a-f0-9]{64}$/.test(ref.sha256), 'QA_OBSERVER_PINNED_INSTALLATION_REQUIRED');
  let d; try { d = JSON.parse(verifiedFile(ref.path, ref.sha256, 1048576)); } catch { throw new Error('QA_OBSERVER_INSTALLATION_INVALID'); }
  need(d.schemaVersion === 1 && d.kind === 'android-qa-observer-installation' && d.domain === QA_OBSERVER_DOMAIN && d.udid === udid && d.appId === QA_APP && d.observerAppId === QA_OBSERVER_APP && d.nonDebuggable === true && d.sameSignerVerified === true && d.productionComponent === false && d.allowQaFixtureUnstop === true && d.fullPackageForceStoppedStateCertified === false, 'QA_OBSERVER_INSTALLATION_SCOPE');
  for (const key of ['targetApkSha256', 'observerApkSha256', 'signerSha256']) need(/^[a-f0-9]{64}$/.test(d[key]), 'QA_OBSERVER_INSTALLATION_HASH');
  need(/^[a-f0-9]{40}$/.test(d.sourceSha) && Number.isSafeInteger(d.packageUid) && d.packageUid >= 10000 && d.packageUid < 100000 && Number.isSafeInteger(d.observerUid) && d.observerUid >= 10000 && d.observerUid < 100000 && d.packageUid !== d.observerUid, 'QA_OBSERVER_INSTALLATION_UID'); return d;
}
export function observeQaPrivacy({ udid, androidTransportMode, environment = process.env, privacyObserver, command = execFileSync, deadline = Date.now() + 30000, budget = { bytes: 0, limit: 67108864 }, operation, requireFullPackageForceStopped = false }, consume = value => value) {
  need(requireFullPackageForceStopped === false, 'QA_OBSERVER_FULL_FORCE_STOPPED_UNPROVED');
  const profile = androidLocalProfile(udid, 'QA_OBSERVER_DEVICE_REQUIRED', androidTransportMode ?? environment.CASEOPS_MOBILE_ANDROID_TRANSPORT_MODE);
  need(profile.deviceKind === 'physical' && profile.transportMode === 'usb-reverse' && environment.ADB_SERVER_SOCKET === `tcp:127.0.0.1:${profile.adbPort}`, 'QA_OBSERVER_PHYSICAL_TRANSPORT_REQUIRED');
  const d = observerConfiguration(privacyObserver, udid), id = randomBytes(16).toString('hex');
  need(['attest', 'files-snapshot', 'camera-snapshot'].includes(operation), 'QA_OBSERVER_OPERATION');
  const env = Object.fromEntries(['PATH', 'HOME', 'USERPROFILE', 'SYSTEMROOT', 'ANDROID_USER_HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'ADB_SERVER_SOCKET', 'ANDROID_ADB_SERVER_PORT'].filter(k => typeof environment[k] === 'string').map(k => [k, environment[k]]));
  function run(args, binary = false) {
    need(Date.now() < deadline && budget.bytes < budget.limit, 'QA_OBSERVER_OBSERVATION_BOUND');
    try { const result = command('adb', ['-s', udid, ...args], { shell: false, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'], env, encoding: binary ? undefined : 'utf8', timeout: Math.min(30000, deadline - Date.now()), maxBuffer: Math.min(binary ? 67108864 : 1048576, budget.limit - budget.bytes) });
      const b = Buffer.isBuffer(result) ? result : Buffer.from(result); budget.bytes += b.length; need(budget.bytes <= budget.limit, 'QA_OBSERVER_OBSERVATION_BOUND'); return binary ? b : text(b).trim();
    } catch (error) { const bufs = [error?.stdout, error?.stderr].filter(v => typeof v === 'string' || Buffer.isBuffer(v)).map(v => Buffer.isBuffer(v) ? v : Buffer.from(v)); for (const b of bufs) { budget.bytes += b.length; b.fill(0); } const missing = error?.status === 1 && !error.signal && !error.code && bufs.every(b => b.length === 0); const safe = new Error('QA_OBSERVER_COMMAND_FAILED'); safe.emptyExitOne = missing; throw safe; }
  }
  const packageUid = pkg => { const raw = run(['shell', 'cmd', 'package', 'list', 'packages', '-U', pkg]); const matched = new RegExp(`^package:${pkg.replaceAll('.', '\\.')} uid:(\\d+)$`).exec(raw); need(matched, 'QA_OBSERVER_PACKAGE_UID'); return Number(matched[1]); };
  const installed = () => {
    need(packageUid(QA_APP) === d.packageUid && packageUid(QA_OBSERVER_APP) === d.observerUid, 'QA_OBSERVER_INSTALLED_UID');
    for (const [pkg, expected] of [[QA_APP, d.targetApkSha256], [QA_OBSERVER_APP, d.observerApkSha256]]) { const p = run(['shell', 'pm', 'path', pkg]); const match = /^package:(\/data\/app\/[A-Za-z0-9_~+=./-]+\/base\.apk)$/.exec(p); need(match && path.posix.normalize(match[1]) === match[1], 'QA_OBSERVER_INSTALLED_APK_PATH'); const actual = run(['shell', 'sha256sum', match[1]]); need(actual === `${expected}  ${match[1]}`, 'QA_OBSERVER_INSTALLED_APK_HASH'); }
  };
  const main = () => {
    let pid; try { pid = run(['shell', 'pidof', QA_APP]); } catch (error) { if (error.emptyExitOne) return { present: false }; throw error; }
    need(/^[1-9]\d*$/.test(pid), 'QA_OBSERVER_MAIN_PID'); const raw = run(['shell', 'cat', `/proc/${pid}/stat`]); need(raw.length <= 4096 && raw.startsWith(`${pid} (`), 'QA_OBSERVER_MAIN_PROC'); const tail = raw.slice(raw.lastIndexOf(')') + 2).split(/ +/); need(tail.length > 19 && /^\d+$/.test(tail[19]), 'QA_OBSERVER_MAIN_BIRTH'); return { present: true, pid: Number(pid), uid: d.packageUid, startTicks: tail[19] };
  };
  installed(); const beforeMain = main(), request = { schemaVersion: 1, requestId: id, operation, sourceSha: d.sourceSha, targetApkSha256: d.targetApkSha256, observerApkSha256: d.observerApkSha256, signerSha256: d.signerSha256, milliseconds: deadline - Date.now(), domain: QA_OBSERVER_DOMAIN, allowQaFixtureUnstop: d.allowQaFixtureUnstop, mainExpected: beforeMain };
  need(request.milliseconds > 0 && request.milliseconds <= 30000, 'QA_OBSERVER_OBSERVATION_BOUND');
  let raw, packet;
  try {
    raw = run(['shell', '-T', ['am', 'instrument', '-m', '-w', '--no-test-api-access', '--no-logcat', '--always-check-signature', '--user', '0', '-e', 'caseopsRequest', JSON.stringify(request), `${QA_OBSERVER_APP}/ai.caseops.qa.privacyobserver.ObserverInstrumentation`].map(quote).join(' ')], true);
    const result = decodeObserverInstrumentation(raw, id); packet = result.packet; need(!result.packageStoppedBefore || d.allowQaFixtureUnstop, 'QA_OBSERVER_FIXTURE_UNSTOP_NOT_AUTHORIZED');
    const output = validateObserverPacket(packet, request, d, value => { budget.bytes += value.metadata.identityBytesRead + result.sidecarIdentityBytes; need(budget.bytes <= budget.limit, 'QA_OBSERVER_OBSERVATION_BOUND'); return consume({ ...value, access: 'qa-observer-service', domain: QA_OBSERVER_DOMAIN, packageStoppedBefore: result.packageStoppedBefore, packageStoppedAfter: result.packageStoppedAfter, deliberateQaFixtureUnstop: result.packageStoppedBefore && !result.packageStoppedAfter, fullPackageForceStoppedStateCertified: false, leaseClosed: true }); });
    need(exact(main(), beforeMain), 'QA_OBSERVER_MAIN_CHANGED_AFTER_COMMAND'); installed(); need(Date.now() < deadline, 'QA_OBSERVER_OBSERVATION_BOUND'); return output;
  } finally { raw?.fill(0); packet?.fill(0); }
}

export async function withObserverAppiumWitness(driver, operation) {
  const sessionId = driver?.sessionId;
  need(typeof sessionId === 'string' && /^[A-Za-z0-9-]{1,200}$/.test(sessionId), 'QA_OBSERVER_LIVE_APPIUM_SESSION_REQUIRED');
  const facts = async () => {
    need(driver.sessionId === sessionId, 'QA_OBSERVER_APPIUM_SESSION_CHANGED');
    const appPackage = await driver.getCurrentPackage(), activity = await driver.getCurrentActivity();
    need(typeof appPackage === 'string' && /^[A-Za-z][A-Za-z0-9_.]{0,199}$/.test(appPackage) && typeof activity === 'string' && /^[A-Za-z.$_][A-Za-z0-9.$_]{0,399}$/.test(activity), 'QA_OBSERVER_ACTIVITY_FACTS_REQUIRED');
    return { sessionId, appPackage, activity };
  };
  const before = await facts(); let value, primary, after, cleanup;
  try { value = await operation(); } catch (error) { primary = error; }
  try { after = await facts(); need(exact(before, after), 'QA_OBSERVER_ACTIVITY_OR_APPIUM_CHANGED'); } catch (error) { cleanup = error; }
  if (primary && cleanup) throw new AggregateError([primary, cleanup], 'QA_OBSERVER_BODY_AND_APPIUM_PROOF_FAILED');
  if (primary) throw primary; if (cleanup) throw cleanup;
  return { value, appiumWitness: { schemaVersion: 1, kind: 'actual-observer-appium-coexistence', before, after, complete: true, taskIdentityClaimed: false } };
}
