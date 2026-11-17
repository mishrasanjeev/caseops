// @vitest-environment node
import assert from "node:assert/strict";
import { spawn, type ChildProcess } from "node:child_process";
import { AsyncLocalStorage } from "node:async_hooks";
import { X509Certificate, createHash } from "node:crypto";
import { once } from "node:events";
import fs from "node:fs";
import https from "node:https";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { rootCertificates } from "node:tls";
import { fileURLToPath } from "node:url";

import { afterAll, aroundEach, beforeAll, expect, test } from "vitest";

const require = createRequire(import.meta.url);
const web = path.resolve(import.meta.dirname, "..");
const scripts = path.join(web, "scripts");
const denied = "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b";
const fingerprint = (pem: string) => createHash("sha256").update(new X509Certificate(pem).raw).digest("hex");
let temp: string;
let trust: string;
const nativeTimings: Array<{ index: number; elapsedMs: number; code: unknown; signal: unknown }> = [];
type NativeScope = { signal: AbortSignal; closed: boolean; children: Set<ChildProcess>; closings: Set<Promise<unknown>> };
const nativeScope = new AsyncLocalStorage<NativeScope>();

aroundEach(async (runTest, context) => {
  const scope: NativeScope = { signal: context.signal, closed: false, children: new Set(), closings: new Set() };
  await nativeScope.run(scope, async () => {
    try { await runTest(); }
    finally {
      scope.closed = true;
      for (const child of scope.children) child.kill();
      await Promise.allSettled([...scope.closings]);
    }
  });
});

function activeScope() {
  const scope = nativeScope.getStore();
  if (!scope || scope.closed) throw new Error("Native trust test scope ended.");
  scope.signal.throwIfAborted();
  return scope;
}

function cleanEnv(): NodeJS.ProcessEnv {
  const env = { ...process.env };
  for (const key of ["NODE_OPTIONS", "NODE_EXTRA_CA_CERTS", "NODE_USE_SYSTEM_CA", "NODE_TLS_REJECT_UNAUTHORIZED", "SSL_CERT_FILE", "SSL_CERT_DIR", "OPENSSL_CONF"]) delete env[key];
  return env;
}

async function child(args: string[], env = cleanEnv(), options?: { file: string; cwd: string; timeout: 5000 }) {
  const scope = activeScope();
  const started = performance.now();
  const index = nativeTimings.length;
  nativeTimings.push({ index, elapsedMs: -1, code: null, signal: null });
  const budget = options?.timeout ?? 8_000;
  const proc = spawn(options?.file ?? process.execPath, args, { env, cwd: options?.cwd, signal: scope.signal, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  scope.children.add(proc);
  let stdout = "";
  let stderr = "";
  let timedOut = false;
  proc.stdout.on("data", (value) => { stdout += value; });
  proc.stderr.on("data", (value) => { stderr += value; });
  const remaining = Math.max(0, budget - (performance.now() - started));
  const timer = setTimeout(() => { timedOut = true; proc.kill(); }, remaining);
  let failure: Error | undefined;
  const closed = new Promise<{ code: number | null; signal: NodeJS.Signals | null }>(resolve => {
    proc.once("error", error => { failure = error; });
    proc.once("close", (code, signal) => resolve({ code, signal }));
  });
  scope.closings.add(closed);
  try {
    // Abort emits error before close. Await physical closure before releasing
    // fixture files, including on a timed-out test or a failed spawn.
    const { code, signal } = await closed;
    nativeTimings[index] = { index, elapsedMs: Math.round(performance.now() - started), code, signal };
    if (failure) throw failure;
    if (timedOut || performance.now() - started > budget || signal !== null || code === null) throw new Error("Native trust child did not finish inside its original deadline.");
    return { code, signal, stdout, stderr };
  } finally {
    clearTimeout(timer);
    scope.children.delete(proc);
    scope.closings.delete(closed);
  }
}

beforeAll(() => {
  // Node resolves the copied module's __dirname through macOS /var -> /private/var.
  // Use that same canonical fixture path in the child's exact trust environment.
  temp = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "caseops-node-trust-")));
  trust = path.join(temp, "trust");
  fs.mkdirSync(trust);
  for (const name of ["node-trust.cjs", "node-trust-start.cjs"]) {
    const source = path.join(scripts, name);
    if (fs.existsSync(source)) fs.copyFileSync(source, path.join(trust, name));
  }
});

