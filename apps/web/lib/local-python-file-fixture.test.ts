// @vitest-environment node
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { runLocalPythonFixture } from "../../../tests/e2e/support/local-python-fixture";
import { runLocalPythonFileFixture } from "../../../tests/e2e/support/local-python-file-fixture";

vi.mock("../../../tests/e2e/support/local-python-fixture", () => ({ runLocalPythonFixture: vi.fn() }));

const pdf = fileURLToPath(new URL("../../../tests/e2e/support/draft_pdf_fixture_20261111.py", import.meta.url));
const ram = fileURLToPath(new URL("../../../tests/e2e/support/ram_batch3_draft_fixture.py", import.meta.url));
const assistant = fileURLToPath(new URL("../../../tests/e2e/support/assistant_history_fixture.py", import.meta.url));
const renewal = fileURLToPath(new URL("../../../tests/e2e/support/seed_iplf037b.py", import.meta.url));
const root = path.resolve(path.dirname(pdf), "../../..");
const support = path.join(root, "tests/e2e/support");
const options = () => ({ cwd: root, encoding: "utf8" as const, timeout: 30_000,
  env: { NODE_ENV: "test" as const, CASEOPS_ENV: "e2e", CASEOPS_LLM_PROVIDER: "mock" } });
const success = { pid: 17, status: 0, signal: null, stdout: "result", stderr: "", output: [null, "result", ""] } as const;
type Result = Awaited<ReturnType<typeof runLocalPythonFileFixture>>;
const errorCode = (result: Result) => (result.error as NodeJS.ErrnoException)?.code;
const bundle = () => JSON.parse(vi.mocked(runLocalPythonFixture).mock.calls[0][2].input as string);
const cloneStat = (stat: fs.BigIntStats, overrides: object) => Object.assign(Object.create(Object.getPrototypeOf(stat)), stat, overrides);
const namedStat = fs.lstatSync.bind(fs);

beforeEach(() => {
  vi.mocked(runLocalPythonFixture).mockReset();
  vi.mocked(runLocalPythonFixture).mockResolvedValue({ ...success, output: [...success.output] });
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllEnvs(); });

