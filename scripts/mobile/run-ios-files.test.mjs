import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { reconcileResults } from '../../apps/mobile/e2e/support.mjs';
import { captureIosFilesCallFailure, captureIosFilesPrivacy, filesCaseRecovery, knownFileSources, validateIosFilesCache,
  iosSourceAdmissionDiagnostic } from './run-ios-files.mjs';

const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const RUNNER = path.join(ROOT, 'scripts/mobile/run-ios-files.mjs');
const EXPECTED = ['FILES-01', 'FILES-02', 'FILES-03', 'FILES-04', 'FILES-05', 'FILES-06', 'FILES-07', 'FILES-08',
  'FILES-09', 'FILES-10', 'FILES-11', 'FILES-12', 'FILES-13', 'FILES-14', 'FILES-15', 'FILES-16', 'FILES-17'].map((id) => `ios:${id}`);

test('controller forces cold preflight and checkpoints, reserving byte verification for final postflight', () => {
  for (const phase of ['preflight','checkpoint','postflight']) {
    let observed;
    const result = captureIosFilesPrivacy({ verifyProviderBytes: phase !== 'postflight' }, phase, options => {
      observed = options.verifyProviderBytes;
      return { snapshot: { schemaVersion: 2, complete: true, providerMetadataPreserved: true, providerOriginalsRead: observed,
        providerOriginalsPreserved: observed ? true : null, providerByteVerification: observed ? 'postflight' : 'deferred-until-postflight', counts: { ownedStagingFiles: 0, privateAssetMatchCount: 0 } } };
    });
    assert.equal(observed, phase === 'postflight'); assert.equal(result.snapshot.providerOriginalsRead, observed);
  }
});
test('controller rejects unknown phases, early byte reads and unverified final originals without weakening private-copy checks', () => {
  let calls = 0; assert.throws(() => captureIosFilesPrivacy({}, 'unknown', () => { calls++; }), /FILES_PRIVACY_PHASE_REQUIRED/); assert.equal(calls, 0);
  const good = { schemaVersion: 2, complete: true, providerMetadataPreserved: true, providerOriginalsRead: false,
    providerOriginalsPreserved: null, providerByteVerification: 'deferred-until-postflight', counts: { ownedStagingFiles: 0, privateAssetMatchCount: 0 } };
  for (const change of [{ providerOriginalsRead: true }, { providerOriginalsPreserved: true }, { providerMetadataPreserved: false }, { counts: { ownedStagingFiles: 1, privateAssetMatchCount: 0 } }, { counts: { ownedStagingFiles: 0, privateAssetMatchCount: 1 } }])
    assert.throws(() => captureIosFilesPrivacy({}, 'checkpoint', () => ({ snapshot: { ...good, ...change } })));
  assert.throws(() => captureIosFilesPrivacy({}, 'postflight', () => ({ snapshot: good })));
});
function environment(t) {
  const reportRoot = realpathSync(mkdtempSync(path.join(os.tmpdir(), 'caseops-ios-files-controller-')));
  t.after(() => rmSync(reportRoot, { recursive: true, force: true }));
  const env = { ...process.env, CASEOPS_MOBILE_REPORT_ROOT: reportRoot,
    CASEOPS_MOBILE_FIXTURE: path.join(reportRoot, 'deliberately-absent-fixture.json'),
    CASEOPS_MOBILE_APPIUM_URL: 'http://127.0.0.1:9', CASEOPS_MOBILE_TOOLING_HOME: path.join(reportRoot, 'absent-tooling') };
  // This controller test never loads human/synthetic credentials or reaches Appium.
  for (const key of Object.keys(env)) if (/^CASEOPS_MOBILE_.*(PASSWORD|EMAIL|TOTP_SECRET)$/.test(key)) delete env[key];
  return { reportRoot, env };
}

