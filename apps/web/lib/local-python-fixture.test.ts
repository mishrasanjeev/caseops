// @vitest-environment node
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import path from "node:path";
import { spawn } from "node:child_process";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { runLocalPythonFixture } from "../../../tests/e2e/support/local-python-fixture";

vi.mock("node:child_process", () => ({ spawn: vi.fn() }));

const release = "8f5de1066c6c34d214d1ac75aec2d1b65f94adc7";
const project = `caseops-acceptance-${release.slice(0, 12)}-012345abcdef`;
const id = "a".repeat(64);
const endpoint = "npipe:////./pipe/dockerDesktopLinuxEngine";
const compose = path.resolve("fixture", "docker-compose.yml");
const code = "import os; print(os.environ['CASEOPS_E2E_COMPANY_ID'])";
const env = { CASEOPS_ENV: "e2e", CASEOPS_E2E_COMPANY_ID: "company-1" };

class FakeChild extends EventEmitter {
  pid: number | undefined = 123;
  stdin = new PassThrough();
  stdout = new PassThrough();
  stderr = new PassThrough();
  input: Buffer[] = [];
  kill = vi.fn(() => true);
  constructor() {
    super();
    this.stdin.on("data", (data: Buffer) => this.input.push(data));
  }
  close(status: number | null = 0, signal: NodeJS.Signals | null = null) {
    this.emit("close", status, signal);
  }
}

let children: FakeChild[];
let inspect: ReturnType<typeof container>;
let context: { Name: string; Endpoints: { docker: { Host: string } } };
let act: ((child: FakeChild, args: string[], call: number) => boolean) | undefined;

function container() {
  return {
    Id: id,
    Config: {
      Labels: {
        "com.docker.compose.project": project, "com.docker.compose.service": "api",
        "com.docker.compose.oneoff": "False", "com.docker.compose.project.config_files": compose,
        "org.opencontainers.image.revision": release,
      },
      Env: ["CASEOPS_ENV=e2e", `CASEOPS_RELEASE_SHA=${release}`,
        "CASEOPS_DATABASE_URL=postgresql+psycopg://caseops:caseops@postgres:5432/caseops"],
    },
    State: { Running: true, Paused: false, Restarting: false, Dead: false },
    NetworkSettings: {
      Networks: { [`${project}_default`]: {} },
      Ports: { "8000/tcp": [{ HostIp: "127.0.0.1", HostPort: "18000" }] },
    },
  };
}

function docker() {
  vi.stubEnv("CASEOPS_E2E_DOCKER_PROJECT", project);
  vi.stubEnv("CASEOPS_E2E_DOCKER_COMPOSE_FILE", compose);
  vi.stubEnv("CASEOPS_EXPECTED_RELEASE_SHA", release);
}

function options(extra: Partial<Parameters<typeof runLocalPythonFixture>[2]> = {}) {
  return { encoding: "utf8" as const, cwd: "C:/fixture", env: { ...env }, ...extra };
}

const calls = () => vi.mocked(spawn).mock.calls as unknown as Array<[string, string[], { env: NodeJS.ProcessEnv; cwd: string; shell: boolean }]>;
const errorCode = (result: Awaited<ReturnType<typeof runLocalPythonFixture>>) => (result.error as NodeJS.ErrnoException)?.code;
const flush = async () => { for (let i = 0; i < 24; i++) await Promise.resolve(); };

