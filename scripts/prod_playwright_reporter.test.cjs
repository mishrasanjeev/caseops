"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const Reporter = require("./prod_playwright_reporter.cjs");
const root = path.resolve(__dirname, "..");
const sha = "99297e17b00dd51178e21baf596ba2ebfd92c5f7";
const sentinel = "PRIVATE-AUTH-LEGAL-SENTINEL";

function forbidden() { throw new Error("Unsafe native field was accessed"); }

function fixture(options = {}) {
  const project = { name: "offline", testDir: root, retries: 0, repeatEach: 1, timeout: 30000,
    get use() { return forbidden(); }, get metadata() { return forbidden(); } };
  const config = { configFile: path.join(root, "playwright.prod-ram.config.ts"),
    rootDir: root, workers: 1, projects: [project],
    get use() { return forbidden(); }, get metadata() { return forbidden(); } };
  const reason = options.reason ?? "Consent pending \u00a7 \u0939\u093f\u0902\u0926\u0940";
  const outcome = options.outcome ?? "expected";
  const runStatus = options.runStatus ?? (outcome === "skipped" ? "skipped" : outcome === "unexpected" ? "failed" : "passed");
  const testCase = { id: "canonical-native-id", title: "Native \u00a7 identity", timeout: 30000,
    location: { file: path.join(root, "tests/e2e/offline.spec.ts"), line: 11, column: 3 },
    expectedStatus: outcome === "skipped" ? "skipped" : "passed", tags: ["@proof"],
    parent: { project: () => project }, titlePath: () => ["", "offline", "offline.spec.ts", "Journey", "Native \u00a7 identity"],
    outcome: () => outcome, ok: () => outcome !== "unexpected",
    annotations: [{ type: "skip", description: reason }],
    results: options.discovery ? [] : [{ status: runStatus, retry: 0, duration: 2,
      workerIndex: 1, parallelIndex: 0, startTime: new Date("2026-10-10T00:00:00Z"),
      annotations: [{ type: "skip", description: reason }],
      errors: [{ get message() { return forbidden(); }, get stack() { return forbidden(); },
        location: testCaseLocation() }],
      get stdout() { return forbidden(); }, get stderr() { return forbidden(); },
      attachments: [{ name: "private-attachment", get body() { return forbidden(); }, get path() { return forbidden(); } }],
      get steps() { return forbidden(); } }],
  };
  return { config, testCase, suite: { allTests: () => options.empty ? [] : [testCase] } };
}

function testCaseLocation() {
  return { file: path.join(root, "tests/e2e/offline.spec.ts"), line: 11, column: 3 };
}

async function capture(options = {}) {
  const prior = { ...process.env };
  const originalWrite = fs.writeFileSync;
  const writes = [];
  const directory = path.join(root, "test-results/prod-native-evidence/offline");
  try {
    Object.assign(process.env, { CASEOPS_EXPECTED_RELEASE_SHA: sha,
      CASEOPS_PW_EVIDENCE_INVOCATION: "offline", CASEOPS_PW_EVIDENCE_PHASE: options.discovery ? "discovery" : "execution",
      CASEOPS_PW_EVIDENCE_JSON_FILE: path.join(directory, options.discovery ? "native-discovery.json" : "native-results.json"),
      CASEOPS_PW_EVIDENCE_JUNIT_FILE: path.join(directory, "native-results.xml"),
      CASEOPS_QA_PASSWORD: sentinel, CUSTOM_EDGE_SECRET: sentinel,
      // Inline auth/custom keys must never reach serialization, even if their
      // value does not match a conventional environment secret name.
      UNRECOGNIZED_KEY: "PRIVATE-INLINE-AUTHSTATE" });
    Object.assign(process.env, options.env);
    fs.writeFileSync = (file, content, writeOptions) => {
      // This executes BEFORE disk I/O, rather than scanning a sanitized copy.
      assert.equal(writeOptions.encoding, "utf8");
      assert.equal(writeOptions.flag, "wx");
      for (const privateValue of [sentinel, "PRIVATE-INLINE-AUTHSTATE", "private-legal-body", "toBeOK raw response"]) {
        assert.ok(!content.includes(privateValue), `Unsafe value at write boundary: ${privateValue}`);
      }
      writes.push({ file, content });
    };
    const data = fixture(options);
    if (options.mutate) options.mutate(data);
    const reporter = new Reporter();
    if (!options.noBegin) reporter.onBegin(data.config, data.suite);
    if (options.globalError) reporter.onError({ message: `Authorization: Bearer ${sentinel} private-legal-body`,
      get stack() { return forbidden(); }, location: testCaseLocation() });
    await reporter.onEnd({ status: options.fullStatus ?? "passed", duration: 5 });
    return { writes, json: JSON.parse(writes[0].content), xml: writes[1]?.content };
  } finally {
    fs.writeFileSync = originalWrite;
    for (const key of Object.keys(process.env)) if (!(key in prior)) delete process.env[key];
    Object.assign(process.env, prior);
  }
}

