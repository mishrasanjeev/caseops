// @vitest-environment node
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

// A docket dropdown fed by one `fetchIpDockets` page reads at most one page
// and silently cannot offer the dockets after it. Pick dockets with
// IpDocketPicker (server search plus keyset paging) instead.
//
// Every `fetchIpDockets` use in app/, components/ and lib/ is checked. A use
// is a first-page read unless it is a call whose argument object passes a
// `cursor` (an infinite query or a paging loop). A bare reference such as
// `queryFn: fetchIpDockets` and any call without a cursor, whatever else it
// passes (`{ limit: 100 }`, `{ signal }`, `{}`), is flagged.

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const SOURCE_DIRS = ["app", "components", "lib"];
const SOURCE_FILE = /\.tsx?$/;

// Each first-page read is identified by its file and the query key of its own
// statement, so a second first-page read in an acknowledged file is still an
// offender. The IP home docket list states its cap (`has_more`) and links to
// the full portfolio; it feeds no picker (B4-ADJ-18 moved the Documents
// "Linked docket" field to IpDocketPicker).
const ACKNOWLEDGED = ['app/app/ip/page.tsx queryKey: ["ip", "dockets"]'];

// The only readers allowed to page dockets themselves. A new paged reader is a
// new picker or check and must be reviewed for search, totals and states.
const PAGED_READERS = [
  "components/ip/IpDocketPicker.tsx",
  "lib/api/endpoints.ts fetchEveryIpDocket",
];

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "node_modules" ? [] : sourceFiles(full);
    return SOURCE_FILE.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [full] : [];
  });
}

/** Blank out import/export-from declarations, keeping offsets. */
function withoutImports(source: string): string {
  return source.replace(
    /^\s*(?:import|export)\b[^;]*?\bfrom\s*["'][^"']+["'];?/gms,
    (match) => match.replace(/[^\n]/g, " "),
  );
}

/** The text between the parenthesis at `open` and its matching close. */
function callArguments(source: string, open: number): string {
  let depth = 0;
  for (let index = open; index < source.length; index += 1) {
    if (source[index] === "(") depth += 1;
    if (source[index] === ")") {
      depth -= 1;
      if (depth === 0) return source.slice(open + 1, index);
    }
  }
  return source.slice(open + 1);
}

type DocketRead = { kind: "first-page" | "paged"; label: string };

/** Every use of fetchIpDockets in a file, classified. */
function docketReads(file: string, source: string): DocketRead[] {
  const code = withoutImports(source);
  const reads: DocketRead[] = [];
  for (const match of code.matchAll(/\bfetchIpDockets\b/g)) {
    const at = match.index ?? 0;
    if (/function\s+$/.test(code.slice(Math.max(0, at - 20), at))) continue;
    const after = code.slice(at + match[0].length);
    const call = /^\s*\(/.exec(after);
    const args = call ? callArguments(code, at + match[0].length + call[0].length - 1) : null;
    const paged = args !== null && /\bcursor\b/.test(args);
    const before = code.slice(0, at);
    if (paged) {
      const owner = [...before.matchAll(/function\s+(\w+)/g)].pop()?.[1];
      reads.push({
        kind: "paged",
        label: file.startsWith("lib/") && owner ? `${file} ${owner}` : file,
      });
      continue;
    }
    const statement = before.slice(before.lastIndexOf(";") + 1);
    const keys = [...statement.matchAll(/queryKey:\s*(\[[^\]\n]*\])/g)];
    reads.push({
      kind: "first-page",
      label: `${file} ${keys.length ? `queryKey: ${keys[keys.length - 1][1]}` : "no queryKey"}`,
    });
  }
  return reads;
}

function productReads(): DocketRead[] {
  return SOURCE_DIRS.flatMap((dir) => sourceFiles(path.join(webRoot, dir))).flatMap((file) =>
    docketReads(path.relative(webRoot, file).split(path.sep).join("/"), readFileSync(file, "utf8")),
  );
}

describe("IP docket dropdowns", () => {
  it("never load only the first page of dockets", () => {
    const offenders = productReads()
      .filter((read) => read.kind === "first-page")
      .map((read) => read.label)
      .sort();
    expect(offenders).toEqual(ACKNOWLEDGED);
  });

  it("pages dockets only in the reviewed picker and whole-portfolio helper", () => {
    const paged = [...new Set(productReads().filter((read) => read.kind === "paged").map((read) => read.label))].sort();
    expect(paged).toEqual(PAGED_READERS);
  });

  it("acknowledges only a read that states its cap and feeds no picker", () => {
    const home = readFileSync(path.join(webRoot, "app/app/ip/page.tsx"), "utf8");
    expect(home).toContain("listing.data?.has_more");
    expect(home).toContain("Showing the 100 most recently updated records.");
    // The home list's rows must never reach the document upload field again.
    expect(home).not.toMatch(/<IpDocumentWorkspace[^>]*\bdockets=/);
  });

  it("flags every first-page read, whatever it passes, including a second one in an acknowledged file", () => {
    const source = [
      'import { fetchIpDockets, fetchIpDocket } from "@/lib/api/endpoints";',
      'const listing = useQuery({ queryKey: ["ip", "dockets"], queryFn: fetchIpDockets });',
      'const upload = useQuery({ queryKey: ["ip", "upload-dockets"], queryFn: fetchIpDockets });',
      "const page = await fetchIpDockets();",
      'const limited = useQuery({ queryKey: ["ip", "limited"], queryFn: () => fetchIpDockets({ limit: 100 }) });',
      'const signalled = useQuery({ queryKey: ["ip", "signalled"], queryFn: ({ signal }) => fetchIpDockets({ signal }) });',
      "const empty = await fetchIpDockets({});",
      "const read = fetchIpDockets;",
      'const searched = await fetchIpDockets({ query: "abc", limit: 200 });',
      "const paged = useInfiniteQuery({ queryFn: ({ pageParam }) => fetchIpDockets({ cursor: pageParam }) });",
    ].join("\n");
    const reads = docketReads("app/app/ip/page.tsx", source);
    expect(reads.filter((read) => read.kind === "first-page").map((read) => read.label)).toEqual([
      'app/app/ip/page.tsx queryKey: ["ip", "dockets"]',
      'app/app/ip/page.tsx queryKey: ["ip", "upload-dockets"]',
      "app/app/ip/page.tsx no queryKey",
      'app/app/ip/page.tsx queryKey: ["ip", "limited"]',
      'app/app/ip/page.tsx queryKey: ["ip", "signalled"]',
      "app/app/ip/page.tsx no queryKey",
      "app/app/ip/page.tsx no queryKey",
      "app/app/ip/page.tsx no queryKey",
    ]);
    expect(reads.filter((read) => read.kind === "paged")).toHaveLength(1);
  });
});
