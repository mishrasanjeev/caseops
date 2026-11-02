// @vitest-environment node
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

// B4-ADJ-13: a table wider than its container hid its row actions (Open
// record, Edit dates, duplicate decisions, invoice downloads) past the right
// edge at 1024px and on a phone. Every table must keep its rows reachable in
// one of three ways:
//   stacked  - the stacked-table utility under a container max-width variant
//              set to the table's own width, inside a container parent, with
//              a `data-label` on every cell, so rows become labelled blocks
//              whenever the container is narrower than the table;
//   switched - an entry list for narrow containers and a hidden table wrapper
//              that a container min-width variant shows, inside a container;
// (Class names are described, not written, here: Tailwind scans this file.)
//   pinned   - the record or action column is `sticky` so it never scrolls
//              out of view.
// Anything else must be listed below with the reason its rows stay
// reachable, or as a known offender still to fix. The list is exact, so a
// fixed table that stays listed, or a new wide table, fails this test.
// Rows are read together with the same-file components that render them
// (EmployeeRow, ProceedingSignalRow, ...), so a cell or action drawn by a row
// component counts, and a table listed as read-only must have no control
// (button, link, input, select or click handler) in it or in its rows.

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SOURCE_DIRS = ["app", "components"];

const ACKNOWLEDGED: Record<string, string> = {
  // Read-only tables: no row control, values scroll inside their own container.
  "app/app/admin/billing/page.tsx#2": "read-only credit ledger",
  "app/app/admin/billing/usage/page.tsx#1": "read-only usage quantities",
  "app/app/admin/billing/usage/page.tsx#2": "read-only provider spend",
  "app/app/admin/employees/page.tsx#2": "read-only import preview",
  "app/app/admin/matter-billing/page.tsx#1": "read-only billing profiles",
  "app/app/case-tracking/page.tsx#1": "read-only tracked case summary",
  "app/app/cause-list/page.tsx#1": "read-only cause list",
  "app/app/ip/docket/page.tsx#1": "read-only workload and capacity",
  "app/app/ip/reports/page.tsx#1": "read-only report preview columns",
  "app/app/matters/[id]/predictive-intelligence/page.tsx#2": "read-only signal distribution",
  "app/app/matters/bulk-update/page.tsx#1": "read-only preview",
  "app/app/matters/imports/page.tsx#1": "read-only import preview",
  "app/app/platform-admin/costs/page.tsx#1": "read-only operator report",
  "app/app/platform-admin/page.tsx#1": "read-only operator report",
  "app/app/platform-admin/paid-production/page.tsx#1": "read-only operator report",
  "app/app/platform-admin/paid-production/page.tsx#2": "read-only operator report",
  "app/app/platform-admin/paid-production/page.tsx#3": "read-only operator report",
  "app/app/platform-admin/paid-production/page.tsx#4": "read-only operator report",
  "app/app/platform-admin/paid-production/page.tsx#5": "read-only operator report",
  "app/app/platform-admin/paid-production/page.tsx#6": "read-only operator report",
  "app/app/platform-admin/paid-production/page.tsx#7": "read-only operator report",
  "app/app/platform-admin/profit/page.tsx#1": "read-only operator report",
  "app/app/statutes/[statute_id]/sections/[section_number]/page.tsx#1": "read-only amendment history",
  "components/platform/PlatformActivity.tsx#1": "read-only operator report",
  "components/platform/PlatformActivity.tsx#2": "read-only operator report",
  "components/platform/PlatformFinancialReport.tsx#1": "read-only operator report",
  "components/platform/PlatformLeads.tsx#1": "read-only operator report",
  // The row action is the first column, so it is on screen at every width.
  "app/app/ip/renewals/page.tsx#1": "row action is the first column",
  "app/app/matters/imports/page.tsx#2": "whole row opens the import; the first column is always on screen",
  // Known offenders in the separate platform operator console, still to fix.
  "app/app/platform-admin/forum-aliases/page.tsx#1": "KNOWN OFFENDER: operator Edit action in a 980px table",
  "app/app/platform-admin/provider-events/page.tsx#1": "KNOWN OFFENDER: operator Reprocess action in a scrolling table",
  "components/platform/PlatformAdmins.tsx#1": "KNOWN OFFENDER: operator access actions in a 40rem table",
};

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "node_modules" ? [] : sourceFiles(full);
    return /\.tsx$/.test(entry.name) && !/\.test\.tsx$/.test(entry.name) ? [full] : [];
  });
}

type Finding = { key: string; problem: string | null; interactive: boolean };

const CONTROL = /<(?:Button|Link|a|button|input|select|textarea|Select|Checkbox|Input|Textarea)\b|\bonClick=/;

/** The body of a component defined in this file, up to the next top-level declaration. */
function componentBody(source: string, name: string): string {
  const match = new RegExp(`\n(?:export )?(?:function ${name}\\b|const ${name}\\s*=)`).exec(source);
  if (!match) return "";
  const rest = source.slice(match.index + 1);
  const next = rest.slice(1).search(/\n(?:export |function |const |type |interface )/);
  return next < 0 ? rest : rest.slice(0, next + 1);
}

