import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { FixtureUnavailable } from './fixture-contract.mjs';
import { collectFiles, expandSourceDetails, inventory, scenarios, source, uploadFilesSource, validateFilesContext, validateSourceAnchor, validateSourceReceipt } from './files-20261025.mjs';
import { selector } from './native-ui.mjs';

// Sidecar unit/discovery tests only. No driver, browser, Appium or HTTP is run.
test('files supplement reconciles its independent exact inventory without changing the 23-case core', () => {
  assert.deepEqual(collectFiles().intended, ['android:FILES-01', 'android:FILES-02']);
  assert.deepEqual(collectFiles().discovered, ['android:FILES-01', 'android:FILES-02']);
  assert.deepEqual(scenarios.map(({ id }) => id), ['FILES-01', 'FILES-02']);
  assert.equal(inventory.cases[1].blocked, 'ANDROID_PICKER_AND_UPLOAD_EVIDENCE_REQUIRED');
  assert.throws(() => collectFiles('ios'), /FILES_ANDROID_ONLY/);
  const core = JSON.parse(readFileSync(new URL('./core-20261025.json', import.meta.url), 'utf8'));
  assert.equal(core.cases.length, 23);
  assert.equal(core.cases.some(({ id }) => id.startsWith('FILES-')), false);
});

test('files source pin matches owner supplied identities and exact committed unverified CLEAN text/hash', () => {
  assert.equal(source.matterId, 'e7cd2909-f8a3-4e6d-88e3-571711046eb4');
  assert.equal(source.attachmentId, '26bdc03b-6e23-410b-b961-d5410f15466d');
  assert.equal(source.sha256, '32df2bb8255ed04c167cd8c99bcd471b606b44aea770cc3612b13e86d8613fd6');
  const seed = readFileSync(new URL('../../../scripts/mobile/local-fixture.py', import.meta.url), 'utf8');
  assert.ok(seed.includes('CLEAN = b"Synthetic CaseOps mobile source. No legal authority or customer data.\\n"'));
  assert.equal(createHash('sha256').update(source.text).digest('hex'), source.sha256);
  validateSourceAnchor();
  for (const key of ['matterId', 'attachmentId', 'sha256', 'filename', 'text'])
    assert.throws(() => validateSourceAnchor({ ...source, [key]: '' }), /FILES_SOURCE_ANCHOR_MISMATCH/);
});

test('files supplement missing/native/production prerequisites remain blocked, not empty success', () => {
  for (const context of [undefined, {}, { platform: 'ios' }, { platform: 'android', fixture: { environment: 'production', syntheticDataOnly: true } },
    { platform: 'android', fixture: { environment: 'docker-integration', syntheticDataOnly: false } }])
    assert.throws(() => validateFilesContext(context), FixtureUnavailable);
});

test('independent source seed receipt binds the actual source identity/hash and positive seed readback before UI expectations', () => {
  const unitReceipt = { environment: 'docker-integration', syntheticDataOnly: true, matter: { id: source.matterId },
    sourceId: source.attachmentId, sourceSha256: source.sha256, cleanUploadAndDownload: true };
  validateSourceReceipt(unitReceipt); // Contract test only, not a backend receipt.
  for (const delta of [{ sourceId: '' }, { sourceSha256: '' }, { matter: null }, { cleanUploadAndDownload: false },
    { environment: 'production' }, { syntheticDataOnly: false }])
    assert.throws(() => validateSourceReceipt({ ...unitReceipt, ...delta }));
});

test('actual source components still own every fixed selector used by the supplemental read journey', () => {
  const files = readFileSync(new URL('../src/application/screens/FilesScreen.tsx', import.meta.url), 'utf8');
  const viewer = readFileSync(new URL('../src/viewer/PrivateDocumentViewer.tsx', import.meta.url), 'utf8');
  const matter = readFileSync(new URL('../src/application/screens/MatterScreen.tsx', import.meta.url), 'utf8');
  for (const id of ['files-matter-code', 'files-matter-title', 'files-reload', 'files-choose', 'files-row-', 'files-name-', 'files-source-', 'files-hash-', 'files-open-'])
    assert.ok(files.includes(`testID="${id}"`) || files.includes('testID={`' + id), 'SOURCE_OWNED_FILES_SELECTOR_MISSING');
  for (const id of ['private-document-viewer', 'viewer-filename', 'viewer-position', 'viewer-text', 'viewer-close'])
    assert.ok(viewer.includes(`testID="${id}"`), 'SOURCE_OWNED_VIEWER_SELECTOR_MISSING');
  assert.ok(matter.includes('`matter-${value.toLowerCase()}`'));
});

test('unknown picker/upload path is explicitly blocked without executing an invented native or API operation', async () => {
  await assert.rejects(uploadFilesSource(), (error) => error instanceof FixtureUnavailable && error.message === 'ANDROID_PICKER_AND_UPLOAD_EVIDENCE_REQUIRED');
});

test('Compose source-details wrapper text is never read; exact visible child caption is scoped to that control', async () => {
  for (const expanded of [false, true]) {
    const queried = [];
    let clicked = 0;
    const expected = selector('android', 'text', expanded ? 'Hide source details' : 'Source details');
    const control = {
      getText() { assert.fail('COMPOSE_WRAPPER_TEXT_MUST_NOT_BE_READ'); },
      async $$(query) {
        queried.push(query);
        return query === expected ? [{ async isDisplayed() { return true; }, async click() { clicked++; } }] : [];
      },
    };
    await expandSourceDetails(control, 'android');
    assert.deepEqual(queried, [selector('android', 'text', 'Source details'), selector('android', 'text', 'Hide source details')]);
    assert.equal(clicked, expanded ? 0 : 1);
  }
});

test('missing, invisible, duplicate or contradictory exact source-details captions fail without a fallback click', async () => {
  for (const state of ['missing', 'invisible', 'duplicate', 'contradictory']) {
    let clicked = 0;
    const child = { async isDisplayed() { return state !== 'invisible'; }, async click() { clicked++; } };
    const control = { async $$(query) {
      if (state === 'missing') return [];
      if (state === 'contradictory') return [child];
      return query === selector('android', 'text', 'Source details') ? (state === 'duplicate' ? [child, child] : [child]) : [];
    } };
    await assert.rejects(expandSourceDetails(control, 'android'), state === 'duplicate' ? /AMBIGUOUS_VISIBLE_NATIVE_LOCATOR/ : /FILES_SOURCE_DETAILS_STATE_UNOBSERVED/);
    assert.equal(clicked, 0);
  }
});
