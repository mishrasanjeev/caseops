import assert from 'node:assert/strict';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { browserOrigin, loginCredentials } from './browser-handoff.mjs';
import { validateFirefoxRecipe } from './firefox-handoff.mjs';
import { fixtureMfaCode } from './mfa.mjs';
import { MARKER } from './support.mjs';
import { verifiedFile } from './evidence.mjs';
export { verifiedFile } from './evidence.mjs';

export const SEARCH_KINDS = ['matter_code', 'case_number', 'filing_number', 'cnr_number', 'temporary_e_case_number'];
export const OWNER_OPERATIONS = ['disposeMatter', 'readMatterState', 'revokeMatterAccess', 'readNoteState'];
export class FixtureUnavailable extends Error {}

export function admitApplication(fixture, platform) {
  assert.ok(['android', 'ios'].includes(platform), 'NATIVE_PLATFORM_REQUIRED');
  const qaId = platform === 'android' ? 'ai.caseops.mobile.dev.localacceptance' : 'ai.caseops.mobile.dev.simulatoracceptance';
  assert.ok(['ai.caseops.mobile.dev', qaId].includes(fixture.appId), 'DEDICATED_DEV_OR_LOCAL_QA_APP_REQUIRED');
  if (fixture.appId === qaId) {
    assert.equal(fixture.environment, 'docker-integration', 'LOCAL_QA_REQUIRES_ISOLATED_DOCKER');
    assert.equal(fixture.syntheticDataOnly, true, 'LOCAL_QA_REQUIRES_SYNTHETIC_FIXTURE');
    assert.equal(fixture.coreInventory, 'native-core-2026-10-25', 'DATED_CORE_FIXTURE_REQUIRED');
  }
  return fixture.appId;
}

export function validateBuildReceipt(fixture, platform, actualHash) {
  admitApplication(fixture, platform);
  if (fixture.appId === 'ai.caseops.mobile.dev') return;
  const receipt = JSON.parse(verifiedFile(fixture.buildReceipt?.path, fixture.buildReceipt?.sha256));
  assert.equal(receipt.platform, platform, 'QA_BINARY_PLATFORM_MISMATCH');
  assert.equal(receipt.profile, platform === 'android' ? 'android-local-acceptance' : 'ios-simulator-acceptance', 'QA_BINARY_PROFILE_MISMATCH');
  assert.equal(receipt.appId, fixture.appId, 'QA_BINARY_APP_ID_MISMATCH');
  assert.equal(receipt.sourceSha, fixture.binarySourceSha, 'QA_BINARY_SOURCE_MISMATCH');
  assert.equal(receipt.sourceFingerprint, fixture.binarySourceFingerprint, 'QA_BINARY_SOURCE_FINGERPRINT_MISMATCH');
  assert.equal(receipt.automatedTest, true, 'QA_EMBEDDED_MARKER_REQUIRED');
  assert.equal(receipt.devEnabled, false, 'STANDALONE_QA_BUNDLE_REQUIRED');
  assert.equal(receipt.apiOrigin, fixture.apiOrigin, 'QA_BINARY_API_ORIGIN_MISMATCH');
  browserOrigin(fixture.apiOrigin);
  assert.equal(receipt.webOrigin, fixture.auth.webOrigin, 'QA_BINARY_WEB_ORIGIN_MISMATCH');
  assert.ok(path.isAbsolute(receipt.artifact || ''), 'ABSOLUTE_NATIVE_BINARY_REQUIRED');
  assert.equal(path.normalize(receipt.artifact), path.normalize(fixture.appPath), 'QA_BINARY_PATH_MISMATCH');
  assert.match(actualHash || '', /^[a-f0-9]{64}$/, 'QA_BINARY_HASH_REQUIRED');
  assert.equal(receipt.binaryHash, actualHash, 'QA_BINARY_HASH_MISMATCH');
  if (platform === 'android') {
    verifiedFile(fixture.publicCa?.path, fixture.publicCa?.sha256);
    assert.equal(receipt.publicCaSha256, fixture.publicCa.sha256, 'QA_BINARY_CA_MISMATCH');
  }
}

