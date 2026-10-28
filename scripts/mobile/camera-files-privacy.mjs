// Read-only SDK-cache observation. This is separate from the historical Files
// known-fixture matcher; it does not inspect or warm a provider URI.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { closeSync, constants, fstatSync, lstatSync, openSync, readdirSync, readSync, realpathSync } from 'node:fs';
import path from 'node:path';

export const CAMERA_COPY_NAME = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\.(?:jpg|jpeg|png)$/i;
export const CAMERA_PRIVACY_LIMITS = Object.freeze({ copies: 128, entries: 512, fileBytes: 50 * 1024 * 1024,
  totalBytes: 64 * 1024 * 1024, milliseconds: 30000 });
const META = ['dev', 'ino', 'mode', 'nlink', 'uid', 'gid', 'size', 'mtimeNs', 'ctimeNs'];
const ANCESTOR_IDENTITY = ['dev', 'ino', 'mode', 'uid', 'gid'];
const identity = value => Object.fromEntries(META.map(key => [key, String(value[key])]));
const digest = value => createHash('sha256').update(value).digest('hex');

export function assertCameraCopiesRemoved(observation) {
  assert.equal(observation?.kind, 'camera-sdk-private-copies', 'CAMERA_SDK_OBSERVATION_REQUIRED');
  assert.equal(observation.complete, true, 'COMPLETE_CAMERA_SDK_OBSERVATION_REQUIRED');
  assert.equal(observation.counts.copies, 0, 'OWNED_CAMERA_SDK_COPY_REMAINS');
  return { status: 'passed', scope: 'owned-ImagePicker-directory-only', physicalCameraAcceptance: false };
}

