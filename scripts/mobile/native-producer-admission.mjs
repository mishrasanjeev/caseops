import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { readdirSync } from 'node:fs';
import { sourceSnapshot } from './source-snapshot.mjs';
import { binaryHash } from '../../apps/mobile/e2e/support.mjs';
import { validateBuildReceipt } from '../../apps/mobile/e2e/fixture-contract.mjs';
import { readProducerReference } from './native-producer-host.mjs';
import { verifiedFile } from '../../apps/mobile/e2e/evidence.mjs';

const ROOT = path.resolve(fileURLToPath(new URL('../../', import.meta.url)));
export function producerCodeInputs(extra = []) {
  return [...new Set(['scripts/mobile/native-producer-host.mjs','scripts/mobile/native-producer-admission.mjs','scripts/mobile/source-snapshot.mjs',
    'scripts/mobile/run-v1-workflows.mjs','scripts/mobile/android-files-privacy.mjs','scripts/mobile/android-qa-observer.mjs','scripts/mobile/camera-files-privacy.mjs',
    ...readdirSync(path.join(ROOT,'apps/mobile/e2e')).filter(x => /\.(mjs|json)$/.test(x)).map(x => 'apps/mobile/e2e/'+x), ...extra])].sort();
}
/** Called before opening any actor credential. Actual installed observation is
 * read afresh through the existing native attestor; this never installs. */
export async function admitProducerPublic(config, { requiredInputs = [], snapshot = sourceSnapshot, installed } = {}) {
  assert.equal(config.repoRoot, ROOT, 'PRODUCER_EXACT_CHECKOUT_REQUIRED');
  assert.ok(['android','ios'].includes(config.platform));
  const expected = config.source;
  assert.equal(expected.sourceDirty,false); assert.match(expected.sourceSha,/^[a-f0-9]{40}$/);
  assert.deepEqual(snapshot(ROOT),expected,'PRODUCER_SOURCE_CHANGED');
  const build = readProducerReference(config.buildReceipt), docker = readProducerReference(config.dockerReceipt), prior = readProducerReference(config.installedEvidence);
  assert.equal(docker.environment,'docker-integration'); assert.equal(docker.syntheticDataOnly,true);
  assert.equal(docker.productionAccessed,false); assert.equal(docker.metroLaunched,false);
  assert.equal(build.sourceSha,expected.sourceSha); assert.equal(build.sourceFingerprint,expected.sourceFingerprint);
  assert.equal(build.inputFileCount,expected.inputFileCount);
  assert.equal(build.sourceDirty,false); assert.equal(build.platform,config.platform);
  assert.equal(build.devEnabled,false); assert.equal(build.automatedTest,true);
  for (const scope of ['api','web']) {
    assert.equal(docker[scope === 'api' ? 'backendSha' : 'webSha'],expected.sourceSha);
    assert.equal(docker.source[scope].head,expected.sourceSha); assert.equal(docker.source[scope].dirty,false);
  }
  assert.equal(binaryHash(build.artifact),build.binaryHash,'PRODUCER_ARTIFACT_CHANGED');
  const fixture = { ...config.deviceTarget, environment:'docker-integration',syntheticDataOnly:true,coreInventory:'native-core-2026-10-25',
    appPath:build.artifact,appId:build.appId,buildReceipt:config.buildReceipt,binarySourceSha:expected.sourceSha,binarySourceFingerprint:expected.sourceFingerprint,
    apiOrigin:build.apiOrigin,auth:{webOrigin:build.webOrigin},publicCa:config.publicCa };
  validateBuildReceipt(fixture,config.platform,build.binaryHash);
  const observe = installed ?? (await import('./run-v1-workflows.mjs')).observeInstalled;
  const actual = observe(fixture,config.platform,build.binaryHash,process.env);
  assert.equal(actual.udid,config.deviceTarget.udid); assert.equal(actual.appId,build.appId); assert.equal(actual.binaryHash,build.binaryHash);
  for (const [key,value] of Object.entries(actual)) assert.deepEqual(prior[key],value,'PRODUCER_INSTALLED_OBSERVATION_CHANGED');
  const closure = readProducerReference(config.codeClosure), inputs = producerCodeInputs(requiredInputs).map(x => path.join(ROOT,x));
  assert.deepEqual(closure.code.map(x => x.path).sort(),inputs,'PRODUCER_COMPLETE_CODE_CLOSURE_REQUIRED');
  for (const ref of closure.code) verifiedFile(ref.path,ref.sha256);
  assert.deepEqual(snapshot(ROOT),expected,'PRODUCER_SOURCE_CHANGED');
  return { source:expected,build,docker,installed:actual,fixture };
}
