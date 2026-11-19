import type { SpawnSyncReturns } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { TextDecoder } from "node:util";

import { runLocalPythonFixture } from "./local-python-fixture";

type FixtureOptions = Parameters<typeof runLocalPythonFixture>[2];
const sourceLimit = 16_384;
const inputLimit = 1_048_576;
const programs = ["draft_pdf_fixture_20261111.py", "ram_batch3_draft_fixture.py",
  "assistant_history_fixture.py", "seed_iplf037b.py"] as const;

// Only these four trusted checkout programs are bundled; admission and execution
// remain owned by the core helper, including its physical-interpreter expiry.
const wrapper = `def _caseops_file_fixture():
    import io, json, sys, types
    bundle = json.load(sys.stdin)
    predicate = globals().get('__caseops_is_owned_fixture_database__')
    if callable(predicate):
        from pathlib import PureWindowsPath
        bundle['main_file'] = '/app/tests/e2e/support/' + PureWindowsPath(bundle['main_file']).name
        for item in bundle['modules']:
            item['file'] = '/app/tests/e2e/support/' + PureWindowsPath(item['file']).name
    try:
        modules = [(item, compile(item['source'], item['file'], 'exec')) for item in bundle['modules']]
        main = compile(bundle['main_source'], bundle['main_file'], 'exec')
    except (SyntaxError, ValueError, TypeError):
        raise SystemExit('Invalid local fixture source.') from None
    sys.stdin = io.StringIO(bundle['original_stdin'])
    sys.argv[:] = [bundle['main_file']]
    for item, code in modules:
        module = types.ModuleType(item['name'])
        module.__file__ = item['file']
        if callable(predicate):
            module.__dict__['__caseops_is_owned_fixture_database__'] = predicate
        sys.modules[item['name']] = module
        exec(code, module.__dict__, module.__dict__)
    module = types.ModuleType('__main__')
    module.__file__ = bundle['main_file']
    if callable(predicate):
        module.__dict__['__caseops_is_owned_fixture_database__'] = predicate
    sys.modules['__main__'] = module
    exec(main, module.__dict__, module.__dict__)
_caseops_file_fixture()
`;

// Core forwards only reviewed fields literally referenced by the inline program.
// The other three programs use stdin, so must not request these renewal fields.
const renewalWrapper = "import os\nos.environ['CASEOPS_E2E_COMPANY_ID']\nos.environ['CASEOPS_E2E_MEMBERSHIP_ID']\n" + wrapper;

function reject(code: string, message: string): never {
  throw Object.assign(new Error(message), { name: "LocalPythonFileFixtureError", code });
}

function same(a: fs.BigIntStats, b: fs.BigIntStats): boolean {
  return (a.dev === b.dev || process.platform === "win32" && a.dev === 0n)
    && a.ino === b.ino && a.mode === b.mode && a.nlink === b.nlink
    && a.size === b.size && a.mtimeNs === b.mtimeNs && a.ctimeNs === b.ctimeNs;
}

function utf8(bytes: Uint8Array): string {
  try { return new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes); }
  catch { return reject("EILSEQ", "Local fixture input/source must be valid UTF-8."); }
}

