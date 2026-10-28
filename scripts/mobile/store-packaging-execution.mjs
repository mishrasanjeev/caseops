import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { packagingPlan } from './prepare-store-packaging.mjs';
import { checkDeadline, digest, gitSource, jsonInput as rawJsonInput, objectKeys, privateDirectory as rawPrivateDirectory, readInput as rawReadInput, readPrivateCredentials, writePrivate as rawWritePrivate, writePublicLock } from './store-packaging-inputs.mjs';
import { EMBED_PROGRAM, inspectDistributionArtifact, PLIST_JSON_PROGRAM } from './store-artifact-postflight.mjs';

const require = createRequire(import.meta.url);
const { reference, validateStoreBuild, reserveBuildNumbers } = require('../../apps/mobile/plugins/store-build.cjs');
const { validateNativeLinkConfig, nativeLinkProjections } = require('../../apps/web/lib/native-link-policy.cjs');
export const GATES = Object.freeze(['mobile', 'web', 'apiCommon', 'apiPostgres', 'nativeIos', 'nativeAndroid',
  'secretTreeHistory', 'codeqlAnalysis', 'codeqlAlertVerdict', 'wholeLockAdvisories', 'installedAdvisories', 'licenses', 'sdk', 'linuxImage', 'requiredCI', 'privacyPolicy']);
export const LIMITS = Object.freeze({ totalSeconds: 3600, cleanupSeconds: 30, commands: 48,
  outputPerStream: 16 * 1024 * 1024, aggregateOutput: 256 * 1024 * 1024, publicReferences: 256 });
const ROOT = path.resolve(fileURLToPath(new URL('../../', import.meta.url)));
const HOST_BOOTSTRAP = String.raw`import hashlib,os,sys
p,h=sys.argv[1:3];b=bytearray()
try:
 while len(b)<=32768:
  v=os.read(3,min(65536,32769-len(b)))
  if not v:break
  b.extend(v)
finally:os.close(3)
if not 0<len(b)<=32768 or hashlib.sha256(b).hexdigest()!=h:raise ValueError('PACKAGING_HOST_BYTES_REFUSED')
sys.argv=[p]
exec(compile(bytes(b),p,'exec'),{'__name__':'__main__','__file__':p,'__caseops_host_source__':bytes(b)})
`;
const roles = platform => ['node', 'python', 'git', ...(platform === 'ios'
  ? ['pod', 'xcodebuild', 'codesign', 'security', 'xcrun'] : ['java', 'keytool', 'jarsigner', 'bundletool'])];
