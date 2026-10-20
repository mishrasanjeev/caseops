// @vitest-environment node
import assert from "node:assert/strict";
import { execFileSync, spawn } from "node:child_process";
import { X509Certificate, createHash } from "node:crypto";
import { once } from "node:events";
import fs from "node:fs";
import https from "node:https";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { rootCertificates } from "node:tls";

import { afterAll, beforeAll, expect, test } from "vitest";

const require = createRequire(import.meta.url);
const web = path.resolve(import.meta.dirname, "..");
const scripts = path.join(web, "scripts");
const denied = "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b";
const fingerprint = (pem: string) => createHash("sha256").update(new X509Certificate(pem).raw).digest("hex");
let temp: string;
let trust: string;

function cleanEnv(): NodeJS.ProcessEnv {
  const env = { ...process.env };
  for (const key of ["NODE_OPTIONS", "NODE_EXTRA_CA_CERTS", "NODE_USE_SYSTEM_CA", "NODE_TLS_REJECT_UNAUTHORIZED", "SSL_CERT_FILE", "SSL_CERT_DIR", "OPENSSL_CONF"]) delete env[key];
  return env;
}

async function child(args: string[], env = cleanEnv()) {
  const proc = spawn(process.execPath, args, { env, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  let stdout = "";
  let stderr = "";
  proc.stdout.on("data", (value) => { stdout += value; });
  proc.stderr.on("data", (value) => { stderr += value; });
  const timer = setTimeout(() => proc.kill(), 8_000);
  try {
    const [code, signal] = await once(proc, "close");
    return { code, signal, stdout, stderr };
  } finally {
    clearTimeout(timer);
  }
}

beforeAll(() => {
  temp = fs.mkdtempSync(path.join(os.tmpdir(), "caseops-node-trust-"));
  trust = path.join(temp, "trust");
  fs.mkdirSync(trust);
  for (const name of ["node-trust.cjs", "node-trust-start.cjs"]) {
    const source = path.join(scripts, name);
    if (fs.existsSync(source)) fs.copyFileSync(source, path.join(trust, name));
  }
});

afterAll(() => fs.rmSync(temp, { recursive: true, force: true }));

test("Docker generates trust before npm and inherits it into build and runtime", () => {
  const docker = fs.readFileSync(path.join(web, "Dockerfile"), "utf8");
  expect(docker).toMatch(/FROM node:22\.14\.0-alpine AS trusted-base/);
  expect(docker.indexOf("node-trust.cjs --generate")).toBeLessThan(docker.indexOf("npm ci"));
  expect(docker).toMatch(/FROM trusted-base AS deps/);
  expect(docker).toMatch(/FROM trusted-base AS runner/);
  expect(docker).toContain("SSL_CERT_DIR=/opt/caseops/trust/empty");
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

test("removes only exact G3 and preserves every other bundled root", () => {
  const bundle = policy().createBundle(rootCertificates);
  const before = rootCertificates.map(fingerprint);
  const after = (bundle.match(/-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----/g) ?? []).map(fingerprint);
  expect(before).toHaveLength(149);
  expect(before.filter((value) => value === denied)).toHaveLength(1);
  expect(after).toHaveLength(148);
  expect(after.sort()).toEqual(before.filter((value) => value !== denied).sort());
  expect(createHash("sha256").update(bundle).digest("hex")).toBe("553a980a0de1e9e7fd65bcea308db009f4e2269f08475227d6f6b04beeab2554");
});

test("missing, duplicate or changed input roots cannot create a bundle", () => {
  const roots = [...rootCertificates];
  expect(() => policy().createBundle(roots.filter((pem) => fingerprint(pem) !== denied))).toThrow();
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

test("missing or tampered bundle and nonempty or missing CA directory fail before app", async () => {
  const dir = path.join(temp, "invalid-trust");
  fs.mkdirSync(dir);
  for (const name of ["node-trust.cjs", "node-trust-start.cjs"]) fs.copyFileSync(path.join(scripts, name), path.join(dir, name));
  const args = ["--use-openssl-ca", "--require", path.join(dir, "node-trust-start.cjs"), "-e", "console.log('APP_RAN')"];
  const env = { ...cleanEnv(), NODE_OPTIONS: "--use-openssl-ca", SSL_CERT_FILE: path.join(dir, "ca-bundle.pem"), SSL_CERT_DIR: path.join(dir, "empty") };
  const reject = async () => {
    const result = await child(args, env);
    expect(result.code).not.toBe(0);
    expect(result.stdout).not.toContain("APP_RAN");
    expect(result.stderr).toContain("CaseOps Node trust policy refused startup.");
  };
  await reject();
  expect((await child([path.join(dir, "node-trust.cjs"), "--generate"])).code).toBe(0);
  fs.chmodSync(env.SSL_CERT_FILE, 0o644);
  fs.appendFileSync(env.SSL_CERT_FILE, "\n");
  await reject();
  fs.writeFileSync(env.SSL_CERT_FILE, policy().createBundle(rootCertificates));
  fs.chmodSync(env.SSL_CERT_DIR, 0o755);
  fs.writeFileSync(path.join(env.SSL_CERT_DIR, "unexpected.pem"), "unexpected");
  await reject();
  fs.rmSync(path.join(env.SSL_CERT_DIR, "unexpected.pem"));
  fs.rmdirSync(env.SSL_CERT_DIR);
  await reject();
});

test("extra or competing trust settings fail before app", async () => {
  const dir = path.join(temp, "env-trust");
  fs.mkdirSync(dir);
  for (const name of ["node-trust.cjs", "node-trust-start.cjs"]) fs.copyFileSync(path.join(scripts, name), path.join(dir, name));
  expect((await child([path.join(dir, "node-trust.cjs"), "--generate"])).code).toBe(0);
  const base = { ...cleanEnv(), NODE_OPTIONS: "--use-openssl-ca", SSL_CERT_FILE: path.join(dir, "ca-bundle.pem"), SSL_CERT_DIR: path.join(dir, "empty") };
  for (const changed of [
    { NODE_EXTRA_CA_CERTS: base.SSL_CERT_FILE }, { NODE_USE_SYSTEM_CA: "1" },
    { NODE_TLS_REJECT_UNAUTHORIZED: "0" }, { NODE_OPTIONS: "--use-bundled-ca" },
    { NODE_OPTIONS: "" }, { SSL_CERT_FILE: "unexpected.pem" }, { SSL_CERT_DIR: os.tmpdir() },
    { OPENSSL_CONF: "unexpected.cnf" },
  ]) {
    const result = await child(["--use-openssl-ca", "--require", path.join(dir, "node-trust-start.cjs"), "-e", "console.log('APP_RAN')"], { ...base, ...changed });
    expect(result.code, JSON.stringify(changed)).not.toBe(0);
    expect(result.stdout).not.toContain("APP_RAN");
  }
  for (const flag of ["--use-bundled-ca", "--no-use-openssl-ca"]) {
    const competing = await child([flag, "--require", path.join(dir, "node-trust-start.cjs"), "-e", "console.log('APP_RAN')"], base);
    expect(competing.code, flag).not.toBe(0);
    expect(competing.stdout).not.toContain("APP_RAN");
  }
});

test("actual fetch and https enforce selected CA and hostname verification offline", async () => {
  const fixture = path.join(temp, "tls");
  fs.mkdirSync(fixture);
  const openssl = process.env.CASEOPS_TEST_OPENSSL ?? (process.platform === "win32" ? "C:/Program Files/Git/usr/bin/openssl.exe" : "openssl");
  const run = (args: string[]) => execFileSync(openssl, args, { cwd: fixture, timeout: 5_000, windowsHide: true, stdio: "pipe" });
  for (const name of ["trusted", "untrusted"]) {
    run(["req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", `${name}.key`, "-out", `${name}.pem`, "-days", "2", "-subj", `/CN=CaseOps local-only ${name} TLS fixture`, "-addext", "subjectAltName=IP:127.0.0.1"]);
  }
  run(["req", "-new", "-newkey", "rsa:2048", "-nodes", "-keyout", "wrong-host.key", "-out", "wrong-host.csr", "-subj", "/CN=CaseOps local-only wrong hostname"]);
  fs.writeFileSync(path.join(fixture, "wrong-host.ext"), "subjectAltName=DNS:wrong.invalid\n");
  run(["x509", "-req", "-in", "wrong-host.csr", "-CA", "trusted.pem", "-CAkey", "trusted.key", "-CAcreateserial", "-out", "wrong-host.pem", "-days", "2", "-extfile", "wrong-host.ext"]);
  const empty = path.join(fixture, "empty");
  fs.mkdirSync(empty);
  const env = { ...cleanEnv(), NODE_OPTIONS: "--use-openssl-ca", SSL_CERT_FILE: path.join(fixture, "trusted.pem"), SSL_CERT_DIR: empty };
  for (const name of ["trusted", "untrusted", "wrong-host"]) {
    const server = https.createServer({ key: fs.readFileSync(path.join(fixture, `${name}.key`)), cert: fs.readFileSync(path.join(fixture, `${name}.pem`)) }, (_request, response) => response.end("local-only"));
    const sockets = new Set<import("node:net").Socket>();
    server.on("connection", (socket) => { sockets.add(socket); socket.once("close", () => sockets.delete(socket)); });
    server.listen(0, "127.0.0.1");
    await once(server, "listening");
    try {
      const address = server.address();
      assert.ok(address && typeof address !== "string");
      const code = `const https=require('node:https');const url='https://127.0.0.1:${address.port}/';(async()=>{const out=[];try{const r=await fetch(url);out.push(await r.text());}catch(e){out.push(e.cause?.code);}await new Promise(resolve=>{const r=https.get(url,async s=>{let b='';for await(const x of s)b+=x;out.push(b);resolve();});r.on('error',e=>{out.push(e.code);resolve();});});console.log(JSON.stringify(out));})().catch(()=>process.exit(1));`;
      const result = await child(["--use-openssl-ca", "-e", code], env);
      expect(result.code, result.stderr).toBe(0);
      const expected = name === "trusted" ? "local-only" : name === "untrusted" ? "DEPTH_ZERO_SELF_SIGNED_CERT" : "ERR_TLS_CERT_ALTNAME_INVALID";
      expect(JSON.parse(result.stdout)).toEqual([expected, expected]);
    } finally {
      for (const socket of sockets) socket.destroy();
      await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    }
  }
});