// Independent native controls share no files they mutate. Bound startup fan-out
// and await every started child even when one rejects; never accept a killed
// process as a successful negative security control.
async function batches<T>(values: readonly T[], check: (value: T) => Promise<void>) {
  let next = 0;
  const worker = async () => {
    while (next < values.length) {
      activeScope();
      const index = next++;
      await check(values[index]);
    }
  };
  // Two physical children at most, starting the next independent control when
  // either slot is free. Always join both slots, including on rejection.
  const results = await Promise.allSettled(Array.from({ length: Math.min(2, values.length) }, worker));
  const failures = results.filter(result => result.status === "rejected");
  if (failures.length) throw new AggregateError(failures.map(result => result.reason), "Native trust controls failed.");
}

afterAll(() => {
  const retained = path.join(web, "../../test-results/native-trust", path.basename(temp));
  fs.mkdirSync(retained, { recursive: true });
  fs.writeFileSync(path.join(retained, "timings.json"), JSON.stringify(nativeTimings));
  fs.rmSync(temp, { recursive: true, force: true });
});

test("Docker generates trust before npm and inherits it into build and runtime", () => {
  const docker = fs.readFileSync(path.join(web, "Dockerfile"), "utf8");
  expect(docker).toMatch(/FROM node:22\.23\.4-alpine AS trusted-base/);
  expect(docker.indexOf("node-trust.cjs --generate")).toBeLessThan(docker.indexOf("npm-tooling.mjs ci"));
  expect(docker).toMatch(/FROM trusted-base AS builder-tooling/);
  expect(docker).toMatch(/FROM builder-tooling AS deps/);
  expect(docker).toMatch(/FROM trusted-base AS runner/);
  expect(docker).toContain("SSL_CERT_DIR=/opt/caseops/trust/empty");
  expect(docker).toContain('test "$(node /opt/caseops/scripts/mobile/npm-tooling.mjs --version)" = "11.12.1"');
  expect(docker).toContain("RUN node /opt/caseops/scripts/mobile/npm-tooling.mjs ci --no-audit --no-fund");
  expect(docker).toContain("RUN node /opt/caseops/scripts/mobile/npm-tooling.mjs prune --omit=dev --no-audit --no-fund");
  expect(docker).toContain("RUN node /opt/caseops/scripts/mobile/npm-tooling.mjs run build");
  const runner = docker.split("FROM trusted-base AS runner")[1];
  expect(runner).not.toMatch(/COPY.*(?:builder-tooling|scripts\/mobile|apps\/mobile\/vendor)/);
});