function nonempty(value) { assert.ok(typeof value === 'string' && value.trim() && value.length <= 4000, 'SEEDED_EXPECTATION_REQUIRED'); }
function matter(value) {
  assert.match(value?.id || '', /^[a-zA-Z0-9_-]{1,100}$/, 'SEEDED_MATTER_ID_REQUIRED');
  nonempty(value.identityLabel);
  nonempty(value.title);
}
export function validateCoreFixture(fixture, environment = process.env) {
  assert.equal(fixture.environment, 'docker-integration', 'REAL_DOCKER_CORE_FIXTURE_REQUIRED');
  assert.equal(fixture.syntheticDataOnly, true, 'NO_PRIVATE_FIXTURES');
  assert.equal(fixture.coreInventory, 'native-core-2026-10-25', 'DATED_CORE_FIXTURE_REQUIRED');
  for (const key of ['backendSha', 'webSha']) assert.match(fixture[key] || '', /^[0-9a-f]{40}$/, 'EXACT_SERVING_SHA_REQUIRED');
  browserOrigin(fixture.auth?.webOrigin);
  loginCredentials(fixture.auth, environment);
  if (fixture.auth.mfaRequired) fixtureMfaCode(fixture.auth, environment);
  assert.ok(['web-context', 'native-firefox'].includes(fixture.auth.mode), 'EXPLICIT_BROWSER_AUTOMATION_MODE_REQUIRED');
  if (fixture.auth.mode === 'native-firefox') validateFirefoxRecipe(fixture.auth);
  assert.equal(fixture.browserApiMarkerVerified, true, 'BROWSER_API_MARKER_RECEIPT_REQUIRED');
  const evidence = JSON.parse(verifiedFile(fixture.isolationEvidence?.path, fixture.isolationEvidence?.sha256));
  assert.equal(evidence.environment, 'docker-integration', 'REAL_DOCKER_FIXTURE_RECEIPT_REQUIRED');
  for (const key of ['backendSha', 'backendRevision', 'gatewayRunId']) {
    assert.equal(evidence[key], fixture[key], 'ISOLATED_FIXTURE_RELEASE_MISMATCH');
    nonempty(fixture[key]);
  }
  assert.equal(evidence.webIdentity?.service, 'web', 'WEB_IDENTITY_REQUIRED');
  assert.equal(evidence.webIdentity.release_sha, fixture.webSha, 'ISOLATED_FIXTURE_RELEASE_MISMATCH');
  assert.equal(evidence.webIdentity.revision, fixture.webRevision, 'ISOLATED_FIXTURE_RELEASE_MISMATCH');
  assert.equal(evidence.webAcceptanceMarkerBuild, true, 'EXPLICIT_LOCAL_BROWSER_MARKER_REQUIRED');
  assert.equal(evidence.productionAccessed, false, 'NO_PRODUCTION_FIXTURE_REQUIRED');
  assert.equal(evidence.metroLaunched, false, 'NO_METRO_POLICY_BYPASS');
  assert.ok(Array.isArray(evidence.containers) && evidence.containers.length >= 3 && evidence.containers.length <= 16, 'OWNED_DOCKER_INVENTORY_REQUIRED');
  for (const container of evidence.containers) {
    assert.equal(container.project, evidence.project, 'FOREIGN_DOCKER_PROJECT');
    assert.match(container.image || '', /^sha256:[a-f0-9]{64}$/, 'EXACT_DOCKER_IMAGE_REQUIRED');
    assert.ok(container.name?.startsWith(`/${evidence.project}-`), 'FOREIGN_DOCKER_CONTAINER');
    assert.ok(Array.isArray(container.networks) && container.networks.length > 0, 'DOCKER_NETWORK_INVENTORY_REQUIRED');
  }
  for (const service of ['api', 'web', 'postgres']) {
    assert.equal(evidence.containers.filter((container) => new RegExp(`-${service}-[0-9]+$`).test(container.name)).length, 1, 'DOCKER_SERVICE_INVENTORY_MISMATCH');
  }
  assert.equal(evidence.syntheticDataOnly, true, 'NO_PRIVATE_FIXTURES');
  if (fixture.seedEvidence) {
    const seed = JSON.parse(verifiedFile(fixture.seedEvidence.path, fixture.seedEvidence.sha256));
    assert.equal(seed.environment, 'docker-integration', 'REAL_SEED_RECEIPT_REQUIRED');
    assert.equal(seed.syntheticDataOnly, true, 'NO_PRIVATE_FIXTURES');
    for (const key of ['principalLabel', 'workspaceLabel', 'companyId', 'membershipId']) assert.equal(fixture[key], seed[key], 'SEED_IDENTITY_MISMATCH');
    for (const key of ['id', 'identityLabel', 'search']) assert.equal(fixture.matter?.[key], seed.matter?.[key], 'SEED_MATTER_MISMATCH');
    assert.equal(fixture.today?.id, seed.taskId, 'SEED_TASK_MISMATCH');
    assert.equal(fixture.work?.task?.id, seed.taskId, 'SEED_TASK_MISMATCH');
    assert.equal(fixture.work?.draft?.id, seed.draftId, 'SEED_DRAFT_MISMATCH');
    assert.equal(fixture.calendar?.day, seed.calendarDate, 'SEED_CALENDAR_MISMATCH');
    if (fixture.foreignMatter) assert.equal(fixture.foreignMatter.id, seed.otherMatterId, 'SEED_FOREIGN_MATTER_MISMATCH');
  }
  matter(fixture.matter);
  assert.deepEqual(fixture.matter.searches?.map((item) => item.kind), SEARCH_KINDS, 'EXACT_SUPPORTED_SEARCH_FIXTURES_REQUIRED');
  for (const item of fixture.matter.searches) nonempty(item.value);
  assert.equal(new Set(fixture.matter.searches.map((item) => item.value)).size, SEARCH_KINDS.length, 'DISTINCT_SEARCH_IDENTIFIERS_REQUIRED');
  for (const item of [fixture.today, fixture.work?.task]) {
    assert.match(item?.id || '', /^[a-zA-Z0-9_-]{1,100}$/, 'SEEDED_WORK_ID_REQUIRED');
    assert.ok(['task', 'draft', 'hearing', 'deadline'].includes(item.kind), 'REAL_WORK_KIND_REQUIRED');
    matter(item.matter);
    nonempty(item.title);
    nonempty(item.metaLabel);
  }
  assert.equal(fixture.today.kind, 'task', 'MEANINGFUL_TODAY_TASK_REQUIRED');
  for (const key of ['dueOn', 'dateLabel', 'status']) nonempty(fixture.today[key]);
  assert.match(fixture.today.dueOn, /^\d{4}-\d{2}-\d{2}$/, 'DATED_TODAY_TASK_REQUIRED');
  assert.ok(fixture.today.metaLabel.includes(fixture.today.dateLabel) && fixture.today.metaLabel.includes(fixture.today.status), 'MEANINGFUL_TODAY_DATE_STATUS_REQUIRED');
  assert.equal(fixture.work.task.kind, 'task', 'WORK_TASK_REQUIRED');
  const draft = fixture.work.draft;
  assert.equal(draft?.kind, 'draft', 'WORK_DRAFT_REQUIRED');
  matter(draft.matter);
  assert.match(draft.id || '', /^[a-zA-Z0-9_-]{1,100}$/, 'SEEDED_DRAFT_ID_REQUIRED');
  assert.ok(['matter-work', 'reviews'].includes(draft.entry), 'REAL_DRAFT_ENTRY_REQUIRED');
  nonempty(draft.title);
  if (draft.entry === 'reviews') nonempty(draft.metaLabel);
  else assert.equal(draft.matter.id, fixture.work.task.matter.id, 'DRAFT_TASK_SOURCE_MISMATCH');
  for (const key of ['revisionLabel', 'body', 'statusLabel']) nonempty(draft[key]);
  assert.ok(Array.isArray(draft.citations) && draft.citations.length <= 20, 'SEEDED_DRAFT_CITATIONS_REQUIRED');
  for (const citation of draft.citations) nonempty(citation);
  nonempty(draft.verifiedCitationCountLabel);
  matter(fixture.calendar?.matter);
  assert.match(fixture.calendar.day, /^\d{4}-\d{2}-\d{2}$/, 'SEEDED_CALENDAR_DAY_REQUIRED');
  for (const key of ['dayLabel', 'title', 'metaLabel', 'nextHearingLabel']) nonempty(fixture.calendar[key]);
  // Negative records must come from the seed ledger too, not invented UUID probes.
  for (const key of ['foreignMatter', 'lifecycleMatter', 'accessMatter']) {
    if (fixture[key]) {
      matter(fixture[key]); nonempty(fixture[key].search);
      assert.notEqual(fixture[key].id, fixture.matter.id, 'NEGATIVE_TARGET_MUST_BE_SEPARATE');
    }
  }
  if (fixture.lifecycleMatter && fixture.accessMatter) assert.notEqual(fixture.lifecycleMatter.id, fixture.accessMatter.id, 'NEGATIVE_TARGETS_MUST_BE_DISTINCT');
  return fixture;
}