/** Finite file-to-inline adapter. It never runs Python, Docker, or retries itself. */
export async function runLocalPythonFileFixture(
  command: string, fixturePath: string, options: FixtureOptions,
): Promise<SpawnSyncReturns<string>> {
  const started = performance.now();
  try {
    if (typeof options.cwd !== "string" || !path.isAbsolute(options.cwd)
      || typeof fixturePath !== "string" || !path.isAbsolute(fixturePath)) {
      reject("EINVAL", "Local file fixtures require absolute checkout paths.");
    }
    const support = path.join(path.resolve(options.cwd), "tests", "e2e", "support");
    const name = programs.find(file => fixturePath === path.join(support, file));
    if (!name) reject("EINVAL", "Local file fixture is not admitted.");
    const snapshots = new Map<string, fs.BigIntStats>();
    const inspect = (file: string, directory: boolean): fs.BigIntStats => {
      const stat = fs.lstatSync(file, { bigint: true });
      if (stat.isSymbolicLink() || (directory ? !stat.isDirectory() : !stat.isFile() || stat.nlink !== 1n)
        || path.relative(file, fs.realpathSync(file)) !== "") {
        reject("EINVAL", "Linked or non-regular local fixture paths are forbidden.");
      }
      return stat;
    };
    let parent = support;
    for (;;) {
      snapshots.set(parent, inspect(parent, true));
      const next = path.dirname(parent);
      if (next === parent) break;
      parent = next;
    }
    const read = (file: string) => {
      const before = inspect(file, false);
      if (before.size === 0n || before.size > BigInt(sourceLimit)) reject("EFBIG", "Local fixture source exceeds its bound.");
      const fd = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0) | (fs.constants.O_NONBLOCK ?? 0));
      let source: string;
      try {
        if (!same(before, fs.fstatSync(fd, { bigint: true }))) reject("ESTALE", "Local fixture source changed during inspection.");
        const bytes = Buffer.alloc(sourceLimit + 1);
        let length = 0, count: number;
        while (length < bytes.length && (count = fs.readSync(fd, bytes, length, bytes.length - length, null)) > 0) length += count;
        if (BigInt(length) !== before.size || !same(before, fs.fstatSync(fd, { bigint: true })) || !same(before, inspect(file, false))) {
          reject("ESTALE", "Local fixture source changed during inspection.");
        }
        source = utf8(bytes.subarray(0, length));
        if (source.includes("\0")) reject("EINVAL", "Invalid local fixture source.");
      } finally { fs.closeSync(fd); }
      snapshots.set(file, before);
      return { source, file };
    };
    const main = read(fixturePath);
    const modules = name === programs[0]
      ? [{ name: "ram_batch3_draft_fixture", ...read(path.join(support, programs[1])) }] : [];
    const input = options.input;
    if (input !== undefined && typeof input !== "string" && !ArrayBuffer.isView(input)) {
      reject("EINVAL", "Unsupported local file fixture stdin.");
    }
    if (input !== undefined && (typeof input === "string" ? Buffer.byteLength(input) : input.byteLength) > inputLimit) {
      reject("EFBIG", "Local fixture stdin exceeds its bound.");
    }
    const originalStdin = input === undefined ? "" : typeof input === "string" ? input
      : utf8(new Uint8Array(input.buffer, input.byteOffset, input.byteLength));
    if (utf8(Buffer.from(originalStdin)) !== originalStdin) reject("EILSEQ", "Invalid local fixture stdin.");
    const envelope = JSON.stringify({ main_source: main.source, main_file: main.file, modules, original_stdin: originalStdin });
    if (Buffer.byteLength(envelope) > inputLimit) reject("EFBIG", "Local fixture bundle exceeds its bound.");
    for (const [file, before] of snapshots) {
      if (!same(before, inspect(file, before.isDirectory()))) reject("ESTALE", "Local fixture path changed during inspection.");
    }
    if (options.timeout !== undefined && (!Number.isFinite(options.timeout) || options.timeout < 0)) {
      reject("EINVAL", "Invalid local fixture timeout.");
    }
    const remaining = Math.min(options.timeout || 30_000, 30_000) - (performance.now() - started);
    if (remaining <= 0) reject("ETIMEDOUT", "Local fixture deadline exceeded.");
    const args = name === "assistant_history_fixture.py" ? ["-I", "-B", "-u"] : [];
    args.push("-c", name === "seed_iplf037b.py" ? renewalWrapper : wrapper);
    return await runLocalPythonFixture(command, args, { ...options, input: envelope, timeout: remaining });
  } catch (cause) {
    const error = cause instanceof Error && cause.name === "LocalPythonFileFixtureError" ? cause
      : Object.assign(new Error("Local fixture source inspection failed."), { name: "LocalPythonFileFixtureError", code: "EIO" });
    return { pid: 0, status: null, signal: null, stdout: "", stderr: error.message,
      output: [null, "", error.message], error };
  }
}
