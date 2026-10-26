import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export function sourceSnapshot(root = fileURLToPath(new URL('../../', import.meta.url))) {
  const paths = ['apps/mobile', 'package.json', 'package-lock.json',
    'scripts/mobile/build-acceptance.mjs', 'scripts/mobile/build-android-local-acceptance.ps1',
    'scripts/mobile/build-android-local-acceptance.sh',
    'scripts/mobile/generate-app-icons.mjs',
    'scripts/mobile/build-ios-simulator-acceptance.sh', 'scripts/mobile/source-snapshot.mjs',
    'scripts/mobile/windows-native-paths.gradle', 'scripts/mobile/use-android-env.ps1',
    'scripts/mobile/android-tooling.ps1', 'scripts/mobile/prepare-viewer-assets.mjs',
    'scripts/mobile/prepare-native-links.mjs',
    'apps/web/lib/native-link-policy.cjs', 'apps/web/lib/native-link-policy.d.cts',
    'apps/web/lib/native-link-config.cjs', 'apps/web/lib/native-link-config.d.cts'];
  const files = execFileSync('git', ['ls-files', '-z', '--cached', '--others', '--exclude-standard', '--', ...paths], {
    cwd: root, encoding: 'utf8', timeout: 5000, maxBuffer: 1048576,
  }).split('\0').filter((file) => file && !/\/(e2e|node_modules|\.expo|dist|build)\//.test(file)
    && !/(^|\/)\.(env[^/]*|npmrc)$|\.(key|pem|jks|keystore|p12|mobileprovision)$|credentials[^/]*\.json|google-services\.json|GoogleService-Info/i.test(file));
  if (!files.length || files.length > 5000) throw new Error('SOURCE_INVENTORY_BOUND');
  const hash = createHash('sha256');
  for (const file of [...new Set(files)].sort()) {
    const content = readFileSync(path.join(root, file));
    hash.update(`${file}\0${createHash('sha256').update(content).digest('hex')}\0`);
  }
  const sourceSha = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8', timeout: 5000 }).trim();
  const dirty = Boolean(execFileSync('git', ['status', '--porcelain', '--untracked-files=all', '--', ...paths], {
    cwd: root, encoding: 'utf8', timeout: 5000, maxBuffer: 1048576,
  }).trim());
  return { sourceSha, sourceFingerprint: hash.digest('hex'), sourceDirty: dirty, inputFileCount: files.length };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) console.log(JSON.stringify(sourceSnapshot(), null, 2));
