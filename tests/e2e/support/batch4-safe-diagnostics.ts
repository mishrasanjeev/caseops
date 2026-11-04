/** Closed, opt-in NONRELEASE diagnostics. No legal text, URLs, IDs or credentials. */
import fs from "node:fs";
import path from "node:path";
import { types } from "node:util";

export type Batch4SafeDiagnostic =
  | { kind: "specialist_control"; ordinal: number; tag: "select" | "input" | "textarea";
      own_disabled: boolean; effective_disabled: boolean; ancestor_fieldset_disabled: boolean;
      real_option_count: number; total_option_count: number; internal_field: boolean }
  | { kind: "watch_http"; phase: "profile_create" | "journal_intake" | "hit_disposition" | "profile_pause"; status: number }
  | { kind: "invoice_line"; invoice_ordinal: number; line_ordinal: number; expected_length: number;
      raw_match: boolean; typography_candidate_match: boolean; nfkc_match: boolean;
      has_non_latin1: boolean; typography_change_count: number; expected_sha256: string; pdf_compact_sha256: string };

const ROOT = process.env.GITHUB_WORKSPACE ?? "";
const DIRECTORY = path.join(ROOT, "test-results", "batch4-safe");
const MAIN = "bdd1480699222712475372690334659088629429";
const BRANCH = "refs/heads/codex/prod-batch4-diagnostics-20261104";
const MAX_FILES = 8;
const MAX_ROWS = 512;
const MAX_BYTES = 1024 * 1024;
let output: { fd: number; dev: bigint; ino: bigint; rows: number; bytes: number } | undefined;
let refused = false;

function refuse(): never {
  refused = true;
  throw new Error("BATCH4_SAFE_DIAGNOSTIC_REFUSED");
}
function check(value: unknown): asserts value {
  if (!value) refuse();
}
function enabled() {
  const flag = process.env.CASEOPS_BATCH4_SAFE_DIAGNOSTICS;
  if (flag === undefined) return false;
  check(flag === "1");
  return true;
}
function context() {
  check(enabled() && process.env.GITHUB_ACTIONS === "true"
    && process.env.GITHUB_EVENT_NAME === "workflow_dispatch" && process.env.GITHUB_REF === BRANCH
    && process.env.CASEOPS_EXPECTED_RELEASE_SHA === MAIN
    && process.env.CASEOPS_BATCH4_DIAGNOSTIC_MODE === "scoped-failure-diagnostics"
    && /^[1-9][0-9]{0,19}$/.test(process.env.GITHUB_RUN_ID ?? "")
    && /^[1-9][0-9]{0,5}$/.test(process.env.GITHUB_RUN_ATTEMPT ?? "")
    && path.isAbsolute(ROOT) && path.normalize(ROOT) === ROOT && path.resolve(ROOT) === ROOT
    && path.resolve(process.cwd()) === ROOT);
  return { schema: 1, release_sha: MAIN, run_id: process.env.GITHUB_RUN_ID!, attempt: process.env.GITHUB_RUN_ATTEMPT! };
}
function ordinaryDirectory(directory: string) {
  const ancestors: string[] = [];
  for (let current = directory;; current = path.dirname(current)) {
    ancestors.push(current);
    if (path.dirname(current) === current) break;
  }
  for (const item of ancestors) {
    const observed = fs.lstatSync(item);
    check(observed.isDirectory() && !observed.isSymbolicLink() && fs.realpathSync(item) === item);
  }
}
function version(value: fs.BigIntStats) {
  return [value.dev, value.ino, value.mode, value.size, value.mtimeNs, value.ctimeNs, value.nlink, value.birthtimeNs].join(":");
}
function readClosed(file: string, limit: number) {
  const pathname = fs.lstatSync(file, { bigint: true });
  check(pathname.isFile() && !pathname.isSymbolicLink() && pathname.size <= BigInt(limit));
  const fd = fs.openSync(file, "r");
  try {
    const before = fs.fstatSync(fd, { bigint: true });
    check(pathname.dev === before.dev && pathname.ino === before.ino && pathname.size === before.size);
    const bytes = fs.readFileSync(fd);
    check(bytes.length <= limit && version(before) === version(fs.fstatSync(fd, { bigint: true }))
      && version(pathname) === version(fs.lstatSync(file, { bigint: true })));
    return bytes;
  } finally { fs.closeSync(fd); }
}
function owner() {
  ordinaryDirectory(DIRECTORY);
  check(readClosed(path.join(DIRECTORY, ".owner.json"), 1024).equals(Buffer.from(JSON.stringify(context()) + "\n")));
}
function row(value: unknown): Batch4SafeDiagnostic {
  check(value !== null && typeof value === "object" && !Array.isArray(value) && !types.isProxy(value));
  check(Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null);
  const descriptors = Object.getOwnPropertyDescriptors(value);
  const keys = Reflect.ownKeys(value);
  check(keys.every((key) => typeof key === "string" && descriptors[key]?.enumerable
    && Object.hasOwn(descriptors[key], "value") && !descriptors[key].get && !descriptors[key].set));
  const clean = Object.fromEntries(keys.map((key) => [key, descriptors[key as string].value])) as Record<string, unknown>;
  const exact = (names: string[]) => keys.length === names.length && names.every((name) => Object.hasOwn(clean, name));
  const integer = (key: string, minimum: number, maximum: number) => Number.isSafeInteger(clean[key])
    && (clean[key] as number) >= minimum && (clean[key] as number) <= maximum;
  const bools = (...names: string[]) => names.every((name) => typeof clean[name] === "boolean");
  if (clean.kind === "specialist_control") {
    check(exact(["kind", "ordinal", "tag", "own_disabled", "effective_disabled", "ancestor_fieldset_disabled",
      "real_option_count", "total_option_count", "internal_field"])
      && integer("ordinal", 1, 10000) && ["select", "input", "textarea"].includes(clean.tag as string)
      && integer("real_option_count", 0, 10000) && integer("total_option_count", 0, 10000)
      && (clean.real_option_count as number) <= (clean.total_option_count as number)
      && bools("own_disabled", "effective_disabled", "ancestor_fieldset_disabled", "internal_field"));
  } else if (clean.kind === "watch_http") {
    check(exact(["kind", "phase", "status"])
      && ["profile_create", "journal_intake", "hit_disposition", "profile_pause"].includes(clean.phase as string)
      && integer("status", 100, 599));
  } else if (clean.kind === "invoice_line") {
    check(exact(["kind", "invoice_ordinal", "line_ordinal", "expected_length", "raw_match", "typography_candidate_match",
      "nfkc_match", "has_non_latin1", "typography_change_count", "expected_sha256", "pdf_compact_sha256"])
      && integer("invoice_ordinal", 1, 2) && integer("line_ordinal", 1, 10000)
      && integer("expected_length", 0, 100000) && integer("typography_change_count", 0, 100000)
      && bools("raw_match", "typography_candidate_match", "nfkc_match", "has_non_latin1")
      && ["expected_sha256", "pdf_compact_sha256"].every((key) => typeof clean[key] === "string" && /^[a-f0-9]{64}$/.test(clean[key] as string)));
  } else refuse();
  check(Buffer.byteLength(JSON.stringify(clean)) < 4096);
  return clean as Batch4SafeDiagnostic;
}

