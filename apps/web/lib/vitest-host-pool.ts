import { createHash } from "node:crypto";
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

import { ForksPoolWorker, type PoolOptions, type PoolRunnerInitializer } from "vitest/node";

// Vitest 4.1.12 prepends an optional warning-suppression CommonJS preload. Node
// executes --require before our inherited --import trust bootstrap. Remove that
// one reviewed pair before constructing the same public fork worker; never grant
// the preload (or any other command-line override) execution authority.
const reviewedFiles = {
  "package.json": "e5a6d55e103f04929442595df0f641f128b02fd706ff01474c094863b44511d0",
  "dist/node.js": "ce61e2589b051900ebcf77555b40169e77275d3c8d08aaf07780458c4ae8fdc2",
  "dist/chunks/cli-api.B0Pz1_R7.js": "222aa60f8555aea9311703c68edaaa8eba0888ea29bfb4a49b37f98e0811ee2d",
  "dist/workers/forks.js": "b461149b7a4488ff72f90af16d900ad9c8c410e1b8ddb2c443d49f6cd1aa7206",
  "suppress-warnings.cjs": "a5012da3d2027007781baecda154d343d8c7ad2327b79bec65b1b60a41f42dd1",
} as const;

function requireThat(condition: unknown): asserts condition {
  if (!condition) throw new Error("VITEST_HOST_FORK_CONSTRUCTOR_REFUSED");
}

type FileIdentity = Pick<fs.BigIntStats, "dev" | "ino" | "mode" | "uid" | "gid" | "nlink" | "size" | "mtimeNs" | "ctimeNs">;

function metadata(value: FileIdentity): string {
  return [value.ino, value.mode, value.uid, value.gid, value.nlink, value.size,
    value.mtimeNs, value.ctimeNs].join(":");
}

export function sameHostForkFileIdentity(opened: FileIdentity, named: FileIdentity,
  platform: NodeJS.Platform = process.platform): boolean {
  return metadata(opened) === metadata(named)
    && (opened.dev === named.dev || platform === "win32" && named.dev === 0n);
}

// These hashes bound the installed compatibility contract, not already loaded
// Vitest imports. Every checked byte comes from the same opened descriptor.
function checkFile(file: string, expected: string): void {
  let descriptor: number | undefined;
  try {
    descriptor = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0) | (fs.constants.O_NONBLOCK ?? 0));
    const opened = fs.fstatSync(descriptor, { bigint: true });
    const named = fs.lstatSync(file, { bigint: true });
    requireThat(opened.isFile() && named.isFile() && !named.isSymbolicLink()
      && opened.nlink === 1n && opened.size > 0n && opened.size <= 1_048_576n
      && sameHostForkFileIdentity(opened, named));
    const bytes = Buffer.alloc(Number(opened.size) + 1);
    let count = 0;
    while (count < bytes.length) {
      const read = fs.readSync(descriptor, bytes, count, bytes.length - count, null);
      if (read === 0) break;
      count += read;
    }
    const finished = fs.fstatSync(descriptor, { bigint: true });
    const finalName = fs.lstatSync(file, { bigint: true });
    requireThat(count === Number(opened.size) && metadata(finished) === metadata(opened)
      && finished.dev === opened.dev && finalName.isFile() && !finalName.isSymbolicLink()
      && metadata(finalName) === metadata(named) && finalName.dev === named.dev
      && createHash("sha256").update(bytes.subarray(0, count)).digest("hex") === expected);
  } finally {
    if (descriptor !== undefined) fs.closeSync(descriptor);
  }
}

export function selectHostForkArguments(execArgv: readonly string[], warningFile: string): string[] {
  // This is the actual default vector emitted by the pinned resolver. Profiling,
  // extra preloads/imports/loaders and arbitrary config.execArgv remain refused.
  requireThat(path.isAbsolute(warningFile) && path.resolve(warningFile) === warningFile);
  requireThat(execArgv.length === 7 && execArgv[0] === "--experimental-import-meta-resolve"
    && execArgv[1] === "--require" && execArgv[2] === warningFile
    && execArgv[3] === "--conditions" && execArgv[4] === "node"
    && execArgv[5] === "--conditions" && (execArgv[6] === "development" || execArgv[6] === "production"));
  return [execArgv[0], ...execArgv.slice(3)];
}

export const hostTrustedForks: PoolRunnerInitializer = {
  // A distinct initializer name is necessary: "forks" selects Vitest's built-in
  // switch and bypasses createPoolWorker. The returned worker still reports forks.
  name: "caseops-host-trusted-forks",
  createPoolWorker(options: PoolOptions) {
    const require = createRequire(import.meta.url);
    const root = path.dirname(require.resolve("vitest/package.json"));
    requireThat(fs.realpathSync(root) === root && options.distPath === path.join(root, "dist"));
    for (const [relative, digest] of Object.entries(reviewedFiles)) checkFile(path.join(root, relative), digest);
    const execArgv = selectHostForkArguments(options.execArgv, path.join(root, "suppress-warnings.cjs"));
    return new ForksPoolWorker({ ...options, execArgv });
  },
};