export async function loadOwnerControls(fixture) {
  if (!fixture.ownerControls) return null;
  const { modulePath, sha256, capabilities } = fixture.ownerControls;
  verifiedFile(modulePath, sha256);
  assert.ok(Array.isArray(capabilities) && capabilities.length > 0 && capabilities.every((operation) => OWNER_OPERATIONS.includes(operation)), 'INVALID_OWNER_CAPABILITY');
  assert.equal(new Set(capabilities).size, capabilities.length, 'DUPLICATE_OWNER_CAPABILITY');
  const adapter = await import(`${pathToFileURL(modulePath).href}?sha256=${sha256}`);
  assert.equal(typeof adapter.control, 'function', 'REAL_FIXTURE_CONTROL_REQUIRED');
  return { control: adapter.control, capabilities };
}

export async function ownerControl(context, operation, targetId) {
  if (!context.owner?.capabilities.includes(operation)) throw new FixtureUnavailable('FIXTURE_OWNER_CAPABILITY_UNAVAILABLE');
  assert.ok(OWNER_OPERATIONS.includes(operation), 'INVALID_OWNER_CAPABILITY');
  assert.equal(context.fixture.environment, 'docker-integration', 'REAL_DOCKER_OWNER_REQUIRED');
  assert.notEqual(context.owner.poisoned, true, 'OWNER_CONTROL_PREVIOUSLY_UNCERTAIN');
  const allowed = [(['disposeMatter', 'readMatterState'].includes(operation)
    ? context.fixture.lifecycleMatter : context.fixture.accessMatter)?.id].filter(Boolean);
  assert.ok(allowed.includes(targetId), 'UNOWNED_FIXTURE_TARGET');
  const signal = AbortSignal.timeout(10000);
  let receipt;
  try {
    receipt = await Promise.race([
      context.owner.control({ operation, targetId, runId: context.runId, backendSha: context.fixture.backendSha, marker: MARKER, signal }),
      new Promise((_, reject) => signal.addEventListener('abort', () => reject(new Error('OWNER_CONTROL_DEADLINE')), { once: true })),
    ]);
  } catch (error) { context.owner.poisoned = true; throw error; }
  assert.ok(JSON.stringify(receipt).length <= 65536, 'OWNER_RECEIPT_BOUND');
  assert.equal(receipt.kind, 'docker-owner-control', 'REAL_OWNER_RECEIPT_REQUIRED');
  for (const [key, expected] of Object.entries({ operation, targetId, runId: context.runId, backendSha: context.fixture.backendSha })) {
    assert.equal(receipt[key], expected, 'OWNER_RECEIPT_IDENTITY_MISMATCH');
  }
  verifiedFile(receipt.evidencePath, receipt.evidenceSha256);
  context.record?.({ type: 'assertion', boundary: 'fixture-owner-control', operation, evidenceSha256: receipt.evidenceSha256 });
  return receipt.result;
}
