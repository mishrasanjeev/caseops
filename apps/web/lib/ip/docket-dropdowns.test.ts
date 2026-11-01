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
const BARE_DOCKET_LIST = /queryFn:\s*fetchIpDockets\b(?!\s*\()|fetchIpDockets\(\s*\)/g;

// Each bare read is identified by its file and the query key of its own
// statement, so a second first-page read in an acknowledged file is still an
// offender. The IP home docket list states its 100-record cap (`has_more`) and
// links to the full portfolio; it feeds no picker (B4-ADJ-18 moved the
// Documents "Linked docket" field to IpDocketPicker).
const ACKNOWLEDGED = ['app/app/ip/page.tsx queryKey: ["ip", "dockets"]'];

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "node_modules" ? [] : sourceFiles(full);
    return SOURCE_FILE.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [full] : [];
  });
}

/** One entry per bare read: "<file> <its statement's queryKey>" or "<file> no queryKey". */
function bareDocketReads(file: string, source: string): string[] {
  return [...source.matchAll(BARE_DOCKET_LIST)].map((match) => {
    const before = source.slice(0, match.index);
    const statement = before.slice(before.lastIndexOf(";") + 1);
    const keys = [...statement.matchAll(/queryKey:\s*(\[[^\]\n]*\])/g)];
    return `${file} ${keys.length ? `queryKey: ${keys[keys.length - 1][1]}` : "no queryKey"}`;
  });
}

describe("IP docket dropdowns", () => {
  it("never load only the first page of dockets", () => {
    const offenders = SOURCE_DIRS.flatMap((dir) => sourceFiles(path.join(webRoot, dir)))
      .flatMap((file) =>
        bareDocketReads(path.relative(webRoot, file).split(path.sep).join("/"), readFileSync(file, "utf8")))
      .sort();
    expect(offenders).toEqual(ACKNOWLEDGED);
  });

  it("acknowledges only a read that states its cap and feeds no picker", () => {
    const home = readFileSync(path.join(webRoot, "app/app/ip/page.tsx"), "utf8");
    expect(home).toContain("listing.data?.has_more");
    expect(home).toContain("Showing the 100 most recently updated records.");
    // The home list's rows must never reach the document upload field again.
    expect(home).not.toMatch(/<IpDocumentWorkspace[^>]*\bdockets=/);
  });

  it("flags every bare read separately, including a second one in an acknowledged file", () => {
    const source = [
      'const listing = useQuery({ queryKey: ["ip", "dockets"], queryFn: fetchIpDockets });',
      'const upload = useQuery({ queryKey: ["ip", "upload-dockets"], queryFn: fetchIpDockets });',
      "const page = await fetchIpDockets();",
    ].join("\n");
    expect(bareDocketReads("app/app/ip/page.tsx", source)).toEqual([
      'app/app/ip/page.tsx queryKey: ["ip", "dockets"]',
      'app/app/ip/page.tsx queryKey: ["ip", "upload-dockets"]',
      "app/app/ip/page.tsx no queryKey",
    ]);
  });
});