test('Files source admission requires the explicit cache and binds every public producer path before native work', (t) => {
  const { reportRoot } = environment(t);
  const manifestPath = path.join(reportRoot, 'manifest.json');
  const manifest = { isolationReceipt: { path: path.join(reportRoot, 'original.json') },
    baseSeed: { path: path.join(reportRoot, 'seed.json') } };
  const fixture = { filesCache: reportRoot, isolationEvidence: { path: path.join(reportRoot, 'current.json') },
    publicCa: { path: path.join(reportRoot, 'tls/ca.crt') }, files: {} };
  const write = () => {
    const bytes = Buffer.from(JSON.stringify(manifest)); writeFileSync(manifestPath, bytes);
    fixture.files.manifestEvidence = { path: manifestPath, sha256: createHash('sha256').update(bytes).digest('hex') };
  };
  write(); assert.equal(validateIosFilesCache(fixture), reportRoot);
  for (const filesCache of [undefined, null, '', 'undefined', '.', reportRoot + '/..']) {
    assert.throws(() => validateIosFilesCache({ ...fixture, filesCache }), /IOS_FILES_EXPLICIT_ABSOLUTE_CACHE_REQUIRED/);
  }
  assert.throws(() => validateIosFilesCache({ ...fixture, filesCache: reportRoot + '/other' }), /IOS_FILES_RECEIPT_CACHE_MISMATCH/);
  manifest.isolationReceipt.path = path.join(reportRoot, 'foreign/original.json'); write();
  assert.throws(() => validateIosFilesCache(fixture), /IOS_FILES_MANIFEST_CACHE_MISMATCH/);
  manifest.isolationReceipt.path = path.join(reportRoot, 'original.json');
  manifest.baseSeed.path = path.join(reportRoot, 'foreign-seed.json'); write();
  assert.throws(() => validateIosFilesCache(fixture), /IOS_FILES_SEED_CACHE_MISMATCH/);
  manifest.baseSeed.path = path.join(reportRoot, 'seed.json'); write();
  fixture.publicCa.path = path.join(reportRoot, 'foreign-ca.crt');
  assert.throws(() => validateIosFilesCache(fixture), /IOS_FILES_CA_CACHE_MISMATCH/);
});

test('source helper diagnostics retain fixed failure facts without stderr, error messages or submitted values', () => {
  assert.deepEqual(iosSourceAdmissionDiagnostic({ status: 1, stderr: JSON.stringify({
    sourceRouteAdmitted: false, error: 'FileNotFoundError', reason: 'synthetic-secret' }) }),
  { exitStatus: 1, timedOut: false, launchFailed: false, failureClass: 'FileNotFoundError' });
  for (const stderr of ['synthetic-secret', '{', JSON.stringify({ sourceRouteAdmitted: false, error: 'synthetic-secret' })]) {
    const value = iosSourceAdmissionDiagnostic({ status: null, error: { code: 'ETIMEDOUT', message: 'synthetic-secret' }, stderr });
    assert.deepEqual(value, { exitStatus: null, timedOut: true, launchFailed: false, failureClass: 'unclassified' });
    assert.equal(JSON.stringify(value).includes('synthetic-secret'), false);
  }
  assert.equal(iosSourceAdmissionDiagnostic({ status: null, error: { code: 'ENOENT' } }).launchFailed, true);
});

test('native Files failure evidence refuses credential/background/oversize surfaces before writing a protected hierarchy', async (t) => {
  const { reportRoot } = environment(t);
  let sourceCalls = 0;
  const driver = { queryAppState: async () => 4, switchContext: async context => assert.equal(context, 'NATIVE_APP'),
    $$: async () => [{ elementId: 'password' }], getPageSource: async () => { sourceCalls++; return '<synthetic-files />'; } };
  const context = { fixture: { environment: 'docker-integration', syntheticDataOnly: true, appId: 'ai.caseops.mobile.dev.simulatoracceptance' }, driver };
  await assert.rejects(captureIosFilesCallFailure(context, reportRoot, 'ios:FILES-01'), /CREDENTIAL_SURFACE_FAILURE_CAPTURE_REFUSED/);
  assert.equal(sourceCalls, 0); assert.deepEqual(readdirSync(reportRoot), []);
  driver.$$ = async () => [];
  driver.queryAppState = async () => 3;
  await assert.rejects(captureIosFilesCallFailure(context, reportRoot, 'ios:FILES-01'), /FAILURE_APP_NOT_FOREGROUND/);
  assert.equal(sourceCalls, 0);
  driver.queryAppState = async () => 4;
  driver.getPageSource = async () => 'x'.repeat(524289);
  await assert.rejects(captureIosFilesCallFailure(context, reportRoot, 'ios:FILES-01'), /NATIVE_FAILURE_HIERARCHY_BOUND/);
  assert.deepEqual(readdirSync(reportRoot), []);
  driver.getPageSource = async () => '<synthetic-files />';
  const evidence = await captureIosFilesCallFailure(context, reportRoot, 'ios:FILES-01');
  assert.equal(readFileSync(evidence.path, 'utf8'), '<synthetic-files />');
  assert.equal(statSync(evidence.path).mode & 0o077, 0);
  assert.match(evidence.sha256, /^[a-f0-9]{64}$/);
});

