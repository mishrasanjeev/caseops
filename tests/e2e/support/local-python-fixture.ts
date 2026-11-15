import { spawn, type SpawnSyncOptionsWithStringEncoding, type SpawnSyncReturns } from "node:child_process";
import path from "node:path";

type FixtureOptions = SpawnSyncOptionsWithStringEncoding & { signal?: AbortSignal };
const wallLimitMs = 30_000;
const byteLimit = 1_048_576;
// The 32-call adjacent inventory includes private-document fixtures as well as entitlements.
const fixtureKeys = ["CASEOPS_E2E_COMPANY_ID", "CASEOPS_E2E_MEMBERSHIP_ID",
  "CASEOPS_E2E_MATTER_ID", "CASEOPS_E2E_ATTACHMENT_ID", "CASEOPS_E2E_PRIVATE_TEXT",
  "CASEOPS_E2E_FILENAME"] as const;

// This runs inside the physical interpreter, not its uv/venv/docker launcher.
// Leave the daemon timer armed even after exec returns: fixture-created threads
// must not keep a transaction alive indefinitely. Closing the process rolls back.
const boundedPython = `def _caseops_bounded_inline():
    import os, sys, threading, time
    code, deadline = sys.argv[1], float(sys.argv[2])
    remaining = deadline - time.time()
    if remaining <= 0:
        os._exit(124)
    timer = threading.Timer(remaining, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    sys.argv[:] = ['-c', *sys.argv[3:]]
    namespace = globals()
    del namespace['_caseops_bounded_inline']
    exec(compile(code, '<string>', 'exec'), namespace, namespace)
_caseops_bounded_inline()
`;

function failure(code: string, message: string): NodeJS.ErrnoException {
  return Object.assign(new Error(message), { code });
}

function empty(error: Error): SpawnSyncReturns<string> {
  return { pid: 0, output: [null, "", ""], stdout: "", stderr: "", status: null, signal: null, error };
}

function requireThat(value: unknown, message: string): asserts value {
  if (!value) throw failure("EINVAL", message);
}

function loopback(value: string): void {
  const url = new URL(value);
  requireThat(url.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)
    && !url.username && !url.password && url.pathname === "/" && !url.search && !url.hash,
  "Local Python fixtures require loopback HTTP origins.");
}

function fixtureFence(env: NodeJS.ProcessEnv): void {
  for (const source of [process.env, env]) {
    requireThat(!source.PROD_API_BASE_URL && !source.PROD_BASE_URL,
      "Local Python fixtures reject production configuration.");
    if (source.CASEOPS_ENV) requireThat(["e2e", "ci"].includes(source.CASEOPS_ENV),
      "Local Python fixtures require an e2e/ci environment.");
    for (const key of ["CASEOPS_API_BASE_URL", "NEXT_PUBLIC_API_BASE_URL", "CASEOPS_WEB_BASE_URL",
      "CASEOPS_PUBLIC_APP_URL", "CASEOPS_DOCKER_PUBLIC_API_URL"]) {
      if (source[key]) loopback(source[key]!);
    }
  }
  requireThat(["e2e", "ci"].includes(env.CASEOPS_ENV ?? ""), "Missing local fixture environment.");
  loopback(`http://127.0.0.1:${env.CASEOPS_E2E_API_PORT ?? process.env.CASEOPS_E2E_API_PORT ?? "8000"}`);
}

function inlineIndex(command: string, args: string[]): number {
  const name = path.basename(command.replaceAll("\\", "/"));
  let offset = 0;
  if (/^uv(?:\.exe)?$/.test(name)) {
    requireThat(args[0] === "--directory" && /(?:^|\/)apps\/api$/.test(args[1]?.replaceAll("\\", "/") ?? "")
      && args[2] === "run" && args[3] === "--no-sync" && args[4] === "python",
    "Unsupported uv inline fixture invocation.");
    offset = 5;
  } else {
    requireThat(/^python(?:3(?:\.\d+)?)?(?:\.exe)?$/.test(name), "Unsupported fixture interpreter.");
  }
  while (["-u", "-B", "-I", "-E", "-s", "-S"].includes(args[offset])) offset++;
  requireThat(args[offset] === "-c" && typeof args[offset + 1] === "string",
    "Only explicit inline -c Python fixtures are supported.");
  requireThat(args.every((arg) => typeof arg === "string" && !arg.includes("\0"))
    && Buffer.byteLength(args.join("\0")) <= 65_536, "Inline fixture arguments exceed their bound.");
  return offset;
}

