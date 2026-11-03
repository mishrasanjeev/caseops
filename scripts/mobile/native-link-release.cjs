'use strict';
// Release admission for the committed production native-link input. Reads the
// exact released bytes from stdin through the shared web/mobile reader (which
// refuses synthetic, placeholder and malformed input) and prints only public
// values: the input digest and the API redirect registry projection.
// Usage: git show <sha>:apps/web/native-links/production.json | node scripts/mobile/native-link-release.cjs
const { createHash } = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { readNativeLinkConfig } = require('../../apps/web/lib/native-link-config.cjs');

// The reader's own bound is 16 KiB; read one more byte to detect excess.
const LIMIT = 16385;

function admit(bytes) {
  if (!Buffer.isBuffer(bytes) || bytes.length < 1 || bytes.length >= LIMIT) throw new Error('NATIVE_LINK_RELEASE_SIZE');
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'caseops-native-link-'));
  try {
    const file = path.join(folder, 'production.json');
    fs.writeFileSync(file, bytes, { flag: 'wx', mode: 0o600 });
    const sha256 = createHash('sha256').update(bytes).digest('hex');
    const loaded = readNativeLinkConfig({ CASEOPS_NATIVE_LINK_CONFIG_FILE: file, CASEOPS_NATIVE_LINK_CONFIG_SHA256: sha256 });
    return { sha256: loaded.sha256, redirectUris: loaded.projections.apiEnvironment.CASEOPS_NATIVE_REDIRECT_URIS };
  } finally {
    fs.rmSync(folder, { recursive: true, force: true });
  }
}

function readStdin() {
  const buffer = Buffer.alloc(LIMIT);
  let count = 0;
  while (count < LIMIT) {
    let length;
    try { length = fs.readSync(0, buffer, count, LIMIT - count, null); }
    catch (error) { if (error && error.code === 'EAGAIN') continue; if (error && error.code === 'EOF') break; throw error; }
    if (!length) break;
    count += length;
  }
  return buffer.subarray(0, count);
}

if (require.main === module) {
  try {
    if (process.argv.length !== 2) throw new Error('NATIVE_LINK_RELEASE_ARGUMENTS');
    process.stdout.write(`${JSON.stringify(admit(readStdin()))}\n`);
  } catch (error) {
    process.stderr.write(`NATIVE_LINK_RELEASE_REFUSED ${error instanceof Error ? error.message : 'unknown'}\n`);
    process.exitCode = 2;
  }
}
module.exports = { admit };