describe("finite local Python file fixture adapter", () => {
  it.each([pdf, ram, assistant, renewal])("bundles exact public source bytes without evaluating them: %s", async file => {
    const result = await runLocalPythonFileFixture("python", file, options());
    expect(result).toEqual(success);
    expect(vi.mocked(runLocalPythonFixture)).toHaveBeenCalledTimes(1);
    const [command, args, delegated] = vi.mocked(runLocalPythonFixture).mock.calls[0];
    expect(command).toBe("python");
    expect(args.slice(0, -1)).toEqual(file === assistant ? ["-I", "-B", "-u", "-c"] : ["-c"]);
    expect(args.at(-1)).not.toContain(fs.readFileSync(file, "utf8"));
    expect(Buffer.from(bundle().main_source)).toEqual(fs.readFileSync(file));
    expect(bundle().main_file).toBe(file);
    expect(bundle().original_stdin).toBe("");
    expect(delegated.timeout).toBeGreaterThan(0);
    expect(delegated.timeout).toBeLessThanOrEqual(30_000);
    expect(delegated.cwd).toBe(root);
    if (file === pdf) {
      expect(bundle().modules).toEqual([{ name: "ram_batch3_draft_fixture", file: ram, source: fs.readFileSync(ram, "utf8") }]);
    } else expect(bundle().modules).toEqual([]);
  });

  it("requests exactly the two renewal environment fields from core, only for renewal", async () => {
    for (const file of [pdf, ram, assistant, renewal]) {
      vi.mocked(runLocalPythonFixture).mockClear();
      const env = { ...options().env, CASEOPS_E2E_COMPANY_ID: "company-1", CASEOPS_E2E_MEMBERSHIP_ID: "member-1" };
      await runLocalPythonFileFixture("python", file, { ...options(), env });
      const [, args, delegated] = vi.mocked(runLocalPythonFixture).mock.calls[0];
      const code = args.at(-1)!;
      for (const key of ["CASEOPS_E2E_COMPANY_ID", "CASEOPS_E2E_MEMBERSHIP_ID"]) {
        expect(code.includes(key)).toBe(file === renewal);
        expect(code.includes(`os.environ['${key}']`)).toBe(file === renewal);
      }
      expect(code).not.toMatch(/CASEOPS_E2E_(MATTER_ID|ATTACHMENT_ID|PRIVATE_TEXT|FILENAME)/);
      expect(delegated.env).toBe(env);
      expect(bundle().modules).toHaveLength(file === pdf ? 1 : 0);
    }
  });

  it.each([assistant, renewal])("reads only the admitted program, with no recursive import discovery: %s", async file => {
    const open = vi.spyOn(fs, "openSync");
    await runLocalPythonFileFixture("python", file, options());
    expect(open).toHaveBeenCalledTimes(1);
    expect(open.mock.calls[0][0]).toBe(file);
    expect(bundle().modules).toEqual([]);
  });

  it.each([false, true])("leaves host/Docker mode, interpreter, environment and capture controls to core (%s)", async docker => {
    if (docker) {
      vi.stubEnv("CASEOPS_E2E_DOCKER_PROJECT", "parent-owned-project");
      vi.stubEnv("CASEOPS_E2E_DOCKER_COMPOSE_FILE", "parent-owned-compose");
    }
    const signal = new AbortController().signal;
    const supplied = { ...options(), signal, maxBuffer: 1234, windowsHide: true, env: { ...options().env, CASEOPS_EMBEDDING_PROVIDER: "mock" } };
    await runLocalPythonFileFixture(path.join(root, "apps/api/.venv/Scripts/python.exe"), pdf, supplied);
    const [command, , delegated] = vi.mocked(runLocalPythonFixture).mock.calls[0];
    expect(command).toBe(path.join(root, "apps/api/.venv/Scripts/python.exe"));
    expect(delegated).toMatchObject({ ...supplied, input: expect.any(String), timeout: expect.any(Number) });
    expect(delegated.env).toBe(supplied.env);
    expect(delegated.signal).toBe(signal);
    expect(supplied).not.toHaveProperty("input");
  });

  it.each([" \r\n{\"text\":\"\u0939\u093f\u0928\u094d\u0926\u0940 \ud83d\udcc4\"}\n\u0000", "\ufefforiginal\r\n"])(
    "preserves original Unicode stdin exactly", async input => {
      for (const value of [input, Buffer.from(input), new Uint8Array(Buffer.from(input))]) {
        vi.mocked(runLocalPythonFixture).mockClear();
        await runLocalPythonFileFixture("python", pdf, { ...options(), input: value });
        expect(bundle().original_stdin).toBe(input);
      }
    });

  it("honors byte-view offsets without copying surrounding bytes into stdin", async () => {
    const bytes = Buffer.from("surround:original\r\n:surround");
    await runLocalPythonFileFixture("python", pdf, { ...options(), input: new DataView(bytes.buffer, bytes.byteOffset + 9, 10) });
    expect(bundle().original_stdin).toBe("original\r\n");
  });

  it("compiles all exact sources before execution and passes only a callable outer predicate to both namespaces", async () => {
    await runLocalPythonFileFixture("python", pdf, options());
    const wrapper = vi.mocked(runLocalPythonFixture).mock.calls[0][1][1];
    expect(wrapper.indexOf("main = compile(bundle['main_source']")).toBeLessThan(wrapper.indexOf("exec(code,"));
    expect(wrapper).toContain("predicate = globals().get('__caseops_is_owned_fixture_database__')");
    // One owned-container filename mapping plus the two namespace fences.
    expect(wrapper.match(/if callable\(predicate\):/g)).toHaveLength(3);
    expect(wrapper.match(/module\.__dict__\['__caseops_is_owned_fixture_database__'\] = predicate/g)).toHaveLength(2);
    expect(wrapper).toContain("types.ModuleType(item['name'])");
    expect(wrapper).toContain("sys.modules[item['name']] = module");
    expect(wrapper).toContain("types.ModuleType('__main__')");
    expect(wrapper).toContain("module.__file__ = item['file']");
    expect(wrapper).toContain("module.__file__ = bundle['main_file']");
    expect(wrapper).toContain("sys.argv[:] = [bundle['main_file']]");
    expect(wrapper).toContain("sys.stdin = io.StringIO(bundle['original_stdin'])");
    expect(wrapper).toContain("raise SystemExit('Invalid local fixture source.') from None");
    expect(wrapper).not.toMatch(/os\.environ|builtins\.|write\(|replace\(|subprocess|socket/);
  });

  it.each(["status", "signal", "error"])("preserves core %s results without logging or retry/fallback", async kind => {
    const result = { ...success, output: [...success.output], status: kind === "status" ? 9 : null,
      signal: kind === "signal" ? "SIGTERM" as const : null,
      error: kind === "error" ? Object.assign(new Error("core failure"), { code: "ETIMEDOUT" }) : undefined };
    vi.mocked(runLocalPythonFixture).mockResolvedValue(result);
    const logs = [vi.spyOn(console, "log"), vi.spyOn(console, "error"), vi.spyOn(console, "warn")];
    expect(await runLocalPythonFileFixture("python", pdf, options())).toBe(result);
    expect(runLocalPythonFixture).toHaveBeenCalledTimes(1);
    for (const log of logs) expect(log).not.toHaveBeenCalled();
  });

  it.each(["other.py", "ip_entitlement_fixture.py", "../ram_batch3_draft_fixture.py", "draft_pdf_fixture_20261111.py/extra"])(
    "refuses a non-admitted source without reading or delegation: %s", async name => {
      const open = vi.spyOn(fs, "openSync");
      const result = await runLocalPythonFileFixture("python", path.join(support, name), options());
      expect(errorCode(result)).toBe("EINVAL");
      expect(open).not.toHaveBeenCalled();
      expect(runLocalPythonFixture).not.toHaveBeenCalled();
    });

  it.each([path.join(root, "ram_batch3_draft_fixture.py"), path.join(root, "elsewhere", "draft_pdf_fixture_20261111.py"),
    "tests/e2e/support/draft_pdf_fixture_20261111.py", `${pdf}\0payload`])("rejects escape/relative paths: %s", async file => {
    expect(errorCode(await runLocalPythonFileFixture("python", file, options()))).toBe("EINVAL");
    expect(runLocalPythonFixture).not.toHaveBeenCalled();
  });

  it.each([undefined, ".", new URL("file:///tmp/checkout")])("requires the actual absolute string cwd: %s", async cwd => {
    expect(errorCode(await runLocalPythonFileFixture("python", pdf, { ...options(), cwd }))).toBe("EINVAL");
    expect(runLocalPythonFixture).not.toHaveBeenCalled();
  });

  it.each([pdf, ram, assistant, renewal, support, path.dirname(support), root])("rejects symlink/reparse sources and parents: %s", async linked => {
    vi.spyOn(fs, "lstatSync").mockImplementation(((file: fs.PathLike) => {
      const value = namedStat(file, { bigint: true });
      return file === linked ? cloneStat(value, { isSymbolicLink: () => true }) : value;
    }) as typeof fs.lstatSync);
    const target = linked === assistant || linked === renewal ? linked : pdf;
    expect(errorCode(await runLocalPythonFileFixture("python", target, options()))).toBe("EINVAL");
    expect(runLocalPythonFixture).not.toHaveBeenCalled();
  });

  it.each(["hardlink", "directory", "fifo", "realpath"])("rejects %s source identities", async kind => {
    if (kind === "realpath") {
      const realpath = fs.realpathSync.bind(fs);
      vi.spyOn(fs, "realpathSync").mockImplementation(((file: fs.PathLike) => file === pdf ? path.join(root, "outside.py") : realpath(file)) as typeof fs.realpathSync);
    } else {
      vi.spyOn(fs, "lstatSync").mockImplementation(((file: fs.PathLike) => {
        const value = namedStat(file, { bigint: true });
        return file === pdf ? cloneStat(value, kind === "hardlink" ? { nlink: 2n } : { isFile: () => false }) : value;
      }) as typeof fs.lstatSync);
    }
    expect(errorCode(await runLocalPythonFileFixture("python", pdf, options()))).toBe("EINVAL");
    expect(runLocalPythonFixture).not.toHaveBeenCalled();
  });

  it.each([0n, 16_385n])("bounds source size before opening: %s", async size => {
    vi.spyOn(fs, "lstatSync").mockImplementation(((file: fs.PathLike) => {
      const value = namedStat(file, { bigint: true });
      return file === pdf ? cloneStat(value, { size }) : value;
    }) as typeof fs.lstatSync);
    const open = vi.spyOn(fs, "openSync");
    expect(errorCode(await runLocalPythonFileFixture("python", pdf, options()))).toBe("EFBIG");
    expect(open).not.toHaveBeenCalled();
    expect(runLocalPythonFixture).not.toHaveBeenCalled();
  });

  it.each(["ino", "mode", "nlink", "size", "mtimeNs", "ctimeNs"])("detects opened-source %s changes and closes the descriptor", async key => {
    const stat = fs.fstatSync.bind(fs);
    vi.spyOn(fs, "fstatSync").mockImplementation(((fd: number) => {
      const value = stat(fd, { bigint: true });
      return cloneStat(value, { [key]: (value[key as keyof fs.BigIntStats] as bigint) + 1n });
    }) as typeof fs.fstatSync);
    const close = vi.spyOn(fs, "closeSync");
    expect(errorCode(await runLocalPythonFileFixture("python", pdf, options()))).toBe("ESTALE");
    expect(close).toHaveBeenCalledTimes(1);
    expect(runLocalPythonFixture).not.toHaveBeenCalled();
  });

  it.each([pdf, support])("rechecks source and parent identity after bundling: %s", async changed => {
    let reads = 0;
    vi.spyOn(fs, "lstatSync").mockImplementation(((file: fs.PathLike) => {
      const value = namedStat(file, { bigint: true });
      if (file === changed && ++reads >= (changed === pdf ? 3 : 2)) return cloneStat(value, { ino: value.ino + 1n });
      return value;
    }) as typeof fs.lstatSync);
    expect(errorCode(await runLocalPythonFileFixture("python", pdf, options()))).toBe("ESTALE");
    expect(runLocalPythonFixture).not.toHaveBeenCalled();
  });

  it("rejects a truncated read and closes its descriptor", async () => {
    vi.spyOn(fs, "readSync").mockReturnValue(0);
    const close = vi.spyOn(fs, "closeSync");
    expect(errorCode(await runLocalPythonFileFixture("python", pdf, options()))).toBe("ESTALE");
    expect(close).toHaveBeenCalledTimes(1);
    expect(runLocalPythonFixture).not.toHaveBeenCalled();
  });

  it.each([0, 255])("rejects NUL or malformed UTF-8 source before core execution (%i)", async byte => {
    const read = fs.readSync.bind(fs);
    vi.spyOn(fs, "readSync").mockImplementation(((fd: number, buffer: Buffer, offset: number, length: number, position: number | null) => {
      const count = read(fd, buffer, offset, length, position);
      if (count) buffer[offset] = byte;
      return count;
    }) as typeof fs.readSync);
    expect(errorCode(await runLocalPythonFileFixture("python", pdf, options()))).toBe(byte ? "EILSEQ" : "EINVAL");
    expect(runLocalPythonFixture).not.toHaveBeenCalled();
  });

  it.each([Buffer.from([255]), "\ud800", "x".repeat(1_048_577), "\u0000".repeat(180_000)])("bounds and validates stdin/envelope", async input => {
    expect((await runLocalPythonFileFixture("python", pdf, { ...options(), input })).error).toBeDefined();
    expect(runLocalPythonFixture).not.toHaveBeenCalled();
  });

  it.each([-1, NaN, Infinity])("rejects invalid timeout %s without core execution", async timeout => {
    expect(errorCode(await runLocalPythonFileFixture("python", pdf, { ...options(), timeout }))).toBe("EINVAL");
    expect(runLocalPythonFixture).not.toHaveBeenCalled();
  });

  it("charges file preparation to the same hard deadline", async () => {
    vi.spyOn(performance, "now").mockReturnValueOnce(0).mockReturnValue(30_001);
    expect(errorCode(await runLocalPythonFileFixture("python", pdf, options()))).toBe("ETIMEDOUT");
    expect(runLocalPythonFixture).not.toHaveBeenCalled();
  });

  it("returns a sanitized typed failure without echoing filesystem diagnostics, source, or stdin", async () => {
    vi.spyOn(fs, "openSync").mockImplementation(() => { throw new Error("secret-source-and-path"); });
    const result = await runLocalPythonFileFixture("python", pdf, { ...options(), input: "private-payload" });
    expect(errorCode(result)).toBe("EIO");
    expect(result).toMatchObject({ pid: 0, status: null, signal: null, stdout: "" });
    expect(result.error?.name).toBe("LocalPythonFileFixtureError");
    expect(JSON.stringify(result)).not.toMatch(/secret-source-and-path|private-payload/);
    expect(runLocalPythonFixture).not.toHaveBeenCalled();
  });
});