test("Docker's exact runtime tool-absence program rejects files, dangling launchers and metadata errors", async () => {
  const docker = fs.readFileSync(path.join(web, "Dockerfile"), "utf8");
  const program = docker.match(/&& node -e '([^']+UNUSED_GLOBAL_TOOL_REMAINS[^']+)'/);
  assert.ok(program, "Missing actual trusted-base absence program");
  await batches(["absent", "file", "dangling-link", "metadata-error"], async mode => {
    const root = path.join(temp, `tool-absence-${mode}`);
    fs.mkdirSync(root);
    const name = mode === "dangling-link" ? "/usr/local/bin/npm" : "/usr/local/lib/node_modules/npm";
    const target = path.join(root, name.slice(1));
    if (mode === "file" || mode === "dangling-link") {
      fs.mkdirSync(path.dirname(target), { recursive: true });
      if (mode === "file") fs.writeFileSync(target, "synthetic retained tool");
      else {
        const missing = path.join(root, "missing-owned-target");
        // Windows junctions exercise the same real dangling-entry refusal
        // without requiring the developer's symlink-administration privilege.
        fs.symlinkSync(missing, target, process.platform === "win32" ? "junction" : "file");
        expect(fs.lstatSync(target).isSymbolicLink()).toBe(true);
        expect(fs.existsSync(target)).toBe(false);
      }
    }
    const prelude = `const actualFs=require('node:fs'), actualPath=require('node:path');
      const originalStat=actualFs.lstatSync;
      actualFs.lstatSync=(p,...args)=>{
        if(${JSON.stringify(mode)}==='metadata-error') throw Error('SYNTHETIC_METADATA_REFUSAL');
        if(typeof p!=='string'||!p.startsWith('/')) throw Error('UNEXPECTED_ABSENCE_PATH');
        return originalStat(actualPath.join(${JSON.stringify(root)},p.slice(1)),...args);
      };`;
    const result = await child(["-e", prelude + program[1]]);
    expect(result.code, mode).toBe(mode === "absent" ? 0 : 1);
    expect(result.stdout).toBe("");
    if (mode === "file" || mode === "dangling-link") expect(fs.lstatSync(target)).toBeTruthy();
  });
});

test("Docker runtime explicitly preloads the guard independently of NODE_OPTIONS", () => {
  const docker = fs.readFileSync(path.join(web, "Dockerfile"), "utf8");
  expect(docker).toContain("node --use-openssl-ca --require /opt/caseops/trust/node-trust-start.cjs");
});

function policy() {
  return require(path.join(scripts, "node-trust.cjs")) as {
    createBundle: (roots: readonly string[]) => string;
  };
}

test("preserves every current upstream root when G3 is already absent", () => {
  const bundle = policy().createBundle(rootCertificates);
  const before = rootCertificates.map(fingerprint);
  const after = (bundle.match(/-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----/g) ?? []).map(fingerprint);
  expect(before).toHaveLength(116);
  expect(before.filter((value) => value === denied)).toHaveLength(0);
  expect(after).toHaveLength(116);
  expect(after.sort()).toEqual(before.filter((value) => value !== denied).sort());
  expect(createHash("sha256").update(bundle).digest("hex")).toBe("c2929361a5be0afcf231461fa8b4b00e4454d49cfea9592c12089d8efdc8c64f");
});

test("requires the exact shipping Node runtime for positive trust acceptance", () => {
  expect(process.versions.node).toBe("22.23.4");
});

test("ended native test scope cannot start a later child", async () => {
  const scope: NativeScope = { signal: new AbortController().signal, closed: true, children: new Set(), closings: new Set() };
  const count = nativeTimings.length;
  await nativeScope.run(scope, async () => {
    await expect(child(["-e", "throw new Error('MUST_NOT_START')"])).rejects.toThrow("scope ended");
  });
  expect(nativeTimings).toHaveLength(count);
  expect(scope.children.size).toBe(0);
});

test("aborted native child physically closes before its fixture can be removed", async () => {
  const controller = new AbortController();
  const scope: NativeScope = { signal: controller.signal, closed: false, children: new Set(), closings: new Set() };
  const marker = path.join(temp, "abort-ready");
  const result = Promise.allSettled([nativeScope.run(scope, () => child(["-e",
    `require('node:fs').writeFileSync(${JSON.stringify(marker)}, 'ready'); setInterval(()=>{},1000);`]))]);
  let completed: PromiseSettledResult<unknown> | undefined;
  const completion = result.then(values => { completed = values[0]; });
  let readinessFailure: unknown;
  try {
    const deadline = performance.now() + 5_000;
    while (!fs.existsSync(marker) && performance.now() < deadline) {
      if (completed?.status === "rejected") throw completed.reason;
      if (completed) throw new Error("Native child completed without its readiness barrier.");
      await new Promise(resolve => setTimeout(resolve, 20));
    }
    expect(fs.existsSync(marker), "Real native child must reach its readiness barrier").toBe(true);
  } catch (error) { readinessFailure = error; }
  finally { controller.abort(); await completion; }
  const settled = await result;
  if (readinessFailure) throw readinessFailure;
  expect(settled[0].status).toBe("rejected");
  if (settled[0].status === "rejected") expect(settled[0].reason.name).toBe("AbortError");
  expect(scope.children.size).toBe(0);
  expect(scope.closings.size).toBe(0);
  fs.unlinkSync(marker);
});

