// @vitest-environment node
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

// A docket dropdown fed by a bare `fetchIpDockets` call reads one page of 100
// and silently cannot offer docket 101 onwards. Pick dockets with
// IpDocketPicker (server search plus keyset paging) instead.

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const SOURCE_DIRS = ["app", "components"];
const SOURCE_FILE = /\.tsx?$/;
const BARE_DOCKET_LIST = /queryFn:\s*fetchIpDockets\b(?!\s*\()|fetchIpDockets\(\s*\)/;

// The IP home page states its 100-record cap and links to the full portfolio.
const ACKNOWLEDGED = ["app/app/ip/page.tsx"];

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "node_modules" ? [] : sourceFiles(full);
    return SOURCE_FILE.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [full] : [];
  });
}

describe("IP docket dropdowns", () => {
  it("never load only the first page of dockets", () => {
    const offenders = SOURCE_DIRS.flatMap((dir) => sourceFiles(path.join(webRoot, dir)))
      .filter((file) => BARE_DOCKET_LIST.test(readFileSync(file, "utf8")))
      .map((file) => path.relative(webRoot, file).split(path.sep).join("/"))
      .sort();
    expect(offenders).toEqual(ACKNOWLEDGED);
  });
});
