import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { closeSync, constants, fstatSync, lstatSync, openSync, opendirSync, readSync, realpathSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const SOURCE_SNAPSHOT_LIMITS = Object.freeze({ entries: 5000, bytes: 67108864,
  fileBytes: 16777216, milliseconds: 5000, gitBytes: 1048576 });
// Selected Node 22.14.0/24.15.0 spawn_sync uses one aggregate output counter,
// checked after each native 65536-byte read; overflow closes both stdio pipes.
// Reserve that whole chunk before spawning, rather than claiming maxBuffer+1.
const GIT_NATIVE_READ_RESERVE = 65536;
const fields = ['dev', 'ino', 'size', 'mtimeNs', 'ctimeNs', 'uid', 'gid', 'mode', 'nlink'];
const identity = ['dev', 'ino', 'uid', 'gid', 'mode'];
const frame = value => fields.map(key => String(value[key]));
const equal = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const canonical = file => (realpathSync.native ?? realpathSync)(file);
function insist(value, code, detail) {
  if (!value) { const error = new Error(code); error.code = code; if (detail) Object.assign(error, detail); throw error; }
}
function boundedLimits(requested = {}) {
  insist(requested && typeof requested === 'object' && !Array.isArray(requested), 'SOURCE_LIMIT_DOMAIN');
  insist(Object.keys(requested).every(key => Object.hasOwn(SOURCE_SNAPSHOT_LIMITS, key)), 'SOURCE_LIMIT_DOMAIN');
  const limits = { ...SOURCE_SNAPSHOT_LIMITS, ...requested };
  for (const key of Object.keys(limits)) insist(Number.isSafeInteger(limits[key]) && limits[key] > 0
    && limits[key] <= SOURCE_SNAPSHOT_LIMITS[key], 'SOURCE_LIMIT_INCREASE_REFUSED');
  return limits;
}

/** The optional limits can only make the fixed resource contract stricter. */
export function sourceSnapshot(root = fileURLToPath(new URL('../../', import.meta.url)), { limits: requested } = {}) {
  const limits = boundedLimits(requested), end = performance.now() + limits.milliseconds;
  insist(['22.14.0', '24.15.0'].includes(process.versions.node), 'SOURCE_GIT_RUNTIME_REQUIRED');
  let bytes = 0; const charged = new Set();
  const check = () => insist(performance.now() < end, 'SOURCE_DEADLINE');
  const charge = (observation, file) => {
    check(); const key = observation + '\0' + file;
    if (!charged.has(key)) { insist(charged.size < limits.entries, 'SOURCE_INVENTORY_BOUND'); charged.add(key); }
  };
  const consume = amount => {
    bytes += amount;
    insist(bytes <= limits.bytes, 'SOURCE_BYTE_BOUND', { bytesRead: bytes, limit: limits.bytes,
      detectorBytes: Math.max(0, bytes - limits.bytes) }); check();
  };
  insist(typeof root === 'string', 'SOURCE_ROOT_REQUIRED');
  root = canonical(path.resolve(root));
  const initialRoot = lstatSync(root, { bigint: true });
  insist(initialRoot.isDirectory() && !initialRoot.isSymbolicLink(), 'SOURCE_ROOT_DIRECTORY_REQUIRED');
  if (typeof process.getuid === 'function') insist(initialRoot.uid === BigInt(process.getuid()), 'SOURCE_CURRENT_OWNER_REQUIRED');
  const namespace = file => {
    check(); insist(canonical(file) === file, 'SOURCE_CANONICAL_PATH_CHANGED'); const rows = [];
    for (let parent = path.dirname(file); ; parent = path.dirname(parent)) {
      check(); insist(rows.length < 128, 'SOURCE_NAMESPACE_BOUND');
      const value = lstatSync(parent, { bigint: true });
      insist(value.isDirectory() && !value.isSymbolicLink(), 'SOURCE_ANCESTOR_DIRECTORY_REQUIRED');
      rows.push([parent, ...(parent === root || parent.startsWith(root + path.sep) ? fields : identity).map(key => String(value[key]))]);
      if (parent === path.dirname(parent)) return rows;
    }
  };
  const rootNamespace = namespace(root);
  const git = (args, input = undefined, statuses = [0]) => {
    check(); insist(canonical(root) === root && equal(rootNamespace, namespace(root)), 'SOURCE_ROOT_NAMESPACE_CHANGED');
    if (input !== undefined) { insist(Buffer.isBuffer(input) && input.length <= limits.gitBytes, 'SOURCE_GIT_INPUT_BOUND'); consume(input.length); }
    const captureCeiling = Math.min(limits.gitBytes, limits.bytes - bytes);
    insist(captureCeiling > GIT_NATIVE_READ_RESERVE, 'SOURCE_GIT_OUTPUT_RESERVE_REQUIRED');
    const result = spawnSync('git', args, { cwd: root, timeout: Math.max(1, Math.min(5000, Math.ceil(end - performance.now()))),
      maxBuffer: captureCeiling - GIT_NATIVE_READ_RESERVE, input,
      stdio: [input === undefined ? 'ignore' : 'pipe', 'pipe', 'pipe'], windowsHide: true });
    const stdoutBytes = Buffer.isBuffer(result.stdout) ? result.stdout.length : 0;
    const stderrBytes = Buffer.isBuffer(result.stderr) ? result.stderr.length : 0;
    consume(stdoutBytes + stderrBytes);
    insist(stdoutBytes + stderrBytes <= captureCeiling, 'SOURCE_GIT_CAPTURE_BOUND');
    insist(!result.error && statuses.includes(result.status) && result.signal === null, 'SOURCE_GIT_COMMAND_REFUSED', {
      stdoutBytes, stderrBytes, capturedBytes: stdoutBytes + stderrBytes, sourceBytesRead: bytes,
      gitExitCode: result.status, gitErrorCode: result.error?.code ?? null, gitSignal: result.signal });
    const text = result.stdout.toString('utf8');
    insist(Buffer.from(text, 'utf8').equals(result.stdout), 'SOURCE_GIT_UTF8_REQUIRED'); return text;
  };
  const paths = ['apps/mobile', 'package.json', 'package-lock.json',
    'scripts/mobile/build-acceptance.mjs', 'scripts/mobile/build-android-local-acceptance.ps1',
    'scripts/mobile/build-android-local-acceptance.sh',
    'scripts/mobile/android-host-launch.mjs', 'scripts/mobile/android-no-paid.gradle',
    'scripts/mobile/host-platform-trust.py', 'scripts/mobile/fixtures/host-platform-trust/HostPlatformTrust.java',
    'scripts/mobile/generate-app-icons.mjs',
    'scripts/mobile/build-ios-simulator-acceptance.sh', 'scripts/mobile/source-snapshot.mjs',
    'scripts/mobile/windows-native-paths.gradle', 'scripts/mobile/use-android-env.ps1',
    'scripts/mobile/android-tooling.ps1', 'scripts/mobile/prepare-viewer-assets.mjs',
    'scripts/mobile/prepare-native-links.mjs',
    'scripts/mobile/prepare-store-packaging.mjs',
    'scripts/mobile/ios-host-launch.mjs', 'scripts/mobile/ios-host-pods.rb',
    'scripts/mobile/ios-simulator-build.sh', 'scripts/mobile/ios-local-qa-host.py',
    'scripts/mobile/ios-git-readonly.py',
    'scripts/mobile/ios-node-build-env.json',
    'scripts/mobile/host-node-trust.mjs', 'scripts/mobile/host-node-trust-start.mjs',
    'scripts/mobile/source-gate-observer.mjs', 'scripts/mobile/host-node-trust-start.source.mjs',
    'scripts/mobile/rebuild-host-node-bootstrap.mjs', 'scripts/mobile/host-node-trust-start.provenance.json',
    'scripts/mobile/store-packaging-host.py', 'scripts/mobile/store_process_owner.py',
    'apps/web/lib/native-link-policy.cjs', 'apps/web/lib/native-link-policy.d.cts',
    'apps/web/lib/native-link-config.cjs', 'apps/web/lib/native-link-config.d.cts'];
  const selectedNames = () => {
    const raw = git(['ls-files', '-z', '--cached', '--others', '--exclude-standard', '--', ...paths]);
    const seen = new Set(), selected = []; let start = 0;
    while (start < raw.length) {
      check(); const stop = raw.indexOf('\0', start);
      insist(stop > start && seen.size < 5000, 'SOURCE_GIT_INVENTORY_BOUND');
      const file = raw.slice(start, stop); start = stop + 1;
      insist(!seen.has(file), 'SOURCE_DUPLICATE_GIT_PATH'); seen.add(file);
      insist(file.length <= 4096 && !path.isAbsolute(file) && !file.includes('\\')
        && !file.split('/').some(part => !part || part === '.' || part === '..'), 'SOURCE_RELATIVE_PATH_REQUIRED');
      if (/\/(e2e|node_modules|\.expo|dist|build)\//.test(file)
        || /(^|\/)\.(env[^/]*|npmrc)$|\.(key|pem|jks|keystore|p12|mobileprovision)$|credentials[^/]*\.json|google-services\.json|GoogleService-Info/i.test(file)) continue;
      insist(selected.length < limits.entries, 'SOURCE_INVENTORY_BOUND'); selected.push(file);
    }
    insist(selected.length > 0, 'SOURCE_INVENTORY_BOUND'); return selected.sort();
  };
  const bindNamed = (opened, named) => {
    insist(named.isFile() && !named.isSymbolicLink(), 'SOURCE_NAMED_REGULAR_REQUIRED');
    for (const key of fields) if (!(process.platform === 'win32' && key === 'dev' && named.dev === 0n))
      insist(opened[key] === named[key], 'SOURCE_NAMED_FD_CHANGED');
  };
  const directoryRows = (observation, names) => {
    const directories = new Set([root]), rows = new Map(), pending = [], scheduled = new Set();
    const schedule = directory => {
      charge(observation, directory);
      if (!scheduled.has(directory)) { scheduled.add(directory); pending.push(directory); }
    };
    for (const relative of names) {
      for (let parent = path.dirname(path.join(root, ...relative.split('/'))); ; parent = path.dirname(parent)) {
        charge(observation, parent); directories.add(parent); if (parent === root) break;
      }
    }
    // Only directory pathspecs are walked. Literal helper-file pathspecs do not
    // turn their siblings into source inputs. No file payload is read here.
    for (const relative of paths) {
      const absolute = path.join(root, ...relative.split('/')); let state;
      try { state = lstatSync(absolute, { bigint: true }); } catch (error) { if (error.code === 'ENOENT') continue; throw error; }
      if (state.isDirectory() && !state.isSymbolicLink()) schedule(absolute);
    }
    while (pending.length) {
      check(); const layer = pending.splice(0), candidates = []; let candidateBytes = 0;
      for (const directory of layer) {
        check(); const state = lstatSync(directory, { bigint: true }), parents = namespace(directory);
        insist(state.isDirectory() && !state.isSymbolicLink(), 'SOURCE_SELECTED_DIRECTORY_REQUIRED');
        const children = [], seen = new Set(); let iterator;
        try {
          iterator = opendirSync(directory, { bufferSize: 1 });
          while (true) {
            check(); const entry = iterator.readSync(); if (entry === null) break;
            insist(entry.name && entry.name !== '.' && entry.name !== '..' && !/[\\/\0]/.test(entry.name), 'SOURCE_DIRECTORY_NAME_REQUIRED');
            const absolute = path.join(directory, entry.name); charge(observation, absolute);
            insist(!seen.has(entry.name), 'SOURCE_DUPLICATE_DIRECTORY_ENTRY'); seen.add(entry.name); children.push(entry.name);
            const relative = path.relative(root, absolute).split(path.sep).join('/');
            if (entry.isDirectory() && !/\/(e2e|node_modules|\.expo|dist|build)\//.test('/' + relative + '/')) {
              candidateBytes += Buffer.byteLength(relative) + 2;
              insist(candidateBytes <= limits.gitBytes, 'SOURCE_GIT_INPUT_BOUND'); candidates.push(relative + '/');
            }
          }
        } finally { if (iterator !== undefined) iterator.closeSync(); }
        insist(equal(frame(state), frame(lstatSync(directory, { bigint: true })))
          && equal(parents, namespace(directory)), 'SOURCE_DIRECTORY_CHANGED_DURING_DISCOVERY');
        rows.set(directory, { path: directory, metadata: frame(state), parents, children: children.sort() });
        directories.add(directory);
      }
      if (candidates.length) {
        const ignoredText = git(['check-ignore', '-z', '--stdin'], Buffer.from(candidates.join('\0') + '\0'), [0, 1]);
        const candidateSet = new Set(candidates), ignored = new Set(); let start = 0;
        while (start < ignoredText.length) {
          check(); const stop = ignoredText.indexOf('\0', start); insist(stop > start, 'SOURCE_GIT_IGNORE_PROTOCOL');
          const relative = ignoredText.slice(start, stop); start = stop + 1;
          insist(candidateSet.has(relative) && !ignored.has(relative), 'SOURCE_GIT_IGNORE_PROTOCOL'); ignored.add(relative);
        }
        for (const relative of candidates) if (!ignored.has(relative)) schedule(path.join(root, ...relative.slice(0, -1).split('/')));
      }
    }
    return [...directories].sort().map(directory => {
      if (rows.has(directory)) return rows.get(directory);
      check(); const state = lstatSync(directory, { bigint: true });
      insist(state.isDirectory() && !state.isSymbolicLink(), 'SOURCE_SELECTED_DIRECTORY_REQUIRED');
      return { path: directory, metadata: frame(state), parents: namespace(directory) };
    });
  };
  const file = (relative, observation) => {
    check(); const absolute = path.join(root, ...relative.split('/')); charge(observation, absolute);
    let fd;
    try {
      fd = openSync(absolute, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0) | (constants.O_NONBLOCK ?? 0));
      const opened = fstatSync(fd, { bigint: true });
      insist(opened.isFile() && opened.nlink === 1n && opened.uid === initialRoot.uid, 'SOURCE_OPENED_REGULAR_OWNER_REQUIRED');
      insist(opened.size >= 0n && opened.size <= BigInt(limits.fileBytes), 'SOURCE_FILE_BYTE_BOUND');
      insist(opened.size <= BigInt(limits.bytes - bytes), 'SOURCE_REMAINING_BYTE_BOUND');
      const named = lstatSync(absolute, { bigint: true }); bindNamed(opened, named);
      const parents = namespace(absolute), digest = createHash('sha256'), buffer = Buffer.alloc(65536); let count = 0;
      while (count <= Number(opened.size)) {
        check(); const length = Math.min(buffer.length, Number(opened.size) + 1 - count, limits.bytes + 1 - bytes);
        insist(length > 0, 'SOURCE_BYTE_BOUND');
        const width = readSync(fd, buffer, 0, length, null); if (!width) break;
        count += width; consume(width);
        insist(count <= Number(opened.size), 'SOURCE_FILE_GREW', { bytesRead: count, detectorBytes: 1 });
        digest.update(buffer.subarray(0, width));
      }
      insist(count === Number(opened.size), 'SOURCE_FILE_SHRANK');
      insist(equal(frame(opened), frame(fstatSync(fd, { bigint: true })))
        && equal(frame(named), frame(lstatSync(absolute, { bigint: true })))
        && equal(parents, namespace(absolute)), 'SOURCE_FILE_OR_NAMESPACE_CHANGED');
      return { path: absolute, named: frame(named), opened: frame(opened), parents, digest: digest.digest('hex') };
    } finally { if (fd !== undefined) closeSync(fd); }
  };
  const observe = observation => {
    charge(observation, root); const rootState = lstatSync(root, { bigint: true });
    insist(rootState.isDirectory() && !rootState.isSymbolicLink(), 'SOURCE_ROOT_DIRECTORY_REQUIRED');
    const names = selectedNames(), dirs = directoryRows(observation, names);
    const rows = names.map(relative => file(relative, observation));
    insist(equal(frame(rootState), frame(lstatSync(root, { bigint: true }))), 'SOURCE_ROOT_CHANGED');
    return { names, rows, dirs };
  };
  const sourceSha = git(['rev-parse', 'HEAD']).trim(); insist(/^[a-f0-9]{40}$/.test(sourceSha), 'SOURCE_SHA_REQUIRED');
  const dirty = git(['status', '--porcelain', '--untracked-files=all', '--', ...paths]);
  const before = observe('first'), after = observe('second');
  insist(equal(before, after), 'SOURCE_SELECTED_INVENTORY_CHANGED');
  insist(git(['rev-parse', 'HEAD']).trim() === sourceSha
    && git(['status', '--porcelain', '--untracked-files=all', '--', ...paths]) === dirty, 'SOURCE_GIT_STATE_CHANGED');
  for (const row of after.rows) {
    check(); insist(equal(row.named, frame(lstatSync(row.path, { bigint: true })))
      && equal(row.parents, namespace(row.path)), 'SOURCE_FINAL_FILE_CHANGED');
  }
  // Pointwise final directory reconciliation follows all leaves; descendants
  // precede root. Frozen writers remain required. This is not an atomic FS audit.
  for (const row of [...after.dirs].sort((a, b) => b.path.split(path.sep).length - a.path.split(path.sep).length || b.path.localeCompare(a.path))) {
    check(); insist(equal(row.metadata, frame(lstatSync(row.path, { bigint: true })))
      && equal(row.parents, namespace(row.path)), 'SOURCE_FINAL_DIRECTORY_CHANGED');
  }
  check(); const hash = createHash('sha256');
  for (let index = 0; index < before.names.length; index++) hash.update(`${before.names[index]}\0${before.rows[index].digest}\0`);
  return { sourceSha, sourceFingerprint: hash.digest('hex'), sourceDirty: Boolean(dirty.trim()), inputFileCount: before.names.length };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) console.log(JSON.stringify(sourceSnapshot(), null, 2));