test("already-removed G3 trust filtering is idempotent", () => {
  const once = policy().createBundle(rootCertificates);
  const roots = once.match(/-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----/g) ?? [];
  expect(policy().createBundle(roots)).toBe(once);
});

test("reintroduced compromised root is rejected at the exact root boundary", () => {
  const compromised = "-----BEGIN CERTIFICATE-----\nMIICTjCCAdOgAwIBAgIKPPYHqWhwDtqLhDAKBggqhkjOPQQDAzBrMQswCQYDVQQG\nEwJJTjETMBEGA1UECxMKZW1TaWduIFBLSTElMCMGA1UEChMcZU11ZGhyYSBUZWNo\nbm9sb2dpZXMgTGltaXRlZDEgMB4GA1UEAxMXZW1TaWduIEVDQyBSb290IENBIC0g\nRzMwHhcNMTgwMjE4MTgzMDAwWhcNNDMwMjE4MTgzMDAwWjBrMQswCQYDVQQGEwJJ\nTjETMBEGA1UECxMKZW1TaWduIFBLSTElMCMGA1UEChMcZU11ZGhyYSBUZWNobm9s\nb2dpZXMgTGltaXRlZDEgMB4GA1UEAxMXZW1TaWduIEVDQyBSb290IENBIC0gRzMw\ndjAQBgcqhkjOPQIBBgUrgQQAIgNiAAQjpQy4LRL1KPOxst3iAhKAnjlfSU2fySU0\nWXTsuwYc58Byr+iuL+FBVIcUqEqy6HyC5ltqtdyzdc6LBtCGI79G1Y4PPwT01xyS\nfvalY8L1X44uT6EYGQIrMgqCZH0Wk9GjQjBAMB0GA1UdDgQWBBR8XQKEE9TMipuB\nzhccLikenEhjQjAOBgNVHQ8BAf8EBAMCAQYwDwYDVR0TAQH/BAUwAwEB/zAKBggq\nhkjOPQQDAwNpADBmAjEAvvNhzwIQHWSVB7gYboiFBS+DCBeQyh+KTOgNG3qxrdWB\nCUfvO6wIBHxcmbHtRwfSAjEAnbpV/KlK6O3t5nYBQnvI+GDZjVGLVTv7jHvrZQnD\n+JbNR6iC8hZVdyR+EhCVBCyj\n-----END CERTIFICATE-----\n";
  expect(fingerprint(compromised)).toBe(denied);
  expect(() => policy().createBundle([...rootCertificates, compromised])).toThrow();
  expect(() => policy().createBundle([...rootCertificates.slice(1), compromised])).toThrow();
});

test("missing, duplicate or changed input roots cannot create a bundle", () => {
  const roots = [...rootCertificates];
  expect(() => policy().createBundle(roots.slice(1))).toThrow();
  expect(() => policy().createBundle([...roots, roots[0]])).toThrow();
  expect(() => policy().createBundle([...roots.slice(1), roots[1]])).toThrow();
  expect(() => policy().createBundle(["not a certificate", ...roots.slice(1)])).toThrow();
});

