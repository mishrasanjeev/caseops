import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { QA_APP, QA_OBSERVER_APP, decodeObserverInstrumentation, validateObserverPacket, observeQaPrivacy } from './android-qa-observer.mjs';
const hash = v => createHash('sha256').update(v).digest('hex');
import { descriptor, request, packet, wire, f, bundle } from './qa-observer-test-fixture.mjs';
test('actual protobuf omitted scalar zero is accepted only for the typed fields', () => { const p = packet(), decoded = decodeObserverInstrumentation(wire(p), request.requestId); assert.deepEqual(decoded.packet, p); assert.equal(decoded.leaseClosed, true); });
for (const [name, mutate] of [ ['source mismatch', m => m.sourceSha = 'f'.repeat(40)], ['different real service UID', m => m.packageUid++], ['different caller UID', m => m.callerUid++], ['React Application initialized', m => m.applicationClass = 'ai.caseops.MainApplication'], ['main starts during cold bind', m => m.lastMainCreatedElapsed = 1001], ['main changes inside read', m => m.mainAfter = { present: true, pid: 3 }], ['lifecycle event during read', m => m.lifecycleSequenceAfter++], ['FD remains open', m => m.fdsClosed--], ['claims full stopped flag', m => m.fullPackageForceStoppedStateCertified = true], ['metadata entry bound', m => m.entries = 8193] ]) test(`composite refuses ${name}`, () => { assert.throws(() => validateObserverPacket(packet(request, mutate), request, descriptor, () => true), /^Error: QA_OBSERVER_/); });
test('coupled private bytes reach only the bounded consumer', () => { const req = { ...request, operation: 'files-snapshot' }, body = Buffer.from('synthetic-private-sentinel'); let observed; const p = packet(req, () => {}, body); assert.equal(validateObserverPacket(p, req, descriptor, value => { observed = value.files[0]; return value.metadata.records.length; }), 3); assert.equal(observed.bytes.toString(), body.toString()); });
for (const [name, mutate] of [ ['late inserted member', m => m.inventories[0].final.push(m.appData.path + '/late')], ['duplicate initial member', m => m.inventories[0].initial.push(m.appData.path)], ['file FD replacement', m => m.records[1].opened.fdAfter = ['9', ...m.records[1].before.slice(1)]], ['namespace replacement', m => m.records[1].opened.namespaceAfter = []], ['symlink type', m => m.records[1].before = ['1','3','41471','10123','10123','1','1','2','2']] ]) test(`complete file read refuses ${name}`, () => { const req = { ...request, operation: 'files-snapshot' }; assert.throws(() => validateObserverPacket(packet(req, mutate, Buffer.from('x')), req, descriptor, () => true), /^Error: QA_OBSERVER_/); });
test('protobuf duplicate, truncation, unknown field and wrong hash refuse', () => { const w = wire(packet()); for (const bad of [w.subarray(0, w.length - 1), Buffer.concat([w, f(2, Buffer.alloc(0))]), Buffer.concat([w, f(7, 1)]), wire(packet(), request.requestId, v => ({ ...v, 'caseops.packetSha256': '0'.repeat(64) }))]) assert.throws(() => decodeObserverInstrumentation(bad, request.requestId), /^Error: QA_OBSERVER_/);  const bad=wire(packet(),request.requestId,v=>({...v,'caseops.packetSha256':'0'.repeat(64)})),originalConcat=Buffer.concat;let scratch;
 Buffer.concat=(...args)=>{const value=originalConcat(...args);if(value.subarray(0,8).equals(Buffer.from('CPQAOBS1')))scratch=value;return value;};
 try{assert.throws(()=>decodeObserverInstrumentation(bad,request.requestId),/QA_OBSERVER_PACKET_HASH/);assert.ok(scratch);assert.ok(scratch.every(value=>value===0),'refused assembled private packet must be wiped before throwing');}finally{Buffer.concat=originalConcat;}
});
test('unknown logcat/private string bundle is refused without reflecting it', () => { const sentinel = 'never-retain-private-sentinel', bad = wire(packet(), request.requestId, v => ({ ...v, secret: sentinel })); let error; try { decodeObserverInstrumentation(bad, request.requestId); } catch (e) { error = e; } assert.ok(error); assert.equal(String(error).includes(sentinel), false); });
test('full package force-stopped assertion refuses before any device command', () => { let calls = 0; assert.throws(() => observeQaPrivacy({ requireFullPackageForceStopped: true, command: () => { calls++; } }), /FULL_FORCE_STOPPED_UNPROVED/); assert.equal(calls, 0); });
test('real command path preserves APK checks and zeroes raw command/packet buffers', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'caseops-observer-unit-')); let raw; const seen = [];
  try { const file = path.join(root, 'installed.json'), bytes = Buffer.from(JSON.stringify(descriptor)); fs.writeFileSync(file, bytes, { mode: 0o600 });
    const result = observeQaPrivacy({ udid: descriptor.udid, androidTransportMode: 'usb-reverse', environment: { ADB_SERVER_SOCKET: 'tcp:127.0.0.1:5042' }, privacyObserver: { path: file, sha256: hash(bytes) }, operation: 'attest', command: (exe, args, opts) => {
      assert.equal(exe, 'adb'); assert.equal(opts.shell, false); seen.push(args); const a = args.slice(2);
      if (a[0] === 'shell' && a[1] === '-T') { assert.equal(a.length, 3); assert.match(a[2], /'--always-check-signature'/); assert.doesNotMatch(a[2], /run-as|no-restart|root|logcat-file/); const req = JSON.parse(/'caseopsRequest' '([^']+)'/.exec(a[2])[1]); raw = wire(packet(req), req.requestId); return raw; }
      if (a[1] === 'cmd') return `package:${a.at(-1)} uid:${a.at(-1) === QA_APP ? descriptor.packageUid : descriptor.observerUid}\n`;
      if (a[1] === 'pm') return `package:/data/app/${a.at(-1)}/base.apk\n`;
      if (a[1] === 'sha256sum') return `${a[2].includes(QA_OBSERVER_APP) ? descriptor.observerApkSha256 : descriptor.targetApkSha256}  ${a[2]}\n`;
      if (a[1] === 'pidof') { const e = new Error('empty'); Object.assign(e, { status: 1, stdout: Buffer.alloc(0), stderr: Buffer.alloc(0), signal: null }); throw e; }
      throw new Error('UNEXPECTED_FAKE_DISPATCH');
    } }, value => ({ access: value.access, count: value.files.length, stoppedCertified: value.fullPackageForceStoppedStateCertified }));
    assert.deepEqual(result, { access: 'qa-observer-service', count: 0, stoppedCertified: false }); assert.ok(raw.every(x => x === 0)); assert.equal(seen.filter(a => a[3] === '-T').length, 1); assert.equal(seen.filter(a => a[3] === 'sha256sum').length, 4);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

test('Appium witness calls real driver boundary before and after without a restart', async () => {
  const { withObserverAppiumWitness } = await import('./android-qa-observer.mjs'); const calls=[];
  const driver={sessionId:'owned-session-1',getCurrentPackage:async()=>{calls.push('package');return QA_APP;},getCurrentActivity:async()=>{calls.push('activity');return '.MainActivity';}};
  const r=await withObserverAppiumWitness(driver,async()=>{calls.push('read');return 7;}); assert.deepEqual(calls,['package','activity','read','package','activity']);assert.equal(r.value,7);assert.equal(r.appiumWitness.complete,true);
});
test('Appium witness keeps original read failure and separately captures session loss', async () => {
  const { withObserverAppiumWitness } = await import('./android-qa-observer.mjs'); const original=new Error('fixed-original'); const d={sessionId:'owned-1',getCurrentPackage:async()=>QA_APP,getCurrentActivity:async()=>'.MainActivity'};
  await assert.rejects(withObserverAppiumWitness(d,async()=>{throw original;}),e=>e===original);
  await assert.rejects(withObserverAppiumWitness(d,async()=>{d.sessionId='changed';throw original;}),e=>e instanceof AggregateError&&e.errors[0]===original&&e.errors.length===2);
});
test('Appium witness refuses changed foreground activity without replaying the read', async () => {
  const { withObserverAppiumWitness } = await import('./android-qa-observer.mjs');let n=0,calls=0;const d={sessionId:'owned-2',getCurrentPackage:async()=>QA_APP,getCurrentActivity:async()=>++n===1?'.MainActivity':'.OtherActivity'};
  await assert.rejects(withObserverAppiumWitness(d,async()=>{calls++;}),/ACTIVITY_OR_APPIUM_CHANGED/);assert.equal(calls,1);
});


test('native fixed failure and separate cleanup survive without accepting a partial private packet',()=>{
 const failure=f(2,Buffer.concat([f(3,2),f(4,bundle({'caseops.complete':'false','caseops.error':'QA_OBSERVER_MAIN_LIFECYCLE_CHANGED','caseops.cleanupFailure':'QA_SIDECAR_LEASE_CLOSE_UNCONFIRMED'}))]));assert.throws(()=>decodeObserverInstrumentation(failure,request.requestId),e=>e instanceof AggregateError&&e.errors[0].message==='QA_OBSERVER_MAIN_LIFECYCLE_CHANGED'&&e.errors[1].message==='QA_SIDECAR_LEASE_CLOSE_UNCONFIRMED');
});