const utf8Json = bytes => {
  try { return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); }
  catch { throw new Error('STORE_PUBLIC_JSON_REFUSED'); }
};
function safeFailure(error) {
  const message = typeof error?.message === 'string' ? error.message.split('\n', 1)[0] : '';
  return { class: ['Error', 'AssertionError', 'TypeError', 'RangeError', 'SyntaxError'].includes(error?.name) ? error.name : 'Error',
    code: /^STORE_[A-Z0-9_]+$/.test(message) ? message : 'STORE_EXECUTION_REFUSED' };
}
export function pendingStoreExecution(platform) {
  assert.ok(['ios', 'android'].includes(platform), 'STORE_PLATFORM_REQUIRED');
  return { schemaVersion: 1, kind: 'caseops-store-execution-request', readyForLocalBuild: false,
    syntheticDataOnly: false, platform, recipe: null, sourceTree: null, gates: null, tools: null,
    storeHistory: null, reservationDirectory: null, outputDirectory: null,
    architecture: { ios: ['arm64'], android: ['arm64-v8a'] }, signingSecrets: null, privacyPolicy: null };
}
export function admitTools(value, platform, { contractOnly = false, deadline } = {}) {
  const readInput = (file, options) => rawReadInput(file, { ...options, deadline });
  checkDeadline(deadline);
  objectKeys(value, ['schemaVersion', 'kind', 'hostPlatform', 'entries', 'runtimeInputs', 'generatedInputs'], 'STORE_TOOLS_REQUIRED');
  assert.equal(value.schemaVersion, 1); assert.equal(value.kind, 'caseops-local-store-tools');
  assert.equal(value.hostPlatform, 'darwin', 'STORE_MACOS_HOST_REQUIRED');
  objectKeys(value.entries, roles(platform), 'STORE_EXACT_TOOL_ROLES_REQUIRED');
  const seen = new Set(); let bytes = 0;
  for (const [role, item] of Object.entries(value.entries)) {
    checkDeadline(deadline); objectKeys(item, ['path', 'sha256', 'sizeBytes', 'version', 'ownerUid'], 'STORE_TOOL_RECORD_REQUIRED');
    assert.ok(path.isAbsolute(item.path) && !seen.has(item.path) && Number.isSafeInteger(item.sizeBytes)
      && item.sizeBytes > 0 && item.sizeBytes <= 256 * 1024 * 1024 && typeof item.version === 'string'
      && item.version.length > 0 && Number.isSafeInteger(item.ownerUid)
      && [0, process.getuid?.()].includes(item.ownerUid), 'STORE_TOOL_IDENTITY_REQUIRED'); seen.add(item.path);
    assert.match(item.sha256, /^[a-f0-9]{64}$/);
    if (!contractOnly) {
      const actual = readInput(item.path, { sha256: item.sha256, maxBytes: item.sizeBytes, systemTool: true });
      assert.equal(actual.bytes.length, item.sizeBytes, 'STORE_TOOL_EXTENT_CHANGED'); bytes += actual.bytes.length;
      assert.equal(Number(actual.metadata.uid), item.ownerUid, 'STORE_TOOL_OWNER_CHANGED');
      if (role !== 'bundletool') assert.ok(Number(actual.metadata.mode) & 0o111, 'STORE_TOOL_EXECUTABLE_REQUIRED');
    }
  }
  assert.equal(value.entries.node.version, '24.15.0', 'STORE_NODE_VERSION_REQUIRED');
  assert.equal(value.entries.python.version, '3.13.17', 'STORE_PYTHON_VERSION_REQUIRED');
  assert.ok(Array.isArray(value.runtimeInputs) && value.runtimeInputs.length > 0 && value.runtimeInputs.length <= 5000, 'STORE_RUNTIME_INPUTS_REQUIRED');
  for (const item of value.runtimeInputs) {
    checkDeadline(deadline); objectKeys(item, ['path', 'sha256', 'sizeBytes'], 'STORE_RUNTIME_REFERENCE_REQUIRED');
    assert.ok(Number.isSafeInteger(item.sizeBytes) && item.sizeBytes > 0 && item.sizeBytes <= 256 * 1024 * 1024, 'STORE_RUNTIME_EXTENT_REQUIRED');
    if (!contractOnly) {
      const actual = readInput(item.path, { sha256: item.sha256, maxBytes: item.sizeBytes, systemTool: true });
      assert.equal(actual.bytes.length, item.sizeBytes, 'STORE_RUNTIME_EXTENT_CHANGED'); bytes += actual.bytes.length;
    }
    assert.ok(bytes <= 1024 * 1024 * 1024, 'STORE_RUNTIME_TOTAL_BOUND');
  }
  const generated = platform === 'ios' ? ['Podfile'] : ['gradlew', 'gradle/wrapper/gradle-wrapper.jar', 'gradle/wrapper/gradle-wrapper.properties'];
  assert.ok(Array.isArray(value.generatedInputs), 'STORE_GENERATED_INPUTS_REQUIRED');
  assert.deepEqual(value.generatedInputs.map(r => r.path).sort(), [...generated].sort(), 'STORE_EXACT_GENERATED_INPUTS_REQUIRED');
  for (const row of value.generatedInputs) {
    objectKeys(row, ['path', 'sha256', 'sizeBytes'], 'STORE_GENERATED_INPUT_RECORD_REQUIRED');
    assert.match(row.sha256, /^[a-f0-9]{64}$/); assert.ok(Number.isSafeInteger(row.sizeBytes) && row.sizeBytes > 0 && row.sizeBytes <= 16 * 1024 * 1024, 'STORE_GENERATED_INPUT_EXTENT');
  }
  return value.entries;
}
function reserveBatch(directory, build, batch, platform, deadline) {
  const readInput = (file, options) => rawReadInput(file, { ...options, deadline });
  const jsonInput = (ref, options) => rawJsonInput(ref, { ...options, deadline });
  const privateDirectory = (file, options) => rawPrivateDirectory(file, { ...options, deadline });
  const writePrivate = (file, bytes) => rawWritePrivate(file, bytes, { deadline });
  privateDirectory(directory);
  const records = [['ios', build.identities.iosBundleIdentifier, build.iosBuildNumber],
    ['android', build.identities.androidPackageName, String(build.androidVersionCode)]];
  const paths = records.map(([p, app, n]) => path.join(directory, digest(JSON.stringify([p, app])) + '-' + p + '-' + n + '.json'));
  const batchPath = path.join(directory, 'batch-' + batch + '.json');
  if (paths.some(p => fs.existsSync(p)) || fs.existsSync(batchPath)) {
    assert.ok(paths.every(p => fs.existsSync(p)) && fs.existsSync(batchPath), 'STORE_PARTIAL_RESERVATION_REFUSED');
    const receipt = jsonInput({ path: batchPath, sha256: readInput(batchPath, { privateFile: true }).sha256 }, { privateFile: true }).value;
    assert.deepEqual(receipt, { kind: 'caseops-store-number-batch', batch, records: records.map(([p, app, n]) => ({ platform: p, appId: app, value: n })) }, 'STORE_RESERVATION_BATCH_MISMATCH');
  } else {
    reserveBuildNumbers(directory, build, batch);
    writePrivate(batchPath, Buffer.from(JSON.stringify({ kind: 'caseops-store-number-batch', batch,
      records: records.map(([p, app, n]) => ({ platform: p, appId: app, value: n })) }) + '\n'));
  }
  for (let i = 0; i < records.length; i++) {
    const r = readInput(paths[i], { privateFile: true });
    assert.deepEqual(utf8Json(r.bytes), { requestSha256: batch, platform: records[i][0], value: records[i][2] }, 'STORE_COUNTER_RESERVATION_MISMATCH');
  }
  return writePrivate(path.join(directory, 'execution-' + batch + '-' + platform + '.claim'), Buffer.from(JSON.stringify({ batch, platform }) + '\n'));
}

