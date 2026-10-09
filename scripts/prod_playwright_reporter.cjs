"use strict";

// Public Playwright Reporter API only. Never serialize FullConfig, TestError,
// stdio, steps, generic attachments or auth state; select/redact before I/O.
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const limit = 64 * 1024 * 1024;
const diagnosticLimit = 64 * 1024;
const routes = new Set(["auth/session", "matter/bulk-update", "matter/attachment", "notice/attachment",
  "ip/title-interest", "web/sign-in", "web/app-navigation"]);
const problems = new Set(["database_lock_timeout", "database_busy", "database_unavailable", "invalid_token",
  "missing_bearer_token", "rate_limited", "capability_required", "role_required", "step_up_required",
  "mfa_enrollment_required", "validation_error"]);
const transports = new Set(["net::ERR_CONNECTION_RESET", "net::ERR_CONNECTION_CLOSED", "net::ERR_CONNECTION_REFUSED",
  "net::ERR_TIMED_OUT", "net::ERR_ABORTED", "net::ERR_FAILED", "net::ERR_INTERNET_DISCONNECTED",
  "net::ERR_NAME_NOT_RESOLVED", "net::ERR_SSL_PROTOCOL_ERROR", "unclassified_transport_failure"]);

function exact(value, keys) {
  return value && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
}

function timestamp(value) {
  if (typeof value !== "string" || !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(value)) return false;
  const date = new Date(value);
  return Number.isFinite(date.getTime()) && date.toISOString() === value;
}

function networkEvidence(attachments) {
  if (!Array.isArray(attachments) || attachments.length > 256) return { status: "rejected", reason: "attachment_inventory" };
  const selected = attachments.filter((item) => item.name === "sanitized-network-evidence");
  if (!selected.length) return { status: "absent" };
  const reject = (reason) => ({ status: "rejected", reason });
  if (selected.length !== 1) return reject("duplicate_diagnostic");
  const attachment = selected[0];
  // The existing diagnostic fixture supplies a public TestResult Buffer.
  // Reject paths outright: no file read/copy, symlink or arbitrary path channel.
  if (attachment.contentType !== "application/json" || attachment.path !== undefined) return reject("type_or_path");
  if (!Buffer.isBuffer(attachment.body) || attachment.body.length > diagnosticLimit) return reject("body_bound");
  let snapshot;
  try {
    const text = attachment.body.toString("utf8");
    if (!Buffer.from(text, "utf8").equals(attachment.body)) return reject("invalid_utf8");
    snapshot = JSON.parse(text);
  } catch { return reject("invalid_json"); }
  if (!exact(snapshot, ["schemaVersion", "drainTimedOut", "omitted", "records"])
    || snapshot.schemaVersion !== 1 || typeof snapshot.drainTimedOut !== "boolean"
    || !Number.isSafeInteger(snapshot.omitted) || snapshot.omitted < 0
    || !Array.isArray(snapshot.records) || snapshot.records.length > 64) return reject("snapshot_schema");
  for (const row of snapshot.records) {
    const keys = ["route", "method", "startedAt", "finishedAt", "outcome"];
    if (row?.outcome === "response_completed") keys.push("status", "requestId", "problemType");
    else if (row?.outcome === "transport_failed") keys.push("failureCode");
    else if (!["pending_at_test_end", "response_unavailable", "diagnostic_unavailable"].includes(row?.outcome)) return reject("outcome");
    if (!exact(row, keys) || !routes.has(row.route) || typeof row.method !== "string" || !/^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)$/.test(row.method)
      || !timestamp(row.startedAt) || (row.outcome === "pending_at_test_end" ? row.finishedAt !== null : !timestamp(row.finishedAt))) return reject("record_schema");
    if (row.outcome === "response_completed" && (!Number.isInteger(row.status) || row.status < 100 || row.status > 599
      || (row.requestId !== null && (typeof row.requestId !== "string" || !/^(?:[a-f0-9]{32}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})$/i.test(row.requestId)))
      || (row.problemType !== null && !problems.has(row.problemType)))) return reject("response_schema");
    if (row.outcome === "transport_failed" && !transports.has(row.failureCode)) return reject("transport_schema");
  }
  return { status: "retained", name: "sanitized-network-evidence", contentType: "application/json", snapshot };
}

