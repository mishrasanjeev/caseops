import { mkdirSync, writeFileSync, realpathSync, existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
const require = createRequire(import.meta.url);
const { readNativeLinkConfig } = require('../../apps/web/lib/native-link-config.cjs');

export function prepareNativeLinks({ file, sha256, output, synthetic = false }) {
  const loaded = readNativeLinkConfig({ CASEOPS_NATIVE_LINK_CONFIG_FILE: file, CASEOPS_NATIVE_LINK_CONFIG_SHA256: sha256 }, { allowSynthetic: synthetic });
  if (loaded.config.syntheticDataOnly !== synthetic) throw new Error('EXPLICIT_SYNTHETIC_MODE_MUST_MATCH_CONFIG');
  if (!path.isAbsolute(output) || existsSync(output)) throw new Error('NEW_ABSOLUTE_LINK_OUTPUT_REQUIRED');
  const parent = realpathSync(path.dirname(output));
  const environment = { ...Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith('GIT_'))), LC_ALL: 'C', LANG: 'C' };
  const probe = spawnSync('git', ['rev-parse', '--is-inside-work-tree'], { cwd: parent, encoding: 'utf8', timeout: 5000, env: environment });
  if (probe.error || probe.status !== 128 || !/not a git repository/.test(probe.stderr)) throw new Error('PUBLIC_LINK_OUTPUT_MUST_REMAIN_OUTSIDE_GIT');
  mkdirSync(output, { mode: 0o700 });
  // Copy only the same already-verified descriptor bytes, not a second path read.
  // This is a public input; the loader returns its exact canonical byte buffer.
  writeFileSync(path.join(output, 'config-evidence.json'), loaded.bytes, { flag: 'wx', mode: 0o444 });
  const outputs = { 'projections.json': loaded.projections,
    'apple-app-site-association': loaded.projections.appleAppSiteAssociation,
    'assetlinks.json': loaded.projections.assetlinks,
    'api-environment.json': loaded.projections.apiEnvironment };
  for (const [name, value] of Object.entries(outputs)) writeFileSync(path.join(output, name), JSON.stringify(value, null, 2) + '\n', { flag: 'wx', mode: 0o444 });
  const receipt = { schemaVersion: 1, kind: 'caseops-native-link-projections', configSha256: loaded.sha256,
    configEvidence: { path: path.join(output, 'config-evidence.json'), sha256: loaded.sha256 },
    syntheticDataOnly: synthetic, platformAssociationVerified: false, productionEnabled: false,
    files: Object.entries(outputs).map(([name, value]) => { const bytes = Buffer.from(JSON.stringify(value, null, 2) + '\n');
      return { name, sha256: createHash('sha256').update(bytes).digest('hex'), sizeBytes: bytes.length }; }) };
  writeFileSync(path.join(output, 'receipt.json'), JSON.stringify(receipt, null, 2) + '\n', { flag: 'wx', mode: 0o444 });
  return receipt;
}

export function main(args = process.argv.slice(2)) {
  const options = {}, allowed = new Set(['--config', '--sha256', '--output']);
  let synthetic = false;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--synthetic' && !synthetic) { synthetic = true; continue; }
    if (!allowed.has(args[i]) || options[args[i]] || !args[i + 1] || args[i + 1].startsWith('--')) throw new Error('EXACT_NATIVE_LINK_ARGUMENTS_REQUIRED');
    options[args[i]] = args[++i];
  }
  if (Object.keys(options).length !== 3) throw new Error('EXACT_NATIVE_LINK_ARGUMENTS_REQUIRED');
  console.log(JSON.stringify(prepareNativeLinks({ file: options['--config'], sha256: options['--sha256'], output: options['--output'], synthetic })));
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { main(); } catch (error) { console.error(error.message); process.exitCode = 1; }
}
