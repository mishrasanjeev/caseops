"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
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

// Independent synthetic expectation, not imported from the serializer under test.
const reportedDraftType = "caseops-b5-reported-draft";
const reportedDraftProof = {
  schema_version: 1,
  status: "READ_ONLY_PARITY_VERIFIED",
  matter_id: "7771c86f-a6d6-442f-a675-4be40622dc05",
  draft_id: "3e81e0ec-e193-4be1-9f3f-b5fee1dcb4f5",
  version_id: "cc114a40-7bb5-422d-9499-988b69c0f4d4",
  body_sha256: "71cf6b959c63e107c46d84b93e736ed8f98418e95fbbf892dd6614490bf1f074",
  unchanged: true,
  attempted_mutations: 0,
};

async function draftReceipt(description, type, extra = {}) {
  if (arguments.length < 2) type = reportedDraftType;
  return capture({ mutate: ({ testCase }) => {
    const annotation = { type, description };
    Object.defineProperties(annotation, Object.getOwnPropertyDescriptors(extra));
    testCase.annotations = [annotation];
    testCase.results[0].annotations = [annotation];
    testCase.results[0].attachments.push({ name: "bug001-production-parity",
      get body() { return forbidden(); }, get path() { return forbidden(); } });
  } });
}

function assertDraftReceipt(result, expected) {
  const native = result.json.suites[0].suites[0].specs[0].tests[0];
  assert.equal(native.annotations[0].description, expected);
  assert.equal(native.results[0].annotations[0].description, expected);
  for (const row of result.progress.filter((row) => row.suites)) {
    const test = row.suites[0].suites[0].specs[0].tests[0];
    assert.equal(test.annotations[0].description, expected);
    for (const run of test.results) assert.equal(run.annotations[0].description, expected);
  }
  assert.ok(result.xml.includes(`name="${reportedDraftType}" value="${expected.replaceAll('"', "&quot;")}"`));
  assert.equal(native.results[0].networkEvidence.status, "absent");
}

test("only the exact reviewed draft receipt survives native JSON XML and durable progress", async () => {
  const canonical = JSON.stringify(reportedDraftProof);
  const reversed = JSON.stringify(Object.fromEntries(Object.entries(reportedDraftProof).reverse()), null, 2);
  for (const description of [canonical, reversed, canonical.padEnd(1024)]) {
    const result = await draftReceipt(description, reportedDraftType, {
      get body() { return forbidden(); }, get attachment() { return forbidden(); },
    });
    assertDraftReceipt(result, canonical);
    assert.deepEqual(Object.keys(result.json.suites[0].suites[0].specs[0].tests[0].annotations[0]),
      ["type", "description"]);
  }
});

test("reviewed draft schema refuses every field's wrong scalar or structured type", async () => {
  for (const key of Object.keys(reportedDraftProof)) {
    for (const value of [null, false, true, 0, 1, "1", "0", "true", [], {}, [sentinel]]) {
      if (value === reportedDraftProof[key]) continue;
      assertDraftReceipt(await draftReceipt(JSON.stringify({ ...reportedDraftProof, [key]: value })),
        "[redacted invalid reported draft receipt]");
    }
  }
});

test("missing extra private and changed draft proof fields never reach the first write", async () => {
  for (const key of Object.keys(reportedDraftProof)) {
    const missing = { ...reportedDraftProof }; delete missing[key];
    assertDraftReceipt(await draftReceipt(JSON.stringify(missing)), "[redacted invalid reported draft receipt]");
  }
  for (const key of ["body", "source_fingerprint", "payload", "token", "attachments", "__proto__"]) {
    const description = JSON.stringify({ ...reportedDraftProof, [key]: `private-legal-body ${sentinel}` });
    assertDraftReceipt(await draftReceipt(description), "[redacted invalid reported draft receipt]");
  }
  for (const [key, value] of [
    ["status", "PASSED"], ["matter_id", "00000000-0000-0000-0000-000000000000"],
    ["draft_id", reportedDraftProof.version_id], ["version_id", reportedDraftProof.draft_id],
    ["body_sha256", "7e83f20a36d662d4b6748542ebf2460daf141f86b9dc3a006baede20d0848504"],
    ["attempted_mutations", -1], ["schema_version", 2],
    ["body_sha256", reportedDraftProof.body_sha256.toUpperCase()],
  ]) {
    assertDraftReceipt(await draftReceipt(JSON.stringify({ ...reportedDraftProof, [key]: value })),
      "[redacted invalid reported draft receipt]");
  }
});