/** Bounded async replacement for UTF-8 spawnSync inline fixtures; never retries or logs captured output. */
export async function runLocalPythonFixture(
  command: string, args: string[], options: FixtureOptions,
): Promise<SpawnSyncReturns<string>> {
  const started = performance.now();
  try {
    requireThat(["utf8", "utf-8"].includes(options.encoding), "Fixture encoding must be UTF-8.");
    requireThat(!options.shell && (!options.stdio || options.stdio === "pipe"),
      "Fixtures require direct execution and captured pipes.");
    requireThat(options.timeout === undefined || Number.isFinite(options.timeout) && options.timeout >= 0,
      "Invalid fixture timeout.");
    requireThat(options.maxBuffer === undefined || Number.isSafeInteger(options.maxBuffer) && options.maxBuffer > 0,
      "Invalid fixture output bound.");
    const timeout = Math.min(wallLimitMs, options.timeout || wallLimitMs);
    const deadline = started + timeout;
    const wallDeadline = (Date.now() + timeout) / 1000;
    const maxBytes = Math.min(byteLimit, options.maxBuffer ?? byteLimit);
    requireThat(options.input === undefined || typeof options.input === "string" || ArrayBuffer.isView(options.input),
      "Unsupported fixture stdin.");
    requireThat(options.input === undefined || (typeof options.input === "string"
      ? Buffer.byteLength(options.input) : options.input.byteLength) <= byteLimit, "Fixture stdin exceeds its bound.");
    const env = options.env ?? process.env;
    fixtureFence(env);
    const index = inlineIndex(command, args);
    const code = args[index + 1];
    const wrapped = ["-c", boundedPython, code, String(wallDeadline), ...args.slice(index + 2)];

    const run = (executable: string, argv: string[], childEnv: NodeJS.ProcessEnv,
      input?: FixtureOptions["input"]): Promise<SpawnSyncReturns<string>> => new Promise((resolve) => {
      let child: ReturnType<typeof spawn> | undefined;
      let settled = false;
      let size = 0;
      const stdout: Buffer[] = [], stderr: Buffer[] = [];
      let timer: ReturnType<typeof setTimeout> | undefined;
      const finish = (status: number | null, signal: NodeJS.Signals | null, error?: Error) => {
        if (settled) return;
        settled = true;
        if (timer) clearTimeout(timer);
        options.signal?.removeEventListener("abort", abort);
        process.removeListener("exit", reap);
        const out = Buffer.concat(stdout).toString("utf8"), err = Buffer.concat(stderr).toString("utf8");
        resolve({ pid: child?.pid ?? 0, status, signal, stdout: out, stderr: err,
          output: [null, out, err], ...(error ? { error } : {}) });
      };
      const reap = () => { child?.kill("SIGKILL"); };
      const stop = (error: Error) => {
        if (settled) return;
        reap();
        child?.stdin?.destroy();
        child?.stdout?.destroy();
        child?.stderr?.destroy();
        finish(null, child ? "SIGKILL" : null, error);
      };
      const abort = () => stop(failure("ABORT_ERR", "Local fixture aborted."));
      if (options.signal?.aborted) { abort(); return; }
      const remaining = deadline - performance.now();
      if (remaining <= 0) { stop(failure("ETIMEDOUT", "Local fixture deadline exceeded.")); return; }
      try {
        child = spawn(executable, argv, {
          cwd: options.cwd, env: childEnv, shell: false, stdio: "pipe", windowsHide: options.windowsHide ?? true,
          argv0: executable === command ? options.argv0 : undefined,
          uid: options.uid, gid: options.gid,
        });
      } catch (error) { finish(null, null, error as Error); return; }
      child.once("error", (error) => {
        if (child?.pid === undefined) finish(null, null, error);
        else stop(error);
      });
      child.once("close", (status, signal) => finish(status, signal));
      for (const [stream, chunks] of [[child.stdout, stdout], [child.stderr, stderr]] as const) {
        stream?.on("data", (chunk: Buffer | string) => {
          if (settled) return;
          const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
          const take = Math.min(bytes.length, maxBytes - size);
          if (take) chunks.push(bytes.subarray(0, take));
          size += take;
          if (take < bytes.length) stop(failure("ENOBUFS", "Local fixture output limit exceeded."));
        });
      }
      child.stdin?.on("error", (error) => stop(error));
      process.once("exit", reap);
      options.signal?.addEventListener("abort", abort, { once: true });
      timer = setTimeout(() => stop(failure("ETIMEDOUT", "Local fixture deadline exceeded.")), remaining);
      if (options.signal?.aborted) abort();
      if (!settled) {
        try {
          child.stdin?.end(input === undefined || typeof input === "string" ? input
            : Buffer.from(input.buffer, input.byteOffset, input.byteLength));
        } catch (error) { stop(error as Error); }
      }
    });

    const project = process.env.CASEOPS_E2E_DOCKER_PROJECT?.trim();
    const compose = process.env.CASEOPS_E2E_DOCKER_COMPOSE_FILE?.trim();
    requireThat(Boolean(project) === Boolean(compose), "Docker fixture project/compose metadata must be paired.");
    if (!project) return await run(command, [...args.slice(0, index), ...wrapped], env, options.input);

    const release = process.env.CASEOPS_EXPECTED_RELEASE_SHA ?? process.env.CASEOPS_RELEASE_SHA;
    requireThat(release && /^[0-9a-f]{40}$/.test(release)
      && (!process.env.CASEOPS_RELEASE_SHA || process.env.CASEOPS_RELEASE_SHA === release)
      && new RegExp(`^caseops-acceptance-${release.slice(0, 12)}-[0-9a-f]{12}$`).test(project),
    "Docker fixture project must belong to the exact expected release.");
    requireThat(path.isAbsolute(compose!), "Docker fixture compose path must be absolute.");
    const localEndpoint = (value: string) => /^unix:\/\/\/[^\s]+$/.test(value)
      || ["npipe:////./pipe/docker_engine", "npipe:////./pipe/dockerDesktopLinuxEngine"].includes(value);
    requireThat(!process.env.DOCKER_HOST || localEndpoint(process.env.DOCKER_HOST), "Remote Docker hosts are forbidden.");
    requireThat(!process.env.DOCKER_TLS_VERIFY && !process.env.DOCKER_CERT_PATH, "Docker TLS overrides are forbidden.");
    const dockerEnv: NodeJS.ProcessEnv = {};
    for (const key of ["PATH", "Path", "SystemRoot", "WINDIR", "HOME", "USERPROFILE", "TEMP", "TMP",
      "DOCKER_CONFIG", "DOCKER_CONTEXT"]) {
      if (process.env[key] !== undefined) dockerEnv[key] = process.env[key];
    }
    let prefix: string[] = [];
    const checked = async (argv: string[]) => {
      const result = await run("docker", [...prefix, ...argv], dockerEnv);
      if (result.error || result.status !== 0) throw result;
      return result.stdout.trim();
    };
    const one = (json: string) => {
      const parsed = JSON.parse(json);
      requireThat(Array.isArray(parsed) && parsed.length === 1, "Ambiguous Docker fixture inspection.");
      return parsed[0];
    };
    const context = one(await checked(["context", "inspect"]));
    const endpoint = context?.Endpoints?.docker?.Host;
    requireThat(["default", "desktop-linux"].includes(context?.Name) && typeof endpoint === "string"
      && localEndpoint(endpoint) && (!process.env.DOCKER_HOST || process.env.DOCKER_HOST === endpoint),
    "Docker fixtures require a local daemon context.");
    delete dockerEnv.DOCKER_CONTEXT;
    prefix = ["--host", endpoint];
    requireThat(JSON.parse(await checked(["info", "--format", "{{json .OSType}}"])) === "linux",
      "Docker fixtures require the installed Linux API interpreter.");
    const id = await checked(["compose", "--project-name", project, "--file", compose!, "ps", "--quiet", "--no-trunc", "api"]);
    requireThat(/^[0-9a-f]{64}$/.test(id), "Expected one immutable API container ID.");
    const container = one(await checked(["inspect", "--type", "container", id]));
    const labels = container?.Config?.Labels;
    const normalize = (value: string) => value.replaceAll("\\", "/").replace(/^[A-Z]:/, (drive) => drive.toLowerCase());
    requireThat(container?.Id === id && labels?.["com.docker.compose.project"] === project
      && labels?.["com.docker.compose.service"] === "api" && labels?.["com.docker.compose.oneoff"] === "False"
      && typeof labels?.["com.docker.compose.project.config_files"] === "string"
      && normalize(labels["com.docker.compose.project.config_files"]) === normalize(compose!)
      && labels?.["org.opencontainers.image.revision"] === release
      && container?.State?.Running === true && !container.State.Paused && !container.State.Restarting && !container.State.Dead,
    "Docker API container ownership/release inspection failed.");
    const values = new Map<string, string>((container.Config.Env ?? []).map((entry: string) => {
      const at = entry.indexOf("="); return [entry.slice(0, at), entry.slice(at + 1)];
    }));
    requireThat(["e2e", "ci"].includes(values.get("CASEOPS_ENV") ?? "") && values.get("CASEOPS_RELEASE_SHA") === release
      && values.get("CASEOPS_DATABASE_URL") === "postgresql+psycopg://caseops:caseops@postgres:5432/caseops"
      && container?.NetworkSettings?.Networks?.[`${project}_default`], "Docker API is not an isolated fixture target.");
    const ports = container?.NetworkSettings?.Ports?.["8000/tcp"];
    requireThat(Array.isArray(ports) && ports.length > 0
      && ports.every((port) => ["127.0.0.1", "::1"].includes(port.HostIp)), "Docker API must be published only on loopback.");
    const forwarded: string[] = [];
    for (const key of fixtureKeys) {
      if (!code.includes(key)) continue;
      const value = env[key];
      requireThat(typeof value === "string" && !value.includes("\0") && Buffer.byteLength(value) <= 16_384,
        "Missing or oversized caller fixture field.");
      forwarded.push("--env", `${key}=${value}`);
    }
    const flagsStart = /^uv(?:\.exe)?$/.test(path.basename(command.replaceAll("\\", "/"))) ? 5 : 0;
    return await run("docker", [...prefix, "exec", "--interactive", ...forwarded, id,
      "/usr/local/bin/python", ...args.slice(flagsStart, index), ...wrapped], dockerEnv, options.input);
  } catch (error) {
    // Inspection errors retain structured process semantics, never fall back to the host.
    if (error && typeof error === "object" && "output" in error && "status" in error) {
      return error as SpawnSyncReturns<string>;
    }
    return empty(error instanceof Error ? error : failure("EINVAL", "Local fixture validation failed."));
  }
}