// iOS Simulator app-data is host-visible. Require the exact attested app root;
// Android uses the descriptor-framed device reader in android-files-privacy.
export function observeIosCameraDirectory(appDataPath, { readChunk = readSync } = {}) {
  assert.ok(path.isAbsolute(appDataPath) && path.resolve(appDataPath) === appDataPath
    && realpathSync(appDataPath) === appDataPath, 'EXACT_CAMERA_APP_DIRECTORY_REQUIRED');
  const app = lstatSync(appDataPath, { bigint: true });
  assert.ok(app.isDirectory() && !app.isSymbolicLink(), 'EXACT_CAMERA_APP_DIRECTORY_REQUIRED');
  const root = path.join(appDataPath, 'Library/Caches/ImagePicker'), limits = CAMERA_PRIVACY_LIMITS;
  const deadline = Date.now() + limits.milliseconds, issues = [], copies = [];
  let entries = 0, bytesRead = 0;
  const charge = () => { assert.ok(++entries <= limits.entries && Date.now() <= deadline, 'CAMERA_OBSERVATION_BOUND'); };
  const namespace = () => {
    const parts = root.split(path.sep).filter(Boolean), result = []; let current = path.parse(root).root;
    for (const part of ['', ...parts]) {
      if (part) current = path.join(current, part);
      charge();
      let metadata;
      try { metadata = lstatSync(current, { bigint: true }); }
      catch (error) { if (error.code === 'ENOENT') { result.push({ path: current, absent: true }); break; } throw error; }
      assert.ok(metadata.isDirectory() && !metadata.isSymbolicLink()
        && realpathSync(current) === current, 'CAMERA_NAMESPACE_REQUIRED');
      if (current === appDataPath || current.startsWith(`${appDataPath}${path.sep}`))
        assert.ok(metadata.uid === app.uid && metadata.dev === app.dev, 'CAMERA_DIRECTORY_OWNER_REQUIRED');
      // Sibling temp/device entries outside this app are not part of the SDK
      // inventory. Bind those ancestors' identity and canonical namespace;
      // charge full metadata for the owned app and every SDK ancestor in it.
      const owned = current === appDataPath || current.startsWith(`${appDataPath}${path.sep}`);
      result.push({ path: current, metadata: owned ? identity(metadata)
        : Object.fromEntries(ANCESTOR_IDENTITY.map(key => [key, String(metadata[key])])) });
    }
    return result;
  };
  const initialNamespace = namespace();
  const present = initialNamespace.at(-1).path === root && !initialNamespace.at(-1).absent;
  const inventory = () => {
    if (!present) return [];
    const names = readdirSync(root); entries += names.length;
    assert.ok(entries <= limits.entries && names.length <= limits.copies && new Set(names).size === names.length,
      'CAMERA_DIRECTORY_ENTRY_BOUND');
    return names.sort();
  };
  let names = [], finalNames = [], initialFileMetadata = new Map();
  try {
    names = inventory();
    for (const name of names) {
      assert.ok(Date.now() <= deadline, 'CAMERA_OBSERVATION_BOUND');
      if (!CAMERA_COPY_NAME.test(name)) { issues.push({ reason: 'unreviewed-camera-entry' }); continue; }
      const file = path.join(root, name), before = lstatSync(file, { bigint: true });
      initialFileMetadata.set(name, identity(before));
      if (!before.isFile() || before.isSymbolicLink() || before.nlink !== 1n || before.uid !== app.uid || before.dev !== app.dev) {
        issues.push({ reason: 'camera-copy-owner-or-kind' }); continue;
      }
      if (before.size > BigInt(limits.fileBytes) || BigInt(bytesRead) + before.size > BigInt(limits.totalBytes)) {
        issues.push({ reason: 'camera-copy-byte-bound' }); continue;
      }
      let fd;
      try {
        assert.equal(realpathSync(file), file, 'CAMERA_COPY_NAMESPACE_REQUIRED');
        fd = openSync(file, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
        assert.deepEqual(identity(fstatSync(fd, { bigint: true })), identity(before), 'CAMERA_COPY_CHANGED');
        const hash = createHash('sha256'), chunk = Buffer.alloc(65536); let consumed = 0;
        while (true) {
          assert.ok(Date.now() <= deadline, 'CAMERA_OBSERVATION_BOUND');
          const length = readChunk(fd, chunk, 0, Math.min(chunk.length, limits.fileBytes + 1 - consumed,
            limits.totalBytes + 1 - bytesRead), null);
          consumed += length; bytesRead += length;
          assert.ok(consumed <= limits.fileBytes && bytesRead <= limits.totalBytes, 'CAMERA_COPY_BYTE_BOUND');
          if (length === 0) break;
          hash.update(chunk.subarray(0, length));
        }
        assert.equal(BigInt(consumed), before.size, 'CAMERA_COPY_CHANGED');
        assert.deepEqual(identity(fstatSync(fd, { bigint: true })), identity(before), 'CAMERA_COPY_CHANGED');
        assert.deepEqual(identity(lstatSync(file, { bigint: true })), identity(before), 'CAMERA_COPY_CHANGED');
        assert.equal(realpathSync(file), file, 'CAMERA_COPY_NAMESPACE_REQUIRED');
        copies.push({ nameSha256: digest(name), sizeBytes: consumed, sha256: hash.digest('hex'), classification: 'owned-camera-sdk-copy' });
      } catch { issues.push({ reason: 'camera-copy-read-or-identity-failed' }); }
      finally { if (fd !== undefined) closeSync(fd); }
    }
    finalNames = inventory();
    assert.deepEqual(finalNames, names, 'CAMERA_DIRECTORY_CHANGED');
    for (const name of names) if (initialFileMetadata.has(name))
      assert.deepEqual(identity(lstatSync(path.join(root, name), { bigint: true })), initialFileMetadata.get(name), 'CAMERA_COPY_CHANGED');
  } catch { issues.push({ reason: 'camera-directory-incomplete-or-changed' }); }
  try { assert.deepEqual(namespace(), initialNamespace, 'CAMERA_NAMESPACE_CHANGED'); }
  catch { issues.push({ reason: 'camera-final-namespace-changed' }); }
  return { schemaVersion: 1, kind: 'camera-sdk-private-copies', platform: 'ios', root, complete: issues.length === 0,
    directoryPresent: present, limits, counts: { copies: names.length, bytesRead, entries }, copies, issues,
    inventory: { initialCount: names.length, finalCount: finalNames.length, initialSha256: digest(JSON.stringify(names)),
      finalSha256: digest(JSON.stringify(finalNames)) },
    legacyKnownFixtureCountsIncluded: false, providerOriginalsRead: false, fileContentsRecorded: false,
    filesDeleted: false, encodedMetadataInspected: false, physicalCameraAcceptance: false };
}
