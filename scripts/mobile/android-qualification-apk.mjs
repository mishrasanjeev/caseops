// Runs only inside the already admitted Android signing boundary. It derives
// installable bytes; LINK-05 must independently inspect their installed signer.
import assert from 'node:assert/strict';
import path from 'node:path';
import fs from 'node:fs';
import { readInput, writePrivate, privateDirectory, checkDeadline } from './store-packaging-inputs.mjs';
import { inspectStoreZip } from './store-artifact-postflight.mjs';

export async function deriveQualificationApk({ aab, output, keystore, keyAlias, tools, deadline }, invoke) {
  checkDeadline(deadline); privateDirectory(output, { deadline });
  assert.match(keyAlias, /^[A-Za-z0-9._-]{1,100}$/);
  assert.ok(keystore && tools.java && tools.bundletool && tools.aapt2, 'QUALIFICATION_DERIVATION_INPUTS_REQUIRED');
  readInput(keystore.path, { sha256: keystore.sha256, maxBytes: 1048576, privateFile: true, deadline }).bytes.fill(0);
  readInput(aab.path, { sha256: aab.sha256, maxBytes: 512 * 1024 * 1024, deadline }).bytes.fill(0);
  const apks = path.join(output, 'qualification.apks');
  assert.equal(fs.existsSync(apks), false, 'QUALIFICATION_FRESH_APKS_REQUIRED');
  await invoke({ role: 'qualification-apk', tool: 'java', args: ['-jar', tools.bundletool.path, 'build-apks',
    '--bundle=' + aab.path, '--output=' + apks, '--mode=universal', '--aapt2=' + tools.aapt2.path,
    '--ks=' + keystore.path, '--ks-key-alias=' + keyAlias,
    '--ks-pass=env:CASEOPS_UPLOAD_STORE_PASSWORD', '--key-pass=env:CASEOPS_UPLOAD_KEY_PASSWORD'],
    cwd: output, timeoutMs: 120000 });
  checkDeadline(deadline);
  const archive = readInput(apks, { maxBytes: 512 * 1024 * 1024, deadline }); let apk;
  try {
    inspectStoreZip(archive.bytes, (row, bytes) => {
      checkDeadline(deadline);
      if (row.name.endsWith('.apk')) {
        assert.equal(row.name, 'universal.apk', 'QUALIFICATION_ONE_UNIVERSAL_APK_REQUIRED');
        assert.equal(apk, undefined, 'QUALIFICATION_ONE_UNIVERSAL_APK_REQUIRED');
        // Transfer the verified member buffer, never reopen a ZIP pathname.
        apk = writePrivate(path.join(output, 'CaseOps-qualification.apk'), bytes, { deadline });
      }
    });
    assert.ok(apk, 'QUALIFICATION_APK_MISSING');
    readInput(aab.path, { sha256: aab.sha256, maxBytes: 512 * 1024 * 1024, deadline }).bytes.fill(0);
    return { kind: 'caseops-android-qualification-apk', artifact: apk, aab,
      apks: { path: apks, sha256: archive.sha256 }, signatureClaimed: false,
      installedAcceptance: false, submissionAllowed: false };
  } finally { archive.bytes.fill(0); }
}