/** Workflow-only initializer. Existing destinations are always refused. */
export function prepareBatch4DiagnosticOutput(): void {
  try {
    const binding = context();
    ordinaryDirectory(ROOT);
    const parent = path.dirname(DIRECTORY);
    if (!fs.existsSync(parent)) fs.mkdirSync(parent);
    ordinaryDirectory(parent);
    check(!fs.existsSync(DIRECTORY));
    fs.mkdirSync(DIRECTORY, { mode: 0o700 });
    const fd = fs.openSync(path.join(DIRECTORY, ".owner.json"), "wx", 0o600);
    try {
      const body = Buffer.from(JSON.stringify(binding) + "\n");
      const written = fs.writeSync(fd, body);
      check(written === body.length); fs.fsyncSync(fd);
    } finally { fs.closeSync(fd); }
    owner();
  } catch { refuse(); }
}

/** No-op without explicit opt-in. Enabled schema/IO refusals throw fixed errors. */
export function recordBatch4Diagnostic(value: Batch4SafeDiagnostic): void {
  if (!enabled()) return;
  try {
    check(!refused);
    context();
    const safe = row(value);
    owner();
    const file = path.join(DIRECTORY, `records-${process.pid}.jsonl`);
    if (!output) {
      check(fs.readdirSync(DIRECTORY).length <= MAX_FILES);
      const fd = fs.openSync(file, "wx", 0o600);
      try {
        const observed = fs.fstatSync(fd, { bigint: true });
        output = { fd, dev: observed.dev, ino: observed.ino, rows: 0, bytes: 0 };
      } catch { fs.closeSync(fd); refuse(); }
    }
    const pathname = fs.lstatSync(file, { bigint: true });
    const descriptor = fs.fstatSync(output.fd, { bigint: true });
    check(pathname.isFile() && !pathname.isSymbolicLink() && descriptor.isFile()
      && pathname.dev === output.dev && pathname.ino === output.ino
      && descriptor.dev === output.dev && descriptor.ino === output.ino
      && pathname.size === BigInt(output.bytes) && descriptor.size === pathname.size);
    const bytes = Buffer.from(JSON.stringify(safe) + "\n");
    check(output.rows < MAX_ROWS && output.bytes + bytes.length <= MAX_BYTES);
    // Reserve before IO: failure can never be retried into a successful capture.
    output.rows += 1; output.bytes += bytes.length;
    const written = fs.writeSync(output.fd, bytes);
    check(written === bytes.length); fs.fsyncSync(output.fd);
  } catch {
    if (output) { try { fs.closeSync(output.fd); } catch {} output = undefined; }
    refuse();
  }
}

/** Validate closed worker outputs after native EOF; never opens private attachments. */
export function validateBatch4DiagnosticOutput() {
  try {
    context(); owner();
    const entries = fs.readdirSync(DIRECTORY).sort();
    check(entries.length >= 2 && entries.length <= MAX_FILES + 1
      && entries.filter((name) => name === ".owner.json").length === 1
      && entries.every((name) => name === ".owner.json" || /^records-[1-9][0-9]{0,10}\.jsonl$/.test(name)));
    const counts = { specialist_control: 0, watch_http: 0, invoice_line: 0 };
    let total = 0; let bytes = 0;
    for (const file of entries.filter((name) => name !== ".owner.json")) {
      const raw = readClosed(path.join(DIRECTORY, file), MAX_BYTES);
      const text = raw.toString("utf8");
      check(Buffer.from(text).equals(raw) && text.endsWith("\n"));
      bytes += raw.length;
      for (const line of text.slice(0, -1).split("\n")) {
        check(Buffer.byteLength(line) < 4096);
        const clean = row(JSON.parse(line));
        check(JSON.stringify(clean) === line);
        counts[clean.kind] += 1; total += 1;
        check(total <= MAX_ROWS && bytes <= MAX_BYTES);
      }
    }
    check(fs.readdirSync(DIRECTORY).sort().join("\0") === entries.join("\0"));
    return { state: "validated_safe_rows" as const, files: entries.length - 1, rows: total, bytes, counts };
  } catch { refuse(); }
}
