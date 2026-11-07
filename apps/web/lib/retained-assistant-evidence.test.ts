// @vitest-environment node

import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { readRetainedAssistantEvidence } from "../../../tests/e2e/support/retained-assistant-evidence";

const digest = (bytes: Buffer | string) => createHash("sha256").update(bytes).digest("hex");

describe("retained assistant evidence", () => {
  let directory: string;
  let file: string;

  beforeEach(() => {
    directory = fs.mkdtempSync(path.join(os.tmpdir(), "caseops-retained-assistant-"));
    file = path.join(directory, "manifest.json");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    fs.rmSync(directory, { recursive: true, force: true });
  });

  it("reads the exact pinned regular file", () => {
    const body = Buffer.from('{"fixture_kind":"retained_qa"}');
    fs.writeFileSync(file, body);
    expect(readRetainedAssistantEvidence(file, digest(body))).toEqual(body);
  });

  it.each(["empty", "oversized", "digest-mismatch"])("rejects %s input", (mode) => {
    const bytes = Buffer.alloc(mode === "empty" ? 0 : mode === "oversized" ? 131073 : 8, 1);
    fs.writeFileSync(file, bytes);
    expect(() => readRetainedAssistantEvidence(file, digest(mode === "digest-mismatch" ? "other" : bytes)))
      .toThrow(/unavailable, unsafe or changed/);
  });

  it("rejects malformed digests before opening a path", () => {
    const open = vi.spyOn(fs, "openSync");
    expect(() => readRetainedAssistantEvidence(file, "invalid")).toThrow(/Invalid retained evidence digest/);
    expect(open).not.toHaveBeenCalled();
  });

  it("refuses a symbolic or reparse leaf", () => {
    const destination = path.join(directory, "destination");
    if (process.platform === "win32") fs.mkdirSync(destination);
    else fs.writeFileSync(destination, "retained");
    fs.symlinkSync(destination, file, process.platform === "win32" ? "junction" : "file");
    expect(() => readRetainedAssistantEvidence(file, digest("retained"))).toThrow(/unsafe/);
  });

  it("never admits replacement bytes after checking the named file", () => {
    fs.writeFileSync(file, "original");
    const replacement = "replaced";
    const realLstat = fs.lstatSync;
    vi.spyOn(fs, "lstatSync").mockImplementationOnce((...args) => {
      const entry = Reflect.apply(realLstat, fs, args);
      fs.renameSync(file, path.join(directory, "original.json"));
      fs.writeFileSync(file, replacement);
      return entry;
    });
    expect(() => readRetainedAssistantEvidence(file, digest(replacement))).toThrow(/changed/);
    expect(fs.readFileSync(file, "utf8")).toBe(replacement);
  });

  it("rejects a file that grows after admission without allocating the new size", () => {
    fs.writeFileSync(file, "retained");
    const realLstat = fs.lstatSync;
    vi.spyOn(fs, "lstatSync").mockImplementationOnce((...args) => {
      const entry = Reflect.apply(realLstat, fs, args);
      fs.appendFileSync(file, Buffer.alloc(131073));
      return entry;
    });
    const read = vi.spyOn(fs, "readSync");
    expect(() => readRetainedAssistantEvidence(file, digest("retained"))).toThrow(/changed/);
    expect(read).toHaveBeenCalledTimes(1);
    expect(read.mock.calls[0][1].byteLength).toBe(9);
  });
});