test('a failed picker remains pending across blocked reader dependencies and restarts once before the next authenticated case', async () => {
  const recovery = filesCaseRecovery(), calls = [], events = [];
  recovery.observe({ id: 'FILES-08', setupPassed: true, callPassed: false });
  for (const id of ['FILES-09', 'FILES-10', 'FILES-11']) recovery.observe({ id, setupPassed: false, callPassed: false });
  const context = { platform: 'ios', fixture: { appId: 'ai.caseops.mobile.dev.simulatoracceptance' }, record: event => events.push(event),
    driver: { terminateApp: async id => calls.push(['terminate', id]), activateApp: async id => calls.push(['activate', id]),
      switchContext: async id => calls.push(['context', id]) } };
  await recovery.prepare(context);
  assert.deepEqual(calls, [['terminate', context.fixture.appId], ['activate', context.fixture.appId], ['context', 'NATIVE_APP']]);
  assert.equal(events.filter(event => event.type === 'native_case_recovery').length, 1);
  assert.equal(events.find(event => event.type === 'native_case_recovery').previousCase, 'FILES-08');
  assert.equal(events.find(event => event.type === 'native_case_recovery').mutationReplay, false);
  recovery.observe({ id: 'FILES-12', setupPassed: true, callPassed: true });
  await recovery.prepare(context);
  assert.equal(calls.length, 3);
});
test('privacy source inventory includes all six retained cohorts with exact hashes and rejects missing or altered evidence', (t) => {
  const {reportRoot}=environment(t),priorManifestEvidence=[];
  for(let index=0;index<6;index++){
    const file=path.join(reportRoot,`prior-${index}.json`),bytes=Buffer.from(JSON.stringify({syntheticDataOnly:true,kind:'ios-files-synthetic-fixtures',assets:Array.from({length:7},(_,asset)=>({id:`asset-${asset}`,filename:`prior-${index}-${asset}.txt`,sha256:String(index+1).repeat(64)}))}));
    writeFileSync(file,bytes);priorManifestEvidence.push({path:file,sha256:createHash('sha256').update(bytes).digest('hex')});
  }
  const current=path.join(reportRoot,'current.json');
  writeFileSync(current,JSON.stringify({syntheticDataOnly:true,kind:'ios-files-synthetic-fixtures',assets:Array.from({length:7},(_,id)=>({id}))}));
  const manifestEvidence={path:current,sha256:createHash('sha256').update(readFileSync(current)).digest('hex')};
  const assets={source:{filename:'source.txt',sha256:'0'.repeat(64),text:'Synthetic seed.'},priorManifestEvidence,manifestEvidence};
  assert.deepEqual(knownFileSources(assets).map(({id})=>id),['seeded-txt',...Array.from({length:6},(_,index)=>Array.from({length:7},(_,asset)=>`prior-${index}-asset-${asset}`)).flat()]);
  assert.throws(()=>knownFileSources({...assets,priorManifestEvidence:[...priorManifestEvidence,priorManifestEvidence[0]]}),/BOUNDED_PRIOR_FILES_COHORTS_REQUIRED/);
  assert.throws(()=>knownFileSources({...assets,priorManifestEvidence:[{...priorManifestEvidence[0],sha256:'f'.repeat(64)}]}));
  assert.throws(()=>knownFileSources({...assets,priorManifestEvidence:[{path:path.join(reportRoot,'absent.json'),sha256:'f'.repeat(64)}]}));
  assert.throws(()=>knownFileSources({...assets,manifestEvidence:undefined}));
  assert.throws(()=>knownFileSources({...assets,manifestEvidence:{...manifestEvidence,sha256:'f'.repeat(64)}}));
});
test('privacy source total independently charges the hashed current manifest and seed at the unchanged sixty-asset boundary', (t) => {
  const {reportRoot}=environment(t);
  const manifest=(name,count,change={})=>{
    const file=path.join(reportRoot,name),bytes=Buffer.from(JSON.stringify({syntheticDataOnly:true,kind:'ios-files-synthetic-fixtures',assets:Array.from({length:count},(_,id)=>({id})),...change}));
    writeFileSync(file,bytes);return {path:file,sha256:createHash('sha256').update(bytes).digest('hex')};
  };
  const priorManifestEvidence=Array.from({length:6},(_,index)=>manifest(`prior-${index}.json`,8));
  const assets={source:{filename:'seed.txt',sha256:'0'.repeat(64)},priorManifestEvidence,manifestEvidence:manifest('current60.json',11)};
  assert.equal(knownFileSources(assets).length,49); // 48 prior + seed + eleven current = 60.
  assert.throws(()=>knownFileSources({...assets,manifestEvidence:manifest('current61.json',12)}),/BOUNDED_TOTAL_FILES_SOURCES_REQUIRED/);
  assert.throws(()=>knownFileSources({...assets,priorManifestEvidence:[manifest('oversize-prior.json',13)]}),/BOUNDED_PRIOR_FILES_REQUIRED/);
  assert.throws(()=>knownFileSources({...assets,manifestEvidence:manifest('wrong-current.json',1,{syntheticDataOnly:false})}),/SYNTHETIC_CURRENT_FILES_REQUIRED/);
  assert.throws(()=>knownFileSources({...assets,priorManifestEvidence:[manifest('wrong-prior.json',1,{kind:'invented'})]}),/PRIOR_FILES_MANIFEST_REQUIRED/);
});

