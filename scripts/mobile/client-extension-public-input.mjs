import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';

const fields = ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs'];
const metadata = stat => Object.fromEntries(fields.map(key => [key, String(stat[key])]));
function namespace(file) {
  assert.equal(path.resolve(file), file, 'CX_CANONICAL_PUBLIC_PATH_REQUIRED');
  assert.equal(fs.realpathSync(file), file, 'CX_CANONICAL_PUBLIC_PATH_REQUIRED');
  const result = [];
  for (let current = path.dirname(file); ; current = path.dirname(current)) {
    const stat = fs.lstatSync(current, { bigint: true });
    assert.ok(stat.isDirectory() && !stat.isSymbolicLink());
    result.push({ path: current, metadata: metadata(stat) });
    if (path.dirname(current) === current) return result;
  }
}

/** Only Windows named-path device zero differs from the held descriptor.
 * Each full named/FD frame is still reconciled separately after consumption. */
export function assertClientNamedDescriptor(named, opened, platform = process.platform) {
  for (const key of fields) {
    if (platform === 'win32' && key === 'dev' && named.dev === 0n) continue;
    assert.equal(named[key], opened[key], 'CX_NAMED_DESCRIPTOR_IDENTITY_CHANGED');
  }
}

/** Unknown-digest public ACKs are consumed from one bounded, verified FD. */
export function readClientPublicInput(file, { maxBytes = 1048576, expectedSha256, afterOpen, json = true } = {}) {
  assert.ok(Number.isSafeInteger(maxBytes) && maxBytes > 0 && maxBytes <= 1048576);
  let fd;
  try {
    fd = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0) | (fs.constants.O_NONBLOCK ?? 0));
    const opened = fs.fstatSync(fd, { bigint: true });
    assert.ok(opened.isFile() && opened.nlink === 1n && opened.size <= BigInt(maxBytes));
    if (typeof process.getuid === 'function') assert.equal(opened.uid, BigInt(process.getuid()));
    const named = fs.lstatSync(file, { bigint: true });
    assert.ok(named.isFile() && !named.isSymbolicLink());
    assertClientNamedDescriptor(named, opened);
    const ancestors = namespace(file);
    afterOpen?.(fd);
    const storage = Buffer.alloc(maxBytes + 1);
    let count = 0;
    while (count < storage.length) {
      const size = fs.readSync(fd, storage, count, storage.length - count, null);
      if (!size) break;
      count += size;
    }
    assert.ok(count <= maxBytes, 'CX_PUBLIC_INPUT_BOUND');
    assert.equal(BigInt(count), opened.size, 'CX_PUBLIC_INPUT_EXTENT_CHANGED');
    assert.deepEqual(metadata(fs.fstatSync(fd, { bigint: true })), metadata(opened));
    const finalNamed = fs.lstatSync(file, { bigint: true });
    assert.deepEqual(metadata(finalNamed), metadata(named));
    assertClientNamedDescriptor(finalNamed, opened);
    assert.deepEqual(namespace(file), ancestors);
    const bytes = storage.subarray(0, count);
    const sha256 = createHash('sha256').update(bytes).digest('hex');
    if (expectedSha256 !== undefined) assert.equal(sha256, expectedSha256);
    const value = json ? JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)) : undefined;
    if (json) assert.ok(value && typeof value === 'object' && !Array.isArray(value));
    return { bytes, value, evidence: { path: file, sha256 }, metadata: metadata(opened) };
  } finally {
    if (fd !== undefined) fs.closeSync(fd);
  }
}

/** Exclusive public projection; caller validation finishes before this writer.
 * Partial/failed outputs remain retained and never produce a success reference. */
export function writeClientProjection(file, bytes) {
  assert.ok(Buffer.isBuffer(bytes) && bytes.length > 0 && bytes.length <= 1048576);
  assert.ok(path.isAbsolute(file) && path.resolve(file) === file);
  const parents = () => {
    const directory=path.dirname(file); assert.equal(fs.realpathSync(directory),directory);
    const result=[];
    for(let p=directory;;p=path.dirname(p)) { const s=fs.lstatSync(p,{bigint:true});assert.ok(s.isDirectory()&&!s.isSymbolicLink());result.push([p,...['dev','ino','uid','gid','mode'].map(k=>String(s[k]))]);if(path.dirname(p)===p)return result; }
  };
  const before=parents();let fd;
  try {
    fd=fs.openSync(file,fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_EXCL|(fs.constants.O_NOFOLLOW??0)|(fs.constants.O_NONBLOCK??0),0o600);
    const opened=fs.fstatSync(fd,{bigint:true});assert.ok(opened.isFile()&&opened.nlink===1n);if(process.getuid)assert.equal(opened.uid,BigInt(process.getuid()));
    let offset=0;const deadline=Date.now()+5000;
    while(offset<bytes.length){assert.ok(Date.now()<=deadline);const n=fs.writeSync(fd,bytes,offset,bytes.length-offset);assert.ok(Number.isSafeInteger(n)&&n>0&&n<=bytes.length-offset);offset+=n;}
    fs.fsyncSync(fd);const after=fs.fstatSync(fd,{bigint:true}),named=fs.lstatSync(file,{bigint:true});
    assert.equal(after.size,BigInt(bytes.length));assert.ok(named.isFile()&&!named.isSymbolicLink());
    for(const key of ['dev','ino','uid','gid','mode','nlink'])assert.equal(after[key],opened[key]);
    for(const key of fields)if(!(process.platform==='win32'&&key==='dev'&&named.dev===0n))assert.equal(named[key],after[key]);
    assert.deepEqual(parents(),before);assert.equal(fs.realpathSync(file),file);
    return {path:file,sha256:createHash('sha256').update(bytes).digest('hex')};
  } finally { if(fd!==undefined)fs.closeSync(fd); }
}
