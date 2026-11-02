// @vitest-environment node
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

// Ram 2026-10-30 (BUG-005/ENH-017 evidence): production showed a capital A
// with a circumflex before every middle dot ("candidate \u00c2\u00b7 triage") because
// UTF-8 punctuation had been saved through a Windows-1252 round trip, and two
// tests asserted the garbled text, which locked the defect in. This guard
// fails on those byte-pair signatures anywhere in web or end-to-end source.
// Every pattern is written as an escape so this file never matches itself.

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const SCANNED = ["apps/web/app", "apps/web/components", "apps/web/lib", "apps/web/test", "tests/e2e"];
const SOURCE_FILE = /\.(?:ts|tsx|js|mjs|cjs|css|json|md)$/;

const MOJIBAKE: Array<[string, RegExp]> = [
  // U+0080-U+00BF (middle dot, copyright, no-break space...) read as
  // Windows-1252: A-circumflex followed by the symbol.
  ["A-circumflex + Latin-1 symbol", /\u00c2[\u00a0-\u00bf]/],
  // U+00C0-U+00FF (e-acute, u-umlaut...) read as Windows-1252: A-tilde
  // followed by a continuation character.
  ["A-tilde + continuation", /\u00c3[\u0080-\u00bf\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u0192\u02c6\u02dc\u2013\u2014\u2018-\u201e\u2020-\u2022\u2026\u2030\u2039\u203a\u20ac\u2122]/],
  // U+2000-U+203F punctuation (dashes, curly quotes, ellipsis) read as
  // Windows-1252: a-circumflex, euro sign, then one more character.
  ["a-circumflex + euro sign", /\u00e2\u20ac/],
  // A UTF-8 byte-order mark read as Windows-1252.
  ["byte-order mark as Windows-1252", /\u00ef\u00bb\u00bf/],
];

function files(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    if (entry.name === "node_modules" || entry.name === ".next") return [];
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return files(full);
    return SOURCE_FILE.test(entry.name) ? [full] : [];
  });
}

function mojibakeFindings(text: string): string[] {
  return text.split("\n").flatMap((line, index) =>
    MOJIBAKE.filter(([, pattern]) => pattern.test(line)).map(
      ([name]) => `${index + 1}: ${name}: ${line.trim().slice(0, 120)}`,
    ),
  );
}

describe("source encoding", () => {
  it("recognises each garbled sequence the tester saw", () => {
    expect(mojibakeFindings("candidate \u00c2\u00b7 triage")).toHaveLength(1);
    expect(mojibakeFindings("Provisional \u00e2\u20ac\u201d source")).toHaveLength(1);
    expect(mojibakeFindings("Loading\u00e2\u20ac\u00a6")).toHaveLength(1);
    expect(mojibakeFindings("Caf\u00c3\u00a9")).toHaveLength(1);
    expect(mojibakeFindings("Lawyer\u00e2\u20ac\u2122s note")).toHaveLength(1);
    expect(mojibakeFindings("\u00ef\u00bb\u00bfimport")).toHaveLength(1);
    // The intended characters are fine, as are Indian scripts and the rupee.
    expect(
      mojibakeFindings(
        "candidate \u00b7 triage \u2014 Loading\u2026 Caf\u00e9 Lawyer\u2019s \u20b9 \u0939\u093f\u0902\u0926\u0940",
      ),
    ).toEqual([]);
  });

  it("finds no Windows-1252 mojibake in web or end-to-end source", () => {
    const scanned = SCANNED.flatMap((dir) => files(path.join(repoRoot, dir)));
    expect(scanned.length).toBeGreaterThan(500);
    const offenders = scanned.flatMap((file) =>
      mojibakeFindings(readFileSync(file, "utf8")).map(
        (finding) => `${path.relative(repoRoot, file).split(path.sep).join("/")}:${finding}`,
      ),
    );
    expect(offenders).toEqual([]);
  });
});
