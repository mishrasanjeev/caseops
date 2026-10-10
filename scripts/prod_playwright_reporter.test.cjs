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
    retries: 0, repeatEachIndex: 0,
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
  const originalOpen = fs.openSync;
  const originalAppend = fs.writeSync;
  const originalSync = fs.fsyncSync;
  const originalClose = fs.closeSync;
  const writes = [];
  const progress = [];
  let syncs = 0;
  let closes = 0;
  let writesToProgress = 0;
  let reporter;
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
      if (options.finalWriteFailure) throw new Error("Safe final output unavailable");
    };
    fs.openSync = (file, flags) => {
      assert.equal(file, path.join(directory, "progress.jsonl"));
      assert.equal(flags, "wx");
      if (options.existingProgress) throw new Error("EEXIST progress evidence retained");
      return 12007;
    };
    fs.writeSync = (fd, buffer, offset, length) => {
      assert.equal(fd, 12007);
      if (options.partialFailure && writesToProgress++ === 1) throw new Error("Injected partial write failure");
      if (options.invalidWrite !== undefined) return options.invalidWrite;
      const written = options.partialWrites ? Math.min(length, 13) : length;
      const content = buffer.toString("utf8");
      for (const privateValue of [sentinel, "PRIVATE-INLINE-AUTHSTATE", "private-legal-body", "toBeOK raw response"]) {
        assert.ok(!content.includes(privateValue), `Unsafe progress value at first write: ${privateValue}`);
      }
      progress.push(Buffer.from(buffer.subarray(offset, offset + written)));
      return written;
    };
    fs.fsyncSync = (fd) => {
      assert.equal(fd, 12007); syncs++;
      if (options.fsyncFailure) throw new Error("Injected fsync failure");
    };
    fs.closeSync = (fd) => { assert.equal(fd, 12007); closes++; };
    const data = fixture(options);
    if (options.mutate) options.mutate(data);
    reporter = new Reporter();
    const earlyError = { message: `Authorization: Bearer ${sentinel} private-legal-body`, location: testCaseLocation() };
    if (options.beforeConfigure) reporter.onError(earlyError);
    reporter.configure(data.config);
    if (options.beforeBegin) reporter.onError(earlyError);
    if (options.configureTwice) reporter.configure(data.config);
    if (!options.noBegin) reporter.onBegin(data.config, data.suite);
    if (options.nearLimit) reporter.progressBytes = 64 * 1024 * 1024;
    if (!options.noBegin && !options.discovery && !options.empty) reporter.onTestEnd(data.testCase, data.testCase.results[0]);
    if (options.globalError) reporter.onError({ message: `Authorization: Bearer ${sentinel} private-legal-body`,
      get stack() { return forbidden(); }, location: testCaseLocation() });
    if (!options.noEnd) await reporter.onEnd({ status: options.fullStatus ?? "passed", duration: 5 });
    if (options.exit) reporter.onExit();
    return { writes, json: writes[0] ? JSON.parse(writes[0].content) : undefined,
      xml: writes[1]?.content, progress: Buffer.concat(progress).toString("utf8").split("\n").filter(Boolean).map(JSON.parse), syncs, closes };
  } finally {
    reporter?.onExit();
    fs.writeFileSync = originalWrite;
    fs.openSync = originalOpen;
    fs.writeSync = originalAppend;
    fs.fsyncSync = originalSync;
    fs.closeSync = originalClose;
    for (const key of Object.keys(process.env)) if (!(key in prior)) delete process.env[key];
    Object.assign(process.env, prior);
  }
}

test("completed failed attempts and collection are flushed before hard interruption", async () => {
  const result = await capture({ outcome: "unexpected", noEnd: true, globalError: true });
  assert.deepEqual(result.progress.map((row) => row.event), ["invocation_started", "collection", "test_end", "global_error"]);
  assert.equal(result.progress[0].release_sha, sha);
  assert.equal(result.progress[0].invocation, "offline");
  const attempt = result.progress[2].suites[0].suites[0].specs[0];
  assert.equal(attempt.id, "canonical-native-id");
  assert.equal(attempt.tests[0].results[0].status, "failed");
  assert.equal(result.syncs, 4);
  assert.equal(result.writes.length, 0);
  assert.ok(!result.progress.some((row) => row.event === "session_finished"));
});

test("journal completion follows safe final reports and retains exact attempts", async () => {
  const { progress, syncs, closes, json } = await capture();
  assert.deepEqual(progress.map((row) => row.event), ["invocation_started", "collection", "test_end", "session_finished"]);
  assert.deepEqual(progress[2].suites, json.suites);
  assert.deepEqual(progress[3], { event: "session_finished", status: "passed", test_count: 1 });
  assert.equal(syncs, 4);
  assert.equal(closes, 1);
});

test("native discovery never opens an execution journal", async () => {
  const result = await capture({ discovery: true, outcome: "skipped" });
  assert.deepEqual(result.progress, []);
  assert.equal(result.syncs, 0);
});

test("existing progress evidence is rejected rather than overwritten", async () => {
  await assert.rejects(capture({ existingProgress: true }), /EEXIST/);
});