/** The table's own JSX plus the same-file components it renders (its rows). */
function tableWithRows(source: string, start: number): { table: string; rows: string } {
  const end = source.indexOf("</table>", start);
  const table = source.slice(start, end < 0 ? undefined : end);
  const names = new Set(Array.from(table.matchAll(/<([A-Z][A-Za-z0-9]*)\b/g), (match) => match[1]));
  return { table, rows: [...names].map((name) => componentBody(source, name)).join("\n") };
}

function classify(source: string, start: number): string | null {
  const { table: own, rows } = tableWithRows(source, start);
  const table = own + rows;
  const openTag = table.slice(0, table.indexOf(">") + 1);
  const before = source.slice(Math.max(0, start - 3000), start);
  if (/@max-\[[^\]]+\]:stacked-table\b/.test(openTag)) {
    if (!before.includes("@container")) return "stacked table without an @container parent";
    if (!/<td\b/.test(table)) return "stacked table whose cells could not be found";
    const cells = table.match(/<td\b[^>]*>/g) ?? [];
    const unlabelled = cells.filter((cell) => !/data-label=/.test(cell) && !/colSpan=/.test(cell));
    return unlabelled.length ? `${unlabelled.length} cell(s) without data-label` : null;
  }
  if (/\bstacked-table\b/.test(openTag)) return "stacked-table must be a container-query variant";
  if (/className="hidden[^"]*@min-\[[^\]]+\]:block/.test(before.slice(-300)) && before.includes("@container")) {
    return null;
  }
  if (/\bsticky (?:left|right)-0\b/.test(table)) return null;
  return "unlisted";
}

function findings(): Finding[] {
  return SOURCE_DIRS.flatMap((dir) => sourceFiles(path.join(webRoot, dir))).flatMap((file) => {
    const source = readFileSync(file, "utf8");
    const relative = path.relative(webRoot, file).split(path.sep).join("/");
    return Array.from(source.matchAll(/<table\b/g)).map((match, index) => {
      const { table, rows } = tableWithRows(source, match.index ?? 0);
      return {
        key: `${relative}#${index + 1}`,
        problem: classify(source, match.index ?? 0),
        interactive: CONTROL.test(table) || CONTROL.test(rows),
      };
    });
  });
}

describe("table rows stay reachable (B4-ADJ-13)", () => {
  it("every stacked table has a container and labels every cell", () => {
    expect(findings().filter((f) => f.problem && f.problem !== "unlisted")).toEqual([]);
  });

  it("every other table is acknowledged with its reason, exactly", () => {
    const unlisted = findings().filter((f) => f.problem === "unlisted").map((f) => f.key).sort();
    expect(unlisted).toEqual(Object.keys(ACKNOWLEDGED).sort());
  });

  it("lists a table as read-only only when neither it nor its row components holds a control", () => {
    const listedReadOnly = new Set(
      Object.entries(ACKNOWLEDGED).filter(([, reason]) => reason.startsWith("read-only")).map(([key]) => key),
    );
    const mislabelled = findings().filter((f) => listedReadOnly.has(f.key) && f.interactive).map((f) => f.key);
    expect(mislabelled).toEqual([]);
  });

  it("pins the matters list's action column through DataTable", () => {
    const table = readFileSync(path.join(webRoot, "components/ui/DataTable.tsx"), "utf8");
    expect(table).toMatch(/PINNED_CELL = "@min-\[40rem\]:sticky @min-\[40rem\]:right-0 /);
    // Below 40rem the pinned column would cover the row, so the table stacks instead.
    expect(table).toMatch(/pinLastColumn && "@max-\[40rem\]:stacked-table/);
    expect(table).toMatch(/pinLastColumn && index === cells\.length - 1 && PINNED_CELL/);
    const matters = readFileSync(path.join(webRoot, "app/app/matters/page.tsx"), "utf8");
    expect(matters).toMatch(/pinLastColumn=\{canEditMatters \|\| canArchiveMatters\}/);
  });

  it("covers the IP and billing tables the batch-4 audit named", () => {
    const reachable = new Set(findings().filter((f) => f.problem === null).map((f) => f.key));
    for (const key of [
      "app/app/ip/portfolio/page.tsx#1", "app/app/ip/portfolio/imports/page.tsx#1", "app/app/ip/watch/page.tsx#1",
      "app/app/ip/madrid/page.tsx#1", "app/app/ip/recordals/page.tsx#1", "app/app/ip/recordals/page.tsx#2",
      "app/app/ip/registry/page.tsx#1", "app/app/ip/registry/page.tsx#2", "components/ip/IpPortfolioDates.tsx#1",
      "components/ip/IpOppositionSpecializedPaths.tsx#1", "app/app/admin/billing/page.tsx#1",
      "app/app/matters/[id]/billing/page.tsx#1", "app/app/matters/[id]/documents/page.tsx#1",
      // Tables whose row actions are drawn by a row component, and the former
      // known offenders outside IP and billing.
      "app/app/admin/employees/page.tsx#1", "app/app/matters/[id]/hearings/page.tsx#1",
      "app/app/matters/[id]/knowledge-graph/page.tsx#1", "app/app/matters/[id]/predictive-intelligence/page.tsx#1",
      "app/app/imports/page.tsx#1", "app/app/matters/bulk-update/page.tsx#2",
    ]) expect(reachable.has(key), key).toBe(true);
  });
});