export async function runHostCommand(command, { python, hostScript, environment, deadline }) {
  const remaining = deadline - Date.now() - LIMITS.cleanupSeconds * 1000;
  assert.ok(remaining > 0, 'STORE_TOTAL_DEADLINE');
  const timeoutSeconds = Math.min(command.timeoutMs, remaining) / 1000;
  const q = { kind: 'caseops-local-store-child', argv: [command.executable, ...command.args], cwd: command.cwd,
    timeoutSeconds, outputLimit: command.capture ? 1048576 : LIMITS.outputPerStream,
    capture: command.capture === true, inputBase64: command.input?.toString('base64') || '', sourceBase64: command.sourceInput?.toString('base64') || '' };
  const code = rawReadInput(hostScript.path, { deadline, sha256: hostScript.sha256, maxBytes: 32768 }).bytes;
  return await new Promise((resolve, reject) => {
    const child = spawn(python, ['-c', HOST_BOOTSTRAP, hostScript.path, hostScript.sha256],
      { env: environment, cwd: command.cwd, shell: false, stdio: ['pipe', 'pipe', 'pipe', 'pipe'] });
    let count = 0, chunks = [], errorBytes = 0; const stderr = [];
    child.stdout.on('data', b => { count += b.length; if (count <= 4 * 1024 * 1024) chunks.push(b); });
    child.stderr.on('data', b => { errorBytes += b.length; if (errorBytes <= 1048576) stderr.push(b); });
    child.on('error', () => reject(new Error('STORE_HOST_LAUNCH_REFUSED')));
    // The Python owner has its own deadline and30s cleanup. A failed transport
    // remains unknown; no unadmitted process is signalled or automatically replayed.
    const timer = setTimeout(() => { reject(new Error('STORE_HOST_ACK_UNKNOWN')); }, Math.min(remaining + 31000, deadline - Date.now()));
    child.on('close', status => {
      clearTimeout(timer);
      try {
        assert.ok(status === 0 && count <= 4 * 1024 * 1024 && errorBytes === 0, 'STORE_HOST_TRANSPORT_REFUSED');
        const result = utf8Json(Buffer.concat(chunks));
        assert.ok(result && typeof result === 'object', 'STORE_HOST_RESULT_REQUIRED'); resolve(result);
      } catch (error) { reject(error); }
      finally { for (const b of [...chunks, ...stderr]) b.fill(0); chunks = []; }
    });
    child.stdin.on('error', () => {});
    child.stdio[3].on('error', () => {}); child.stdio[3].end(code);
    child.stdin.end(JSON.stringify(q) + '\n');
  });
}

