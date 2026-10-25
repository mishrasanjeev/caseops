import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { verifiedFile } from './evidence.mjs';
import { admitApplication, SEARCH_KINDS, validateBuildReceipt, validateCoreFixture } from './fixture-contract.mjs';
import { binaryHash, safeFailure } from './support.mjs';
import { collect } from './suite.mjs';

const allCases = collect('android').intended.map((id) => id.split(':')[1]);
function noEmbeddedSecrets(value) {
  if (!value || typeof value !== 'object') return;
  for (const [key, nested] of Object.entries(value)) {
    assert.ok(!/^(password|access_token|refresh_token|totp_secret|code_verifier|cookies)$/i.test(key), 'SECRET_VALUE_FORBIDDEN_IN_RUN_PLAN');
    noEmbeddedSecrets(nested);
  }
}
function readReference(reference) { return JSON.parse(verifiedFile(reference?.path, reference?.sha256)); }
function nonempty(value) { return typeof value === 'string' && !!value.trim(); }

export function inspectLocalPlan(plan, platform, environment = process.env) {
  noEmbeddedSecrets(plan);
  assert.equal(plan.schemaVersion, 1, 'LOCAL_RUN_PLAN_VERSION_REQUIRED');
  const collection = collect(platform), blockers = [];
  const block = (code, fields, cases = allCases) => blockers.push({ code, fields, cases });
  const receipt = readReference(plan.dockerReceipt), seed = readReference(plan.seed);
  assert.equal(receipt.environment, 'docker-integration', 'REAL_DOCKER_FIXTURE_REQUIRED');
  assert.equal(seed.syntheticDataOnly, true, 'NO_PRIVATE_FIXTURES');
  let build;
  if (plan.buildReceipt) build = readReference(plan.buildReceipt);
  else block('STANDALONE_BUILD_RECEIPT_MISSING', ['buildReceipt']);
  const expected = plan.expectations || {}, sourceMatter = seed.matter;
  const matter = { ...expected.matter, id: sourceMatter.id, identityLabel: sourceMatter.identityLabel, search: sourceMatter.search };
  const suppliedSearches = expected.matter?.searches || [];
  const suppliedCode = suppliedSearches.find((search) => search.kind === 'matter_code');
  if (suppliedCode) assert.equal(suppliedCode.value, sourceMatter.identityLabel, 'PRIMARY_SEARCH_MUST_MATCH_SEED');
  matter.searches = SEARCH_KINDS.map((kind) => kind === 'matter_code' ? { kind, value: sourceMatter.identityLabel }
    : suppliedSearches.find((search) => search.kind === kind) || { kind });
  const matterRef = { id: matter.id, identityLabel: matter.identityLabel, title: matter.title };
  const fixture = {
    coreInventory: collection.inventoryId, environment: receipt.environment, syntheticDataOnly: receipt.syntheticDataOnly,
    backendSha: receipt.backendSha, backendRevision: receipt.backendRevision,
    webSha: receipt.webIdentity?.release_sha, webRevision: receipt.webIdentity?.revision,
    gatewayUrl: receipt.gatewayUrl, gatewayRunId: receipt.gatewayRunId, webGatewayUrl: receipt.webGatewayUrl,
    apiOrigin: receipt.apiOrigin, isolationEvidence: plan.dockerReceipt, seedEvidence: plan.seed,
    buildReceipt: plan.buildReceipt, publicCa: plan.publicCa,
    appId: plan.appId, appPath: build?.artifact, binarySourceSha: build?.sourceSha,
    binarySourceFingerprint: build?.sourceFingerprint,
    binaryVersion: plan.binaryVersion, binaryBuild: plan.binaryBuild,
    deviceName: plan.device?.deviceName, platformVersion: plan.device?.platformVersion, udid: plan.device?.udid,
    principalLabel: seed.principalLabel, workspaceLabel: seed.workspaceLabel,
    companyId: seed.companyId, membershipId: seed.membershipId,
    browserApiMarkerVerified: receipt.webAcceptanceMarkerBuild === true && receipt.webMarkerTransportSourcePresent === true,
    auth: { ...plan.auth, webOrigin: receipt.webOrigin, mfaRequired: seed.mfaEnrolled === true },
    matter, noteRoute: `/api/matters/${matter.id}/notes`, matterReloadRoute: `/api/matters/${matter.id}/workspace`,
    today: expected.today ? { ...expected.today, id: seed.taskId, kind: 'task', matter: matterRef } : undefined,
    work: expected.work ? {
      task: { ...expected.work.task, id: seed.taskId, kind: 'task', matter: matterRef },
      draft: { ...expected.work.draft, id: seed.draftId, kind: 'draft', matter: matterRef },
    } : undefined,
    calendar: expected.calendar ? { ...expected.calendar, hearingId: seed.hearingId, day: seed.calendarDate, matter: matterRef } : undefined,
    foreignMatter: expected.foreignMatter ? { ...expected.foreignMatter, id: seed.otherMatterId } : undefined,
    lifecycleMatter: expected.lifecycleMatter, accessMatter: expected.accessMatter, ownerControls: plan.ownerControls,
  };
  admitApplication(fixture, platform);
  if (plan.firefoxRecipe) {
    fixture.auth.firefoxUi = readReference(plan.firefoxRecipe);
    if (fixture.auth.firefoxUi.status !== 'complete') block('FIREFOX_RECIPE_INCOMPLETE', ['firefoxRecipe']);
  }
  else if (fixture.auth.mode === 'native-firefox') block('OBSERVED_FIREFOX_RECIPE_MISSING', ['firefoxRecipe']);
  for (const key of ['backendSha', 'webSha']) if (!/^[a-f0-9]{40}$/.test(fixture[key] || '')) block('EXACT_SERVING_SHA_UNAVAILABLE', [key]);
  if (receipt.source?.api?.dirty || receipt.source?.web?.dirty) block('SERVING_SOURCE_NOT_FROZEN', ['dockerReceipt.source']);
  if (!plan.publicCa) block('PUBLIC_CA_REFERENCE_MISSING', ['publicCa']);
  for (const key of ['binaryVersion', 'binaryBuild', 'deviceName', 'platformVersion', 'udid']) if (!nonempty(fixture[key])) block('BINARY_OR_DEVICE_METADATA_MISSING', [key]);
  if (!nonempty(matter.title)) block('MATTER_TITLE_EXPECTATION_MISSING', ['expectations.matter.title'], ['NATIVE-03', ...allCases.slice(3, 20)]);
  const searches = matter.searches || [];
  for (const [index, kind] of SEARCH_KINDS.entries()) {
    const item = searches.find((search) => search.kind === kind);
    if (!nonempty(item?.value)) block('EXACT_SEARCH_IDENTIFIER_EXPECTATION_MISSING', [`expectations.matter.searches.${kind}`], [`NATIVE-${String(index + 4).padStart(2, '0')}`]);
  }
  for (const [key, cases] of [['today', ['NATIVE-03']], ['work', ['NATIVE-12']], ['calendar', ['NATIVE-10', 'NATIVE-11']],
    ['foreignMatter', ['NATIVE-19']], ['lifecycleMatter', ['NATIVE-17']], ['accessMatter', ['NATIVE-18']]]) {
    if (!expected[key]) block('CANONICAL_EXPECTATION_OR_NEGATIVE_TARGET_MISSING', [`expectations.${key}`], cases);
  }
  if (!plan.ownerControls) block('REAL_BOUNDED_OWNER_CONTROLS_MISSING', ['ownerControls'], ['NATIVE-17', 'NATIVE-18']);
  else {
    try {
      verifiedFile(plan.ownerControls.modulePath, plan.ownerControls.sha256);
      for (const operation of ['disposeMatter', 'readMatterState', 'revokeMatterAccess', 'readNoteState']) {
        assert.ok(plan.ownerControls.capabilities?.includes(operation), 'REAL_BOUNDED_OWNER_CONTROLS_MISSING');
      }
    } catch (error) { block(safeFailure(error, 'OWNER_CONTROL_EVIDENCE_INVALID'), ['ownerControls'], ['NATIVE-17', 'NATIVE-18']); }
  }
  if (plan.gatewayRoutes) {
    const routes = readReference(plan.gatewayRoutes).routes;
    assert.ok(Array.isArray(routes), 'GATEWAY_ROUTE_INVENTORY_REQUIRED');
    if (!routes.includes('GET /api/auth/native/sessions')) block('DEVICE_SESSION_LIST_ROUTE_MISSING', ['gatewayRoutes'], ['NATIVE-20']);
    if (!routes.some((route) => /^DELETE \/api\/auth\/native\/sessions\/[a-zA-Z0-9_-]{1,100}$/.test(route))) {
      block('CURRENT_SESSION_DELETE_ADMISSION_MISSING', ['gatewayRoutes'], ['NATIVE-20']);
    }
  } else block('PINNED_GATEWAY_ROUTE_INVENTORY_MISSING', ['gatewayRoutes'], ['NATIVE-20', 'NATIVE-21']);
  for (const key of ['emailEnv', 'passwordEnv', ...(fixture.auth.mfaRequired ? ['totpSecretEnv'] : [])]) {
    const name = fixture.auth[key];
    if (!/^CASEOPS_MOBILE_[A-Z0-9_]+$/.test(name || '') || !environment[name]) block('BROWSER_CREDENTIAL_ENVIRONMENT_NOT_LOADED', [`auth.${key}`]);
  }
  if (!nonempty(plan.outputFixture) || !path.isAbsolute(plan.outputFixture)) block('ABSOLUTE_OUTPUT_FIXTURE_REQUIRED', ['outputFixture']);
  if (blockers.length === 0) {
    try {
      validateCoreFixture(fixture, environment);
      validateBuildReceipt(fixture, platform, binaryHash(fixture.appPath));
    } catch (error) { block(safeFailure(error, 'FIXTURE_CONTRACT_VALIDATION_FAILED'), ['assembledFixture']); }
  }
  return { fixture, readiness: { schemaVersion: 1, mode: 'offline-local-preparation', ...collection,
    status: blockers.length ? 'incomplete' : 'ready-for-native-preflight', blockers,
    observed: { backendSha: fixture.backendSha, backendRevision: fixture.backendRevision,
      webSha: fixture.webSha, webRevision: fixture.webRevision, appId: fixture.appId },
    credentialFilesRead: false, credentialValuesPrinted: false, nativeExecution: 'not-run', servicesChanged: false } };
}

export function prepareLocalPlan(plan, platform, environment = process.env) {
  const result = inspectLocalPlan(plan, platform, environment);
  if (result.readiness.status !== 'ready-for-native-preflight') return result;
  const target = path.resolve(plan.outputFixture), root = fileURLToPath(new URL('../../../', import.meta.url));
  const relative = path.relative(root, target);
  assert.ok(relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative), 'FIXTURE_OUTPUT_MUST_STAY_OUTSIDE_REPOSITORY');
  mkdirSync(path.dirname(target), { recursive: true });
  writeFileSync(target, `${JSON.stringify(result.fixture, null, 2)}\n`, { flag: 'wx' });
  result.readiness.fixturePath = target;
  return result;
}