test("duplicate plain or escaped draft keys reject even when JSON.parse would erase private values", async () => {
  const canonical = JSON.stringify(reportedDraftProof);
  for (const [key, value] of Object.entries(reportedDraftProof)) {
    const escapedKey = `\\u${key.charCodeAt(0).toString(16).padStart(4, "0")}${key.slice(1)}`;
    for (const spelling of [key, escapedKey]) {
      for (const duplicate of [JSON.stringify(value), JSON.stringify(`private-legal-body ${sentinel}`)]) {
        const description = `{"${spelling}":${duplicate},${canonical.slice(1)}`;
        assertDraftReceipt(await draftReceipt(description), "[redacted invalid reported draft receipt]");
      }
    }
  }
});

test("draft receipt rejects malformed nonstring oversized and floating point descriptions", async () => {
  const canonical = JSON.stringify(reportedDraftProof);
  const opaque = { get toJSON() { return forbidden(); }, toString: forbidden };
  for (const description of [undefined, null, 1, true, opaque, Buffer.from(canonical),
    canonical.padEnd(1025), `${canonical}${canonical}`, `${canonical} private-legal-body`,
    canonical.slice(0, -1), "null", "[]", JSON.stringify(canonical),
    canonical.replace('"schema_version":1', '"schema_version":1.0'),
    canonical.replace('"schema_version":1', '"schema_version":1e0'),
    canonical.replace('"attempted_mutations":0', '"attempted_mutations":0.0'),
    canonical.replace('"attempted_mutations":0', '"attempted_mutations":0e1'),
    canonical.replace('"attempted_mutations":0', '"attempted_mutations":-0'),
    canonical.replace('"matter_id"', '"\\u006datter_id"'),
    canonical.replace("READ_ONLY", "\\u0052EAD_ONLY"),
  ]) {
    const result = await draftReceipt(description);
    if (description === undefined) {
      assert.equal(result.json.suites[0].suites[0].specs[0].tests[0].annotations[0].description, undefined);
    } else assertDraftReceipt(result, "[redacted invalid reported draft receipt]");
  }
});