test("generates immutable bundle and permits guarded startup", async () => {
  const generated = await child([path.join(trust, "node-trust.cjs"), "--generate"]);
  expect(generated.code, generated.stderr).toBe(0);
  expect(fs.statSync(path.join(trust, "ca-bundle.pem")).mode & 0o222).toBe(0);
  const result = await child(["--use-openssl-ca", "--require", path.join(trust, "node-trust-start.cjs"), "-e", "console.log('started')"], {
    ...cleanEnv(), NODE_OPTIONS: "--use-openssl-ca", SSL_CERT_FILE: path.join(trust, "ca-bundle.pem"), SSL_CERT_DIR: path.join(trust, "empty"),
  });
  expect(result.code, result.stderr).toBe(0);
  expect(result.stdout.trim()).toBe("started");
});

test.each(["valid", "tampered", "read-error", "stat-error", "open-error", "path-replacement"])("bundle descriptor remains bound and closes on %s", async (scenario) => {
  const dir = path.join(temp, `descriptor-${scenario}`);
  fs.mkdirSync(dir);
  fs.copyFileSync(path.join(scripts, "node-trust.cjs"), path.join(dir, "node-trust.cjs"));
  expect((await child([path.join(dir, "node-trust.cjs"), "--generate"])).code).toBe(0);
  const bundle = path.join(dir, "ca-bundle.pem");
  fs.chmodSync(bundle, 0o644);
  if (scenario === "tampered") fs.appendFileSync(bundle, "\n");
  if (scenario === "open-error") fs.unlinkSync(bundle);
  const code = `
    const fs = require('node:fs');
    const target = ${JSON.stringify(bundle)};
    const scenario = ${JSON.stringify(scenario)};
    const policy = require(${JSON.stringify(path.join(dir, "node-trust.cjs"))});
    const original = { open: fs.openSync, stat: fs.fstatSync, read: fs.readFileSync, close: fs.closeSync };
    const events = [];
    let descriptor;
    fs.openSync = (name, ...args) => {
      if (name === target) events.push('open');
      const value = original.open(name, ...args);
      if (name === target) descriptor = value;
      return value;
    };
    fs.fstatSync = (value, ...args) => {
      if (value === descriptor) {
        events.push('stat');
        if (scenario === 'stat-error') throw new Error('injected descriptor stat fault');
      }
      const result = original.stat(value, ...args);
      if (value === descriptor && scenario === 'path-replacement') {
        fs.renameSync(target, target + '.opened');
        fs.copyFileSync(target + '.opened', target);
      }
      return result;
    };
    fs.readFileSync = (value, ...args) => {
      if (value === target) throw new Error('bundle must not be reopened by path');
      if (value === descriptor) {
        events.push('read');
        if (scenario === 'read-error') throw new Error('injected descriptor read fault');
      }
      return original.read(value, ...args);
    };
    fs.closeSync = (value) => {
      if (value === descriptor) events.push('close');
      return original.close(value);
    };
    let outcome = 'accepted';
    try { policy.verifyRuntime(); } catch { outcome = 'rejected'; }
    console.log(JSON.stringify({ outcome, events }));
  `;
  const result = await child(["--use-openssl-ca", "-e", code], {
    ...cleanEnv(), NODE_OPTIONS: "--use-openssl-ca", SSL_CERT_FILE: bundle, SSL_CERT_DIR: path.join(dir, "empty"),
  });
  expect(result.code, result.stderr).toBe(0);
  const expectedEvents = scenario === "open-error" ? ["open"]
    : scenario === "stat-error" || scenario === "path-replacement" ? ["open", "stat", "close"]
      : ["open", "stat", "read", "close"];
  expect(JSON.parse(result.stdout)).toEqual({ outcome: scenario === "valid" ? "accepted" : "rejected", events: expectedEvents });
});