export async function executeStorePackaging(requestRef, { root = ROOT, adapter } = {}) {
  const startedAt = Date.now(), deadline = startedAt + LIMITS.totalSeconds * 1000;
  const admissionDeadline = deadline - LIMITS.cleanupSeconds * 1000;
  const readInput = (file, options) => rawReadInput(file, { ...options, deadline: admissionDeadline });
  const jsonInput = (ref, options) => rawJsonInput(ref, { ...options, deadline: admissionDeadline });
  const privateDirectory = (file, options) => rawPrivateDirectory(file, { ...options, deadline: admissionDeadline });
  const writePrivate = (file, bytes) => rawWritePrivate(file, bytes, { deadline: admissionDeadline });
  const contractOnly = adapter !== undefined;
  assert.ok(contractOnly || process.env.CASEOPS_LOCAL_STORE_BUILD_GO === 'EXPLICIT_REVIEWED_LOCAL_STORE_BUILD', 'STORE_BUILD_NOT_ARMED');
  assert.ok(contractOnly || (process.platform === 'darwin' && process.versions.node === '24.15.0'), 'STORE_ACCEPTED_HOST_REQUIRED');
  const q = jsonInput(reference(requestRef)).value;
  objectKeys(q, ['schemaVersion', 'kind', 'readyForLocalBuild', 'syntheticDataOnly', 'platform', 'recipe', 'sourceTree', 'gates', 'tools',
    'storeHistory', 'reservationDirectory', 'outputDirectory', 'architecture', 'signingSecrets', 'privacyPolicy'], 'STORE_EXECUTION_REQUEST_REQUIRED');
  assert.ok(q.schemaVersion === 1 && q.kind === 'caseops-store-execution-request' && q.readyForLocalBuild === true
    && typeof q.syntheticDataOnly === 'boolean' && (contractOnly || !q.syntheticDataOnly), 'STORE_COMPLETE_REAL_REQUEST_REQUIRED');
  assert.ok(['ios', 'android'].includes(q.platform), 'STORE_PLATFORM_REQUIRED');
  if (q.platform === 'ios') assert.equal(q.signingSecrets, null, 'STORE_IOS_PASSWORD_INPUT_FORBIDDEN');
  else { objectKeys(q.signingSecrets, ['path'], 'STORE_PRIVATE_CREDENTIAL_PATH_REQUIRED'); assert.ok(path.isAbsolute(q.signingSecrets.path || '') && path.resolve(q.signingSecrets.path) === q.signingSecrets.path, 'STORE_PRIVATE_CREDENTIAL_PATH_REQUIRED'); }
  assert.equal(fs.lstatSync(path.join(root, 'apps/mobile', q.platform), { throwIfNoEntry: false }), undefined, 'STORE_FRESH_NATIVE_PROJECT_REQUIRED');
  objectKeys(q.architecture, ['ios', 'android'], 'STORE_ARCHITECTURES_REQUIRED');
  assert.ok(Array.isArray(q.architecture.ios) && q.architecture.ios.length > 0
    && q.architecture.ios.every(a => ['arm64', 'arm64e'].includes(a)) && new Set(q.architecture.ios).size === q.architecture.ios.length
    && Array.isArray(q.architecture.android) && q.architecture.android.includes('arm64-v8a')
    && q.architecture.android.every(a => ['arm64-v8a', 'armeabi-v7a', 'x86', 'x86_64'].includes(a))
    && new Set(q.architecture.android).size === q.architecture.android.length, 'STORE_ARCHITECTURES_REQUIRED');
  const request = jsonInput(reference(q.recipe)).value;
  const linkInput = jsonInput(reference(request.nativeLinks)), config = validateNativeLinkConfig(linkInput.value);
  assert.equal(config.syntheticDataOnly, q.syntheticDataOnly, 'STORE_SYNTHETIC_SCOPE_MISMATCH');
  const links = { config, sha256: request.nativeLinks.sha256, bytes: linkInput.bytes, projections: nativeLinkProjections(config, request.nativeLinks.sha256) };
  const policyInput = jsonInput(reference(q.privacyPolicy));
  let privacyPolicy;
  if (adapter?.privacyPolicy) privacyPolicy = adapter.privacyPolicy(policyInput.value, q.privacyPolicy.sha256, links, request.webOrigin);
  else {
    let reader;
    try { reader = require('../../apps/mobile/plugins/privacy-policy.cjs').readPrivacyPolicySettings; }
    catch { throw new Error('STORE_PRIVACY_POLICY_READER_UNAVAILABLE'); }
    privacyPolicy = reader({ CASEOPS_MOBILE_PRIVACY_POLICY_FILE: q.privacyPolicy.path, CASEOPS_MOBILE_PRIVACY_POLICY_SHA256: q.privacyPolicy.sha256 },
      { links, webOrigin: request.webOrigin, required: true });
  }
  const policyAfter = readInput(q.privacyPolicy.path, { sha256: q.privacyPolicy.sha256 });
  assert.ok(privacyPolicy && privacyPolicy.sha256 === q.privacyPolicy.sha256 && privacyPolicy.url === policyInput.value.url
    && privacyPolicy.version === policyInput.value.version && policyInput.value.nativeLinkConfigSha256 === links.sha256
    && policyAfter.canonical === policyInput.canonical, 'STORE_PRIVACY_POLICY_PROJECTION_MISMATCH');
  assert.deepEqual(policyAfter.metadata, policyInput.metadata, 'STORE_PRIVACY_POLICY_INPUT_CHANGED');
  const buildInput = jsonInput(reference(request.storeBuild)), baseline = jsonInput(reference(buildInput.value.baseline));
  const settings = { ...validateStoreBuild(buildInput.value, baseline.value, links, { allowSynthetic: contractOnly }),
    ref: request.storeBuild, build: { value: buildInput.value, bytes: buildInput.bytes }, baseline };
  const toolsInput = jsonInput(reference(q.tools)), tools = admitTools(toolsInput.value, q.platform, { contractOnly, deadline: admissionDeadline });
  const sourceBudget = { entries: 0, bytes: 0, deadline: Math.min(Date.now() + 120000, admissionDeadline) };
  const source = adapter?.source ? adapter.source() : gitSource(root, tools.git.path, sourceBudget);
  assert.equal(source.sourceSha, request.source.sourceSha, 'STORE_ACTUAL_SOURCE_MISMATCH');
  assert.equal(source.tree, q.sourceTree, 'STORE_ACTUAL_TREE_MISMATCH');
  const plan = packagingPlan(request, { root, output: q.outputDirectory, links, settings,
    source: { ...request.source, sourceDirty: false }, allowSynthetic: contractOnly });
  assert.equal(plan.platform, q.platform, 'STORE_PLATFORM_MISMATCH');
  const gates = jsonInput(reference(q.gates)).value;
  objectKeys(gates, ['schemaVersion', 'kind', 'sourceSha', 'tree', 'sourceFingerprint', 'inputFileCount', 'reviewedAt', 'reservationDirectory', 'inputBindings', 'results', 'evidence'], 'STORE_REVIEWED_GATES_REQUIRED');
  assert.ok(gates.schemaVersion === 1 && gates.kind === 'caseops-reviewed-store-gates'
    && gates.sourceSha === source.sourceSha && gates.tree === source.tree
    && gates.sourceFingerprint === request.source.sourceFingerprint && gates.inputFileCount === request.source.inputFileCount
    && Date.parse(gates.reviewedAt) <= Date.now() && Date.now() - Date.parse(gates.reviewedAt) <= 86400000
    && gates.reservationDirectory === q.reservationDirectory, 'STORE_CURRENT_SOURCE_GATES_REQUIRED');
  assert.deepEqual(gates.inputBindings, { toolsSha256: q.tools.sha256, nativeLinkConfigSha256: request.nativeLinks.sha256,
    storeBuildSha256: request.storeBuild.sha256, privacyPolicySha256: q.privacyPolicy.sha256,
    signingPublicInputs: request.signing, architecture: q.architecture }, 'STORE_REVIEWED_INPUT_BINDINGS_MISMATCH');
  objectKeys(gates.results, GATES, 'STORE_COMPLETE_GATE_INVENTORY_REQUIRED');
  assert.ok(GATES.every(name => gates.results[name] === 'passed'), 'STORE_REQUIRED_GATE_FAILED');
  assert.ok(Array.isArray(gates.evidence) && gates.evidence.length >= GATES.length && gates.evidence.length <= LIMITS.publicReferences, 'STORE_GATE_EVIDENCE_REQUIRED');
  for (const ref of gates.evidence) { checkDeadline(admissionDeadline); jsonInput(reference(ref)); }
  const history = jsonInput(reference(q.storeHistory)).value;
  objectKeys(history, ['kind', 'identities', 'observedAt', 'iosBuildNumber', 'androidVersionCode', 'evidence'], 'STORE_HISTORY_REQUIRED');
  assert.equal(history.kind, 'caseops-reviewed-actual-store-history', 'STORE_ACTUAL_HISTORY_REQUIRED');
  assert.deepEqual(history.identities, buildInput.value.identities, 'STORE_HISTORY_IDENTITY_MISMATCH');
  assert.ok(Date.parse(history.observedAt) <= Date.now() && Date.now() - Date.parse(history.observedAt) <= 86400000
    && Number(history.iosBuildNumber) < Number(settings.iosBuildNumber)
    && Number.isSafeInteger(history.androidVersionCode) && history.androidVersionCode < settings.androidVersionCode, 'STORE_FRESH_MONOTONIC_HISTORY_REQUIRED');
  assert.ok(Array.isArray(history.evidence) && history.evidence.length > 0 && history.evidence.length <= LIMITS.publicReferences, 'STORE_HISTORY_EVIDENCE_REQUIRED');
  for (const ref of history.evidence) { checkDeadline(admissionDeadline); jsonInput(reference(ref)); }
  if (!contractOnly && q.platform === 'android') {
    assert.equal(fs.realpathSync(path.join(request.signing.javaHome, 'bin/java')), fs.realpathSync(tools.java.path), 'STORE_JAVA_HOME_MISMATCH');
    const java17 = fs.realpathSync(path.join(request.signing.java17Home, 'bin/java'));
    assert.ok(toolsInput.value.runtimeInputs.some(ref => fs.realpathSync(ref.path) === java17), 'STORE_JAVA17_INPUT_REQUIRED');
    const sdk = fs.realpathSync(request.signing.androidSdkRoot);
    assert.ok(toolsInput.value.runtimeInputs.some(ref => ref.path.startsWith(sdk + path.sep) && path.basename(ref.path) === 'source.properties'), 'STORE_SDK_RUNTIME_INPUT_REQUIRED');
  } else if (!contractOnly) {
    assert.equal(fs.realpathSync(tools.xcodebuild.path), fs.realpathSync(path.join(request.signing.developerDirectory, 'usr/bin/xcodebuild')), 'STORE_XCODE_DIRECTORY_MISMATCH');
  }
  assert.ok(q.outputDirectory !== root && !q.outputDirectory.startsWith(root + path.sep), 'STORE_OUTPUT_OUTSIDE_SOURCE_REQUIRED');
  privateDirectory(q.reservationDirectory); privateDirectory(path.dirname(q.outputDirectory));
  const output = privateDirectory(q.outputDirectory, { existing: false });
  const batch = digest(JSON.stringify({ sourceSha: source.sourceSha, tree: source.tree, build: request.storeBuild, links: request.nativeLinks }));
  const result = { schemaVersion: 1, kind: 'caseops-local-store-build-result', contractOnly,
    invocationStartedAt: new Date(startedAt).toISOString(), deadlineUtc: new Date(deadline).toISOString(),
    sourceScope: 'complete tracked file contents/root-file metadata; no complete directory inventory',
    runtimeScope: 'operator-reviewed declared tool/runtime inputs; import closure not independently established here',
    sourceSha: source.sourceSha, tree: source.tree, platform: q.platform, observed: false,
    distributionSigningVerified: false, storeAcceptance: false, uploaded: false, originalFailure: null,
    cleanup: { complete: false }, commands: [], phases: ['reservation', 'signing-admission', 'build', 'artifact-postflight', 'source-postflight'].map(name => ({ name, status: 'unreached' })) };
  let privateCopy, secret, lastCommandCleanup = true;
  let runtime;
  let aggregateOutput = 0;
  const journal = fs.openSync(path.join(output, 'events.jsonl'), fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_EXCL, 0o600);
  const persist = row => { const b = Buffer.from(JSON.stringify(row) + '\n'); let n = 0; while (n < b.length) {
    const amount = fs.writeSync(journal, b, n, b.length - n); assert.ok(amount > 0, 'STORE_JOURNAL_NO_PROGRESS'); n += amount;
  } fs.fsyncSync(journal); };
  const phase = (name, status) => { result.phases.find(p => p.name === name).status = status; persist({ kind: 'phase', name, status }); };
  let environment = {};
  const invoke = async command => {
    assert.ok(result.commands.length < LIMITS.commands && Date.now() + 30000 < deadline, 'STORE_COMMAND_BUDGET');
    const executable = command.executable || tools[command.tool]?.path;
    assert.ok(path.isAbsolute(executable || ''), 'STORE_PINNED_COMMAND_REQUIRED');
    const declaredTool = Object.values(tools).find(t => t.path === executable);
    const generatedTool = toolsInput.value.generatedInputs.find(t => path.join(root, 'apps/mobile', q.platform, t.path) === executable);
    assert.ok(declaredTool || generatedTool, 'STORE_PINNED_COMMAND_REQUIRED');
    const executableSha256 = declaredTool?.sha256 || generatedTool.sha256;
    if (!contractOnly) readInput(executable, { sha256: executableSha256, maxBytes: declaredTool?.sizeBytes || generatedTool.sizeBytes, systemTool: Boolean(declaredTool) });
    const row = { ordinal: result.commands.length + 1, role: command.role, executableSha256,
      argvSha256: digest(JSON.stringify([executable, ...command.args])), status: 'dispatched-outcome-unknown' };
    result.commands.push(row); persist(row);
    lastCommandCleanup = false;
    if (!contractOnly) readInput(tools.python.path, { sha256: tools.python.sha256, maxBytes: tools.python.sizeBytes, systemTool: true });
    const answer = adapter?.command ? await adapter.command({ ...command, executable }, environment)
      : await runHostCommand({ ...command, executable }, { python: tools.python.path,
        hostScript: runtime['store-packaging-host.py'], environment, deadline });
    row.exitCode = answer.exitCode; row.workerExitCode = answer.workerExitCode ?? (contractOnly ? answer.exitCode : null);
    row.timedOut = answer.timedOut; row.cleanup = answer.cleanup;
    row.stdout = { bytes: answer.stdout?.bytes || 0, sha256: answer.stdout?.sha256 || digest('') };
    row.stderr = { bytes: answer.stderr?.bytes || 0, sha256: answer.stderr?.sha256 || digest('') };
    aggregateOutput += row.stdout.bytes + row.stderr.bytes;
    row.status = 'returned'; persist(row); lastCommandCleanup = answer.cleanup?.complete === true;
    assert.ok(Number.isInteger(answer.exitCode) && answer.exitCode === 0 && answer.timedOut === false
      && row.workerExitCode === 0
      && answer.outputExceeded !== true && answer.failureClass == null && answer.streamCleanupComplete !== false
      && lastCommandCleanup && aggregateOutput <= LIMITS.aggregateOutput, 'STORE_COMMAND_FAILED');
    return { exitCode: answer.exitCode, stdout: Buffer.from(answer.stdout?.base64 || '', 'base64'),
      stderr: Buffer.from(answer.stderr?.base64 || '', 'base64') };
  };
  try {
    writePrivate(path.join(output, 'attempt.claim'), Buffer.from(JSON.stringify({ requestSha256: requestRef.sha256, batch, platform: q.platform }) + '\n'));
    phase('reservation', 'running');
    result.reservation = reserveBatch(q.reservationDirectory, buildInput.value, batch, q.platform, admissionDeadline); phase('reservation', 'passed');
    phase('build', 'running');
    // Native preparation is public and must complete/pin its actual generated
    // inputs before the first profile/keychain/keystore/password admission.
    const runtimeDirectory = privateDirectory(path.join(output, 'verified-runtime'), { existing: false });
    runtime = Object.fromEntries(['store-packaging-host.py', 'store_process_owner.py', 'StoreJarVerifier.java'].map(name => {
      const row = source.files.find(f => f.path === 'scripts/mobile/' + name);
      const bytes = readInput(path.join(root, 'scripts/mobile', name), { ...(row ? { sha256: row.sha256 } : {}), maxBytes: 32768 }).bytes;
      assert.ok(contractOnly || row, 'STORE_RUNTIME_SOURCE_ROW_REQUIRED');
      const ref = writePrivate(path.join(runtimeDirectory, name), bytes); fs.chmodSync(ref.path, 0o400); return [name, ref];
    }));
    environment = { HOME: process.env.HOME, PATH: [...new Set([...Object.values(tools).map(t => path.dirname(t.path)), '/usr/bin', '/bin', '/usr/sbin', '/sbin'])].join(path.delimiter),
      LANG: 'C', LC_ALL: 'C', TZ: 'UTC', ...plan.environment, COCOAPODS_DISABLE_STATS: 'true',
      CASEOPS_MOBILE_PRIVACY_POLICY_FILE: q.privacyPolicy.path, CASEOPS_MOBILE_PRIVACY_POLICY_SHA256: q.privacyPolicy.sha256 };
    const notices = ['apps/mobile/BUILD_TOOL_NOTICES.txt', 'apps/mobile/CAMERA_NOTICES.txt', 'apps/mobile/src/viewer/generated/LICENSES.txt'];
    const vendorLicense = 'apps/mobile/vendor/deepmerge-4.3.1-caseops.1/LICENSE.txt';
    if (source.files.some(f => f.path === vendorLicense)) notices.push(vendorLicense);
    const attestation = { schemaVersion: 1, kind: 'caseops-store-artifact-source', source: request.source,
      sourceTree: source.tree, fullSourceFingerprint: source.fullSourceFingerprint, nativeLinks: request.nativeLinks,
      storeBuild: request.storeBuild, apiOrigin: request.apiOrigin, webOrigin: request.webOrigin,
      nativeLinkPolicy: links.projections.policy, privacyPolicy, privacyPolicyRef: q.privacyPolicy, architecture: q.architecture,
      notices: notices.map(name => { const bytes = readInput(path.join(root, name), { maxBytes: 131072 }).bytes;
        return { name, sha256: digest(bytes), bytesBase64: bytes.toString('base64') }; }) };
    const attestationRef = writePrivate(path.join(output, 'artifact-attestation.json'), Buffer.from(JSON.stringify(attestation)));
    const expected = { appId: q.platform === 'ios' ? config.ios.bundleIdentifier : config.android.packageName,
      version: settings.version, iosBuildNumber: settings.iosBuildNumber, androidVersionCode: settings.androidVersionCode,
      signing: request.signing, associatedDomains: links.projections.mobile.ios.associatedDomains,
      iosArchitectures: [...q.architecture.ios].sort(), androidAbis: q.architecture.android, now: Date.now(), privacyPolicy, attestation };
    let signingAdmitted = false;
    const admitSigning = async () => {
    phase('signing-admission', 'running');
    if (adapter?.signingAdmission) await adapter.signingAdmission(q, request);
    else if (q.platform === 'android') {
      const keystore = readInput(request.signing.uploadKeystoreEvidence.path, { sha256: request.signing.uploadKeystoreEvidence.sha256, maxBytes: 1048576, privateFile: true });
      privateCopy = writePrivate(path.join(output, 'upload.keystore'), keystore.bytes); keystore.bytes.fill(0);
      const loaded = readPrivateCredentials(q.signingSecrets, { deadline: admissionDeadline }); secret = loaded.value;
      objectKeys(secret, ['storePassword', 'keyPassword'], 'STORE_PASSWORD_FIELDS_REQUIRED');
      assert.ok(Object.values(secret).every(v => typeof v === 'string' && v.length > 0 && v.length <= 1024 && !v.includes('\0')), 'STORE_PASSWORD_VALUES_REQUIRED');
      Object.assign(environment, { CASEOPS_UPLOAD_KEYSTORE: privateCopy.path, CASEOPS_UPLOAD_STORE_PASSWORD: secret.storePassword, CASEOPS_UPLOAD_KEY_PASSWORD: secret.keyPassword });
      const certificate = await invoke({ role: 'signing-admission', tool: 'keytool', args: ['-J-Duser.language=en', '-J-Duser.country=US', '-list', '-rfc', '-keystore', privateCopy.path,
        '-alias', request.signing.uploadKeyAlias, '-storepass:env', 'CASEOPS_UPLOAD_STORE_PASSWORD'], cwd: output, timeoutMs: 30000, capture: true });
      const certificates = certificate.stdout.toString().match(/-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\s]+-----END CERTIFICATE-----/g) || [];
      assert.ok(certificates.length > 0, 'STORE_UPLOAD_CERTIFICATE_REQUIRED');
      assert.match(certificate.stdout.toString(), /^Entry type: PrivateKeyEntry\s*$/m, 'STORE_UPLOAD_PRIVATE_KEY_ENTRY_REQUIRED');
      const { certificateIdentity } = await import('./store-artifact-postflight.mjs');
      assert.equal(certificateIdentity(Buffer.from(certificates[0])).sha256, request.signing.uploadCertificateSha256, 'STORE_UPLOAD_CERTIFICATE_MISMATCH');
    } else {
      assert.equal(q.signingSecrets, null, 'STORE_IOS_PASSWORD_INPUT_FORBIDDEN');
      const profile = readInput(request.signing.provisioningProfileEvidence.path, { sha256: request.signing.provisioningProfileEvidence.sha256, maxBytes: 1048576 });
      assert.equal(Number(profile.metadata.mode) & 0o022, 0, 'STORE_PROFILE_WRITABLE_BY_OTHERS');
      const decodedProfile = await invoke({ role: 'signing-admission', tool: 'security', args: ['cms', '-D'], input: profile.bytes, cwd: output, timeoutMs: 30000, capture: true });
      const p = utf8Json((await invoke({ role: 'signing-admission', tool: 'python', args: ['-c', PLIST_JSON_PROGRAM], input: decodedProfile.stdout, cwd: output, timeoutMs: 30000, capture: true })).stdout);
      assert.equal(p.UUID, request.signing.provisioningProfileUuid, 'STORE_PROFILE_UUID_MISMATCH');
      assert.deepEqual(p.TeamIdentifier, [request.signing.teamId], 'STORE_PROFILE_TEAM_MISMATCH');
      assert.deepEqual(p.ApplicationIdentifierPrefix, [request.signing.applicationIdentifierPrefix], 'STORE_PROFILE_PREFIX_MISMATCH');
      assert.ok(Date.parse(p.ExpirationDate) > Date.now() && !Object.hasOwn(p, 'ProvisionedDevices') && p.ProvisionsAllDevices !== true
        && p.Entitlements?.['get-task-allow'] === false, 'STORE_APP_STORE_PROFILE_REQUIRED');
      assert.equal(p.Entitlements['application-identifier'], request.signing.applicationIdentifierPrefix + '.' + config.ios.bundleIdentifier, 'STORE_PROFILE_APPLICATION_MISMATCH');
      const { certificateIdentity } = await import('./store-artifact-postflight.mjs');
      const { X509Certificate } = await import('node:crypto');
      assert.ok(Array.isArray(p.DeveloperCertificates) && p.DeveloperCertificates.some(c => {
        const bytes = Buffer.from(c.base64, 'base64'), cert = new X509Certificate(bytes);
        if (cert.fingerprint256.replaceAll(':', '').toLowerCase() !== request.signing.certificateSha256) return false;
        const actual = certificateIdentity(bytes);
        return actual.sha1 === request.signing.certificateSha1;
      }), 'STORE_PROFILE_CERTIFICATE_MISMATCH');
      const installedPaths = ['Library/MobileDevice/Provisioning Profiles', 'Library/Developer/Xcode/UserData/Provisioning Profiles']
        .map(directory => path.join(process.env.HOME, directory, p.UUID + '.mobileprovision'));
      assert.ok(installedPaths.some(file => {
        if (!fs.existsSync(file)) return false;
        return readInput(file, { sha256: request.signing.provisioningProfileEvidence.sha256, maxBytes: 1048576 }).sha256 === profile.sha256;
      }), 'STORE_EXACT_INSTALLED_PROFILE_REQUIRED');
      const identity = await invoke({ role: 'signing-admission', tool: 'security', args: ['find-identity', '-v', '-p', 'codesigning'], cwd: output, timeoutMs: 30000, capture: true });
      assert.equal(identity.stdout.toString().split(/\r?\n/).filter(line => {
        const match = /^\s*[1-9][0-9]*\) ([a-fA-F0-9]{40}) ".*"\s*$/.exec(line);
        return match?.[1].toLowerCase() === request.signing.certificateSha1;
      }).length, 1, 'STORE_PRIVATE_KEY_IDENTITY_REQUIRED');
    }
    phase('signing-admission', 'passed'); signingAdmitted = true;
    };
    for (const [name, bytes] of Object.entries(plan.outputs)) writePrivate(path.join(output, name), Buffer.from(bytes));
    for (const item of plan.commands) {
      const tool = item.executable === './gradlew' ? null : item.executable;
      let executable = tool ? tools[tool]?.path : path.join(item.cwd, 'gradlew');
      if (item.args.includes('archive') || item.args[0] === ':app:bundleRelease') await admitSigning();
      let args = [...item.args];
      if (args.includes('archive')) args = [...args, 'ARCHS=' + q.architecture.ios.join(' ')];
      if (args[0] === ':app:bundleRelease') args.push('-PreactNativeArchitectures=' + q.architecture.android.join(','));
      await invoke({ role: 'build', executable, args, cwd: item.cwd, timeoutMs: item.timeoutMs, capture: false });
      if (item.args.includes('prebuild')) {
        for (const generated of toolsInput.value.generatedInputs) {
          const actual = readInput(path.join(root, 'apps/mobile', q.platform, generated.path), { sha256: generated.sha256, maxBytes: generated.sizeBytes });
          assert.equal(actual.bytes.length, generated.sizeBytes, 'STORE_GENERATED_INPUT_CHANGED');
        }
        if (q.platform === 'ios') {
          const lock = readInput(request.signing.podfileLockEvidence.path, { sha256: request.signing.podfileLockEvidence.sha256, maxBytes: 1048576 });
          const lockFile = path.join(root, 'apps/mobile/ios/Podfile.lock');
          try { writePublicLock(lockFile, lock.bytes, { deadline: admissionDeadline }); }
          catch (error) { if (error?.code === 'EEXIST') throw new Error('STORE_EXISTING_POD_LOCK_REFUSED', { cause: error }); throw error; }
        }
        const embedded = await invoke({ role: 'embed', tool: 'python', args: ['-c', EMBED_PROGRAM, q.platform, path.join(root, 'apps/mobile'), attestationRef.path,
          path.join(output, 'native-before-info.plist')], cwd: output, timeoutMs: 30000, capture: true });
        assert.deepEqual(utf8Json(embedded.stdout), { embedded: true, sha256: attestationRef.sha256 }, 'STORE_EMBED_ACK_MISMATCH');
      }
    }
    assert.equal(signingAdmitted, true, 'STORE_SIGNING_BOUNDARY_UNREACHED');
    phase('build', 'passed');
    phase('artifact-postflight', 'running');
    const built = q.platform === 'ios' ? path.join(output, 'export/CaseOps.ipa') : path.join(root, 'apps/mobile/android/app/build/outputs/bundle/release/app-release.aab');
    const artifact = readInput(built, { maxBytes: 512 * 1024 * 1024 });
    result.artifact = writePrivate(path.join(output, q.platform === 'ios' ? 'CaseOps.ipa' : 'CaseOps.aab'), artifact.bytes);
    result.postflight = adapter?.postflight ? await adapter.postflight({ artifact: result.artifact.path, expected, tools, output })
      : await inspectDistributionArtifact({ platform: q.platform, artifact: result.artifact.path, expected,
        tools: { ...tools, jarVerifier: runtime['StoreJarVerifier.java'] }, output, deadline: admissionDeadline, signingCopy: privateCopy?.path }, invoke);
    assert.equal(result.postflight.distributionSigningVerified, true, 'STORE_POSTFLIGHT_INCOMPLETE'); phase('artifact-postflight', 'passed');
    phase('source-postflight', 'running');
    sourceBudget.deadline = Math.min(Date.now() + 120000, deadline - 30000);
    const after = adapter?.source ? adapter.source() : gitSource(root, tools.git.path, sourceBudget);
    assert.deepEqual(after, source, 'STORE_SOURCE_CHANGED_DURING_BUILD'); phase('source-postflight', 'passed');
    result.observed = true; result.distributionSigningVerified = !contractOnly;
  } catch (error) {
    result.originalFailure = safeFailure(error);
    const active = result.phases.find(p => p.status === 'running'); if (active) active.status = 'failed';
    for (const p of result.phases) if (p.status === 'running') p.status = 'blocked';
    try { persist({ kind: 'failure', ...result.originalFailure }); } catch { result.persistenceFailure = true; }
  }
  finally {
    let secretCopyClosed = true;
    if (privateCopy && lastCommandCleanup) {
      try { rawReadInput(privateCopy.path, { sha256: privateCopy.sha256, privateFile: true, maxBytes: 1048576, deadline }); fs.unlinkSync(privateCopy.path); }
      catch { secretCopyClosed = false; }
    } else if (privateCopy) secretCopyClosed = false;
    if (secret) for (const name of Object.keys(secret)) secret[name] = undefined;
    delete environment.CASEOPS_UPLOAD_STORE_PASSWORD; delete environment.CASEOPS_UPLOAD_KEY_PASSWORD;
    result.cleanup = { complete: lastCommandCleanup && secretCopyClosed, ownedSecretCopyRemoved: secretCopyClosed,
      rawToolLogsRetained: false, diagnosticScope: 'exact exit/status, stream bytecounts and digests; original tool text intentionally not retained' };
    try { persist({ kind: 'completed', observed: result.observed, cleanup: result.cleanup }); } catch { result.persistenceFailure = true; }
    try { fs.closeSync(journal); } catch { result.persistenceFailure = true; }
    if (!result.cleanup.complete || result.persistenceFailure) result.observed = false;
    try { rawWritePrivate(path.join(output, 'result.json'), Buffer.from(JSON.stringify(result, null, 2) + '\n'), { deadline }); }
    catch { result.persistenceFailure = true; result.observed = false; }
  }
  return result;
}