test("draft allowlist does not enable generic structured annotations or attachment payloads", async () => {
  for (const type of ["caseops-b5-proof", "caseops-b5-reported-draft-extra", "CASEOPS-B5-REPORTED-DRAFT",
    "caseops-b5-reported-draft ", "", undefined, null, 1]) {
    const { json, xml, progress } = await draftReceipt(JSON.stringify(reportedDraftProof), type);
    const native = json.suites[0].suites[0].specs[0].tests[0];
    assert.equal(native.annotations[0].description, "[redacted structured or sensitive annotation]");
    for (const content of [JSON.stringify(json), xml, JSON.stringify(progress)]) {
      assert.ok(!content.includes(reportedDraftProof.matter_id));
      assert.ok(!content.includes(reportedDraftProof.body_sha256));
    }
  }
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

test("failure snapshots retain safe correlators, API-first duplicates and bounded page overflow", async () => {
  const data = snapshot();
  const { evidence, json, xml } = await diagnostic(attach(data));
  assert.equal(evidence.status, "retained");
  assert.equal(evidence.name, "sanitized-network-evidence");
  assert.equal(evidence.contentType, "application/json");
  assert.deepEqual(evidence.snapshot, data);
  assert.equal(json.stats.unexpected, 1);
  assert.match(xml, /name="sanitized-network-evidence" value="retained"/);
  const api = applicationSnapshot();
  const page = snapshot();
  const combined = await diagnostic([attach(api), attach(page)]);
  assert.equal(combined.evidence.status, "retained");
  assert.deepEqual(combined.evidence.snapshot.records, [...api.records, ...page.records]);
  assert.equal(combined.evidence.snapshot.omitted, 2);
  assert.equal(combined.json.stats.unexpected, 1);
  assert.match(combined.xml, /name="sanitized-network-evidence" value="retained"/);
  page.records = Array.from({ length: 64 }, () => page.records[0]);
  page.drainTimedOut = true;
  const full = (await diagnostic([attach(api), attach(page)])).evidence;
  assert.equal(full.status, "retained");
  assert.equal(full.snapshot.records.length, 64);
  assert.deepEqual(full.snapshot.records[0], api.records[0]);
  assert.equal(full.snapshot.omitted, 3);
  assert.equal(full.snapshot.drainTimedOut, true);
});

function applicationSnapshot() {
  const data = snapshot();
  data.omitted = 0;
  data.records = [{ ...data.records[0], route: "ip/application" }];
  return data;
}

test("Calendar and tracker read evidence survives reporter sanitization", async () => {
  for (const route of ["calendar/events", "ip/renewal-tracker"]) {
    const data = snapshot();
    data.records = [{ ...data.records[0], route, method: "GET" }];
    const { evidence } = await diagnostic(attach(data));
    assert.equal(evidence.status, "retained");
    assert.deepEqual(evidence.snapshot, data);
  }
  const data = snapshot();
  data.records[0].route = "calendar/events?private=secret";
  assert.equal((await diagnostic(attach(data))).evidence.status, "rejected");
});

test("portfolio export categories survive sanitization without source identities", async () => {
  for (const route of ["ip/portfolio-export-preview", "ip/portfolio-export", "ip/portfolio-export-status",
    "ip/portfolio-export-download", "ip/portfolio-export-retry"]) {
    const data = snapshot();
    data.records = [{ ...data.records[0], route }];
    const { evidence } = await diagnostic(attach(data));
    assert.equal(evidence.status, "retained");
    assert.deepEqual(evidence.snapshot, data);
    data.records[0].route = `${route}/PRIVATE-JOB?token=${sentinel}`;
    assert.equal((await diagnostic(attach(data))).evidence.status, "rejected");
  }
});

test("IP list and workspace categories retain reads without private identities", async () => {
  for (const route of ["ip/madrid-list", "ip/madrid-workspace", "ip/foreign-associate-list",
    "ip/foreign-associate-workspace", "ip/recordal-list", "ip/recordal-workspace"]) {
    const data = snapshot();
    data.records = [{ ...data.records[0], route, method: "GET" }];
    const { evidence } = await diagnostic(attach(data));
    assert.equal(evidence.status, "retained");
    assert.deepEqual(evidence.snapshot, data);
    data.records[0].route = `${route}/PRIVATE-RECORD?query=${sentinel}`;
    assert.equal((await diagnostic(attach(data))).evidence.status, "rejected");
  }
});

test("Team categories retain status and timing while rejecting private path additions", async () => {
  for (const [route, method, status] of [["team/list", "POST", 201], ["team/record", "DELETE", 204],
    ["team/members", "POST", 200], ["team/member-lead", "PATCH", 409]]) {
    const data = snapshot();
    data.records = [{ ...data.records[0], route, method, status }];
    const { evidence } = await diagnostic(attach(data));
    assert.equal(evidence.status, "retained");
    assert.deepEqual(evidence.snapshot, data);
    data.records[0].route = `${route}/PRIVATE-TEAM?expected_team_membership_id=${sentinel}`;
    assert.equal((await diagnostic(attach(data))).evidence.status, "rejected");
  }
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
  const trailingId = snapshot(); trailingId.records[0].requestId += "\n"; bad.push(trailingId);
  for (const data of bad) {
    const { evidence } = await diagnostic(attach(data));
    assert.equal(evidence.status, "rejected");
    assert.equal(evidence.snapshot, undefined);
  }
});

test("paths, wrong types, malformed UTF8/JSON and oversized bodies rejected without file reads", async () => {
  const originalRead = fs.readFileSync;
  try {
    fs.readFileSync = forbidden;
    for (const attachment of [attach(snapshot(), { path: path.join(root, "private/attachment.json") }),
      attach(snapshot(), { path: "../../private-legal-body" }), attach(snapshot(), { contentType: "text/plain" }),
      attach(snapshot(), { body: Buffer.alloc(65537, "x") }), attach(snapshot(), { body: Buffer.from([0xff]) }),
      attach(snapshot(), { body: Buffer.from("private-legal-body") }),
      [attach(applicationSnapshot()), attach(snapshot(), { body: Buffer.from("private-legal-body") })]]) {
      const { evidence } = await diagnostic(attachment);
      assert.equal(evidence.status, "rejected");
    }
  } finally { fs.readFileSync = originalRead; }
});

async function duplicateBounds() {
  const api = applicationSnapshot();
  const safeDuplicate = await diagnostic([attach(api), attach(api)]);
  assert.equal(safeDuplicate.evidence.status, "retained");
  assert.deepEqual(safeDuplicate.evidence.snapshot.records, [...api.records, ...api.records]);
  const oversized = Buffer.from(JSON.stringify(api).padEnd(32_769));
  assert.equal((await diagnostic([attach(api, { body: oversized }), attach(api, { body: oversized })])).evidence.reason, "body_bound");
  const invalid = snapshot(); invalid.rawBody = sentinel;
  assert.equal((await diagnostic([attach(api), attach(invalid)])).evidence.status, "rejected");
  const overflow = snapshot(); overflow.omitted = Number.MAX_SAFE_INTEGER;
  assert.equal((await diagnostic([attach(snapshot()), attach(overflow)])).evidence.reason, "snapshot_schema");
}

test("network snapshot bounds, exact schema and drains remain strict at 64 records", async () => {
  await duplicateBounds();
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

test("real offline Playwright runtime draft annotation survives the actual Python reader", () => {
  const invocation = `draft-receipt-${process.pid}-${require("node:crypto").randomBytes(4).toString("hex")}`;
  const directory = path.join(root, "test-results/prod-native-evidence", invocation);
  const fixtureDirectory = path.join(root, ".tmp", invocation);
  fs.mkdirSync(directory, { recursive: true });
  fs.mkdirSync(fixtureDirectory, { recursive: true });
  fs.writeFileSync(path.join(fixtureDirectory, "probe.spec.ts"), `
import { test } from "@playwright/test";
test("synthetic read-only draft receipt", async ({}, testInfo) => {
  testInfo.annotations.push({ type: ${JSON.stringify(reportedDraftType)},
    description: JSON.stringify(${JSON.stringify(reportedDraftProof)}) });
  await testInfo.attach("bug001-production-parity", { contentType: "application/json",
    body: Buffer.from(${JSON.stringify(`private-legal-body ${sentinel}`)}) });
});
`, { flag: "wx" });
  const configFile = path.join(fixtureDirectory, "playwright.config.cjs");
  fs.writeFileSync(configFile, `module.exports = { testDir: __dirname, testMatch: "probe.spec.ts", timeout: 30000,
    outputDir: ${JSON.stringify(path.join(fixtureDirectory, "output"))},
    workers: 1, retries: 0, reporter: [[${JSON.stringify(path.join(root, "scripts/prod_playwright_reporter.cjs"))}]],
    use: { trace: "off", screenshot: "off", video: "off" }, projects: [{ name: "offline" }] };`, { flag: "wx" });
  const env = Object.fromEntries(Object.entries(process.env)
    .filter(([key]) => /^(?:PATH|PATHEXT|SYSTEMROOT|WINDIR|TEMP|TMP|TMPDIR|HOME|USERPROFILE)$/i.test(key)));
  Object.assign(env, { CASEOPS_EXPECTED_RELEASE_SHA: sha, CASEOPS_PW_EVIDENCE_INVOCATION: invocation,
    CASEOPS_PW_EVIDENCE_PHASE: "execution", CASEOPS_PW_EVIDENCE_JSON_FILE: path.join(directory, "native-results.json"),
    CASEOPS_PW_EVIDENCE_JUNIT_FILE: path.join(directory, "native-results.xml") });
  const playwrightCli = process.env.CASEOPS_TEST_PLAYWRIGHT_CLI ?? path.join(root, "node_modules/@playwright/test/cli.js");
  assert.ok(path.isAbsolute(playwrightCli) && fs.statSync(playwrightCli).isFile(), "Installed Playwright CLI is required");
  const installed = JSON.parse(fs.readFileSync(path.join(path.dirname(playwrightCli), "package.json"), "utf8"));
  const locked = JSON.parse(fs.readFileSync(path.join(root, "package-lock.json"), "utf8"));
  assert.equal(installed.version, locked.packages["node_modules/@playwright/test"].version);
  env.NODE_PATH = path.resolve(path.dirname(playwrightCli), "../..");
  const child = spawnSync(process.execPath, [playwrightCli, "test", `--config=${configFile}`,
    "--workers=1", "--retries=0"], { cwd: root, env, encoding: "utf8", timeout: 60000 });
  fs.writeFileSync(path.join(fixtureDirectory, "child.stdout.log"), child.stdout ?? "", { flag: "wx" });
  fs.writeFileSync(path.join(fixtureDirectory, "child.stderr.log"), child.stderr ?? "", { flag: "wx" });
  assert.ifError(child.error);
  assert.equal(child.status, 0, child.stdout + child.stderr);
  const text = fs.readFileSync(path.join(directory, "native-results.json"), "utf8");
  const native = JSON.parse(text);
  const journal = fs.readFileSync(path.join(directory, "progress.jsonl"), "utf8").trim().split("\n").map(JSON.parse);
  const xml = fs.readFileSync(path.join(directory, "native-results.xml"), "utf8");
  assert.deepEqual(native.stats, { ...native.stats, expected: 1, skipped: 0, unexpected: 0, flaky: 0 });
  assert.equal(native.status, "passed");
  assert.equal(native.errors.length, 0);
  assert.equal(native.suites.length, 1);
  const nativeTest = native.suites[0].specs[0].tests[0];
  const expected = { type: reportedDraftType, description: JSON.stringify(reportedDraftProof) };
  // Playwright must promote runtime annotations onto TestCase for JUnit parity.
  assert.deepEqual(nativeTest.annotations, [expected]);
  assert.equal(nativeTest.results.length, 1);
  assert.equal(nativeTest.results[0].retry, 0);
  assert.equal(nativeTest.results[0].status, "passed");
  assert.equal(nativeTest.results[0].networkEvidence.status, "absent");
  assert.deepEqual(journal.map((row) => row.event), ["invocation_started", "collection", "test_end", "session_finished"]);
  assert.deepEqual(journal[2].suites, native.suites);
  assert.deepEqual(journal[1].suites[0].specs[0].tests[0].annotations, []);
  assert.deepEqual(journal.at(-1), { event: "session_finished", status: "passed", test_count: 1 });
  const script = `import importlib.util, json, pathlib, sys
root, directory = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("receipt_reader", root / "scripts/prod_playwright_evidence.py")
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)
raw = json.loads((directory / "native-results.json").read_text(encoding="utf-8"))
env = {"CASEOPS_EXPECTED_RELEASE_SHA": sys.argv[3]}
rows = reader._inventory(raw, env)
assert len(rows) == 1 and len(rows[0]["results"]) == 1
assert rows[0]["results"][0]["status"] == "passed"
assert len(rows[0]["annotations"]) == 1
assert json.loads(rows[0]["annotations"][0]["description"]) == json.loads(sys.argv[4])
reader._app_native_fields(raw)
reader._junit(directory / "native-results.xml", directory / "results.xml", env,
              {"tests": rows, "stats": raw["stats"]})
print("synthetic real-Playwright-to-Python receipt: 1 passed, 0 skipped, 0 retries")
`;
  const python = process.env.CASEOPS_TEST_PYTHON ?? (process.platform === "win32" ? "python" : "python3");
  const bridge = spawnSync(python, ["-X", "utf8", "-B", "-c", script, root, directory, sha,
    JSON.stringify(reportedDraftProof)], { cwd: root, env, encoding: "utf8", timeout: 15000 });
  fs.writeFileSync(path.join(fixtureDirectory, "python.stdout.log"), bridge.stdout ?? "", { flag: "wx" });
  fs.writeFileSync(path.join(fixtureDirectory, "python.stderr.log"), bridge.stderr ?? "", { flag: "wx" });
  assert.ifError(bridge.error);
  assert.equal(bridge.status, 0, bridge.stdout + bridge.stderr);
  for (const content of [text, xml, JSON.stringify(journal),
    fs.readFileSync(path.join(directory, "results.xml"), "utf8")]) {
    assert.ok(!content.includes(sentinel) && !content.includes("private-legal-body"));
  }
});

test("reporter allowlists agree with the helper and real offline Playwright retains API-first failures", () => {
  const helper = fs.readFileSync(path.join(root, "tests/e2e/support/prod-failure-diagnostics.ts"), "utf8");
  const reporter = fs.readFileSync(path.join(root, "scripts/prod_playwright_reporter.cjs"), "utf8");
  const strings = (block) => [...block.matchAll(/"([\w:/-]+)"/g)].map((match) => match[1]).sort();
  const set = (source, name) => strings(source.match(new RegExp(`const ${name} = new Set\\(\\[([\\s\\S]*?)\\]\\)`))[1]);
  const helperRoutes = strings(helper.slice(helper.indexOf("const routes:"), helper.indexOf("const problemTypes")));
  assert.deepEqual(set(reporter, "routes"), helperRoutes);
  assert.deepEqual(set(reporter, "problems"), set(helper, "problemTypes"));
  assert.deepEqual(set(reporter, "transports"), [...set(helper, "transportCodes"), "unclassified_transport_failure"].sort());
  const invocation = `api-response-${process.pid}-${require("node:crypto").randomBytes(4).toString("hex")}`;
  const directory = path.join(root, "test-results/prod-native-evidence", invocation);
  const fixtureDirectory = path.join(root, ".tmp", invocation);
  fs.mkdirSync(directory, { recursive: true });
  fs.mkdirSync(fixtureDirectory, { recursive: true });
  const page = snapshot();
  page.records = Array.from({ length: 64 }, () => page.records[0]);
  fs.writeFileSync(path.join(fixtureDirectory, "probe.spec.ts"), `
import { test } from "@playwright/test";
import { createPatentApplicationWithEvidence } from ${JSON.stringify(path.join(root, "tests/e2e/support/prod-api-response-evidence"))};
for (const status of [503, 200]) {
  test("offline API-first response " + status, async ({}, testInfo) => {
    let bodyReads = 0;
    const forbiddenBody = async () => { bodyReads++; throw new Error(${JSON.stringify(sentinel)}); };
    const api = { post: async () => ({ status: () => status,
      headers: () => status === 503 ? { "content-type": "application/problem+json", "content-length": "1",
        "content-encoding": "gzip", "x-request-id": "01234567-89ab-cdef-0123-456789abcdef" } : {},
      body: forbiddenBody, text: forbiddenBody, json: forbiddenBody }) };
    try {
      await createPatentApplicationWithEvidence(api as any, testInfo, "https://api.example.invalid", { data: {} });
    } catch (error) {
      if (bodyReads !== 0) throw new Error("Diagnostic accessed a decoded response body");
      await testInfo.attach("sanitized-network-evidence", { contentType: "application/json", body: Buffer.from(JSON.stringify(${JSON.stringify(page)})) });
      throw error;
    }
  });
}
`, { flag: "wx" });
  const configFile = path.join(fixtureDirectory, "playwright.config.cjs");
  fs.writeFileSync(configFile, `module.exports = { testDir: __dirname, testMatch: "probe.spec.ts", timeout: 30000,
    outputDir: ${JSON.stringify(path.join(fixtureDirectory, "output"))},
    workers: 1, retries: 0, reporter: [[${JSON.stringify(path.join(root, "scripts/prod_playwright_reporter.cjs"))}]],
    use: { trace: "off", screenshot: "off", video: "off" }, projects: [{ name: "offline" }] };`, { flag: "wx" });
  const env = Object.fromEntries(Object.entries(process.env)
    .filter(([key]) => /^(?:PATH|PATHEXT|SYSTEMROOT|WINDIR|TEMP|TMP|TMPDIR|HOME|USERPROFILE)$/i.test(key)));
  Object.assign(env, { CASEOPS_EXPECTED_RELEASE_SHA: sha, CASEOPS_PW_EVIDENCE_INVOCATION: invocation,
    CASEOPS_PW_EVIDENCE_PHASE: "execution", CASEOPS_PW_EVIDENCE_JSON_FILE: path.join(directory, "native-results.json"),
    CASEOPS_PW_EVIDENCE_JUNIT_FILE: path.join(directory, "native-results.xml") });
  const playwrightCli = process.env.CASEOPS_TEST_PLAYWRIGHT_CLI ?? path.join(root, "node_modules/@playwright/test/cli.js");
  assert.ok(path.isAbsolute(playwrightCli) && fs.statSync(playwrightCli).isFile(), "Installed Playwright CLI is required");
  const installed = JSON.parse(fs.readFileSync(path.join(path.dirname(playwrightCli), "package.json"), "utf8"));
  const locked = JSON.parse(fs.readFileSync(path.join(root, "package-lock.json"), "utf8"));
  assert.equal(installed.version, locked.packages["node_modules/@playwright/test"].version);
  env.NODE_PATH = path.resolve(path.dirname(playwrightCli), "../..");
  const result = spawnSync(process.execPath, [playwrightCli,
    "test", `--config=${configFile}`, "--workers=1", "--retries=0"], { cwd: root, env, encoding: "utf8", timeout: 60000 });
  fs.writeFileSync(path.join(fixtureDirectory, "child.stdout.log"), result.stdout ?? "", { flag: "wx" });
  fs.writeFileSync(path.join(fixtureDirectory, "child.stderr.log"), result.stderr ?? "", { flag: "wx" });
  assert.ifError(result.error);
  assert.equal(result.status, 1, result.stdout + result.stderr);
  const text = fs.readFileSync(path.join(directory, "native-results.json"), "utf8");
  const native = JSON.parse(text);
  const journal = fs.readFileSync(path.join(directory, "progress.jsonl"), "utf8").trim().split("\n").map(JSON.parse);
  assert.equal(native.stats.unexpected, 2);
  assert.equal(native.errors.length, 0);
  assert.deepEqual(journal.map((row) => row.event), ["invocation_started", "collection", "test_end", "test_end", "session_finished"]);
  assert.equal(journal.at(-1).status, "failed");
  for (const suite of native.suites) {
    const tests = suite.specs ?? suite.suites?.[0]?.specs;
    for (const spec of tests) {
      const run = spec.tests[0].results[0];
      assert.equal(run.retry, 0);
      assert.equal(run.status, "failed");
      assert.equal(run.networkEvidence.status, "retained");
      assert.equal(run.networkEvidence.snapshot.records.length, 64);
      assert.equal(run.networkEvidence.snapshot.records[0].route, "ip/application");
      assert.equal(run.networkEvidence.snapshot.records[0].status, spec.title.endsWith("503") ? 503 : 200);
      assert.equal(run.networkEvidence.snapshot.records[0].problemType, null);
      assert.equal(run.networkEvidence.snapshot.records[0].requestId,
        spec.title.endsWith("503") ? "01234567-89ab-cdef-0123-456789abcdef" : null);
      assert.equal(run.networkEvidence.snapshot.omitted, 3);
    }
  }
  const nativeXml = fs.readFileSync(path.join(directory, "native-results.xml"), "utf8");
  assert.equal([...nativeXml.matchAll(/<testsuite\b[^>]* tests="1" failures="1" errors="0" skipped="0"/g)].length, 2);
  assert.ok(![text, nativeXml, JSON.stringify(journal)].some((content) => content.includes(sentinel)));
});
