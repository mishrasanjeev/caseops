import { QA_APP, QA_OBSERVER_APP, QA_OBSERVER_DOMAIN } from './android-qa-observer.mjs';
// Synthetic source-test identities only. No device command or installer.
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { OBSERVER_IDENTITY } from './android-files-privacy.mjs';
export function bindObserverTestIdentity(record, directory, sourceSha) {
  const d={schemaVersion:1,kind:'android-qa-observer-installation',udid:record.udid,appId:record.appId,observerAppId:'ai.caseops.qa.privacyobserver',domain:'qa-main-preserved-observer-running',sourceSha,targetApkSha256:record.binaryHash,observerApkSha256:'a'.repeat(64),signerSha256:'b'.repeat(64),packageUid:record.packageUid,observerUid:record.packageUid+1,nonDebuggable:true,sameSignerVerified:true,productionComponent:false,allowQaFixtureUnstop:true,fullPackageForceStoppedStateCertified:false};
  const p=path.join(directory,'observer-installation.json'),raw=Buffer.from(JSON.stringify(d));fs.writeFileSync(p,raw,{flag:'wx',mode:0o600});const ref={path:p,sha256:createHash('sha256').update(raw).digest('hex')};
  Object.assign(record,{access:'qa-observer-service',observerInstallationEvidence:ref,observationDomain:d.domain,fullPackageForceStoppedStateCertified:false},Object.fromEntries(['observerAppId','observerUid','targetApkSha256','observerApkSha256','sourceSha','signerSha256'].map(k=>[k,d[k]])));delete record.runAsUid;
  if(record.androidLayout)record.androidLayout.physicalIdentity=Object.fromEntries(['packageUid',...OBSERVER_IDENTITY].map(k=>[k,record[k]]));
  return ref;
}

const hash=v=>createHash('sha256').update(v).digest('hex');
export const descriptor = { schemaVersion: 1, kind: 'android-qa-observer-installation', udid: 'qa-serial-01', appId: QA_APP, observerAppId: QA_OBSERVER_APP, domain: QA_OBSERVER_DOMAIN, sourceSha: 'a'.repeat(40), targetApkSha256: 'b'.repeat(64), observerApkSha256: 'c'.repeat(64), signerSha256: 'd'.repeat(64), packageUid: 10123, observerUid: 10124, nonDebuggable: true, sameSignerVerified: true, productionComponent: false, allowQaFixtureUnstop: true, fullPackageForceStoppedStateCertified: false };
export const request = { schemaVersion: 1, requestId: 'e'.repeat(32), operation: 'attest', sourceSha: descriptor.sourceSha, targetApkSha256: descriptor.targetApkSha256, observerApkSha256: descriptor.observerApkSha256, signerSha256: descriptor.signerSha256, mainExpected: { present: false } };
const dir = ['1', '2', '16832', '10123', '10123', '1', '0', '1', '1'];
const ns = (target, root) => { const out = []; for (let p = path.posix.dirname(target); ; p = path.posix.dirname(p)) { const owned = p === root || p.startsWith(root + '/'); out.push({ path: p, owned, frame: owned ? dir : dir.slice(0, 5) }); if (p === '/') return out; } };
export function packet(req = request, mutate = () => {}, body = Buffer.alloc(0)) {
  const m = { schemaVersion: 1, kind: 'caseops-qa-observer-composite', complete: true, ...Object.fromEntries(['requestId','operation','sourceSha','targetApkSha256','observerApkSha256','signerSha256'].map(k => [k, req[k]])), packageUid: 10123, callerUid: 10124, callerPid: 121, observerPid: 122, observerProcess: QA_APP + ':privacyobserver', applicationClass: 'android.app.Application', mainExpected: req.mainExpected, mainBefore: req.mainExpected, mainAfter: req.mainExpected, lifecycleSequenceBefore: 2, lifecycleSequenceAfter: 2, sidecarStartElapsed: 1000, lastMainCreatedElapsed: -1, fdsOpened: 2, fdsClosed: 2, providerOriginalsRead: false, deviceFilesDeleted: false, appRestarted: false, fullPackageForceStoppedStateCertified: false, entries: 20, privateBytesRead: body.length, identityBytesRead: 100, appData: { path: '/data/user/0/' + QA_APP, frame: dir }, externalAppData: null, inventories: [], records: [] };
  if (req.operation === 'files-snapshot') {
    const root = m.appData.path, file = root + '/cache/public-fixture.txt', fileFrame = ['1','3','33152','10123','10123','1',String(body.length),'2','2'];
    m.inventories = [{ name: 'app-data', root, initial: [root, root+'/cache', file], final: [root, root+'/cache', file], namespaceBefore: ns(root, root), namespaceAfter: ns(root, root) }, { name: 'external-app-data', root: '/storage/emulated/0/Android/data/' + QA_APP, initial: [], final: [], namespaceBefore: ns('/storage/emulated/0/Android/data/' + QA_APP, root), namespaceAfter: ns('/storage/emulated/0/Android/data/' + QA_APP, root) }];
    m.records = [{ path: root, kind: 'directory', canonical: root, before: dir, after: dir, opened: null }, { path: file, kind: 'file', canonical: file, before: fileFrame, after: fileFrame, opened: { bodyIndex: 0, length: body.length, fdClosed: true, pathBefore: fileFrame, pathAfter: fileFrame, fdBefore: fileFrame, fdAfter: fileFrame, namespaceBefore: ns(file, root), namespaceAfter: ns(file, root) } }, { path: root+'/cache', kind:'directory',canonical:root+'/cache',before:['1','4',...dir.slice(2)],after:['1','4',...dir.slice(2)],opened:null }];
  }
  mutate(m); const header = Buffer.from(JSON.stringify(m)), prefix = Buffer.alloc(12); prefix.write('CPQAOBS1'); prefix.writeUInt32BE(header.length, 8); return Buffer.concat([prefix, header, body]);
}
function vi(value) { const a = []; do { const b = value % 128; value = Math.floor(value / 128); a.push(b | (value ? 128 : 0)); } while (value); return Buffer.from(a); }
export const f = (key, value) => typeof value === 'number' ? Buffer.concat([vi(key * 8), vi(value)]) : Buffer.concat([vi(key * 8 + 2), vi(value.length), value]);
export function bundle(values) { return Buffer.concat(Object.entries(values).map(([key, value]) => f(1, Buffer.concat([f(1, Buffer.from(key)), ...(typeof value === 'number' ? (value ? [f(3, value * 2)] : []) : [f(Buffer.isBuffer(value) ? 8 : 2, Buffer.isBuffer(value) ? value : Buffer.from(value))])])))); }
export function wire(p, id = request.requestId, mutate = v => v) {
  const status = f(1, f(4, bundle({ 'caseops.requestId': id, 'caseops.sequence': 0, 'caseops.chunk': p })));
  const final = mutate({ 'caseops.requestId': id, 'caseops.packetSha256': hash(p), 'caseops.chunkCount': 1, 'caseops.complete': 'true', 'caseops.leaseClosed': 'true', 'caseops.packageStoppedBefore': 'false', 'caseops.packageStoppedAfter': 'false', 'caseops.sidecarIdentityBytes': 100 });
  return Buffer.concat([status, f(2, f(4, bundle(final)))]);
}