beforeEach(() => {
  for (const key of ["CASEOPS_E2E_DOCKER_PROJECT", "CASEOPS_E2E_DOCKER_COMPOSE_FILE",
    "CASEOPS_EXPECTED_RELEASE_SHA", "CASEOPS_RELEASE_SHA", "DOCKER_HOST", "DOCKER_CONTEXT",
    "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH", "PROD_API_BASE_URL", "PROD_BASE_URL", "CASEOPS_API_BASE_URL",
    "NEXT_PUBLIC_API_BASE_URL", "CASEOPS_WEB_BASE_URL", "CASEOPS_PUBLIC_APP_URL", "CASEOPS_DOCKER_PUBLIC_API_URL",
    "CASEOPS_E2E_API_PORT"]) vi.stubEnv(key, undefined);
  vi.stubEnv("CASEOPS_ENV", "ci");
  children = [];
  inspect = container();
  context = { Name: "desktop-linux", Endpoints: { docker: { Host: endpoint } } };
  act = undefined;
  vi.mocked(spawn).mockReset();
  vi.mocked(spawn).mockImplementation(((_command: string, args: string[]) => {
    const child = new FakeChild();
    children.push(child);
    const call = children.length;
    queueMicrotask(() => {
      if (act?.(child, args, call)) return;
      const value = args[0] === "context" ? JSON.stringify([context])
        : args.includes("info") ? '"linux"'
          : args.includes("compose") ? id
            : args.includes("inspect") ? JSON.stringify([inspect]) : "fixture-output\n";
      child.stdout.write(value);
      child.close();
    });
    return child;
  }) as unknown as typeof spawn);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("local inline Python fixture", () => {
  it("retains the original host interpreter, options, environment, argv and stdin", async () => {
    const originalEnv = { ...env, CASEOPS_DATABASE_URL: "owned-host-database", PATH: "owned-path" };
    const result = await runLocalPythonFixture("C:/fixture/.venv/Scripts/python.exe",
      ["-u", "-c", code, "argument with spaces", "-c", "last"], options({ env: originalEnv, input: "input\n" }));
    expect(calls()).toHaveLength(1);
    const [command, args, settings] = calls()[0];
    expect(command).toBe("C:/fixture/.venv/Scripts/python.exe");
    expect(settings).toMatchObject({ cwd: "C:/fixture", env: originalEnv, shell: false });
    expect(settings.env).toBe(originalEnv);
    expect(args.slice(0, 2)).toEqual(["-u", "-c"]);
    expect(args.slice(3)).toEqual([code, expect.any(String), "argument with spaces", "-c", "last"]);
    expect(Buffer.concat(children[0].input).toString()).toBe("input\n");
    expect(result).toMatchObject({ pid: 123, stdout: "fixture-output\n", stderr: "", status: 0, signal: null,
      output: [null, "fixture-output\n", ""] });
    expect(result.error).toBeUndefined();
  });

  it("preserves the no-sync uv prefix on the host", async () => {
    const prefix = ["--directory", "apps/api", "run", "--no-sync", "python"];
    await runLocalPythonFixture("uv", [...prefix, "-c", code], options());
    expect(calls()[0][0]).toBe("uv");
    expect(calls()[0][1].slice(0, 6)).toEqual([...prefix, "-c"]);
  });

  it("uses the inspected immutable Docker ID and installed Linux Python, never host uv", async () => {
    docker();
    const result = await runLocalPythonFixture("uv",
      ["--directory", "apps/api", "run", "--no-sync", "python", "-c", code, "tail"], options({ input: "stdin" }));
    expect(result.status).toBe(0);
    expect(calls()).toHaveLength(5);
    expect(calls().every(([command]) => command === "docker")).toBe(true);
    expect(calls()[0][1]).toEqual(["context", "inspect"]);
    expect(calls()[1][1].slice(0, 2)).toEqual(["--host", endpoint]);
    expect(calls()[2][1]).toEqual(["--host", endpoint, "compose", "--project-name", project,
      "--file", compose, "ps", "--quiet", "--no-trunc", "api"]);
    expect(calls()[3][1]).toEqual(["--host", endpoint, "inspect", "--type", "container", id]);
    expect(calls()[4][1]).toEqual(["--host", endpoint, "exec", "--interactive", "--env",
      "CASEOPS_E2E_COMPANY_ID=company-1", id, "/usr/local/bin/python", "-c", expect.any(String), code,
      expect.any(String), "tail"]);
    expect(Buffer.concat(children[4].input).toString()).toBe("stdin");
  });

  it("accepts the runner release variable and pins a local Unix daemon while retaining Python flags", async () => {
    docker();
    vi.stubEnv("CASEOPS_EXPECTED_RELEASE_SHA", undefined);
    vi.stubEnv("CASEOPS_RELEASE_SHA", release);
    context = { Name: "default", Endpoints: { docker: { Host: "unix:///var/run/docker.sock" } } };
    expect((await runLocalPythonFixture("python", ["-I", "-u", "-c", code], options())).status).toBe(0);
    const args = calls()[4][1];
    expect(args.slice(args.indexOf("/usr/local/bin/python"), -1)).toEqual([
      "/usr/local/bin/python", "-I", "-u", "-c", expect.any(String), code]);
    expect(args.slice(0, 2)).toEqual(["--host", "unix:///var/run/docker.sock"]);
  });

  it("never forwards host database/provider values or unused fixture fields", async () => {
    docker();
    vi.stubEnv("CASEOPS_DATABASE_URL", "do-not-forward-db");
    vi.stubEnv("CASEOPS_ECOURTSINDIA_API_TOKEN", "do-not-forward-provider");
    const privateCode = "print('CASEOPS_E2E_PRIVATE_TEXT', 'CASEOPS_E2E_FILENAME')";
    const extra = { ...env, CASEOPS_E2E_PRIVATE_TEXT: "fixture content", CASEOPS_E2E_FILENAME: "fixture.txt",
      CASEOPS_E2E_MEMBERSHIP_ID: "unused", CASEOPS_DATABASE_URL: "other-db", PYTHONPATH: "host-only" };
    await runLocalPythonFixture("python", ["-c", privateCode], options({ env: extra }));
    const exec = calls()[4][1];
    expect(exec.filter((_, index) => exec[index - 1] === "--env")).toEqual([
      "CASEOPS_E2E_PRIVATE_TEXT=fixture content", "CASEOPS_E2E_FILENAME=fixture.txt"]);
    for (const [, args, settings] of calls()) {
      expect(settings.env).not.toHaveProperty("CASEOPS_DATABASE_URL");
      expect(settings.env).not.toHaveProperty("CASEOPS_ECOURTSINDIA_API_TOKEN");
      expect(settings.env).not.toHaveProperty("PYTHONPATH");
      expect(args.join(" ")).not.toMatch(/do-not-forward|other-db|host-only|=unused/);
    }
  });

  it.each(["https://127.0.0.1:8000", "http://remote.invalid", "http://user:pass@localhost:8000",
    "http://127.0.0.1:8000/path", "http://127.0.0.1:8000?target=remote", "http://127.0.0.1:8000#fragment"])(
    "rejects unsafe API origin %s before spawning", async (origin) => {
      vi.stubEnv("CASEOPS_API_BASE_URL", origin);
      expect((await runLocalPythonFixture("python", ["-c", code], options())).error).toBeDefined();
      expect(calls()).toHaveLength(0);
    });

  it.each(["http://localhost:18000", "http://127.0.0.1:18000", "http://[::1]:18000"])(
    "accepts exact loopback HTTP origin %s", async (origin) => {
      vi.stubEnv("CASEOPS_API_BASE_URL", origin);
      expect((await runLocalPythonFixture("python", ["-c", code], options())).status).toBe(0);
    });

  it.each(["production", "cloud", "local"])("rejects non-fixture environment %s", async (value) => {
    const result = await runLocalPythonFixture("python", ["-c", code], options({ env: { CASEOPS_ENV: value } }));
    expect(errorCode(result)).toBe("EINVAL");
    expect(calls()).toHaveLength(0);
  });

  it("rejects ambient production configuration even with a safe caller environment", async () => {
    vi.stubEnv("PROD_API_BASE_URL", "https://production.invalid");
    expect(errorCode(await runLocalPythonFixture("python", ["-c", code], options()))).toBe("EINVAL");
    expect(calls()).toHaveLength(0);
  });

  it.each(["project", "compose", "release", "mismatched-release", "wrong-project"])(
    "rejects missing or conflicting Docker metadata: %s", async (kind) => {
      docker();
      if (kind === "project") vi.stubEnv("CASEOPS_E2E_DOCKER_PROJECT", undefined);
      if (kind === "compose") vi.stubEnv("CASEOPS_E2E_DOCKER_COMPOSE_FILE", undefined);
      if (kind === "release") vi.stubEnv("CASEOPS_EXPECTED_RELEASE_SHA", undefined);
      if (kind === "mismatched-release") vi.stubEnv("CASEOPS_RELEASE_SHA", "b".repeat(40));
      if (kind === "wrong-project") vi.stubEnv("CASEOPS_E2E_DOCKER_PROJECT", "caseops-production");
      expect(errorCode(await runLocalPythonFixture("python", ["-c", code], options()))).toBe("EINVAL");
      expect(calls()).toHaveLength(0);
    });

  it.each(["ssh://remote", "tcp://127.0.0.1:2375", "tcp://remote:2376"])(
    "rejects remote/network Docker endpoint %s", async (value) => {
      docker(); vi.stubEnv("DOCKER_HOST", value);
      expect(errorCode(await runLocalPythonFixture("python", ["-c", code], options()))).toBe("EINVAL");
      expect(calls()).toHaveLength(0);
    });

  it.each(["name", "endpoint", "override", "tls"])("rejects unsafe Docker context: %s", async (kind) => {
    docker();
    if (kind === "name") context.Name = "production";
    if (kind === "endpoint") context.Endpoints.docker.Host = "ssh://remote";
    if (kind === "override") vi.stubEnv("DOCKER_HOST", "unix:///var/run/docker.sock");
    if (kind === "tls") vi.stubEnv("DOCKER_TLS_VERIFY", "1");
    expect(errorCode(await runLocalPythonFixture("python", ["-c", code], options()))).toBe("EINVAL");
    expect(calls().some(([, args]) => args.includes("exec"))).toBe(false);
  });

  it.each(["project", "service", "revision", "compose", "id", "state", "environment", "database", "network", "ports"])(
    "fails closed on inspected container mismatch: %s", async (kind) => {
      docker();
      if (kind === "project") inspect.Config.Labels["com.docker.compose.project"] = `${project}-other`;
      if (kind === "service") inspect.Config.Labels["com.docker.compose.service"] = "web";
      if (kind === "revision") inspect.Config.Labels["org.opencontainers.image.revision"] = "b".repeat(40);
      if (kind === "compose") inspect.Config.Labels["com.docker.compose.project.config_files"] = "C:/other/compose.yml";
      if (kind === "id") inspect.Id = "b".repeat(64);
      if (kind === "state") inspect.State.Running = false;
      if (kind === "environment") inspect.Config.Env[0] = "CASEOPS_ENV=cloud";
      if (kind === "database") inspect.Config.Env[2] = "CASEOPS_DATABASE_URL=external-database";
      if (kind === "network") inspect.NetworkSettings.Networks = {};
      if (kind === "ports") inspect.NetworkSettings.Ports["8000/tcp"][0].HostIp = "0.0.0.0";
      expect(errorCode(await runLocalPythonFixture("python", ["-c", code], options()))).toBe("EINVAL");
      expect(calls()).toHaveLength(4);
    });

  it.each([1, 2, 3, 4, 5])("never retries or falls back after Docker step %i fails", async (step) => {
    docker();
    act = (child, _args, call) => { if (call !== step) return false; child.stderr.write("captured failure"); child.close(9); return true; };
    const result = await runLocalPythonFixture("python", ["-c", code], options());
    expect(result).toMatchObject({ status: 9, stderr: "captured failure" });
    expect(calls()).toHaveLength(step);
    expect(calls().every(([command]) => command === "docker")).toBe(true);
  });

  it.each(["invalid-json", "multiple-containers", "windows-daemon"])("rejects malformed/ambiguous metadata: %s", async (kind) => {
    docker();
    act = (child, args) => {
      if (kind === "invalid-json" && args[0] === "context") child.stdout.write("not-json");
      else if (kind === "multiple-containers" && args.includes("compose")) child.stdout.write(`${id}\n${"b".repeat(64)}`);
      else if (kind === "windows-daemon" && args.includes("info")) child.stdout.write('"windows"');
      else return false;
      child.close(); return true;
    };
    const result = await runLocalPythonFixture("python", ["-c", code], options());
    expect(result.status).toBeNull();
    expect(result.error).toBeDefined();
    expect(calls().some(([, args]) => args.includes("exec"))).toBe(false);
  });

  it.each([0, 100, 60_000])("bounds a hung launcher with timeout %i and independent physical-child expiry", async (timeout) => {
    vi.useFakeTimers();
    act = () => true;
    const before = process.listenerCount("exit");
    const pending = runLocalPythonFixture("python", ["-c", code], options({ timeout }));
    const args = calls()[0][1];
    const script = args[1];
    expect(script).toContain("threading.Timer(remaining, lambda: os._exit(124))");
    expect(script).toContain("if remaining <= 0:");
    expect(script.indexOf("timer.start()")).toBeLessThan(script.indexOf("exec(compile(code"));
    expect(script).toContain("sys.argv[:] = ['-c', *sys.argv[3:]]");
    expect(script).not.toContain("sys.stdin");
    const limit = timeout === 100 ? 100 : 30_000;
    expect(Number(args[3]) * 1000).toBe(Date.now() + limit);
    await vi.advanceTimersByTimeAsync(limit);
    const result = await pending;
    expect(errorCode(result)).toBe("ETIMEDOUT");
    expect(result.signal).toBe("SIGKILL");
    expect(children[0].kill).toHaveBeenCalledExactlyOnceWith("SIGKILL");
    expect(children[0].stdin.destroyed && children[0].stdout.destroyed && children[0].stderr.destroyed).toBe(true);
    expect(process.listenerCount("exit")).toBe(before);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("charges Docker inspection time to the same global deadline", async () => {
    docker(); vi.useFakeTimers();
    act = (child, args) => {
      if (args[0] !== "context") return false;
      setTimeout(() => { child.stdout.write(JSON.stringify([context])); child.close(); }, 29_000);
      return true;
    };
    const pending = runLocalPythonFixture("python", ["-c", code], options());
    await vi.advanceTimersByTimeAsync(29_000);
    await flush();
    // The physical interpreter receives the original absolute deadline, not a fresh 30 seconds.
    expect(Number(calls()[4][1].at(-1)) * 1000).toBe(Date.now() + 1_000);
    expect((await pending).status).toBe(0);
  });

  it("terminates hung Docker inspection without host fallback or a new deadline", async () => {
    docker(); vi.useFakeTimers();
    act = () => true;
    const pending = runLocalPythonFixture("python", ["-c", code], options({ timeout: 50 }));
    await vi.advanceTimersByTimeAsync(50);
    expect(errorCode(await pending)).toBe("ETIMEDOUT");
    expect(calls()).toHaveLength(1);
    expect(children[0].kill).toHaveBeenCalledExactlyOnceWith("SIGKILL");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("releases timers and listeners after normal completion and preserves binary stdin", async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    const before = process.listenerCount("exit");
    const remove = vi.spyOn(controller.signal, "removeEventListener");
    const input = new Uint8Array([0, 127, 255]);
    expect((await runLocalPythonFixture("python", ["-c", code], options({ input, signal: controller.signal }))).status).toBe(0);
    controller.abort();
    expect(Buffer.concat(children[0].input)).toEqual(Buffer.from(input));
    expect(children[0].kill).not.toHaveBeenCalled();
    expect(process.listenerCount("exit")).toBe(before);
    expect(remove).toHaveBeenCalledWith("abort", expect.any(Function));
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each([false, true])("aborts and cleans up host or Docker CLI without another process (%s)", async (inDocker) => {
    if (inDocker) docker();
    vi.useFakeTimers();
    act = (_child, args) => inDocker ? args.includes("exec") : true;
    const signal = new AbortController();
    const remove = vi.spyOn(signal.signal, "removeEventListener");
    const pending = runLocalPythonFixture("python", ["-c", code], options({ signal: signal.signal }));
    await flush();
    signal.abort();
    const result = await pending;
    expect(errorCode(result)).toBe("ABORT_ERR");
    expect(children.at(-1)!.kill).toHaveBeenCalledExactlyOnceWith("SIGKILL");
    expect(remove).toHaveBeenCalledWith("abort", expect.any(Function));
    expect(calls()).toHaveLength(inDocker ? 5 : 1);
    expect(calls().at(-1)![1].join(" ")).toContain("threading.Timer");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not spawn for a pre-aborted call", async () => {
    const controller = new AbortController(); controller.abort();
    const result = await runLocalPythonFixture("python", ["-c", code], options({ signal: controller.signal }));
    expect(errorCode(result)).toBe("ABORT_ERR");
    expect(calls()).toHaveLength(0);
  });

  it("bounds combined stdout/stderr, retaining captured partial output without printing", async () => {
    const log = vi.spyOn(console, "log");
    act = (child) => { child.stdout.write("1234"); child.stderr.write("56789"); return true; };
    const result = await runLocalPythonFixture("python", ["-c", code], options({ maxBuffer: 8 }));
    expect(errorCode(result)).toBe("ENOBUFS");
    expect(result).toMatchObject({ stdout: "1234", stderr: "5678", status: null, signal: "SIGKILL" });
    expect(children[0].kill).toHaveBeenCalledTimes(1);
    expect(log).not.toHaveBeenCalled();
  });

  it("does not allow a caller to raise the output ceiling", async () => {
    act = (child) => { child.stdout.write(Buffer.alloc(1_048_577, 65)); return true; };
    const result = await runLocalPythonFixture("python", ["-c", code], options({ maxBuffer: 10_000_000 }));
    expect(errorCode(result)).toBe("ENOBUFS");
    expect(Buffer.byteLength(result.stdout)).toBe(1_048_576);
  });

  it("decodes split UTF-8 chunks and preserves nonzero exit and signal semantics", async () => {
    act = (child) => {
      const bytes = Buffer.from("\u0939\u093f\u0928\u094d\u0926\u0940");
      child.stdout.write(bytes.subarray(0, 2)); child.stdout.write(bytes.subarray(2));
      child.stderr.write("error\n"); child.close(null, "SIGTERM"); return true;
    };
    expect(await runLocalPythonFixture("python", ["-c", code], options())).toMatchObject({
      stdout: "\u0939\u093f\u0928\u094d\u0926\u0940", stderr: "error\n", status: null, signal: "SIGTERM" });
  });

  it("preserves asynchronous spawn errors", async () => {
    const error = Object.assign(new Error("missing interpreter"), { code: "ENOENT" });
    act = (child) => { child.pid = undefined; child.emit("error", error); return true; };
    const result = await runLocalPythonFixture("python", ["-c", code], options());
    expect(result.error).toBe(error);
    expect(result.status).toBeNull();
    expect(result.signal).toBeNull();
  });

  it("preserves synchronous spawn errors and handles stdin failure", async () => {
    const error = Object.assign(new Error("spawn refused"), { code: "EACCES" });
    vi.mocked(spawn).mockImplementationOnce(() => { throw error; });
    expect((await runLocalPythonFixture("python", ["-c", code], options())).error).toBe(error);
    act = (child) => { child.stdin.emit("error", Object.assign(new Error("pipe closed"), { code: "EPIPE" })); return true; };
    expect(errorCode(await runLocalPythonFixture("python", ["-c", code], options()))).toBe("EPIPE");
  });

  it.each([["python", ["-m", "fixture"]], ["python", ["fixture.py"]], ["sh", ["-c", code]],
    ["uv", ["run", "python", "-c", code]]])("rejects unsupported invocation %s %j", async (command, args) => {
    expect(errorCode(await runLocalPythonFixture(command as string, args as string[], options()))).toBe("EINVAL");
    expect(calls()).toHaveLength(0);
  });

  it.each([{ shell: true }, { stdio: "inherit" }, { timeout: -1 }, { timeout: NaN }, { maxBuffer: 0 }])(
    "rejects options that remove bounds or capture: %j", async (extra) => {
      const result = await runLocalPythonFixture("python", ["-c", code], options(extra as Parameters<typeof options>[0]));
      expect(errorCode(result)).toBe("EINVAL");
      expect(calls()).toHaveLength(0);
    });

  it("rejects oversized inline code and stdin without spawning", async () => {
    expect(errorCode(await runLocalPythonFixture("python", ["-c", "x".repeat(65_537)], options()))).toBe("EINVAL");
    expect(errorCode(await runLocalPythonFixture("python", ["-c", code], options({ input: Buffer.alloc(1_048_577) })))).toBe("EINVAL");
    expect(calls()).toHaveLength(0);
  });

  it.each(["missing", "oversized"])("rejects %s referenced fixture values", async (kind) => {
    docker();
    const value = kind === "missing" ? undefined : "x".repeat(16_385);
    const result = await runLocalPythonFixture("python", ["-c", code],
      options({ env: { CASEOPS_ENV: "e2e", CASEOPS_E2E_COMPANY_ID: value } }));
    expect(errorCode(result)).toBe("EINVAL");
    expect(calls()).toHaveLength(4);
  });
});