test('Files CLI independently collects its complete ordered 17-case inventory without executing or creating a report', (t) => {
  const { reportRoot, env } = environment(t);
  const child = spawnSync(process.execPath, [RUNNER, '--collect'], { cwd: ROOT, env, encoding: 'utf8', timeout: 20000 });
  assert.equal(child.error, undefined); assert.equal(child.status, 0, child.stderr);
  const collected = JSON.parse(child.stdout);
  assert.equal(collected.inventoryId, 'native-ios-files-2026-10-26'); assert.equal(collected.platform, 'ios');
  assert.deepEqual(collected.intended, EXPECTED); assert.deepEqual(collected.discovered, EXPECTED);
  assert.deepEqual(readdirSync(reportRoot), []);
});

test('a real failed-preflight invocation retains every setup/call/teardown outcome and completion while executing no native call/session', (t) => {
  const { reportRoot, env } = environment(t);
  // This deliberately absent-fixture unit must reach the controller's own
  // preflight. The optional source observer correctly refuses native entry
  // forms before that boundary; its refusal is covered separately.
  const preflightEnv = { ...env };
  for (const key of Object.keys(preflightEnv)) if (/^CASEOPS_SOURCE_GATE_/i.test(key)) delete preflightEnv[key];
  for (const key of ['NODE_OPTIONS', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'NODE_V8_COVERAGE',
    'CASEOPS_HOST_NODE_TRUST_POLICY_FILE', 'CASEOPS_HOST_NODE_TRUST_POLICY_SHA256']) assert.equal(preflightEnv[key], env[key]);
  const child = spawnSync(process.execPath, [RUNNER], { cwd: ROOT, env: preflightEnv, encoding: 'utf8', timeout: 20000 });
  assert.equal(child.error, undefined); assert.equal(child.status, 1, child.stderr);
  const runs = readdirSync(reportRoot); assert.equal(runs.length, 1);
  const report = path.join(reportRoot, runs[0]); assert.equal(existsSync(path.join(report, 'summary.json')), true);
  const summary = JSON.parse(readFileSync(path.join(report, 'summary.json')));
  const events = readFileSync(path.join(report, 'events.jsonl'), 'utf8').trim().split('\n').map((row) => JSON.parse(row));
  assert.deepEqual(summary.intended, EXPECTED); assert.deepEqual(summary.discovered, EXPECTED);
  assert.equal(summary.status, 'incomplete-or-failed'); assert.equal(summary.nativeCallsPassed, 0); assert.equal(summary.unexecutedCalls, 17);
  assert.equal(events.filter(({ type }) => type === 'appium_session').length, 0);
  assert.deepEqual(events.filter(({ type }) => type === 'preflight_result').map(({ status }) => status), ['failed']);
  assert.equal(events.filter(({ type }) => type === 'postflight_result').length, 0);
  for (const id of EXPECTED) {
    assert.deepEqual(events.filter((event) => event.type === 'phase_result' && event.id === id).map(({ phase, status }) => ({ phase, status })),
      [{ phase: 'setup', status: 'failed' }, { phase: 'call', status: 'not-run' }, { phase: 'teardown', status: 'passed' }]);
  }
  assert.equal(events.filter(({ type }) => type === 'phase_started').length, 51);
  assert.equal(events.filter(({ type }) => type === 'phase_result').length, 51);
  assert.equal(events.at(-1).type, 'run_completed');
  const reconciled = reconcileResults(events, EXPECTED);
  assert.equal(reconciled.status, summary.status); assert.equal(reconciled.nativeCallsPassed, 0);
});