test("partial synchronous writes preserve complete UTF8 packets and flush once per event", async () => {
  const result = await capture({ partialWrites: true });
  assert.deepEqual(result.progress[2].suites, result.json.suites);
  assert.equal(result.syncs, 4);
  assert.equal(result.closes, 1);
});

test("zero, negative, noninteger and oversized progress writes fail before completion", async () => {
  for (const invalidWrite of [0, -1, 0.5, 64 * 1024 * 1024]) {
    await assert.rejects(capture({ invalidWrite }), /Incomplete safe progress write/);
  }
});

test("cumulative progress bound rejects later packets without final reports", async () => {
  await assert.rejects(capture({ nearLimit: true }), /oversized safe progress evidence/);
});

test("normal exit without completion closes the journal but cannot create a finish receipt", async () => {
  const result = await capture({ noEnd: true, exit: true });
  assert.equal(result.closes, 1);
  assert.equal(result.writes.length, 0);
  assert.ok(!result.progress.some((row) => row.event === "session_finished"));
});

test("failed final report write cannot produce a journal completion", async () => {
  await assert.rejects(capture({ finalWriteFailure: true }), /Safe final output unavailable/);
});

test("pre-collection errors are fsynced without inventing collection or completion", async () => {
  const result = await capture({ noBegin: true, noEnd: true, beforeBegin: true });
  assert.deepEqual(result.progress.map((row) => row.event), ["invocation_started", "global_error"]);
  assert.equal(result.syncs, 2);
  assert.equal(result.writes.length, 0);
});

test("errors delivered before collection flush exactly once under reviewed invocation binding", async () => {
  const result = await capture({ beforeConfigure: true, fullStatus: "failed" });
  assert.deepEqual(result.progress.map((row) => row.event),
    ["invocation_started", "global_error", "collection", "test_end", "session_finished"]);
  assert.equal(result.json.errors.length, 1);
});

test("fsync failure closes the journal and rejects all later appends inside the bound", () => {
  const reporter = Object.create(Reporter.prototype);
  const value = { event: "global_error", error: { message: "[redacted native error]" } };
  const bytes = Buffer.byteLength(JSON.stringify(value) + "\n", "utf8");
  const limit = 64 * 1024 * 1024;
  reporter.progressFd = 12007;
  reporter.progressBytes = limit - bytes;
  const original = { write: fs.writeSync, sync: fs.fsyncSync, close: fs.closeSync };
  let written = reporter.progressBytes;
  let closes = 0;
  try {
    fs.writeSync = (_, __, ___, length) => { written += length; return length; };
    fs.fsyncSync = () => { throw new Error("Injected fsync failure"); };
    fs.closeSync = (fd) => { assert.equal(fd, 12007); closes++; };
    assert.throws(() => reporter.appendProgress(value), /Injected fsync failure/);
    assert.equal(reporter.progressBytes, limit);
    assert.equal(reporter.progressFd, undefined);
    assert.throws(() => reporter.appendProgress(value), /Missing or oversized/);
    assert.equal(written, limit);
    assert.equal(closes, 1);
  } finally { fs.writeSync = original.write; fs.fsyncSync = original.sync; fs.closeSync = original.close; }
});

test("partial write failure cannot continue a damaged journal", async () => {
  await assert.rejects(capture({ partialWrites: true, partialFailure: true }), /Injected partial write failure/);
});

test("repeat configuration cannot overwrite the original invocation", async () => {
  await assert.rejects(capture({ configureTwice: true }), /already configured/);
});

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

test("canonical XML title path distinguishes display collisions and preserves UTF8 whitespace", async () => {
  const shapes = [
    ["offline.spec.ts", "Root title"],
    ["offline.spec.ts", "Outer", "Inner", "Nested title"],
    ["offline.spec.ts", "", "Whitespace\t\r\n \u00a7 \u0939\u093f\u0902\u0926\u0940"],
    ["offline.spec.ts", "Joined \u203a title", "Leaf"],
    ["offline.spec.ts", "Joined", "title \u203a Leaf"],
  ];
  for (const titles of shapes) {
    const { json, xml } = await capture({ mutate: ({ testCase }) => {
      testCase.title = titles.at(-1);
      testCase.titlePath = () => ["", "offline", ...titles];
    } });
    let node = json.suites[0];
    const retained = [node.title];
    while (node.suites) { node = node.suites[0]; retained.push(node.title); }
    retained.push(node.specs[0].title);
    assert.deepEqual(retained, titles);
    assert.equal(node.specs[0].tests[0].retries, 0);
    assert.equal(node.specs[0].tests[0].repeatEachIndex, 0);
    const escaped = JSON.stringify(titles).replaceAll("&", "&amp;").replaceAll('"', "&quot;");
    assert.ok(xml.includes(`caseops-title-path="${escaped}"`));
    assert.match(xml, /caseops-id="canonical-native-id"/);
    assert.match(xml, /file="tests\/e2e\/offline.spec.ts" line="11" column="3"/);
    assert.match(xml, /caseops-outcome="expected"/);
    if (titles.at(-1).includes("\n")) assert.match(xml, /&#9;&#13;&#10;/);
  }
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