test("native identity, config/project binding and safe annotations survive before-write selection", async () => {
  const { json, xml, writes } = await capture();
  assert.equal(writes.length, 2);
  assert.equal(json.release_sha, sha);
  assert.equal(json.phase, "execution");
  assert.equal(json.config.projects[0].name, "offline");
  const spec = json.suites[0].suites[0].specs[0];
  assert.equal(spec.id, "canonical-native-id");
  assert.equal(spec.title, "Native \u00a7 identity");
  assert.equal(spec.tests[0].results[0].workerIndex, 1);
  assert.equal(spec.tests[0].results[0].errors.length, 1);
  assert.deepEqual(Object.keys(spec.tests[0].results[0]).sort(),
    ["annotations", "duration", "errors", "networkEvidence", "parallelIndex", "retry", "startTime", "status", "workerIndex"]);
  assert.match(xml, /Consent pending/);
  assert.deepEqual(Object.keys(json.config).sort(), ["configFile", "projects", "rootDir", "workers"]);
});

test("full long multiline UTF8 skip reason retained in both native reports without truncation", async () => {
  const reason = "Consent pending \u00a7 \u0939\u093f\u0902\u0926\u0940\n" + "Reviewed prerequisite remains missing. ".repeat(150);
  const { json, xml } = await capture({ reason, outcome: "skipped" });
  const native = json.suites[0].suites[0].specs[0].tests[0];
  assert.equal(native.annotations[0].description, reason);
  assert.equal(native.results[0].annotations[0].description, reason);
  assert.equal(json.stats.skipped, 1);
  assert.match(xml, /&#10;/);
  assert.ok(xml.includes(reason.replaceAll("\n", "&#10;")));
  assert.match(xml, /<skipped\/>/);
});

test("sensitive annotation fragments redacted before first write", async () => {
  const { json, xml } = await capture({ reason: `${sentinel} user@test.invalid https://example.invalid/?token=abc Bearer credential` });
  const reason = json.suites[0].suites[0].specs[0].tests[0].annotations[0].description;
  assert.match(reason, /redacted/);
  assert.ok(!reason.includes("user@test.invalid"));
  assert.ok(!xml.includes("?token="));
  const body = await capture({ reason: 'payload={"private":"private-legal-body"}' });
  assert.match(body.json.suites[0].suites[0].specs[0].tests[0].annotations[0].description, /sensitive annotation/);
});

test("legacy skip response bodies are redacted even when plain unstructured legal text", async () => {
  for (const reason of [`Upload failed (403): private-legal-body; cannot seed BUG-028 fixture.`,
    "Could not create probe matter: 409 private-legal-body"]) {
    const { json } = await capture({ outcome: "skipped", reason });
    const retained = json.suites[0].suites[0].specs[0].tests[0].annotations[0].description;
    assert.match(retained, /response body redacted/);
    assert.match(retained, /403|409/);
  }
});

test("actual unrecognized inline auth/config data, errors, stdout and attachments are never serialized", async () => {
  const { json, xml } = await capture({ mutate: ({ config, testCase }) => {
    Object.defineProperty(config, "use", { value: { storageState: { cookies: [{ value: "PRIVATE-INLINE-AUTHSTATE" }] },
      extraHTTPHeaders: { "X-Custom-Edge": "PRIVATE-INLINE-AUTHSTATE" } } });
    Object.assign(testCase.results[0], { errors: [{ message: `toBeOK raw response Authorization: Bearer ${sentinel}`,
      stack: "private-legal-body", value: "PRIVATE-INLINE-AUTHSTATE" }] });
    Object.defineProperties(testCase.results[0], {
      stdout: { value: ["private-legal-body"] }, stderr: { value: [sentinel] },
      attachments: { value: [{ name: "generic-private", path: "private-legal-body", body: Buffer.from(sentinel) }] } });
  } });
  assert.equal(json.suites[0].suites[0].specs[0].tests[0].results[0].errors.length, 1);
  assert.ok(!xml.includes("storageState"));
});

test("native failure/global-error outcomes remain failures despite redacted detail", async () => {
  const { json, xml } = await capture({ outcome: "unexpected", fullStatus: "failed", globalError: true });
  assert.equal(json.status, "failed");
  assert.equal(json.stats.unexpected, 1);
  assert.equal(json.errors.length, 1);
  assert.equal(json.errors[0].location.file, "tests/e2e/offline.spec.ts");
  assert.match(xml, /<failure/);
});

test("interrupted native full result and attempt status remain explicit", async () => {
  const { json } = await capture({ fullStatus: "interrupted", runStatus: "interrupted", outcome: "unexpected" });
  assert.equal(json.status, "interrupted");
  assert.equal(json.suites[0].suites[0].specs[0].tests[0].results[0].status, "interrupted");
});

test("native discovery retains all identities without execution or XML", async () => {
  const { json, writes } = await capture({ discovery: true, outcome: "skipped" });
  assert.equal(writes.length, 1);
  assert.equal(json.stats.skipped, 1);
  assert.equal(json.suites[0].suites[0].specs[0].tests[0].results.length, 0);
});

test("native unnamed default project identity is preserved for the production cost config", async () => {
  const { json } = await capture({ discovery: true, outcome: "skipped", mutate: ({ config }) => {
    config.projects[0].name = "";
  } });
  assert.equal(json.config.projects[0].id, "");
  assert.equal(json.suites[0].suites[0].specs[0].tests[0].projectId, "");
});

test("empty native inventory is retained as empty, never fabricated", async () => {
  const { json } = await capture({ empty: true });
  assert.deepEqual(json.suites, []);
  assert.equal(json.stats.expected, 0);
});

test("bad binding, unsafe destination, missing collection and duplicate projects fail closed", async () => {
  await assert.rejects(capture({ env: { CASEOPS_EXPECTED_RELEASE_SHA: "short" } }), /binding/);
  await assert.rejects(capture({ env: { CASEOPS_PW_EVIDENCE_JSON_FILE: "/unreviewed.json" } }), /destination/);
  await assert.rejects(capture({ noBegin: true }), /collection/);
  await assert.rejects(capture({ mutate: ({ config }) => config.projects.push(config.projects[0]) }), /project identity/);
});

test("private/attachment error locations outside code sources are omitted", async () => {
  const { json } = await capture({ mutate: ({ testCase }) => {
    testCase.results[0].errors[0].location = { file: path.join(root, "private/attachment.pdf"), line: 1, column: 1 };
  } });
  assert.deepEqual(json.suites[0].suites[0].specs[0].tests[0].results[0].errors[0],
    { message: "[redacted native test error; outcome retained]" });
});

function snapshot() {
  const base = { route: "matter/attachment", method: "POST", startedAt: "2026-10-10T00:00:00.000Z" };
  return { schemaVersion: 1, drainTimedOut: false, omitted: 2, records: [
    { ...base, finishedAt: "2026-10-10T00:00:00.100Z", outcome: "response_completed", status: 503,
      requestId: "01234567-89ab-cdef-0123-456789abcdef", problemType: "database_lock_timeout" },
    { ...base, finishedAt: "2026-10-10T00:00:00.200Z", outcome: "transport_failed", failureCode: "net::ERR_TIMED_OUT" },
    { ...base, finishedAt: null, outcome: "pending_at_test_end" },
    { ...base, finishedAt: "2026-10-10T00:00:00.300Z", outcome: "response_unavailable" },
    { ...base, finishedAt: "2026-10-10T00:00:00.400Z", outcome: "diagnostic_unavailable" },
  ] };
}

function attach(data, extra = {}) {
  return { name: "sanitized-network-evidence", contentType: "application/json",
    body: Buffer.from(JSON.stringify(data)), ...extra };
}

async function diagnostic(attachment) {
  const { json, xml } = await capture({ outcome: "unexpected", fullStatus: "failed", mutate: ({ testCase }) => {
    testCase.results[0].attachments = Array.isArray(attachment) ? attachment : [attachment];
  } });
  return { evidence: json.suites[0].suites[0].specs[0].tests[0].results[0].networkEvidence, json, xml };
}

test("reviewed failure-only network snapshot retains exact safe correlators, completion and transport", async () => {
  const data = snapshot();
  const { evidence, json, xml } = await diagnostic(attach(data));
  assert.equal(evidence.status, "retained");
  assert.equal(evidence.name, "sanitized-network-evidence");
  assert.equal(evidence.contentType, "application/json");
  assert.deepEqual(evidence.snapshot, data);
  assert.equal(json.stats.unexpected, 1);
  assert.match(xml, /name="sanitized-network-evidence" value="retained"/);
});

test("same-name malicious extra keys or private enum/correlator values rejected before any write", async () => {
  const bad = [];
  const extra = snapshot(); extra.rawBody = sentinel; bad.push(extra);
  for (const [key, value] of [["rawBody", sentinel], ["route", `https://example.invalid/?token=${sentinel}`],
    ["method", sentinel], ["problemType", "private-legal-body"], ["requestId", sentinel],
    ["status", "private-legal-body"], ["finishedAt", sentinel], ["outcome", sentinel]]) {
    const data = snapshot(); data.records[0][key] = value; bad.push(data);
  }
  const transport = snapshot(); transport.records[1].failureCode = sentinel; bad.push(transport);
  for (const data of bad) {
    const { evidence } = await diagnostic(attach(data));
    assert.equal(evidence.status, "rejected");
    assert.equal(evidence.snapshot, undefined);
  }
});

test("paths, wrong types, duplicate names, malformed UTF8/JSON and oversized bodies rejected without file reads", async () => {
  const originalRead = fs.readFileSync;
  try {
    fs.readFileSync = forbidden;
    for (const attachment of [attach(snapshot(), { path: path.join(root, "private/attachment.json") }),
      attach(snapshot(), { path: "../../private-legal-body" }), attach(snapshot(), { contentType: "text/plain" }),
      attach(snapshot(), { body: Buffer.alloc(65537, "x") }), attach(snapshot(), { body: Buffer.from([0xff]) }),
      attach(snapshot(), { body: Buffer.from("private-legal-body") }),
      [attach(snapshot()), attach(snapshot())]]) {
      const { evidence } = await diagnostic(attachment);
      assert.equal(evidence.status, "rejected");
    }
  } finally { fs.readFileSync = originalRead; }
});

test("network snapshot bounds, exact schema and drains remain strict at 64 records", async () => {
  const data = snapshot(); data.records = Array.from({ length: 64 }, () => data.records[0]);
  data.drainTimedOut = true;
  assert.equal((await diagnostic(attach(data))).evidence.snapshot.records.length, 64);
  data.records.push(data.records[0]);
  assert.equal((await diagnostic(attach(data))).evidence.status, "rejected");
  for (const [key, value] of [["schemaVersion", 2], ["drainTimedOut", "private-legal-body"], ["omitted", -1], ["records", {}]]) {
    const invalid = snapshot(); invalid[key] = value;
    assert.equal((await diagnostic(attach(invalid))).evidence.status, "rejected");
  }
});

test("reporter diagnostic allowlists remain identical to the unchanged production diagnostic helper", () => {
  const helper = fs.readFileSync(path.join(root, "tests/e2e/support/prod-failure-diagnostics.ts"), "utf8");
  const reporter = fs.readFileSync(path.join(root, "scripts/prod_playwright_reporter.cjs"), "utf8");
  const strings = (block) => [...block.matchAll(/"([\w:/-]+)"/g)].map((match) => match[1]).sort();
  const set = (source, name) => strings(source.match(new RegExp(`const ${name} = new Set\\(\\[([\\s\\S]*?)\\]\\)`))[1]);
  const helperRoutes = strings(helper.slice(helper.indexOf("const routes:"), helper.indexOf("const problemTypes")));
  assert.deepEqual(set(reporter, "routes"), helperRoutes);
  assert.deepEqual(set(reporter, "problems"), set(helper, "problemTypes"));
  assert.deepEqual(set(reporter, "transports"), [...set(helper, "transportCodes"), "unclassified_transport_failure"].sort());
});