function safe(value) {
  let text = String(value ?? "").replace(/[\x00-\x08\x0b\x0c\x0e-\x1f]/g, "\ufffd");
  for (const [name, secret] of Object.entries(process.env)) {
    if (/PASSWORD|SECRET|TOKEN|API_KEY|COOKIE|AUTH/i.test(name) && secret.length >= 4) {
      text = text.split(secret).join("[redacted]");
    }
  }
  // Two legacy skips append response.text(), which may be unstructured legal
  // text. Keep their status/prerequisite, never retain that body as annotation.
  text = text.replace(/(Upload failed \(\d+\): )[^]*?(; cannot seed BUG-028 fixture\.)$/, "$1[response body redacted]$2")
    .replace(/(Could not create probe matter: \d+ )[^]*/, "$1[response body redacted]");
  if (/[{}<>]|authorization\s*:|cookie\s*:|\b(?:body|payload)\s*[:=]/i.test(text)) {
    return "[redacted structured or sensitive annotation]";
  }
  return text
    .replace(/https?:\/\/\S+|\S*\?\S+|\bBearer\s+\S+/gi, "[url-query-token-redacted]")
    .replace(/[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}/g, "[email-redacted]")
    .replace(/\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b/gi, "[identity-redacted]");
}

function location(value) {
  if (!value || typeof value.file !== "string") return undefined;
  const file = path.resolve(value.file);
  const relative = path.relative(root, file);
  if (relative.startsWith("..") || path.isAbsolute(relative) || !/\.(?:[cm]?[jt]sx?)$/.test(relative)) return undefined;
  return { file: relative.replaceAll("\\", "/"), line: value.line, column: value.column };
}

function annotations(values) {
  return (values ?? []).map((value) => ({
    type: safe(value.type),
    ...(value.description === undefined ? {} : { description: safe(value.description) }),
    ...(location(value.location) ? { location: location(value.location) } : {}),
  }));
}

function error(value) {
  return {
    message: "[redacted native test error; outcome retained]",
    ...(location(value?.location) ? { location: location(value.location) } : {}),
  };
}

function xml(value) {
  return String(value ?? "").replace(/[&<>"'\r\n\t]/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;",
    "\n": "&#10;", "\r": "&#13;", "\t": "&#9;",
  })[c]);
}

function write(file, content) {
  if (!file || Buffer.byteLength(content, "utf8") > limit) throw new Error("Missing or oversized safe evidence");
  fs.writeFileSync(file, content, { encoding: "utf8", flag: "wx" });
}

class ProductionEvidenceReporter {
  constructor() {
    this.errors = [];
    this.start = new Date();
  }

  onBegin(config, suite) {
    this.config = config;
    this.suite = suite;
  }

  onError(value) {
    this.errors.push(error(value));
  }

