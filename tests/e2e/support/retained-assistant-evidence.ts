import { createHash } from "node:crypto";
import fs from "node:fs";

const MAX_BYTES = 128 * 1024;

function sameLeaf(entry: fs.BigIntStats, opened: fs.BigIntStats): boolean {
  // Windows libuv reports device zero for lstat and the volume ID for fstat.
  return entry.isFile() && !entry.isSymbolicLink() && opened.ino > 0n
    && entry.ino === opened.ino
    && (entry.dev === opened.dev || (process.platform === "win32" && entry.dev === 0n && opened.dev > 0n));
}

export function readRetainedAssistantEvidence(file: string, expectedSha: string): Buffer {
  if (!/^[a-f0-9]{64}$/.test(expectedSha)) throw new Error("Invalid retained evidence digest.");
  let descriptor: number | undefined;
  try {
    descriptor = fs.openSync(file, fs.constants.O_RDONLY
      | (fs.constants.O_NOFOLLOW || 0) | (fs.constants.O_NONBLOCK || 0));
    const opened = fs.fstatSync(descriptor, { bigint: true });
    if (!opened.isFile() || opened.size < 1n || opened.size > BigInt(MAX_BYTES)
      || !sameLeaf(fs.lstatSync(file, { bigint: true }), opened)) {
      throw new Error("Invalid retained evidence file.");
    }
    // Check and read one descriptor. Never reopen a pathname after validating it.
    const bytes = Buffer.alloc(Number(opened.size) + 1);
    let length = 0;
    while (length < bytes.length) {
      const count = fs.readSync(descriptor, bytes, length, bytes.length - length, length);
      if (count === 0) break;
      length += count;
    }
    const after = fs.fstatSync(descriptor, { bigint: true });
    if (BigInt(length) !== opened.size || after.size !== opened.size
      || after.mtimeNs !== opened.mtimeNs || after.ctimeNs !== opened.ctimeNs
      || !sameLeaf(fs.lstatSync(file, { bigint: true }), opened)) {
      throw new Error("Retained evidence changed while reading.");
    }
    const body = bytes.subarray(0, length);
    if (createHash("sha256").update(body).digest("hex") !== expectedSha) {
      throw new Error("Retained evidence digest did not match.");
    }
    return body;
  } catch {
    throw new Error("Retained assistant evidence is unavailable, unsafe or changed.");
  } finally {
    if (descriptor !== undefined) fs.closeSync(descriptor);
  }
}