test("missing or tampered bundle and nonempty or missing CA directory fail before app", async () => {
  const generated = path.join(temp, "invalid-trust-generated");
  fs.mkdirSync(generated);
  fs.copyFileSync(path.join(scripts, "node-trust.cjs"), path.join(generated, "node-trust.cjs"));
  expect((await child([path.join(generated, "node-trust.cjs"), "--generate"])).code).toBe(0);
  const canonical = fs.readFileSync(path.join(generated, "ca-bundle.pem"));
  await batches(["missing-bundle", "tampered-bundle", "nonempty-directory", "missing-directory"], async mode => {
    const dir = path.join(temp, "invalid-trust-" + mode);
    fs.mkdirSync(dir);
    for (const name of ["node-trust.cjs", "node-trust-start.cjs"]) fs.copyFileSync(path.join(scripts, name), path.join(dir, name));
    const args = ["--use-openssl-ca", "--require", path.join(dir, "node-trust-start.cjs"), "-e", "console.log('APP_RAN')"];
    const env = { ...cleanEnv(), NODE_OPTIONS: "--use-openssl-ca", SSL_CERT_FILE: path.join(dir, "ca-bundle.pem"), SSL_CERT_DIR: path.join(dir, "empty") };
    if (mode !== "missing-bundle") fs.writeFileSync(env.SSL_CERT_FILE, mode === "tampered-bundle" ? Buffer.concat([canonical, Buffer.from("\n")]) : canonical, { mode: 0o444 });
    if (mode !== "missing-directory") fs.mkdirSync(env.SSL_CERT_DIR);
    if (mode === "nonempty-directory") fs.writeFileSync(path.join(env.SSL_CERT_DIR, "unexpected.pem"), "unexpected");
    const result = await child(args, env);
    expect(result.code).not.toBe(0);
    expect(result.stdout).not.toContain("APP_RAN");
    expect(result.stderr).toContain("CaseOps Node trust policy refused startup.");
  });
});

test("extra or competing trust settings fail before app", async () => {
  const dir = path.join(temp, "env-trust");
  fs.mkdirSync(dir);
  for (const name of ["node-trust.cjs", "node-trust-start.cjs"]) fs.copyFileSync(path.join(scripts, name), path.join(dir, name));
  expect((await child([path.join(dir, "node-trust.cjs"), "--generate"])).code).toBe(0);
  const base = { ...cleanEnv(), NODE_OPTIONS: "--use-openssl-ca", SSL_CERT_FILE: path.join(dir, "ca-bundle.pem"), SSL_CERT_DIR: path.join(dir, "empty") };
  const changes = [
    { NODE_EXTRA_CA_CERTS: base.SSL_CERT_FILE }, { NODE_USE_SYSTEM_CA: "1" },
    { NODE_TLS_REJECT_UNAUTHORIZED: "0" }, { NODE_OPTIONS: "--use-bundled-ca" },
    { NODE_OPTIONS: "" }, { SSL_CERT_FILE: "unexpected.pem" }, { SSL_CERT_DIR: os.tmpdir() },
    { OPENSSL_CONF: "unexpected.cnf" },
  ];
  const controls = [
    ...changes.map(changed => ({ args: ["--use-openssl-ca", "--require", path.join(dir, "node-trust-start.cjs"), "-e", "console.log('APP_RAN')"], env: { ...base, ...changed }, label: JSON.stringify(changed) })),
    ...["--use-bundled-ca", "--no-use-openssl-ca"].map(flag => ({ args: [flag, "--require", path.join(dir, "node-trust-start.cjs"), "-e", "console.log('APP_RAN')"], env: base, label: flag })),
  ];
  await batches(controls, async control => {
    const result = await child(control.args, control.env);
    expect(result.code, control.label).not.toBe(0);
    expect(result.stdout).not.toContain("APP_RAN");
  });
});