  async onEnd(result) {
    if (!this.config || !this.suite) throw new Error("Missing native collection");
    const config = this.config;
    const phase = process.env.CASEOPS_PW_EVIDENCE_PHASE;
    const sha = process.env.CASEOPS_EXPECTED_RELEASE_SHA;
    const invocation = process.env.CASEOPS_PW_EVIDENCE_INVOCATION;
    if (!/^[a-f0-9]{40}$/.test(sha ?? "") || !/^[a-z][a-z0-9-]{0,63}$/.test(invocation ?? "")
      || !["discovery", "execution"].includes(phase)) throw new Error("Invalid native evidence binding");
    const names = config.projects.map((project) => project.name);
    if (new Set(names).size !== names.length || names.some((name) => !/^[\w-]*$/.test(name))) {
      throw new Error("Ambiguous native project identity");
    }
    const output = (name, variable) => {
      const expected = path.join(root, "test-results", "prod-native-evidence", invocation, name);
      if (path.resolve(process.env[variable] ?? ".") !== expected) throw new Error("Unreviewed evidence destination");
      return expected;
    };
    const jsonFile = output(phase === "discovery" ? "native-discovery.json" : "native-results.json",
      "CASEOPS_PW_EVIDENCE_JSON_FILE");
    const junitFile = phase === "execution" ? output("native-results.xml", "CASEOPS_PW_EVIDENCE_JUNIT_FILE") : undefined;
    const stats = { startTime: (result.startTime ?? this.start).toISOString(),
      duration: result.duration ?? Date.now() - this.start.getTime(),
      expected: 0, skipped: 0, unexpected: 0, flaky: 0 };
    const suites = [];
    const junit = [];
    for (const test of this.suite.allTests()) {
      const project = test.parent.project();
      if (!project || !names.includes(project.name)) throw new Error("Unknown native project");
      const outcome = test.outcome();
      if (!Object.hasOwn(stats, outcome)) throw new Error("Unknown native outcome");
      stats[outcome]++;
      const relativeFile = path.relative(config.rootDir, test.location.file).replaceAll("\\", "/");
      const titles = test.titlePath().slice(2);
      const titlePath = titles.map(safe);
      const nativeTest = {
        timeout: test.timeout, annotations: annotations(test.annotations),
        retries: test.retries, repeatEachIndex: test.repeatEachIndex,
        expectedStatus: test.expectedStatus, projectId: project.name, projectName: project.name,
        results: test.results.map((run) => ({
          workerIndex: run.workerIndex, parallelIndex: run.parallelIndex,
          status: run.status, duration: run.duration, retry: run.retry,
          startTime: run.startTime.toISOString(), annotations: annotations(run.annotations),
          errors: (run.errors ?? []).map(error),
          networkEvidence: networkEvidence(run.attachments),
        })), status: outcome,
      };
      const spec = { title: safe(test.title), ok: test.ok(), id: test.id,
        file: relativeFile, line: test.location.line, column: test.location.column,
        tags: (test.tags ?? []).map(safe), tests: [nativeTest] };
      // One canonical native spec per case keeps public TestCase.id intact,
      // including repeated/project variants, without internal Playwright APIs.
      let node = { title: titlePath[0], file: relativeFile, specs: [] };
      suites.push(node);
      for (const title of titlePath.slice(1, -1)) {
        const child = { title, specs: [] };
        node.suites = [child];
        node = child;
      }
      node.specs.push(spec);
      const properties = nativeTest.annotations.map((item) =>
        `<property name="${xml(item.type)}" value="${xml(item.description)}"/>`).join("")
        + nativeTest.results.map((run) => `<property name="sanitized-network-evidence" value="${xml(run.networkEvidence.status)}"/>`).join("");
      const failure = outcome === "unexpected" ?
        '<failure message="Redacted native test error" type="FAILURE">Native failure; private detail omitted.</failure>' : "";
      const skipped = outcome === "skipped" ? "<skipped/>" : "";
      const duration = test.results.reduce((total, run) => total + run.duration, 0) / 1000;
      // The title-path array disambiguates nested/display-separator collisions.
      // Escape XML attribute whitespace rather than normalizing native titles.
      junit.push(`<testsuite name="${xml(titlePath[0])}" hostname="${xml(project.name)}" tests="1" failures="${failure ? 1 : 0}" errors="0" skipped="${skipped ? 1 : 0}" time="${duration}">`
        + `<testcase classname="${xml(titlePath[0])}" name="${xml(titlePath.slice(1).join(" \u203a "))}" time="${duration}"`
        + ` file="${xml(relativeFile)}" line="${xml(test.location.line)}" column="${xml(test.location.column)}"`
        + ` caseops-id="${xml(test.id)}" caseops-project-id="${xml(project.name)}" caseops-project-name="${xml(project.name)}"`
        + ` caseops-title-path="${xml(JSON.stringify(titlePath))}" caseops-outcome="${xml(outcome)}">`
        + `<properties>${properties}</properties>${failure}${skipped}</testcase></testsuite>`);
    }
    const report = {
      config: {
        configFile: config.configFile, rootDir: config.rootDir, workers: config.workers,
        projects: config.projects.map((project) => ({
          id: project.name, name: project.name, testDir: project.testDir,
          retries: project.retries, repeatEach: project.repeatEach, timeout: project.timeout,
        })),
      }, suites, errors: this.errors, stats, status: result.status,
      release_sha: sha, invocation, phase,
    };
    write(jsonFile, JSON.stringify(report, null, 2) + "\n");
    if (phase === "execution") {
      write(junitFile,
        '<?xml version="1.0" encoding="UTF-8"?>\n<testsuites>' + junit.join("") + "</testsuites>\n");
    }
  }
}

module.exports = ProductionEvidenceReporter;