test("actual fetch and https enforce selected CA and hostname verification offline", async () => {
  const probe = fileURLToPath(new URL("../../../tests/fixtures/node-default-tls-probe.cjs", import.meta.url));
  await batches(["https://example.com:443/", "http://127.0.0.1:443/", "https://127.0.0.1/", "https://user@127.0.0.1:443/", "https://127.0.0.1:443/other"], async target => {
    const rejected = await child([probe, target]);
    expect(rejected.code, target).not.toBe(0);
    expect(rejected.stdout, target).toBe("");
    expect(rejected.stderr, target).toContain("only an explicit loopback HTTPS origin");
  });
  const fixture = path.join(temp, "tls");
  fs.mkdirSync(fixture);
  const openssl = process.env.CASEOPS_TEST_OPENSSL ?? (process.platform === "win32" ? "C:/Program Files/Git/usr/bin/openssl.exe" : "openssl");
  const run = (args: string[]) => {
    return child(args, cleanEnv(), { file: openssl, cwd: fixture, timeout: 5000 }).then(result => {
      expect(result.code, result.stderr).toBe(0);
    });
  };
  // Fresh P-256 fixtures exercise the same default-client trust/hostname
  // boundaries without repeated RSA prime searches inside the 15-second test.
  await batches(["trusted", "untrusted", "wrong-host"], async name => {
    const common = ["req", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes", "-keyout", `${name}.key`];
    if (name === "wrong-host") await run([...common, "-new", "-out", "wrong-host.csr", "-subj", "/CN=CaseOps local-only wrong hostname"]);
    else await run([...common, "-x509", "-out", `${name}.pem`, "-days", "2", "-subj", `/CN=CaseOps local-only ${name} TLS fixture`, "-addext", "subjectAltName=IP:127.0.0.1"]);
  });
  fs.writeFileSync(path.join(fixture, "wrong-host.ext"), "subjectAltName=DNS:wrong.invalid\n");
  await run(["x509", "-req", "-in", "wrong-host.csr", "-CA", "trusted.pem", "-CAkey", "trusted.key", "-CAcreateserial", "-out", "wrong-host.pem", "-days", "2", "-extfile", "wrong-host.ext"]);
  const empty = path.join(fixture, "empty");
  fs.mkdirSync(empty);
  const env = { ...cleanEnv(), NODE_OPTIONS: "--use-openssl-ca", SSL_CERT_FILE: path.join(fixture, "trusted.pem"), SSL_CERT_DIR: empty };
  await batches(["trusted", "untrusted", "wrong-host"], async name => {
    const receivedMarkers: string[][] = [];
    const server = https.createServer({ key: fs.readFileSync(path.join(fixture, `${name}.key`)), cert: fs.readFileSync(path.join(fixture, `${name}.pem`)) }, (request, response) => {
      const markers: string[] = [];
      for (let index = 0; index < request.rawHeaders.length; index += 2) {
        if (request.rawHeaders[index].toLowerCase() === "x-caseops-automated-test") markers.push(request.rawHeaders[index + 1]);
      }
      receivedMarkers.push(markers);
      response.end("local-only");
    });
    const sockets = new Set<import("node:net").Socket>();
    server.on("connection", (socket) => { sockets.add(socket); socket.once("close", () => sockets.delete(socket)); });
    server.listen(0, "127.0.0.1");
    await once(server, "listening");
    try {
      const address = server.address();
      assert.ok(address && typeof address !== "string");
      const result = await child(["--use-openssl-ca", probe, `https://127.0.0.1:${address.port}/`], env);
      expect(result.code, result.stderr).toBe(0);
      const expected = name === "trusted" ? "local-only" : name === "untrusted" ? "DEPTH_ZERO_SELF_SIGNED_CERT" : "ERR_TLS_CERT_ALTNAME_INVALID";
      expect(JSON.parse(result.stdout)).toEqual([expected, expected]);
      expect(receivedMarkers).toEqual(name === "trusted" ? [["no-paid-providers"], ["no-paid-providers"]] : []);
    } finally {
      for (const socket of sockets) socket.destroy();
      await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    }
  });
});
